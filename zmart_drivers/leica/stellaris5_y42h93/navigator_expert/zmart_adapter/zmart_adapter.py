r"""ZMART Controller adapter for the Navigator Expert driver.

The ops table that plugs this driver into ``zmart_controller``: one
function per controller op, each taking the opaque handle as its first
argument. The controller stays vendor-free — this module (not the
controller) knows both contracts, and importing it registers the
instrument::

    import zmart_controller
    import zmart_drivers.leica.stellaris5_y42h93.navigator_expert.zmart_adapter  # registers

    instrument = next(
        i for i in zmart_controller.get_instruments() if i["vendor"] == "leica"
    )
    zmart_controller.set_instrument(instrument)

Frame math lives here: the driver speaks absolute stage micrometres, the
controller speaks micrometres relative to the origin set by
``set_origin``. The controller's single ``z`` axis is the *focus*
displacement — the sum of the two physical drives (z-wide + z-galvo)
relative to the origin's focus sum — so it reads the same regardless of
which drive realized a move. An objective change is compensated with the
calibration's per-objective translation totals (ΔT relative to the
origin's objective): x/y apply to the motoric stage, z in focus space — a
driver-side assumption; the calibration schema is unchanged (operator
decision, 2026-07-02). Cross-objective moves REFUSE when translations are
unavailable; reads warn and return uncompensated. The driver package
itself is untouched. Full design: ``docs/design/objective-aware-frame.md``.

Scope of v1 (grow as needed):
    - ``set_origin`` captures stage XY, both z drives, and the current
      objective as the zero point, persisted machine-locally to
      ``origin.json`` in the newest machine snapshot (next to
      ``calibration.json`` / ``limits.json``) and restored by ``connect`` -
      the origin stays the frame truth across sessions until set again.
    - ``get_xyz`` returns both frames: controller-relative values plus
      the raw hardware readings under ``"hardware"``.
    - ``get_state``/``set_state`` round-trip the selected job (the job
      is LAS X's unit of configuration, so reapplying the selection
      restores the whole setup).
    - ``get_procedures`` offers backlash takeup and autofocus (with
      job discovery); ``run_procedure`` runs them.
    - ``acquire`` selects the job, captures, and saves in one step;
      ``acquisition_type``/``position_label`` map onto the driver's
      Naming slots and travel verbatim in the save lineage.

Live-validation note: the z model assumes the two drives combine
*additively with the same sign*. The arithmetic, readback keys/units,
and sign convention are validated against a live CAM by
``tests/hardware/validate_zmart_adapter.py`` (galvo leg). The *physical*
additivity of the two drives on a real objective still wants one hardware
pass (park the galvo at a known offset, move z-wide, check the focus sum)
before trusting large z moves.

Dependency direction:
    - Imports: driver internals, ``zmart_controller.registry``,
      ``shared.output_layout``.
    - Imported by: nothing in the driver — workflows opt in explicitly.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared.output_layout import Naming
from shared.output_layout.naming import run_hash
from zmart_controller import registry as _registry

try:  # driver version for embedded export state; never fail acquire over it
    from .. import __version__ as _DRIVER_VERSION
except Exception:  # noqa: BLE001 -- best-effort provenance
    _DRIVER_VERSION = None

from .. import orientation as _orientation
from .. import readers as _readers
from .. import scanfields as _scanfields
from ..acquisition import capture as _capture
from ..acquisition import save as _save
from ..calibration.core import model as _cal_model
from ..commands import commands as _commands
from ..commands import gate as _gate
from ..config import machine as _machine
from ..connection import session as _session
from ..motion import limits as _limits
from ..motion import movement as _motion
from ..readers.derived import z_um_from_settings as _z_um_from_settings
from . import procedures as _procedures

log = logging.getLogger(__name__)

CONNECTION = {
    "vendor": "leica",
    "microscope": "stellaris5-y42h93",
    "api": "navigator-expert",
    # driver-specific connect params — edit before set_instrument():
    "client": "PythonClient",
    "api_delay_ms": None,
    "output_root": None,  # optional override; otherwise discovered from native AutoSave
    "calibration_name": None,  # optional ProgramData calibrations/<name>/calibration.json
}

_ACTUATORS = {"x": ("motoric",), "y": ("motoric",), "z": ("z-wide", "z-galvo")}

# Fixed defaults for axes omitted from ``with_actuators`` — never sticky: a
# previous call's choice is not state.
_DEFAULT_ACTUATORS = {"x": "motoric", "y": "motoric", "z": "z-wide"}

# controller actuator name -> driver move_z z_mode
_Z_MODES = {"z-wide": "zwide", "z-galvo": "galvo"}

# Function-keyed limits are enforced BELOW this adapter, in the command
# wrappers themselves (commands/gate.py; maintainer decision §7) — the
# adapter no longer carries its own gate. connect() runs the limits
# handshake; a failed handshake leaves the session read-only and every
# mutating command underneath refuses with the recorded reason. What the
# adapter keeps is the whole-move XY+Z pre-flight in set_xyz (both legs
# checked before any motion), deliberate defense in depth the per-command
# checks cannot replicate.


@dataclass
class ZmartHandle:
    """Opaque controller handle: the CAM client plus all adapter state.

    Attributes:
        client: Connected LAS X CAM client (process-lifetime, no close).
        connection: The connection dict this session was opened with
            (carries ``output_root`` and the connect params).
        hash6: SESSION hash, minted at connect. Travels in lineage /
            ``session_hash6`` provenance only — each :func:`acquire` mints
            its OWN per-acquisition hash for the output Naming.
        origin: The frame zero point captured by :func:`set_origin` —
            stage XY, both z drives, their focus sum, and the objective
            it was captured under. Defaults to all-zero (frame ==
            absolute stage coordinates) until ``set_origin`` runs.
        position_counter: Next per-session position index handed to an
            unlabeled :func:`acquire` (formatted 6-digit zero-padded). An
            explicit ``position_label`` does not consume a counter value.
        translations: Per-objective-slot translation triples (µm) from the
            active calibration, loaded at connect; ``None`` when it could not
            be read (cross-objective moves are then refused, reads warn).
        closed: Set by :func:`disconnect`; every op refuses a closed
            handle.
    """

    client: Any
    connection: dict[str, Any]
    hash6: str
    origin: dict[str, Any] = field(
        default_factory=lambda: {
            "x_um": 0.0,
            "y_um": 0.0,
            "z_wide_um": 0.0,
            "z_galvo_um": 0.0,
            "z_focus_um": 0.0,
            "objective": None,
        }
    )
    position_counter: int = 0
    translations: dict[int, tuple[float, float, float]] | None = None
    closed: bool = False


def _require_open(handle: ZmartHandle) -> None:
    """Refuse to drive a disconnected handle."""
    if handle.closed:
        raise RuntimeError("session is disconnected")


# =============================================================================
# Lifecycle
# =============================================================================


def _refuse_if_gated(handle: ZmartHandle, command: str, values: dict) -> None:
    """Pre-flight one command leg against the commands-layer limits gate.

    The gate itself lives below the adapter (``commands/gate.py``) and would
    refuse anyway when the command fires; calling it here lets :func:`set_xyz`
    pre-flight the WHOLE move (both legs) before any motion, and raise the
    ops-contract RuntimeError with the gate's own actionable message.
    """
    refusal = _gate.check_refusal(handle.client, command, values)
    if refusal is not None:
        raise RuntimeError(refusal)


def connect(connection: dict) -> ZmartHandle:
    """Open the CAM client and return the controller handle.

    Args:
        connection: The instrument dict from ``get_instruments()``.
            ``client`` and ``api_delay_ms`` feed the CAM connection;
            ``output_root`` (edited in by the caller) is where
            :func:`acquire` saves and :func:`set_origin` persists.

    Runs the connect-time limits handshake (``commands.gate``): the single
    machine-local ``limits.json`` must exist in the newest machine snapshot,
    validate (its ``constraints``/``functions`` and stage envelope), and sit
    within the hardcoded physical backstop. On success the stage envelope is applied so
    :func:`set_xyz` can move; on failure the session still connects for
    read-only use and every mutating command refuses with an error naming
    the file tried and the notebook that creates it
    (``limits/notebooks/set_stage_limits.ipynb``). Also restores the
    machine-local frame origin persisted by :func:`set_origin` (the origin
    stays the frame truth across sessions until set again; with none
    persisted, the frame is absolute stage coordinates).

    Raises whatever :func:`connect_python_client` raises when LAS X is
    unreachable — the controller surfaces that to the caller unchanged.
    """
    client = _session.connect_python_client(
        client_name=connection.get("client", "PythonClient"),
        api_delay_ms=connection.get("api_delay_ms"),
    )
    _gate.connect_handshake(client)
    handle = ZmartHandle(client=client, connection=dict(connection), hash6=run_hash())
    handle.translations = _load_objective_translations(connection.get("calibration_name"))
    _restore_persisted_origin(handle)
    return handle


def _load_objective_translations(calibration_name: str | None = None) -> dict | None:
    """Per-slot objective translations (µm) from the active calibration.

    The driver ASSUMES (operator decision, 2026-07-02 — calibration.json is
    NOT extended for this): translation x/y apply to the motoric stage and z
    applies in focus space. Returns None when the calibration cannot be
    loaded; the frame math then refuses cross-objective moves and warns on
    cross-objective reads instead of silently computing uncompensated values.
    """
    try:
        config = _cal_model.load_calibration(_machine.MACHINE.calibration_path(calibration_name))
        return {
            int(slot): _cal_model.get_translation_um(config, int(slot))
            for slot in (config.get("objectives") or {})
        }
    except Exception as exc:  # noqa: BLE001 -- config IO / schema; degrade, don't crash connect
        log.warning(
            "objective translations unavailable (%s); cross-objective moves will be refused",
            exc,
        )
        return None


def _objective_delta_um(handle: ZmartHandle, current_objective: dict | None) -> tuple:
    """ΔT = T[current objective] − T[origin's objective], in µm (x, y, z-focus).

    Zero when the origin has no objective anchor or the objective is
    unchanged. Raises RuntimeError when the objective HAS changed but the
    translations are unavailable — the caller decides whether that refuses
    (moves) or warns (reads).
    """
    origin_slot = (handle.origin.get("objective") or {}).get("slotIndex")
    current_slot = (current_objective or {}).get("slotIndex")
    if origin_slot is None or current_slot == origin_slot:
        return (0.0, 0.0, 0.0)
    t = handle.translations
    if current_slot is None or not t or current_slot not in t or origin_slot not in t:
        raise RuntimeError(
            f"objective changed since set_origin (slot {origin_slot} -> "
            f"{current_slot}) but no calibration translation covers both slots; "
            "re-set the origin under the current objective, or adopt an "
            "objective-pair calibration"
        )
    a, b = t[origin_slot], t[current_slot]
    return (b[0] - a[0], b[1] - a[1], b[2] - a[2])


_ORIGIN_KEYS = ("x_um", "y_um", "z_wide_um", "z_galvo_um", "z_focus_um")


def _restore_persisted_origin(handle: ZmartHandle) -> None:
    """Adopt the machine-local origin as this session's frame zero point.

    Best-effort: an unreadable or malformed origin file is logged and the
    frame stays absolute (all-zero origin) — the safe interpretation, since
    an absolute frame applies no hidden offset.
    """
    try:
        stored = _machine.MACHINE.read_origin()
    except Exception as exc:  # noqa: BLE001 -- config IO / JSON; degrade, don't crash connect
        log.warning("could not read the persisted origin (%s); frame stays absolute", exc)
        return
    if stored is None:
        return
    origin = stored.get("origin") or {}
    if not all(key in origin for key in _ORIGIN_KEYS):
        log.warning(
            "persisted origin at %s is missing keys %s; frame stays absolute",
            _machine.MACHINE.latest_snapshot(),
            [key for key in _ORIGIN_KEYS if key not in origin],
        )
        return
    handle.origin = dict(origin)
    log.info(
        "restored persisted origin (captured_at=%s, objective=%s)",
        stored.get("captured_at"),
        (origin.get("objective") or {}).get("name"),
    )


def disconnect(handle: ZmartHandle) -> None:
    """Mark the handle closed and drop its commands-layer gate state.

    The CAM client itself has no teardown, and none exists to call: verified
    by reflection that ``LasxApiClientPyModel`` (the client `connect_python_client`
    returns) exposes only ``Connect``/``ConnectAsync`` (plus a COM-style
    ``Release``, not a session close) -- there is no ``Disconnect``/``Close``/
    ``Dispose``. Reconnecting without disconnecting the previous handle was
    also verified live (both connections independently ping and read state
    correctly; the first stays usable after the second connects) -- a
    resource leak on the LAS X side, not a corruption/dead-end risk. Without
    this function's ``uninstall`` call, a disconnected client's
    ``FunctionLimits`` stayed installed in the gate's module-level registry
    indefinitely; a reconnect on a new handle re-runs the handshake and
    installs its own state regardless, but a stale entry left behind after
    disconnect is real teardown debt, not just cosmetic.
    """
    _gate.uninstall(handle.client)
    handle.closed = True


# =============================================================================
# Frame and movement
# =============================================================================


def _hardware_snapshot(handle: ZmartHandle) -> dict:
    """One consistent read of everything the frame math needs.

    Stage XY, both z drives, and the current objective come from the
    authoritative API route; raises when any of them is unreadable.
    """
    xy = _readers.get_xy(handle.client, mode="api")
    if not xy:
        raise RuntimeError("could not read stage XY position")
    job = _selected_job_name(handle)
    settings = _readers.get_job_settings(handle.client, job, mode="api")
    if not settings:
        raise RuntimeError(f"could not read job settings for '{job}'")
    return {
        "job": job,
        "x_um": float(xy["x_um"]),
        "y_um": float(xy["y_um"]),
        "z_wide_um": _z_um_from_settings(settings, "z-wide"),
        "z_galvo_um": _z_um_from_settings(settings, "z-galvo"),
        "objective": settings.get("objective"),
    }


def _delta_or_warn(handle: ZmartHandle, snapshot: dict) -> tuple:
    """ΔT for a READ: uncompensated-but-loud when translations are missing.

    Reads must stay available (a read cannot land the stage anywhere wrong),
    so a missing translation degrades to ΔT = 0 with a warning instead of
    raising — unlike moves, which refuse.
    """
    try:
        return _objective_delta_um(handle, snapshot.get("objective"))
    except RuntimeError as exc:
        log.warning("%s; frame values are UNCOMPENSATED for the objective change", exc)
        return (0.0, 0.0, 0.0)


def _selected_job_name(handle: ZmartHandle) -> str:
    """Name of the currently selected LAS X job; raises when unreadable."""
    selected = _readers.get_selected_job(handle.client, mode="api")
    name = selected.get("Name") if selected else None
    if not name:
        raise RuntimeError("could not determine the selected LAS X job")
    return name


def _job_catalog(handle: ZmartHandle) -> tuple[list[dict], list[dict]]:
    """The live job catalog split into (normal, autofocus) jobs.

    Autofocus jobs are a separate category: they never appear as acquisition
    or state options and run only through the ``autofocus`` procedure.
    """
    jobs = _readers.get_jobs(handle.client, mode="api") or []
    normal = [dict(j) for j in jobs if not j.get("IsAutofocus")]
    autofocus = [dict(j) for j in jobs if j.get("IsAutofocus")]
    return normal, autofocus


def set_origin(handle: ZmartHandle) -> dict:
    """The current position becomes (0, 0, 0) of the controller frame.

    Captures stage XY, both z drives, their focus sum, and the current
    objective as the zero point, and persists that reference machine-locally
    as ``origin.json`` in the newest machine snapshot (next to
    ``calibration.json`` / ``limits.json``). The persisted origin is restored
    by :func:`connect`, so it stays the frame truth until set again. On a
    machine with no snapshot yet (never calibrated) the origin is kept in
    memory only, with a warning.

    Not limits-gated: this op fires no native command — it reads the current
    position and persists a machine-local reference file. (The commands-layer
    gate governs everything that commands hardware; ``set_origin`` stays in
    the ``limits.json`` ``functions`` vocabulary so machine files remain
    explicit about it.)
    """
    _require_open(handle)
    snap = _hardware_snapshot(handle)
    handle.origin = {
        "x_um": snap["x_um"],
        "y_um": snap["y_um"],
        "z_wide_um": snap["z_wide_um"],
        "z_galvo_um": snap["z_galvo_um"],
        "z_focus_um": snap["z_wide_um"] + snap["z_galvo_um"],
        "objective": snap["objective"],
    }
    payload = {
        "origin": handle.origin,
        "job": snap["job"],
        "session_hash6": handle.hash6,
        "captured_at": time.time(),
    }
    try:
        path = _machine.MACHINE.write_origin(payload)
    except OSError as exc:
        # The in-memory origin is already set; failing to persist the
        # reference must be loud (re-running set_origin after fixing the
        # cause is cheap), not a silent divergence discovered later.
        raise RuntimeError(f"could not persist origin reference: {exc}") from exc
    if path is None:
        log.warning(
            "set_origin: no machine snapshot under %s; origin kept in memory only "
            "(adopt a calibration to make it persistent)",
            _machine.MACHINE.snapshot_root(),
        )
    return {
        "origin": {"x": 0.0, "y": 0.0, "z": 0.0},
        "reference": dict(handle.origin),
        "origin_file": None if path is None else str(path),
    }


def get_actuators(handle: ZmartHandle) -> dict:
    """The actuator menu per axis — exactly the names ``with_actuators`` accepts.

    ``{"x": ["motoric"], "y": ["motoric"], "z": ["z-wide", "z-galvo"]}``.
    Axes omitted from ``with_actuators`` use the fixed defaults (x/y
    ``motoric``, z ``z-wide``) — never sticky: a previous call's choice is
    not remembered.
    """
    _require_open(handle)
    return {axis: list(opts) for axis, opts in _ACTUATORS.items()}


def _resolve_actuators(with_actuators: dict | None) -> dict[str, str]:
    """Merge a per-call actuator selection over the fixed defaults."""
    chosen = dict(_DEFAULT_ACTUATORS)
    for axis, actuator in (with_actuators or {}).items():
        if actuator not in _ACTUATORS.get(axis, ()):
            raise ValueError(f"unknown actuator {actuator!r} for axis {axis!r}")
        chosen[axis] = actuator
    return chosen


def get_xyz(handle: ZmartHandle, *, with_actuators: dict | None = None) -> dict:
    """Position per axis in the frame (um from the origin), plus raw hardware.

    ``F = fresh_read − origin − ΔT``: the frame ``z`` is the *focus*
    displacement ((z-wide + z-galvo) minus the origin's focus sum, so it
    reads the same regardless of which drive realized the move), and ΔT
    compensates an objective change relative to the origin's objective
    (uncompensated-but-loud when translations are unavailable). The
    untranslated stage values (XY, both z drives, objective) ride along
    under ``"hardware"``.
    """
    _require_open(handle)
    chosen = _resolve_actuators(with_actuators)
    snap = _hardware_snapshot(handle)
    dt = _delta_or_warn(handle, snap)
    z_focus = snap["z_wide_um"] + snap["z_galvo_um"]
    frame = {
        "x": snap["x_um"] - handle.origin["x_um"] - dt[0],
        "y": snap["y_um"] - handle.origin["y_um"] - dt[1],
        "z": z_focus - handle.origin["z_focus_um"] - dt[2],
    }
    result = {
        axis: {"value": frame[axis], "unit": "um", "actuator": chosen[axis]}
        for axis in ("x", "y", "z")
    }
    result["objective_translation_um"] = list(dt)
    result["hardware"] = {
        "x_um": snap["x_um"],
        "y_um": snap["y_um"],
        "z_wide_um": snap["z_wide_um"],
        "z_galvo_um": snap["z_galvo_um"],
        "objective": snap["objective"],
        "job": snap["job"],
    }
    return result


def set_xyz(
    handle: ZmartHandle, x: float, y: float, z: float, *, with_actuators: dict | None = None
) -> dict:
    """Move to (x, y, z) in the frame; confirmed or this raises.

    Destination = origin + F + ΔT, commanded absolutely. One decomposition
    rule: the chosen z actuator absorbs the whole change, the other drive
    holds where it is::

        chosen_drive = origin_focus + z + ΔT.z − other_drive_current

    ΔT compensates an objective change relative to the origin's objective
    (from the calibration's translation totals); a cross-objective move with
    no translations available REFUSES. All targets are pre-flighted against
    the stage envelope before anything moves — an out-of-range galvo target
    refuses the whole move with the actionable alternative.
    """
    _require_open(handle)
    chosen = _resolve_actuators(with_actuators)
    snap = _hardware_snapshot(handle)
    dt = _objective_delta_um(handle, snap.get("objective"))  # raises if unavailable
    abs_x = handle.origin["x_um"] + x + dt[0]
    abs_y = handle.origin["y_um"] + y + dt[1]
    target_focus = handle.origin["z_focus_um"] + z + dt[2]
    if chosen["z"] == "z-wide":
        z_target = target_focus - snap["z_galvo_um"]
    else:
        z_target = target_focus - snap["z_wide_um"]
    z_mode = _Z_MODES[chosen["z"]]

    # Pre-flight the WHOLE move (XY and Z legs) before anything travels, so a
    # doomed z leg can never leave the stage at a new XY with the old focus.
    # Two layers on purpose: the commands-layer function gate carries
    # provenance (which file, which constraint) and would refuse each leg at
    # fire time anyway; checking both legs here first preserves whole-move
    # atomicity, with the driver's own Phase A checks as the net underneath.
    z_param = "z_galvo_um" if chosen["z"] == "z-galvo" else "z_wide_um"
    _refuse_if_gated(handle, "move_xy", {"x_um": abs_x, "y_um": abs_y})
    _limits._check_xy_limits(abs_x, abs_y)
    try:
        _refuse_if_gated(handle, "move_z", {z_param: z_target})
        _limits._check_z_limits(z_target, z_mode)
    except RuntimeError as exc:
        alternative = "z-wide" if chosen["z"] == "z-galvo" else "z-galvo"
        raise RuntimeError(
            f"refusing the whole move before any motion: {exc} "
            f"(try with_actuators={{'z': '{alternative}'}})"
        ) from exc

    # Backlash-compensated transit raises unless the readback confirms.
    _motion.move_xy_with_backlash(handle.client, abs_x, abs_y)

    z_result = _commands.move_z(handle.client, snap["job"], z_target, unit="um", z_mode=z_mode)
    if not z_result.get("success") or not z_result.get("confirmed"):
        raise RuntimeError(f"move_z ({chosen['z']}) failed or was unconfirmed: {z_result}")

    return {
        "position": {"x": x, "y": y, "z": z},
        "actuators": dict(chosen),
        "objective_translation_um": list(dt),
        "hardware_targets": {
            "x_um": abs_x,
            "y_um": abs_y,
            f"{chosen['z'].replace('-', '_')}_um": z_target,
        },
    }


# =============================================================================
# Acquisition (captures and saves)
# =============================================================================


def get_acquisition_options(handle: ZmartHandle) -> dict:
    """The acquisition + saving options this instrument offers (options + active).

    Discovered live on every call: ``job`` lists the LAS X jobs with the
    selected one active; ``cleanup_source`` is forwarded
    to the driver's ``save()``; ``backlash_correction`` runs an XY slack
    takeup before capture; ``strip_scan_fields`` (Leica-specific, default
    on) empties the scanning template before the capture so LAS X acquires
    the single current position, never a stored scan-field pattern.
    """
    _require_open(handle)
    normal, _ = _job_catalog(handle)
    names = [j["Name"] for j in normal if j.get("Name")]
    selected = next((j["Name"] for j in normal if j.get("IsSelected")), None)
    return {
        "job": {"options": names, "active": selected},
        "backlash_correction": {"options": [True, False], "active": True},
        "strip_scan_fields": {"options": [True, False], "active": True},
        "format": {"options": ["ome-tiff"], "active": "ome-tiff"},
        "cleanup_source": {"options": [True, False], "active": False},
    }


def _with_defaults(handle: ZmartHandle, options: dict | None) -> dict:
    """Validate options against the live menu, filling omissions from actives."""
    menu = get_acquisition_options(handle)
    resolved = {name: spec["active"] for name, spec in menu.items()}
    for name, value in (options or {}).items():
        if name not in menu:
            raise ValueError(f"unknown acquisition option {name!r}")
        if value not in menu[name]["options"]:
            raise ValueError(
                f"invalid value {value!r} for acquisition option {name!r} "
                f"(available: {menu[name]['options']!r})"
            )
        resolved[name] = value
    return resolved


def _ensure_scan_fields_stripped(handle: ZmartHandle) -> None:
    """Empty the scanning template before a capture.

    A template carrying scan fields makes LAS X acquire the stored pattern
    instead of the single current position. Sidecar strip only (never
    in-place): the operator's canonical template files stay on disk and
    ``drv.restore_template`` can bring the fields back. Cheap when there is
    nothing to do — "stripped" and "fresh" return immediately.
    """
    state = _scanfields.get_template_state()
    if state in ("stripped", "fresh"):
        return
    if state == "unreadable":
        raise RuntimeError(
            "scanning template is unreadable; cannot verify the scan field is empty — "
            "fix or remove the template, or pass options={'strip_scan_fields': False}"
        )
    if not _scanfields.strip_template(handle.client):
        raise RuntimeError("could not strip the scanning template before acquiring")


def _next_position_label(handle: ZmartHandle) -> str:
    """The next per-session position label ("000000", "000001", ...).

    Consumes one counter value. Only used when :func:`acquire` gets no
    explicit ``position_label``.
    """
    label = f"{handle.position_counter:06d}"
    handle.position_counter += 1
    return label


def _try(fn):
    """Call ``fn()``; degrade any failure to ``None`` (state must not fail save)."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 -- provenance capture is best-effort
        log.debug("export-state field unavailable: %s", exc)
        return None


def _export_state(
    handle: ZmartHandle,
    *,
    acquisition_type: str,
    position_label: str,
    acquisition_hash: str,
    job: str,
) -> dict:
    """A JSON-serialisable snapshot of machine/software state at export time.

    Every field is captured best-effort: a missing reader degrades to
    ``None`` rather than failing the save. Embedded per-plane by ``save``.
    """
    machine_state = _try(lambda: get_state(handle))
    return {
        "software": {
            "driver_version": _DRIVER_VERSION,
            "client": handle.connection.get("client"),
            "api": handle.connection.get("api"),
        },
        "hardware": _try(lambda: _readers.get_hardware_info(handle.client, mode="api")),
        "job_settings": _try(lambda: _readers.get_job_settings(handle.client, job, mode="api")),
        "job_state": (machine_state or {}).get("changeable") if machine_state else None,
        "position": _try(lambda: get_xyz(handle)),
        "provenance": {
            "acquisition_type": acquisition_type,
            "position_label": position_label,
            "job": job,
            "session_hash6": handle.hash6,
            "acquisition_hash": acquisition_hash,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def acquire(
    handle: ZmartHandle,
    *,
    acquisition_type: str = "scan",
    position_label: str | None = None,
    options: dict | None = None,
) -> dict:
    """Run the job, wait for the export, and persist the OME-TIFF product.

    Args:
        acquisition_type: Kind of scan; names the output folder/files, so it
            must be kebab-case lowercase (``Naming`` raises a clear
            ``ValueError`` otherwise). Defaults to ``"scan"``.
        position_label: Free text naming this position; sanitized into the
            filename by ``Naming``. When omitted, the next per-session
            counter value ("000000", "000001", ...) is used (an explicit
            label does NOT consume a counter value). The label travels
            verbatim in the lineage record ``save()`` writes to
            ``summary.json`` and in the embedded per-plane state.
        options: Values from :func:`get_acquisition_options`; omitted
            options use the active defaults, unknown keys/values raise.

    A fresh per-acquisition hash is minted here (``run_hash()``) and used as
    ``Naming.hash6``; the session hash (``handle.hash6``) rides along only in
    lineage/provenance. The machine/software state at export time is captured
    and embedded in each saved plane's OME-XML (no sidecar).

    Returns a record with the resolved job/options and the saved image paths.
    Raises on any unrecoverable step — job selection, capture, export
    detection, or persistence.
    """
    _require_open(handle)
    output_root = _procedures.output_root(handle, _save.save_source_root)
    resolved = _with_defaults(handle, options)
    job = resolved["job"]
    if not job:
        raise RuntimeError("no LAS X job selected and none passed via options['job']")

    # Strip BEFORE selecting: stripping reloads the experiment, which could
    # otherwise undo the selection.
    if resolved["strip_scan_fields"]:
        _ensure_scan_fields_stripped(handle)

    if job != _selected_job_name(handle):
        select = _commands.select_job(handle.client, job)
        if not select.get("success"):
            raise RuntimeError(f"select_job('{job}') failed: {select}")

    if resolved["backlash_correction"]:
        _motion.correct_backlash(handle.client)

    acq = _capture.acquire(handle.client, job)

    label = position_label if position_label is not None else _next_position_label(handle)
    acquisition_hash = run_hash()
    naming = Naming(
        acquisition_type=acquisition_type,
        hash6=acquisition_hash,
        position_label=label,
    )
    state = _export_state(
        handle,
        acquisition_type=acquisition_type,
        position_label=label,
        acquisition_hash=acquisition_hash,
        job=job,
    )
    saved = _save.save(
        handle.client,
        acq,
        output_root,
        naming,
        lineage={
            "acquisition_type": acquisition_type,
            "position_label": label,
            "job": job,
            "session_hash6": handle.hash6,
            "acquisition_hash": acquisition_hash,
        },
        state=state,
        # Rig image->stage orientation, applied to the saved planes behind the
        # scenes so the workflow only ever sees stage-aligned images. Measured
        # once by the set_orientation setup notebook; a separate concern from
        # pixel-scale calibration and limits.
        orientation=_orientation.rig_orientation(),
        cleanup_source=resolved["cleanup_source"],
    )

    return {
        "acquisition_type": acquisition_type,
        "position_label": label,
        "job": job,
        "format": resolved["format"],
        "settle": "backlash-corrected" if resolved["backlash_correction"] else "direct",
        "images": sorted(str(path) for path in saved.image_paths.values()),
    }


# =============================================================================
# State and procedures
# =============================================================================


def get_state(handle: ZmartHandle) -> dict:
    """The instrument state: the changeable part first, then the observed report.

    ``changeable`` is the promise — exactly what :func:`set_state` reapplies.
    It is deliberately just the selected job: the job *is* the unit of
    configuration in LAS X, so reapplying the selection round-trips the whole
    setup. ``observed`` is a read-only report of identity and condition — the
    connection identity, the hardware-reported serial number and system type
    (simulator vs. real), the stand, the turret configuration (slot →
    objectiveNumber), the full selected-job record, the job catalog, and the
    provenance of the function limits governing this session. All LAS
    X-derived values are fresh reads.
    """
    _require_open(handle)
    hw = _readers.get_hardware_info(handle.client, mode="api") or {}
    microscope = hw.get("Microscope") or {}
    selected = _readers.get_selected_job(handle.client, mode="api") or {}
    if not selected.get("Name"):
        raise RuntimeError("could not determine the selected LAS X job")
    normal, autofocus = _job_catalog(handle)
    return {
        "changeable": {"job": selected["Name"]},
        "observed": {
            "vendor": handle.connection.get("vendor"),
            "microscope": handle.connection.get("microscope"),
            "serial_number": hw.get("SerialNumber"),
            "system_type": hw.get("SystemType"),
            "stand": microscope.get("name"),
            "objectives": [
                [o.get("slotIndex"), o.get("objectiveNumber")]
                for o in (microscope.get("objectives") or [])
            ],
            "job": dict(selected),
            "jobs": normal,
            "autofocus_jobs": autofocus,
            # Which function-limits file governs this session (evidence, not
            # an instruction): path, source tag, is_fallback — reported by
            # the commands-layer gate. None when the limits handshake failed
            # (every mutating command underneath is then refusing).
            "limits": _gate.describe(handle.client),
        },
    }


def set_state(handle: ZmartHandle, state: dict) -> dict:
    """Apply the changeable part; report what stuck.

    ``observed`` is a report, never an instruction — it is not read here
    (operator decision, 2026-07-02; an identity gate returns only if the
    changeable part ever grows beyond the low-risk job selection). The job
    must still exist on this instrument before it is reapplied: the catalog
    changes legitimately, so only the REFERENT is guarded — with an error
    that lists what is available.
    """
    _require_open(handle)
    applied: dict[str, Any] = {}
    job = (state.get("changeable") or {}).get("job")
    if job and job != _selected_job_name(handle):
        normal, autofocus = _job_catalog(handle)
        names = [j.get("Name") for j in normal if j.get("Name")]
        if job in (j.get("Name") for j in autofocus):
            raise ValueError(
                f"{job!r} is an autofocus job — run it via the 'autofocus' "
                "procedure (run_procedure), not as state"
            )
        if job not in names:
            raise ValueError(
                f"job {job!r} no longer exists on this instrument (available: {names})"
            )
        result = _commands.select_job(handle.client, job)
        if not result.get("success"):
            raise RuntimeError(f"select_job('{job}') failed: {result}")
        applied["job"] = job
    return {"applied": applied}


def get_procedures(handle: ZmartHandle) -> dict:
    """The named procedures this instrument offers (discover-then-apply)."""
    _require_open(handle)
    _, autofocus = _job_catalog(handle)
    return {
        "backlash_takeup": {
            "description": "pin the XY leadscrew slack at the current position (+X +Y approach)"
        },
        "autofocus": {
            "description": "run a LAS X autofocus job (capture only, nothing saved); "
            "restores the previously selected job and returns the focus readback",
            "args": ["job"],
            "jobs": [j["Name"] for j in autofocus if j.get("Name")],
        },
        "get_root": {"description": "return the SMART run output root"},
        "get_positions": {"description": "return LAS X scan-field positions in frame um"},
    }


def run_procedure(handle: ZmartHandle, procedure: dict) -> dict:
    """Run a procedure from :func:`get_procedures`; report what ran."""
    _require_open(handle)
    name = procedure.get("name")
    if name == "get_root":
        return {
            "ran": dict(procedure),
            "output_root": str(_procedures.output_root(handle, _save.save_source_root)),
        }
    if name == "get_positions":
        return {
            "ran": dict(procedure),
            "positions": _procedures.positions(_scan_field(handle)),
        }
    if name == "backlash_takeup":
        _motion.correct_backlash(handle.client)
        return {"ran": dict(procedure)}
    if name == "autofocus":
        return _run_autofocus(handle, procedure)
    raise ValueError(f"unknown procedure {name!r}")


def _run_autofocus(handle: ZmartHandle, procedure: dict) -> dict:
    """Select the autofocus job, run it capture-only, restore the selection.

    ``job`` names the autofocus job; it may be omitted when the instrument
    has exactly one. Nothing is saved — the result is the focus readback
    right after the run (before the selection is restored), in both
    hardware and frame terms. The scanning template is stripped first,
    like every capture (an autofocus must run at the current position,
    never a stored pattern).
    """
    _, autofocus = _job_catalog(handle)
    names = [j["Name"] for j in autofocus if j.get("Name")]
    if not names:
        raise RuntimeError("no autofocus job exists on this instrument")
    job = procedure.get("job")
    if job is None:
        if len(names) > 1:
            raise ValueError(f"multiple autofocus jobs; pass 'job' (available: {names})")
        job = names[0]
    elif job not in names:
        raise ValueError(f"{job!r} is not an autofocus job (available: {names})")

    _ensure_scan_fields_stripped(handle)
    original = _selected_job_name(handle)
    if job != original:
        selected = _commands.select_job(handle.client, job)
        if not selected.get("success"):
            raise RuntimeError(f"select_job('{job}') failed: {selected}")
    try:
        acq = _capture.acquire(handle.client, job)
        # Read the focus result BEFORE restoring the selection: restoring
        # could reposition (jobs own objective state).
        snap = _hardware_snapshot(handle)
    finally:
        if job != original:
            restored = _commands.select_job(handle.client, original)
            if not restored.get("success"):
                log.warning("could not restore job %r after autofocus: %s", original, restored)
    focus = snap["z_wide_um"] + snap["z_galvo_um"]
    dt = _delta_or_warn(handle, snap)
    return {
        "ran": "autofocus",
        "job": job,
        "focus_um": focus,
        "frame_z_um": focus - handle.origin["z_focus_um"] - dt[2],
        "duration_s": acq.finished_at - acq.started_at,
    }


# =============================================================================
# Context and registration
# =============================================================================


def _scan_field(handle: ZmartHandle) -> dict | None:
    """Positions and focus points the operator stored in the scanning template.

    Saves the experiment first (the parsers read the on-disk template; a
    load alone does not flush it), then reports every stored position as a
    typed entry in BOTH coordinate spaces — grid positions name the region
    group they belong to. Template z values are treated as focus positions
    (the same convention as the frame's z axis). None when this machine has
    no LAS X scanning-templates profile.

    Read this BEFORE acquiring: the default ``strip_scan_fields``
    acquisition option empties the template.
    """
    templates_dir = _scanfields.find_scanning_templates_dir()
    if templates_dir is None:
        return None
    saved = _scanfields.save_experiment(
        handle.client,
        _scanfields.TEMPLATE_XML,
        templates_dir,
        timeout=60,
        confirm_path=Path(templates_dir) / _scanfields.TEMPLATE_RGN,
    )
    if not saved:
        raise RuntimeError("save_experiment did not confirm; the template on disk may be stale")
    parsed = _scanfields.parse_scan_positions(
        templates_dir, _scanfields.TEMPLATE_BASE, client=handle.client
    )
    dt = _delta_or_warn(handle, _hardware_snapshot(handle))
    origin = handle.origin

    def entry(kind: str, x_um: float, y_um: float, z_um: float | None, **meta: Any) -> dict:
        return {
            "kind": kind,
            "frame": {
                "x_um": x_um - origin["x_um"] - dt[0],
                "y_um": y_um - origin["y_um"] - dt[1],
                "z_um": None if z_um is None else z_um - origin["z_focus_um"] - dt[2],
            },
            "stage": {"x_um": x_um, "y_um": y_um, "z_um": z_um},
            **meta,
        }

    positions = []
    for region_key, region in (parsed.get("acquisition_positions") or {}).items():
        for tile in region.get("positions") or []:
            positions.append(
                entry(
                    "grid",
                    tile["x_um"],
                    tile["y_um"],
                    tile.get("z_um"),
                    group={"region": region_key, "row": tile.get("row"), "col": tile.get("col")},
                    job=region.get("job_name"),
                )
            )
    for kind, points in (
        ("focus-point", parsed.get("focus_points") or []),
        ("autofocus-point", parsed.get("autofocus_points") or []),
    ):
        for point in points:
            positions.append(
                entry(
                    kind,
                    point["x_um"],
                    point["y_um"],
                    point.get("z_um"),
                    id=point.get("identifier"),
                    enabled=point.get("enabled", True),
                )
            )
    for geometry in (parsed.get("geometries") or {}).values():
        center = geometry.get("center_um") or {}
        if geometry.get("type") == "Point" and center.get("x_um") is not None:
            positions.append(
                entry("marker", center["x_um"], center["y_um"], None, label=geometry.get("label"))
            )
    return {
        "coordinate_spaces": {
            "frame": "um from the origin, objective-compensated (what set_xyz accepts)",
            "stage": "absolute stage um (what LAS X stores)",
        },
        "template_state": _scanfields.get_template_state(templates_dir),
        "positions": positions,
    }


def get_context(handle: ZmartHandle) -> dict:
    """Extra read-only context for the controller.

    Purely informational, so it degrades instead of raising: an
    unreadable job selection or scan field reports ``None`` rather than
    failing a caller that only wanted the output root. Note ``scan_field``
    flushes the live experiment to disk before parsing it (a save, not a
    state change).
    """
    _require_open(handle)
    try:
        selected = _selected_job_name(handle)
    except RuntimeError:
        selected = None
    try:
        scan_field = _scan_field(handle)
    except Exception as exc:  # noqa: BLE001 -- informational surface; degrade, don't raise
        log.warning("scan field unavailable: %s", exc)
        scan_field = None
    return {
        "selected_job": selected,
        "scan_field": scan_field,
        "client": handle.connection.get("client"),
        "output_root": handle.connection.get("output_root"),
        "session_hash6": handle.hash6,
    }


def register() -> None:
    """Register this instrument's ops table with the controller registry."""
    _registry.register(
        CONNECTION,
        ops={
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
            "get_context": get_context,
        },
    )


# Import-time registration IS the opt-in: nothing in the driver imports
# this module, so the instrument appears in get_instruments() exactly when
# a workflow imports the adapter (see the module docstring example).
register()
