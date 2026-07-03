"""
mesospim -- mesoSPIM light-sheet microscope driver (ZMART).
===========================================================
A vendor sibling to the Leica ``navigator_expert`` and ZEISS ``zenapi`` drivers,
targeting **mesoSPIM-control** (the GPL PyQt5 acquisition app) from an external
MIT client. mesoSPIM-control has no external control API, so this driver talks to
its **Remote Scripting** server (a tiny generic bridge -- see ``pull_request/`` --
that runs a Python script in the live Core and returns the console) over a
localhost TCP socket. The driver injects small scripts (``connection/scripts.py``)
and parses a structured result back, keeping ZMART MIT behind the process boundary
while all the command vocabulary stays client-side. See ``README.md`` for the
architecture and licensing rationale, and ``pull_request/PROTOCOL.md`` for the
wire framing.

The public surface is **synchronous**, so operator notebooks keep the thin
1-3-line invocation style used across the ZMART drivers::

    import mesospim as drv
    client = drv.connect({"host": "127.0.0.1", "port": 42000})
    drv.apply_stage_limits_from_config(drv.load_stage_config())
    drv.move_xy(client, 1000, 2000)          # micrometers
    drv.set_filter(client, "515/30")
    # low-level acquire needs a folder/filename (the controller path sets these):
    acq = drv.acquire(client, "prescan", options={"folder": str(run_dir), "filename": "A1.tiff"})
    saved = drv.save(acq, run_dir, position_label="A1")
    drv.close(client)

To drive it through the vendor-neutral controller instead, call
:func:`mesospim.register` and use ``zmart_controller``.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

# --- version ---
__version__ = "0.1.0"

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

# --- controller integration ---
from .mesospim_zmart_adapter import register

# --- motion: stage limits (movement wrappers come in via .commands above) ---
from .motion import (
    LimitError,
    apply_stage_limits_from_config,
    check_move,
    get_stage_limits,
    load_stage_config,
    set_stage_limits,
)

# --- protocol (for advanced callers / server authors) ---
from .protocol import Reply, frame, parse_result, wrap_script

# --- state readers ---
from .readers import (
    Reading,
    get_config,
    get_filters,
    get_hardware_info,
    get_lasers,
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
    "Reply",
    "frame",
    "wrap_script",
    "parse_result",
    # readers
    "Reading",
    "ping",
    "get_state",
    "get_positions",
    "get_position",
    "get_xyz",
    "get_config",
    "get_hardware_info",
    "get_lasers",
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
