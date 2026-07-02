"""
Save: persist a capture into the canonical output layout.
=========================================================
The mesoSPIM image writer produces frame files on the acquisition PC; ``save``
relocates them into ``<output_root>/data/`` under a stable, sortable name and
writes a JSON metadata sidecar next to them. It returns a
:class:`SavedAcquisition` manifest.

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


def canonical_stem(acquisition_type: str, position_label: str) -> str:
    """Stable, filesystem-safe stem for one acquisition's output files.

    Public so the controller can pre-name the image-writer output folder/file
    with the same stem the saved frames end up under.
    """
    safe_label = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in position_label)
    safe_type = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in acquisition_type)
    return f"{safe_type}_{safe_label}"


def save(
    acq: AcquisitionResult,
    output_root: str | Path,
    *,
    position_label: str,
    format: str = "ome-tiff",
) -> SavedAcquisition:
    """Persist ``acq``'s frames under ``<output_root>/data/`` and write metadata.

    Args:
        acq: the :class:`AcquisitionResult` from ``capture.acquire``.
        output_root: the workflow-owned run directory.
        position_label: names the position in the output filenames.
        format: recorded in the manifest and metadata sidecar.

    Returns:
        A :class:`SavedAcquisition` manifest with the persisted image paths.

    Raises:
        FileNotFoundError: a source frame file is missing on disk.
    """
    data_dir = Path(output_root) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    stem = canonical_stem(acq.acquisition_type, position_label)

    image_paths: list[Path] = []
    multiplane = len(acq.files) > 1
    for index, source in enumerate(acq.files):
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError(f"source frame file missing: {source}")
        suffix = source.suffix or ".tiff"
        name = f"{stem}_z{index:04d}{suffix}" if multiplane else f"{stem}{suffix}"
        dest = data_dir / name
        shutil.copy2(source, dest)
        image_paths.append(dest)

    metadata_path = data_dir / f"{stem}.json"
    payload = {
        "acquisition_type": acq.acquisition_type,
        "position_label": position_label,
        "format": format,
        "planes": acq.planes,
        "duration_s": acq.duration_s,
        "acquisition": acq.acquisition,
        "metadata": _metadata_dict(acq),
        "image_files": [p.name for p in image_paths],
    }
    tmp = metadata_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(metadata_path)

    log.info(
        "saved %s/%s: %d frame(s) -> %s",
        acq.acquisition_type,
        position_label,
        len(image_paths),
        data_dir,
    )
    return SavedAcquisition(
        acquisition_type=acq.acquisition_type,
        position_label=position_label,
        image_paths=tuple(image_paths),
        metadata_path=metadata_path,
        format=format,
        metadata=acq.metadata,
    )


def _metadata_dict(acq: AcquisitionResult) -> dict:
    # asdict recurses into the channels tuple, converting each ChannelMetadata.
    return asdict(acq.metadata)
