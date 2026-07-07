"""Persist an acquired CZI into the workflow output layout.

ZEN writes one CZI container on the acquisition PC; ``save`` resolves that path
via ``get_image_output_path``, waits for the file to stop growing, and copies it
into the canonical ``data/`` directory under ``output_root`` using the
lab-wide :class:`~shared.output_layout.Naming` slots (with a ``.czi`` extension,
since a CZI holds the whole c x z grid -- like the XML companion, it omits c/z).

The per-plane pixel-pull path (stream -> numpy -> OME-TIFF) is an extension
seam; see the driver README.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from shared.output_layout.naming import acquisition_data_dir

from ..readers.api_reader import _attr
from .product import Naming, SavedAcquisition


def _czi_name(naming: Naming) -> str:
    """CZI filename: ``{acquisition_type}_{hash}_{position_label}.czi``.

    Minimal compatibility port to the shared ``Naming`` (flat contract). The
    full Zeiss flat/state alignment is deferred; this only tracks the shared
    field set so the driver keeps building valid names.
    """
    n = naming
    return f"{n.acquisition_type}_{n.hash6}_{n.position_label}.czi"


def _resolve_czi_path(client, output_name: str) -> Path:
    """Ask ZEN for the on-disk path of the CZI it wrote for ``output_name``."""
    resp = client.submit(client.experiment.get_image_output_path(client.messages.image_output_path(output_name)))
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
    stable_timeout_s: float = 60.0,
    stable_poll_s: float = 0.5,
) -> SavedAcquisition:
    """Copy the acquisition's CZI into ``output_root`` under the canonical layout.

    Args:
        client: the ZenClient.
        acq: an ``AcquisitionResult`` (must carry ``output_name``).
        output_root: the run root (a CZI lands under ``<kind>/data/``).
        naming: the canonical :class:`Naming` for this acquisition.

    Returns:
        ``SavedAcquisition`` with the persisted ``czi_path``.
    """
    if not getattr(acq, "output_name", None):
        raise ValueError("acquisition has no output_name; nothing to resolve/save")

    src = _resolve_czi_path(client, acq.output_name)
    _wait_stable(src, timeout_s=stable_timeout_s, poll_s=stable_poll_s)

    data_dir = acquisition_data_dir(output_root, naming.acquisition_type)
    data_dir.mkdir(parents=True, exist_ok=True)
    dst = data_dir / _czi_name(naming)
    shutil.copy2(src, dst)

    return SavedAcquisition(czi_path=dst, naming=naming)
