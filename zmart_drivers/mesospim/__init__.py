"""
mesospim -- mesoSPIM light-sheet microscope driver (ZMART).
===========================================================
A vendor sibling to the Leica ``navigator_expert`` and ZEISS ``zenapi`` drivers,
targeting **mesoSPIM-control** (the GPL PyQt5 acquisition app) from an external
MIT client. mesoSPIM-control gained a **Remote Control** server in its pull
request #106: a fixed list of named, validated calls over a password-gated
TCP socket. This driver is one client of that server. Nothing ZMART-specific
runs inside mesoSPIM, which keeps ZMART MIT behind the process boundary. See
``README.md`` for the architecture and licensing rationale, and ``protocol.py``
for the wire contract.

The public surface is **synchronous**, so operator notebooks keep the thin
1-3-line invocation style used across the ZMART drivers::

    import mesospim as drv
    client = drv.connect({"host": "127.0.0.1", "port": 42000, "token": "..."})
    drv.apply_stage_limits_from_config(drv.load_stage_config())
    drv.move_xy(client, 1000, 2000)          # micrometers
    drv.set_filter(client, "515/30")
    # low-level acquire needs a folder/filename (the controller path sets these):
    acq = drv.acquire(client, "prescan", options={"folder": str(run_dir), "filename": "A1.tiff"})
    saved = drv.save(acq, run_dir, position_label="A1")
    drv.close(client)

To drive it through the vendor-neutral controller instead, import the package
(which registers the instrument) and use ``zmart_controller``.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

# --- version ---
__version__ = "0.2.0"

# --- connection ---
# --- acquisition ---
from .acquisition import (
    AcquisitionMetadata,
    AcquisitionResult,
    ChannelMetadata,
    SavedAcquisition,
    acquire,
    build_acquisition,
    canonical_stem,
    run_acquisition_list,
    save,
    snap,
)

# --- commands ---
from .commands import (
    confirm_and_fire,
    move_absolute,
    move_focus,
    move_relative,
    move_rotation,
    move_to_preset,
    move_xy,
    move_z,
    set_etl,
    set_filter,
    set_intensity,
    set_laser,
    set_shutter,
    set_state,
    set_zoom,
    stop,
    zero_axes,
)

# --- config (profiles) ---
from .config import (
    ACQUISITION,
    CONNECTION,
    HARDWARE,
)
from .connection.client import MesospimClient, MesospimError
from .connection.session import close, connect

# --- stage limits (movement wrappers come in via .commands above) ---
from .limits import (
    LimitError,
    apply_stage_limits_from_config,
    check_move,
    get_stage_limits,
    load_stage_config,
    set_stage_limits,
)

# --- controller integration ---
from .mesospim_zmart_adapter import register

# --- protocol (for advanced callers / server authors) ---
from .protocol import PROTOCOL_VERSION, Reply, encode_call, frame, parse_reply

# --- state readers ---
from .readers import (
    Reading,
    get_config,
    get_filters,
    get_hardware_info,
    get_info,
    get_lasers,
    get_limits,
    get_position,
    get_positions,
    get_progress,
    get_state,
    get_xyz,
    get_zooms,
    ping,
)

__all__ = [
    "__version__",
    # connection
    "MesospimClient",
    "MesospimError",
    "connect",
    "close",
    # protocol
    "PROTOCOL_VERSION",
    "Reply",
    "frame",
    "encode_call",
    "parse_reply",
    # readers
    "Reading",
    "ping",
    "get_state",
    "get_positions",
    "get_position",
    "get_xyz",
    "get_config",
    "get_hardware_info",
    "get_info",
    "get_lasers",
    "get_limits",
    "get_filters",
    "get_zooms",
    "get_progress",
    # commands
    "confirm_and_fire",
    "move_absolute",
    "move_relative",
    "move_xy",
    "move_z",
    "move_focus",
    "move_rotation",
    "move_to_preset",
    "stop",
    "zero_axes",
    "set_state",
    "set_filter",
    "set_zoom",
    "set_laser",
    "set_intensity",
    "set_shutter",
    "set_etl",
    # config / limits
    "ACQUISITION",
    "CONNECTION",
    "HARDWARE",
    "LimitError",
    "apply_stage_limits_from_config",
    "check_move",
    "get_stage_limits",
    "set_stage_limits",
    "load_stage_config",
    # acquisition
    "acquire",
    "snap",
    "run_acquisition_list",
    "build_acquisition",
    "save",
    "canonical_stem",
    "AcquisitionResult",
    "AcquisitionMetadata",
    "ChannelMetadata",
    "SavedAcquisition",
    # controller
    "register",
]
