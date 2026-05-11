"""Driver-first acquisition pipeline.

The workflow-facing API for smart-microscopy acquisitions. Composes
existing driver primitives (acquire_frame, parse_lasx_filename,
check_ome_*, ome_tiff fixers) with the lab-wide naming convention from
``_shared.output_layout``.

Public surface:
    start_run(client, experiment)          -> RunHandle
    acquire_and_save(client, run, ...)     -> SavedAcquisition

Workflow contract: caller positions the stage; driver triggers the
frame and persists. Single-threaded: ``acquire_and_save`` must be
called from one thread. Concurrent calls have undefined behavior on
the summary append.

``output_root`` is derived as ``media_path / "smart"`` and created on
the fly. Operators only choose ``experiment``; there is no path config.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from . import acquire as _acquire
from . import file_confirmation as _fc
from . import ome_tiff as _ome
from . import readers as _readers

from _shared.output_layout import (
    LayoutPlan,
    MAX_ACQUISITION_TYPE_LEN,
    Naming,
    build_image_name,
    build_layout,
    build_xml_name,
)

log = logging.getLogger(__name__)

# Path-length sentinel: leave headroom under Windows MAX_PATH=260.
_MAX_PATH_BUDGET = 250


@dataclass(frozen=True)
class RunHandle:
    """State carried across ``acquire_and_save`` calls for one run."""

    layout: LayoutPlan
    media_path: Path
    baseline: str
    start_time_utc: float


@dataclass(frozen=True)
class SavedAcquisition:
    """Result of one ``acquire_and_save`` call."""

    image: np.ndarray
    image_path: Path
    naming: Naming


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_run(client: Any, experiment: str) -> RunHandle:
    """Derive ``output_root = media_path / "smart"``, atomically create the
    run dir, cache baseline, write initial ``summary.json`` skeleton.

    Raises ``RuntimeError`` if LAS X settings can't be read, or
    ``ValueError`` if the projected worst-case path exceeds the budget.
    """
    settings = _readers.get_lasx_settings()
    if not settings or "export" not in settings:
        raise RuntimeError(
            "Could not read media_path from LAS X settings. "
            "Verify the Navigator Expert settings file is present and "
            "configured with an export media path."
        )
    media_path_str = settings["export"].get("media_path")
    if not media_path_str:
        raise RuntimeError("LAS X settings missing export/media_path.")
    media_path = Path(media_path_str)

    output_root = media_path / "smart"
    layout = build_layout(output_root, experiment)

    _check_path_budget(layout)

    baseline = _fc.read_relative_path(client)
    start_time_utc = layout.start_time_utc

    summary_path = layout.run_dir / "summary.json"
    _write_summary_atomic(
        summary_path,
        {
            "experiment": experiment,
            "hash6": layout.hash6,
            "start_time_utc": start_time_utc,
            "acquisitions": [],
        },
    )

    return RunHandle(
        layout=layout,
        media_path=media_path,
        baseline=baseline,
        start_time_utc=start_time_utc,
    )


def acquire_and_save(
    client: Any,
    run: RunHandle,
    job: str,
    naming: Naming,
    *,
    lineage: dict | None = None,
    fix_ome: bool = False,
    cleanup_source: bool = False,
) -> SavedAcquisition:
    """Acquire frame → locate companion XML → validate → atomic save
    image+XML → atomic append record to summary.json → return result.

    Caller has positioned the stage. Returns one file per call.
    Multi-slice positions are produced by workflow loops varying
    ``(c, z)`` in ``Naming`` across successive calls.
    """
    image, lasx_image_path = _acquire.acquire_frame(client, job)
    lasx_image_path = Path(lasx_image_path)

    xml_src = _find_companion_xml(lasx_image_path)
    if xml_src is None:
        raise RuntimeError(
            f"OME-XML companion not found for {lasx_image_path.name} "
            f"under {lasx_image_path.parent / 'metadata'}. "
            f"Image + XML are an atomic unit; aborting save."
        )

    _validate_ome(lasx_image_path, xml_src, fix_ome=fix_ome)

    image_dest = (
        run.layout.data_dir(naming.acquisition_type)
        / build_image_name(naming)
    )
    xml_dest = (
        run.layout.metadata_dir(naming.acquisition_type)
        / build_xml_name(naming)
    )
    image_dest.parent.mkdir(parents=True, exist_ok=True)
    xml_dest.parent.mkdir(parents=True, exist_ok=True)

    _save_atomic(lasx_image_path, image_dest, xml_src, xml_dest)

    record = {
        "naming": _naming_to_dict(naming),
        "image_path": _rel_posix(image_dest, run.layout.run_dir),
        "xml_path": _rel_posix(xml_dest, run.layout.run_dir),
        "lasx_source": _rel_posix(lasx_image_path, run.media_path),
        "lineage": lineage,
    }
    _append_summary_atomic(run.layout.run_dir / "summary.json", record)

    if cleanup_source:
        for p in (lasx_image_path, xml_src):
            try:
                p.unlink()
            except OSError as e:
                log.warning("cleanup_source failed for %s: %s", p, e)

    return SavedAcquisition(image=image, image_path=image_dest, naming=naming)


# ---------------------------------------------------------------------------
# Internal helpers (file-private)
# ---------------------------------------------------------------------------


def _check_path_budget(layout: LayoutPlan) -> None:
    """Raise if the worst-case canonical path exceeds ``_MAX_PATH_BUDGET``."""
    longest_acq_type = "a" * MAX_ACQUISITION_TYPE_LEN
    worst_naming = Naming(
        acquisition_type=longest_acq_type,
        hash6=layout.hash6,
        k=99999, m=99999, g=99999, p=99999,
        t=99999, v=99, c=99, z=99999,
    )
    worst_path = (
        layout.data_dir(longest_acq_type) / build_image_name(worst_naming)
    )
    if len(str(worst_path)) > _MAX_PATH_BUDGET:
        raise ValueError(
            f"Worst projected path is {len(str(worst_path))} chars "
            f"(cap {_MAX_PATH_BUDGET}). Shorten media_path or experiment. "
            f"Path: {worst_path}"
        )


def _find_companion_xml(image_path: Path) -> Path | None:
    """Locate the OME-XML companion for a LAS X export TIFF.

    LAS X exports image to ``<experiment_dir>/<image>.ome.tif`` and XML
    to ``<experiment_dir>/metadata/<image>.ome.xml``. XML drops the
    X/Y/Z/C segments. Returns ``None`` if metadata dir or matching XML
    not found.
    """
    parsed = _fc.parse_lasx_filename(image_path.name)
    if parsed is None:
        return None
    metadata_dir = image_path.parent / "metadata"
    if not metadata_dir.is_dir():
        return None
    xml_name = (
        f"image"
        f"--L{parsed['L']:04d}"
        f"--J{parsed['J']:02d}"
        f"--E{parsed['E']:02d}"
        f"--T{parsed['T']:04d}"
        f".ome.xml"
    )
    xml_path = metadata_dir / xml_name
    return xml_path if xml_path.is_file() else None


def _validate_ome(image_path: Path, xml_path: Path, *, fix_ome: bool) -> None:
    """Check OME-TIFF and companion XML. With ``fix_ome=True``, attempt
    in-place repair before failing."""
    img_check = _ome.check_ome_tiff(image_path)
    if not img_check.get("success"):
        if fix_ome:
            _ome.fix_ome_tiff(image_path)
            img_check = _ome.check_ome_tiff(image_path)
        if not img_check.get("success"):
            raise RuntimeError(
                f"OME-TIFF validation failed: {image_path} :: {img_check}"
            )

    xml_check = _ome.check_ome_xml_file(xml_path)
    if not xml_check.get("success"):
        if fix_ome:
            _ome.fix_ome_xml_file(xml_path)
            xml_check = _ome.check_ome_xml_file(xml_path)
        if not xml_check.get("success"):
            raise RuntimeError(
                f"OME-XML validation failed: {xml_path} :: {xml_check}"
            )


def _save_atomic(
    image_src: Path, image_dest: Path,
    xml_src: Path, xml_dest: Path,
) -> None:
    """All-or-nothing copy of image + XML pair to canonical destinations.

    Six-step contract:
      1. Copy image to ``image_dest.tmp``.
      2. Copy XML to ``xml_dest.tmp``.
      3. Validate both ``.tmp`` files exist and are non-empty.
      4. ``os.replace`` both ``.tmp`` files to their final destinations.
      5. On any exception in steps 1-3, unlink any ``.tmp`` created
         by this call; final paths are not touched.
      6. The narrow window between step 4's two ``os.replace`` calls can
         only leave a final image without final XML on filesystem-level
         failure; log loudly and propagate.
    """
    image_tmp = _with_tmp_suffix(image_dest)
    xml_tmp = _with_tmp_suffix(xml_dest)

    created: list[Path] = []
    try:
        shutil.copy2(str(image_src), str(image_tmp))
        created.append(image_tmp)
        shutil.copy2(str(xml_src), str(xml_tmp))
        created.append(xml_tmp)

        if image_tmp.stat().st_size == 0:
            raise RuntimeError(f"Image .tmp is empty: {image_tmp}")
        if xml_tmp.stat().st_size == 0:
            raise RuntimeError(f"XML .tmp is empty: {xml_tmp}")
    except BaseException:
        for tmp in created:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        raise

    os.replace(str(image_tmp), str(image_dest))
    try:
        os.replace(str(xml_tmp), str(xml_dest))
    except BaseException:
        log.error(
            "PARTIAL SAVE: image landed at %s but XML failed to replace "
            "from %s -> %s. Atomic-unit contract violated; investigate "
            "filesystem health.", image_dest, xml_tmp, xml_dest,
        )
        raise


def _write_summary_atomic(summary_path: Path, data: dict) -> None:
    """Write *data* to *summary_path* atomically via tempfile + os.replace."""
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _with_tmp_suffix(summary_path)
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(summary_path))


def _append_summary_atomic(summary_path: Path, record: dict) -> None:
    """Append *record* to ``summary.json``'s ``acquisitions`` list, atomically.

    Single-threaded contract: caller is responsible for serialization.
    """
    if not summary_path.is_file():
        raise RuntimeError(
            f"summary.json missing at {summary_path}; "
            f"start_run was not called or run dir was deleted."
        )
    with summary_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("acquisitions", []).append(record)
    _write_summary_atomic(summary_path, data)


def _with_tmp_suffix(p: Path) -> Path:
    """Return ``p`` with ``.tmp`` appended (preserves the original suffix)."""
    return p.with_name(p.name + ".tmp")


def _rel_posix(p: Path, base: Path) -> str:
    """Return ``p`` relative to ``base`` with forward-slash separators."""
    return str(p.relative_to(base)).replace("\\", "/")


def _naming_to_dict(n: Naming) -> dict:
    return {
        "acquisition_type": n.acquisition_type,
        "hash6": n.hash6,
        "k": n.k, "m": n.m, "g": n.g, "p": n.p,
        "t": n.t, "v": n.v, "c": n.c, "z": n.z,
    }
