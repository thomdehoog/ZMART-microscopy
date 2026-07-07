"""Target discovery: segment overviews via the analysis engine -> frame targets.

Reuses the existing cellpose analysis engine (``submit`` / ``status`` / ``results``)
for segmentation -- no reinvented segmentation. Each detected cell's pixel centroid
is converted to a frame ``(x, y)`` target here via ``overview_pixel_to_frame`` (no
calibration, no ``navigator_expert`` import); the engine is used only to find cells.
"""

from __future__ import annotations

import time
from typing import Any

from ._geom import overview_pixel_to_frame


def _identity_image_to_stage(pixel_size_um: float) -> list[list[float]]:
    """A 2x2 pixel->um matrix with no rotation/flip (isotropic pixel size)."""
    size = float(pixel_size_um)
    return [[size, 0.0], [0.0, size]]


def build_overview_inputs(
    overview_positions: list[dict],
    image_paths: list[Any],
    *,
    pixel_size_um: float,
    image_size_px: tuple[int, int],
    labels: list[Any] | None = None,
) -> list[dict]:
    """Pair captured overview frame positions with their saved images.

    Bridges the overview step to :func:`discover_targets`. The workflow owns
    the frame positions it captured at (``overview_positions`` -- the placed
    ``[{"x", "y", ...}]``) and, per driver, the saved image path for each
    (the driver's ``acquire`` record shape is driver-defined: the Leica adapter
    returns ``{"images": [...]}``, so ``image_paths`` is what the caller pulls
    out of each record). ``pixel_size_um`` / ``image_size_px`` (H, W) describe
    the overview job's geometry, shared by every tile.

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
    return [
        {
            "image_path": path,
            "center_frame_um": (float(pos["x"]), float(pos["y"])),
            "pixel_size_um": float(pixel_size_um),
            "image_size_px": (int(image_size_px[0]), int(image_size_px[1])),
            "label": label,
        }
        for pos, path, label in zip(overview_positions, image_paths, labels, strict=True)
    ]


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
                "tile_id": overview.get("label", index),
                "tile_stage_xy_um": tuple(overview["center_frame_um"]),
                "tile_zwide_um": 0.0,
                "source_pixel_size_um": float(overview["pixel_size_um"]),
                "source_image_size_px": tuple(overview["image_size_px"]),
                "image_to_stage": _identity_image_to_stage(overview["pixel_size_um"]),
                "n_picks": n_picks,
                "feature": feature,
            },
        )

    by_index = dict(enumerate(overviews))
    targets: list[dict] = []
    while True:
        status = engine.status(queue)
        for result in engine.results(queue):
            overview = by_index[result["input"]["naming_p"]]
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
                            "naming_p": result["input"]["naming_p"],
                            "centroid_col_row_px": tuple(pick["centroid_col_row_px"]),
                            "area_px": pick.get("area_px"),
                            "mean_intensity": pick.get("mean_intensity"),
                        },
                    }
                )
        if status["pending"] == 0 and status["running"] == 0:
            break
        time.sleep(poll_interval)
    return targets
