"""
Instrument-state command wrappers.
==================================
Public write commands for instrument state: filter, zoom, laser, intensity,
shutter, and ETL settings, applied via the server's ``sig_state_request``. Each
follows the three-phase pattern shared across the driver:

    Phase A -- pre-checks: validate values.
    Phase B -- backbone: build a ``fire_fn`` (sends one protocol request) and a
        target-bound ``confirm_fn`` (reads state back with the freshness gate),
        then call ``confirm_and_fire``.
    Phase C -- the standard result envelope is returned as-is.

Sibling: stage movement lives in :mod:`mesospim.motion.movement`; acquisition
(snap / run list) lives in :mod:`mesospim.acquisition`. These wrappers cover
instrument state, not motion or capture.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
from functools import partial

from ..config.profiles import SET_STATE
from ..readers.readers import _reading_value_after, get_state
from ..utils import _fail
from .dispatch import confirm_and_fire

log = logging.getLogger(__name__)


# =============================================================================
# Confirmation
# =============================================================================


def _confirm_state_keys(client, wanted, *, observed_after):
    """Confirm that every key in ``wanted`` reads back equal in the state dict."""
    reading = get_state(client, diagnostics=True)
    state = _reading_value_after(reading, observed_after)
    if state is None:
        return {"confirmed": False, "reason": "stale readback"}
    for key, want in wanted.items():
        got = state.get(key)
        # Numeric fields compare with a small tolerance; the rest exact.
        if isinstance(want, (int, float)) and isinstance(got, (int, float)):
            if abs(float(got) - float(want)) > 1e-6:
                return {"confirmed": False, "state": {k: state.get(k) for k in wanted}}
        elif got != want:
            return {"confirmed": False, "state": {k: state.get(k) for k in wanted}}
    return {"confirmed": True, "state": {k: state.get(k) for k in wanted}}


# =============================================================================
# Instrument-state settings (via sig_state_request on the server)
# =============================================================================


def set_state(client, settings: dict) -> dict:
    """Apply a batch of mesoSPIM state settings and confirm the readback.

    ``settings`` keys are mesoSPIM state keys (``filter``, ``zoom``, ``laser``,
    ``intensity``, ``shutterconfig``, ``etl_l_amplitude``, ...). The server
    applies them via ``sig_state_request_and_wait_until_done``; confirmation
    reads the same keys back.
    """
    if not settings:
        return _fail("set_state", "no settings given")
    label = "set_state " + ",".join(f"{k}={v}" for k, v in settings.items())
    return confirm_and_fire(
        client,
        label,
        SET_STATE,
        fire_fn=lambda: client.request("set_state", settings=dict(settings)),
        confirm_fn=partial(_confirm_state_keys, wanted=dict(settings)),
    )


def set_filter(client, name: str) -> dict:
    """Select an emission filter by name."""
    return set_state(client, {"filter": name})


def set_zoom(client, name: str) -> dict:
    """Select a zoom setting by name (e.g. ``"1x"``)."""
    return set_state(client, {"zoom": name})


def set_laser(client, laser: str) -> dict:
    """Select the active laser line by name (e.g. ``"488 nm"``)."""
    return set_state(client, {"laser": laser})


def set_intensity(client, intensity: float) -> dict:
    """Set the active laser intensity (0-100 %)."""
    if not 0 <= float(intensity) <= 100:
        return _fail("set_intensity", f"intensity {intensity} out of range [0, 100]")
    return set_state(client, {"intensity": float(intensity)})


def set_shutter(client, shutterconfig: str) -> dict:
    """Select the light-sheet shutter configuration (``Left`` / ``Right`` / ``Both``)."""
    return set_state(client, {"shutterconfig": shutterconfig})


def set_etl(
    client,
    side: str,
    *,
    amplitude: float | None = None,
    offset: float | None = None,
) -> dict:
    """Set the electrically tunable lens parameters for one sheet side.

    ``side`` is ``"left"`` or ``"right"``; either ``amplitude`` or ``offset``
    (or both) may be given.
    """
    side = side.lower()
    if side not in ("left", "right"):
        return _fail("set_etl", f"side must be 'left' or 'right', got {side!r}")
    prefix = "etl_l" if side == "left" else "etl_r"
    settings = {}
    if amplitude is not None:
        settings[f"{prefix}_amplitude"] = float(amplitude)
    if offset is not None:
        settings[f"{prefix}_offset"] = float(offset)
    if not settings:
        return _fail("set_etl", "give amplitude and/or offset")
    return set_state(client, settings)


__all__ = [
    "set_state",
    "set_filter",
    "set_zoom",
    "set_laser",
    "set_intensity",
    "set_shutter",
    "set_etl",
]
