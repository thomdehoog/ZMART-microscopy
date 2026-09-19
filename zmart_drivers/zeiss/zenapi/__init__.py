"""
zenapi -- ZEISS ZEN API microscope driver.
==========================================
Drives a ZEISS microscope through ZEN's API (gRPC, reached through the ZEN
API Gateway). A vendor sibling of the Leica, mesoSPIM and Nikon drivers: the
public surface is **synchronous** (a blocking facade over the async gRPC
client, see ``connection.client.ZenClient``), so notebooks stay 1-3 lines per
step, and importing the package registers the instrument with
``zmart_controller`` (see ``zen_zmart_adapter``).

Typical session::

    import zenapi as drv
    client = drv.connect("config.ini")
    drv.apply_stage_limits_from_config(drv.load_stage_config("stage_limits.json"))
    drv.move_xy(client, 1000, 2000)          # micrometers
    drv.move_z(client, 50)                    # micrometers
    drv.set_objective(client, name="Plan-Apochromat 20x/0.8")
    exp = drv.load_experiment(client, "ZMART_Snap")
    acq = drv.acquire(client, exp, mode="snap", output_name="tile_01")
    saved = drv.save(client, acq, output_root, naming)
    drv.close(client)

No ZEN at hand? ``python -m zenapi.simulator`` starts a fake ZEN API gateway
that speaks the real protocol; point ``config.ini`` at it.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

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

# --- commands ---
from .commands.commands import (
    Experiment,
    find_autofocus,
    find_surface,
    load_experiment,
    move_xy,
    move_z,
    recall_focus,
    run_experiment,
    run_snap,
    set_objective,
    start_experiment,
    start_live,
    stop,
    store_focus,
)

# --- stage limits (the rulebook; enforced only in commands/) ---
from .commands.routines import correct_backlash

# --- profiles (tuning surface) ---
from .config.profiles import (
    FOCUS_MOVE,
    FOCUS_PROCEDURE,
    OBJECTIVE,
    READERS,
    RUN_EXPERIMENT,
    SNAP,
    STAGE_MOVE,
    ZEN_API,
)

# --- connection ---
from .connection.client import ZenClient
from .connection.session import close, connect
from .limits.checks import (
    apply_stage_limits_from_config,
    get_stage_limits,
    set_stage_limits,
)
from .limits.stage_config import load as load_stage_config

# --- state readers ---
from .readers import (
    get_available_experiments,
    get_image_output_path,
    get_objective,
    get_objectives,
    get_status,
    get_xy,
    get_z,
    monitor,
    ping,
)

# --- the ZMART controller adapter (registers the instrument on import) ---
from .zen_zmart_adapter import CONNECTION, register  # noqa: E402

__all__ = [
    # connection
    "connect",
    "close",
    "ZenClient",
    # readers
    "get_xy",
    "get_z",
    "get_objective",
    "get_objectives",
    "get_available_experiments",
    "get_image_output_path",
    "get_status",
    "monitor",
    "ping",
    # commands
    "move_xy",
    "move_z",
    "set_objective",
    "load_experiment",
    "run_snap",
    "run_experiment",
    "start_experiment",
    "start_live",
    "stop",
    "find_autofocus",
    "find_surface",
    "store_focus",
    "recall_focus",
    "Experiment",
    # controller adapter
    "CONNECTION",
    "register",
    # stage limits + backlash
    "set_stage_limits",
    "get_stage_limits",
    "apply_stage_limits_from_config",
    "correct_backlash",
    "load_stage_config",
    # acquisition
    "acquire",
    "save",
    "AcquisitionResult",
    "SavedAcquisition",
    "PlaneIndex",
    "PositionIndex",
    "AcquisitionMetadata",
    "ChannelMetadata",
    # profiles
    "ZEN_API",
    "READERS",
    "STAGE_MOVE",
    "FOCUS_MOVE",
    "OBJECTIVE",
    "SNAP",
    "RUN_EXPERIMENT",
    "FOCUS_PROCEDURE",
]
