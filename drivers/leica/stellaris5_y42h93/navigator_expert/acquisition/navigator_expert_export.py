"""Collect files produced by the Navigator Expert exporter.

Navigator Expert / LAS X is the file producer. The driver accepts the
exported files, waits until they are stable, and hands stable source
paths to ``acquisition.save`` for persistence into the workflow output
layout.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import readers as _readers
from . import files as _files
from . import ome_canonical as _canonical
from .capture import AcquisitionResult
from .product import (
    ExportedAcquisition,
    ExportedPosition,
    PlaneIndex,
    PlaneSource,
    VendorMetadataSource,
)

DEFAULT_FILE_STABILITY_TIMEOUT_S = 120
DEFAULT_EXPORT_COMPLETION_TIMEOUT_S = 5.0
DEFAULT_EXPORT_COMPLETION_POLL_INTERVAL_S = 0.5


@dataclass(frozen=True)
class _CollectedExport:
    positions: list[ExportedPosition]
    xml_paths: list[Path]


def collect_navigator_expert_export(
    client: Any,
    acq: AcquisitionResult,
    *,
    file_stability_timeout_s: int = DEFAULT_FILE_STABILITY_TIMEOUT_S,
    path_poll_timeout: float = 5.0,
    path_poll_interval: float = 0.5,
    mtime_poll_timeout: float = 15.0,
    export_completion_timeout: float = DEFAULT_EXPORT_COMPLETION_TIMEOUT_S,
    export_completion_poll_interval: float = (DEFAULT_EXPORT_COMPLETION_POLL_INTERVAL_S),
) -> ExportedAcquisition:
    """Return stable files exported by Navigator Expert for *acq*.

    Primary detection uses the current ``RelativePathName`` when it
    points at a file updated since the acquisition started. Fallback scans
    the configured MediaPath for Leica OME-TIFF exports newer than
    ``acq.started_at``.
    """
    media_path = navigator_expert_media_path()
    detected = _detect_from_relative_path(
        client,
        media_path,
        acq,
        timeout=path_poll_timeout,
        poll_interval=path_poll_interval,
        completion_timeout=export_completion_timeout,
        completion_poll_interval=export_completion_poll_interval,
    )
    if detected is None:
        detected = _detect_from_mtime(
            client,
            media_path,
            acq,
            timeout=mtime_poll_timeout,
            completion_timeout=export_completion_timeout,
            completion_poll_interval=export_completion_poll_interval,
        )

    files = detected.source_files
    if not files:
        raise RuntimeError("Navigator Expert export produced no files")
    stability = _files.wait_all_stable(
        files,
        timeout=file_stability_timeout_s,
    )
    if not stability.get("success"):
        raise RuntimeError(
            f"Navigator Expert export files did not become stable: {stability.get('error')}"
        )
    return detected


def navigator_expert_media_path() -> Path:
    """Return the Navigator Expert exporter media path."""
    settings = _readers.get_lasx_settings()
    if not settings or "export" not in settings:
        raise RuntimeError(
            "Could not read media_path from LAS X settings. "
            "Verify the Navigator Expert settings file is present and "
            "configured with an export media path."
        )
    media_path = settings["export"].get("media_path")
    if not media_path:
        raise RuntimeError("LAS X settings missing export/media_path.")
    return Path(media_path)


def _detect_from_relative_path(
    client: Any,
    media_path: Path,
    acq: AcquisitionResult,
    *,
    timeout: float,
    poll_interval: float,
    completion_timeout: float,
    completion_poll_interval: float,
) -> ExportedAcquisition | None:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        rel = _files.read_relative_path(client)
        if rel:
            full_path = media_path / rel.lstrip("\\/")
            if full_path.is_file() and _is_from_acquisition(full_path, acq):
                parsed = _files.parse_lasx_filename(full_path.name)
                if parsed is not None:
                    collected = _collect_positions(
                        full_path.parent,
                        parsed,
                        acq,
                        timeout=completion_timeout,
                        poll_interval=completion_poll_interval,
                    )
                    return _exported_acquisition(
                        client=client,
                        acq=acq,
                        media_path=media_path,
                        source_dir=full_path.parent,
                        collected=collected,
                        method="relative_path",
                        relative_path=rel,
                    )
        time.sleep(poll_interval)
    return None


def _detect_from_mtime(
    client: Any,
    media_path: Path,
    acq: AcquisitionResult,
    *,
    timeout: float,
    completion_timeout: float,
    completion_poll_interval: float,
) -> ExportedAcquisition:
    found = _find_fresh_seed_by_mtime(media_path, acq, timeout=timeout)
    if found is None:
        raise RuntimeError(
            f"No Navigator Expert OME-TIFF files found after acquisition (scanned {media_path})"
        )
    source_dir, parsed = found
    collected = _collect_positions(
        source_dir,
        parsed,
        acq,
        timeout=completion_timeout,
        poll_interval=completion_poll_interval,
    )
    return _exported_acquisition(
        client=client,
        acq=acq,
        media_path=media_path,
        source_dir=source_dir,
        collected=collected,
        method="mtime",
    )


def _find_fresh_seed_by_mtime(
    media_path: Path,
    acq: AcquisitionResult,
    *,
    timeout: float,
) -> tuple[Path, dict] | None:
    media = Path(media_path)
    experiments_dir = media / "Experiments"
    if not experiments_dir.is_dir():
        experiments_dir = media

    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        candidates: list[tuple[float, Path, dict]] = []
        for exp_dir in sorted(experiments_dir.iterdir(), reverse=True):
            if not exp_dir.is_dir():
                continue
            for p in exp_dir.iterdir():
                if not p.is_file() or not p.name.endswith(".ome.tif"):
                    continue
                parsed = _files.parse_lasx_filename(p.name)
                if parsed is None or not _is_from_acquisition(p, acq):
                    continue
                candidates.append((p.stat().st_mtime, p, parsed))
        if candidates:
            _mtime, seed, parsed = max(candidates, key=lambda item: item[0])
            return seed.parent, parsed
        time.sleep(0.5)
    return None


def _collect_positions(
    source_dir: Path,
    ref_parsed: dict,
    acq: AcquisitionResult,
    *,
    timeout: float = DEFAULT_EXPORT_COMPLETION_TIMEOUT_S,
    poll_interval: float = DEFAULT_EXPORT_COMPLETION_POLL_INTERVAL_S,
) -> _CollectedExport:
    deadline = time.perf_counter() + timeout
    last_error: _IncompleteExport | None = None

    while True:
        try:
            return _collect_positions_once(source_dir, ref_parsed, acq)
        except _IncompleteExport as e:
            last_error = e
            if time.perf_counter() >= deadline:
                raise RuntimeError(str(last_error)) from last_error
            time.sleep(poll_interval)


class _IncompleteExport(RuntimeError):
    """The export product is visible but not complete yet."""


def _collect_positions_once(
    source_dir: Path,
    ref_parsed: dict,
    acq: AcquisitionResult,
) -> _CollectedExport:
    target_j = ref_parsed.get("J")
    target_l = ref_parsed.get("L")
    target_e = ref_parsed.get("E")

    fresh: list[tuple[Path, dict]] = []
    for p in sorted(source_dir.iterdir()):
        if not p.is_file() or not p.name.endswith(".ome.tif"):
            continue
        parsed = _files.parse_lasx_filename(p.name)
        if parsed is None:
            continue
        if parsed.get("L") != target_l:
            continue
        if parsed.get("J") != target_j:
            continue
        if parsed.get("E") != target_e:
            continue
        if not _is_from_acquisition(p, acq):
            continue
        fresh.append((p, parsed))

    if not fresh:
        raise _IncompleteExport(
            f"Navigator Expert export had no fresh image planes for job index {target_j}"
        )

    source_views = sorted({(parsed["X"], parsed["Y"]) for _p, parsed in fresh})
    if len(source_views) != 1:
        raise RuntimeError(
            "Navigator Expert export contains multiple source X/Y groups. "
            "These are Navigator-internal indices, not canonical view (v); "
            "define an explicit product mapping before saving this export."
        )

    by_t: dict[int, dict[PlaneIndex, PlaneSource]] = {}
    for p, parsed in fresh:
        idx = PlaneIndex(t=parsed["T"], z=parsed["Z"], c=parsed["C"])
        planes = by_t.setdefault(idx.t, {})
        if idx in planes:
            raise RuntimeError(f"duplicate LAS X plane index {idx}: {p}")
        planes[idx] = PlaneSource(path=p)

    xml_by_t: dict[int, tuple[Path, tuple[int, int, int] | None]] = {}
    for t in sorted(by_t):
        xml_path = _find_companion_xml(source_dir, ref_parsed, t, acq)
        if xml_path is None:
            raise _IncompleteExport(f"OME-XML companion not found for job index {target_j}, T={t}")
        xml_by_t[t] = (xml_path, _expected_dims_from_xml(xml_path))

    expected_time_counts = {dims[2] for _xml_path, dims in xml_by_t.values() if dims is not None}
    if len(expected_time_counts) > 1:
        raise RuntimeError(
            "Navigator Expert companion XML files disagree on SizeT: "
            f"{sorted(expected_time_counts)}"
        )
    if expected_time_counts:
        expected_t = next(iter(expected_time_counts))
        missing_t = [t for t in range(expected_t) if t not in by_t]
        if missing_t:
            preview = ", ".join(f"T{t:04d}" for t in missing_t[:8])
            if len(missing_t) > 8:
                preview += ", ..."
            raise _IncompleteExport(f"incomplete LAS X export timepoints: missing {preview}")

    positions = []
    xml_paths = []
    for t in sorted(by_t):
        planes = by_t[t]
        xml_path, expected = xml_by_t[t]
        _validate_complete_grid(t, planes, expected=expected)
        xml_paths.append(xml_path)
        positions.append(
            ExportedPosition(
                t=t,
                planes=planes,
            )
        )
    return _CollectedExport(positions=positions, xml_paths=xml_paths)


def _exported_acquisition(
    *,
    client: Any,
    acq: AcquisitionResult,
    media_path: Path,
    source_dir: Path,
    collected: _CollectedExport,
    method: str,
    relative_path: str | None = None,
) -> ExportedAcquisition:
    metadata = _metadata_from_collected(collected)
    metadata = _canonical.metadata_with_job_physical_sizes(
        metadata,
        client,
        acq.job,
    )
    return ExportedAcquisition(
        media_path=media_path,
        source_dir=source_dir,
        positions=collected.positions,
        metadata=metadata,
        method=method,
        relative_path=relative_path,
        source_exporter="navigator_expert_exporter",
        vendor_metadata_sources=tuple(
            VendorMetadataSource(
                name=f"source_t{pos.t:05d}.ome.xml",
                path=xml_path,
            )
            for pos, xml_path in zip(
                collected.positions,
                collected.xml_paths,
                strict=True,
            )
        ),
    )


def _metadata_from_collected(collected: _CollectedExport):
    all_indices = [idx for pos in collected.positions for idx in pos.planes]
    if not all_indices:
        raise RuntimeError("Navigator Expert export has no planes")
    first_source = collected.positions[0].planes[sorted(collected.positions[0].planes)[0]]
    size_y, size_x, pixel_type = _plane_shape_and_type(first_source.path)
    size_t = max(idx.t for idx in all_indices) + 1
    size_z = max(idx.z for idx in all_indices) + 1
    size_c = max(idx.c for idx in all_indices) + 1
    xml = collected.xml_paths[0].read_bytes()
    metadata = _canonical.metadata_from_ome_xml(
        xml,
        size_x=size_x,
        size_y=size_y,
        size_t=size_t,
        size_z=size_z,
        size_c=size_c,
        pixel_type=pixel_type,
    )
    return metadata


def _plane_shape_and_type(path: Path) -> tuple[int, int, str]:
    try:
        import tifffile
    except ImportError as e:
        raise RuntimeError("tifffile is required for Navigator Expert export") from e

    arr = tifffile.imread(str(path))
    if arr.ndim != 2:
        raise RuntimeError(
            f"Expected Navigator Expert source plane to be 2-D, got {arr.shape}: {path}"
        )
    return int(arr.shape[0]), int(arr.shape[1]), _canonical.pixel_type_from_dtype(str(arr.dtype))


def _validate_complete_grid(
    t: int,
    planes: dict[PlaneIndex, PlaneSource],
    *,
    expected: tuple[int, int, int] | None,
) -> None:
    if expected is None:
        channels = sorted({idx.c for idx in planes})
        z_slices = sorted({idx.z for idx in planes})
    else:
        size_c, size_z, _size_t = expected
        channels = list(range(size_c))
        z_slices = list(range(size_z))
    missing = [
        (c, z) for c in channels for z in z_slices if PlaneIndex(t=t, z=z, c=c) not in planes
    ]
    if missing:
        preview = ", ".join(f"C{c:02d}/Z{z:02d}" for c, z in missing[:8])
        if len(missing) > 8:
            preview += ", ..."
        detail = "XML-declared" if expected is not None else "observed"
        raise _IncompleteExport(
            f"incomplete LAS X export grid for T={t} ({detail} grid): missing {preview}"
        )


def _expected_dims_from_xml(xml_path: Path) -> tuple[int, int, int] | None:
    """Return ``(SizeC, SizeZ, SizeT)`` from OME XML when declared."""
    try:
        root = ET.parse(xml_path).getroot()
    except (OSError, ET.ParseError):
        return None
    for pixels in root.iter():
        if pixels.tag.rsplit("}", 1)[-1] != "Pixels":
            continue
        try:
            size_c = int(pixels.attrib["SizeC"])
            size_z = int(pixels.attrib["SizeZ"])
            size_t = int(pixels.attrib["SizeT"])
        except (KeyError, TypeError, ValueError):
            return None
        if size_c <= 0 or size_z <= 0 or size_t <= 0:
            return None
        return size_c, size_z, size_t
    return None


def _find_companion_xml(
    source_dir: Path,
    parsed: dict,
    t: int,
    acq: AcquisitionResult,
) -> Path | None:
    metadata_dir = source_dir / "metadata"
    if not metadata_dir.is_dir():
        return None
    candidates = []
    for p in metadata_dir.iterdir():
        if not p.is_file() or not p.name.endswith(".ome.xml"):
            continue
        xml_parsed = _files.parse_lasx_filename(p.name)
        if xml_parsed is None:
            continue
        if xml_parsed.get("L") != parsed.get("L"):
            continue
        if xml_parsed.get("J") != parsed.get("J"):
            continue
        if xml_parsed.get("E") != parsed.get("E"):
            continue
        if xml_parsed.get("T") != t:
            continue
        if not _is_from_acquisition(p, acq):
            continue
        candidates.append(p)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _is_from_acquisition(path: Path, acq: AcquisitionResult) -> bool:
    try:
        return path.stat().st_mtime >= acq.started_at
    except OSError:
        return False
