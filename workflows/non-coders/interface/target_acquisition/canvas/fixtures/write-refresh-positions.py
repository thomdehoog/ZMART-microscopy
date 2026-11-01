"""Two real position stores, with an optional same-shape rewrite of the first."""

import sys
from pathlib import Path

import numpy as np
import zarr

# The workflow is imported by its own folder's name, the way the bridge
# imports it: the folder of workflows it sits in goes on the search path.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from target_acquisition.storage.images import declare_image  # noqa: E402

folder = Path(sys.argv[1])
if len(sys.argv) > 2:
    image = np.zeros((1, 1, 1, 64, 64), dtype=np.uint16)
    image[..., 32:] = 240
    zarr.open_array(str(folder / "P0.ome.zarr" / "0"), mode="r+")[:] = image
else:
    for i in range(2):
        arrays = declare_image(
            folder / f"P{i}.ome.zarr",
            canvas_shape=(1, 64, 64),
            frames=1,
            channels=1,
            dtype="uint16",
            chunk=64,
            levels=1,
            voxel_size_um=(1, 1, 1),
            first_voxel_um=(0, 0.5, i * 96 + 0.5),
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
