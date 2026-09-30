"""Microscope Agnostic Controller: the single workflow-facing surface.

The one aim of this controller is to provide a simplified abstraction over
microscope drivers, with no unnecessary complication, that workflows can build
on. It earns its keep by being boring: it forwards intent and context to the
driver and returns whatever the driver hands back; the driver does the work.

Each concern is discover-then-apply: read the available options with a ``get_*``
call, then pass your choice back to the matching call. Omitted options fall back
to the driver's active default, filled by the driver.

Every call is synchronous: the controller calls the driver, the driver does
the work on the microscope, and only then does the call return with the
driver's answer. Nothing runs in the background, and there is no "live" mode
yet. (A future live view, where you change settings while watching and then
snap, would need a different kind of call; it is deliberately not part of
this contract.)

The controller keeps no configuration of its own. Where (0, 0, 0) is, the
travel limits and the calibration are the driver's configuration: set up
once in a separate step with the driver, saved to a file, and loaded by the
driver when it connects.

Failure is reported by raising: driver ops raise exceptions (``ValueError`` for
caller mistakes, ``RuntimeError`` for instrument failures or refusals) and never
encode failure in a returned dict; the controller catches nothing and propagates
driver exceptions to the caller unchanged.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from typing import Any

from .registry import IDENTITY, resolve


class Session:
    """A connected microscope, returned by :func:`set_instrument`.

    Each method calls the matching driver function and returns what it returns.
    The session keeps no state of its own and refuses nothing: every check,
    including whether the connection is still open, belongs to the driver. The
    only public attribute is ``context`` -- how the driver was selected:
    ``vendor``, ``microscope``, ``api``.
    """

    def __init__(
        self,
        ops: dict[str, Any],
        handle: Any,
        context: dict[str, str],
    ) -> None:
        # operation name -> bound driver callable
        self._ops = ops

        # opaque driver connection/state
        self._handle = handle

        self.context = context

    # --- state and procedures: opaque dicts the driver owns -----------------

    def get_state(self) -> dict:
        """Capture instrument state as an opaque dict.

        Carries a ``"changeable"`` part (the settings ``set_state``
        reapplies) and an ``"observed"`` part (a read-only report:
        instrument identity and current condition). The controller does not
        interpret it; the driver owns the boundary.
        """
        return self._ops["get_state"](self._handle)

    def set_state(self, state: dict) -> dict:
        """Reapply captured state; return whatever the driver reports.

        The driver acts on the ``"changeable"`` part only; ``"observed"`` is
        a report, never an instruction.
        """
        return self._ops["set_state"](self._handle, state)

    def get_procedures(self) -> dict:
        """The named procedures the driver offers (e.g. hardware autofocus)."""
        return self._ops["get_procedures"](self._handle)

    def run_procedure(self, procedure: dict) -> dict:
        """Run a procedure; return whatever the driver reports.

        Its meaning is encoded in the dict and run by the driver.
        """
        return self._ops["run_procedure"](self._handle, procedure)

    # --- movement -----------------------------------------------------------

    def get_actuators(self) -> dict:
        """The actuator options each axis offers, e.g. ``{"z": ["motoric", "piezo"]}``.

        Pass a choice back as ``with_actuators`` on :meth:`get_xyz` / :meth:`set_xyz`.
        """
        return self._ops["get_actuators"](self._handle)

    def get_xyz(self, with_actuators: dict | None = None) -> dict:
        """Read the current position per axis, in micrometers from the driver's origin.

        ``with_actuators`` optionally names an actuator per axis (e.g.
        ``{"z": "piezo"}``; names must come from :meth:`get_actuators`). The
        driver validates the choice and echoes it in the reading; whether the
        value differs per actuator is up to the driver.
        """
        return self._ops["get_xyz"](self._handle, with_actuators=with_actuators)

    def set_xyz(self, x: float, y: float, z: float, with_actuators: dict | None = None) -> dict:
        """Move to an absolute target, in micrometers from the driver's origin.

        Returns whatever the driver reports (e.g. a move record / confirmation).
        ``with_actuators`` selects the actuator
        that realizes the move per axis (``None`` -> the reference one). The driver
        applies the objective offset and the actuator transform -- that
        calibration is never the controller's job.
        """
        return self._ops["set_xyz"](self._handle, x, y, z, with_actuators=with_actuators)

    # --- acquire (captures and saves) ---------------------------------------

    def get_acquisition_options(self) -> dict:
        """The acquisition + saving options the driver offers (options + active).

        Forwarded live to the driver on every call -- the controller caches
        nothing. Includes both acquisition settings (e.g. ``backlash_correction``)
        and saving settings (e.g. ``format``, ``procedure``), since :meth:`acquire`
        captures and saves in one step.
        """
        return self._ops["get_acquisition_options"](self._handle)

    def acquire(
        self,
        acquisition_type: str,
        position_label: str,
        options: dict | None = None,
    ) -> dict:
        """Capture one dataset and save it, returning the driver's record.

        ``acquisition_type`` is the kind of scan (e.g. ``"prescan"`` /
        ``"targetscan"``); ``position_label`` labels the position in the
        driver's output records — how it appears (filename slot, lineage) is
        driver-defined. ``options`` carries the acquisition and saving settings from
        :meth:`get_acquisition_options`; pass it through untouched -- the driver
        fills any omitted option from its active default.
        """
        return self._ops["acquire"](
            self._handle,
            acquisition_type=acquisition_type,
            position_label=position_label,
            options=options,
        )

    # --- information and lifecycle ------------------------------------------

    def get_info(self) -> dict:
        """Read the connected setup information live.

        Every driver reports ``output_root``, the folder where images are
        saved. Any other key is an extra of that particular driver (for
        example, tile positions drawn in the vendor's own software), so a
        workflow meant to run on any microscope should not rely on it. The
        controller does not cache this snapshot. A driver may write working
        files and pause briefly while it gathers the information.
        """
        return self._ops["get_info"](self._handle)

    def disconnect(self) -> None:
        """Close the connection, if the driver provides a way to close it.

        The driver decides what a second call does; a well-behaved driver
        makes it harmless.
        """
        disconnect = self._ops.get("disconnect")
        if disconnect is not None:
            disconnect(self._handle)


def set_instrument(instrument: dict[str, Any]) -> Session:
    """Select an instrument and open the session.

    ``instrument`` is one of the connection dicts from :func:`get_instruments`.
    This is the connector: it resolves the driver and forwards the connection
    dict to the driver's ``connect`` untouched. The driver loads its own
    configuration as it connects, including the origin that positions are
    measured from, so there is nothing to declare here. Option menus are not
    cached here -- ``get_*`` calls forward live.

    Returns a connected :class:`Session`. Raises ``ValueError`` if the instrument
    identity matches no registered driver.
    """
    ops, connection = resolve(instrument)
    handle = ops["connect"](connection)
    context = {key: connection[key] for key in IDENTITY}
    return Session(ops, handle, context)
