"""The Setup: one driver's configuration, held open while an operator works through it.

This is the setup-side counterpart of :class:`zmart_controller.Session`, and
like it, it is deliberately boring: it forwards to the driver's ops and hands
back what the driver said. What it adds is the two questions a page asks
before drawing anything -- what can this driver configure, and can it do the
optional things -- so that no step has to know a driver by name.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .registry import IDENTITY, OPTIONAL_OPS, SUBSYSTEMS, resolve


class Setup:
    """A driver opened for configuration. Obtain one with :func:`open_setup`."""

    def __init__(self, ops: dict[str, Any], handle: Any, context: dict[str, str],
                 connection: dict[str, Any] | None = None) -> None:
        self._ops = ops
        self._handle = handle
        self._connection = dict(connection or {})
        self._closed = False
        #: How the driver was chosen: vendor, microscope, api.
        self.context = context

    @property
    def closed(self) -> bool:
        return self._closed

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("this setup is closed")

    # --- what the driver says about itself ------------------------------

    def describe(self) -> dict:
        """What this driver can configure, its connection checks, and what
        each subsystem needs on screen. Every subsystem in
        :data:`SUBSYSTEMS` is present in the answer; one the driver did not
        mention says ``supported: False``, so callers never have to check."""
        self._require_open()
        said = dict(self._ops["describe"](self._handle))
        declared = dict(said.get("subsystems") or {})
        said["subsystems"] = {
            name: {"supported": False, **dict(declared.get(name) or {})}
            if name not in declared
            else {"supported": bool(declared[name].get("supported", False)), **dict(declared[name])}
            for name in SUBSYSTEMS
        }
        said["can"] = {name: self.can(name) for name in OPTIONAL_OPS}
        return said

    def can(self, op: str) -> bool:
        """Whether the driver supplies an optional op (``objective``, ``markers``)."""
        return op in self._ops

    def supports(self, subsystem: str) -> bool:
        return bool(self.describe()["subsystems"].get(subsystem, {}).get("supported"))

    # --- the small vocabulary -------------------------------------------

    def where(self) -> dict:
        """Absolute stage position: ``{"x_um", "y_um", "z_um"}``."""
        self._require_open()
        return self._ops["where"](self._handle)

    def move(self, x_um: float, y_um: float, z_um: float) -> dict:
        """Move, and answer with where the stage was read back to be."""
        self._require_open()
        return self._ops["move"](self._handle, float(x_um), float(y_um), float(z_um))

    def acquire(self, *, into: str | Path, name: str, z_um: list[float] | None = None) -> dict:
        """One raw picture (or a stack, when ``z_um`` lists heights) written under ``into``."""
        self._require_open()
        return self._ops["acquire"](self._handle, into=str(into), name=str(name), z_um=z_um)

    def objective(self) -> dict:
        """Which lens is in: ``{"slot", "name"}``. Raises if the driver cannot say."""
        self._require_open()
        if "objective" not in self._ops:
            raise RuntimeError("this driver cannot report which objective is in")
        return self._ops["objective"](self._handle)

    def objectives(self) -> list:
        """Every lens the turret holds: ``[{"slot", "name"}, ...]``."""
        self._require_open()
        if "objectives" not in self._ops:
            raise RuntimeError("this driver cannot list its objectives")
        return list(self._ops["objectives"](self._handle))

    def markers(self) -> dict:
        """The corner markers the operator placed: ``{"points": [...]}``."""
        self._require_open()
        if "markers" not in self._ops:
            raise RuntimeError("this driver has no markers to read")
        return self._ops["markers"](self._handle)

    # --- the four documents ----------------------------------------------

    def read(self, subsystem: str, *, fresh: bool = False) -> dict:
        """The document as it stands -- or, with ``fresh``, the driver's own
        default for it, as a new setup starts from rather than editing what a
        previous one published."""
        self._require_open()
        _require_subsystem(subsystem)
        if fresh:
            return self._ops["read"](self._handle, subsystem, fresh=True)
        return self._ops["read"](self._handle, subsystem)

    def publish(self, subsystem: str, document: dict, *, evidence: list | None = None) -> dict:
        """Write ``document`` as a dated snapshot of ``subsystem``, keeping the
        ``evidence`` files (figures, the measurement's numbers) beside it."""
        self._require_open()
        _require_subsystem(subsystem)
        if not isinstance(document, dict):
            raise ValueError(f"a {subsystem} document is a dict, got {type(document).__name__}")
        kept = [str(path) for path in (evidence or [])]
        if kept:
            return self._ops["publish"](self._handle, subsystem, dict(document), evidence=kept)
        return self._ops["publish"](self._handle, subsystem, dict(document))

    # --- configurations: what the machine stands on --------------------------

    def _configuration_op(self, name: str):
        if name not in self._ops:
            raise RuntimeError("this driver keeps no configurations")
        return self._ops[name]

    def configurations(self) -> list[dict]:
        """Every configuration the machine has, newest first."""
        self._require_open()
        return list(self._configuration_op("configurations")(self._connection))

    def new_configuration(self) -> dict:
        """Start a configuration as a full copy of what stands now, and stand on it."""
        self._require_open()
        return dict(self._configuration_op("new_configuration")(self._handle))

    def use_configuration(self, configuration: str) -> dict:
        """Stand on one of the machine's configurations, by id."""
        self._require_open()
        return dict(self._configuration_op("use_configuration")(self._handle, str(configuration)))

    def configuration(self) -> dict | None:
        """The configuration this setup stands on, or None before one is chosen."""
        self._require_open()
        if "configuration" not in self._ops:
            return None
        said = self._ops["configuration"](self._handle)
        return None if said is None else dict(said)

    def close(self) -> None:
        """Idempotent: a second close is a no-op."""
        if self._closed:
            return
        self._closed = True
        self._ops["close"](self._handle)


def _require_subsystem(subsystem: str) -> None:
    if subsystem not in SUBSYSTEMS:
        raise ValueError(f"unknown subsystem {subsystem!r}; one of {SUBSYSTEMS}")


def open_setup(instrument: dict[str, Any]) -> Setup:
    """Open one of :func:`zmart_setup.get_instruments`'s entries for configuration."""
    ops, connection = resolve(instrument)
    handle = ops["open"](connection)
    context = {key: connection[key] for key in IDENTITY}
    return Setup(ops, handle, context, connection)
