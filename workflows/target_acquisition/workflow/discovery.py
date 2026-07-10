"""Target discovery: segment overviews via the analysis engine -> frame targets.

Reuses the existing cellpose analysis engine (``submit`` / ``status`` / ``results``)
for segmentation -- no reinvented segmentation. Each detected cell's pixel centroid
is converted to a frame ``(x, y)`` target here via ``overview_pixel_to_frame`` (no
calibration, no ``navigator_expert`` import); the engine is used only to find cells.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any

from ._geom import overview_pixel_to_frame

# OME PhysicalSize is µm by default (no Unit attribute); support the handful of
# length units a real native file might carry, expressed as µm-per-unit.
_UM_PER_UNIT = {
    None: 1.0,
    "µm": 1.0,
    "um": 1.0,
    "micron": 1.0,
    "micrometer": 1.0,
    "micrometre": 1.0,
    "nm": 1e-3,
    "nanometer": 1e-3,
    "nanometre": 1e-3,
    "mm": 1e3,
    "millimeter": 1e3,
    "millimetre": 1e3,
    "cm": 1e4,
    "m": 1e6,
}


def _identity_image_to_stage() -> list[list[float]]:
    """No rotation/flip: Leica records are saved stage-aligned."""
    return [[1.0, 0.0], [0.0, 1.0]]


def _physical_size_um(pixels: ET.Element, axis: str) -> float | None:
    """Read ``PhysicalSize{axis}`` (µm) off an OME ``<Pixels>`` element, or None."""
    raw = pixels.attrib.get(f"PhysicalSize{axis}")
    if raw is None:
        return None
    unit = pixels.attrib.get(f"PhysicalSize{axis}Unit")
    factor = _UM_PER_UNIT.get(unit.strip().lower() if unit else None)
    if factor is None:
        raise ValueError(f"unsupported PhysicalSize{axis}Unit {unit!r}")
    return float(raw) * factor


def read_overview_geometry(image_path: Any, *, pixel_tol: float = 1e-6) -> dict:
    """Read ``{pixel_size_um, image_size_px}`` from a saved OME-TIFF.

    The pixel grid ``image_size_px`` is ``(H, W)`` from the first page's array
    shape; ``pixel_size_um`` is the OME ``PhysicalSizeX`` (the driver writes it
    in µm, the OME default). The pipeline treats pixel size as an isotropic
    scalar, so ``PhysicalSizeX`` and ``PhysicalSizeY`` must agree within
    ``pixel_tol`` (relative); otherwise ``ValueError``.

    Driver-agnostic: reads the embedded OME-XML (TIFF tag 270) with the stdlib
    parser, no ``navigator_expert`` import. ``tifffile`` is lazy-imported.

    Raises ``ValueError`` when the OME ``<Pixels>`` element or its
    ``PhysicalSizeX``/``PhysicalSizeY`` is missing, or the pixel size is
    anisotropic.
    """
    import tifffile

    with tifffile.TiffFile(image_path) as tif:
        page = tif.pages[0]
        shape = page.shape
        desc = page.description
    h, w = int(shape[-2]), int(shape[-1])

    try:
        root = ET.fromstring(desc)
    except ET.ParseError as exc:
        raise ValueError(f"{image_path}: tag-270 OME-XML is unparseable: {exc}") from exc
    pixels = root.find(".//{*}Pixels")
    if pixels is None:
        raise ValueError(f"{image_path}: no OME <Pixels> element in tag 270")

    sx = _physical_size_um(pixels, "X")
    sy = _physical_size_um(pixels, "Y")
    if sx is None or sy is None:
        raise ValueError(f"{image_path}: OME PhysicalSizeX/Y missing")
    if abs(sx - sy) > pixel_tol * max(abs(sx), abs(sy)):
        raise ValueError(
            f"{image_path}: anisotropic pixel size (X={sx} µm, Y={sy} µm); the "
            f"pipeline treats pixel size as an isotropic scalar"
        )
    return {"pixel_size_um": float(sx), "image_size_px": (h, w)}


def build_overview_inputs(
    overview_positions: list[dict],
    image_paths: list[Any],
    *,
    pixel_size_um: float | None = None,
    image_size_px: tuple[int, int] | None = None,
    labels: list[Any] | None = None,
) -> list[dict]:
    """Pair captured overview frame positions with their saved images.

    Bridges the overview step to :func:`discover_targets`. The workflow owns
    the frame positions it captured at (``overview_positions`` -- the placed
    ``[{"x", "y", ...}]``) and, per driver, the saved image path for each
    (the driver's ``acquire`` record shape is driver-defined: the Leica adapter
    returns ``{"images": [...]}``, so ``image_paths`` is what the caller pulls
    out of each record).

    ``pixel_size_um`` / ``image_size_px`` (H, W) describe the overview job's
    geometry. Leave either as ``None`` to read it per-image from the saved
    OME-TIFF via :func:`read_overview_geometry` -- so the caller supplies
    nothing by default; pass an explicit value only to override.

    Returns the ``[{"image_path", "center_frame_um", "pixel_size_um",
    "image_size_px", "label"}]`` list :func:`discover_targets` consumes.

    Raises ``ValueError`` if the positions and image paths differ in length.
    """
    if len(overview_positions) != len(image_paths):
        raise ValueError(
            f"overview_positions ({len(overview_positions)}) and image_paths "
            f"({len(image_paths)}) must be the same length"
        )
    labels = labels if labels is not None else list(range(len(overview_positions)))
    inputs = []
    for pos, path, label in zip(overview_positions, image_paths, labels, strict=True):
        ps, sz = pixel_size_um, image_size_px
        if ps is None or sz is None:
            geo = read_overview_geometry(path)
            ps = geo["pixel_size_um"] if ps is None else ps
            sz = geo["image_size_px"] if sz is None else sz
        inputs.append(
            {
                "image_path": path,
                "center_frame_um": (float(pos["x"]), float(pos["y"])),
                "pixel_size_um": float(ps),
                "image_size_px": (int(sz[0]), int(sz[1])),
                "label": label,
            }
        )
    return inputs


def discover_targets(
    engine: Any,
    overviews: list[dict],
    *,
    feature: str = "area",
    n_picks: int | None = None,
    queue: str = "overview",
    poll_interval: float = 0.05,
) -> list[dict]:
    """Segment each overview via *engine*; return target frame positions.

    Each overview dict provides ``image_path``, ``center_frame_um`` (x, y um -- the
    frame position the overview was captured at), ``pixel_size_um``, and
    ``image_size_px`` (H, W). Submits every overview, drains the engine to
    completion, and returns ``[{"x", "y", "source": {...}}]`` frame targets.
    """
    for index, overview in enumerate(overviews):
        engine.submit(
            queue,
            {
                "image_path": str(overview["image_path"]),
                "naming_p": index,
                # smart-analysis requires a stable (region, row, col) identity.
                # The notebook's overviews are a flat ordered list.
                "tile_id": ("overview", 0, index),
                "tile_stage_xy_um": tuple(overview["center_frame_um"]),
                "tile_zwide_um": 0.0,
                "source_pixel_size_um": (
                    float(overview["pixel_size_um"]),
                    float(overview["pixel_size_um"]),
                ),
                # smart-analysis uses (width, height), while this package stores
                # image shapes as the NumPy-native (height, width).
                "source_image_size_px": (
                    int(overview["image_size_px"][1]),
                    int(overview["image_size_px"][0]),
                ),
                "image_to_stage": _identity_image_to_stage(),
                "n_picks": n_picks,
                "feature": feature,
            },
        )

    by_index = dict(enumerate(overviews))
    targets: list[dict] = []
    seen: set[int] = set()
    while True:
        status = engine.status(queue)
        for result in engine.results(queue):
            result_index = int(result["input"]["naming_p"])
            if result_index in seen:
                raise RuntimeError(f"smart-analysis returned overview {result_index} more than once")
            if result_index not in by_index:
                raise RuntimeError(f"smart-analysis returned unknown overview index {result_index}")
            seen.add(result_index)
            overview = by_index[result_index]
            for pick in result.get("pick_targets", {}).get("picks", []):
                x_um, y_um = overview_pixel_to_frame(
                    centroid_col_row_px=tuple(pick["centroid_col_row_px"]),
                    image_shape_px=tuple(overview["image_size_px"]),
                    pixel_size_um=float(overview["pixel_size_um"]),
                    image_center_frame_um=tuple(overview["center_frame_um"]),
                )
                targets.append(
                    {
                        "x": x_um,
                        "y": y_um,
                        "source": {
                            "naming_p": result_index,
                            "centroid_col_row_px": tuple(pick["centroid_col_row_px"]),
                            "area_px": pick.get("area_px"),
                            "eccentricity": pick.get("eccentricity"),
                            "mean_intensity": pick.get("mean_intensity"),
                        },
                    }
                )
        if status.get("failed", 0):
            failures = status.get("failures") or []
            details = "; ".join(
                f"{failure.get('step', 'unknown')}: {failure.get('error', 'unknown error')}"
                for failure in failures
            )
            raise RuntimeError(f"smart-analysis target discovery failed: {details}")
        if status["pending"] == 0 and status["running"] == 0:
            break
        time.sleep(poll_interval)
    missing = sorted(set(by_index) - seen)
    if missing:
        raise RuntimeError(f"smart-analysis completed without results for overviews {missing}")
    return targets
