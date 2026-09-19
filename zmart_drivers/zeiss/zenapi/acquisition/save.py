"""Persist an acquired CZI into the workflow output layout.

ZEN writes one CZI container on the acquisition PC; ``save`` resolves that path
via ``get_image_output_path``, waits for the file to stop growing, and copies it
into the canonical ``<type>/data/`` directory under ``output_root`` using the
driver's private :class:`Naming` slots (with a ``.czi`` extension, since a CZI
holds the whole c x z grid -- like the XML companion, it omits c/z). When a
*state* is given, what the driver knew about the microscope at capture time is
printed beside the container, under ``data/metadata/ZMART_state``, so the
capture can be understood, and repeated, without the microscope.

The per-plane pixel-pull path (stream -> numpy -> OME-TIFF) is an extension
seam; see the driver README.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from ..readers.api_reader import _attr
from .naming import build_state_name, data_dir, state_dir
from .product import Naming, SavedAcquisition


def _czi_name(naming: Naming) -> str:
    """CZI filename: ``{acquisition_type}_{hash}_{position_label}.czi``.

    Minimal compatibility naming for the existing flat contract. The
    full Zeiss flat/state alignment is deferred; this only tracks the shared
    field set so the driver keeps building valid names.
    """
    n = naming
    return f"{n.acquisition_type}_{n.hash6}_{n.position_label}.czi"


def _resolve_czi_path(client, output_name: str) -> Path:
    """Ask ZEN for the on-disk path of the CZI it wrote for ``output_name``."""
    resp = client.submit(
        client.experiment.get_image_output_path(client.messages.image_output_path(output_name))
    )
    if isinstance(resp, (str, Path)):
        return Path(resp)
    path = _attr(resp, "path", "output_path", "image_output_path")
    if path is None:
        raise RuntimeError(f"ZEN did not return an output path for {output_name!r}")
    return Path(path)


def _wait_stable(path: Path, *, timeout_s: float = 60.0, poll_s: float = 0.5) -> None:
    """Block until ``path`` exists and its size is unchanged across two polls."""
    deadline = time.perf_counter() + timeout_s
    last_size = -1
    while time.perf_counter() < deadline:
        if path.exists():
            size = path.stat().st_size
            if size == last_size:
                return
            last_size = size
        time.sleep(poll_s)
    raise TimeoutError(f"CZI did not stabilize within {timeout_s}s: {path}")


def save(
    client,
    acq,
    output_root,
    naming: Naming,
    *,
    state: dict | None = None,
    stable_timeout_s: float = 60.0,
    stable_poll_s: float = 0.5,
) -> SavedAcquisition:
    """Copy the acquisition's CZI into ``output_root`` under the canonical layout.

    Args:
        client: the ZenClient.
        acq: an ``AcquisitionResult`` (must carry ``output_name``).
        output_root: the run root (a CZI lands under ``<kind>/data/``).
        naming: the driver's :class:`Naming` for this acquisition.
        state: what the driver knows about the microscope at capture time
            (the controller passes its state and position); printed beside
            the CZI under ``data/metadata/ZMART_state``. None prints nothing.

    Returns:
        ``SavedAcquisition`` with the persisted ``czi_path`` and ``state_path``.
    """
    if not getattr(acq, "output_name", None):
        raise ValueError("acquisition has no output_name; nothing to resolve/save")

    src = _resolve_czi_path(client, acq.output_name)
    _wait_stable(src, timeout_s=stable_timeout_s, poll_s=stable_poll_s)

    destination = data_dir(output_root, naming.acquisition_type)
    destination.mkdir(parents=True, exist_ok=True)
    dst = destination / _czi_name(naming)
    shutil.copy2(src, dst)

    state_path = None
    if state is not None:
        state_path = state_dir(output_root, naming.acquisition_type) / build_state_name(naming)
        _write_json_atomic(
            state_path,
            {
                "acquisition_type": naming.acquisition_type,
                "position_label": naming.position_label,
                "hash6": naming.hash6,
                "experiment_id": acq.experiment_id,
                "output_name": acq.output_name,
                "images": [dst.name],
                "started_at": acq.started_at,
                "finished_at": acq.finished_at,
                "state": state,
            },
        )
    return SavedAcquisition(czi_path=dst, naming=naming, state_path=state_path)


def _write_json_atomic(path: Path, payload: dict) -> None:
    """Write the file completely or not at all, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    os.replace(str(tmp), str(path))
