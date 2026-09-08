"""Two real position stores, with an optional same-shape rewrite of the first."""

import sys
from pathlib import Path

import numpy as np
import zarr

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from zmart_storage.canvas import _declare_one  # noqa: E402

folder = Path(sys.argv[1])
if len(sys.argv) > 2:
    image = np.zeros((1, 1, 1, 64, 64), dtype=np.uint16)
    image[..., 32:] = 240
    zarr.open_array(str(folder / "P0.ome.zarr" / "0"), mode="r+")[:] = image
else:
    for i in range(2):
        arrays = _declare_one(
            folder / f"P{i}.ome.zarr",
            canvas_shape=(1, 64, 64),
            frames=1,
            channels=1,
            dtype="uint16",
            chunk=64,
            levels=1,
            voxel_size_um=(1, 1, 1),
            origin_um=(0, 0, i * 96),
            channel_blocks=[
                {
                    "label": "signal",
                    "color": "FFFFFF",
                    "window": {"start": 0, "end": 255, "min": 0, "max": 65535},
                }
            ],
            ome_zarr_version="0.5",
        )
        image = np.zeros((1, 1, 1, 64, 64), dtype=np.uint16)
        image[..., :32] = 240
        arrays[0][:] = image
