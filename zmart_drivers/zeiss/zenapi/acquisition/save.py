"""Bring an acquired CZI into the workflow's output folder.

ZEN writes every acquisition as one CZI file on the ZEN computer, in the
folder it reports through ``GetImageOutputPath``, named after the acquisition's
``output_name``. ``save`` resolves that file, waits for it to stop growing
(ZEN may still be flushing it), and copies it into ``<output_root>/<type>/data/``
under the driver's :class:`Naming` slots. A CZI holds the whole channel x Z
grid, so like the Leica XML companion the name omits c/z.

When ZMART runs on another computer than ZEN, the ZEN folder must be reachable
as a network share for the copy to work; ``zen_image_path`` gives the path to
look for when it is not.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from ..readers.api_reader import get_image_output_path
from .naming import data_dir
from .product import Naming, SavedAcquisition


def _czi_name(naming: Naming) -> str:
    """CZI filename: ``{acquisition_type}_{hash}_{position_label}.czi``.

    Minimal compatibility naming for the existing flat contract. The
    full Zeiss flat/state alignment is deferred; this only tracks the shared
    field set so the driver keeps building valid names.
    """
    n = naming
    return f"{n.acquisition_type}_{n.hash6}_{n.position_label}.czi"


def zen_image_path(client, output_name: str) -> Path:
    """Where ZEN wrote the CZI for ``output_name``: ``<image output folder>/<output_name>.czi``."""
    folder = get_image_output_path(client)
    if not folder:
        raise RuntimeError("ZEN did not report an image output folder")
    return Path(folder) / f"{output_name}.czi"


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
    raise TimeoutError(
        f"CZI did not appear or did not stop growing within {timeout_s}s: {path}. "
        "If ZMART runs on another computer than ZEN, the ZEN image folder must "
        "be reachable from here (for example as a network share)."
    )


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
        output_root: the run root (a CZI lands under ``<type>/data/``).
        naming: the driver's :class:`Naming` for this acquisition.

    Returns:
        ``SavedAcquisition`` with the persisted ``czi_path``.
    """
    if not getattr(acq, "output_name", None):
        raise ValueError("acquisition has no output_name; nothing to resolve/save")

    src = zen_image_path(client, acq.output_name)
    _wait_stable(src, timeout_s=stable_timeout_s, poll_s=stable_poll_s)

    destination = data_dir(output_root, naming.acquisition_type)
    destination.mkdir(parents=True, exist_ok=True)
    dst = destination / _czi_name(naming)
    shutil.copy2(src, dst)

    return SavedAcquisition(czi_path=dst, naming=naming)
