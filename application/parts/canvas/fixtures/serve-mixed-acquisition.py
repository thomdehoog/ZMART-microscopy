"""Real shared aggregates for the operator's mixed-depth browser proof."""

import json
import sys
from pathlib import Path

import zarr
from zmart_viewer.server import make_server

from application.parts.storage.viewer_service import _allow_the_page_to_read
from zmart_storage.canvas import _declare_one

folder = Path(sys.argv[1])
for name, depth, x, z, reference in (() if "--existing" in sys.argv else (
    ("flat", 1, 0, 75, 75),
    ("stack", 3, 128, 60, 61.3),
    ("black", 3, 0, 200, 201.3),
)):
    store = folder / f"{name}.ome.zarr"
    _declare_one(
        store, canvas_shape=(depth, 64, 64), frames=1, channels=2,
        dtype="uint16", chunk=64, levels=3, voxel_size_um=(1.3, 1, 1),
        origin_um=(z, 0, x), channel_blocks=[{"label": "red"}, {"label": "green"}],
        ome_zarr_version="0.5",
    )
    group = zarr.open_group(str(store), mode="r+")
    ome = group.attrs["ome"]
    ome["multiscales"][0]["type"] = "mean"
    group.attrs["ome"] = ome
    group.attrs["zmart_microscopy"] = {"z_coordinate": {
        "frame": "specimen", "acquisition_provenance": {"requested_stage_focus_z_um": reference},
    }}
    for plane in range(depth):
        for level in range(3):
            group[str(level)][:, :, plane] = 0 if name == "black" else (80 if depth == 1 else 40 + 60 * plane)

server = make_server(port=0, data_dir=folder, live=True, allow_open=True,
                     transparent_background=True, window=(0, 255))
_allow_the_page_to_read(server)
print(json.dumps({"url": f"http://127.0.0.1:{server.server_address[1]}"}), flush=True)
server.serve_forever()
