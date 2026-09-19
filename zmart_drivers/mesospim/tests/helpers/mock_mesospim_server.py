"""
Mock mesoSPIM Remote Control server (offline test double).
==========================================================
A faithful **MIT** stand-in for the Remote Control TCP server of
mesoSPIM-control (pull request #106) for offline testing. Like the real server
it speaks the length-framed protocol, demands the password as the first frame,
takes one ``{name: args}`` JSON call per frame, answers ``__MESOSPIM_OK__`` +
JSON or ``error: [code] message``, validates arguments and stage limits before
anything moves, admits one change at a time, and hands every change back as an
*operation* the client must poll ``get_progress`` for.

Its Core is a small fake with the same state surface as mesoSPIM's
(``state[key]`` only, no ``.get``), a configuration with lasers, filters,
zooms, a camera and a stage envelope, and an image writer that really writes a
TIFF stack -- so the driver's tests exercise real framing, real validation
errors, real polling and real files. Only the live hardware Core is absent.

Two knobs make failure paths testable: ``errors`` maps a call name to an
execution error the server answers with, and ``stall`` names calls whose
operation never completes (a client must then time out, not wait forever).

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import hmac
import json
import math
import os
import socket
import tempfile
import threading
from pathlib import Path

import numpy as np
import tifffile

_AXES = ("x", "y", "z", "f", "theta")
OK_MARKER = "__MESOSPIM_OK__"
DEFAULT_TOKEN = "smart_mesospim"

SETTABLE_STATE_KEYS = (
    "filter",
    "zoom",
    "laser",
    "intensity",
    "shutterconfig",
    "camera_exposure_time",
    "etl_l_amplitude",
    "etl_l_offset",
    "etl_r_amplitude",
    "etl_r_offset",
)
ACQUISITION_FIELDS = (
    "x_pos",
    "y_pos",
    "z_start",
    "z_end",
    "z_step",
    "planes",
    "rot",
    "f_start",
    "f_end",
    "laser",
    "intensity",
    "filter",
    "zoom",
    "shutterconfig",
    "folder",
    "filename",
    "image_writer_plugin",
    "etl_l_offset",
    "etl_l_amplitude",
    "etl_r_offset",
    "etl_r_amplitude",
    "processing",
)
ACQUISITION_AXIS_FIELDS = {
    "x_pos": "x",
    "y_pos": "y",
    "z_start": "z",
    "z_end": "z",
    "f_start": "f",
    "f_end": "f",
    "rot": "theta",
}
PARAMETER_RANGES = {
    "etl_l_amplitude": (0.0, 2.0),
    "etl_r_amplitude": (0.0, 2.0),
    "etl_l_offset": (0.0, 5.0),
    "etl_r_offset": (0.0, 5.0),
    "camera_exposure_time": (0.001, 5.0),
}


class ValidationError(ValueError):
    pass


class BusyError(RuntimeError):
    pass


class UnknownCommand(KeyError):
    pass


# =============================================================================
# A Core-shaped fake: configuration, state, stage, image writer
# =============================================================================


class FakeCfg:
    """The mesoSPIM config attributes the server reads."""

    laserdict = {"405 nm": "PWM", "488 nm": "PWM", "561 nm": "PWM", "647 nm": "PWM"}
    filterdict = {"Empty-Alignment": 0, "515/30": 1, "561/LP": 2, "647-LP": 3}
    zoomdict = {"1x": 6.55, "2x": 3.26}
    pixelsize = {"1x": 6.55, "2x": 3.26}
    shutteroptions = ("Left", "Right", "Both")
    version = "1.10.2-mock"
    # Small camera so synthetic frames stay tiny in tests.
    camera_parameters = {"x_pixels": 64, "y_pixels": 64, "subsampling": [1, 2, 4]}
    stage_parameters = {
        "stage_type": "DemoStage",
        "x_min": -50000.0,
        "x_max": 50000.0,
        "y_min": -50000.0,
        "y_max": 50000.0,
        "z_min": -50000.0,
        "z_max": 50000.0,
        "f_min": -50000.0,
        "f_max": 50000.0,
        "theta_min": -720.0,
        "theta_max": 720.0,
        "y_load_position": 30000.0,
        "y_unload_position": 20000.0,
        "x_center_position": 1000.0,
        "y_center_position": 2000.0,
    }
    startup = {}


class _FakeStateSingleton:
    """Mimics ``mesoSPIM_StateSingleton``: item access only, **no** ``.get``."""

    def __init__(self, initial):
        self._state_dict = dict(initial)

    def __getitem__(self, key):
        return self._state_dict[key]

    def __setitem__(self, key, value):
        self._state_dict[key] = value

    def __len__(self):
        return len(self._state_dict)

    def set_parameters(self, mapping):
        self._state_dict.update(mapping)


class FakeCore:
    """Duck-typed ``mesoSPIM_Core`` with the surface the Remote Control commands use."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cfg = FakeCfg()
        self.state = _FakeStateSingleton(
            {
                "state": "idle",
                "position": {f"{a}_pos": 0.0 for a in _AXES},
                "position_absolute": {f"{a}_pos": 0.0 for a in _AXES},
                "laser": "488 nm",
                "intensity": 10.0,
                "filter": "515/30",
                "zoom": "1x",
                "shutterconfig": "Left",
                "camera_exposure_time": 0.02,
                "etl_l_amplitude": 1.0,
                "etl_l_offset": 2.0,
                "etl_r_amplitude": 1.0,
                "etl_r_offset": 2.0,
                "acq_list": [],
                "selected_row": 0,
                "folder": str(output_dir),
                "snap_folder": str(output_dir),
                "ETL_cfg_file": "etl.csv",
            }
        )
        self.moves = 0
        self._seq = 0

    # -- position ---------------------------------------------------------------

    def position(self, absolute=False):
        key = "position_absolute" if absolute else "position"
        pos = self.state[key]
        return {a: pos.get(f"{a}_pos") for a in _AXES}

    def move_absolute(self, sdict, wait_until_done=False):
        self.moves += 1
        for key, val in sdict.items():
            axis = key.replace("_abs", "")
            self.state["position"][f"{axis}_pos"] = float(val)
            self.state["position_absolute"][f"{axis}_pos"] = float(val)

    def move_relative(self, ddict, wait_until_done=False):
        self.moves += 1
        for key, val in ddict.items():
            axis = key.replace("_rel", "")
            self.state["position"][f"{axis}_pos"] += float(val)
            self.state["position_absolute"][f"{axis}_pos"] += float(val)

    def zero_axes(self, axes):
        for axis in axes:
            self.state["position"][f"{axis}_pos"] = 0.0

    def unzero_axes(self, axes):
        for axis in axes:
            self.state["position"][f"{axis}_pos"] = self.state["position_absolute"][f"{axis}_pos"]

    def state_request_handler(self, settings):
        self.state.set_parameters(settings)

    # -- acquisition ------------------------------------------------------------

    def start(self, row=0):
        """Run the acquisition at ``state['acq_list'][row]``: write ONE stack.

        Mirrors the real Core entry point + default Tiff image writer -- a single
        multi-page TIFF (shape ``(planes, H, W)``, or 2-D for a single plane) at
        the Acquisition's ``folder``/``filename``, with its ``_meta.txt`` note
        beside it -- then returns to idle.
        """
        acq = self.state["acq_list"][row]
        planes = _image_count(acq)
        folder = acq.get("folder") or str(self.output_dir)
        filename = acq.get("filename") or f"stack_{self._next():06d}.tiff"
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, filename)
        w, h = self.cfg.camera_parameters["x_pixels"], self.cfg.camera_parameters["y_pixels"]
        pages = []
        for _ in range(planes):
            self._seq += 1
            base = np.arange(w * h, dtype=np.uint16).reshape(h, w)
            pages.append(((base + self._seq) % 65535).astype(np.uint16))
        stack = pages[0] if planes == 1 else np.stack(pages)
        tifffile.imwrite(path, stack, photometric="minisblack")
        Path(path + "_meta.txt").write_text(
            "\n".join(f"[{k}] {v}" for k, v in sorted(acq.items())) + "\n", encoding="utf-8"
        )
        self.state["state"] = "idle"

    def _next(self) -> int:
        self._acq_seq = getattr(self, "_acq_seq", 0) + 1
        return self._acq_seq


def _image_count(acq: dict) -> int:
    """The plane count mesoSPIM derives from the z geometry (``Acquisition.get_image_count``)."""
    z_start = float(acq.get("z_start", 0) or 0)
    z_end = float(acq.get("z_end", 0) or 0)
    z_step = float(acq.get("z_step", 1) or 1)
    return abs(round((z_end - z_start) / z_step)) + 1


# =============================================================================
# The command registry: validation + execution, as the real dispatcher orders it
# =============================================================================

READ, ACTION, WAIT, EMERGENCY = "read", "action", "wait", "emergency"


def _only(args, allowed):
    unknown = sorted(set(args) - set(allowed))
    if unknown:
        raise ValidationError(f"unknown argument(s): {', '.join(unknown)}")


def _finite(value, where):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValidationError(f"{where} must be a finite number, got {value!r}")
    return float(value)


def _limits(core):
    stage = core.cfg.stage_parameters
    return {a: (stage[f"{a}_min"], stage[f"{a}_max"]) for a in _AXES}


def _check_absolute(core, axis, value):
    low, high = _limits(core)[axis]
    if not low <= value <= high:
        raise ValidationError(
            f"{axis}={value} is outside the allowed range [{low}, {high}] "
            "(units: um for x/y/z/f, deg for theta; see get_limits)"
        )


def _options(core):
    return {
        "filter": list(core.cfg.filterdict),
        "zoom": list(core.cfg.zoomdict),
        "laser": list(core.cfg.laserdict),
        "shutterconfig": list(core.cfg.shutteroptions),
    }


def _check_setting(core, key, value):
    options = _options(core)
    if key in options:
        if not isinstance(value, str):
            raise ValidationError(f"{key!r} must be a string")
        if value not in options[key]:
            raise ValidationError(f"{key}={value!r} is not one of {options[key]}")
    elif key == "intensity":
        _finite(value, key)
        if not 0 <= value <= 100:
            raise ValidationError(f"{key}={value} is outside the allowed range [0, 100] (percent)")
    elif key in PARAMETER_RANGES:
        low, high = PARAMETER_RANGES[key]
        _finite(value, key)
        if not low <= value <= high:
            raise ValidationError(f"{key}={value} is outside the allowed range [{low}, {high}]")
    elif key in SETTABLE_STATE_KEYS:
        _finite(value, key)


def _axis_map(args, key):
    moves = args.get(key)
    if not isinstance(moves, dict) or not moves:
        raise ValidationError(f"{key!r} must be a non-empty object of axis -> number")
    clean = {}
    for axis, value in moves.items():
        if axis not in _AXES:
            raise ValidationError(f"unknown axis {axis!r}; valid axes are {list(_AXES)}")
        clean[axis] = _finite(value, f"{key}.{axis}")
    return clean


def _check_acquisition(core, acq):
    if not isinstance(acq, dict):
        raise ValidationError("acquisition must be an object")
    _only(acq, ACQUISITION_FIELDS)
    for key, value in acq.items():
        _check_setting(core, key, value)
    for field, axis in ACQUISITION_AXIS_FIELDS.items():
        if field in acq:
            _check_absolute(core, axis, _finite(acq[field], f"acquisition.{field}"))
    if "z_step" in acq and _finite(acq["z_step"], "acquisition.z_step") <= 0:
        raise ValidationError("acquisition.z_step must be positive")
    if "planes" in acq:
        planes = acq["planes"]
        if not isinstance(planes, int) or isinstance(planes, bool) or planes < 1:
            raise ValidationError("acquisition.planes must be a positive integer")
    for field in ("folder", "filename", "image_writer_plugin", "processing"):
        if field in acq and not isinstance(acq[field], str):
            raise ValidationError(f"acquisition.{field} must be a string")
    return dict(acq)


def _config_document(core):
    cfg = core.cfg
    return {
        "app": "mesoSPIM-control",
        "version": cfg.version,
        "lasers": [
            {"name": n, "wavelength_nm": int("".join(c for c in n if c.isdigit()))}
            for n in cfg.laserdict
        ],
        "filters": list(cfg.filterdict),
        "zooms": [{"name": z, "pixel_size_um": cfg.pixelsize.get(z)} for z in cfg.zoomdict],
        "shutter_configs": list(cfg.shutteroptions),
        "axes": list(_AXES),
        "camera": {
            "pixels_x": cfg.camera_parameters["x_pixels"],
            "pixels_y": cfg.camera_parameters["y_pixels"],
        },
    }


class MockMesospimServer:
    """One-client-at-a-time fake Remote Control server for tests.

    Args:
        host, port: bind address; ``port=0`` picks a free ephemeral port
            (read ``.port`` after construction).
        output_dir: where synthetic frame files are written; a temp dir by default.
        token: the password the first frame must carry (mesoSPIM's public
            placeholder by default, like the real server on the local machine).
        errors: call names that should answer with an execution error instead
            of running -- to exercise the client/dispatch failure paths.
        stall: call names whose operation is accepted but never completes.
    """

    def __init__(
        self,
        host="127.0.0.1",
        port=0,
        *,
        output_dir=None,
        token=DEFAULT_TOKEN,
        errors=None,
        stall=None,
    ):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(1)
        self.host, self.port = self._sock.getsockname()
        self.core = FakeCore(output_dir or tempfile.mkdtemp(prefix="mock_mesospim_"))
        self._token = token
        self.errors = set(errors or [])
        self.stall = set(stall or [])
        self.token = token
        self._session = {"counter": 0, "operation": None, "prev_acq_list": None, "warnings": []}
        # Every call the server received, in order: what a test inspects to
        # prove the driver spoke the protocol it should have.
        self.calls: list[tuple[str, dict]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- compatibility accessors --------------------------------------------

    @property
    def state(self):
        return self.core.state

    @property
    def output_dir(self) -> Path:
        return self.core.output_dir

    @property
    def operation(self) -> dict | None:
        return self._session["operation"]

    # -- lifecycle -----------------------------------------------------------

    def __enter__(self) -> MockMesospimServer:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._serve, name="mock-mesospim", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    # -- server loop ---------------------------------------------------------

    def _serve(self) -> None:
        self._sock.settimeout(0.3)
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with conn:
                self._handle(conn)

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(0.3)
        buf = b""
        authed = False
        while not self._stop.is_set():
            try:
                chunk = conn.recv(4096)
            except TimeoutError:
                continue
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                head, _, rest = buf.partition(b"\n")
                if not head.isdigit():
                    conn.sendall(_frame("framing error: expected canonical byte-count header"))
                    return
                length = int(head)
                if len(rest) < length:
                    break
                payload = rest[:length].decode("utf-8", "replace")
                buf = rest[length:]
                if not authed:
                    ok = hmac.compare_digest(
                        payload.encode("utf-8"), str(self._token).encode("utf-8")
                    )
                    authed = ok
                    conn.sendall(_frame("OK" if ok else "AUTH-FAILED"))
                    if not ok:
                        return
                else:
                    conn.sendall(_frame(self._answer(payload)))

    # -- one call ------------------------------------------------------------

    def _answer(self, payload: str) -> str:
        try:
            name, args = _parse_call(payload)
            self.calls.append((name, dict(args)))
            data = self._run(name, args)
        except ValidationError as exc:
            return f"error: [validation] {exc}"
        except BusyError as exc:
            return f"error: [busy] {exc}"
        except UnknownCommand as exc:
            return f"error: [unknown_command] {exc.args[0]}"
        except Exception as exc:  # noqa: BLE001 -- an execution error is a reply, not a crash
            return f"error: [execution] {exc}"
        return OK_MARKER + json.dumps(data, allow_nan=False)

    def _run(self, name: str, args: dict) -> dict:
        cmd = _COMMANDS.get(name)
        if cmd is None:
            raise UnknownCommand(f"unknown command: {name!r}")
        kind, accept, execute = cmd
        if name in self.errors:
            raise RuntimeError(f"injected error for command {name!r}")
        clean = accept(self, args)
        if kind == READ:
            return execute(self, clean)
        if kind == EMERGENCY:
            result = execute(self, clean)
            return {
                **result,
                "accepted": True,
                "accepted_command": name,
                "operation": self._public(),
            }
        active = self.operation
        if active is not None and active["status"] in ("processing", "stopping"):
            raise BusyError(f"busy: {active['command']} ({active['id']}) is running")
        self._session["counter"] += 1
        operation = {
            "id": f"op-{self._session['counter']:06d}",
            "command": name,
            "status": "processing",
            "kind": kind,
        }
        self._session["operation"] = operation
        # The real server schedules the work on the next Qt turn and answers
        # first; here the work runs now, and the operation becomes terminal on
        # the client's next get_progress -- so a driver must poll to see it.
        try:
            result = execute(self, clean)
            operation["result"] = result
            operation["_finish"] = None if name in self.stall else "completed"
        except Exception as exc:  # noqa: BLE001
            operation["_finish"] = "failed"
            operation["_error"] = str(exc)
        return {"accepted": True, "accepted_command": name, "operation": self._public()}

    def _public(self) -> dict:
        op = self.operation
        if op is None:
            return {"status": "idle"}
        keys = (
            "id",
            "command",
            "status",
            "target",
            "observed",
            "stop_requested",
            "result",
            "error",
        )
        return {k: op[k] for k in keys if k in op}

    def _settle_operation(self) -> None:
        """Move the current operation to its terminal state (called on every poll)."""
        op = self.operation
        if op is None or op["status"] not in ("processing", "stopping"):
            return
        finish = op.get("_finish")
        if finish is None:
            return
        op["status"] = finish
        if finish == "failed":
            op["error"] = op.get("_error", "the operation failed")


def _frame(text: str) -> bytes:
    b = text.encode("utf-8")
    return str(len(b)).encode("ascii") + b"\n" + b


def _parse_call(payload: str):
    try:
        msg = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON: {exc}") from exc
    if not isinstance(msg, dict) or len(msg) != 1:
        raise ValidationError("expected one JSON object: {'command': {args}}")
    ((name, args),) = msg.items()
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ValidationError("command arguments must be an object")
    return name, args


# -- accept / execute functions -------------------------------------------------


def _no_args(server, args):
    _only(args, ())
    return {}


def _hello(server, args):
    return {
        "app": "mesoSPIM-control",
        "version": server.core.cfg.version,
        "protocol": 1,
        "state": server.core.state["state"],
    }


def _ping(server, args):
    return {"pong": True, "state": server.core.state["state"]}


def _get_state(server, args):
    core = server.core
    out = {"state": core.state["state"], "position": core.position()}
    for key in (
        "laser",
        "intensity",
        "filter",
        "zoom",
        "shutterconfig",
        "etl_l_amplitude",
        "etl_l_offset",
        "etl_r_amplitude",
        "etl_r_offset",
    ):
        out[key] = core.state[key]
    return out


def _get_position(server, args):
    return server.core.position()


def _get_config(server, args):
    return _config_document(server.core)


def _get_info(server, args):
    core = server.core
    return {
        "app": "mesoSPIM-control",
        "version": core.cfg.version,
        "protocol": 1,
        "state": core.state["state"],
        "stage_type": core.cfg.stage_parameters["stage_type"],
        "save_path": core.state["folder"],
        "last_acquisition_path": None,
        "etl_config_path": core.state["ETL_cfg_file"],
        "operation": server._public(),
        "warnings": list(server._session["warnings"]),
    }


def _get_limits(server, args):
    core = server.core
    return {
        "stage": dict(core.cfg.stage_parameters),
        "camera": dict(core.cfg.camera_parameters),
        "startup": {},
        "enforced": {
            "axes": {a: list(b) for a, b in _limits(core).items()},
            "axes_frame": "stage",
            "axis_offsets": {a: 0.0 for a in _AXES},
            "parameters": {},
        },
    }


def _get_progress(server, args):
    server._settle_operation()
    core = server.core
    return {
        "state": core.state["state"],
        "current_plane": None,
        "total_planes": None,
        "current_acquisition": None,
        "total_acquisitions": None,
        "operation": server._public(),
    }


def _accept_move_absolute(server, args):
    _only(args, ("targets",))
    targets = _axis_map(args, "targets")
    for axis, value in targets.items():
        _check_absolute(server.core, axis, value)
    return {"targets": targets}


def _run_move_absolute(server, args):
    targets = args["targets"]
    server.core.move_absolute({f"{a}_abs": v for a, v in targets.items()})
    server.operation["target"] = dict(targets)
    server.operation["observed"] = {a: server.core.position()[a] for a in targets}
    return {"target": targets}


def _accept_move_relative(server, args):
    _only(args, ("deltas",))
    deltas = _axis_map(args, "deltas")
    here = server.core.position()
    targets = {}
    for axis, delta in deltas.items():
        targets[axis] = here[axis] + delta
        _check_absolute(server.core, axis, targets[axis])
    return {"deltas": deltas, "targets": targets}


def _run_move_relative(server, args):
    server.core.move_relative({f"{a}_rel": d for a, d in args["deltas"].items()})
    server.operation["target"] = dict(args["targets"])
    return {"target": args["targets"]}


def _accept_axes(server, args):
    _only(args, ("axes",))
    axes = args.get("axes")
    if axes is None or axes == []:
        return {"axes": list(_AXES)}
    if not isinstance(axes, list) or any(a not in _AXES for a in axes):
        raise ValidationError(f"'axes' must be a list of {list(_AXES)}")
    return {"axes": axes}


def _run_zero(server, args):
    server.core.zero_axes(args["axes"])
    return {}


def _run_unzero(server, args):
    server.core.unzero_axes(args["axes"])
    return {}


def _run_stop(server, args):
    op = server.operation
    if op is not None and op["status"] == "processing":
        op["stop_requested"] = True
        op["status"] = "stopping"
        op["_finish"] = "completed"
    return {}


def _accept_set_state(server, args):
    _only(args, ("settings",))
    settings = args.get("settings")
    if not isinstance(settings, dict) or not settings:
        raise ValidationError("'settings' must be a non-empty object")
    for key, value in settings.items():
        if key not in SETTABLE_STATE_KEYS:
            raise ValidationError(f"unknown state setting {key!r}")
        _check_setting(server.core, key, value)
    return {"settings": settings}


def _run_set_state(server, args):
    server.core.state_request_handler(args["settings"])
    return {}


def _accept_stat_files(server, args):
    _only(args, ("files",))
    files = args.get("files") or []
    if not isinstance(files, list) or any(not isinstance(f, str) for f in files):
        raise ValidationError("'files' must be a list of strings")
    return {"files": files}


def _run_stat_files(server, args):
    files = args["files"]
    return {
        "missing": [f for f in files if not os.path.isfile(f)],
        "sizes": {f: os.path.getsize(f) for f in files if os.path.isfile(f)},
    }


def _get_acquisition_list(server, args):
    return {"acquisitions": [dict(a) for a in server.core.state["acq_list"]]}


def _accept_acquire_start(server, args):
    _only(args, ("acquisition",))
    if server._session.get("prev_acq_list_saved"):
        raise ValidationError("a previous acquire_start is unfinished; call acquire_finish first")
    return {"acquisition": _check_acquisition(server.core, args.get("acquisition"))}


def _run_acquire_start(server, args):
    core = server.core
    acq = dict(args["acquisition"])
    row = {"z_start": 0, "z_end": 0, "z_step": 1.0, "planes": 1, "folder": "", "filename": ""}
    row.update(acq)
    filename = acq.get("filename") or ""
    files = [os.path.join(acq.get("folder") or "", filename)] if filename else []
    server._session["prev_acq_list"] = core.state["acq_list"]
    server._session["prev_acq_list_saved"] = True
    core.state["acq_list"] = [row]
    core.state["state"] = "run_acquisition_list"
    core.start(row=0)
    return {
        "started": True,
        "scheduled": True,
        "files": files,
        "planes": _image_count(row),
        "pixels": [core.cfg.camera_parameters["x_pixels"], core.cfg.camera_parameters["y_pixels"]],
    }


def _run_acquire_finish(server, args):
    if server._session.pop("prev_acq_list_saved", False):
        server.core.state["acq_list"] = server._session.pop("prev_acq_list")
    return {"state": server.core.state["state"]}


def _preset(mapping, message):
    def accept(server, args):
        _only(args, ())
        params = server.core.cfg.stage_parameters
        targets = {}
        for axis, key in mapping:
            if key in params:
                _check_absolute(server.core, axis, params[key])
                targets[axis] = float(params[key])
        if not targets:
            raise ValidationError(message)
        return {"targets": targets}

    return accept


def _run_preset(server, args):
    server.core.move_absolute({f"{a}_abs": v for a, v in args["targets"].items()})
    server.operation["target"] = dict(args["targets"])
    return {"target": args["targets"]}


_COMMANDS = {
    "hello": (READ, _no_args, _hello),
    "ping": (READ, _no_args, _ping),
    "get_state": (READ, _no_args, _get_state),
    "get_position": (READ, _no_args, _get_position),
    "get_config": (READ, _no_args, _get_config),
    "get_info": (READ, _no_args, _get_info),
    "get_limits": (READ, _no_args, _get_limits),
    "get_progress": (READ, _no_args, _get_progress),
    "get_acquisition_list": (READ, _no_args, _get_acquisition_list),
    "stat_files": (READ, _accept_stat_files, _run_stat_files),
    "move_absolute": (WAIT, _accept_move_absolute, _run_move_absolute),
    "move_relative": (WAIT, _accept_move_relative, _run_move_relative),
    "zero": (ACTION, _accept_axes, _run_zero),
    "unzero": (ACTION, _accept_axes, _run_unzero),
    "stop": (EMERGENCY, _no_args, _run_stop),
    "set_state": (ACTION, _accept_set_state, _run_set_state),
    "acquire_start": (WAIT, _accept_acquire_start, _run_acquire_start),
    "acquire_finish": (ACTION, _no_args, _run_acquire_finish),
    "load_sample": (
        WAIT,
        _preset([("y", "y_load_position")], "stage configuration has no y_load_position"),
        _run_preset,
    ),
    "unload_sample": (
        WAIT,
        _preset([("y", "y_unload_position")], "stage configuration has no y_unload_position"),
        _run_preset,
    ),
    "center_sample": (
        WAIT,
        _preset(
            [("x", "x_center_position"), ("y", "y_center_position")],
            "stage configuration has no centre position",
        ),
        _run_preset,
    ),
}
