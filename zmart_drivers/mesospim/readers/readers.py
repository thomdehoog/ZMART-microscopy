"""
State readers.
==============
Read-only queries against the mesoSPIM command server. Every reader maps to one
protocol ``get_*`` request and parses the reply's ``data`` into a plain value or
dict; none of them mutate instrument state.

Values are source-tagged with a :class:`Reading` when ``diagnostics=True`` so the
confirmation layer can apply its freshness gate (a readback taken before a
command fired can never confirm it). Plain reads return the bare value.

mesoSPIM has a single evidence source -- the command server reading the
process-wide ``mesoSPIM_StateSingleton`` -- so ``source`` is always ``"server"``
today. The field is kept so a second source (e.g. a direct stage poll) can be
added without changing the confirmation contract.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from ..utils import AXES, _safe_float

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Reading:
    """A state read, tagged with its source and observation time.

    ``observed_at`` is a :func:`time.perf_counter` stamp, not wall-clock epoch:
    the freshness gate only ever *orders* it against the fire time (same clock),
    so the clock must be monotonic **and** high-resolution. Wall clock is unsafe
    (coarse + can step backward on an NTP sync), and on Windows ``time.time()``
    *and* ``time.monotonic()`` are both ~16 ms coarse -- so a stale pre-fire read
    and the fire share a timestamp and the gate wrongly confirms. ``perf_counter``
    is the only stdlib clock that is monotonic and sub-microsecond on Windows.
    """

    value: Any
    source: str = "server"
    observed_at: float = 0.0

    @staticmethod
    def now(value: Any, source: str = "server") -> Reading:
        return Reading(value=value, source=source, observed_at=time.perf_counter())


def _reading_value_after(reading: Any, observed_after: float):
    """Return the reading's value only if observed at/after ``observed_after``.

    Accepts a :class:`Reading` (from ``diagnostics=True`` reads) or a bare value.
    A bare value has no timestamp, so it is returned as-is -- the gate only
    applies when the reader supplied provenance.
    """
    if isinstance(reading, Reading):
        if reading.observed_at < observed_after:
            return None
        return reading.value
    return reading


def _wrap(value: Any, diagnostics: bool):
    return Reading.now(value) if diagnostics else value


# Over the Remote Scripting transport every read runs inside
# ``mesoSPIM_Core.execute_script``, which sets ``state['state']='running_script'``
# for the read's duration -- so the machine run-state is NOT observable here; it
# always reads ``'running_script'``. Report it as ``None`` ("unknown") rather than
# a misleading value. Position, settings and progress counts ARE read truthfully.
_UNOBSERVABLE_RUN_STATE = "running_script"


def _run_state(raw: Any) -> Any:
    return None if raw == _UNOBSERVABLE_RUN_STATE else raw


# -- connection health --------------------------------------------------------


def ping(client) -> bool:
    """Lightweight liveness check. True if the server answers ``ping``."""
    try:
        return client.try_request("ping").ok
    except Exception:  # noqa: BLE001 - ping must never raise
        log.debug("ping failed", exc_info=True)
        return False


# -- state --------------------------------------------------------------------


def get_state(client, *, diagnostics: bool = False) -> Reading | dict:
    """Read the full instrument state dict.

    Keys: ``position`` (``{x,y,z,f,theta}``) and the current settings
    (``filter``, ``zoom``, ``laser``, ``intensity``, ``shutterconfig``, the
    ``etl_*`` block, ...), plus ``state``.

    NOTE -- ``state`` (the mesoSPIM run-state string) is **not observable** over
    this transport: every read runs inside ``Core.execute_script``, which reports
    ``'running_script'`` for the read's duration, so ``state`` is returned as
    ``None`` (unknown). Position and settings are read truthfully.
    """
    data = dict(client.request("get_state").data)
    data["state"] = _run_state(data.get("state"))
    return _wrap(data, diagnostics)


def get_positions(client, *, diagnostics: bool = False) -> Reading | dict:
    """Read every axis position as ``{x,y,z,f,theta}`` (um / deg)."""
    data = client.request("get_position").data
    positions = {axis: _safe_float(data.get(axis)) for axis in AXES}
    return _wrap(positions, diagnostics)


def get_position(client, axis: str, *, diagnostics: bool = False) -> Reading | float | None:
    """Read a single axis position (um for linear axes, deg for theta)."""
    if axis not in AXES:
        raise ValueError(f"unknown axis {axis!r}; known axes: {AXES}")
    positions = get_positions(client)
    return _wrap(positions.get(axis), diagnostics)


def get_xyz(client, *, diagnostics: bool = False) -> Reading | dict:
    """Read just the linear stage position as ``{x, y, z}`` (um)."""
    positions = get_positions(client)
    xyz = {axis: positions.get(axis) for axis in ("x", "y", "z")}
    return _wrap(xyz, diagnostics)


# -- configuration / hardware model -------------------------------------------


def get_config(client, *, diagnostics: bool = False) -> Reading | dict:
    """Read the instrument's hardware model.

    Keys: ``lasers`` (list of ``{name, wavelength_nm}``), ``filters`` (list of
    names), ``zooms`` (list of ``{name, pixel_size_um}``), ``axes`` (list),
    ``shutter_configs`` (list), ``camera`` (``{pixels_x, pixels_y}``), and the
    server identity (``app``, ``version``).
    """
    data = dict(client.request("get_config").data)
    return _wrap(data, diagnostics)


# get_hardware_info is the cross-driver name for the same read.
get_hardware_info = get_config


def get_lasers(client) -> list[dict]:
    """List available laser lines as ``[{name, wavelength_nm}, ...]``."""
    return list(get_config(client).get("lasers", []))


def get_filters(client) -> list[str]:
    """List available emission filter names."""
    return list(get_config(client).get("filters", []))


def get_zooms(client) -> list[dict]:
    """List available zoom settings as ``[{name, pixel_size_um}, ...]``."""
    return list(get_config(client).get("zooms", []))


# -- acquisition progress -----------------------------------------------------


def get_progress(client, *, diagnostics: bool = False) -> Reading | dict:
    """Read acquisition progress.

    Keys: ``current_plane``, ``total_planes``, ``current_acquisition``,
    ``total_acquisitions``, and ``state`` -- which is ``None`` over this transport
    (the run-state is not observable; see :func:`get_state`). Judge acquisition
    completion from the frame files on disk, not ``state`` (see
    ``acquisition.capture``).
    """
    data = dict(client.request("get_progress").data)
    data["state"] = _run_state(data.get("state"))
    return _wrap(data, diagnostics)
