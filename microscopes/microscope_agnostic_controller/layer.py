"""Microscope Agnostic Controller: the single workflow-facing surface.

The one aim of this controller is to provide a simplified abstraction over
microscope drivers, with no unnecessary complication, that workflows can build
on. It earns its keep by being boring: it forwards intent and context to the
driver and returns whatever the driver hands back; the driver does the work.

Each concern is discover-then-apply: read the available options with a ``get_*``
call, then pass your choice back to the matching call. Omitted options fall back
to the driver's active default, filled by the driver.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from typing import Any

from .registry import IDENTITY, resolve


class Session:
    """A connected microscope, returned by :func:`set_instrument`.

    Send/receive only. The only public attribute is ``context`` -- how the driver
    was selected: ``vendor``, ``microscope``, ``api``. Call :meth:`disconnect`
    when finished if the driver needs teardown.
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

        Carries an ``"immutable"`` part (instrument/config fingerprint, not
        settable) and a ``"mutable"`` part (settings that can be reapplied). The
        controller does not interpret it; the driver owns the boundary.
        """
        return self._ops["get_state"](self._handle)

    def set_state(self, state: dict):
        """Reapply captured state; return whatever the driver reports.

        The driver applies only what it deems mutable.
        """
        return self._ops["set_state"](self._handle, state)

    def get_procedures(self) -> dict:
        """The named procedures the driver offers (e.g. hardware autofocus)."""
        return self._ops["get_procedures"](self._handle)

    def set_procedure(self, procedure: dict):
        """Run a procedure; return whatever the driver reports.

        Its meaning is encoded in the dict and run by the driver.
        """
        return self._ops["set_procedure"](self._handle, procedure)

    # --- movement -----------------------------------------------------------

    def get_xyz(self, with_actuators: dict | None = None) -> dict:
        """Read the current position per axis, in the canonical (motoric) frame.

        Coordinates are micrometers. ``with_actuators`` optionally selects which
        actuator to read per axis (e.g. ``{"z": "piezo"}``); axes left unspecified
        use the reference one.
        """
        return self._ops["get_xyz"](self._handle, with_actuators=with_actuators)

    def set_xyz(self, x: float, y: float, z: float, with_actuators: dict | None = None):
        """Move to an absolute target in the canonical (motoric) coordinate system.

        Returns whatever the driver reports (e.g. a move record / confirmation).
        Coordinates are micrometers. ``with_actuators`` selects the actuator
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
        return self._ops["acquisition_options"](self._handle)

    def acquire(
        self,
        acquisition_type: str,
        position_label: str,
        options: dict | None = None,
    ) -> dict:
        """Capture one dataset and save it, returning the driver's record.

        ``acquisition_type`` is the kind of scan (e.g. ``"prescan"`` /
        ``"targetscan"``); ``position_label`` names the position in the output
        filename. ``options`` carries the acquisition and saving settings from
        :meth:`get_acquisition_options`; pass it through untouched -- the driver
        fills any omitted option from its active default.
        """
        return self._ops["acquire"](
            self._handle,
            acquisition_type=acquisition_type,
            position_label=position_label,
            options=options,
        )

    # --- context and lifecycle ----------------------------------------------

    def get_context(self) -> dict:
        """Additional read-only context the driver provides (e.g. initial positions).

        Opaque to the controller -- whatever the driver chooses to expose.
        """
        return self._ops["get_context"](self._handle)

    def disconnect(self) -> None:
        """Close the session if the driver provides a teardown hook."""
        disconnect = self._ops.get("disconnect")
        if disconnect is not None:
            disconnect(self._handle)


def set_instrument(
    instrument: dict[str, Any],
    reference_actuators: dict[str, str],
    reference_objective: str,
) -> Session:
    """Select an instrument, open the session, and fix the coordinate system.

    ``instrument`` is one of the dicts from :func:`get_instruments`.
    ``reference_actuators`` (a per-axis dict, e.g. ``{"x": "motoric", "z":
    "z-wide"}``) and ``reference_objective`` are chosen from that dict's
    ``actuators`` / ``objectives``; they fix the reference frame in which
    ``set_xyz`` coordinates are given. This is the connector: it resolves the
    driver, forwards the instrument's ``connection`` dict to the driver's
    ``connect``, and sets the frame (the driver validates the choices). Option
    menus are not cached here -- ``get_*`` calls forward to the driver live.

    Returns a connected :class:`Session`. Raises ``ValueError`` if the instrument
    is unknown or a reference objective/actuator is not supported.
    """
    ops, connection = resolve(instrument)
    handle = ops["connect"](connection)
    ops["set_coordinate_system"](
        handle, objective=reference_objective, actuators=reference_actuators
    )
    context = {key: connection[key] for key in IDENTITY}
    return Session(ops, handle, context)
