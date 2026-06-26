"""Microscope-agnostic layer: the single workflow-facing surface.

The one aim of this layer is to provide a simplified abstraction over microscope
drivers, with no unnecessary complication, that workflows can build on. Nothing
more (see DESIGN.md).

It earns its keep by being boring. It forwards intent and context to the driver
and returns whatever the driver hands back; the driver does the work. Two things
serve that single aim:

  - It provides the driver with context. connect() establishes the session
    context - vendor, microscope, api, reference objective, stage frame - and
    every later call forwards it to the driver.

  - It keeps the surface easy. Set the context once, get good defaults and
    discoverable options, then issue short, domain-level calls.

Every method is send/receive: the layer never moves a stage, computes an
offset, or interprets a payload - it just provides the clean surface to build
on, and the driver does the work.

The methods come in two styles:

  - Standardized (get_xyz, set_xyz, acquire, save) take specific typed
    parameters and return structured results.

  - Flexible (get_state, set_state, get_procedure, set_procedure,
    get_initial_positions) pass opaque dictionaries straight through.

Typical use:

    from microscope_agnostic_layer import connect

    mic = connect(vendor="leica", microscope="stellaris5-01")
    print(mic.capabilities["objective"])   # discover what is available
    mic.set_xyz(10.0, 20.0, 5.0)           # absolute, in the motoric frame
    frame = mic.acquire(backlash_correction=True)
    mic.save(format="ome-zarr", name="well_A1")
    mic.disconnect()                       # optional teardown when finished

Method names follow the design's operations in snake_case (getXYZ -> get_xyz,
setState -> set_state, and so on).
"""

from __future__ import annotations

from typing import Any

from .registry import resolve


class Session:
    """A connected microscope, returned by :func:`connect`.

    The session is send/receive only. It holds two public attributes:

    ``capabilities``
        The menu discovered at connect, as ``{axis: {"options": [...],
        "active": ...}}`` -- the single source of truth for selectable options
        (objective, stages, save format, save procedure). ``active`` is the
        default the layer uses when a call omits the choice; ``options`` is the
        vocabulary callers read and pass back as arguments.
    ``context``
        What the layer feeds the driver on every call: ``vendor``,
        ``microscope``, ``api``, ``objective``, ``stage_type``.

    Call :meth:`disconnect` when finished if the driver needs teardown.
    """

    def __init__(
        self,
        ops: dict[str, Any],
        handle: Any,
        capabilities: dict[str, Any],
        context: dict[str, str],
    ) -> None:
        # operation name -> bound driver callable
        self._ops = ops

        # opaque driver connection/state
        self._handle = handle

        self.capabilities = capabilities
        self.context = context

    def _active(self, axis: str) -> str:
        """Return the ``active`` option for a selectable capability.

        Raises a clear error if the driver advertises no such capability, rather
        than letting a bare ``KeyError`` escape from a default lookup.
        """
        try:
            return self.capabilities[axis]["active"]
        except (KeyError, TypeError):
            raise ValueError(f"driver advertises no {axis!r} capability to default") from None

    # --- standardized: typed params, structured results ---------------------

    def get_xyz(self, stages: dict | None = None) -> dict:
        """Read the current stage position.

        Returns a per-axis mapping ``{axis: {"value", "stage", "unit"}}`` in the
        canonical (motoric) frame. ``stages`` optionally selects which actuator
        to read per axis (e.g. ``{"z": "piezo"}``); axes left unspecified use the
        active frame. The driver produces the reading.
        """
        return self._ops["get_xyz"](self._handle, stages=stages)

    def set_xyz(self, x: float, y: float, z: float, stages: dict | None = None) -> None:
        """Move to an absolute target in the canonical (motoric) frame.

        ``x``/``y``/``z`` are always given in the motoric coordinate system;
        ``stages`` selects the actuator that realizes the move per axis (``None``
        -> the active frame). The driver applies the objective offset and the
        actuator transform -- that calibration math is never the layer's job.
        """
        self._ops["set_xyz"](self._handle, x, y, z, stages=stages)

    def acquire(self, backlash_correction: bool = True) -> dict:
        """Acquire one dataset and return the driver's structured result.

        ``backlash_correction`` (default ``True``) is acquisition-time intent: it
        tells the driver to settle the stage via the correct approach *before*
        the capture, so the image is taken at the true position. It is an
        acquisition concern, not a move concern -- ``set_xyz`` has no backlash
        notion. Turn it off to trade trustworthiness for speed.
        """
        return self._ops["acquire"](self._handle, backlash_correction=backlash_correction)

    def save(
        self,
        format: str | None = None,
        procedure: str | None = None,
        name: str | None = None,
        position: Any = None,
    ) -> dict:
        """Persist the most recent acquisition.

        ``format`` (e.g. ``"ome-tiff"`` / ``"ome-zarr"``) and ``procedure`` (how
        it writes -- e.g. direct, tiled) are the two selectable axes; when
        omitted, each defaults to the option discovered as ``active`` at connect.
        ``name`` and ``position`` are optional context for the output filename
        and embedded metadata.
        """
        fmt = format or self._active("save_format")
        proc = procedure or self._active("save_procedure")
        return self._ops["save"](
            self._handle, format=fmt, procedure=proc, name=name, position=position
        )

    # --- flexible: opaque dicts, send/receive only --------------------------

    def get_state(self) -> dict:
        """Capture instrument state as an opaque dict.

        Carries an ``"immutable"`` part (instrument/config fingerprint, not
        settable) and a ``"mutable"`` part (settings that can be reactivated).
        The layer does not interpret it; the driver owns the boundary.
        Round-trip through :meth:`set_state` to reactivate a captured state.
        """
        return self._ops["get_state"](self._handle)

    def set_state(self, state: dict) -> None:
        """Reactivate captured state.

        Sends the dict to the driver, which applies only what it deems mutable
        and validates the immutable fingerprint. The layer never inspects the
        contents.
        """
        self._ops["set_state"](self._handle, state)

    def get_procedure(self) -> dict:
        """Receive the current procedure from the driver as an opaque dict."""
        return self._ops["get_procedure"](self._handle)

    def set_procedure(self, procedure: dict) -> None:
        """Send a procedure dict to the driver.

        Whatever the dict means -- run, define, stage -- is encoded in it and
        acted on by the driver. The layer only pipes it across.
        """
        self._ops["set_procedure"](self._handle, procedure)

    def get_initial_positions(self) -> dict:
        """Receive the positions captured at connect, for reactivation (dict)."""
        return self._ops["get_initial_positions"](self._handle)

    # --- lifecycle ----------------------------------------------------------

    def disconnect(self) -> None:
        """Close the session if the driver provides a teardown hook."""
        disconnect = self._ops.get("disconnect")
        if disconnect is not None:
            disconnect(self._handle)


def connect(
    vendor: str,
    microscope: str | None = None,
    api: str | None = None,
    client: str | None = None,
    password: str | None = None,
    objective: str | None = None,
    stage_type: str | None = None,
) -> Session:
    """Resolve a driver, open the session, discover capabilities, return it.

    This is the connector: it selects the driver, opens and authenticates the
    session, fixes the coordinate-frame context (reference objective + stage
    frame), and discovers the capability menu -- all in one call.

    Args:
        vendor: Picks the driver, e.g. ``"leica"``.
        microscope: Instrument id; falls back to the vendor default when omitted.
        api: Backend/transport; falls back to the vendor default when omitted.
        client: Client/session identity passed to the driver, if it needs one.
        password: Auth secret. Has no default -- pass it explicitly, or resolve
            it from a secret store upstream. Never baked into the registry.
        objective: Reference objective defining the coordinate frame; falls back
            to the vendor default when omitted.
        stage_type: Reference actuator frame; falls back to the vendor default.

    Returns:
        A connected :class:`Session`.

    Raises:
        ValueError: If the vendor is unknown or no driver matches
            ``(microscope, api)``.

    Example::

        mic = connect(vendor="mock")          # all defaults
        mic = connect(vendor="leica", microscope="stellaris5-01", api="pyapi")
    """
    ops, context = resolve(vendor, microscope, api, objective=objective, stage_type=stage_type)
    handle = ops["connect"](
        microscope=context["microscope"],
        api=context["api"],
        client=client,
        password=password,
        objective=context["objective"],
        stage_type=context["stage_type"],
    )
    capabilities = ops["capabilities"](handle)
    return Session(ops, handle, capabilities, context)
