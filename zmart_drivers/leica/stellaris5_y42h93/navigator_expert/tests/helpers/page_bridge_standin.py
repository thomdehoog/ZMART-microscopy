"""Start the operator page's bridge on the Leica driver, with the CAM socket
and the camera stood in for.

This is how the page is walked against this driver on a machine that has
no LAS X: application/workflows/zmart_driver_configuration/walk-leica.spec.js
starts the bridge through this file instead of bridge.py directly. The
stand-ins are the same two the driver's own configuration-walk test uses
(tests/unit/test_configuration_walk.py): MockLasxClient plays the
CAM socket, and a picture of a real micrograph is written where LAS X
native AutoSave would write the camera's pixels. Everything else the page
asks of the bridge runs through the real Leica setup driver, adapter, gate,
limits, orientation, calibration and acquisition code.

A side door on LEICA_SIDE_PORT plays the operator at LAS X: it drives
the stage, focuses, and switches the selected job. The Leica's ProgramData
is rooted wherever ZMART_MICROSCOPY_ROOT points, a folder of its own
for a walk, so nothing lands in the real one.
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

NE = Path(__file__).resolve().parents[2]
LEICA = NE.parent
REPO = NE.parents[3]
for p in (REPO, LEICA, NE / "tests" / "helpers", NE / "tests" / "unit"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.setdefault("ZMART_MICROSCOPY_ROOT", tempfile.mkdtemp(prefix="zmart-leica-root-"))

import test_configuration_walk as walk  # noqa: E402  -- the stand-ins live there

client = walk._instrument()
camera_root = Path(tempfile.mkdtemp(prefix="zmart-leica-camera-"))

# LAS X keeps its native AutoSave setting in a StartUp file under the user's
# AppData. There is no LAS X here, so that one file is written where the
# driver looks for it, saying AutoSave is on and points at the camera's
# folder: the driver then reads it exactly as it would on the instrument.
appdata = Path(tempfile.mkdtemp(prefix="zmart-leica-appdata-"))
os.environ["APPDATA"] = str(appdata)
startup = appdata / "Leica Microsystems" / "LAS X" / "StartUp"
startup.mkdir(parents=True)
(startup / "UserDataNavigatorExpert.lcf").write_text(
    f'<Config AutoSaveBaseFolder="{camera_root}" DoUseAutoSave="true" DoStoreInSeparateFolders="true" />',
    encoding="utf-8")

healthy = {"path": "x", "corrupted": False, "violations": [], "error": None}
for p in (
    patch.object(walk.drv_session, "connect_python_client", return_value=client),
    patch.object(walk._save, "collect_lasx_native_autosave", walk._camera(camera_root)),
    patch.object(walk.materialize._ome, "check_ome_tiff", return_value=healthy),
    patch.object(walk.materialize._ome, "check_ome_xml_file", return_value=healthy),
):
    p.start()


class SideDoor(BaseHTTPRequestHandler):
    def log_message(self, *_):  # quiet
        pass

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/drive":
                client._stage_x = float(q["x"]) / 1e6
                client._stage_y = float(q["y"]) / 1e6
                walk._the_operator_focuses(client, client._selected_job)
                answer = {"x_um": client._stage_x * 1e6, "y_um": client._stage_y * 1e6}
            elif url.path == "/job":
                client._selected_job = q["name"]
                walk._the_operator_focuses(client, q["name"])
                answer = {"job": client._selected_job}
            elif url.path == "/focus":
                walk._the_operator_focuses(client, client._selected_job)
                answer = {"job": client._selected_job}
            elif url.path == "/where":
                answer = {"x_um": client._stage_x * 1e6, "y_um": client._stage_y * 1e6,
                          "job": client._selected_job}
            else:
                self.send_response(404); self.end_headers(); return
            body = json.dumps(answer).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        except Exception as why:  # noqa: BLE001
            self.send_response(500); self.end_headers()
            self.wfile.write(str(why).encode())


side = HTTPServer(("127.0.0.1", int(os.environ.get("LEICA_SIDE_PORT", "8874"))), SideDoor)
threading.Thread(target=side.serve_forever, daemon=True).start()
print(f"leica stand-in: root={os.environ['ZMART_MICROSCOPY_ROOT']} side door on {side.server_address[1]}", flush=True)

import runpy  # noqa: E402

sys.argv = [str(REPO / "application" / "framework" / "bridge.py"), *sys.argv[1:]]
runpy.run_path(sys.argv[0], run_name="__main__")
