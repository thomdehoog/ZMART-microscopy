"""A two-channel image with black acquired pixels and separately declared coverage."""

import sys
from pathlib import Path

import numpy as np
import zarr

# The workflow is imported by its own folder's name, the way the bridge
# imports it: the folder of workflows it sits in goes on the search path.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from target_acquisition.storage.images import declare_image  # noqa: E402

store = Path(sys.argv[1]) / "signal.ome.zarr"
rewritten = len(sys.argv) > 2
for target in (store, store / "coverage"):
    if not rewritten:
        declare_image(
            target, canvas_shape=(1, 64, 256), frames=1, channels=2,
            dtype="uint16", chunk=64, levels=1,
            voxel_size_um=(1, 1, 1), first_voxel_um=(0, 0.5, 0.5),
            channel_blocks=[{"label": "red"}, {"label": "green"}],
            ome_zarr_version="0.5",
        )
    data = np.zeros((1, 2, 1, 64, 256), dtype=np.uint16)
    if target == store:
        data[:, :, :, 32:, :64] = 240
        if rewritten:
            data[:, 0] = 0
    else:
        data[..., :64] = 1
        if rewritten:
            data[..., 128:192] = 1
    zarr.open_array(str(target / "0"), mode="r+")[:] = data
