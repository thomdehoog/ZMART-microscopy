r"""
Nikon NIS-Elements driver for ZMART.
====================================
Drives a Nikon microscope through NIS-Elements. A small bridge runs *inside*
NIS-Elements (its bundled Python, started by ``bridge/start_bridge.mac``) and
calls the NIS macro functions directly; this package talks to that bridge over
a local socket.

Quick use::

    import nis_elements_6_10 as nis
    client = nis.connect({"host": "127.0.0.1", "port": 54468})
    nis.get_position(client)          # {'x': ..., 'y': ..., 'z': ...} in um
    nis.move_xyz(client, 100, 0, 500) # absolute, checked against NIS limits
    nis.capture(client); nis.save_image(client, r"C:\data\snap.tif")

Importing this package also registers the instrument with ``zmart_controller``
(see ``nis_zmart_adapter``). See ``README.md`` for the setup steps.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from .commands.commands import (
    SAVE_FORMATS,
    LimitError,
    autofocus,
    capture,
    capture_z_stack,
    check_within_limits,
    close_document,
    freeze,
    live,
    move_piezo_z,
    move_xy,
    move_xyz,
    move_z,
    save_image,
    select_optical_configuration,
    set_exposure_ms,
    set_objective,
    set_pfs,
)
from .connection.client import NisClient, NisConnectionError
from .connection.session import close, connect
from .nis_zmart_adapter import CONNECTION, register
from .protocol import PROTOCOL_VERSION, ProtocolError
from .readers.readers import (
    get_bridge_info,
    get_calibration,
    get_devices,
    get_exposure_ms,
    get_limits,
    get_objectives,
    get_optical_configurations,
    get_pfs,
    get_position,
    get_z_drives,
)

__all__ = [
    "CONNECTION",
    "PROTOCOL_VERSION",
    "SAVE_FORMATS",
    "LimitError",
    "NisClient",
    "NisConnectionError",
    "ProtocolError",
    "autofocus",
    "capture",
    "capture_z_stack",
    "check_within_limits",
    "close",
    "close_document",
    "connect",
    "freeze",
    "get_bridge_info",
    "get_calibration",
    "get_devices",
    "get_exposure_ms",
    "get_limits",
    "get_objectives",
    "get_optical_configurations",
    "get_pfs",
    "get_position",
    "get_z_drives",
    "live",
    "move_piezo_z",
    "move_xy",
    "move_xyz",
    "move_z",
    "register",
    "save_image",
    "select_optical_configuration",
    "set_exposure_ms",
    "set_objective",
    "set_pfs",
]
