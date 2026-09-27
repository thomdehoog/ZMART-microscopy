"""The questions a client may ask: readers observe NIS-Elements and change nothing.

Each public method of ``Readers`` is one read-only request. They are safe to
call at any time, and the commands use them to read back what they did.

Standard library only: this runs inside NIS-Elements.
"""

from __future__ import annotations

from typing import Any

from .nis_dll import PFS_STATUS
from .protocol import PROTOCOL_VERSION
from .settings import PFS_ON_STATUSES

BRIDGE_VERSION = "0.2.0"  # of the server inside NIS, reported by ping; not the package


class Readers:
    def __init__(self, api: Any) -> None:
        self.api = api

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

    def get_optical_configurations(self, args: dict) -> list:
        return self.api.optical_configurations()

    def get_objectives(self, args: dict) -> dict:
        if not self.api.nosepiece_present():
            return {"current": None, "objectives": {}}
        names = {p: self.api.objective_name(p) for p in range(1, self.api.nosepiece_count() + 1)}
        return {
            "current": self.api.nosepiece_position(),
            "objectives": {p: name for p, name in names.items() if name},
        }

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


READS = (
    "ping",
    "get_position",
    "get_limits",
    "get_optical_configurations",
    "get_objectives",
    "get_pfs",
)
