"""
zenapi -- ZEISS ZEN API microscope driver.
==========================================
A vendor sibling to the Leica ``navigator_expert`` driver, targeting ZEISS ZEN
via the ZEN API (gRPC/grpclib through a ZEN API Gateway). The public surface is
**synchronous** -- a blocking facade over an async core (see
``connection.client.ZenClient``) -- so operator notebooks keep the thin 1-3 line
invocation style.

Typical session::

    import zenapi as drv
    client = drv.connect("config.ini")
    drv.apply_stage_limits_from_config(drv.load_stage_config("stage.json"))
    drv.move_xy(client, 1000, 2000)          # micrometers
    drv.move_z(client, 50)                    # micrometers
    drv.set_objective(client, name="Plan-Apochromat 20x/0.8")
    exp = drv.load_experiment(client, "TileScan_10x")
    acq = drv.acquire(client, exp)            # blocks until acquisition complete
    saved = drv.save(client, acq, output_root, naming)
    drv.close(client)

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

# --- connection ---
from .connection.client import ZenClient
from .connection.session import close, connect

# --- state readers ---
from .readers import (
    get_objective,
    get_objectives,
    get_status,
    get_xy,
    get_z,
    monitor,
    ping,
)

# --- commands ---
from .commands.commands import (
    Experiment,
    load_experiment,
    move_xy,
    move_z,
    run_experiment,
    run_snap,
    set_objective,
)

# --- motion ---
from .motion.limits import (
    apply_stage_limits_from_config,
    get_stage_limits,
    set_stage_limits,
)
from .motion.movement import correct_backlash, move_xy_with_backlash
from .motion.stage_config import load as load_stage_config

# --- acquisition ---
from .acquisition.capture import AcquisitionResult, acquire
from .acquisition.product import (
    AcquisitionMetadata,
    ChannelMetadata,
    PlaneIndex,
    PositionIndex,
    SavedAcquisition,
)
from .acquisition.save import save

# --- profiles (tuning surface) ---
from .config.profiles import (
    FOCUS_MOVE,
    OBJECTIVE,
    READERS,
    RUN_EXPERIMENT,
    SNAP,
    STAGE_MOVE,
    ZEN_API,
)

__all__ = [
    # connection
    "connect", "close", "ZenClient",
    # readers
    "get_xy", "get_z", "get_objective", "get_objectives", "get_status", "monitor", "ping",
    # commands
    "move_xy", "move_z", "set_objective", "load_experiment", "run_snap", "run_experiment",
    "Experiment",
    # motion
    "set_stage_limits", "get_stage_limits", "apply_stage_limits_from_config",
    "move_xy_with_backlash", "correct_backlash", "load_stage_config",
    # acquisition
    "acquire", "save", "AcquisitionResult", "SavedAcquisition",
    "PlaneIndex", "PositionIndex", "AcquisitionMetadata", "ChannelMetadata",
    # profiles
    "ZEN_API", "READERS", "STAGE_MOVE", "FOCUS_MOVE", "OBJECTIVE", "SNAP", "RUN_EXPERIMENT",
]
