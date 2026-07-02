"""
Connection, command, hardware, and acquisition profiles.
========================================================
One place for machine-sensitive tuning and the mesoSPIM hardware model, kept out
of the command wrappers (which accept explicit overrides only for tests).

- :class:`ConnectionProfile` -- host/port/timeout for the command-server socket.
- :class:`CommandProfile` -- per-command retry/confirm tuning (the mesoSPIM
  analog of the Leica/ZEN ``CommandProfile``, minus the vendor transport knobs).
- :class:`HardwareProfile` -- the instrument's axes, laser lines, filters, and
  zoom settings. This mirrors a mesoSPIM ``config`` file's device model; the live
  values are read back from the server via ``readers.get_config`` and this is the
  offline default / validation fallback.
- :class:`AcquisitionProfile` -- default save format and light-sheet defaults.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectionProfile:
    """Command-server socket settings."""

    host: str = "127.0.0.1"
    port: int = 42000
    timeout_s: float = 10.0


CONNECTION = ConnectionProfile()


@dataclass(frozen=True)
class CommandProfile:
    """Recipe for one command's backbone behaviour.

    Attributes:
        max_retries: transient-error (timeout / dropped-link) retries inside the
            fire block.
        max_confirm_attempts: confirm-wrapper re-attempt ceiling.
        refire_on_unconfirmed: re-send the command before the next confirm
            attempt when a readback did not confirm.
        confirm_tolerance: numeric tolerance for a target readback (um or deg).
        success_on_unconfirmed: return ``success=True`` when confirmation is
            exhausted (confirmed=False) rather than a hard failure. Used for
            moves, where the fire is reliable but the reader may lag.
    """

    max_retries: int = 2
    max_confirm_attempts: int = 3
    refire_on_unconfirmed: bool = False
    confirm_tolerance: float | None = None
    success_on_unconfirmed: bool = False

    def __post_init__(self) -> None:
        # Mirror the sibling drivers' guard: a single confirm attempt cannot also
        # ask to re-fire (there is no "next attempt" to re-fire before).
        if self.max_confirm_attempts <= 1 and self.refire_on_unconfirmed:
            object.__setattr__(self, "refire_on_unconfirmed", False)


# Move commands: reliable fire, reader may lag -> accept unconfirmed as success.
MOVE = CommandProfile(
    confirm_tolerance=1.0,
    success_on_unconfirmed=True,
)

# Rotation: coarser tolerance (degrees).
MOVE_ROTATION = CommandProfile(
    confirm_tolerance=0.1,
    success_on_unconfirmed=True,
)

# State settings (filter / zoom / laser / intensity / shutter / ETL / galvo):
# the server applies them via sig_state_request; confirm by reading state back.
SET_STATE = CommandProfile(
    max_confirm_attempts=3,
    refire_on_unconfirmed=True,
    success_on_unconfirmed=True,
)


@dataclass(frozen=True)
class HardwareProfile:
    """The mesoSPIM instrument model: axes, illumination, filters, zoom.

    Defaults describe a generic mesoSPIM (Benchtop / v5). The live instrument's
    values are authoritative and read via ``readers.get_config``; these serve as
    the offline default and as a validation reference.
    """

    # Laser lines, named the mesoSPIM way ("488 nm"), with wavelength in nm.
    lasers: tuple[tuple[str, int], ...] = (
        ("405 nm", 405),
        ("488 nm", 488),
        ("561 nm", 561),
        ("647 nm", 647),
    )
    # Emission filter names available on the wheel.
    filters: tuple[str, ...] = (
        "Empty-Alignment",
        "405-488-561-647-Quadband",
        "515/30",
        "561/LP",
        "594/LP",
        "647-LP",
    )
    # Zoom settings; each maps to a pixel size (um/px) at the camera.
    zoom_pixel_size_um: tuple[tuple[str, float], ...] = (
        ("0.63x", 10.52),
        ("1x", 6.55),
        ("2x", 3.26),
        ("3.2x", 2.04),
        ("4x", 1.63),
        ("5x", 1.31),
        ("6.3x", 1.04),
    )
    # Light-sheet shutter configurations.
    shutter_configs: tuple[str, ...] = ("Left", "Right", "Both")
    # Camera default frame size (px). Hamamatsu Orca Flash 4 is 2048 x 2048.
    camera_pixels: tuple[int, int] = (2048, 2048)


HARDWARE = HardwareProfile()


@dataclass(frozen=True)
class AcquisitionProfile:
    """Acquisition + save defaults."""

    save_format: str = "ome-tiff"
    formats: tuple[str, ...] = ("ome-tiff", "raw", "h5")
    default_shutterconfig: str = "Left"
    default_zoom: str = "1x"
    # Socket read deadline for a capture reply. Acquisitions run far longer than
    # the ~10s per-request default -- the server only answers once the run
    # finishes (a real stack can take minutes). Sized as a generous ceiling.
    acquire_timeout_s: float = 600.0
    # Named procedures the driver exposes to the controller.
    procedures: tuple[tuple[str, str], ...] = (
        ("autofocus", "sweep the focus (ETL/remote) for peak sharpness"),
        ("find_sample", "move to the configured sample-load position"),
        ("zero_stage", "define the current position as the software origin"),
    )


ACQUISITION = AcquisitionProfile()
