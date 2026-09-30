"""Per-connection driver configuration: the orientation and calibration loaded
when the driver connects to the microscope.

The limits gate keeps its own client-keyed registry
(:mod:`navigator_expert.commands.gate`). This module is its sibling for the
other two machine-local configs the driver loads at connect time: how the
camera is turned relative to the stage (``orientation``) and the per-objective
translation offsets that keep coordinates consistent when you switch lenses
(``translations``).

Both are read once, at connect, so a single connection carries one consistent
picture of the microscope for its whole life — rather than every saved image
re-reading files that might have changed underneath it. Re-measuring a config
takes effect on the next connection.

Single instrument per process, exactly like the gate: the registry is keyed by
``id(client)`` and holds a strong reference to the client, so a client's id can
never be recycled onto a different, never-loaded client.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..orientation import Orientation


@dataclass
class SessionConfig:
    """The orientation and calibration a connection loaded at connect time.

    ``orientation`` is the measured camera turn applied to saved images (the
    identity "no turn" when orientation was not loaded). ``translations`` maps
    each objective slot to its ``(x, y, z)`` offset in micrometres, or is
    ``None`` when calibration was not loaded — in which case the frame math
    refuses cross-objective moves rather than computing uncompensated values.
    ``calibration_name`` records which named calibration set was selected.
    ``orientation_info`` and ``calibration_info`` are immutable provenance
    captured at connect; the adapter uses them to issue its driver-owned
    readiness verdict without making workflows interpret configuration files.
    """

    orientation: Orientation
    translations: dict | None = None
    calibration_name: str | None = None
    orientation_info: dict | None = None
    calibration_info: dict | None = None


# id(client) -> (client, SessionConfig). The client reference is deliberately
# strong so a garbage-collected client's id can never be recycled onto a new,
# never-loaded client that would then inherit stale config. CAM clients live
# for the process, so this is not a leak in practice.
_STATE: dict[int, tuple[Any, SessionConfig]] = {}


def install(client: Any, config: SessionConfig) -> None:
    """Record the config loaded for *client* (rebinds on a re-connect)."""
    _STATE[id(client)] = (client, config)


def get(client: Any) -> SessionConfig | None:
    """The config loaded for *client*, or None when the driver never loaded it."""
    entry = _STATE.get(id(client))
    return entry[1] if entry is not None else None


def uninstall(client: Any) -> None:
    """Drop a client's loaded config (e.g. on disconnect)."""
    _STATE.pop(id(client), None)
