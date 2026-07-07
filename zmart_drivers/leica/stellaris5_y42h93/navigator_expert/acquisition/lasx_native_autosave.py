"""Collect files produced by LAS X native AutoSave.

Native AutoSave writes into a LAS X project folder. The observed
product is one multipage OME-TIFF per acquisition with embedded OME-XML
plus XLEF/XLIF project metadata. This module only maps that source product to the
writer-agnostic acquisition contract; persistence stays in ``save``.
"""

from __future__ import annotations

import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import files as _files
from . import ome_canonical as _canonical
from .capture import AcquisitionResult
from .files import (
    DEFAULT_EXPORT_COMPLETION_POLL_INTERVAL_S,
    DEFAULT_EXPORT_COMPLETION_TIMEOUT_S,
    DEFAULT_FILE_STABILITY_TIMEOUT_S,
    _is_from_acquisition,
)
from .product import (
    ExportedAcquisition,
    ExportedPosition,
    PlaneIndex,
    PlaneSource,
    VendorMetadataSource,
)

log = logging.getLogger(__name__)

_PROJECT_CONFIG_NAME = "IOManagerConfiguation.xlif"

# How often to log a heartbeat while waiting (without a deadline) for AutoSave
# to flush a detected project's OME-TIFF.
_FLUSH_HEARTBEAT_S = 30.0


@dataclass(frozen=True)
class _NativeAutoSaveConfig:
    base_folder: Path
    use_autosave: bool
    store_separate_folders: bool
    lcf_path: Path


def collect_lasx_native_autosave(
    client: Any,
    acq: AcquisitionResult,
    *,
    file_stability_timeout_s: int = DEFAULT_FILE_STABILITY_TIMEOUT_S,
    export_completion_timeout: float = DEFAULT_EXPORT_COMPLETION_TIMEOUT_S,
    export_completion_poll_interval: float = (DEFAULT_EXPORT_COMPLETION_POLL_INTERVAL_S),
    autosave_root: str | Path | None = None,
    lcf_path: str | Path | None = None,
) -> ExportedAcquisition:
    """Return stable source refs from LAS X native AutoSave for *acq*."""
    config = _read_native_autosave_config(lcf_path=lcf_path)
    if not config.use_autosave:
        raise RuntimeError(
            "LAS X native AutoSave is not enabled in the active StartUp "
            f"configuration: {config.lcf_path}"
        )
    base = Path(autosave_root) if autosave_root is not None else config.base_folder

    anchor = _detect_from_relative_path(client, base, acq)
    method = "relative_path"
    if anchor is None:
        anchor = _detect_from_mtime(
            base,
            acq,
            detect_timeout=export_completion_timeout,
            poll_interval=export_completion_poll_interval,
        )
        method = "mtime"

    stability = _files.wait_all_stable(
        [anchor],
        timeout=file_stability_timeout_s,
    )
    if not stability.get("success"):
        raise RuntimeError(
            f"LAS X native AutoSave file did not become stable: {stability.get('error')}"
        )

    project_dir = _project_dir_for(anchor, base)
    positions = _positions_from_native_tiff(anchor)
    metadata = _metadata_from_native_tiff(anchor, positions)
    metadata = _canonical.metadata_with_job_physical_sizes(
        metadata,
        client,
        acq.job,
    )

    return ExportedAcquisition(
        source_root=base,
        source_dir=project_dir,
        positions=positions,
        metadata=metadata,
        method=f"lasx_native_autosave:{method}",
        relative_path=_relative_or_none(anchor, base),
        source_exporter="lasx_native_autosave",
        cleanup_source_supported=False,
        vendor_metadata_sources=_vendor_metadata_sources(project_dir, anchor),
    )


def native_autosave_base_folder(
    *,
    lcf_path: str | Path | None = None,
) -> Path:
    """Return the configured LAS X native AutoSave base folder."""
    return _read_native_autosave_config(lcf_path=lcf_path).base_folder


def native_autosave_enabled(
    *,
    lcf_path: str | Path | None = None,
) -> bool:
    """Return whether LAS X native AutoSave is enabled in the active config."""
    return _read_native_autosave_config(lcf_path=lcf_path).use_autosave


def _read_native_autosave_config(
    *,
    lcf_path: str | Path | None = None,
) -> _NativeAutoSaveConfig:
    path = Path(lcf_path) if lcf_path is not None else _default_startup_lcf()
    if not path.is_file():
        raise RuntimeError(f"LAS X native AutoSave config not found: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    attrs = dict(re.findall(r'([A-Za-z0-9_]+)="([^"]*)"', text))
    base = attrs.get("AutoSaveBaseFolder")
    if not base:
        raise RuntimeError(f"LAS X native AutoSave config missing AutoSaveBaseFolder: {path}")
    return _NativeAutoSaveConfig(
        base_folder=Path(base),
        use_autosave=_as_bool(attrs.get("DoUseAutoSave")),
        store_separate_folders=_as_bool(attrs.get("DoStoreInSeparateFolders")),
        lcf_path=path,
    )


def _default_startup_lcf() -> Path:
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return appdata / "Leica Microsystems" / "LAS X" / "StartUp" / "UserDataNavigatorExpert.lcf"


def _as_bool(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _detect_from_relative_path(
    client: Any,
    base: Path,
    acq: AcquisitionResult,
) -> Path | None:
    rel = _files.read_relative_path(client)
    if not rel:
        return None
    raw = Path(rel)
    candidates = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(base / rel.lstrip("\\/"))
        candidates.extend(project / raw.name for project in _project_dirs(base))
    for candidate in candidates:
        if _is_native_ome_tiff(candidate) and _is_under(candidate, base):
            if _is_from_acquisition(candidate, acq):
                return candidate
    return None


def _detect_from_mtime(
    base: Path,
    acq: AcquisitionResult,
    *,
    detect_timeout: float,
    poll_interval: float,
) -> Path:
    """Wait for the native AutoSave OME-TIFF, in two phases.

    Phase A (bounded by *detect_timeout*): wait for evidence that AutoSave
    engaged for this acquisition -- a fresh candidate OME-TIFF, or a fresh
    project directory. If none appears, native AutoSave is almost certainly
    disabled in the *running* LAS X session (the StartUp ``.lcf`` can report
    it enabled while the live session has it off); raise an actionable error
    naming that cause rather than a generic "no file found".

    Phase B (unbounded once engaged): the scan has already completed and a
    project exists, so the OME-TIFF is being flushed -- a slow or large write
    is healthy, not a failure. Wait without a deadline (mirroring the acquire
    idle-wait's deliberate no-deadline policy) until the single fresh
    candidate appears.
    """
    detect_deadline = time.perf_counter() + detect_timeout
    t_start = time.perf_counter()
    last_heartbeat = t_start
    engaged = False
    while True:
        candidates = _fresh_native_tiffs(base, acq)
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            names = ", ".join(str(p) for p in candidates[:5])
            if len(candidates) > 5:
                names += ", ..."
            raise RuntimeError(
                "Multiple fresh LAS X native AutoSave OME-TIFF candidates "
                f"after acquisition; refusing to guess: {names}"
            )
        # No file yet. A fresh project directory is the earliest sign that
        # AutoSave engaged; once seen, the file is on its way -- wait for it
        # without a deadline (Phase B).
        if not engaged and _has_fresh_project(base, acq):
            engaged = True
        if not engaged and time.perf_counter() >= detect_deadline:
            raise RuntimeError(
                "LAS X native AutoSave produced no project or OME-TIFF under "
                f"{base} within {detect_timeout:.0f}s after the scan completed. "
                "Native AutoSave is most likely disabled in the running LAS X "
                "session -- the StartUp configuration can report it enabled "
                "while the live session has it off. Enable AutoSave in LAS X "
                "and re-run."
            )
        now = time.perf_counter()
        if engaged and now - last_heartbeat >= _FLUSH_HEARTBEAT_S:
            log.info(
                "Waiting for LAS X native AutoSave to flush the OME-TIFF "
                "(project detected, %.0fs elapsed)",
                now - t_start,
            )
            last_heartbeat = now
        time.sleep(poll_interval)


def _has_fresh_project(base: Path, acq: AcquisitionResult) -> bool:
    """True when a native AutoSave project folder was created for *acq*.

    A fresh project directory (its ``.xlef`` / IOManager config written at or
    after the acquisition started) is the earliest on-disk sign that AutoSave
    engaged -- LAS X creates it before the OME-TIFF is flushed.
    """
    return any(_is_from_acquisition(project, acq) for project in _project_dirs(base))


def _fresh_native_tiffs(base: Path, acq: AcquisitionResult) -> list[Path]:
    out = []
    for project in _project_dirs(base):
        for p in sorted(project.rglob("*.ome.tif")):
            if _is_native_ome_tiff(p) and _is_from_acquisition(p, acq):
                out.append(p)
    return sorted(out, key=lambda p: (p.stat().st_mtime, str(p)))


def _project_dirs(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    dirs = []
    for p in base.iterdir():
        if not p.is_dir():
            continue
        if _project_config_path(p).is_file() or list(p.glob("*.xlef")):
            dirs.append(p)
    return sorted(dirs, key=lambda p: p.stat().st_mtime, reverse=True)


def _project_dir_for(path: Path, base: Path) -> Path:
    current = path.parent
    while _is_under(current, base):
        if _project_config_path(current).is_file() or list(current.glob("*.xlef")):
            return current
        if current == base:
            break
        current = current.parent
    raise RuntimeError(f"Could not locate native AutoSave project for {path}")


def _project_config_path(project_dir: Path) -> Path:
    return project_dir / "Metadata" / _PROJECT_CONFIG_NAME


def _positions_from_native_tiff(tiff_path: Path) -> list[ExportedPosition]:
    planes = _plane_sources_from_tiff(tiff_path)
    positions = []
    for t in sorted({idx.t for idx in planes}):
        positions.append(
            ExportedPosition(
                t=t,
                planes={idx: src for idx, src in sorted(planes.items()) if idx.t == t},
            )
        )
    return positions


def _plane_sources_from_tiff(tiff_path: Path) -> dict[PlaneIndex, PlaneSource]:
    try:
        import tifffile
    except ImportError as e:
        raise RuntimeError("tifffile is required for native AutoSave") from e

    with tifffile.TiffFile(str(tiff_path)) as tif:
        if not tif.is_ome:
            raise RuntimeError(f"Native AutoSave image is not OME-TIFF: {tiff_path}")
        if len(tif.series) != 1:
            raise RuntimeError(
                f"Expected one OME series in native AutoSave TIFF, got "
                f"{len(tif.series)}: {tiff_path}"
            )
        series = tif.series[0]
        axes = str(series.axes)
        shape = tuple(int(x) for x in series.shape)
        _validate_axes(axes)
        size_t, size_z, size_c = _ome_tzc_from_description(tif.pages[0].description)
        _assert_axis_size(axes, shape, "T", size_t, tiff_path)
        _assert_axis_size(axes, shape, "Z", size_z, tiff_path)
        _assert_axis_size(axes, shape, "C", size_c, tiff_path)

        pages = list(series.pages)
        expected_pages = size_t * size_z * size_c
        if len(pages) != expected_pages or len(tif.pages) < expected_pages:
            raise RuntimeError(
                f"Native AutoSave page count mismatch for {tiff_path}: "
                f"series pages={len(pages)}, TIFF pages={len(tif.pages)}, "
                f"expected={expected_pages}"
            )

        non_spatial_axes = [a for a in axes if a not in {"Y", "X"}]
        non_spatial_shape = [shape[i] for i, a in enumerate(axes) if a not in {"Y", "X"}]
        planes: dict[PlaneIndex, PlaneSource] = {}
        for t in range(size_t):
            for z in range(size_z):
                for c in range(size_c):
                    coords = [{"T": t, "Z": z, "C": c}[axis] for axis in non_spatial_axes]
                    offset = _ravel_index(coords, non_spatial_shape)
                    page = pages[offset]
                    if page is None:
                        raise RuntimeError(
                            f"Native AutoSave missing page for T={t}, Z={z}, C={c}: {tiff_path}"
                        )
                    planes[PlaneIndex(t=t, z=z, c=c)] = PlaneSource(
                        path=tiff_path,
                        page_index=page.index,
                    )
        return planes


def _metadata_from_native_tiff(
    tiff_path: Path,
    positions: list[ExportedPosition],
):
    try:
        import tifffile
    except ImportError as e:
        raise RuntimeError("tifffile is required for native AutoSave") from e

    all_indices = [idx for pos in positions for idx in pos.planes]
    if not all_indices:
        raise RuntimeError("Native AutoSave export has no planes")
    with tifffile.TiffFile(str(tiff_path)) as tif:
        series = tif.series[0]
        shape = tuple(int(x) for x in series.shape)
        axes = str(series.axes)
        size_y = shape[axes.index("Y")]
        size_x = shape[axes.index("X")]
        dtype = str(series.dtype)
        xml = _canonical.extract_embedded_ome_xml(tiff_path)
    return _canonical.metadata_from_ome_xml(
        xml,
        size_x=size_x,
        size_y=size_y,
        size_t=max(idx.t for idx in all_indices) + 1,
        size_z=max(idx.z for idx in all_indices) + 1,
        size_c=max(idx.c for idx in all_indices) + 1,
        pixel_type=_canonical.pixel_type_from_dtype(dtype),
    )


def _vendor_metadata_sources(
    project_dir: Path,
    tiff_path: Path,
) -> tuple[VendorMetadataSource, ...]:
    sources = [
        VendorMetadataSource(
            name="source_embedded.ome.xml",
            data=_canonical.extract_embedded_ome_xml(tiff_path),
        )
    ]
    for p in sorted(project_dir.glob("*.xlef")):
        sources.append(VendorMetadataSource(name=p.name, path=p))
    metadata_dir = project_dir / "Metadata"
    acquisition_stem = _native_image_stem(tiff_path)
    metadata_paths = [
        metadata_dir / f"{acquisition_stem}.xlif",
        metadata_dir / _PROJECT_CONFIG_NAME,
    ]
    seen: set[Path] = set()
    for p in metadata_paths:
        if p in seen or not p.is_file():
            continue
        seen.add(p)
        sources.append(VendorMetadataSource(name=f"metadata_{p.name}", path=p))
    return tuple(sources)


def _native_image_stem(path: Path) -> str:
    name = path.name
    for suffix in (".ome.tiff", ".ome.tif"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def _validate_axes(axes: str) -> None:
    if axes.count("Y") != 1 or axes.count("X") != 1:
        raise RuntimeError(f"Unsupported native AutoSave axes '{axes}': need X/Y")
    if len(set(axes)) != len(axes):
        raise RuntimeError(f"Unsupported native AutoSave axes '{axes}': duplicates")
    invalid = [a for a in axes if a not in {"T", "Z", "C", "Y", "X"}]
    if invalid:
        raise RuntimeError(f"Unsupported native AutoSave axes '{axes}': unsupported {invalid}")


def _ome_tzc_from_description(description: str | None) -> tuple[int, int, int]:
    if not description:
        raise RuntimeError("Native AutoSave TIFF has no embedded OME-XML")
    try:
        root = ET.fromstring(description.encode("utf-8"))
    except ET.ParseError as e:
        raise RuntimeError(f"Invalid embedded OME-XML in native TIFF: {e}") from e
    for pixels in root.iter():
        if pixels.tag.rsplit("}", 1)[-1] != "Pixels":
            continue
        try:
            size_t = int(pixels.attrib.get("SizeT", "1"))
            size_z = int(pixels.attrib.get("SizeZ", "1"))
            size_c = int(pixels.attrib.get("SizeC", "1"))
        except ValueError as e:
            raise RuntimeError(
                f"Invalid OME SizeT/SizeZ/SizeC in native TIFF: {pixels.attrib}"
            ) from e
        if min(size_t, size_z, size_c) <= 0:
            raise RuntimeError(
                f"Invalid non-positive OME dimensions in native TIFF: {pixels.attrib}"
            )
        return size_t, size_z, size_c
    raise RuntimeError("Native AutoSave TIFF embedded OME-XML has no Pixels element")


def _assert_axis_size(
    axes: str,
    shape: tuple[int, ...],
    axis: str,
    expected: int,
    tiff_path: Path,
) -> None:
    if axis in axes:
        actual = shape[axes.index(axis)]
    else:
        actual = 1
    if actual != expected:
        raise RuntimeError(
            f"Native AutoSave axis {axis} size mismatch for {tiff_path}: "
            f"series axes={axes} shape={shape}, OME Size{axis}={expected}"
        )


def _ravel_index(coords: list[int], shape: list[int]) -> int:
    if not coords:
        return 0
    offset = 0
    for coord, size in zip(coords, shape, strict=True):
        if coord < 0 or coord >= size:
            raise RuntimeError(f"Native AutoSave coordinate {coords} out of range for {shape}")
        offset = offset * size + coord
    return offset


def _is_native_ome_tiff(path: Path) -> bool:
    return path.is_file() and path.name.lower().endswith((".ome.tif", ".ome.tiff"))


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _relative_or_none(path: Path, root: Path) -> str | None:
    return _files._relative_posix(path, root, fallback_to_str=False)
