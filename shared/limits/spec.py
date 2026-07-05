"""Function-keyed safety limits: one JSON file per driver, checked per call.

Every mutating driver operation (a call that changes something about the
microscope) is validated against a limits file before it runs. The file is
keyed by FUNCTION, so completeness is checkable: at load time the file must
carry an entry for every mutating operation the driver declares — ``null``
is a legal entry ("reviewed, deliberately unlimited"), a MISSING entry is a
load error. A new setter added without a limits entry therefore fails at
connect, in the offline suite — never silently unlimited on hardware.

Physical truth is stated once: bounds live under ``constraints`` by name,
and function entries reference them (``"@stage.x"``), so two functions that
touch the same physical quantity cannot drift apart. The machine's own
envelope (e.g. a ProgramData limits snapshot) overrides the bundled numbers
through ``constraint_overrides`` at load — the file shape stays the
driver's, the numbers stay the machine's.

Schema (v1)::

    {
      "schema_version": 1,
      "source": "defaults",
      "constraints": {
        "stage.x": {"min": 1000, "max": 130000},
        "save.format": {"allowed": ["lof", "xlef"]}
      },
      "functions": {
        "set_xyz": {"x_um": "@stage.x", "y_um": "@stage.y"},
        "set_state": null
      }
    }

A function entry maps parameter name -> constraint (an ``@name`` reference
or an inline constraint object). A constraint bounds a numeric value with
``min`` / ``max`` (either may be omitted) or an enumerated value with
``allowed``. :meth:`FunctionLimits.check` validates only the parameters the
entry names and the call provides — partial calls (e.g. a move touching one
axis) check only what they touch.

The loaded :class:`FunctionLimits` is per-session state: keep it keyed to the
session it governs — off the driver handle, or (when enforcement lives below
the handle, e.g. a commands-layer gate) in a registry keyed by client
identity. Never share ONE object module-wide: two instruments in one process
must not share an envelope. This module holds no state and does no IO beyond
:func:`load` reading one file.

Import convention: ``from shared.limits import FunctionLimits, load, ...``
Requires the repository root on sys.path.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


class LimitsError(ValueError):
    """The limits file (or an override) is malformed or incomplete."""


class LimitViolation(RuntimeError):
    """A checked value is outside its configured limit."""


@dataclass(frozen=True)
class Constraint:
    """One named bound: a numeric range and/or an enumerated value set.

    ``name`` is the provenance label carried into violation messages —
    the ``constraints`` key for shared constraints, ``<function>.<param>``
    for inline ones.
    """

    name: str
    min: float | None = None
    max: float | None = None
    allowed: tuple | None = None

    def check(self, value: Any) -> str | None:
        """The violation ("outside [a, b]" / "not one of ..."), or None if fine."""
        if self.allowed is not None and value not in self.allowed:
            options = ", ".join(repr(v) for v in self.allowed)
            return f"not one of: {options}"
        if self.min is not None or self.max is not None:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return f"is not numeric (bounded [{self.min}, {self.max}])"
            if not math.isfinite(number):
                # NaN compares False against every bound, so without this
                # check a NaN target would sail through a bounded range.
                return f"is not finite (bounded [{self.min}, {self.max}])"
            if self.min is not None and number < self.min:
                return f"outside [{self.min}, {self.max}]"
            if self.max is not None and number > self.max:
                return f"outside [{self.min}, {self.max}]"
        return None


def _parse_constraint(name: str, raw: Any, *, where: str) -> Constraint:
    if not isinstance(raw, dict) or not raw:
        raise LimitsError(f"{where}: constraint {name!r} must be a non-empty object, got {raw!r}")
    unknown = sorted(set(raw) - {"min", "max", "allowed"})
    if unknown:
        raise LimitsError(f"{where}: constraint {name!r} has unknown keys {unknown}")
    low, high, allowed = raw.get("min"), raw.get("max"), raw.get("allowed")
    if allowed is not None:
        if not isinstance(allowed, list) or not allowed:
            raise LimitsError(f"{where}: constraint {name!r} 'allowed' must be a non-empty list")
        allowed = tuple(allowed)
    if low is not None:
        low = float(low)
        if not math.isfinite(low):
            raise LimitsError(f"{where}: constraint {name!r} min is not finite: {low!r}")
    if high is not None:
        high = float(high)
        if not math.isfinite(high):
            raise LimitsError(f"{where}: constraint {name!r} max is not finite: {high!r}")
    if low is not None and high is not None and low > high:
        raise LimitsError(f"{where}: constraint {name!r} has min > max: [{low}, {high}]")
    if low is None and high is None and allowed is None:
        raise LimitsError(f"{where}: constraint {name!r} bounds nothing (no min/max/allowed)")
    return Constraint(name=name, min=low, max=high, allowed=allowed)


class FunctionLimits:
    """The loaded, validated limits for one driver session.

    Built by :func:`load` / :func:`parse`; immutable in use. ``check`` is the
    single runtime entry point; ``describe`` is the provenance record a driver
    reports under its observed state.
    """

    def __init__(
        self,
        *,
        functions: dict[str, dict[str, Constraint] | None],
        source: str,
        path: Path | None,
        is_fallback: bool,
    ) -> None:
        self._functions = functions
        self.source = source
        self.path = path
        self.is_fallback = is_fallback

    def _origin(self) -> str:
        return f"limits: {self.path or '<in-memory>'}, source={self.source}"

    def check(self, function: str, values: Mapping[str, Any]) -> None:
        """Validate one call's values; raise :class:`LimitViolation` if out of bounds.

        ``values`` maps parameter name -> the value about to be applied —
        pass the PHYSICAL targets (e.g. absolute stage micrometres), not the
        caller's frame-relative arguments, so the check bounds what the
        hardware will actually see. Parameters the entry does not name, and
        entry parameters the call does not provide, are not checked.

        Raises :class:`LimitsError` for a function the file never declared —
        that is a programming error (the completeness check at load time
        guarantees every declared mutating op has an entry).
        """
        try:
            entry = self._functions[function]
        except KeyError:
            raise LimitsError(
                f"function {function!r} has no limits entry ({self._origin()}); "
                f"declared: {sorted(self._functions)}"
            ) from None
        if entry is None:
            return
        for param, constraint in entry.items():
            if param not in values:
                continue
            value = values[param]
            violation = constraint.check(value)
            if violation is not None:
                raise LimitViolation(
                    f"{function}: {param}={value!r} {violation} "
                    f"(constraint {constraint.name!r}; {self._origin()})"
                )

    def describe(self) -> dict:
        """Provenance record for the observed state: which limits ran this session."""
        return {
            "schema_version": SCHEMA_VERSION,
            "source": self.source,
            "path": str(self.path) if self.path is not None else None,
            "is_fallback": self.is_fallback,
        }


def parse(
    payload: dict,
    *,
    functions: Iterable[str],
    constraint_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    path: Path | None = None,
    is_fallback: bool = False,
) -> FunctionLimits:
    """Validate a limits payload against the driver's declared mutating ops.

    ``functions`` is the driver's own list of mutating operation names; the
    payload's ``functions`` keys must match it EXACTLY — a missing entry and
    an undeclared (typo) entry are both :class:`LimitsError`. Every ``@name``
    reference must resolve, and every ``constraint_overrides`` key must name
    an existing constraint (an override may only re-bound known physical
    truth, never smuggle in unchecked names).
    """
    where = str(path) if path is not None else "<in-memory limits>"
    if not isinstance(payload, dict):
        raise LimitsError(f"{where}: limits payload must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise LimitsError(
            f"{where}: unsupported schema_version {payload.get('schema_version')!r}; "
            f"expected {SCHEMA_VERSION}"
        )
    source = payload.get("source")
    if not isinstance(source, str) or not source:
        raise LimitsError(f"{where}: source must be a non-empty string")

    raw_constraints = payload.get("constraints", {})
    if not isinstance(raw_constraints, dict):
        raise LimitsError(f"{where}: constraints must be an object")
    constraints = {
        name: _parse_constraint(name, raw, where=where) for name, raw in raw_constraints.items()
    }

    for name, override in (constraint_overrides or {}).items():
        if name not in constraints:
            raise LimitsError(
                f"{where}: constraint override {name!r} matches no constraint; "
                f"known: {sorted(constraints)}"
            )
        constraints[name] = _parse_constraint(name, dict(override), where=f"{where} (override)")

    raw_functions = payload.get("functions")
    if not isinstance(raw_functions, dict):
        raise LimitsError(f"{where}: missing 'functions' object")
    declared = set(functions)
    missing = sorted(declared - set(raw_functions))
    if missing:
        raise LimitsError(
            f"{where}: no limits entry for mutating functions {missing} — every "
            f"mutating op needs one (null means reviewed-and-unlimited)"
        )
    undeclared = sorted(set(raw_functions) - declared)
    if undeclared:
        raise LimitsError(
            f"{where}: entries for unknown functions {undeclared}; declared "
            f"mutating ops: {sorted(declared)}"
        )

    parsed: dict[str, dict[str, Constraint] | None] = {}
    for fn, entry in raw_functions.items():
        if entry is None:
            parsed[fn] = None
            continue
        if not isinstance(entry, dict):
            raise LimitsError(f"{where}: functions[{fn!r}] must be null or an object")
        bound: dict[str, Constraint] = {}
        for param, spec in entry.items():
            if isinstance(spec, str):
                if not spec.startswith("@"):
                    raise LimitsError(
                        f"{where}: functions[{fn!r}][{param!r}] string value must be an "
                        f"'@name' constraint reference, got {spec!r}"
                    )
                name = spec[1:]
                if name not in constraints:
                    raise LimitsError(
                        f"{where}: functions[{fn!r}][{param!r}] references unknown "
                        f"constraint {name!r}; known: {sorted(constraints)}"
                    )
                bound[param] = constraints[name]
            else:
                bound[param] = _parse_constraint(f"{fn}.{param}", spec, where=where)
        parsed[fn] = bound

    return FunctionLimits(functions=parsed, source=source, path=path, is_fallback=is_fallback)


def load(
    path: str | Path,
    *,
    functions: Iterable[str],
    constraint_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    is_fallback: bool = False,
) -> FunctionLimits:
    """Read and validate a limits JSON file (see :func:`parse` for the rules).

    ``is_fallback`` is provenance only: pass True when *path* is the
    driver-bundled default rather than a machine (ProgramData) copy, so the
    session's observed state reports which one governed.
    """
    selected = Path(path)
    with selected.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return parse(
        payload,
        functions=functions,
        constraint_overrides=constraint_overrides,
        path=selected,
        is_fallback=is_fallback,
    )
