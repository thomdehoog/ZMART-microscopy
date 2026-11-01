"""Small real viewer/HTTP publication failure; all data lives in a test folder."""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

# The workflow is imported by its own folder's name, the way the bridge
# imports it: the folder of workflows it sits in goes on the search path.
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from target_acquisition.storage import viewer_service as service  # noqa: E402
from target_acquisition.storage.images import declare_image  # noqa: E402
from target_acquisition.storage.zarr_positions import (  # noqa: E402
    _describe_mean_pyramid,
)

root = Path(sys.argv[1])


def write(kind, name, x, sampling, value):
    store = root / kind / f"{name}.ome.zarr"
    arrays = declare_image(
        store, canvas_shape=(1, 32, 32), frames=1, channels=1,
        dtype="uint16", chunk=32, levels=2, voxel_size_um=(1, sampling, sampling),
        first_voxel_um=(0, sampling / 2, x + sampling / 2), ome_zarr_version="0.5",
        channel_blocks=[{"label": "signal", "color": "FFFFFF",
                         "window": {"start": 0, "end": 255, "min": 0, "max": 65535}}],
    )
    for array in arrays:
        array[:] = value
    metadata = store / "zarr.json"
    description = json.loads(metadata.read_text())
    _describe_mean_pyramid(description)
    metadata.write_text(json.dumps(description))
    service.a_position_landed(kind, store.parent, store=store)


def flush():
    pending = set(service._viewer["pending"])
    service._viewer["pending"].clear()
    assert service._publish_once(service._viewer["wake"], pending)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(service.status()).encode())

    def do_POST(self):
        if self.path == "/fail":
            write("overview", "second", 40, 1.01, 180)
            write("targets", "first", 96, 1, 240)
        elif self.path == "/recover":
            write("overview", "second", 40, 1, 180)
        else:
            self.send_error(404)
            return
        flush()
        self.do_GET()


# Drive the publisher synchronously so the test controls arrival, not timing.
with patch.object(service, "_publish_changes", lambda wake: None):
    service.start(root, bake=sys.argv[2] == "true", canvas={"x_um": [0, 160], "y_um": [0, 64]})
assert service.status()["running"], service.status()
write("overview", "first", 0, 1, 120)
flush()
server = HTTPServer(("127.0.0.1", 0), Handler)
print(json.dumps({"url": f"http://127.0.0.1:{server.server_address[1]}"}), flush=True)
try:
    server.serve_forever()
finally:
    service.stop()
    server.server_close()
