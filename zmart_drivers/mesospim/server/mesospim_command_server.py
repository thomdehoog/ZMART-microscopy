"""
mesoSPIM command server -- resident script (GPL edge).
======================================================
Load this file through mesoSPIM-control's **Script Window** (Core menu). The Core
``execute_script`` slot ``exec()``s it with ``self`` (the ``mesoSPIM_Core``) in
scope, so the script has full in-process access to the Core, its signals, and the
process-wide ``mesoSPIM_StateSingleton``. It opens a localhost TCP socket and
**QTimer-polls** it (non-blocking, so the Qt event loop never freezes -- the
exact analog of the Nikon ``NkSocketServerDemo.mac`` ``WM_TIMER`` poll), turning
each JSON request line into a Core action or a state read and writing back a JSON
reply line.

    LICENSE NOTE. This one file is the **GPL edge**: it uses the GPL-3.0 mesoSPIM
    Core API, so it is GPL-3.0, not MIT. It is deliberately standalone and
    imports **nothing** from ZMART, so the ZMART driver stays MIT behind the
    socket (see ``../README.md`` -> Licensing). The ideal home for this file is
    an upstream contribution to the mesoSPIM project.

    BENCH VALIDATION. The Core-binding calls are grouped in ``_CoreBridge`` and
    are the surface to validate against mesoSPIM ``-D`` demo mode (all Demo
    backends, no hardware). Everything else -- framing, dispatch, the socket
    poll -- is generic. Method/attribute names below follow mesoSPIM-control
    v1.20.0; confirm them against your installed version in demo mode first.

Protocol: ../PROTOCOL.md.  Author of the ZMART integration: Thom de Hoog (ZMB,
University of Zurich). This resident script: GPL-3.0 (uses the GPL Core API).
"""

from __future__ import annotations

import json
import traceback

PROTOCOL_VERSION = 1
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 42000

# Axis name -> mesoSPIM state keys for absolute / relative moves.
_ABS_KEY = {"x": "x_abs", "y": "y_abs", "z": "z_abs", "f": "f_abs", "theta": "theta_abs"}
_REL_KEY = {"x": "x_rel", "y": "y_rel", "z": "z_rel", "f": "f_rel", "theta": "theta_rel"}
_AXES = ("x", "y", "z", "f", "theta")


# =============================================================================
# Core bridge -- the ONLY place that touches the mesoSPIM Core API.
# Validate these against mesoSPIM -D demo mode.
# =============================================================================


class _CoreBridge:
    """Thin adapter over the live ``mesoSPIM_Core`` (``self`` in the script)."""

    def __init__(self, core):
        self.core = core

    # -- reads ---------------------------------------------------------------

    def state(self) -> dict:
        """Snapshot the process-wide state singleton as a plain dict."""
        st = self.core.state  # mesoSPIM_StateSingleton, dict-like + mutex-guarded
        keys = (
            "state",
            "position",
            "laser",
            "intensity",
            "filter",
            "zoom",
            "shutterconfig",
            "etl_l_amplitude",
            "etl_l_offset",
            "etl_r_amplitude",
            "etl_r_offset",
        )
        out = {}
        for key in keys:
            try:
                out[key] = st[key]
            except (KeyError, TypeError):
                out[key] = None
        return out

    def position(self) -> dict:
        """Read the current position dict ``{x,y,z,f,theta}`` in um/deg."""
        pos = self.state().get("position") or {}
        # mesoSPIM stores position under keys like 'x_pos','y_pos',... or a
        # nested {'x':..}. Normalise both shapes to axis names.
        out = {}
        for axis in _AXES:
            out[axis] = pos.get(axis, pos.get(f"{axis}_pos"))
        return out

    def config(self) -> dict:
        """Read the hardware model from the loaded mesoSPIM config."""
        cfg = getattr(self.core, "cfg", None)
        lasers, filters, zooms, shutters = [], [], [], []
        if cfg is not None:
            for name in getattr(cfg, "laser_designation", {}) or {}:
                lasers.append({"name": name, "wavelength_nm": _wavelength(name)})
            filters = list((getattr(cfg, "filterdict", {}) or {}).keys())
            zooms = [{"name": z, "pixel_size_um": px} for z, px in _zoomdict(cfg).items()]
            shutters = list(getattr(cfg, "shutteroptions", ["Left", "Right", "Both"]))
        return {
            "app": "mesoSPIM-control",
            "version": getattr(cfg, "version", None),
            "lasers": lasers,
            "filters": filters,
            "zooms": zooms,
            "shutter_configs": shutters,
            "axes": list(_AXES),
            "camera": _camera(cfg),
        }

    def progress(self) -> dict:
        st = self.state()
        return {
            "state": st.get("state"),
            "current_plane": _get(self.core.state, "current_framenumber"),
            "total_planes": _get(self.core.state, "snap_count"),
            "current_acquisition": _get(self.core.state, "current_acquisition"),
            "total_acquisitions": _get(self.core.state, "total_acquisitions"),
        }

    # -- writes --------------------------------------------------------------

    def move_absolute(self, targets: dict) -> dict:
        sdict = {_ABS_KEY[a]: float(v) for a, v in targets.items()}
        self.core.move_absolute(sdict, wait_until_done=True)
        return self.position()

    def move_relative(self, deltas: dict) -> dict:
        sdict = {_REL_KEY[a]: float(v) for a, v in deltas.items()}
        self.core.move_relative(sdict, wait_until_done=True)
        return self.position()

    def zero(self, axes: list) -> None:
        self.core.zero_axes(list(axes))

    def stop(self) -> None:
        self.core.sig_stop_movement.emit()

    def set_state(self, settings: dict) -> dict:
        # sig_state_request is the mesoSPIM central control channel.
        self.core.sig_state_request_and_wait_until_done.emit(dict(settings))
        return {"applied": dict(settings)}

    def acquire(self, acquisition: dict, acquisition_type: str) -> dict:
        """Run one Acquisition and return the written frame file(s).

        Builds a mesoSPIM ``Acquisition`` + single-item ``AcquisitionList`` and
        runs it through the Core. The image-writer plugin writes the frames; we
        return their paths. Adapt the run entrypoint / writer path resolution to
        your installed mesoSPIM version (validate in ``-D`` demo mode).
        """
        from utils.acquisitions import Acquisition, AcquisitionList  # mesoSPIM, GPL

        acq = Acquisition()
        acq.update({k: v for k, v in acquisition.items() if v is not None})
        acq_list = AcquisitionList([acq])
        self.core.sig_prepare_image_series.emit(acq, acq_list)
        self.core.sig_run_timepoint.emit(0)
        self.core.sig_end_image_series.emit(acq, acq_list)
        files = _written_files(acq)
        return {"files": files, "planes": int(acq.get("planes", 1)), "pixels": _camera(self.core.cfg)}


def _wavelength(name):
    digits = "".join(c for c in str(name) if c.isdigit())
    return int(digits) if digits else None


def _zoomdict(cfg):
    zd = getattr(cfg, "zoomdict", None) or getattr(cfg, "zoom", None) or {}
    return zd if isinstance(zd, dict) else {}


def _camera(cfg):
    x = _get(cfg, "camera_x_pixels", "x_pixels") or 2048
    y = _get(cfg, "camera_y_pixels", "y_pixels") or 2048
    return {"pixels_x": int(x), "pixels_y": int(y)}


def _get(obj, *names, default=None):
    for name in names:
        try:
            val = obj[name] if isinstance(obj, dict) else getattr(obj, name)
        except (KeyError, TypeError, AttributeError):
            val = None
        if val is not None:
            return val
    return default


def _written_files(acq: dict) -> list:
    import os

    folder = acq.get("folder") or ""
    filename = acq.get("filename") or ""
    path = os.path.join(folder, filename)
    return [path] if filename else []


# =============================================================================
# Pure dispatch -- request dict -> reply dict. No sockets, no Qt.
# =============================================================================


def handle_request(bridge: _CoreBridge, request: dict) -> dict:
    """Translate one parsed request into a reply dict (``ok``/``data``/``error``).

    Kept pure (only the ``_CoreBridge`` touches Qt/Core) so the dispatch table
    can be reasoned about and, in principle, tested against a fake core.
    """
    req_id = request.get("id")
    cmd = request.get("cmd")
    args = request.get("args") or {}
    try:
        data = _dispatch(bridge, cmd, args)
        return {"ok": True, "data": data, "id": req_id}
    except _Nak as exc:
        return {"ok": False, "error": str(exc), "id": req_id}
    except Exception as exc:  # noqa: BLE001 - never let a handler crash the loop
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "id": req_id}


class _Nak(Exception):
    """A request the server understood but declined."""


def _axis_dict(raw: dict) -> dict:
    out = {}
    for axis, value in (raw or {}).items():
        if axis not in _AXES:
            raise _Nak(f"unknown axis {axis!r}")
        out[axis] = float(value)
    if not out:
        raise _Nak("no axes given")
    return out


def _dispatch(bridge: _CoreBridge, cmd, args):
    if cmd == "hello":
        return {
            "app": "mesoSPIM-control",
            "version": bridge.config().get("version"),
            "protocol": PROTOCOL_VERSION,
            "state": bridge.state().get("state"),
        }
    if cmd == "ping":
        return {}
    if cmd == "bye":
        return {}
    if cmd == "get_state":
        return bridge.state()
    if cmd == "get_position":
        return bridge.position()
    if cmd == "get_config":
        return bridge.config()
    if cmd == "get_progress":
        return bridge.progress()
    if cmd == "move_absolute":
        return {"position": bridge.move_absolute(_axis_dict(args.get("targets")))}
    if cmd == "move_relative":
        return {"position": bridge.move_relative(_axis_dict(args.get("deltas")))}
    if cmd == "zero":
        bridge.zero(args.get("axes") or list(_AXES))
        return {}
    if cmd == "stop":
        bridge.stop()
        return {}
    if cmd == "set_state":
        settings = args.get("settings") or {}
        if not settings:
            raise _Nak("set_state needs 'settings'")
        return bridge.set_state(settings)
    if cmd == "acquire":
        acq = args.get("acquisition")
        if not acq:
            raise _Nak("acquire needs 'acquisition'")
        return bridge.acquire(acq, args.get("acquisition_type", "snap"))
    if cmd == "run_acquisition_list":
        acqs = args.get("acquisitions") or []
        if not acqs:
            raise _Nak("run_acquisition_list needs 'acquisitions'")
        files, per = [], []
        for one in acqs:
            data = bridge.acquire(one, "list")
            files.extend(data.get("files", []))
            per.append(data)
        return {"files": files, "per_acquisition": per}
    if cmd == "procedure":
        raise _Nak(f"procedure {args.get('name')!r} not implemented on this server")
    raise _Nak(f"unknown cmd {cmd!r}")


# =============================================================================
# Socket server -- QTimer-polled, non-blocking. Qt imported here only.
# =============================================================================


class MesospimCommandServer:
    """Localhost TCP server polled by a QTimer inside the Qt event loop."""

    def __init__(self, core, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, poll_ms: int = 20):
        from PyQt5 import QtCore, QtNetwork  # noqa: F401 - import guarded to runtime

        self._QtCore = QtCore
        self._QtNetwork = QtNetwork
        self.bridge = _CoreBridge(core)
        self._server = QtNetwork.QTcpServer(core)
        if not self._server.listen(QtNetwork.QHostAddress(host), port):
            raise RuntimeError(f"cannot listen on {host}:{port}: {self._server.errorString()}")
        self._conn = None
        self._buf = b""
        self._timer = QtCore.QTimer(core)
        self._timer.timeout.connect(self._poll)
        self._timer.start(poll_ms)
        print(f"[mesospim-cmd-server] listening on {host}:{port}")

    def _poll(self) -> None:
        # Accept one client at a time; mesoSPIM's command channel is single-client.
        if self._conn is None and self._server.hasPendingConnections():
            self._conn = self._server.nextPendingConnection()
            self._buf = b""
        if self._conn is None:
            return
        if self._conn.state() == self._QtNetwork.QAbstractSocket.UnconnectedState:
            self._conn = None
            return
        while self._conn is not None and self._conn.bytesAvailable():
            self._buf += bytes(self._conn.readAll())
            while b"\n" in self._buf:
                raw, _, self._buf = self._buf.partition(b"\n")
                self._respond(raw.decode("utf-8", "replace"))

    def _respond(self, line: str) -> None:
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("expected a JSON object")
        except Exception as exc:  # noqa: BLE001
            reply = {"ok": False, "error": f"bad request: {exc}", "id": None}
        else:
            reply = handle_request(self.bridge, request)
        try:
            self._conn.write((json.dumps(reply) + "\n").encode("utf-8"))
            self._conn.flush()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        if isinstance(reply, dict) and reply.get("ok") and _is_bye(line):
            self._conn.disconnectFromHost()
            self._conn = None

    def stop(self) -> None:
        self._timer.stop()
        if self._conn is not None:
            self._conn.disconnectFromHost()
        self._server.close()
        print("[mesospim-cmd-server] stopped")


def _is_bye(line: str) -> bool:
    try:
        return json.loads(line).get("cmd") == "bye"
    except Exception:  # noqa: BLE001
        return False


# =============================================================================
# Script-window entry point.
# When run via mesoSPIM's Script Window, ``self`` (the Core) is in scope, so the
# server is parented to it and outlives this script's exec() frame.
# =============================================================================

if "self" in dir():
    _mesospim_command_server = MesospimCommandServer(self)  # noqa: F821 - Core from Script Window
