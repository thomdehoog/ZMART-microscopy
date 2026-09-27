"""The commands a client may ask for: everything that changes NIS-Elements.

Each public method of ``Commands`` is one command, in the same shape:

1. check the arguments, and refuse bad ones with ``ValueError``;
2. call NIS through ``self.api`` (see ``nis_dll.py``), which raises
   ``RuntimeError`` when NIS refuses;
3. read the state back through ``self.read`` (see ``readers.py``) and return
   that, not what was asked for.

To add a command, add a method here and its name to ``COMMANDS``. Nothing
else changes: the client sends the name, and the dispatcher runs it. A request
that only reads belongs in ``readers.py`` instead.

Standard library only: this runs inside NIS-Elements.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB), University of Zurich
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
Date: 2026-09-27
License: MIT
"""

from __future__ import annotations

import os
from typing import Any

from .readers import Readers
from .settings import (
    AUTOFOCUS_MAX_SPEED,
    AUTOFOCUS_RANGE_UM,
    AUTOFOCUS_SPEED,
    PFS_SETTLE_S,
)


def _number(args: dict, key: str) -> float:
    try:
        return float(args[key])
    except KeyError:
        raise ValueError(f"missing argument {key!r}") from None
    except (TypeError, ValueError):
        raise ValueError(f"argument {key!r} must be a number") from None


class Commands:
    def __init__(self, api: Any, read: Readers) -> None:
        self.api = api
        self.read = read

    def move(self, args: dict) -> dict:
        """Absolute move of any of x, y, z (um); axes left out stay where they are."""
        target = {
            axis: _number(args, axis) for axis in ("x", "y", "z") if args.get(axis) is not None
        }
        if not target:
            raise ValueError("move needs at least one of 'x', 'y', 'z'")
        if "x" in target or "y" in target:
            here = self.read.get_position({})
            x, y = target.get("x", here["x"]), target.get("y", here["y"])
            if "z" in target:
                self.api.move_xyz(x, y, target["z"])
            else:
                self.api.move_xy(x, y)
        else:
            self.api.move_z(target["z"])
        return self.read.get_position({})

    def select_optical_configuration(self, args: dict) -> dict:
        name = args.get("name")
        if name not in self.api.optical_configurations():
            raise ValueError(f"unknown optical configuration {name!r}")
        self.api.select_optical_configuration(name)
        return {"selected": name}

    def set_exposure(self, args: dict) -> dict:
        exposure_ms = _number(args, "exposure_ms")
        if exposure_ms <= 0:
            raise ValueError("'exposure_ms' must be positive")
        return {"exposure_ms": self.api.set_exposure_ms(exposure_ms)}

    def set_objective(self, args: dict) -> dict:
        position = args.get("position")
        if not isinstance(position, int) or isinstance(position, bool) or position < 1:
            raise ValueError("'position' must be a nosepiece position (1, 2, ...)")
        self.api.set_nosepiece_position(position)
        return {"current": self.api.nosepiece_position()}

    def set_pfs(self, args: dict) -> dict:
        """Switch the Perfect Focus System on (waiting up to ``timeout_s`` to lock) or off."""
        on = args.get("on")
        if not isinstance(on, bool):
            raise ValueError("'on' must be true or false")
        if not self.api.pfs_present():
            raise RuntimeError("no Perfect Focus System (PFS) is connected")
        self.api.set_pfs(on)
        if on:
            self.api.wait_for_pfs(float(args.get("timeout_s", PFS_SETTLE_S)))
        return self.read.get_pfs({})

    def autofocus(self, args: dict) -> dict:
        range_um = float(args.get("range_um", AUTOFOCUS_RANGE_UM))
        speed = int(args.get("speed", AUTOFOCUS_SPEED))
        if range_um <= 0 or not 0 <= speed <= AUTOFOCUS_MAX_SPEED:
            raise ValueError(
                f"'range_um' must be positive and 'speed' between 0 and {AUTOFOCUS_MAX_SPEED}"
            )
        rc = self.api.autofocus(range_um, speed)
        if rc != 1:
            reason = {0: "focus not found", -3: "image is all black or all white"}
            raise RuntimeError(f"StgFocusInRangeEx: {reason.get(rc, 'failed')} ({rc})")
        return self.read.get_position({})

    def snap(self, args: dict) -> dict:
        """Capture one image, save it as TIFF at ``path``, close its window in NIS.

        ``pixel_size_um`` is None when the objective has no calibration in NIS.
        """
        path = args.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError("'path' must be a file path")
        self.api.capture()
        try:
            pixel_size_um = self.api.pixel_size_um()  # read while the image is still open
            self.api.save_tiff(path)
        finally:
            self.api.close_document()  # never leave capture windows piling up in NIS
        if not os.path.exists(path):
            raise RuntimeError(f"ImageSaveAs returned but no file appeared at {path}")
        return {"path": path, "pixel_size_um": pixel_size_um if pixel_size_um > 0 else None}


COMMANDS = (
    "move",
    "select_optical_configuration",
    "set_exposure",
    "set_objective",
    "set_pfs",
    "autofocus",
    "snap",
)
