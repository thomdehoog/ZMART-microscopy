"""Function-keyed limits gate for the commands layer.

Maintainer decision (MAINTAINER_DECISIONS.md §7): limits are enforced as low
as possible — at the command wrapper that populates the native CAM function's
model — so nothing built on top (adapter, controller, workflows, notebooks)
can interfere with or bypass them. This module is that chokepoint's state and
policy; the wrappers in ``commands.py`` (and the two experiment-file mutators
in ``scanfields/files.py``) call :func:`check_refusal` before anything fires.

Wrapper -> key mapping
----------------------
The single ``limits.json`` (its ``functions`` block) keeps the op-level key
vocabulary shared with the zmart adapter (plus the PR-07 additions); every
mutating command wrapper declares exactly one key in :data:`MUTATING_COMMANDS`:

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
``set_procedure`` (its effects run through gated wrappers: backlash ->
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
single machine-local ``limits.json`` must exist in the newest machine snapshot
(the bundled ``limits/defaults/limits.json`` is a TEMPLATE and is refused), be
schema-valid with finite numbers only (both its ``constraints``/``functions``
and its stage envelope), and sit within the hardcoded physical backstop
(``motion.limits.STAGE_BACKSTOP_UM``). On
success it applies the stage envelope and installs the validated
``FunctionLimits`` in a module-level registry keyed by client identity; on
failure the session stays usable read-only, and every gated wrapper refuses
with the recorded reason (which names the path tried and the notebook that
creates the files: ``limits/notebooks/set_stage_limits.ipynb``).

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

# The limits.json ``functions`` key vocabulary this driver declares. The shared
# parser requires the file's ``functions`` block to match this set EXACTLY
# (missing and unknown keys are both load errors), so a machine file must
# make an explicit decision — a constraint object or an explicit ``null``
# ("reviewed, deliberately unlimited") — for every key. An ABSENT key fails
# closed at load time; there is no way to ship one silently unlimited.
FUNCTION_LIMIT_KEYS = (
    "set_origin",
    "set_xyz",
    "set_state",
    "set_procedure",
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
    """The ``constraints`` + ``functions`` of a machine-local limits.json.

    Used by ``stage_config.adopt_limits`` (the set_stage_limits notebook) to
    build the merged limits.json — it adds the ``backlash`` block on top of
    this. The ``stage.*`` constraints are the measured machine envelope and
    every non-stage key starts as explicit ``null`` (reviewed, deliberately
    unlimited — the same policy as the bundled template). Operators tighten
    entries by editing the machine-local file; the connect handshake
    re-validates it on every session.
    """
    constraints = {
        f"stage.{axis}": {"min": float(bounds[0]), "max": float(bounds[1])}
        for axis, bounds in stage_um.items()
    }
    functions: dict[str, Any] = {key: None for key in FUNCTION_LIMIT_KEYS}
    functions["set_xyz"] = {
        "x_um": "@stage.x",
        "y_um": "@stage.y",
        "z_galvo_um": "@stage.z_galvo",
        "z_wide_um": "@stage.z_wide",
    }
    return {
        "schema_version": _shared_limits.SCHEMA_VERSION,
        "source": source,
        "constraints": constraints,
        "functions": functions,
    }


def connect_handshake(client: Any, *, machine: Any = None, stage_limits_path: Any = None):
    """The connect-time limits handshake: resolve, validate, install. Never raises.

    Steps (any failure -> a fail-closed :class:`GateState` whose ``error``
    names the file tried and points at limits/notebooks/set_stage_limits.ipynb):

    1. The single ``limits.json`` must be machine-local (newest snapshot; the
       bundled template is refused), schema-valid with finite numbers, min <=
       max, exactly this machine's axes (envelope derived from
       ``constraints.stage.*``). ``stage_limits_path`` overrides the resolution
       with an explicit operator-chosen file (still validated).
    2. The envelope must sit WITHIN the hardcoded physical backstop
       (``motion.limits.STAGE_BACKSTOP_UM``).
    3. The SAME file's ``constraints`` + ``functions`` must parse under
       ``shared.limits`` (finite numbers, exact key vocabulary =
       :data:`FUNCTION_LIMIT_KEYS`), with the validated envelope overlaid onto
       its ``stage.*`` constraints so the numbers governing moves are exactly
       what stage_config validated. Its ``backlash`` section is ignored by the
       shared parser.
    4. On success: apply the stage envelope (module-global, single instrument
       per process) and install the gate state for *client*.

    On failure the session still works read-only; every mutating command
    refuses with the recorded error until the machine-local file exists and a
    new handshake runs.
    """
    machine = machine if machine is not None else _machine.MACHINE
    try:
        # -- 1. the single limits.json, strict machine-local. Its
        #       constraints.stage.* is the physical envelope; stage_config
        #       derives stage_um from it (and reads the backlash block).
        if stage_limits_path is not None:
            limits_file = stage_limits_path
        else:
            limits_file = machine.require_machine_local(
                _machine.LIMITS_FILENAME, "the physical stage envelope"
            )
        stage_cfg = _stage_config.load(limits_path=limits_file)

        # -- 2. backstop containment
        _limits.check_envelope_within_backstop(stage_cfg["stage_um"])

        # -- 3. function-keyed limits (constraints + functions of the SAME
        #       file), strict machine-local. The validated envelope is overlaid
        #       onto the stage.* constraints so the numbers governing moves are
        #       exactly the ones stage_config validated. The file's backlash
        #       section is ignored by the shared parser.
        overrides = {
            f"stage.{axis}": {"min": bounds[0], "max": bounds[1]}
            for axis, bounds in stage_cfg["stage_um"].items()
        }
        function_limits = _shared_limits.load(
            limits_file,
            functions=FUNCTION_LIMIT_KEYS,
            constraint_overrides=overrides,
            is_fallback=False,
        )
    except Exception as exc:  # noqa: BLE001 -- config IO / schema; fail closed, never crash connect
        error = (
            f"limits handshake failed: {exc} — every mutating command refuses until the "
            f"machine-local limits files validate (create/update them with {NOTEBOOK_POINTER})."
        )
        log.warning("%s", error)
        state = GateState(limits=None, stage_cfg=None, error=error)
        _install(client, state)
        return state

    # -- 4. install (module-global envelope + client-keyed gate state)
    _limits.apply_stage_limits_from_config(stage_cfg)
    state = GateState(limits=function_limits, stage_cfg=stage_cfg, error=None)
    _install(client, state)
    log.info(
        "limits handshake ok: %s governs this session",
        function_limits.describe(),
    )
    return state
