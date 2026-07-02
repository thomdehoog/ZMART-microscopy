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
# Guard against a client that never sends a newline: cap the un-framed buffer.
_MAX_LINE_BYTES = 4 * 1024 * 1024

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
        # mesoSPIM does not keep acquisition progress in the state singleton --
        # it emits it on ``sig_progress(dict)``. Cache the latest so ``progress``
        # can answer a synchronous read. Guarded: a fake/older Core may lack it.
        self._last_progress: dict = {}
        try:
            self.core.sig_progress.connect(self._on_progress)
        except Exception:  # noqa: BLE001 - no sig_progress on this Core; progress stays empty
            pass

    def _on_progress(self, payload) -> None:
        try:
            self._last_progress = dict(payload)
        except (TypeError, ValueError):
            self._last_progress = {}

    def disconnect_signals(self) -> None:
        """Detach from Core signals so a stopped/reloaded server leaks nothing."""
        try:
            self.core.sig_progress.disconnect(self._on_progress)
        except Exception:  # noqa: BLE001 - not connected / no such signal
            pass

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
        # The singleton stores position under raw 'x_pos','y_pos',... keys.
        # Normalise it here so get_state's `position` block matches get_position
        # and the documented {x,y,z,f,theta} reader contract (the mock server and
        # the ZMART readers both assume axis names, not the raw 'x_pos' keys).
        out["position"] = self._axis_positions(out.get("position"))
        return out

    @staticmethod
    def _axis_positions(pos) -> dict:
        """Normalise a mesoSPIM position dict to axis names ``{x,y,z,f,theta}``.

        mesoSPIM stores position under keys like ``'x_pos','y_pos',...`` (or, on
        some builds, a nested ``{'x':..}``); accept both shapes.
        """
        pos = pos or {}
        return {axis: pos.get(axis, pos.get(f"{axis}_pos")) for axis in _AXES}

    def position(self) -> dict:
        """Read the current position dict ``{x,y,z,f,theta}`` in um/deg."""
        return self._axis_positions(self.state().get("position"))

    def config(self) -> dict:
        """Read the hardware model from the loaded mesoSPIM config.

        Attribute names match mesoSPIM-control's config module (verified against
        the 1.20.0 `demo_config.py`): laser lines are the keys of ``laserdict``;
        zoom *names* are the keys of ``zoomdict`` while the pixel size (um/px)
        lives in a separate ``pixelsize`` dict keyed by the same names; the
        camera frame size is ``camera_parameters['x_pixels' / 'y_pixels']``.
        """
        cfg = getattr(self.core, "cfg", None)
        lasers, filters, zooms, shutters = [], [], [], []
        if cfg is not None:
            for name in getattr(cfg, "laserdict", {}) or {}:
                lasers.append({"name": name, "wavelength_nm": _wavelength(name)})
            filters = list((getattr(cfg, "filterdict", {}) or {}).keys())
            pixelsize = getattr(cfg, "pixelsize", {}) or {}
            zooms = [
                {"name": z, "pixel_size_um": pixelsize.get(z)}
                for z in (getattr(cfg, "zoomdict", {}) or {})
            ]
            shutters = list(getattr(cfg, "shutteroptions", ("Left", "Right", "Both")))
        return {
            "app": "mesoSPIM-control",
            "version": _config_version(cfg),
            "lasers": lasers,
            "filters": filters,
            "zooms": zooms,
            "shutter_configs": shutters,
            "axes": list(_AXES),
            "camera": _camera(cfg),
        }

    def progress(self) -> dict:
        # Live status is in the state singleton; the counts come from the cached
        # sig_progress payload (keys per mesoSPIM-control 1.20.0 send_progress()).
        st = self.state()
        p = self._last_progress
        return {
            "state": st.get("state"),
            "current_plane": p.get("current_image_in_acq"),
            "total_planes": p.get("images_in_acq"),
            "current_acquisition": p.get("current_acq"),
            "total_acquisitions": p.get("total_acqs"),
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

        Builds a mesoSPIM ``Acquisition`` (an ``IndexedOrderedDict`` subclass, so
        ``.update()`` merges over the constructor defaults) and a single-item
        ``AcquisitionList``, then runs it.

        RUN MECHANISM -- BENCH ITEM (see TODO.md). Against mesoSPIM-control 1.20.0
        the intended entry point is the Core method ``start(row=...)``, which wraps
        the row of ``state['acq_list']`` and drives the real per-image signal
        ``sig_add_images_to_image_series`` (``sig_run_timepoint(int)`` is the
        *time-lapse* counter, not a per-acquisition trigger). Emitting
        prepare/end alone does NOT capture frames. Wire this to ``start()`` and
        wait for the state to return to ``idle`` when validating on the bench.
        """
        from utils.acquisitions import Acquisition, AcquisitionList  # mesoSPIM, GPL

        acq = Acquisition()
        acq.update({k: v for k, v in acquisition.items() if v is not None})
        acq_list = AcquisitionList([acq])

        # Run through the public entry point so the image writer + per-image
        # signals fire exactly as the GUI drives them. Snapshot and restore the
        # operator's acquisition table so a socket-driven run never destroys it.
        state = self.core.state
        had_key = True
        try:
            prev_list = state["acq_list"]
        except (KeyError, TypeError):
            prev_list, had_key = None, False
        state["acq_list"] = acq_list
        try:
            self.core.start(row=0)
            self._run_until_idle()
        finally:
            if had_key:
                state["acq_list"] = prev_list
            else:
                # The key was absent before; don't leave a stray None the GUI
                # might later assume is a list. Remove it if the singleton allows
                # deletion, else fall back to restoring the prior value.
                try:
                    del state["acq_list"]
                except (KeyError, TypeError, AttributeError):
                    state["acq_list"] = prev_list

        files = _written_files(acq)
        cam = _camera(self.core.cfg)
        # PROTOCOL.md: pixels is [x, y] (the driver indexes pixels[0]/pixels[1]).
        return {
            "files": files,
            "planes": int(acq.get("planes", 1)),
            "pixels": [cam["pixels_x"], cam["pixels_y"]],
        }

    def _run_until_idle(self, timeout_s: float = 600.0) -> None:
        """Wait for the run to finish WITHOUT freezing the Qt event loop.

        ``start()`` drives the acquisition through the Qt event loop / worker
        threads, so a plain ``time.sleep`` loop here (this runs inside the socket
        poll callback on the GUI thread) would stall the state machine and freeze
        mesoSPIM. Instead a nested ``QEventLoop`` keeps events flowing: a ticker
        quits it once the state has left ``idle`` and come back (edge-detected), a
        one-shot grace timer covers a run that finished before we started waiting,
        and a watchdog bounds the total wait. The outer socket poll is
        re-entrancy-guarded (``MesospimCommandServer._busy``), so no second
        request is read while this nested loop runs. BENCH ITEM: confirm the
        finish semantics of ``start()`` on the installed version.
        """
        from PyQt5 import QtCore  # present inside mesoSPIM-control

        loop = QtCore.QEventLoop()
        seen = {"active": False}

        def _check() -> None:
            st = self.state().get("state")
            if st and st != "idle":
                seen["active"] = True
            elif seen["active"] and st == "idle":
                loop.quit()

        ticker = QtCore.QTimer()
        ticker.timeout.connect(_check)
        ticker.start(50)
        grace = QtCore.QTimer()  # run already done before we got here (fast demo snap)
        grace.setSingleShot(True)
        grace.timeout.connect(lambda: None if seen["active"] else loop.quit())
        grace.start(1000)
        watchdog = QtCore.QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(loop.quit)
        watchdog.start(int(timeout_s * 1000))
        try:
            loop.exec_()
        finally:
            ticker.stop()
            grace.stop()
            watchdog.stop()


def _wavelength(name):
    digits = "".join(c for c in str(name) if c.isdigit())
    return int(digits) if digits else None


def _config_version(cfg):
    # mesoSPIM's config module carries no version attribute; fall back to the
    # app package version if it is importable, else None.
    v = getattr(cfg, "version", None)
    if v is not None:
        return v
    try:
        import mesoSPIM  # mesoSPIM-control package, GPL

        return getattr(mesoSPIM, "__version__", None)
    except Exception:  # noqa: BLE001 - version is best-effort metadata
        return None


def _camera(cfg):
    # mesoSPIM stores the frame size in cfg.camera_parameters['x_pixels'/'y_pixels'].
    params = getattr(cfg, "camera_parameters", None) or {}
    x = params.get("x_pixels") if isinstance(params, dict) else None
    y = params.get("y_pixels") if isinstance(params, dict) else None
    return {"pixels_x": int(x or 2048), "pixels_y": int(y or 2048)}


def _sanitize_filename(name: str) -> str:
    """Mirror mesoSPIM's ``utility_functions.replace_with_underscores``.

    The image writer sanitises ``acq['filename']`` before writing, so the server
    must apply the same transform to predict the real output path.
    """
    return str(name).replace(" ", "_").replace("/", "_").replace("%", "pct")


def _written_files(acq: dict) -> list:
    """Resolve the file the image writer produced for this acquisition.

    Against mesoSPIM-control 1.20.0 the writer path is
    ``os.path.realpath(folder + '/' + replace_with_underscores(filename))``, and
    the default Tiff writer produces ONE multi-page (ImageJ) stack per
    acquisition -- not one file per plane. So a single acquisition maps to a
    single output path; multi-file products come from a multi-item
    AcquisitionList (one stack per acquisition). Returning empty means the driver
    gave the writer no filename. (Companion ``MAX_*`` MIP and ``*_meta.txt``
    sidecar files are written alongside but are not returned as frame data.)
    """
    import os

    folder = acq.get("folder") or ""
    filename = acq.get("filename") or ""
    # Require BOTH: an empty folder would let realpath resolve against the
    # mesoSPIM process CWD and silently return a wrong absolute path.
    if not folder or not filename:
        return []
    path = os.path.realpath(os.path.join(folder, _sanitize_filename(filename)))
    if not os.path.exists(path):
        # The writer names files itself; if our prediction misses, don't invent a
        # path. Return empty so the client fails loudly rather than saving junk.
        return []
    return [path]


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
        self._busy = False
        self._timer = QtCore.QTimer(core)
        self._timer.timeout.connect(self._poll)
        self._timer.start(poll_ms)
        print(f"[mesospim-cmd-server] listening on {host}:{port}")

    def _poll(self) -> None:
        # Re-entrancy guard: a Core call that pumps the event loop (a
        # wait_until_done move, or the acquisition wait) can re-fire this QTimer
        # while a request is still being handled. Never read/dispatch a second
        # request concurrently -- it would corrupt the shared read buffer.
        if self._busy:
            return
        # Accept one client at a time; mesoSPIM's command channel is single-client.
        if self._conn is None and self._server.hasPendingConnections():
            self._conn = self._server.nextPendingConnection()
            self._buf = b""
        if self._conn is None:
            return
        if self._conn.state() == self._QtNetwork.QAbstractSocket.UnconnectedState:
            self._conn = None
            return
        self._busy = True
        try:
            while self._conn is not None and self._conn.bytesAvailable():
                self._buf += bytes(self._conn.readAll())
                if len(self._buf) > _MAX_LINE_BYTES:
                    print(
                        f"[mesospim-cmd-server] request exceeded {_MAX_LINE_BYTES} bytes "
                        f"with no newline; dropping client"
                    )
                    self._conn.disconnectFromHost()
                    self._conn = None
                    self._buf = b""
                    return
                while self._conn is not None and b"\n" in self._buf:
                    raw, _, self._buf = self._buf.partition(b"\n")
                    self._respond(raw.decode("utf-8", "replace"))
        finally:
            self._busy = False

    def _respond(self, line: str) -> None:
        is_bye = False
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("expected a JSON object")
        except Exception as exc:  # noqa: BLE001
            reply = {"ok": False, "error": f"bad request: {exc}", "id": None}
        else:
            is_bye = request.get("cmd") == "bye"
            reply = handle_request(self.bridge, request)
        if self._conn is None:  # client went away while the command ran
            return
        try:
            self._conn.write((json.dumps(reply) + "\n").encode("utf-8"))
            self._conn.flush()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        if is_bye and isinstance(reply, dict) and reply.get("ok"):
            self._conn.disconnectFromHost()
            self._conn = None

    def stop(self) -> None:
        self._timer.stop()
        self.bridge.disconnect_signals()
        if self._conn is not None:
            self._conn.disconnectFromHost()
        self._server.close()
        print("[mesospim-cmd-server] stopped")


# =============================================================================
# Script-window entry point.
# When run via mesoSPIM's Script Window, ``self`` (the Core) is in scope, so the
# server is parented to it and outlives this script's exec() frame.
# =============================================================================

if "self" in dir():
    # Re-running the script must not fail with "address in use": stop any prior
    # server (tracked on the Core so it survives across Script-Window re-runs).
    _prev = getattr(self, "_zmart_cmd_server", None)  # noqa: F821 - Core from Script Window
    if _prev is not None:
        try:
            _prev.stop()
        except Exception:  # noqa: BLE001 - best-effort teardown of the old instance
            pass
    self._zmart_cmd_server = MesospimCommandServer(self)  # noqa: F821 - Core from Script Window
    _mesospim_command_server = self._zmart_cmd_server  # noqa: F821
