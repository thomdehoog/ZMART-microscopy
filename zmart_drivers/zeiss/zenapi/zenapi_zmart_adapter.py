"""
ZMART controller adapter for ZEISS ZEN.
=======================================
The seam that plugs this driver into the vendor-agnostic **ZMART controller**
(``zmart_controller``). The controller drives every microscope through one
small ops table -- ``connect`` plus one callable per operation -- registered
under a ``connection`` identity dict. This module implements that table for
ZEN (through the ZEN API gateway, see ``connection/``) and registers it.

As in the reference ``mock_driver``, the driver owns the frame **origin**: the
controller works in micrometres from an origin the driver subtracts, so the
controller never does coordinate maths. The driver also refuses any move
outside the stage envelope this machine is configured with (fail-closed: an
envelope must exist before anything moves), and it does the capture+save in
one step.

What the neutral surface covers for ZEN today:

* **x/y/z** -- the XY stage and the focus drive (a single "motoric" actuator each).
* **changeable state** -- the objective (turret position).
* **procedures** -- none yet; ZEN's software autofocus and Definite Focus are
  extension seams of the driver, and nothing is advertised before it exists.
* **acquire** -- run a ZEN experiment (by name) to completion and save the
  CZI container ZEN wrote under ``<output_root>/<type>/data/``, with the state
  it was captured under printed beside it under ``data/metadata``.

Register at import: importing this module (which ``import zenapi`` does)
calls :func:`register` at the bottom of the file, so
``zmart_controller.get_instruments()`` lists the ZEISS entry with no explicit
call. It is a safe no-op when ``zmart_controller`` is not installed.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .acquisition import capture as _capture
from .acquisition import save as _save
from .acquisition.naming import Naming, run_hash
from .calibration import machine as _machine
from .commands import commands as _cmd
from .connection.session import close as _close
from .connection.session import connect as _connect
from .limits import checks as _limits
from .limits import stage_config as _stage_config
from .readers import api_reader as _readers

log = logging.getLogger(__name__)

# Per-axis actuator options: ZEN's stage and focus services are one drive each.
_ACTUATORS: dict[str, list[str]] = {"x": ["motoric"], "y": ["motoric"], "z": ["motoric"]}

# The connection identity the ZMART controller keys on. ``microscope`` names a
# specific instrument; edit it per deployment. The connection parameters
# resolve like the driver's ``connect``: an explicit value here wins over the
# ``config.ini`` named by ``config`` (default: the driver's profile path).
# ``control_token`` is a credential: the driver never echoes it.
CONNECTION = {
    "vendor": "zeiss",
    "microscope": "zen-01",
    "api": "zen-api",
    "config": None,
    "host": None,
    "port": None,
    "cert_file": None,
    "control_token": None,
    "experiment": None,
    "output_root": None,
}


@dataclass
class ZenHandle:
    """Live session handle the controller passes back into every op."""

    client: Any
    connection: dict
    output_root: Path
    machine: Any
    stage_cfg: dict = field(default_factory=dict)
    stage_source: str = "defaults"
    origin: dict = field(default_factory=lambda: {"x": 0.0, "y": 0.0, "z": 0.0})
    immutable: dict = field(default_factory=dict)
    initial_position: dict = field(default_factory=dict)
    # Loaded ZEN experiments by name, so a scan does not reload one per position.
    experiments: dict = field(default_factory=dict)
    acquisition_hashes: set = field(default_factory=set)
    closed: bool = False


# =============================================================================
# lifecycle
# =============================================================================


def connect(connection: dict) -> ZenHandle:
    """Open a session with the ZEN API gateway and read what the microscope offers.

    Honours ``config`` (a ZEN API ``config.ini``), ``host`` / ``port`` /
    ``cert_file`` / ``control_token`` (explicit overrides), ``output_root``
    (where ``acquire`` saves; a temp folder when omitted), ``machine_root``
    (override for the ProgramData root) and ``stage_limits`` (an explicit path
    to a stage envelope). The envelope governs every move of the session: the
    machine copy under the ProgramData root wins, else the driver's bundled
    default. The frame origin a previous session persisted is restored.
    """
    client = _connect(
        connection.get("config"),
        host=connection.get("host"),
        port=connection.get("port"),
        cert_file=connection.get("cert_file"),
        control_token=connection.get("control_token"),
    )
    try:
        return _open(client, connection)
    except BaseException:
        _close(client)
        raise


def _open(client: Any, connection: dict) -> ZenHandle:
    """Build the handle over an open client: the envelope, the origin, the first readings."""
    output_root = Path(connection.get("output_root") or tempfile.mkdtemp(prefix="zeiss_run_"))
    output_root.mkdir(parents=True, exist_ok=True)
    machine = _machine.MachineProfile(
        microscope_id=connection.get("microscope") or CONNECTION["microscope"],
        programdata_root=connection.get("machine_root"),
    )
    explicit = connection.get("stage_limits")
    if explicit is not None:
        stage_path, is_fallback = Path(explicit), False
    else:
        stage_path, is_fallback = machine.resolve(_machine.STAGE_LIMITS_FILENAME)
        if is_fallback:
            log.info(
                "no machine stage envelope under %s; using the bundled default",
                machine.machine_dir(),
            )
    stage_cfg = _stage_config.load(stage_path)
    _limits.apply_stage_limits_from_config(stage_cfg)

    xy = _readers.get_xy(client)
    handle = ZenHandle(
        client=client,
        connection=dict(connection),
        output_root=output_root,
        machine=machine,
        stage_cfg=stage_cfg,
        stage_source=str(stage_cfg.get("source") or ("defaults" if is_fallback else "machine")),
        immutable={
            "app": "ZEN",
            "api": "ZEN API (gRPC)",
            "microscope": connection.get("microscope"),
            "host": connection.get("host"),
            "port": connection.get("port"),
        },
        initial_position={
            "x": float(xy["x_um"]),
            "y": float(xy["y_um"]),
            "z": float(_readers.get_z(client)),
        },
    )
    _restore_persisted_origin(handle)
    log.info("ZEN controller session ready (output_root=%s)", output_root)
    return handle


def _restore_persisted_origin(handle: ZenHandle) -> None:
    try:
        payload = handle.machine.read_origin()
    except Exception as exc:  # noqa: BLE001 - a corrupt file must not block connect
        log.warning("could not read persisted origin (%s); frame is raw stage coordinates", exc)
        return
    if not payload:
        return
    origin = payload.get("origin") or {}
    try:
        handle.origin = {axis: float(origin[axis]) for axis in ("x", "y", "z")}
    except (KeyError, TypeError, ValueError) as exc:
        log.warning("persisted origin is malformed (%s); frame is raw stage coordinates", exc)
        return
    log.info(
        "restored frame origin from %s", handle.machine.machine_dir() / _machine.ORIGIN_FILENAME
    )


def disconnect(handle: ZenHandle) -> None:
    """Close the gRPC channel and stop the client's event loop."""
    handle.closed = True
    _close(handle.client)


def _require_open(handle: ZenHandle) -> None:
    if handle.closed:
        raise RuntimeError("session is disconnected")


# =============================================================================
# frame origin
# =============================================================================


def _raw_xyz(handle: ZenHandle) -> dict[str, float]:
    """The stage and focus positions as ZEN reports them, in micrometres."""
    xy = _readers.get_xy(handle.client)
    return {
        "x": float(xy["x_um"]),
        "y": float(xy["y_um"]),
        "z": float(_readers.get_z(handle.client)),
    }


def _user_xyz(handle: ZenHandle, raw: dict) -> dict[str, float]:
    return {axis: float(raw[axis]) - handle.origin[axis] for axis in ("x", "y", "z")}


def set_origin(handle: ZenHandle) -> dict:
    """Mark the current position as the origin -- it now reads (0, 0, 0).

    Persisted in the machine folder and restored by :func:`connect`, so the zero
    point survives reconnects until it is set again.
    """
    _require_open(handle)
    handle.origin = _raw_xyz(handle)
    try:
        path = handle.machine.write_origin(
            {
                "origin": dict(handle.origin),
                "microscope": handle.immutable.get("microscope"),
                "captured_at": time.time(),
            }
        )
    except OSError as exc:
        raise RuntimeError(f"could not persist origin reference: {exc}") from exc
    return {"origin": dict(handle.origin), "origin_file": str(path)}


# =============================================================================
# movement
# =============================================================================


def get_actuators(handle: ZenHandle) -> dict:
    """The actuator options each axis offers: one motorised drive per axis."""
    _require_open(handle)
    return {axis: list(opts) for axis, opts in _ACTUATORS.items()}


def _resolve_actuators(with_actuators: dict | None) -> dict[str, str]:
    """Per-axis actuator choice for one call, validated; omitted axes use the only one."""
    chosen = {axis: opts[0] for axis, opts in _ACTUATORS.items()}
    for axis, actuator in (with_actuators or {}).items():
        if axis not in _ACTUATORS:
            raise ValueError(f"unknown axis {axis!r}")
        name = actuator[0] if isinstance(actuator, (list, tuple)) else actuator
        if name not in _ACTUATORS[axis]:
            raise ValueError(f"unknown actuator {actuator!r} for axis {axis!r}")
        chosen[axis] = name
    return chosen


def get_xyz(handle: ZenHandle, *, with_actuators: dict | None = None) -> dict:
    """Report the position per axis (um, relative to the origin) with its actuator."""
    _require_open(handle)
    chosen = _resolve_actuators(with_actuators)
    user = _user_xyz(handle, _raw_xyz(handle))
    return {
        axis: {"value": user[axis], "actuator": chosen[axis], "unit": "um"}
        for axis in ("x", "y", "z")
    }


def set_xyz(
    handle: ZenHandle, x: float, y: float, z: float, *, with_actuators: dict | None = None
) -> dict:
    """Move to an absolute target (um, relative to the origin); return a move record.

    The target is mapped to raw stage coordinates through the origin and checked
    against the stage envelope before ZEN is asked to move: an out-of-range
    target refuses without touching the microscope. The stage moves first, the
    focus drive second; each leg returns once ZEN reports it complete and the
    driver has read the position back.
    """
    _require_open(handle)
    chosen = _resolve_actuators(with_actuators)
    targets = {
        axis: handle.origin[axis] + float(value) for axis, value in (("x", x), ("y", y), ("z", z))
    }
    # The envelope is checked here, before anything is asked of ZEN, and again
    # inside the move commands themselves (the driver's own safety net).
    try:
        _limits._check_xy_limits(targets["x"], targets["y"])
        _limits._check_z_limits(targets["z"])
    except RuntimeError as exc:
        raise RuntimeError(f"set_xyz refused: {exc}") from exc
    moved_xy = _cmd.move_xy(handle.client, targets["x"], targets["y"])
    if not moved_xy.get("success"):
        raise RuntimeError(f"set_xyz failed: {moved_xy.get('message')}")
    moved_z = _cmd.move_z(handle.client, targets["z"])
    if not moved_z.get("success"):
        raise RuntimeError(f"set_xyz failed on z: {moved_z.get('message')}")
    confirmed = bool(moved_xy.get("confirmed")) and bool(moved_z.get("confirmed"))
    return {
        "position": {"x": float(x), "y": float(y), "z": float(z)},
        "confirmed": confirmed,
        "read_back": _user_xyz(handle, _raw_xyz(handle)),
        "actuators": chosen,
    }


# =============================================================================
# state
# =============================================================================


def get_state(handle: ZenHandle) -> dict:
    """Changeable settings first, then the observed report.

    Changeable: ``objective_index`` (the turret position ZEN switches by).
    Observed: identity, the fitted objectives, the current objective by name,
    the raw position, and the stage envelope governing this session.
    """
    _require_open(handle)
    objective = _readers.get_objective(handle.client)
    observed = dict(handle.immutable)
    observed["objective"] = dict(objective)
    observed["objectives"] = [dict(o) for o in _readers.get_objectives(handle.client)]
    observed["position"] = _raw_xyz(handle)
    observed["limits"] = {
        "source": handle.stage_source,
        "stage_um": dict(handle.stage_cfg.get("stage_um", {})),
    }
    return {"changeable": {"objective_index": objective.get("index")}, "observed": observed}


def set_state(handle: ZenHandle, state: dict) -> dict:
    """Apply the changeable settings; report what stuck.

    Accepts ``objective_index`` (a turret position) or ``objective`` (a name
    from the observed list). ``observed`` is a report, never an instruction,
    and is not read here.
    """
    _require_open(handle)
    changeable = state.get("changeable") or {}
    applied: dict[str, Any] = {}
    if changeable.get("objective") is not None:
        result = _cmd.set_objective(handle.client, name=str(changeable["objective"]))
        if not result.get("success"):
            raise RuntimeError(f"set_state failed: {result.get('message')}")
        applied["objective_index"] = result.get("index")
    elif changeable.get("objective_index") is not None:
        result = _cmd.set_objective(handle.client, index=int(changeable["objective_index"]))
        if not result.get("success"):
            raise RuntimeError(f"set_state failed: {result.get('message')}")
        applied["objective_index"] = result.get("index")
    return {"applied": applied}


# =============================================================================
# procedures
# =============================================================================


def get_procedures(handle: ZenHandle) -> dict:
    """The named procedures this driver offers: none yet.

    ZEN's software autofocus and Definite Focus are extension seams of the
    driver (see the README); nothing is advertised before it exists, so a
    workflow cannot mistake "listed" for "working".
    """
    _require_open(handle)
    return {}


def run_procedure(handle: ZenHandle, procedure: dict) -> dict:
    """Run a procedure. None are offered yet, so every name is refused."""
    _require_open(handle)
    raise ValueError(
        f"unknown procedure {procedure.get('name')!r}; this driver offers none yet "
        "(autofocus is an extension seam, see the README)"
    )


# =============================================================================
# acquire (captures and saves)
# =============================================================================


def get_acquisition_options(handle: ZenHandle) -> dict:
    """The acquisition + saving options this instrument offers (options + active).

    ``experiment`` is the name of the ZEN experiment to run; the ZEN API does
    not list experiments, so the name comes from the operator (or the
    connection's ``experiment`` default). The output is ZEN's own CZI container.
    """
    _require_open(handle)
    return {
        "experiment": {
            "options": "the name of a ZEN experiment",
            "active": handle.connection.get("experiment"),
        },
        "format": {"options": ["czi"], "active": "czi"},
        "stable_timeout_s": {"options": "float s (how long to wait for the CZI)", "active": 60.0},
    }


def _next_acquisition_hash(handle: ZenHandle) -> str:
    """Mint a unique hash for one acquired position (six base-36 characters)."""
    now = time.time()
    for offset in range(100):
        value = run_hash(now + offset)
        if value not in handle.acquisition_hashes:
            handle.acquisition_hashes.add(value)
            return value
    raise RuntimeError("could not mint a unique acquisition hash")


def _experiment(handle: ZenHandle, name: str):
    """The loaded ZEN experiment handle for *name*, loaded once per session."""
    if name not in handle.experiments:
        handle.experiments[name] = _cmd.load_experiment(handle.client, name)
    return handle.experiments[name]


def _try(fn):
    """Call ``fn()``; degrade any failure to ``None`` (a report must not fail a capture)."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 -- provenance capture is best-effort
        log.debug("state field unavailable: %s", exc)
        return None


def _export_state(
    handle: ZenHandle, *, acquisition_type: str, position_label: str, experiment: str
) -> dict:
    """What the driver knows about the microscope at capture time, JSON-ready."""
    return {
        "software": {
            "driver": "zenapi",
            "api": handle.connection.get("api"),
            "server": dict(handle.immutable),
        },
        "instrument": _try(lambda: get_state(handle)),
        "position": _try(lambda: get_xyz(handle)),
        "origin": dict(handle.origin),
        "provenance": {
            "acquisition_type": acquisition_type,
            "position_label": position_label,
            "experiment": experiment,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def acquire(
    handle: ZenHandle, *, acquisition_type: str, position_label: str, options: dict | None = None
) -> dict:
    """Run a ZEN experiment and save the CZI it wrote; return the record.

    ``acquisition_type`` names the output folder, so it must be kebab-case
    lowercase (``Naming`` says so clearly otherwise). ``options["experiment"]``
    names the ZEN experiment (else the connection's default). The run blocks
    until ZEN's status stream reports it finished; the CZI is then waited for
    until it stops growing and copied to ``<output_root>/<type>/data/``, with
    the state it was captured under printed beside it under ``data/metadata``.

    The record lists the saved ``images`` (one CZI, which holds every channel
    and plane of the experiment) and the ``metadata`` printed; ``position`` is
    where the stage stood, in the frame ``set_xyz`` accepts.
    """
    _require_open(handle)
    options = dict(options or {})
    experiment_name = options.get("experiment") or handle.connection.get("experiment")
    if not experiment_name:
        raise ValueError("acquire needs the name of a ZEN experiment: options={'experiment': ...}")
    fmt = str(options.get("format", "czi"))
    if fmt != "czi":
        raise ValueError(f"unknown format {fmt!r}; ZEN writes 'czi'")
    naming = Naming(
        acquisition_type=acquisition_type,
        hash6=_next_acquisition_hash(handle),
        position_label=position_label,
    )
    state = _export_state(
        handle,
        acquisition_type=acquisition_type,
        position_label=position_label,
        experiment=experiment_name,
    )
    started = time.perf_counter()
    experiment = _experiment(handle, experiment_name)
    output_name = f"{naming.acquisition_type}_{naming.hash6}_{naming.position_label}"
    result = _capture.acquire(handle.client, experiment, output_name=output_name)
    saved = _save.save(
        handle.client,
        result,
        handle.output_root,
        naming,
        state=state,
        stable_timeout_s=float(options.get("stable_timeout_s", 60.0)),
    )
    return {
        "acquisition_type": acquisition_type,
        "position_label": position_label,
        "experiment": experiment_name,
        "format": fmt,
        "acquisition_hash": naming.hash6,
        "images": [str(saved.czi_path)],
        "metadata": [str(saved.state_path)] if saved.state_path else [],
        "position": _user_xyz(handle, _raw_xyz(handle)),
        "duration_s": round(time.perf_counter() - started, 3),
    }


# =============================================================================
# info + registration
# =============================================================================


def get_info(handle: ZenHandle) -> dict:
    """Read-only extras: where the session started, how far the stage may go, and what it stands on.

    ``limits`` is the stage envelope governing this session (um, raw stage
    coordinates) and ``canvas`` the same envelope shifted into the frame, so a
    workflow knows the x/y/z range it may ask for. ``connection_status`` says,
    in words, whether each thing a session needs is in place.
    """
    _require_open(handle)
    raw = _try(lambda: _raw_xyz(handle))
    return {
        "initial_position": dict(handle.initial_position),
        "limits": {
            "source": handle.stage_source,
            "stage_um": dict(handle.stage_cfg.get("stage_um", {})),
        },
        "canvas": _canvas(handle),
        "objectives": _try(lambda: [dict(o) for o in _readers.get_objectives(handle.client)]),
        "output_root": str(handle.output_root),
        "server": dict(handle.immutable),
        "connection_status": _connection_status(handle, raw),
    }


def _canvas(handle: ZenHandle) -> dict | None:
    """The stage envelope shifted into the frame: nothing can be imaged outside it."""
    stage = handle.stage_cfg.get("stage_um")
    if not stage:
        return None
    return {
        f"{axis}_um": [stage[axis][0] - handle.origin[axis], stage[axis][1] - handle.origin[axis]]
        for axis in ("x", "y", "z")
        if axis in stage
    }


def _connection_status(handle: ZenHandle, raw: dict | None) -> dict:
    """What a session stands on, from what the driver already holds; a failure names itself."""
    return {
        "api": "answering" if _readers.ping(handle.client) else "failed — no answer",
        "limits": (
            f"{handle.stage_source}{' (bundled default, not this machine)' if handle.stage_source == 'defaults' else ''}"
        ),
        "stage": (
            f"x {raw['x']:.0f} · y {raw['y']:.0f} · z {raw['z']:.1f} um"
            if raw
            else "failed — no reading"
        ),
        "experiment": handle.connection.get("experiment")
        or "none chosen — pass options={'experiment': ...} to acquire",
        "output root": str(handle.output_root),
    }


OPS = {
    "connect": connect,
    "disconnect": disconnect,
    "get_acquisition_options": get_acquisition_options,
    "set_origin": set_origin,
    "get_actuators": get_actuators,
    "get_xyz": get_xyz,
    "set_xyz": set_xyz,
    "acquire": acquire,
    "get_state": get_state,
    "set_state": set_state,
    "get_procedures": get_procedures,
    "run_procedure": run_procedure,
    "get_info": get_info,
}


def register(connection: dict | None = None) -> None:
    """Register the ZEISS driver with the ZMART controller registry (idempotent)."""
    try:
        from zmart_controller.registry import register as _register
    except Exception:  # noqa: BLE001 - controller optional at import time
        log.debug("zmart_controller not importable; skipping registration", exc_info=True)
        return
    _register(connection or dict(CONNECTION), ops=dict(OPS))


register()
