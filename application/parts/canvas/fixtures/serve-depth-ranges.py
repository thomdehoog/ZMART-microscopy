"""Two relative stack domains, with different plane spacing, for the axis proof."""

import json
import sys
from pathlib import Path

import zarr
from zmart_viewer.server import make_server

from application.parts.storage.viewer_service import _allow_the_page_to_read
from zmart_storage.canvas import _declare_one

folder = Path(sys.argv[1])
for name, depth, x, z, spacing in (("a", 11, 0, 95, 1), ("b", 3, 128, 99, 2)):
    store = folder / name / "position.ome.zarr"
    _declare_one(
        store, canvas_shape=(depth, 64, 64), frames=1, channels=1,
        dtype="uint16", chunk=64, levels=1, voxel_size_um=(spacing, 1, 1),
        origin_um=(z, 0, x), channel_blocks=[{"label": "signal"}], ome_zarr_version="0.5",
    )
    group = zarr.open_group(str(store), mode="r+")
    ome = group.attrs["ome"]
    ome["multiscales"][0]["type"] = "mean"
    group.attrs["ome"] = ome
    group.attrs["zmart_microscopy"] = {"z_coordinate": {
        "frame": "specimen", "acquisition_provenance": {"requested_stage_focus_z_um": 100},
    }}
    for plane in range(depth):
        group["0"][:, :, plane] = 40 + 10 * plane

server = make_server(port=0, data_dir=folder / "a", live=True, allow_open=True,
                     transparent_background=True, window=(0, 255))
_allow_the_page_to_read(server)
print(json.dumps({"url": f"http://127.0.0.1:{server.server_address[1]}"}), flush=True)
server.serve_forever()
