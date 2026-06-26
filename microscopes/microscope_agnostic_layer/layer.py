"""Microscope-agnostic layer: the single workflow-facing surface.

The one aim of this layer is to provide a simplified abstraction over microscope
drivers, with no unnecessary complication, that workflows can build on. Nothing
more (see DESIGN.md).

It earns its keep by being boring. It forwards intent and context to the driver
and returns whatever the driver hands back; the driver does the work. Two things
serve that single aim:

  - It provides the driver with context. connect_to_microscope() establishes the
    session context (vendor, microscope, api) and the coordinate system (set from
    the discovered objective and stage via set_coordinate_system), and forwards it
    to the driver.

  - It keeps the surface easy. Each concern is discover-then-apply: read the
    available options with a get_* call, then pass your choices back to the
    matching apply call. Omitted options fall back to the driver's active default.

Every method is send/receive: the layer never moves a stage, computes an offset,
or interprets a payload - it just provides the clean surface to build on, and the
driver does the work.

Typical use:

    from microscope_agnostic_layer import available_microscopes, connect_to_microscope

    available_microscopes()                # what can I connect to?
    mic = connect_to_microscope(vendor="leica", microscope="stellaris5-01")
    mic.get_coordinate_system()            # which objectives / stages are available?
    mic.set_coordinate_system(objective="10x", stage_type="motoric")
    mic.set_xyz(10.0, 20.0, 5.0)           # absolute, in the motoric coordinate system
    frame = mic.acquire()                  # options from get_acquisitions_options()
    mic.export_data(options={"format": "ome-zarr", "name": "well_A1"})
    mic.disconnect()                       # optional teardown when finished
"""

from __future__ import annotations

from typing import Any

from .registry import resolve


class Session:
    """A connected microscope, returned by :func:`connect_to_microscope`.

    Send/receive only. Each concern is discover-then-apply: read the available
    options with a ``get_*`` call, then pass your choices back to the matching
    apply call. The discoverable menus are the coordinate system
    (:meth:`get_coordinate_system`), acquisition
    (:meth:`get_acquisitions_options`) and export
    (:meth:`get_export_data_options`).

    The only public attribute is ``context`` -- how the driver was selected:
    ``vendor``, ``microscope``, ``api``. Call :meth:`disconnect` when finished if
    the driver needs teardown.
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

        # the full options/active menu the driver reports, exposed through the
        # focused get_* methods rather than as a public attribute
        self._capabilities = capabilities

        self.context = context

    # --- coordinate system --------------------------------------------------

    def get_coordinate_system(self) -> dict:
        """The available objectives and stage types, each as ``options`` + ``active``.

        Read this before :meth:`set_coordinate_system` to see what you can choose.
        """
        return {
            "objective": self._capabilities["objective"],
            "stage_types": self._capabilities["stage_types"],
        }

    def set_coordinate_system(
        self, objective: str | None = None, stage_type: str | None = None
    ) -> None:
        """Fix the coordinate system from the discovered options.

        ``objective`` is the optical reference (the driver applies offsets between
        objectives) and ``stage_type`` the default actuator the canonical axes
        resolve to. Either may be omitted to keep the driver's current choice. The
        driver validates, and the discoverable options are refreshed afterwards.
        """
        self._ops["set_coordinate_system"](self._handle, objective=objective, stage_type=stage_type)
        self._capabilities = self._ops["capabilities"](self._handle)

    # --- movement -----------------------------------------------------------

    def get_initial_positions(self) -> list:
        """The positions captured at connect, for the workflow to visit (list of dicts)."""
        return self._ops["get_initial_positions"](self._handle)

    def get_xyz(self, stage_types: dict | None = None) -> dict:
        """Read the current stage position.

        Returns a per-axis mapping ``{axis: {"value", "stage", "unit"}}`` in the
        canonical (motoric) coordinate system. ``stage_types`` optionally selects
        which actuator to read per axis (e.g. ``{"z": "piezo"}``); axes left
        unspecified use the active one. The driver produces the reading.
        """
        return self._ops["get_xyz"](self._handle, stage_types=stage_types)

    def set_xyz(self, x: float, y: float, z: float, stage_types: dict | None = None) -> None:
        """Move to an absolute target in the canonical (motoric) coordinate system.

        ``x``/``y``/``z`` are always given in the motoric coordinate system;
        ``stage_types`` selects the actuator that realizes the move per axis
        (``None`` -> the active one). The driver applies the objective offset and
        the actuator transform -- that calibration math is never the layer's job.
        """
        self._ops["set_xyz"](self._handle, x, y, z, stage_types=stage_types)

    # --- acquire ------------------------------------------------------------

    def get_acquisitions_options(self) -> dict:
        """The acquisition options the driver offers, each as ``options`` + ``active``.

        For example ``{"backlash_correction": {"options": [True, False],
        "active": True}}``. Pass chosen values back through :meth:`acquire`.
        """
        return self._capabilities["acquisitions"]

    def acquire(self, options: dict | None = None) -> dict:
        """Acquire one dataset and return the driver's structured result.

        ``options`` selects acquisition settings discovered via
        :meth:`get_acquisitions_options`; pass it through untouched -- the driver
        fills any omitted option from its active default. For example
        ``backlash_correction`` settles the stage via the right approach *before*
        the capture, so the image is taken at the true position.
        """
        return self._ops["acquire"](self._handle, options=options)

    # --- export -------------------------------------------------------------

    def get_export_data_options(self) -> dict:
        """The export options the driver offers, each as ``options`` + ``active``.

        For example ``format`` and ``procedure``. ``name`` and ``position`` are
        free per-call context, not discovered here. Pass choices through
        :meth:`export_data`.
        """
        return self._capabilities["export_data"]

    def export_data(self, options: dict | None = None) -> dict:
        """Export the most recent acquisition.

        ``options`` may set the discovered ``format`` / ``procedure`` plus free
        ``name`` / ``position`` context for the output filename and embedded
        metadata. Pass it through untouched -- the driver fills any omitted
        ``format`` / ``procedure`` from its active default.
        """
        return self._ops["export_data"](self._handle, options=options)

    # --- state and procedures: opaque dicts, send/receive only --------------

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

    # --- lifecycle ----------------------------------------------------------

    def disconnect(self) -> None:
        """Close the session if the driver provides a teardown hook."""
        disconnect = self._ops.get("disconnect")
        if disconnect is not None:
            disconnect(self._handle)


def connect_to_microscope(
    vendor: str,
    microscope: str | None = None,
    api: str | None = None,
    client: str | None = None,
    password: str | None = None,
) -> Session:
    """Resolve a driver, open the session, discover its options, return it.

    This is the connector: it selects the driver, opens and authenticates the
    session, and discovers the option menus. It does *not* set the coordinate
    system -- the available objectives and stages are only known after connecting,
    so you read them from ``session.get_coordinate_system()`` and apply them with
    :meth:`Session.set_coordinate_system`. Use :func:`available_microscopes` first
    to see what you can connect to.

    Args:
        vendor: Picks the driver, e.g. ``"leica"``.
        microscope: Instrument id; falls back to the vendor default when omitted.
        api: Backend/transport; falls back to the vendor default when omitted.
        client: Client/session identity passed to the driver, if it needs one.
        password: Auth secret. Has no default -- pass it explicitly, or resolve
            it from a secret store upstream. Never baked into the registry.

    Returns:
        A connected :class:`Session`.

    Raises:
        ValueError: If the vendor is unknown or no driver matches
            ``(microscope, api)``.

    Example::

        mic = connect_to_microscope(vendor="mock")   # microscope/api from defaults
        mic = connect_to_microscope(vendor="leica", microscope="stellaris5-01", api="pyapi")
    """
    ops, context = resolve(vendor, microscope, api)
    handle = ops["connect"](
        microscope=context["microscope"],
        api=context["api"],
        client=client,
        password=password,
    )
    capabilities = ops["capabilities"](handle)
    return Session(ops, handle, capabilities, context)
