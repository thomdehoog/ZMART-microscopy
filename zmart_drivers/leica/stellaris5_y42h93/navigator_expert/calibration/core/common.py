"""Shared helpers for calibration workflows.

Owns:

- Session folder layout (``SessionPaths``) and creation
- Job geometry parsing + non-square pixel rejection (``ImageGeometry``)
- Geometry-mismatch validator
- Move helpers that verify readback within tolerance
- Acquisition helpers that write canonical OME-TIFFs into the session
- Atomic JSON write + ISO timestamp
- Minimal magenta/green overlay and Brenner-curve plot helpers

Path-base convention (used by every workflow's save / save_and_visualize):

- Report image paths stay acquisition-relative (for example,
  ``"data/reference/calibration-frame/<plane>.ome.tiff"``).
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

from ... import orientation as _orientation
from ...acquisition.naming import Naming, run_hash
from ...commands import routines as _movement

# matplotlib is imported lazily inside the plot helpers so test imports
# (and headless environments) do not pull in a display backend on import.


# -- Constants ---------------------------------------------------------

STAGING_SCHEMA_VERSION: int = 1
MIN_FOCUS_STACK_SECTIONS: int = 5


# -- Dataclasses -------------------------------------------------------


@dataclass(frozen=True)
class SessionPaths:
    session_root: Path
    session_dir: Path
    configs_dir: Path
    reports_dir: Path
    data_dir: Path


@dataclass
class ImageGeometry:
    image_size_px: tuple[int, int]
    format_px: tuple[int, int]
    pixel_size_um: float
    pixel_w_um: float
    pixel_h_um: float


# -- Path / naming helpers ---------------------------------------------


def make_session_paths(
    session_id: str,
    sessions_root: str | Path,
    *,
    acquisition_name: str | None = None,
) -> SessionPaths:
    # absolute(), not resolve(): mapped-drive letters and symlinks stay
    # as the operator spelled them. resolve() once turned Z:\ into a UNC
    # path on the rig and broke acquisition writes.
    root = Path(sessions_root).absolute()
    session_root = root / session_id
    session_dir = session_root if acquisition_name is None else session_root / acquisition_name
    paths = SessionPaths(
        session_root=session_root,
        session_dir=session_dir,
        configs_dir=session_dir / "configs",
        reports_dir=session_dir / "reports",
        data_dir=session_dir / "data",
    )
    directories = [paths.reports_dir, paths.data_dir]
    if acquisition_name is None:
        directories.append(paths.configs_dir)
    for p in directories:
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
    settings = drv.get_job_settings(client, job_name) or {}
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
    xy = drv.get_xy(client) or {}
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
    if result.get("confirmed") is not True:
        raise RuntimeError(f"move_z zwide remained unconfirmed: {result}")


def read_selected_job_name(client: Any) -> str:
    """Return the active Navigator Expert job name."""
    selected = drv.get_selected_job(client) or {}
    job_name = str(selected.get("Name") or "").strip()
    if not job_name:
        raise RuntimeError("No Navigator Expert job is selected in LAS X.")
    return job_name


def read_active_objective(
    client: Any,
    job_name: str,
    known_names: dict[int, str] | None = None,
) -> tuple[int, str]:
    """Read the selected job's objective slot and name, changing nothing.

    Verifies the operator kept ``job_name`` selected (the calibration
    notebooks ask for the objective to be the only thing that changes
    between steps), then returns ``(slot, name)`` for the objective the
    microscope reports as active. ``known_names`` supplies a fallback
    name per slot for hardware records that omit one.
    """
    selected = drv.get_selected_job(client) or {}
    selected_name = selected.get("Name")
    if selected_name != job_name:
        raise RuntimeError(
            f"Navigator Expert job changed: expected {job_name!r}, "
            f"but {selected_name!r} is selected. Re-select {job_name!r}; "
            "change only the objective between calibration steps."
        )
    settings = drv.get_job_settings(client, job_name) or {}
    objective = settings.get("objective") or {}
    slot = objective.get("slotIndex")
    if slot is None:
        raise RuntimeError(f"could not read the active objective slot from job {job_name!r}")
    slot = int(slot)
    name = str(objective.get("name") or (known_names or {}).get(slot) or "").strip()
    if not name:
        raise RuntimeError(
            f"could not read the active objective name for slot {slot} from job {job_name!r}"
        )
    return slot, name


# -- Acquisition helper ------------------------------------------------


def acquire_frame_to(
    session: Any,
    name: str,
    *,
    orientation=None,
    backlash_passes: int | None = None,
) -> np.ndarray:
    """Acquire one frame, save into ``session.paths.data_dir``, track paths.

    Any parent directories implied by ``name`` are created as needed.
    ``orientation`` is threaded to the driver save path; ``None`` defaults
    to the rig orientation. Pass ``Orientation()`` for a raw, unreoriented
    frame (the orientation measurement acquires raw frames so it always
    measures the physical rig).
    """
    saved = _capture_for_calibration(
        session,
        name=name,
        acquisition_type="calibration-frame",
        orientation=orientation,
        backlash_passes=backlash_passes,
    )
    img = _single_plane_image(saved, context=name)
    _idx, exported_path = next(iter(saved.image_paths.items()))
    rel = str(Path(exported_path).relative_to(session.paths.session_dir)).replace("\\", "/")
    session.raw_files[name] = rel
    session.exported_files[name] = str(exported_path)
    return img


def acquire_stack_to(
    session: Any,
    dirname: str,
    *,
    orientation=None,
    backlash_passes: int | None = None,
) -> np.ndarray:
    """Trigger the operator-configured LAS X z-stack, save slices, track paths.

    The workflow never configures the stack (range, step, sections,
    direction). It only triggers the acquisition that the operator has
    already set up in LAS X and persists what comes back. The saved
    image must have shape ``(slices, H, W)``; anything else is a hard error.

    Canonical planes and metadata land below
    ``session.paths.data_dir / dirname`` and are tracked under
    acquisition-relative ``raw_files`` keys.
    ``orientation`` is threaded to the driver save path (``None`` = rig
    orientation).
    """
    saved = _capture_for_calibration(
        session,
        name=dirname,
        acquisition_type="calibration-stack",
        orientation=orientation,
        backlash_passes=backlash_passes,
    )
    arr = _stack_from_saved_planes(saved, context=dirname)
    if arr.ndim != 3:
        raise ValueError(
            f"acquire_stack expected 3-D (slices, H, W); got shape "
            f"{arr.shape!r}. The LAS X job may not be in z-stack mode, or "
            "the export produced an unexpected layout."
        )
    for i, (_idx, slice_path) in enumerate(sorted(saved.image_paths.items())):
        rel = str(Path(slice_path).relative_to(session.paths.session_dir)).replace("\\", "/")
        session.raw_files[f"{dirname}/z_{i:03d}"] = rel
    session.exported_files[dirname] = ";".join(
        str(p) for _idx, p in sorted(saved.image_paths.items())
    )
    return arr


def _capture_for_calibration(
    session: Any,
    *,
    name: str,
    acquisition_type: str,
    orientation=None,
    backlash_passes: int | None = None,
):
    """Use the public driver acquire/save workflow for calibration captures.

    When backlash_passes is provided, pin motoric XY backlash immediately
    before capture with that many jog-and-return passes. This is operational
    only: it has zero intended net displacement and is never persisted.
    """
    if orientation is None:
        orientation = _orientation.rig_orientation()
    position_label = f"{len(session.exported_files):06d}"
    naming = Naming(
        acquisition_type=acquisition_type,
        hash6=run_hash(),
        position_label=position_label,
    )
    if backlash_passes is not None:
        _movement.correct_backlash(session.client, passes=backlash_passes)
    acq = drv.acquire(session.client, session.job_name)
    return drv.save(
        session.client,
        acq,
        session.paths.data_dir / name,
        naming,
        orientation=orientation,
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
    raw = drv.get_job_settings(client, job_name)
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


def _overlay_rgb(ref_norm: np.ndarray, tgt_norm: np.ndarray) -> np.ndarray:
    """Combine two normalised images into one colour picture.

    The reference is drawn in magenta and the target in green. Where the
    two images carry the same structure the colours add up to white/grey,
    so any misalignment stands out as coloured fringes.
    """
    h = max(ref_norm.shape[0], tgt_norm.shape[0])
    w = max(ref_norm.shape[1], tgt_norm.shape[1])
    rgb = np.zeros((h, w, 3), dtype=np.float64)
    rgb[: ref_norm.shape[0], : ref_norm.shape[1], 0] = ref_norm  # magenta = R + B
    rgb[: ref_norm.shape[0], : ref_norm.shape[1], 2] = ref_norm
    rgb[: tgt_norm.shape[0], : tgt_norm.shape[1], 1] = tgt_norm  # green
    return np.clip(rgb, 0.0, 1.0)


def plot_overlay(
    ref: np.ndarray,
    tgt: np.ndarray,
    title: str,
    *,
    subtitle: str | None = None,
    corrected_target: np.ndarray | None = None,
    corrected_title: str = "Acquisition after stage correction",
):
    """Magenta = reference, green = target. Returns the matplotlib Figure.

    When *corrected_target* is given, the second panel shows that separately
    acquired image. This helper never shifts image pixels to imitate a stage
    correction.
    """
    import matplotlib.pyplot as plt

    def _norm(img: np.ndarray) -> np.ndarray:
        a = img.astype(np.float64)
        lo, hi = float(a.min()), float(a.max())
        if hi - lo < 1e-12:
            return np.zeros_like(a)
        return (a - lo) / (hi - lo)

    r = _norm(ref)
    t = _norm(tgt)

    if corrected_target is not None:
        fig, (ax, ax_corrected) = plt.subplots(1, 2, figsize=(12, 6))
    else:
        fig, ax = plt.subplots(figsize=(6, 6))

    ax.imshow(_overlay_rgb(r, t), origin="upper")
    ax.set_title(title if subtitle is None else f"{title}\n{subtitle}")
    ax.set_axis_off()

    if corrected_target is not None:
        corrected = _norm(corrected_target)
        ax_corrected.imshow(_overlay_rgb(r, corrected), origin="upper")
        ax_corrected.set_title(corrected_title)
        ax_corrected.set_axis_off()

    fig.tight_layout()
    return fig


def plot_brenner_curve(
    z_positions_um: list[float],
    scores: list[float],
    peak_z_um: float,
    *,
    focus_image: np.ndarray | None = None,
):
    """Plot Brenner score vs. z and mark the peak. Returns the Figure.

    When *focus_image* is given (the stack slice closest to the fitted
    peak), it is shown next to the curve so the operator can see the
    picture the microscope considered sharpest. That is a quick sanity
    check: the slice should look like the sample in focus, not like an
    empty field or an artifact.
    """
    import matplotlib.pyplot as plt

    if focus_image is None:
        fig, ax = plt.subplots(figsize=(9, 6))
    else:
        fig, (ax, ax_img) = plt.subplots(1, 2, figsize=(16, 7))
    ax.plot(z_positions_um, scores, marker="o")
    ax.axvline(peak_z_um, color="red", linestyle="--", label=f"peak z = {peak_z_um:.3f} um")
    ax.set_xlabel("z-wide (um, absolute)")
    ax.set_ylabel("Brenner Gradient Score")
    ax.set_title("Software Autofocus")
    ax.legend(loc="best")
    if focus_image is not None:
        ax_img.imshow(focus_image, cmap="gray", origin="upper")
        ax_img.set_title(f"Focus positions (Z = {peak_z_um:.2f} µm)")
        ax_img.set_axis_off()
    fig.tight_layout()
    return fig
