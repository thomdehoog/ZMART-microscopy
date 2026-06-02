"""Collect files produced by LAS X native AutoSave.

Native AutoSave writes into a LAS X project folder instead of the
Navigator Expert flat export tree. The observed product is one
multipage OME-TIFF per acquisition with embedded OME-XML plus XLEF/XLIF
project metadata. This module only maps that source product to the
writer-agnostic acquisition contract; persistence stays in ``save``.
"""

from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import files as _files
from .capture import AcquisitionResult
from .navigator_expert_export import (
    DEFAULT_EXPORT_COMPLETION_POLL_INTERVAL_S,
    DEFAULT_EXPORT_COMPLETION_TIMEOUT_S,
    DEFAULT_FILE_STABILITY_TIMEOUT_S,
)
from .product import (
    ExportedAcquisition,
    ExportedPosition,
    PlaneIndex,
    PlaneSource,
    XmlSource,
)

_PROJECT_CONFIG_NAME = "IOManagerConfiguation.xlif"


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
    export_completion_poll_interval: float = (
        DEFAULT_EXPORT_COMPLETION_POLL_INTERVAL_S
    ),
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
            timeout=export_completion_timeout,
            poll_interval=export_completion_poll_interval,
        )
        method = "mtime"

    stability = _files.wait_all_stable(
        [anchor],
        timeout=file_stability_timeout_s,
    )
    if not stability.get("success"):
        raise RuntimeError(
            "LAS X native AutoSave file did not become stable: "
            f"{stability.get('error')}"
        )

    project_dir = _project_dir_for(anchor, base)
    positions = _positions_from_native_tiff(anchor)

    return ExportedAcquisition(
        media_path=base,
        source_dir=project_dir,
        positions=positions,
        method=f"lasx_native_autosave:{method}",
        relative_path=_relative_or_none(anchor, base),
        source_exporter="lasx_native_autosave",
        cleanup_source_supported=False,
    )


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
        raise RuntimeError(
            f"LAS X native AutoSave config missing AutoSaveBaseFolder: {path}"
        )
    return _NativeAutoSaveConfig(
        base_folder=Path(base),
        use_autosave=_as_bool(attrs.get("DoUseAutoSave")),
        store_separate_folders=_as_bool(attrs.get("DoStoreInSeparateFolders")),
        lcf_path=path,
    )


def _default_startup_lcf() -> Path:
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return (
        appdata
        / "Leica Microsystems"
        / "LAS X"
        / "StartUp"
        / "UserDataNavigatorExpert.lcf"
    )


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
    timeout: float,
    poll_interval: float,
) -> Path:
    deadline = time.perf_counter() + timeout
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
        if time.perf_counter() >= deadline:
            raise RuntimeError(
                "No LAS X native AutoSave OME-TIFF found after acquisition "
                f"(scanned {base})"
            )
        time.sleep(poll_interval)


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
                xml=XmlSource(path=tiff_path, embedded=True),
                planes={
                    idx: src
                    for idx, src in sorted(planes.items())
                    if idx.t == t
                },
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
        size_t, size_z, size_c = _ome_tzc_from_description(
            tif.pages[0].description
        )
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
        non_spatial_shape = [
            shape[i] for i, a in enumerate(axes) if a not in {"Y", "X"}
        ]
        planes: dict[PlaneIndex, PlaneSource] = {}
        for t in range(size_t):
            for z in range(size_z):
                for c in range(size_c):
                    coords = [
                        {"T": t, "Z": z, "C": c}[axis]
                        for axis in non_spatial_axes
                    ]
                    offset = _ravel_index(coords, non_spatial_shape)
                    page = pages[offset]
                    if page is None:
                        raise RuntimeError(
                            f"Native AutoSave missing page for T={t}, Z={z}, "
                            f"C={c}: {tiff_path}"
                        )
                    planes[PlaneIndex(t=t, z=z, c=c)] = PlaneSource(
                        path=tiff_path,
                        page_index=page.index,
                    )
        return planes


def _validate_axes(axes: str) -> None:
    if axes.count("Y") != 1 or axes.count("X") != 1:
        raise RuntimeError(f"Unsupported native AutoSave axes '{axes}': need X/Y")
    if len(set(axes)) != len(axes):
        raise RuntimeError(f"Unsupported native AutoSave axes '{axes}': duplicates")
    invalid = [a for a in axes if a not in {"T", "Z", "C", "Y", "X"}]
    if invalid:
        raise RuntimeError(
            f"Unsupported native AutoSave axes '{axes}': unsupported {invalid}"
        )


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
                f"Invalid non-positive OME dimensions in native TIFF: "
                f"{pixels.attrib}"
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
    for coord, size in zip(coords, shape):
        if coord < 0 or coord >= size:
            raise RuntimeError(
                f"Native AutoSave coordinate {coords} out of range for {shape}"
            )
        offset = offset * size + coord
    return offset


def _is_native_ome_tiff(path: Path) -> bool:
    return path.is_file() and path.name.lower().endswith((".ome.tif", ".ome.tiff"))


def _is_from_acquisition(path: Path, acq: AcquisitionResult) -> bool:
    try:
        return path.stat().st_mtime >= acq.started_at
    except OSError:
        return False


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _relative_or_none(path: Path, root: Path) -> str | None:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return None
