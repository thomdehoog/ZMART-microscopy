"""
Commands: the things the driver asks NIS-Elements to do.
========================================================
Every function sends one request to the bridge and returns what NIS reported
afterwards (for moves, the position it ended up at). A move is checked against
the stage limits NIS reports **before** it is sent, so a typo in a coordinate
is refused here rather than driving the stage into a limit.

Coordinates are raw NIS stage coordinates in micrometres. The frame origin the
operator sets in ZMART is handled one layer up, in the adapter.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

from typing import Any

from ..connection.client import NisClient
from ..readers import readers as _readers

# Image formats the bridge can save. "nd2" is Nikon's own format and keeps every
# piece of metadata; "tif" is the portable choice most analysis tools read.
SAVE_FORMATS = ("tif", "nd2", "ome.tif")


class LimitError(RuntimeError):
    """A requested position lies outside the stage limits NIS-Elements reports."""


def check_within_limits(limits: dict[str, dict[str, float]], targets: dict[str, float]) -> None:
    """Refuse any target outside ``limits`` (per axis ``{"min", "max"}``).

    Raises :class:`LimitError` naming the axis, the value and the allowed range,
    so the message on its own tells the operator what to fix.
    """
    for axis, value in targets.items():
        bounds = limits.get(axis)
        if bounds is None:
            raise LimitError(f"no limits known for axis {axis!r}; refusing to move it")
        lo, hi = float(bounds["min"]), float(bounds["max"])
        if not (lo <= float(value) <= hi):
            raise LimitError(
                f"{axis} = {float(value):.1f} um is outside the stage limits [{lo:.1f}, {hi:.1f}] um"
            )


def move_xyz(
    client: NisClient,
    x: float,
    y: float,
    z: float,
    *,
    limits: dict[str, dict[str, float]] | None = None,
) -> dict[str, float]:
    """Move all three axes to an absolute position (um) and return where the stage is now.

    ``limits`` defaults to the limits NIS reports right now; pass them in to
    avoid re-reading them on every move.
    """
    targets = {"x": float(x), "y": float(y), "z": float(z)}
    check_within_limits(limits or _readers.get_limits(client), targets)
    return dict(client.request("move_xyz", **targets))


def move_xy(
    client: NisClient, x: float, y: float, *, limits: dict | None = None
) -> dict[str, float]:
    """Move the XY stage only (um) and return the position afterwards."""
    targets = {"x": float(x), "y": float(y)}
    check_within_limits(limits or _readers.get_limits(client), targets)
    return dict(client.request("move_xy", **targets))


def move_z(client: NisClient, z: float, *, limits: dict | None = None) -> dict[str, float]:
    """Move the focus drive only (um) and return the position afterwards."""
    check_within_limits(limits or _readers.get_limits(client), {"z": float(z)})
    return dict(client.request("move_z", z=float(z)))


def set_objective(client: NisClient, position: int) -> int:
    """Turn the nosepiece to ``position`` (1-based) and return the position it reports."""
    return int(client.request("set_objective", position=int(position))["current"])


def select_optical_configuration(client: NisClient, name: str) -> str:
    """Activate a named optical configuration (light path, camera settings...)."""
    return str(client.request("select_optical_configuration", name=name)["selected"])


def capture(client: NisClient, *, timeout: float | None = None) -> dict[str, Any]:
    """Take one image with the current settings; returns its size and bit depth.

    The image becomes the current document in NIS-Elements; call
    :func:`save_image` to write it to disk.
    """
    return dict(client.request("capture", read_timeout=timeout))


def save_image(
    client: NisClient,
    path: str,
    *,
    format: str = "tif",
    close: bool = True,
) -> dict[str, Any]:
    """Save the current NIS document to ``path`` and (by default) close it.

    Closing keeps NIS-Elements from piling up one open window per tile during
    a long scan. Returns ``{"path", "bytes"}``.
    """
    if format not in SAVE_FORMATS:
        raise ValueError(f"unknown format {format!r}; choose one of {SAVE_FORMATS}")
    return dict(client.request("save_image", path=str(path), format=format, close=bool(close)))


def close_document(client: NisClient) -> None:
    """Close the current NIS document without saving."""
    client.request("close_document")


def move_piezo_z(client: NisClient, z: float) -> float:
    """Move the piezo Z insert to an absolute position (um); returns where it is now.

    Refused by NIS when no piezo is connected.
    """
    return float(client.request("move_piezo_z", z=float(z))["z"])


def autofocus(
    client: NisClient, *, range_um: float = 50.0, speed: int = 30, timeout: float | None = None
) -> dict[str, Any]:
    """Run NIS's image-based autofocus over ``range_um`` around the current Z.

    NIS sweeps the range, grabbing frames as it goes, and ends on the sharpest
    plane. Returns the position afterwards and how long it took. Raises
    ``RuntimeError`` when NIS reports that no focus was found.
    """
    return dict(
        client.request(
            "autofocus", range_um=float(range_um), speed=int(speed), read_timeout=timeout
        )
    )


def set_pfs(client: NisClient, on: bool, *, timeout_s: float = 8.0) -> dict[str, Any]:
    """Switch the Perfect Focus System on (and wait for it to lock) or off."""
    return dict(client.request("set_pfs", on=bool(on), timeout_s=float(timeout_s)))


def set_exposure_ms(client: NisClient, exposure_ms: float) -> float:
    """Set the camera exposure time (ms); returns the value NIS reports back."""
    return float(client.request("set_exposure", exposure_ms=float(exposure_ms))["exposure_ms"])


def live(client: NisClient) -> None:
    """Start the live camera view in NIS-Elements."""
    client.request("live")


def freeze(client: NisClient) -> None:
    """Stop the live view, keeping the last frame as the current image."""
    client.request("freeze")


def capture_z_stack(
    client: NisClient,
    *,
    z_top: float,
    z_bottom: float,
    z_step: float,
    limits: dict | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Acquire a Z-stack between two absolute Z positions (um) with a given step.

    Both ends are checked against the stage limits first. The stack becomes the
    current NIS document; call :func:`save_image` (``format="nd2"`` keeps every
    plane and all metadata) to write it to disk.
    """
    lim = limits or _readers.get_limits(client)
    check_within_limits(lim, {"z": float(z_top)})
    check_within_limits(lim, {"z": float(z_bottom)})
    return dict(
        client.request(
            "capture_z_stack",
            z_top=float(z_top),
            z_bottom=float(z_bottom),
            z_step=float(z_step),
            read_timeout=timeout,
        )
    )
