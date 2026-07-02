"""Headless validation of the resident command-server script's Qt half.

Runs the real command server (QTcpServer + QTimer poll + JSON dispatch +
_CoreBridge) against a FAKE mesoSPIM Core, driven by the real MesospimClient over
a localhost socket. mesoSPIM-control itself is not vendored (GPL), so the fake
Core stands in for it; the Core method/signal names it exercises were separately
verified against mesoSPIM-control v1.20.0 source. This proves everything in the
server EXCEPT the actual Core executing the calls -- the one remaining `-D`-demo
bench step (see README.md).

Run (needs PyQt5; no display required thanks to the offscreen platform):

    QT_QPA_PLATFORM=offscreen python zmart_drivers/mesospim/server/validate_headless.py

Author: Thom de Hoog (ZMB, University of Zurich). GPL-3.0 (loads the GPL server).
"""

import importlib.util
import sys
import threading
from pathlib import Path

# mesoSPIM-control is Windows-only, where the console defaults to cp1252 and
# cannot encode the PASS/FAIL emoji in the result line -- which would crash this
# validator at the very end even when every check passed. Re-encode our own
# stdout/stderr as UTF-8 (dropping to a replacement char if even that fails) so
# the report always prints on the target platform.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

_HERE = Path(__file__).resolve()
_DRIVERS_DIR = _HERE.parents[2]  # server -> mesospim -> zmart_drivers

# Real driver client (MIT).
sys.path.insert(0, str(_DRIVERS_DIR))
from mesospim.connection.client import MesospimClient  # noqa: E402

# Load the resident server script as a module (its `if "self" in dir()` guard
# means importing it does NOT start a server).
_SERVER = _HERE.parent / "mesospim_command_server.py"
spec = importlib.util.spec_from_file_location("mesospim_command_server", _SERVER)
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)

from PyQt5 import QtCore, QtWidgets  # noqa: E402


class FakeSignal:
    """Minimal stand-in for a pyqtSignal: emit() runs a bound handler."""

    def __init__(self, handler=None):
        self._handler = handler or (lambda *a: None)

    def emit(self, *args):
        self._handler(*args)


class FakeCfg:
    # Attribute names/shapes match mesoSPIM-control 1.20.0's config module (what
    # _CoreBridge.config()/_camera() actually read): laserdict, zoomdict + a
    # separate pixelsize dict, shutteroptions, camera_parameters.
    laserdict = {"488 nm": "PXI1Slot4/port0/line3", "561 nm": "PXI1Slot4/port0/line4"}
    filterdict = {"Empty": 0, "515/30": 1}
    zoomdict = {"1x": 2707, "2x": 1706}
    pixelsize = {"1x": 6.55, "2x": 3.26}
    shutteroptions = ("Left", "Right")
    camera_parameters = {"x_pixels": 2048, "y_pixels": 2048}


class FakeCore:
    """A duck-typed mesoSPIM_Core with the exact surface _CoreBridge uses."""

    def __init__(self):
        self.cfg = FakeCfg()
        self.state = {
            "state": "idle",
            "position": {k: 0.0 for k in ("x_pos", "y_pos", "z_pos", "f_pos", "theta_pos")},
            "laser": "488 nm",
            "intensity": 5.0,
            "filter": "515/30",
            "zoom": "1x",
            "shutterconfig": "Left",
            "etl_l_amplitude": 1.0,
            "etl_l_offset": 2.0,
            "etl_r_amplitude": 1.0,
            "etl_r_offset": 2.0,
        }
        self.sig_stop_movement = FakeSignal()
        self.sig_state_request_and_wait_until_done = FakeSignal(self._apply_state)

    def _apply_state(self, settings):
        self.state.update(settings)

    def move_absolute(self, sdict, wait_until_done=False, use_internal_position=True):
        for key, val in sdict.items():
            axis = key.replace("_abs", "")
            self.state["position"][f"{axis}_pos"] = float(val)

    def move_relative(self, ddict, wait_until_done=False):
        for key, val in ddict.items():
            axis = key.replace("_rel", "")
            self.state["position"][f"{axis}_pos"] += float(val)

    def zero_axes(self, axes):
        for axis in axes:
            self.state["position"][f"{axis}_pos"] = 0.0


results = {}


def drive(port):
    c = MesospimClient("127.0.0.1", port, timeout=3.0)
    c.connect()
    try:
        results["hello"] = dict(c.server_info)
        results["ping_ok"] = c.request("ping").ok
        results["config"] = c.request("get_config").data
        c.request("move_absolute", targets={"x": 111.0, "z": 42.0})
        results["pos_after_abs"] = c.request("get_position").data
        c.request("move_relative", deltas={"x": 9.0})
        results["pos_after_rel"] = c.request("get_position").data
        c.request("set_state", settings={"filter": "Empty", "intensity": 77.0})
        results["state_after_set"] = c.request("get_state").data
        # get_state's `position` block must be normalised to axis names
        # (x,y,z,f,theta), same as get_position -- not the Core's raw 'x_pos' keys.
        results["state_position"] = (results["state_after_set"].get("position") or {})
        c.request("zero", axes=["x", "z"])
        results["pos_after_zero"] = c.request("get_position").data
        results["stop_ok"] = c.request("stop").ok
        results["nak"] = c.try_request("bogus").ok
    finally:
        c.close()
    results["done"] = True


def main():
    app = QtWidgets.QApplication(sys.argv)
    core = FakeCore()
    holder = QtCore.QObject()  # parent for the server's QTcpServer/QTimer
    core_like = core
    # The server parents QTcpServer/QTimer to the object passed in; pass a real
    # QObject so Qt ownership is valid, but give the bridge our fake core.
    server = srv.MesospimCommandServer.__new__(srv.MesospimCommandServer)
    from PyQt5 import QtNetwork

    server._QtCore = QtCore
    server._QtNetwork = QtNetwork
    server.bridge = srv._CoreBridge(core_like)
    server._server = QtNetwork.QTcpServer(holder)
    assert server._server.listen(QtNetwork.QHostAddress("127.0.0.1"), 0)
    port = server._server.serverPort()
    server._conn = None
    server._buf = b""
    server._busy = False
    server._timer = QtCore.QTimer(holder)
    server._timer.timeout.connect(server._poll)
    server._timer.start(10)

    threading.Thread(target=drive, args=(port,), daemon=True).start()

    def check():
        if results.get("done"):
            app.quit()

    watchdog = QtCore.QTimer()
    watchdog.timeout.connect(check)
    watchdog.start(20)
    QtCore.QTimer.singleShot(8000, app.quit)  # hard stop
    app.exec_()

    ok = True
    print("hello       :", results.get("hello"))
    print("ping ok     :", results.get("ping_ok"))
    cfg = results.get("config", {})
    print("config keys :", sorted(cfg))
    print("  lasers    :", cfg.get("lasers"))
    print("  camera    :", cfg.get("camera"))
    print("pos abs     :", results.get("pos_after_abs"), "(expect x=111, z=42)")
    print("pos rel     :", results.get("pos_after_rel"), "(expect x=120)")
    print("state set   :", {k: results.get("state_after_set", {}).get(k) for k in ("filter", "intensity")}, "(expect Empty/77)")
    print("state pos   :", sorted(results.get("state_position", {})), "(expect x,y,z,f,theta axis keys)")
    print("pos zero    :", results.get("pos_after_zero"), "(expect x=0, z=0)")
    print("stop ok     :", results.get("stop_ok"))
    print("bogus is nak:", results.get("nak") is False)

    checks = [
        results.get("ping_ok") is True,
        results.get("pos_after_abs", {}).get("x") == 111.0,
        results.get("pos_after_abs", {}).get("z") == 42.0,
        results.get("pos_after_rel", {}).get("x") == 120.0,
        results.get("state_after_set", {}).get("filter") == "Empty",
        results.get("state_after_set", {}).get("intensity") == 77.0,
        results.get("pos_after_zero", {}).get("x") == 0.0,
        results.get("stop_ok") is True,
        results.get("nak") is False,
        bool(cfg.get("lasers")),
        {"x", "y", "z", "f", "theta"} <= set(results.get("state_position", {})),
    ]
    ok = all(checks) and results.get("done")
    print("\nRESULT:", "PASS ✅" if ok else f"FAIL ❌ ({checks})")
    server.stop()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
