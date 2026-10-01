"""Part 5 of the driver anatomy: procedures.

A procedure is a recipe of several get and set commands, such as autofocus.
It never talks to the vendor software directly, so every step passes the
limits gate and the error rules without any extra effort.

:data:`PROCEDURES` lists them by name, with a plain description; that is what
``get_procedures`` shows and ``run_procedure`` runs.
"""

from .autofocus import autofocus
from .focus_score import brenner
from .stage import backlash_takeup, record_origin, zero_piezo

PROCEDURES = {
    "autofocus": {
        "description": (
            "Take a short z-stack around the current height, find the sharpest "
            "plane, and move there. Optional: range_um (default 20), step_um (default 2)."
        ),
        "run": autofocus,
    },
    "backlash_takeup": {
        "description": (
            "Approach the current position from the same side every time, so "
            "that positions repeat exactly."
        ),
        "run": backlash_takeup,
    },
    "zero_piezo": {
        "description": "Move the piezo to the middle of its range, keeping the focus height.",
        "run": zero_piezo,
    },
}

__all__ = ["PROCEDURES", "autofocus", "backlash_takeup", "brenner", "record_origin", "zero_piezo"]
