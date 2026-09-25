"""The bridge: a small server that runs inside NIS-Elements.

NIS-Elements ships its own Python, and every NIS macro function (``StgMoveXY``,
``Capture``, ``ImageSaveAs`` ...) is also exported by ``g5_regprocs.dll``. This
module calls those functions through ``ctypes`` and answers requests from the
client over a local socket (``127.0.0.1`` only). ``start_bridge.mac`` starts it;
``install_macros.py`` writes that macro.

Rules that keep it safe:

* Only the operations in :data:`OPS` can be called. No macro text is executed.
* Every NIS call runs on the NIS main thread. ``Capture`` from any other thread
  crashes NIS-Elements, so socket threads only queue requests, and the macro
  loop runs them by calling :func:`pump`.
* One call at a time: the queue is drained by that single thread.

Standard library only (NIS 6.10 bundles Python 3.12 with numpy and nothing else).
Tests replace :class:`NisApi` with a fake; see ``nis_bridge/fake.py``.
"""

from __future__ import annotations

import ctypes as ct
import logging
import os
import queue
import socketserver
import sys
import tempfile
import threading
import time
from typing import Any

from .protocol import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    PROTOCOL_VERSION,
    ProtocolError,
    decode_request,
    encode_error,
    encode_reply,
)

BRIDGE_VERSION = "0.2.0"  # of the server inside NIS, reported by ping; not the package

log = logging.getLogger("nis_bridge.bridge")

# Return codes of NIS device functions. 1 and 2 mean success.
DR_CODES = {
    1: "DR_OK",
    2: "DR_PARTIALLYOK",
    0: "DR_CANCELED",
    -1: "DR_UNKNOWNERROR",
    -2: "DR_BADPARAMETER",
    -3: "DR_NOTSUPPORTED",
    -4: "DR_NOTAVAILABLE",
    -5: "DR_NOTAUTOMATIC",
    -6: "DR_NOTCALIBRATED",
    -7: "DR_NOTINITIALIZED",
}

TIFF_ALL_LAYERS = 18  # ImageSaveAs file type
CLOSE_WITHOUT_ASKING = 2  # CloseCurrentDocument argument
INFOSTR_VERSION = 1  # Get_InfoStr: the NIS version string

# Stg_GetPFSStatus values.
PFS_STATUS = {
    -1: "error or not connected",
    0: "off, in range",
    1: "on, focused",
    3: "off, out of range",
    4: "off, PFS optics not set (dichroic mirror out)",
    5: "on, searching",
    6: "on, search stopped (cannot find focus)",
    7: "disabled, objective not supported",
}


class NisError(RuntimeError):
    """A NIS function returned an error code."""


def _check(rc: int, what: str) -> None:
    if rc not in (1, 2):
        raise NisError(f"{what}: {DR_CODES.get(rc, 'unknown code')} ({rc})")


def _check_negative(value: int, what: str) -> int:
    """Raise for a negative DR code, which every NIS function uses for failure.

    For functions whose success value is a count, or is not documented.
    """
    if value < 0:
        _check(value, what)
    return int(value)


# ---------------------------------------------------------------------------
# NIS functions, one small method each. Signatures come from the macro
# reference installed with NIS (Docs/nis/eng_ar). Units: micrometres.
# ---------------------------------------------------------------------------


class NisApi:
    def __init__(self) -> None:
        self._dll = ct.cdll.g5_regprocs
        self._functions: dict[str, Any] = {}

    def _fn(self, name: str, argtypes: list, restype: Any = ct.c_int32) -> Any:
        if name not in self._functions:
            fn = getattr(self._dll, name)
            fn.argtypes, fn.restype = argtypes, restype
            self._functions[name] = fn
        return self._functions[name]

    def version(self) -> str:
        buf = ct.create_unicode_buffer(64)
        self._fn("Get_InfoStr", [ct.c_int32, ct.c_wchar_p])(INFOSTR_VERSION, buf)
        return buf.value

    # stage
    def get_position(self) -> dict[str, float]:
        x, y, z = ct.c_double(), ct.c_double(), ct.c_double()
        fn = self._fn("StgGetPos", [ct.POINTER(ct.c_double)] * 3)
        _check(fn(ct.byref(x), ct.byref(y), ct.byref(z)), "StgGetPos")
        return {"x": x.value, "y": y.value, "z": z.value}

    def get_limits(self) -> dict[str, dict[str, float]]:
        x0, y0, x1, y1 = (ct.c_double() for _ in range(4))
        fn = self._fn("StgXY_GetLimits", [ct.POINTER(ct.c_double)] * 4)
        _check(fn(ct.byref(x0), ct.byref(y0), ct.byref(x1), ct.byref(y1)), "StgXY_GetLimits")
        z0, z1 = ct.c_double(), ct.c_double()
        fn = self._fn("StgZ_GetLimits", [ct.POINTER(ct.c_double)] * 2)
        _check(fn(ct.byref(z0), ct.byref(z1)), "StgZ_GetLimits")
        return {
            "x": {"min": x0.value, "max": x1.value},
            "y": {"min": y0.value, "max": y1.value},
            "z": {"min": z0.value, "max": z1.value},
        }

    def move_xyz(self, x: float, y: float, z: float) -> None:
        fn = self._fn("StgMove", [ct.c_double, ct.c_double, ct.c_double, ct.c_int32])
        _check(fn(x, y, z, 0), "StgMove")

    def move_xy(self, x: float, y: float) -> None:
        _check(self._fn("StgMoveXY", [ct.c_double, ct.c_double, ct.c_int32])(x, y, 0), "StgMoveXY")

    def move_z(self, z: float) -> None:
        _check(self._fn("StgMoveZ", [ct.c_double, ct.c_int32])(z, 0), "StgMoveZ")

    # optical configurations and camera
    def optical_configurations(self) -> list[str]:
        count = self._fn("GetOptConfCount", [])()
        get_name = self._fn("GetOptConfName", [ct.c_int32, ct.c_wchar_p, ct.c_int32])
        names = []
        for index in range(max(count, 0)):
            buf = ct.create_unicode_buffer(256)
            get_name(index, buf, 256)
            names.append(buf.value)
        return names

    def select_optical_configuration(self, name: str) -> None:
        _check_negative(self._fn("SelectOptConf", [ct.c_wchar_p])(name), f"SelectOptConf({name})")

    def set_exposure_ms(self, exposure_ms: float) -> float:
        """Set the camera exposure; return the value NIS applied (it may round it).

        Not exported by the DLL; NIS registers it internally and ``nis.call_proc``
        reaches it by name. It answers with a list: the return value, then each
        argument as it is after the call. (Reading the exposure with
        ``Camera_ExposureGet`` opens a blocking dialog in NIS, so it is never used.)
        """
        import nis  # exists only inside NIS-Elements

        out = nis.call_proc("Camera_ExposureSet", float(exposure_ms))
        out = list(out) if isinstance(out, (list, tuple)) else [out]
        return float(out[1]) if len(out) > 1 else float(exposure_ms)

    # nosepiece
    def nosepiece_present(self) -> bool:
        return bool(self._fn("Stg_IsNosepiecePresent", [])())

    def nosepiece_count(self) -> int:
        count = self._fn("Stg_GetNosepiecePositions", [])()
        return _check_negative(count, "Stg_GetNosepiecePositions")

    def nosepiece_position(self) -> int:
        position = self._fn("Stg_GetNosepiecePosition", [])()
        return _check_negative(position, "Stg_GetNosepiecePosition")

    def objective_name(self, position: int) -> str:
        buf = ct.create_unicode_buffer(256)
        fn = self._fn("Stg_GetNosepieceObjectiveName", [ct.c_int32, ct.c_wchar_p, ct.c_int32])
        _check(fn(position, buf, 256), f"Stg_GetNosepieceObjectiveName({position})")
        return buf.value

    def set_nosepiece_position(self, position: int) -> None:
        fn = self._fn("Stg_SetNosepiecePosition", [ct.c_int32])
        _check(fn(position), f"Stg_SetNosepiecePosition({position})")

    # focus
    def pfs_present(self) -> bool:
        return bool(self._fn("Stg_IsPFSPresent", [])())

    def pfs_status(self) -> int:
        return int(self._fn("Stg_GetPFSStatus", [])())

    def set_pfs(self, on: bool) -> None:
        _check_negative(
            self._fn("Stg_SetPFSStatus", [ct.c_int32])(1 if on else 0), "Stg_SetPFSStatus"
        )

    def wait_for_pfs(self, timeout_s: float) -> None:
        self._fn("Stg_WaitForPFS", [ct.c_double])(timeout_s)

    def autofocus(self, range_um: float, speed: int) -> int:
        """Image-based focus sweep over ``range_um`` around the current Z; 1 = found."""
        return int(self._fn("StgFocusInRangeEx", [ct.c_double, ct.c_double])(range_um, speed))

    # images
    def capture(self) -> None:
        # Checked, so that a failed capture never lets the save and close that follow
        # act on another image open in NIS, such as the operator's own.
        _check_negative(self._fn("Capture", [])(), "Capture")

    def pixel_size_um(self) -> float:
        """Calibration of the current image in um/px; 0 when uncalibrated."""
        name = ct.create_unicode_buffer(256)
        cal, aspect, unit = ct.c_double(), ct.c_double(), ct.c_int32()
        fn = self._fn(
            "Get_Calibration",
            [
                ct.c_wchar_p,
                ct.POINTER(ct.c_double),
                ct.POINTER(ct.c_double),
                ct.POINTER(ct.c_int32),
            ],
            ct.c_double,
        )
        fn(name, ct.byref(cal), ct.byref(aspect), ct.byref(unit))
        return cal.value

    def save_tiff(self, path: str) -> None:
        self._fn("ImageSaveAs", [ct.c_wchar_p, ct.c_int32, ct.c_int32])(path, TIFF_ALL_LAYERS, 0)

    def close_document(self) -> None:
        self._fn("CloseCurrentDocument", [ct.c_int32])(CLOSE_WITHOUT_ASKING)


# ---------------------------------------------------------------------------
# The operations a client may ask for
# ---------------------------------------------------------------------------


def _number(args: dict, key: str) -> float:
    try:
        return float(args[key])
    except KeyError:
        raise ValueError(f"missing argument {key!r}") from None
    except (TypeError, ValueError):
        raise ValueError(f"argument {key!r} must be a number") from None


class Operations:
    """Each public method is one request. Arguments are checked here."""

    def __init__(self, api: Any, request_stop: Any) -> None:
        self.api = api
        self._request_stop = request_stop

    def ping(self, args: dict) -> dict:
        return {
            "bridge": BRIDGE_VERSION,
            "protocol": PROTOCOL_VERSION,
            "nis": self.api.version(),
        }

    def get_position(self, args: dict) -> dict:
        return self.api.get_position()

    def get_limits(self, args: dict) -> dict:
        return self.api.get_limits()

    def move(self, args: dict) -> dict:
        """Absolute move of any of x, y, z (um); axes left out stay where they are."""
        target = {
            axis: _number(args, axis) for axis in ("x", "y", "z") if args.get(axis) is not None
        }
        if not target:
            raise ValueError("move needs at least one of 'x', 'y', 'z'")
        if "x" in target or "y" in target:
            here = self.api.get_position()
            x, y = target.get("x", here["x"]), target.get("y", here["y"])
            if "z" in target:
                self.api.move_xyz(x, y, target["z"])
            else:
                self.api.move_xy(x, y)
        else:
            self.api.move_z(target["z"])
        return self.api.get_position()

    def get_optical_configurations(self, args: dict) -> list:
        return self.api.optical_configurations()

    def select_optical_configuration(self, args: dict) -> dict:
        name = args.get("name")
        if name not in self.api.optical_configurations():
            raise ValueError(f"unknown optical configuration {name!r}")
        self.api.select_optical_configuration(name)
        return {"selected": name}

    def set_exposure(self, args: dict) -> dict:
        exposure_ms = _number(args, "exposure_ms")
        if exposure_ms <= 0:
            raise ValueError("'exposure_ms' must be positive")
        return {"exposure_ms": self.api.set_exposure_ms(exposure_ms)}

    def get_objectives(self, args: dict) -> dict:
        if not self.api.nosepiece_present():
            return {"current": None, "objectives": {}}
        names = {p: self.api.objective_name(p) for p in range(1, self.api.nosepiece_count() + 1)}
        return {
            "current": self.api.nosepiece_position(),
            "objectives": {p: name for p, name in names.items() if name},
        }

    def set_objective(self, args: dict) -> dict:
        position = args.get("position")
        if not isinstance(position, int) or isinstance(position, bool) or position < 1:
            raise ValueError("'position' must be a nosepiece position (1, 2, ...)")
        self.api.set_nosepiece_position(position)
        return {"current": self.api.nosepiece_position()}

    def get_pfs(self, args: dict) -> dict:
        if not self.api.pfs_present():
            return {"present": False, "on": False, "status": None, "meaning": "no PFS"}
        status = self.api.pfs_status()
        return {
            "present": True,
            "on": status in (1, 5, 6),
            "status": status,
            "meaning": PFS_STATUS.get(status, "unknown"),
        }

    def set_pfs(self, args: dict) -> dict:
        """Switch the Perfect Focus System on (waiting up to ``timeout_s`` to lock) or off."""
        on = args.get("on")
        if not isinstance(on, bool):
            raise ValueError("'on' must be true or false")
        if not self.api.pfs_present():
            raise RuntimeError("no Perfect Focus System (PFS) is connected")
        self.api.set_pfs(on)
        if on:
            self.api.wait_for_pfs(float(args.get("timeout_s", 8.0)))
        return self.get_pfs({})

    def autofocus(self, args: dict) -> dict:
        range_um = float(args.get("range_um", 50.0))
        speed = int(args.get("speed", 30))
        if range_um <= 0 or not 0 <= speed <= 90:
            raise ValueError("'range_um' must be positive and 'speed' between 0 and 90")
        rc = self.api.autofocus(range_um, speed)
        if rc != 1:
            reason = {0: "focus not found", -3: "image is all black or all white"}
            raise RuntimeError(f"StgFocusInRangeEx: {reason.get(rc, 'failed')} ({rc})")
        return self.api.get_position()

    def snap(self, args: dict) -> dict:
        """Capture one image, save it as TIFF at ``path``, close its window in NIS.

        ``pixel_size_um`` is None when the objective has no calibration in NIS.
        """
        path = args.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError("'path' must be a file path")
        self.api.capture()
        try:
            pixel_size_um = self.api.pixel_size_um()  # read while the image is still open
            self.api.save_tiff(path)
        finally:
            self.api.close_document()  # never leave capture windows piling up in NIS
        if not os.path.exists(path):
            raise RuntimeError(f"ImageSaveAs returned but no file appeared at {path}")
        return {"path": path, "pixel_size_um": pixel_size_um if pixel_size_um > 0 else None}

    def shutdown(self, args: dict) -> dict:
        self._request_stop()
        return {"stopping": True}


OPS = (
    "ping",
    "get_position",
    "get_limits",
    "move",
    "get_optical_configurations",
    "select_optical_configuration",
    "set_exposure",
    "get_objectives",
    "set_objective",
    "get_pfs",
    "set_pfs",
    "autofocus",
    "snap",
    "shutdown",
)


# ---------------------------------------------------------------------------
# The server: socket threads queue requests, the NIS main thread runs them
# ---------------------------------------------------------------------------


class _Job:
    def __init__(self, op: str, args: dict) -> None:
        self.op, self.args = op, args
        self.lock = threading.Lock()  # decides between "started" and "cancelled"
        self.started = self.cancelled = False
        self.done = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None


class BridgeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = False  # never let a second bridge share the port on Windows
    daemon_threads = True

    def __init__(self, address: tuple[str, int], api: Any) -> None:
        super().__init__(address, _Handler)
        self.ops = Operations(api, self.request_stop)
        self.jobs: queue.Queue[_Job] = queue.Queue()
        self.stop_requested = False
        self.last_pump = 0.0

    def request_stop(self) -> None:
        self.stop_requested = True

    def pump(self, wait_s: float = 0.0) -> int:
        """Run queued requests on the calling thread; wait up to ``wait_s`` for the first."""
        self.last_pump = time.monotonic()
        ran = 0
        while True:
            try:
                job = (
                    self.jobs.get(timeout=wait_s)
                    if (wait_s and not ran)
                    else self.jobs.get_nowait()
                )
            except queue.Empty:
                return ran
            with job.lock:
                if job.cancelled:  # the client stopped waiting; never run it late
                    continue
                job.started = True
            try:
                job.result = getattr(self.ops, job.op)(job.args)
            except BaseException as exc:  # noqa: BLE001 - every failure becomes a reply
                log.exception("op %s failed", job.op)
                job.error = exc
            job.done.set()
            ran += 1

    def handle_line(self, line: str) -> str:
        """Queue one request, wait for the main thread to run it, return the reply line."""
        request_id = None
        try:
            request_id, op, args, timeout = decode_request(line)
            if op not in OPS:
                raise ValueError(f"unknown op {op!r}; known: {', '.join(OPS)}")
            job = _Job(op, args)
            self.jobs.put(job)
            if not job.done.wait(timeout):
                with job.lock:
                    job.cancelled = not job.started
                if job.cancelled:
                    raise RuntimeError(
                        f"{op!r} did not start within {timeout:g} s: "
                        "is start_bridge.mac still running in NIS-Elements?"
                    )
                raise RuntimeError(f"{op!r} is still running in NIS after {timeout:g} s")
            if job.error is not None:
                raise job.error
            return encode_reply(request_id, job.result)
        except ProtocolError as exc:
            return encode_error(request_id, ValueError(str(exc)))
        except BaseException as exc:  # noqa: BLE001
            return encode_error(request_id, exc)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        server: BridgeServer = self.server  # type: ignore[assignment]
        while raw := self.rfile.readline():
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                self.wfile.write(server.handle_line(line).encode("utf-8"))
                self.wfile.flush()


def serve(api: Any, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> BridgeServer:
    """Listen in a background thread. The caller must call ``server.pump()`` regularly."""
    server = BridgeServer((host, port), api)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    return server


# ---------------------------------------------------------------------------
# Used by start_bridge.mac. The running server is kept in __main__ so that it
# survives the module reload the macro does to pick up code changes.
# ---------------------------------------------------------------------------

_running: dict[str, Any] = sys.modules["__main__"].__dict__.setdefault("_nis_bridge", {})
STOP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge.stop")


def start(port: int = DEFAULT_PORT) -> str:
    """Start listening (called once by the macro before its pump loop)."""
    old = _running.get("server")
    if old is not None:
        if not old.stop_requested and time.monotonic() - old.last_pump < 2.0:
            return f"bridge already running on port {port}"
        stop()  # left over from an earlier macro run: free its port
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    log_path = os.path.join(tempfile.gettempdir(), "nis-bridge.log")
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.handlers[:] = [handler]
    log.setLevel(logging.INFO)
    try:
        _running["server"] = serve(NisApi(), DEFAULT_HOST, port)
    except OSError as exc:
        log.error("could not start: %s", exc)
        return f"bridge failed to start on port {port}: {exc}"
    log.info("bridge %s listening on port %s", BRIDGE_VERSION, port)
    return f"bridge {BRIDGE_VERSION} listening on {DEFAULT_HOST}:{port}; log: {log_path}"


def pump(wait_s: float = 0.05) -> None:
    """Run queued requests on the NIS main thread (called by the macro loop)."""
    server = _running.get("server")
    if server is None:
        return
    server.pump(wait_s)
    if server.stop_requested and not os.path.exists(STOP_FILE):
        open(STOP_FILE, "w").close()  # ends the macro loop


def stop() -> str:
    """Close the server (called by the macro after its loop ends)."""
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    server = _running.pop("server", None)
    if server is None:
        return "bridge is not running"
    server.shutdown()
    server.server_close()
    log.info("bridge stopped")
    for handler in log.handlers[:]:
        log.removeHandler(handler)
        handler.close()
    return "bridge stopped"
