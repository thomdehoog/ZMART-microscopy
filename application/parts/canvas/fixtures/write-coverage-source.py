"""A two-channel image with black acquired pixels and separately declared coverage."""

import sys
from pathlib import Path

import numpy as np
import zarr

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from zmart_storage.canvas import _declare_one  # noqa: E402

store = Path(sys.argv[1]) / "signal.ome.zarr"
rewritten = len(sys.argv) > 2
for target in (store, store / "coverage"):
    if not rewritten:
        _declare_one(
            target, canvas_shape=(1, 64, 256), frames=1, channels=2,
            dtype="uint16", chunk=64, levels=1,
            voxel_size_um=(1, 1, 1), origin_um=(0, 0, 0),
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
