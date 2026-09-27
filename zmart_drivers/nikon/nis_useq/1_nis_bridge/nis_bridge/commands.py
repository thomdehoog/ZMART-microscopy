"""The commands a client may ask for: the bridge's whole vocabulary.

Each public method of ``Operations`` is one command, in the same shape:

1. check the arguments, and refuse bad ones with ``ValueError``;
2. call NIS through ``self.api`` (see ``nis_api.py``), which raises
   ``RuntimeError`` when NIS refuses;
3. read the state back and return that, not what was asked for.

To add a command, add a method here and its name to ``OPS``. Nothing else
changes: the client sends any name in ``OPS``, and the dispatcher runs it.

Standard library only: this runs inside NIS-Elements.
"""

from __future__ import annotations

import os
from typing import Any

from .nis_api import PFS_STATUS
from .protocol import PROTOCOL_VERSION
from .settings import (
    AUTOFOCUS_MAX_SPEED,
    AUTOFOCUS_RANGE_UM,
    AUTOFOCUS_SPEED,
    PFS_ON_STATUSES,
    PFS_SETTLE_S,
)

BRIDGE_VERSION = "0.2.0"  # of the server inside NIS, reported by ping; not the package


def _number(args: dict, key: str) -> float:
    try:
        return float(args[key])
    except KeyError:
        raise ValueError(f"missing argument {key!r}") from None
    except (TypeError, ValueError):
        raise ValueError(f"argument {key!r} must be a number") from None


class Operations:
    """Each public method is one request. Arguments are checked here."""

    def __init__(self, api: Any, request_stop: Any) -> None:
        self.api = api
        self._request_stop = request_stop

    def ping(self, args: dict) -> dict:
        return {
            "bridge": BRIDGE_VERSION,
            "protocol": PROTOCOL_VERSION,
            "nis": self.api.version(),
        }

    def get_position(self, args: dict) -> dict:
        return self.api.get_position()

    def get_limits(self, args: dict) -> dict:
        return self.api.get_limits()

    def move(self, args: dict) -> dict:
        """Absolute move of any of x, y, z (um); axes left out stay where they are."""
        target = {
            axis: _number(args, axis) for axis in ("x", "y", "z") if args.get(axis) is not None
        }
        if not target:
            raise ValueError("move needs at least one of 'x', 'y', 'z'")
        if "x" in target or "y" in target:
            here = self.api.get_position()
            x, y = target.get("x", here["x"]), target.get("y", here["y"])
            if "z" in target:
                self.api.move_xyz(x, y, target["z"])
            else:
                self.api.move_xy(x, y)
        else:
            self.api.move_z(target["z"])
        return self.api.get_position()

    def get_optical_configurations(self, args: dict) -> list:
        return self.api.optical_configurations()

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

    def get_objectives(self, args: dict) -> dict:
        if not self.api.nosepiece_present():
            return {"current": None, "objectives": {}}
        names = {p: self.api.objective_name(p) for p in range(1, self.api.nosepiece_count() + 1)}
        return {
            "current": self.api.nosepiece_position(),
            "objectives": {p: name for p, name in names.items() if name},
        }

    def set_objective(self, args: dict) -> dict:
        position = args.get("position")
        if not isinstance(position, int) or isinstance(position, bool) or position < 1:
            raise ValueError("'position' must be a nosepiece position (1, 2, ...)")
        self.api.set_nosepiece_position(position)
        return {"current": self.api.nosepiece_position()}

    def get_pfs(self, args: dict) -> dict:
        if not self.api.pfs_present():
            return {"present": False, "on": False, "status": None, "meaning": "no PFS"}
        status = self.api.pfs_status()
        return {
            "present": True,
            "on": status in PFS_ON_STATUSES,
            "status": status,
            "meaning": PFS_STATUS.get(status, "unknown"),
        }

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
        return self.get_pfs({})

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
        return self.api.get_position()

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

    def shutdown(self, args: dict) -> dict:
        self._request_stop()
        return {"stopping": True}


OPS = (
    "ping",
    "get_position",
    "get_limits",
    "move",
    "get_optical_configurations",
    "select_optical_configuration",
    "set_exposure",
    "get_objectives",
    "set_objective",
    "get_pfs",
    "set_pfs",
    "autofocus",
    "snap",
    "shutdown",
)
