"""Small acquire/save helper for example scripts."""

from __future__ import annotations

from itertools import count
from pathlib import Path
from typing import Any

import tifffile

from shared.output_layout import Naming, run_hash

_COUNTER = count()


def acquire_saved_frame(
    drv: Any,
    client: Any,
    job: str,
    output_root: str | Path,
    *,
    acquisition_type: str,
    c: int = 0,
    z: int = 0,
    t: int = 0,
):
    """Acquire/save all exported planes, then load one explicit plane."""
    idx = next(_COUNTER)
    naming = Naming(
        acquisition_type=acquisition_type,
        hash6=run_hash(),
        p=idx,
    )
    acq = drv.acquire(client, job)
    saved = drv.save(
        client,
        acq,
        Path(output_root) / "driver-save",
        naming,
    )
    plane = drv.PlaneIndex(t=t, z=z, c=c)
    path = saved.image_paths[plane]
    return tifffile.imread(path), path
