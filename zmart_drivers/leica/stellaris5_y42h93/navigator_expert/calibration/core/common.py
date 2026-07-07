"""Shared helpers for calibration workflows.

Owns:

- Session folder layout (``SessionPaths``) and creation
- Job geometry parsing + non-square pixel rejection (``ImageGeometry``)
- Geometry-mismatch validator
- Move helpers that verify readback within tolerance
- Frame-acquire helper that writes raw TIFFs into the session
- Atomic JSON write + ISO timestamp
- Minimal magenta/green overlay and Brenner-curve plot helpers

Path-base convention (used by every workflow's save / save_and_visualize):

- Report image paths under ``images:`` and ``figures:`` stay
  session-root-relative (e.g. ``"data/<kind>/home.tif"``). A report JSON
  already carries the session_id, so the prefix would be redundant.
- Summary dicts returned to the notebook and adoption return paths use
  absolute strings; ``sessions_root`` lives outside the package tree so
  there is no meaningful package-relative form.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import tifffile

import navigator_expert as drv
from shared.output_layout import Naming, run_hash

# matplotlib is imported lazily inside the plot helpers so test imports
# (and headless environments) do not pull in a display backend on import.


# -- Constants ---------------------------------------------------------

STAGING_SCHEMA_VERSION: int = 1
MIN_FOCUS_STACK_SECTIONS: int = 5


# -- Dataclasses -------------------------------------------------------


@dataclass(frozen=True)
class SessionPaths:
    session_dir: Path
    configs_dir: Path
    reports_dir: Path
    notebooks_dir: Path
    data_dir: Path


@dataclass
class ImageGeometry:
    image_size_px: tuple[int, int]
    format_px: tuple[int, int]
    pixel_size_um: float
    pixel_w_um: float
    pixel_h_um: float


# -- Path / naming helpers ---------------------------------------------


def slug(value: str) -> str:
    """Filesystem-safe objective label.

    '10x' -> '10x', '100x oil' -> '100x_oil', '0.5x' -> '0p5x'.
    """
    return value.strip().replace(" ", "_").replace("/", "_").replace("\\", "_").replace(".", "p")


def objective_config_name(from_objective: str, to_objective: str) -> str:
    return f"objective_{slug(from_objective)}_to_{slug(to_objective)}.json"


def make_session_paths(
    session_id: str,
    kind: str,
    sessions_root: str | Path,
) -> SessionPaths:
    # absolute(), not resolve(): mapped-drive letters and symlinks stay
    # as the operator spelled them. resolve() once turned Z:\ into a UNC
    # path on the rig and broke acquisition writes.
    root = Path(sessions_root).absolute()
    session_dir = root / session_id
    paths = SessionPaths(
        session_dir=session_dir,
        configs_dir=session_dir / "configs",
        reports_dir=session_dir / "reports",
        notebooks_dir=session_dir / "notebooks",
        data_dir=session_dir / "data" / kind,
    )
    for p in (paths.configs_dir, paths.reports_dir, paths.notebooks_dir, paths.data_dir):
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(f"cannot create calibration session directory {p}: {exc}") from exc
    return paths


# -- Job geometry ------------------------------------------------------


def read_job_geometry(
    client: Any,
    job_name: str,
    image: np.ndarray | None = None,
) -> ImageGeometry:
    """Read pixel size + image format from LAS X; reject non-square pixels.

    If ``image`` is provided, its ``shape[-2:]`` populates ``image_size_px``;
    otherwise ``image_size_px`` falls back to the LAS X format.
    """
    # Calibration geometry is a persisted correctness artifact. Use the
    # authoritative API reader, not the passive state-reader profile.
    settings = drv.get_job_settings(client, job_name, mode="api") or {}
    geom = drv.parse_tile_geometry(settings)
    if geom is None or geom.get("pixel_w_um") is None or geom.get("pixels_x") is None:
        raise ValueError(
            f"job settings for '{job_name}' are missing pixel size / image "
            f"format metadata (imageSize/format unparseable or absent)"
        )
    pixel_w = float(geom["pixel_w_um"])
    pixel_h = float(geom["pixel_h_um"])
    if not np.isclose(pixel_w, pixel_h, rtol=0, atol=1e-9):
        raise ValueError(
            f"non-square pixels are not supported in v1 "
            f"(pixel_w_um={pixel_w}, pixel_h_um={pixel_h})"
        )
    format_px = (int(geom["pixels_y"]), int(geom["pixels_x"]))
    if image is not None:
        h, w = image.shape[-2:]
        image_size_px = (int(h), int(w))
    else:
        image_size_px = format_px
    return ImageGeometry(
        image_size_px=image_size_px,
        format_px=format_px,
        pixel_size_um=pixel_w,
        pixel_w_um=pixel_w,
        pixel_h_um=pixel_h,
    )


def assert_geometry_matches(
    actual: ImageGeometry,
    expected_size_px: tuple[int, int],
    expected_pixel_size_um: float,
    *,
    context: str,
) -> None:
    if tuple(actual.image_size_px) != tuple(expected_size_px):
        raise ValueError(
            f"{context}: image size mismatch "
            f"({tuple(actual.image_size_px)} vs {tuple(expected_size_px)})"
        )
    if not np.isclose(actual.pixel_size_um, expected_pixel_size_um, rtol=0, atol=1e-9):
        raise ValueError(
            f"{context}: pixel size mismatch ({actual.pixel_size_um} vs {expected_pixel_size_um})"
        )


# -- Move helpers ------------------------------------------------------


def move_xy_and_verify(
    client: Any,
    x_um: float,
    y_um: float,
    *,
    settle_s: float = 0.5,
    tolerance_um: float = 0.5,
) -> None:
    result = drv.move_xy(client, x_um, y_um, unit="um", tolerance=tolerance_um)
    if not result or not result.get("success"):
        raise RuntimeError(f"move_xy failed: {result}")
    if settle_s > 0:
        time.sleep(settle_s)
    xy = drv.get_xy(client, mode="api") or {}
    if ("x_um" not in xy) or ("y_um" not in xy):
        raise RuntimeError(f"get_xy returned no readback: {xy}")
    if abs(xy["x_um"] - x_um) > tolerance_um or abs(xy["y_um"] - y_um) > tolerance_um:
        raise RuntimeError(
            f"stage readback outside tolerance: requested "
            f"({x_um}, {y_um}), got ({xy['x_um']}, {xy['y_um']})"
        )


def move_zwide_and_verify(
    client: Any,
    job_name: str,
    z_um: float,
    *,
    tolerance_um: float = 1.0,
) -> None:
    result = drv.move_z(client, job_name, z_um, unit="um", z_mode="zwide", tolerance=tolerance_um)
    if not result or not result.get("success"):
        raise RuntimeError(f"move_z zwide failed: {result}")
    actual = drv.read_zwide_um(client, job_name, mode="api")
    if actual is None:
        raise RuntimeError(f"z-wide readback unavailable for job '{job_name}'")
    if abs(actual - z_um) > tolerance_um:
        raise RuntimeError(f"z-wide readback outside tolerance: requested {z_um}, got {actual}")


def zero_z_galvo(client: Any, job_name: str) -> None:
    result = drv.move_z(client, job_name, 0.0, unit="um", z_mode="galvo")
    if not result or not result.get("success"):
        raise RuntimeError(f"move_z galvo zero failed: {result}")


# -- Acquisition helper ------------------------------------------------


def acquire_frame_to(session: Any, name: str) -> np.ndarray:
    """Acquire one frame, save into ``session.paths.data_dir``, track paths.

    Any parent directories implied by ``name`` are created as needed.
    """
    saved = _capture_for_calibration(
        session,
        acquisition_type="calibration-frame",
    )
    img = _single_plane_image(saved, context=name)
    out = session.paths.data_dir / f"{name}.tif"
    out.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(out, img)
    rel = str(out.relative_to(session.paths.session_dir)).replace("\\", "/")
    session.raw_files[name] = rel
    _idx, exported_path = next(iter(saved.image_paths.items()))
    session.exported_files[name] = str(exported_path)
    return img


def acquire_stack_to(session: Any, dirname: str) -> np.ndarray:
    """Trigger the operator-configured LAS X z-stack, save slices, track paths.

    The workflow never configures the stack (range, step, sections,
    direction). It only triggers the acquisition that the operator has
    already set up in LAS X and persists what comes back. The saved
    image must have shape ``(slices, H, W)``; anything else is a hard error.

    Slices land in ``session.paths.data_dir / dirname / z_<index>.tif``
    and are tracked under session-root-relative ``raw_files`` keys.
    """
    saved = _capture_for_calibration(
        session,
        acquisition_type="calibration-stack",
    )
    arr = _stack_from_saved_planes(saved, context=dirname)
    if arr.ndim != 3:
        raise ValueError(
            f"acquire_stack expected 3-D (slices, H, W); got shape "
            f"{arr.shape!r}. The LAS X job may not be in z-stack mode, or "
            "the export produced an unexpected layout."
        )
    out_dir = session.paths.data_dir / dirname
    out_dir.mkdir(parents=True, exist_ok=True)
    for i in range(arr.shape[0]):
        slice_path = out_dir / f"z_{i:03d}.tif"
        tifffile.imwrite(slice_path, arr[i])
        rel = str(slice_path.relative_to(session.paths.session_dir)).replace("\\", "/")
        session.raw_files[f"{dirname}/z_{i:03d}"] = rel
    session.exported_files[dirname] = ";".join(
        str(p) for _idx, p in sorted(saved.image_paths.items())
    )
    return arr


def _capture_for_calibration(
    session: Any,
    *,
    acquisition_type: str,
):
    """Use the public driver acquire/save workflow for calibration captures."""
    position_label = f"{len(session.exported_files):06d}"
    naming = Naming(
        acquisition_type=acquisition_type,
        hash6=run_hash(),
        position_label=position_label,
    )
    acq = drv.acquire(session.client, session.job_name)
    return drv.save(
        session.client,
        acq,
        session.paths.session_dir / "driver-save",
        naming,
    )


def _single_plane_image(saved: Any, *, context: str) -> np.ndarray:
    if len(saved.image_paths) != 1:
        raise ValueError(f"{context} expected one saved plane; got {len(saved.image_paths)}")
    _idx, path = next(iter(saved.image_paths.items()))
    img = np.asarray(tifffile.imread(path))
    if img.ndim == 3 and img.shape[0] == 1:
        img = img[0]
    if img.ndim != 2:
        raise ValueError(f"{context} expected 2-D image; got shape {img.shape!r}")
    return img


def _stack_from_saved_planes(saved: Any, *, context: str) -> np.ndarray:
    if not saved.image_paths:
        raise ValueError(f"{context} saved no image planes")
    channels = sorted({idx.c for idx in saved.image_paths})
    times = sorted({idx.t for idx in saved.image_paths})
    if len(channels) != 1 or len(times) != 1:
        raise ValueError(
            f"{context} expected one channel and one timepoint; "
            f"got channels={channels}, times={times}"
        )
    planes = [
        (idx.z, path)
        for idx, path in saved.image_paths.items()
        if idx.c == channels[0] and idx.t == times[0]
    ]
    arr = np.asarray([tifffile.imread(path) for _z, path in sorted(planes)])
    return arr


def read_stack_z_positions(
    client: Any,
    job_name: str,
    expected_slices: int,
    *,
    override: list[float] | None = None,
) -> list[float]:
    """Return absolute z-wide positions matching the slice order of a stack.

    The workflow never derives positions from slice count alone. If
    ``override`` is supplied it is used as-is (validated). Otherwise
    LAS X job settings are read and the ``stack`` block must carry
    ``begin``, ``end``, and ``sections``; positions are then
    ``np.linspace(begin, end, sections)``, which preserves reversed
    stacks (``begin > end``). When a ``zDrive`` / ``mode`` field is
    present it is validated. ``stepSize`` is informational only and is
    not validated -- LAS X rounds it for display, so cross-checking it
    against the derived step trips on vendor noise.
    """
    if override is not None:
        if len(override) != expected_slices:
            raise ValueError(
                f"override z_positions_um has length {len(override)}, "
                f"expected {expected_slices} (one per acquired slice)."
            )
        if len(override) < MIN_FOCUS_STACK_SECTIONS:
            raise ValueError(
                f"z-stack must have at least {MIN_FOCUS_STACK_SECTIONS} "
                "positions for the trimmed parabolic "
                f"peak refinement; override has {len(override)}."
            )
        return [float(z) for z in override]

    # Z-stack positions are persisted calibration geometry. Use the
    # authoritative API reader, not the passive state-reader profile.
    raw = drv.get_job_settings(client, job_name, mode="api")
    if not raw:
        raise RuntimeError(
            f"Could not read job settings for job {job_name!r}; cannot "
            "derive z-stack positions. Pass z_positions_um=[...] if you "
            "need to override."
        )

    stack: dict | None = None
    try:
        normalized = drv.make_changeable_copy(raw)
    except Exception:
        normalized = None
    if normalized and isinstance(normalized.get("stack"), dict):
        stack = normalized["stack"]
    # Fall back to raw stack metadata if the normalized block is
    # missing OR partial -- any of begin/end/sections being None
    # forces a re-read from the raw settings, where the partial
    # normalized fields may have full counterparts.
    _required = ("begin", "end", "sections")
    if not stack or any(stack.get(k) is None for k in _required):
        raw_stack = raw.get("stack")
        if isinstance(raw_stack, dict):
            stack = {
                "begin": raw_stack.get("begin"),
                "end": raw_stack.get("end"),
                "sections": raw_stack.get("sections"),
                "zDrive": raw_stack.get("mode") or raw_stack.get("zDrive"),
            }

    if not stack:
        raise RuntimeError(
            "No z-stack metadata in LAS X job settings. Configure a "
            "z-stack in LAS X, or pass z_positions_um=[...] to override."
        )

    begin = stack.get("begin")
    end = stack.get("end")
    sections = stack.get("sections")
    if begin is None or end is None or sections is None:
        raise RuntimeError(
            "z-stack metadata is missing begin/end/sections "
            f"(got begin={begin!r}, end={end!r}, sections={sections!r}). "
            "Re-check the LAS X stack configuration."
        )

    try:
        sections_int = int(sections)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"z-stack sections {sections!r} is not an integer.") from exc

    if sections_int != expected_slices:
        raise RuntimeError(
            f"z-stack metadata sections={sections_int} does not match the "
            f"{expected_slices} slices returned by acquire_stack. Re-check "
            "the LAS X stack configuration."
        )
    if sections_int < MIN_FOCUS_STACK_SECTIONS:
        raise RuntimeError(
            f"z-stack must have at least {MIN_FOCUS_STACK_SECTIONS} slices "
            "for trimmed parabolic peak refinement; LAS X reports "
            f"sections={sections_int}. Increase the stack sections in LAS X."
        )

    z_drive = stack.get("zDrive")
    if z_drive is not None:
        if "wide" not in str(z_drive).lower():
            raise RuntimeError(
                f"Calibration requires z-wide stacks; LAS X reports "
                f"zDrive={z_drive!r}. Reconfigure the stack drive in LAS X."
            )

    # begin/end/sections are authoritative; np.linspace reproduces the
    # rig's z-wide positions to full float precision. stepSize is
    # informational only and is not validated here -- LAS X rounds it
    # for display, and a cross-check tripped on vendor noise (2.051
    # reported vs 2.05077 derived) without protecting anything real.
    begin_f = float(begin)
    end_f = float(end)
    positions = np.linspace(begin_f, end_f, sections_int)
    return [float(z) for z in positions]


# -- JSON I/O ----------------------------------------------------------


def write_json_atomic(path: Path, payload: dict) -> None:
    """Atomic JSON write. ``allow_nan=False`` so NaN/inf never reach disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# -- Visualization helpers --------------------------------------------


def plot_overlay(
    ref: np.ndarray,
    tgt: np.ndarray,
    title: str,
    *,
    shift_um: tuple[float, float] | None = None,
    pixel_size_um: float | None = None,
):
    """Magenta = reference, green = target. Returns the matplotlib Figure."""
    import matplotlib.pyplot as plt

    def _norm(img: np.ndarray) -> np.ndarray:
        a = img.astype(np.float64)
        lo, hi = float(a.min()), float(a.max())
        if hi - lo < 1e-12:
            return np.zeros_like(a)
        return (a - lo) / (hi - lo)

    r = _norm(ref)
    t = _norm(tgt)
    h = max(r.shape[0], t.shape[0])
    w = max(r.shape[1], t.shape[1])
    rgb = np.zeros((h, w, 3), dtype=np.float64)
    rgb[: r.shape[0], : r.shape[1], 0] = r  # magenta = R + B
    rgb[: r.shape[0], : r.shape[1], 2] = r
    rgb[: t.shape[0], : t.shape[1], 1] = t  # green
    rgb = np.clip(rgb, 0.0, 1.0)

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.imshow(rgb, origin="upper")
    subtitle = title
    # shift_um may be a 2-tuple of floats, or a 2-tuple containing
    # None when registration was untrusted; skip the annotation in
    # that case rather than format-erroring.
    has_shift = shift_um is not None and shift_um[0] is not None and shift_um[1] is not None
    if has_shift and pixel_size_um is not None:
        subtitle += (
            f"\nimage shift: ({shift_um[0]:+.2f}, {shift_um[1]:+.2f}) um"
            f"  (pixel_size_um={pixel_size_um:g})"
        )
    elif has_shift:
        subtitle += f"\nimage shift: ({shift_um[0]:+.2f}, {shift_um[1]:+.2f}) um"
    ax.set_title(subtitle)
    ax.set_axis_off()
    fig.tight_layout()
    return fig


def plot_brenner_curve(
    z_positions_um: list[float],
    scores: list[float],
    peak_z_um: float,
):
    """Plot Brenner score vs. z and mark the peak. Returns the Figure."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(z_positions_um, scores, marker="o")
    ax.axvline(peak_z_um, color="red", linestyle="--", label=f"peak z = {peak_z_um:.3f} um")
    ax.set_xlabel("z-wide (um, absolute)")
    ax.set_ylabel("Brenner score")
    ax.set_title("Parfocality Brenner curve")
    ax.legend(loc="best")
    fig.tight_layout()
    return fig


# -- Image-to-stage review diagnostics --------------------------------
#
# These helpers are display- and diagnostic-only. They never run a
# driver call, never modify session state, and never write JSON or
# staging configs. PNG output is the caller's responsibility (Step 3's
# save path); the helpers only return Figure objects.


def shift_image_no_wrap(
    image: np.ndarray,
    *,
    dx_px: float,
    dy_px: float,
) -> np.ndarray:
    """Shift image content for display alignment only.

    ``dx_px`` is along the column axis (image x). ``dy_px`` is along
    the row axis (image y). Areas exposed by the shift fill with 0.0
    rather than wrapping -- ``np.roll`` would create false edge
    content that misleads the operator's eye when comparing overlays.
    """
    from scipy.ndimage import shift as ndi_shift

    return ndi_shift(
        image.astype(np.float64),
        shift=(float(dy_px), float(dx_px)),
        order=1,
        mode="constant",
        cval=0.0,
    )


def compute_d4_candidate_residuals(
    measured_plus_x_um: tuple[float, float],
    measured_plus_y_um: tuple[float, float],
    stage_move_um: float,
) -> list[dict]:
    """Score every D4 candidate against the measured image shifts.

    For each labeled candidate matrix, predicts the image displacement
    that would result from a +X / +Y stage move using the workflow's
    sign convention::

        pred_image_disp_um = -inv(candidate) @ stage_disp_um

    and returns the per-candidate row residuals plus the combined
    Frobenius-style residual. Pure function (no Figure, no I/O), so
    the same scoring drives both ``plot_d4_candidates`` and the unit
    tests that pin the sign convention.

    Returns a list of dicts in stable ``D4_ELEMENTS`` order with keys:

    - ``label``: D4 label (e.g. ``"-Y +X"``).
    - ``candidate``: 2x2 numpy array.
    - ``pred_plus_x_um`` / ``pred_plus_y_um``: predicted image-um shifts.
    - ``residual_plus_x_um`` / ``residual_plus_y_um``: per-row L2 errors.
    - ``residual_um``: combined row residual.
    """
    from shared.algorithms import D4_ELEMENTS

    measured_x = np.asarray(measured_plus_x_um, dtype=float)
    measured_y = np.asarray(measured_plus_y_um, dtype=float)
    stage_plus_x = np.array([float(stage_move_um), 0.0])
    stage_plus_y = np.array([0.0, float(stage_move_um)])

    rows: list[dict] = []
    for label, candidate in D4_ELEMENTS.items():
        c = np.asarray(candidate, dtype=float)
        try:
            inv = np.linalg.inv(c)
        except np.linalg.LinAlgError:
            rows.append(
                {
                    "label": label,
                    "candidate": c,
                    "pred_plus_x_um": None,
                    "pred_plus_y_um": None,
                    "residual_plus_x_um": float("inf"),
                    "residual_plus_y_um": float("inf"),
                    "residual_um": float("inf"),
                }
            )
            continue
        pred_x = -inv @ stage_plus_x
        pred_y = -inv @ stage_plus_y
        rx = float(np.linalg.norm(measured_x - pred_x))
        ry = float(np.linalg.norm(measured_y - pred_y))
        rows.append(
            {
                "label": label,
                "candidate": c,
                "pred_plus_x_um": (float(pred_x[0]), float(pred_x[1])),
                "pred_plus_y_um": (float(pred_y[0]), float(pred_y[1])),
                "residual_plus_x_um": rx,
                "residual_plus_y_um": ry,
                "residual_um": float(np.hypot(rx, ry)),
            }
        )
    return rows


def plot_raw_triplet(
    home: np.ndarray,
    plus_x: np.ndarray,
    plus_y: np.ndarray,
    title: str,
):
    """1x3 grayscale panel: home, +X, +Y. Display-only."""
    import matplotlib.pyplot as plt

    def _norm(img: np.ndarray) -> np.ndarray:
        a = img.astype(np.float64)
        lo, hi = float(a.min()), float(a.max())
        if hi - lo < 1e-12:
            return np.zeros_like(a)
        return (a - lo) / (hi - lo)

    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    for ax, img, label in zip(
        axes,
        (home, plus_x, plus_y),
        ("home", "+X", "+Y"),
        strict=False,
    ):
        ax.imshow(_norm(img), cmap="gray", origin="upper")
        ax.set_title(label)
        ax.set_axis_off()
    fig.suptitle(title)
    fig.tight_layout()
    return fig


ROTATION_LABELS_IN_DISPLAY_ORDER: tuple[str, ...] = (
    "+X +Y",
    "-Y +X",
    "-X -Y",
    "+Y -X",
)


def _is_rotation_label(label: str | None) -> bool:
    """True when ``label`` names a determinant +1 D4 element."""
    return label is not None and label in ROTATION_LABELS_IN_DISPLAY_ORDER


def plot_d4_candidates(
    home: np.ndarray,
    plus_x: np.ndarray,
    plus_y: np.ndarray,
    *,
    stage_move_um: float,
    pixel_size_um: float,
    measured_plus_x_um: tuple[float | None, float | None],
    measured_plus_y_um: tuple[float | None, float | None],
    selected_label: str | None,
    d4_accepted: bool | None,
    failure_reason: str | None = None,
    title: str = "D4 candidate correction check",
):
    """Rotation-only 1x4 grouped grid.

    For each of the four determinant +1 D4 candidates (the rotations
    +X+Y, -Y+X, -X-Y, +Y-X, in that order), render one tile that
    stacks the corrected +X overlay on top and the corrected +Y
    overlay below. Each tile lives in its own ``Matplotlib`` SubFigure.
    The winner is named in the global suptitle; no additional border or
    background is drawn -- the visual signal is the clean grayscale
    alignment in the winning tile vs the magenta/green ghosting in the
    losing tiles.

    The math still considers all eight D4 candidates upstream
    (``compute_d4_candidate_residuals`` enumerates them). Reflections
    are filtered out of the operator view; ``measure()`` is responsible
    for rejecting reflection-best fits before this plotter ever runs.
    The global suptitle is one line and reflects workflow state:

    - ``Winner: <label> (rotation)`` when ``selected_label`` is a
      rotation and ``d4_accepted`` is True.
    - ``REFLECTION REJECTED -- reflection-free workflow`` when
      ``failure_reason`` flags a reflection.
    - ``NO WINNER -- D4 residual too high`` when ``d4_accepted`` is
      False on a rotation candidate.
    - ``SINGULAR FIT -- D4 not evaluated`` when ``failure_reason``
      flags a singular fit.
    - ``NO WINNER -- vote untrusted`` otherwise.
    """
    import matplotlib.pyplot as plt

    def _norm(img: np.ndarray) -> np.ndarray:
        a = img.astype(np.float64)
        lo, hi = float(a.min()), float(a.max())
        if hi - lo < 1e-12:
            return np.zeros_like(a)
        return (a - lo) / (hi - lo)

    def _overlay(home_norm: np.ndarray, moved_norm: np.ndarray) -> np.ndarray:
        h = max(home_norm.shape[0], moved_norm.shape[0])
        w = max(home_norm.shape[1], moved_norm.shape[1])
        rgb = np.zeros((h, w, 3), dtype=np.float64)
        rgb[: home_norm.shape[0], : home_norm.shape[1], 0] = home_norm
        rgb[: home_norm.shape[0], : home_norm.shape[1], 2] = home_norm
        rgb[: moved_norm.shape[0], : moved_norm.shape[1], 1] = moved_norm
        return np.clip(rgb, 0.0, 1.0)

    def _finite_pair(t) -> bool:
        # Treat NaN / inf exactly like None so weak-vote diagnostics
        # never display "+X resid nan um".
        if t is None:
            return False
        a, b = t
        if a is None or b is None:
            return False
        try:
            return np.isfinite(float(a)) and np.isfinite(float(b))
        except (TypeError, ValueError):
            return False

    measured_x_known = _finite_pair(measured_plus_x_um)
    measured_y_known = _finite_pair(measured_plus_y_um)
    all_rows = compute_d4_candidate_residuals(
        measured_plus_x_um=(
            (float(measured_plus_x_um[0]), float(measured_plus_x_um[1]))
            if measured_x_known
            else (0.0, 0.0)
        ),
        measured_plus_y_um=(
            (float(measured_plus_y_um[0]), float(measured_plus_y_um[1]))
            if measured_y_known
            else (0.0, 0.0)
        ),
        stage_move_um=stage_move_um,
    )
    by_label = {r["label"]: r for r in all_rows}
    rotation_rows = [by_label[lbl] for lbl in ROTATION_LABELS_IN_DISPLAY_ORDER]

    home_norm = _norm(home)
    plus_x_norm = _norm(plus_x)
    plus_y_norm = _norm(plus_y)

    show_winner = _is_rotation_label(selected_label) and (d4_accepted is True)

    n_cols = len(rotation_rows)
    fig = plt.figure(figsize=(12, 6))
    subfigs = fig.subfigures(1, n_cols, wspace=0.03)
    if n_cols == 1:
        subfigs = np.array([subfigs])

    for col, row in enumerate(rotation_rows):
        sub = subfigs[col]
        label = row["label"]
        pred_x = row["pred_plus_x_um"] or (0.0, 0.0)
        pred_y = row["pred_plus_y_um"] or (0.0, 0.0)

        if measured_x_known:
            x_resid = f"+X {row['residual_plus_x_um']:.1f} um"
        else:
            x_resid = "+X (no measurement)"
        if measured_y_known:
            y_resid = f"+Y {row['residual_plus_y_um']:.1f} um"
        else:
            y_resid = "+Y (no measurement)"
        sub.suptitle(
            f"{label}\n{x_resid}  |  {y_resid}",
            fontsize=12,
            fontweight="bold",
            y=0.85,
        )

        dx_px_x = -pred_x[0] / pixel_size_um
        dy_px_x = -pred_x[1] / pixel_size_um
        corrected_x = shift_image_no_wrap(
            plus_x_norm,
            dx_px=dx_px_x,
            dy_px=dy_px_x,
        )
        dx_px_y = -pred_y[0] / pixel_size_um
        dy_px_y = -pred_y[1] / pixel_size_um
        corrected_y = shift_image_no_wrap(
            plus_y_norm,
            dx_px=dx_px_y,
            dy_px=dy_px_y,
        )

        axes = sub.subplots(
            2,
            1,
            gridspec_kw={
                "top": 0.75,
                "bottom": 0.02,
                "left": 0.06,
                "right": 0.98,
                "hspace": 0.04,
            },
        )
        axes[0].imshow(_overlay(home_norm, corrected_x), origin="upper")
        axes[1].imshow(_overlay(home_norm, corrected_y), origin="upper")
        # Inner axes carry no titles. Drop tick marks but keep the
        # leftmost column's y-labels so the operator can tell which
        # row is the +X correction and which is the +Y correction.
        for ax in axes:
            ax.set_xticks([])
            ax.set_yticks([])
        if col == 0:
            axes[0].set_ylabel("+X", fontsize=14, fontweight="bold")
            axes[1].set_ylabel("+Y", fontsize=14, fontweight="bold")

    # Compose the global suptitle from workflow state. One line; do
    # not append residuals -- those live in each tile title.
    is_reflection_reason = failure_reason is not None and "reflection-free" in failure_reason
    is_singular_reason = failure_reason is not None and "singular" in failure_reason
    if show_winner:
        suptitle = f"Winner: {selected_label} (rotation)"
    elif is_reflection_reason:
        suptitle = "REFLECTION REJECTED -- reflection-free workflow"
    elif is_singular_reason:
        suptitle = "SINGULAR FIT -- D4 not evaluated"
    elif d4_accepted is False:
        suptitle = "NO WINNER -- D4 residual too high"
    elif not measured_x_known or not measured_y_known:
        suptitle = "NO WINNER -- vote untrusted"
    elif d4_accepted is None:
        suptitle = "NO WINNER -- D4 not evaluated"
    else:
        suptitle = "NO WINNER"
    # Pin the global title above the per-tile suptitle band so the two
    # text rows don't share vertical space. Without an explicit y the
    # default places the global title in the same band as the
    # subfigure suptitles and the operator sees overlapping text.
    fig.suptitle(suptitle, y=0.95, fontsize=16, fontweight="bold")

    return fig
