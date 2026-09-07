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

# Two jobs more than the configuration walk needs, for target acquisition:
# a focussing job on the 10x that takes a z-stack, and a target job on the
# 40x. The stack is stated the way LAS X states it, begin and end in
# absolute z-wide with a number of sections, and it follows the z-wide
# drive: when the driver focuses somewhere, the stack re-centres there.
import copy  # noqa: E402

STACK_HALF_UM, STACK_SECTIONS = 10.0, 21
client._jobs["Focussing"] = copy.deepcopy(client._jobs["Overview"])
client._jobs["Focussing"]["stack"] = {"begin": -STACK_HALF_UM, "end": STACK_HALF_UM,
                                      "sections": STACK_SECTIONS, "stepSize": 1.0, "size": 2 * STACK_HALF_UM}
client._jobs["Target"] = copy.deepcopy(client._jobs["HiRes"])
_move_z = client._handle_move_z


def _move_z_and_recentre(model, job):
    _move_z(model, job)
    stack = job.get("stack") or {}
    if stack.get("sections"):
        z = float(job["zPosition"]["z-wide"]["position"])
        half = (float(stack["end"]) - float(stack["begin"])) / 2
        stack["begin"], stack["end"] = z - half, z + half


client._handle_move_z = _move_z_and_recentre


def focus(job_name: str) -> None:
    """The operator focuses in LAS X: the job's z-wide goes to where the
    sample is sharp under the job's own lens, and a stack the job takes
    re-centres there."""
    from zmart_drivers.mock import mock_driver
    job = client._jobs[job_name]
    x, y = client._stage_x * 1e6, client._stage_y * 1e6
    slot = job["objective"]["slotIndex"]
    sharp = mock_driver.sharp_height_um(x, y) + walk.OFFSET_UM[slot][2]
    job["zPosition"]["z-wide"]["position"] = sharp
    stack = job.get("stack") or {}
    if stack.get("sections"):
        half = (float(stack["end"]) - float(stack["begin"])) / 2
        stack["begin"], stack["end"] = sharp - half, sharp + half


def camera(root):
    """What LAS X native AutoSave writes after an acquire: the sample as seen
    from where the stage stands, through the job's lens, by the camera as
    mounted -- one plane, or one per section when the job takes a stack."""
    import numpy as np
    import tifffile
    from zmart_drivers.mock import mock_driver, mock_setup

    def collect(client, acq, **_kw):
        job = client._jobs[acq.job]
        x, y = client._stage_x * 1e6, client._stage_y * 1e6
        slot = job["objective"]["slotIndex"]
        pixel = float(job["pixelSize"].split()[0])
        frame_px = int(job["format"].split()[0])
        dx, dy, dz = walk.OFFSET_UM[slot]
        stack = job.get("stack") or {}
        if stack.get("sections"):
            heights = list(np.linspace(float(stack["begin"]), float(stack["end"]), int(stack["sections"])))
        else:
            heights = [float(job["zPosition"]["z-wide"]["position"])]
        folder = root / "autosave" / f"{acq.job}-{acq.started_at:.6f}"
        folder.mkdir(parents=True)
        planes = {}
        for index, z in enumerate(heights):
            aligned = mock_driver._the_sample_from(np, x + dx, y + dy, z - dz, 0, frame_px=frame_px, pixel_um=pixel)
            raw = mock_setup.as_the_camera_records(np, aligned, walk.CAMERA)
            path = folder / f"image--Z{index:02d}--C00.ome.tif"
            tifffile.imwrite(str(path), raw)
            planes[walk.product.PlaneIndex(0, index, 0)] = walk.product.PlaneSource(path=path)
        step = (heights[-1] - heights[0]) / (len(heights) - 1) if len(heights) > 1 else None
        return walk.product.ExportedAcquisition(
            source_root=folder.parent, source_dir=folder,
            positions=[walk.product.ExportedPosition(t=0, planes=planes)],
            metadata=walk.product.AcquisitionMetadata(
                size_x=frame_px, size_y=frame_px, size_t=1, size_z=len(heights), size_c=1, pixel_type="uint16",
                physical_size_x_um=pixel, physical_size_y_um=pixel, physical_size_z_um=step,
                channels=(walk.product.ChannelMetadata(index=0, name="C0"),)),
            method="test camera", source_exporter="lasx_native_autosave", vendor_metadata_sources=(),
        )
    return collect

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
    patch.object(walk._save, "collect_lasx_native_autosave", camera(camera_root)),
    patch.object(walk.materialize._ome, "check_ome_tiff", return_value=healthy),
    patch.object(walk.materialize._ome, "check_ome_xml_file", return_value=healthy),
):
    p.start()


def configure() -> dict:
    """Publish a whole configuration through the setup seam, the way the
    driver's configuration-walk test does: limits from four corners, the
    origin at a field with structure, the orientation, and the 10x-40x pair.
    For a walk that starts on a configured machine, as target acquisition
    does, without walking the configuration workflow first."""
    from zmart_drivers.setup import procedures
    seam = walk.seam
    into = Path(tempfile.mkdtemp(prefix="zmart-leica-configure-"))
    instrument = next(i for i in seam.get_instruments() if i["vendor"] == "leica")
    setup = seam.open_setup(instrument)
    started = setup.new_configuration()
    corners = [(5000.0, 6000.0), (110000.0, 6000.0), (5000.0, 70000.0), (110000.0, 70000.0)]
    read = [setup.move(x, y, 0.0) for x, y in corners]
    limits = dict(setup.read("limits", fresh=True)["document"])
    limits["x_um"] = {"range": [min(r["x_um"] for r in read), max(r["x_um"] for r in read)]}
    limits["y_um"] = {"range": [min(r["y_um"] for r in read), max(r["y_um"] for r in read)]}
    setup.publish("limits", limits)
    setup.move(*walk.HOME, 0.0)
    walk._the_operator_focuses(client, "Overview")
    setup.publish("origin", procedures.origin_here(setup))
    orientation = procedures.measure_orientation(setup, into=into / "orientation", stage_move_um=40.0)
    if not orientation["accepted"]:
        raise RuntimeError(f"orientation not accepted: {orientation.get('why')}")
    setup.publish("orientation", orientation["orientation"], evidence=[orientation["diagnostic"]])
    turn = orientation["orientation"]
    reference = procedures.capture_lens_view(setup, into=into / "lens", name="1-2-reference", orientation=turn)
    client._selected_job = "HiRes"
    walk._the_operator_focuses(client, "HiRes")
    target = procedures.capture_lens_view(setup, into=into / "lens", name="1-2-target", orientation=turn)
    pair = procedures.measure_objective_pair(reference, target)
    if not pair["accepted"]:
        raise RuntimeError(f"objective pair not accepted: {pair.get('why')}")
    t = pair["translation_um"]
    setup.publish("calibration", {"objectives": {
        "1": {"name": walk.JOBS["Overview"]["name"], "translation_um": [0.0, 0.0, 0.0]},
        "2": {"name": walk.JOBS["HiRes"]["name"], "translation_um": [t["x"], t["y"], t["z"]]},
    }})
    setup.close()
    walk._machine.use_configuration(None)
    client._selected_job = "Overview"
    walk._the_operator_focuses(client, "Overview")
    return {"configuration": started["id"], "translation_um": t}


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
                focus(client._selected_job)
                answer = {"x_um": client._stage_x * 1e6, "y_um": client._stage_y * 1e6}
            elif url.path == "/job":
                client._selected_job = q["name"]
                focus(q["name"])
                answer = {"job": client._selected_job}
            elif url.path == "/focus":
                focus(client._selected_job)
                answer = {"job": client._selected_job}
            elif url.path == "/where":
                answer = {"x_um": client._stage_x * 1e6, "y_um": client._stage_y * 1e6,
                          "job": client._selected_job}
            elif url.path == "/configure":
                answer = configure()
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
