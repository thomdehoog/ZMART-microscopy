"""
Readers: questions the driver asks NIS-Elements without changing anything.
==========================================================================
Each function here sends one read-only request to the bridge and returns the
answer as plain Python. Positions and limits are in micrometres, exactly as
NIS-Elements reports them (the "raw" stage frame; the adapter applies the
frame origin on top).

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

from typing import Any

from ..connection.client import NisClient


def get_bridge_info(client: NisClient) -> dict[str, Any]:
    """Version of the bridge and of NIS-Elements (``{"bridge", "protocol", "nis", "pid"}``)."""
    return dict(client.request("ping"))


def get_devices(client: NisClient) -> dict[str, bool]:
    """Which motorised parts NIS sees: ``xy``, ``z``, ``z_secondary``, ``nosepiece``."""
    return dict(client.request("get_devices"))


def get_position(client: NisClient) -> dict[str, float]:
    """Current stage position ``{"x", "y", "z"}`` in micrometres."""
    return dict(client.request("get_position"))


def get_limits(client: NisClient) -> dict[str, dict[str, float]]:
    """Software travel limits per axis, ``{"x": {"min", "max"}, ...}`` in micrometres.

    These are the limits NIS-Elements itself enforces (Devices > Stage limits);
    the driver refuses a move outside them before asking NIS.
    """
    return {axis: dict(bounds) for axis, bounds in client.request("get_limits").items()}


def get_objectives(client: NisClient) -> dict[str, Any]:
    """The nosepiece: ``{"present", "current", "objectives": [{"position", "name"}, ...]}``."""
    return dict(client.request("get_objectives"))


def get_optical_configurations(client: NisClient) -> list[str]:
    """Names of the optical configurations defined in NIS-Elements."""
    return list(client.request("get_optical_configurations")["names"])


def get_calibration(client: NisClient) -> dict[str, Any]:
    """Pixel size of the current image (``pixel_size`` with ``unit``; 0 = uncalibrated)."""
    return dict(client.request("get_calibration"))


def get_z_drives(client: NisClient) -> dict[str, Any]:
    """The Z drives NIS sees: ``{"drives": [{"index", "kind", "z"}], "piezo_index", "active_index"}``.

    ``kind`` is ``"piezo"`` for the piezo insert and ``"motoric"`` for the
    microscope's own focus drive; ``piezo_index`` is -1 when there is no piezo.
    """
    return dict(client.request("get_z_drives"))


def get_pfs(client: NisClient) -> dict[str, Any]:
    """Perfect Focus System state: ``present``, ``on``, ``focused``, ``status`` and its ``meaning``."""
    return dict(client.request("get_pfs"))


def get_exposure_ms(client: NisClient) -> float | None:
    """The camera exposure (ms) as last set through the bridge; None when not set yet.

    NIS-Elements offers no way to read the exposure back without a blocking
    dialog, so the bridge reports the value it applied last.
    """
    value = client.request("get_exposure")["exposure_ms"]
    return None if value is None else float(value)
