"""Limits gate for the commands layer.

Maintainer decision (MAINTAINER_DECISIONS.md §7): limits are enforced as low
as possible — at the command wrapper that populates the native CAM function's
model — so nothing built on top (adapter, controller, workflows, notebooks)
can interfere with or bypass them. This module is that chokepoint's state and
policy; the wrappers in ``commands.py`` (and the two experiment-file mutators
in ``scanfields/files.py``) call :func:`check_refusal` before anything fires.

Wrapper -> key mapping
----------------------
The operator-facing ``limits.json`` is flat. Four axis ranges and the objective
slot allow-list carry actual limits; setter names with ``[]`` explicitly show
that those setters are currently unrestricted. The internal mapping below is
only the command chokepoint vocabulary—it is not the JSON shape.

- all ``set_*`` job setters and ``select_job``  -> ``set_state`` (the job is
  LAS X's unit of configuration; selecting/configuring it is the state
  surface)
- ``move_xy`` / ``move_z``                      -> ``set_xyz``
- ``acquire``                                   -> ``acquire``
- ``move_galvo_to_pixel``                       -> ``move_galvo_to_pixel``
  (LRP pan write; its hardcoded ``utils.PAN_LIMIT`` stays the sanctioned
  numeric check, the gate adds fail-closed state + optional file constraints
  on ``pan_x`` / ``pan_y``)
- ``save_experiment`` / ``load_experiment``     -> their own keys (direct
  ``PyApi{Save,Load}Experiment`` fires; loading a template changes what
  ``acquire`` will scan)

Two keys are vocabulary-only (no wrapper maps to them): ``set_origin`` (the
adapter op fires no native command — it reads and persists origin.json) and
``run_procedure`` (its effects run through gated wrappers: backlash ->
``move_xy``, autofocus -> ``select_job``/``acquire``). They stay in the
vocabulary so a machine file must still make an explicit decision for them.

Offline ``experimental/lrp_edits`` and template-file edits do not command
hardware at write time; they are gated at the point LAS X executes them
(``load_experiment`` / job selection / ``acquire``), not at file write.
The ``lasx_native_autosave`` exporter only toggles where LAS X writes files
during an already-gated ``acquire``.

State model
-----------
:func:`connect_handshake` performs the connect-time limits handshake — the
single ``limits.json`` resolves to the newest ProgramData snapshot. If
ProgramData is empty, the repo defaults are copied there first. The flat file
must have the exact documented keys, finite ordered stage ranges, valid
objective slots, and ``[]`` for every unrestricted setter. Its stage envelope
must sit within the hardcoded physical backstop
(``motion.limits.STAGE_BACKSTOP_UM``). On success it applies the stage envelope
and installs the validated ``FunctionLimits`` in a module-level registry keyed
by client identity.

If loading is deliberately skipped for a connection (``load=False``) or the
machine file fails to validate, the session is NOT left fail-closed: the
bundled DEFAULT limits are installed instead (marked ``is_fallback`` and loudly
warned), so the session stays usable and bounded while the operator fixes the
file. The defaults sit within the physical backstop, and the backstop bounds
every move regardless. Only if even the shipped defaults are unusable does the
session go fail-closed, and every gated wrapper then refuses with the recorded
reason (which names the notebook that creates the files:
``limits/notebooks/set_stage_limits.ipynb``). A client that never handshook at
all (no ``connect_handshake`` ran) still refuses fail-closed.

Single-writer invariant: like command dispatch (``dispatch.py``) and the
stage-envelope module global (``motion/limits.py``), this registry assumes
ONE instrument per process. The registry is keyed by ``id(client)`` and holds
a strong reference to the client (CAM clients are process-lifetime), so an id
can never be recycled onto a different client. A second ``connect_handshake``
for the same client rebinds its state; the module-global stage envelope is
rebound by whichever handshake ran last.

Deviating from ``shared/limits/spec.py``'s "hang it off the driver handle"
guidance is deliberate (plan amendment PR-04): command wrappers receive the
``client``, not a handle, and the enforcement must live below anything a
caller can skip.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from shared import limits as _shared_limits

from ..config import machine as _machine
from ..motion import limits as _limits
from ..motion import stage_config as _stage_config

log = logging.getLogger(__name__)

NOTEBOOK_POINTER = "limits/notebooks/set_stage_limits.ipynb"

# Internal command-category vocabulary used by shared.limits after the flat
# Leica document has been validated and translated in memory. This never leaks
# into limits.json.
FUNCTION_LIMIT_KEYS = (
    "set_origin",
    "set_xyz",
    "set_state",
    "run_procedure",
    "acquire",
    "move_galvo_to_pixel",
    "save_experiment",
    "load_experiment",
)

# Every mutating command wrapper -> its limits.json functions key. The completeness
# suite (tests/unit/test_limits_adversarial.py) enumerates the wrappers that
# dispatch through the fire path and fails if any is missing here — the
# commands-layer successor of the adapter's old _MUTATING_OPS guard.
MUTATING_COMMANDS = {
    # job-level setters (the job is the unit of configuration -> set_state)
    "set_zoom": "set_state",
    "set_scan_speed": "set_state",
    "set_scan_resonant": "set_state",
    "set_scan_mode": "set_state",
    "set_sequential_mode": "set_state",
    "set_scan_field_rotation": "set_state",
    "set_image_format": "set_state",
    "set_objective": "set_state",
    "set_z_stack_definition": "set_state",
    "set_z_stack_step_size": "set_state",
    "set_z_stack_size": "set_state",
    "set_frame_accumulation": "set_state",
    "set_frame_average": "set_state",
    "set_line_accumulation": "set_state",
    "set_line_average": "set_state",
    "set_pinhole_airy": "set_state",
    "set_detector_gain": "set_state",
    "set_laser_intensity": "set_state",
    "set_laser_shutter": "set_state",
    "set_filter_wheel_slot": "set_state",
    "set_filter_wheel_spectrum": "set_state",
    "select_job": "set_state",
    # stage / galvo motion
    "move_xy": "set_xyz",
    "move_z": "set_xyz",
    "move_galvo_to_pixel": "move_galvo_to_pixel",
    # acquisition
    "acquire": "acquire",
    # experiment file round-trips (scanfields/files.py)
    "save_experiment": "save_experiment",
    "load_experiment": "load_experiment",
}


@dataclass
class GateState:
    """One session's validated limits (or the reason there are none).

    ``limits`` is the loaded ``shared.limits.FunctionLimits`` and ``stage_cfg``
    the validated stage config when the handshake succeeded; on failure both
    are None and ``error`` records exactly what is wrong (fail closed: every
    gated wrapper refuses with this message).
    """

    limits: Any | None = None
    stage_cfg: dict | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


# id(client) -> (client, GateState). The client reference is deliberately
# strong: it pins the id so a garbage-collected client's id can never be
# recycled onto a new, never-handshaken client that would then inherit stale
# limits. CAM clients are process-lifetime, so this is not a leak in practice.
_GATE_STATE: dict[int, tuple[Any, GateState]] = {}


def _install(client: Any, state: GateState) -> None:
    _GATE_STATE[id(client)] = (client, state)


def uninstall(client: Any) -> None:
    """Drop a client's gate state (its commands then refuse fail-closed)."""
    _GATE_STATE.pop(id(client), None)


def state_for(client: Any) -> GateState | None:
    """The installed gate state for *client*, or None when never handshaken."""
    entry = _GATE_STATE.get(id(client))
    return entry[1] if entry is not None else None


def describe(client: Any) -> dict | None:
    """Provenance of the limits governing *client* (None = refusing, see error).

    The shape is ``FunctionLimits.describe()``: schema_version, source, path,
    is_fallback. Reported by the adapter under observed state as evidence.
    """
    state = state_for(client)
    if state is None or state.limits is None:
        return None
    return state.limits.describe()


def check_refusal(client: Any, command: str, values: Mapping[str, Any]) -> str | None:
    """Gate one mutating command; returns the refusal message, or None to fire.

    Fail-closed on every failure mode: no handshake ever ran for this client,
    the handshake failed (missing/invalid machine-local limits), or *values*
    violate the file's constraints. The caller (a command wrapper) must not
    fire the native call when this returns a message; wrappers turn it into
    their fail-closed result-dict idiom, the adapter/controller raise.
    """
    key = MUTATING_COMMANDS[command]  # KeyError = unmapped wrapper = programming error
    state = state_for(client)
    if state is None:
        return (
            f"{command} refused: no limits are installed for this session — run the "
            f"connect limits handshake first (navigator_expert.connect_limits_handshake, "
            f"done automatically by the zmart adapter's connect). The machine-local "
            f"limits files live in the newest snapshot under "
            f"{_machine.MACHINE.snapshot_root()}; create them with {NOTEBOOK_POINTER}."
        )
    if state.limits is None:
        return f"{command} refused: {state.error}"
    try:
        state.limits.check(key, values)
    except (_shared_limits.LimitsError, _shared_limits.LimitViolation) as exc:
        return f"{command} refused: {exc}"
    return None


def build_function_limits_payload(stage_um: Mapping[str, Any], *, source: str = "machine") -> dict:
    """Compatibility wrapper returning the flat operator-facing document."""
    _stage_config._validate_source(source)
    return _stage_config.build_limits_payload(dict(stage_um))


def _runtime_function_limits(
    stage_cfg: Mapping[str, Any], *, path: Any, source: str, is_fallback: bool
):
    """Translate a validated flat file into the existing immutable checker."""
    constraints = {
        f"stage.{axis}": {"min": bounds[0], "max": bounds[1]}
        for axis, bounds in stage_cfg["stage_um"].items()
    }
    constraints["objective.slot"] = {"allowed": stage_cfg["objective_slot_allowed"]}
    functions: dict[str, Any] = {key: None for key in FUNCTION_LIMIT_KEYS}
    functions["set_xyz"] = {
        "x_um": "@stage.x",
        "y_um": "@stage.y",
        "z_galvo_um": "@stage.z_galvo",
        "z_wide_um": "@stage.z_wide",
    }
    functions["set_state"] = {"objective_slot": "@objective.slot"}
    payload = {
        "schema_version": _shared_limits.SCHEMA_VERSION,
        "source": source,
        "constraints": constraints,
        "functions": functions,
    }
    return _shared_limits.parse(
        payload,
        functions=FUNCTION_LIMIT_KEYS,
        path=path,
        is_fallback=is_fallback,
    )


def _build_gate_from_file(
    client: Any,
    limits_file: Any,
    *,
    source: str,
    is_fallback: bool,
) -> GateState:
    """Validate one limits.json, apply its envelope, and install the gate.

    Shared by the normal machine-file path and the bundled-defaults fallback.
    Raises on any validation problem so the caller can decide how to fall back.
    """
    # stage_config validates the complete flat file in one read.
    stage_cfg = _stage_config.load(limits_path=limits_file)
    # The envelope must sit within the hardcoded physical backstop.
    _limits.check_envelope_within_backstop(stage_cfg["stage_um"])
    function_limits = _runtime_function_limits(
        stage_cfg,
        path=limits_file,
        source=source,
        is_fallback=is_fallback,
    )
    _limits.apply_stage_limits_from_config(stage_cfg)
    state = GateState(limits=function_limits, stage_cfg=stage_cfg, error=None)
    _install(client, state)
    return state


def _install_default_limits(client: Any, machine: Any, reason: str) -> GateState:
    """Govern the session with the driver's bundled DEFAULT limits (loud).

    Used when limits loading is deliberately skipped for a connection, or when
    the machine-local ``limits.json`` does not validate. The bundled default
    envelope sits within the physical backstop, so the session stays usable and
    bounded rather than fail-closed — but it is emphatically NOT the operator's
    measured envelope, so this warns clearly and marks the limits as a fallback.
    """
    default_file = machine.bundled_default_path(_machine.LIMITS_FILENAME)
    state = _build_gate_from_file(
        client,
        default_file,
        source="defaults",
        is_fallback=True,
    )
    log.warning(
        "limits fallback: %s — the session is governed by the bundled DEFAULT "
        "limits (%s), NOT this machine's measured envelope. The defaults span "
        "the full physical travel, so they may be WIDER than the envelope this "
        "machine's own limits.json intended: do not rely on your published "
        "limits until the file validates again. The hardcoded physical backstop "
        "still bounds every move. Publish measured limits with %s.",
        reason,
        state.limits.describe(),
        NOTEBOOK_POINTER,
    )
    return state


def connect_handshake(
    client: Any, *, machine: Any = None, stage_limits_path: Any = None, load: bool = True
):
    """The connect-time limits handshake: resolve, validate, install. Never raises.

    Steps:

    1. When ``load`` is False, the machine file is skipped and the session is
       governed by the bundled DEFAULT limits (see below). Otherwise the single
       ``limits.json`` resolves through ProgramData, seeding repo defaults there
       first when needed. It must contain exactly the flat keys shown by the
       limits notebook, finite ranges with min <= max, and a non-empty unique
       integer objective-slot allow-list. ``stage_limits_path`` overrides the resolution
       with an explicit operator-chosen file (still validated); it is only
       consulted when ``load`` is True — with ``load=False`` the explicit path
       is ignored and the defaults govern.
    2. The envelope must sit WITHIN the hardcoded physical backstop
       (``motion.limits.STAGE_BACKSTOP_UM``).
    3. The objective allow-list is translated into the immutable runtime gate;
       setter ``[]`` entries remain explicitly unrestricted. Unknown, missing,
       or legacy metadata/nesting is rejected rather than silently ignored.
    4. On success: apply the stage envelope (module-global, single instrument
       per process) and install the gate state for *client*.

    Defaults fallback (operator decision): if loading is skipped (``load``
    False) or the machine ``limits.json`` fails to validate, the session is
    NOT left fail-closed. Instead the bundled DEFAULT limits are installed
    (marked ``is_fallback`` and loudly warned). The bundled defaults sit within
    the physical backstop, and the backstop bounds every move regardless, so
    the session stays bounded and usable while the operator fixes the file.
    Note the chosen trade-off: an invalid file is rejected WHOLE, so a
    deliberately NARROW machine envelope is replaced by the (wider) defaults
    until the file validates again — the fallback warning says so. Only if
    even the shipped defaults fail to load does the session go fail-closed
    (every mutating command then refuses with the recorded error).
    """
    machine = machine if machine is not None else _machine.MACHINE

    if not load:
        return _install_default_limits(
            client, machine, "limits loading was skipped for this connection"
        )

    try:
        if stage_limits_path is not None:
            limits_file = stage_limits_path
            source = "machine"
        else:
            limits_file = machine.require_machine_local(
                _machine.LIMITS_FILENAME, "the physical stage envelope"
            )
            marker = limits_file.parent / _machine.LIMITS_MACHINE_MARKER
            source = "machine" if marker.exists() else "defaults"
        state = _build_gate_from_file(
            client,
            limits_file,
            source=source,
            is_fallback=False,
        )
    except Exception as exc:  # noqa: BLE001 -- config IO / schema; fall back to defaults, never crash connect
        try:
            return _install_default_limits(
                client, machine, f"the machine limits.json did not validate: {exc}"
            )
        except Exception as default_exc:  # noqa: BLE001 -- shipped defaults broken: last-resort fail-closed
            error = (
                f"limits handshake failed and the bundled defaults are unusable "
                f"({default_exc}); machine file error: {exc} — every mutating command "
                f"refuses until the limits files validate (see {NOTEBOOK_POINTER})."
            )
            log.error("%s", error)
            state = GateState(limits=None, stage_cfg=None, error=error)
            _install(client, state)
            # A previous handshake's module-global stage envelope (if any) is
            # deliberately left in place: it is unreachable for moves, because
            # every mutating wrapper checks this fail-closed gate state first
            # and refuses before the envelope is ever consulted.
            return state

    log.info(
        "limits handshake ok: %s governs this session",
        state.limits.describe(),
    )
    return state
