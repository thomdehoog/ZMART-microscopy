"""
The limits rulebook.
====================
Every "is this allowed?" answer in the driver comes from this module:
stage positions (the envelope and the physical backstop), objective
slots, and the 21 configurable setter values. Enforcement — the moment
of refusing — lives in the commands layer (``commands/gate.py`` and the
command wrappers), which asks this rulebook and obeys. Nothing above the
commands layer checks limits itself.

Stage moves are guarded by two independent layers, both checked in
Phase A of the command wrappers before the backbone fires:

1. **Session envelope** — the machine-local limits file, applied via
   ``set_stage_limits()`` / ``apply_stage_limits_from_config()`` (the
   connect-time limits handshake does this from the machine snapshot).
   Moves refuse until it is configured (fail closed).
2. **Hardcoded physical backstop** (:data:`STAGE_BACKSTOP_UM`) — checked
   AFTER the envelope, independently of any file, so even a hand-widened
   limits file can never command a move outside the physical envelope.

The mutable module-level envelope is intentional: limits are set once at
session start and shared across all command calls. This assumes ONE
instrument per process (the same single-writer convention as command
dispatch, see ``commands/dispatch.py``); a second connect in the same
process rebinds the envelope for everyone.

Dependency direction:
    - Imports: stdlib only (no driver imports).
    - Imported by: ``commands`` (for Phase A limit checks),
      ``commands.gate`` (backstop containment at the connect handshake),
      ``limits.config`` (envelope validation), ``__init__`` (re-export).
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

# =============================================================================
# Hardcoded physical backstop
# =============================================================================

# !! PARTIALLY VERIFIED ON RIG !! -------------------------------------------
# Absolute coordinate backstop for the motoric stage and both z drives
# (micrometers, [min, max] per axis). The bundled X/Y defaults deliberately
# start at 1000 um as a conservative safety margin; that margin is not the
# physical coordinate floor, so operator-measured limits may extend below
# it, down to coordinate zero. The z-wide maximum of 8000 um is the
# MEASURED travel of this stage (operator-confirmed at the rig,
# 2026-07-19). The X/Y upper bounds and the z-galvo range remain the
# historical ZMB STELLARIS 5 (serial y42h93) envelope until someone
# verifies different travel on the rig.
# NEVER widen these without measured rig data; narrowing is always safe.
# ---------------------------------------------------------------------------
STAGE_BACKSTOP_UM = {
    "x": (0.0, 130000.0),
    "y": (0.0, 100000.0),
    "z_galvo": (-250.0, 250.0),
    "z_wide": (0.0, 8000.0),
}


def check_envelope_within_backstop(stage_um):
    """Validate that a limits-file envelope sits WITHIN the physical backstop.

    ``stage_um`` is the ``{"x": [min, max], ...}`` mapping from a validated
    limits file. Raises ``RuntimeError`` when any axis reaches outside
    :data:`STAGE_BACKSTOP_UM` — a file wider than the physical travel is a
    hand-edited (or wrong-machine) file and must not be trusted. Called by
    the connect-time limits handshake; the per-move backstop check in
    ``check_xy`` / ``check_z`` stays independent of it.
    """
    for axis, (backstop_lo, backstop_hi) in STAGE_BACKSTOP_UM.items():
        lo, hi = float(stage_um[axis][0]), float(stage_um[axis][1])
        if lo < backstop_lo or hi > backstop_hi:
            raise RuntimeError(
                f"stage limits for axis {axis!r} = [{lo}, {hi}] reach outside the "
                f"physical backstop [{backstop_lo}, {backstop_hi}] "
                f"(limits/checks.py STAGE_BACKSTOP_UM); refusing the envelope — "
                f"a file wider than the machine's physical travel cannot be trusted"
            )


# =============================================================================
# Stage limits
# =============================================================================

_stage_limits = {
    "x_min": None,
    "x_max": None,
    "y_min": None,
    "y_max": None,
    "z_galvo_min": None,
    "z_galvo_max": None,
    "z_wide_min": None,
    "z_wide_max": None,
}


def set_stage_limits(
    *, x_min, x_max, y_min, y_max, z_galvo_min, z_galvo_max, z_wide_min, z_wide_max
):
    """Configure hard safety limits for stage movement (micrometers).

    An explicit operator action; the hardcoded :data:`STAGE_BACKSTOP_UM`
    still bounds every move independently of what is set here.
    """
    _stage_limits.update(
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
        z_galvo_min=z_galvo_min,
        z_galvo_max=z_galvo_max,
        z_wide_min=z_wide_min,
        z_wide_max=z_wide_max,
    )


def get_stage_limits():
    """Return current stage limits as a dict (copy)."""
    return dict(_stage_limits)


def apply_stage_limits_from_config(stage_cfg: dict) -> None:
    """Configure stage limits from the loaded limits configuration.

    The dict shape is the one produced by
    :func:`navigator_expert.limits.config.load`; pass it through
    once at session start so the cookbook and calibration share one
    source of truth.
    """
    lim = stage_cfg["stage_um"]
    set_stage_limits(
        x_min=lim["x"][0],
        x_max=lim["x"][1],
        y_min=lim["y"][0],
        y_max=lim["y"][1],
        z_galvo_min=lim["z_galvo"][0],
        z_galvo_max=lim["z_galvo"][1],
        z_wide_min=lim["z_wide"][0],
        z_wide_max=lim["z_wide"][1],
    )


def _require_finite(value, label):
    """A move target must be a finite int/float; NaN/inf/None/str all refuse.

    NaN compares False against every bound, so without this check a NaN
    target would pass straight through the range checks below. Numeric
    STRINGS are refused too (not coerced): ``float("50000")`` would satisfy
    the range check here while the raw string travels on into the native
    command model — the checked value must be the commanded value.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"{label}={value!r} is not a number; refusing the move")
    number = float(value)
    if not math.isfinite(number):
        raise RuntimeError(f"{label}={value!r} is not finite; refusing the move")
    return number


def check_xy(x, y):
    """Validate XY position against the envelope, then the physical backstop.

    Raises RuntimeError on any violation (unconfigured envelope, non-finite
    target, outside the session envelope, or outside the hardcoded backstop).
    """
    if _stage_limits["x_min"] is None:
        raise RuntimeError("Stage limits not configured. Call set_stage_limits() first.")
    x = _require_finite(x, "X")
    y = _require_finite(y, "Y")
    if x < _stage_limits["x_min"] or x > _stage_limits["x_max"]:
        raise RuntimeError(
            f"X={x} outside limits [{_stage_limits['x_min']}, {_stage_limits['x_max']}]"
        )
    if y < _stage_limits["y_min"] or y > _stage_limits["y_max"]:
        raise RuntimeError(
            f"Y={y} outside limits [{_stage_limits['y_min']}, {_stage_limits['y_max']}]"
        )
    # Backstop AFTER the envelope: even a hand-widened envelope cannot
    # authorize a move outside the physical travel.
    for axis, value in (("x", x), ("y", y)):
        lo, hi = STAGE_BACKSTOP_UM[axis]
        if value < lo or value > hi:
            raise RuntimeError(
                f"{axis.upper()}={value} outside the physical backstop [{lo}, {hi}] "
                f"(limits/checks.py STAGE_BACKSTOP_UM) — refused regardless of the "
                f"configured envelope"
            )


def check_z(z, z_mode):
    """Validate Z position against the envelope, then the physical backstop.

    Raises:
        RuntimeError: If limits are not configured, z is non-finite, or z is
            out of range (envelope or backstop).
        ValueError: If z_mode is not recognized.
    """
    if _stage_limits["z_galvo_min"] is None:
        raise RuntimeError("Stage limits not configured. Call set_stage_limits() first.")
    if z_mode == "galvo":
        axis = "z_galvo"
    elif z_mode == "zwide":
        axis = "z_wide"
    else:
        raise ValueError(f"Unknown z_mode '{z_mode}'. Use: 'galvo' or 'zwide'")
    z = _require_finite(z, "Z")
    lo, hi = _stage_limits[f"{axis}_min"], _stage_limits[f"{axis}_max"]
    if z < lo or z > hi:
        label = "galvo" if axis == "z_galvo" else "zwide"
        raise RuntimeError(f"Z={z} outside {label} limits [{lo}, {hi}]")
    backstop_lo, backstop_hi = STAGE_BACKSTOP_UM[axis]
    if z < backstop_lo or z > backstop_hi:
        raise RuntimeError(
            f"Z={z} ({z_mode}) outside the physical backstop [{backstop_lo}, {backstop_hi}] "
            f"(limits/checks.py STAGE_BACKSTOP_UM) — refused regardless of the "
            f"configured envelope"
        )


# =============================================================================
# The compiled limits document (objectives + setter allow-lists)
# =============================================================================

# The 21 configurable setters. Each key appears in limits.json with either
# ``[]`` (unrestricted) or one typed constraint, and the command wrapper with
# the same name enforces it immediately before its native CAM call.
SETTER_LIMIT_KEYS = (
    "set_zoom",
    "set_scan_speed",
    "set_scan_resonant",
    "set_scan_mode",
    "set_sequential_mode",
    "set_scan_field_rotation",
    "set_image_format",
    "set_z_stack_definition",
    "set_z_stack_step_size",
    "set_z_stack_size",
    "set_frame_accumulation",
    "set_frame_average",
    "set_line_accumulation",
    "set_line_average",
    "set_pinhole_airy",
    "set_detector_gain",
    "set_laser_intensity",
    "set_laser_shutter",
    "set_filter_wheel_slot",
    "set_filter_wheel_spectrum",
)


class LimitsError(ValueError):
    """The limits file (or an override) is malformed or incomplete."""


class LimitViolation(RuntimeError):
    """A checked value is outside its configured limit."""


@dataclass(frozen=True, slots=True)
class LimitsStatus:
    """Detached public provenance for the installed limits."""

    source: str
    path: str | None
    is_fallback: bool

    def describe(self) -> dict:
        return {
            "source": self.source,
            "path": self.path,
            "is_fallback": self.is_fallback,
        }


@dataclass(frozen=True, slots=True, init=False)
class LeicaLimits:
    """Immutable runtime checker compiled from the flat Leica limits document."""

    _policy: Mapping[str, tuple[str, tuple[Any, ...]] | None]
    source: str
    path: Any
    is_fallback: bool

    def __init__(self, payload: Mapping[str, Any], *, source: str, path: Any, is_fallback: bool):
        compiled = {}
        for name, entry in payload.items():
            if entry == []:
                compiled[name] = None
                continue
            kind, values = next(iter(entry.items()))
            compiled[name] = (kind, tuple(values))
        object.__setattr__(self, "_policy", MappingProxyType(compiled))
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "is_fallback", is_fallback)

    def _origin(self) -> str:
        return f"limits: {self.path}, source={self.source}"

    def _check_one(self, name: str, spec: Any, value: Any) -> None:
        if spec is None:
            return
        kind, configured = spec
        if kind == "range":
            low, high = configured
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise LimitViolation(
                    f"{name}={value!r} is not numeric (range [{low}, {high}]; {self._origin()})"
                )
            number = float(value)
            if not math.isfinite(number) or number < low or number > high:
                raise LimitViolation(
                    f"{name}={value!r} outside range [{low}, {high}] ({self._origin()})"
                )
            return
        allowed = configured
        if not any(type(value) is type(candidate) and value == candidate for candidate in allowed):
            raise LimitViolation(
                f"{name}={value!r} not allowed; expected one of {list(allowed)!r} "
                f"({self._origin()})"
            )

    def check(self, function: str, values: Mapping[str, Any]) -> None:
        if function == "set_xyz":
            for param in ("x_um", "y_um", "z_galvo_um", "z_wide_um"):
                if param in values:
                    self._check_one(param, self._policy[param], values[param])
            return
        if function == "set_objective":
            if "objective_slot" in values:
                self._check_one(
                    "objective_slot", self._policy["objective_slot"], values["objective_slot"]
                )
            return
        if function not in SETTER_LIMIT_KEYS:
            return
        spec = self._policy[function]
        if spec is None:
            return
        candidates = values.get("values")
        if candidates is None and "value" in values:
            candidates = [values["value"]]
        if not candidates:
            raise LimitsError(
                f"{function} has a configured limit but the wrapper supplied no value "
                f"({self._origin()})"
            )
        for value in candidates:
            self._check_one(function, spec, value)

    def status(self) -> LimitsStatus:
        return LimitsStatus(
            source=self.source,
            path=str(self.path) if self.path is not None else None,
            is_fallback=self.is_fallback,
        )

    def describe(self) -> dict:
        return self.status().describe()


