"""
Save: persist a capture into the canonical output layout.
=========================================================
The mesoSPIM image writer produces frame files on the acquisition PC; ``save``
relocates them into ``<output_root>/data/`` under a stable, sortable name and
prints what the driver knows about the capture beside them, under
``data/metadata``. It returns a :class:`SavedAcquisition` manifest.

The layout is the one every ZMART driver writes, so a workflow finds the same
things in the same places whatever microscope took the picture::

    <output_root>/
        data/
            <type>_<label>.tiff                       the pixels
            metadata/
                ZMART_state/<type>_<label>_ZMART_state.json   ZMART's account
                vendor/mesospim/<type>_<label>_meta.txt       the writer's own notes

The pixels get a folder of their own so what is made from them later -- a
stitched view, an analysis -- becomes a folder beside them, and everything
that merely *describes* a capture sits under ``metadata``, one folder per
party, so whose account a file is never has to be read off its name.

This is intentionally simple and dependency-light: it copies the frames the
image writer already wrote (it does not re-encode pixels). The per-plane
pixel-pull path (numpy -> OME-TIFF rewrite) is an extension seam, matching the
ZEN driver's save contract.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict
from pathlib import Path

from .product import AcquisitionResult, SavedAcquisition

log = logging.getLogger(__name__)

# The companion files the default mesoSPIM Tiff writer leaves beside a stack
# ``<name>``: its own metadata text, and a maximum-intensity projection. The
# metadata is the vendor's account of the capture and is kept; the projection
# is derived from the pixels and is not.
VENDOR_METADATA_SUFFIX = "_meta.txt"


def canonical_stem(acquisition_type: str, position_label: str) -> str:
    """Stable, filesystem-safe stem for one acquisition's output files.

    Public so the controller can pre-name the image-writer output folder/file
    with the same stem the saved frames end up under.
    """
    safe_label = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in position_label)
    safe_type = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in acquisition_type)
    return f"{safe_type}_{safe_label}"


def data_dir(output_root: str | Path) -> Path:
    """Where the images of a run go: ``<output_root>/data``."""
    return Path(output_root) / "data"


def metadata_dir(output_root: str | Path) -> Path:
    """Where everything that describes a capture goes: ``<output_root>/data/metadata``."""
    return data_dir(output_root) / "metadata"


def state_dir(output_root: str | Path) -> Path:
    """Where ZMART's own account of each capture goes: ``data/metadata/ZMART_state``."""
    return metadata_dir(output_root) / "ZMART_state"


def vendor_dir(output_root: str | Path) -> Path:
    """Where the mesoSPIM writer's own notes go: ``data/metadata/vendor/mesospim``."""
    return metadata_dir(output_root) / "vendor" / "mesospim"


def save(
    acq: AcquisitionResult,
    output_root: str | Path,
    *,
    position_label: str,
    format: str = "ome-tiff",
    state: dict | None = None,
) -> SavedAcquisition:
    """Persist ``acq``'s frames under ``<output_root>/data/`` and print its state.

    Args:
        acq: the :class:`AcquisitionResult` from ``capture.acquire``.
        output_root: the workflow-owned run directory.
        position_label: names the position in the output filenames.
        format: recorded in the manifest and the printed state.
        state: what the driver knows about the microscope at capture time
            (the controller passes ``get_state`` plus the position). It is
            printed to ``data/metadata/ZMART_state`` together with the
            acquisition row that ran and the file names, so the capture can be
            understood, and repeated, without the microscope.

    Returns:
        A :class:`SavedAcquisition` manifest with the persisted image paths.

    Raises:
        FileNotFoundError: a source frame file is missing on disk.
    """
    images = data_dir(output_root)
    images.mkdir(parents=True, exist_ok=True)

    # Validate every source up front so a missing frame can't leave a partial
    # dataset behind (we would otherwise copy some frames, then raise).
    sources = [Path(s) for s in acq.files]
    missing = [str(s) for s in sources if not s.exists()]
    if missing:
        raise FileNotFoundError(f"source frame file(s) missing: {missing}")

    # A distinct stem per acquisition: never silently overwrite a prior dataset
    # that shares the same type+label (a retry, a re-image of the same well).
    stem = _unique_stem(output_root, canonical_stem(acq.acquisition_type, position_label))

    image_paths: list[Path] = []
    multiplane = len(sources) > 1
    for index, source in enumerate(sources):
        suffix = source.suffix or ".tiff"
        name = f"{stem}_z{index:04d}{suffix}" if multiplane else f"{stem}{suffix}"
        dest = images / name
        shutil.copy2(source, dest)
        image_paths.append(dest)

    vendor_paths = _keep_vendor_metadata(sources, output_root, stem)

    state_path = state_dir(output_root) / f"{stem}_ZMART_state.json"
    payload = {
        "acquisition_type": acq.acquisition_type,
        "position_label": position_label,
        "format": format,
        "planes": acq.planes,
        "duration_s": acq.duration_s,
        "acquisition": acq.acquisition,
        "metadata": _metadata_dict(acq),
        "images": [p.name for p in image_paths],
        "vendor_metadata": [p.name for p in vendor_paths],
        "state": state,
    }
    _write_json_atomic(state_path, payload)

    log.info(
        "saved %s/%s: %d frame(s) -> %s",
        acq.acquisition_type,
        position_label,
        len(image_paths),
        images,
    )
    return SavedAcquisition(
        acquisition_type=acq.acquisition_type,
        position_label=position_label,
        image_paths=tuple(image_paths),
        state_path=state_path,
        format=format,
        metadata=acq.metadata,
        vendor_metadata_paths=tuple(vendor_paths),
    )


def _keep_vendor_metadata(sources: list[Path], output_root: str | Path, stem: str) -> list[Path]:
    """Copy the writer's ``*_meta.txt`` companions, when it left any, under ``metadata/vendor``."""
    kept: list[Path] = []
    for index, source in enumerate(sources):
        companion = source.with_name(source.name + VENDOR_METADATA_SUFFIX)
        if not companion.is_file():
            continue
        suffix = f"_z{index:04d}" if len(sources) > 1 else ""
        dest = vendor_dir(output_root) / f"{stem}{suffix}{VENDOR_METADATA_SUFFIX}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(companion, dest)
        kept.append(dest)
    return kept


def _write_json_atomic(path: Path, payload: dict) -> None:
    """Write the file completely or not at all, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def _unique_stem(output_root: str | Path, stem: str) -> str:
    """Return ``stem`` or ``stem_2`` / ``stem_3`` / … that isn't already used.

    The printed state (``<stem>_ZMART_state.json``) is the sentinel, so a
    repeated type+label can't clobber an earlier dataset's frames or state.
    """
    candidate = stem
    n = 2
    while (state_dir(output_root) / f"{candidate}_ZMART_state.json").exists():
        candidate = f"{stem}_{n}"
        n += 1
    return candidate


def _metadata_dict(acq: AcquisitionResult) -> dict:
    # asdict recurses into the channels tuple, converting each ChannelMetadata.
    return asdict(acq.metadata)
