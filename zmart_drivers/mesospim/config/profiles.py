"""
Connection, command, hardware, and acquisition profiles.
========================================================
One place for machine-sensitive tuning and the mesoSPIM hardware model, kept out
of the command wrappers (which accept explicit overrides only for tests).

- :class:`ConnectionProfile` -- host, port, password and timing for the Remote
  Control socket, including how the driver waits for an accepted change to finish.
- :class:`CommandProfile` -- per-command retry/confirm tuning (the mesoSPIM
  analog of the Leica/ZEN ``CommandProfile``, minus the vendor transport knobs).
- :class:`HardwareProfile` -- the instrument's axes, laser lines, filters, and
  zoom settings. This mirrors a mesoSPIM ``config`` file's device model; the live
  values are read back from the server via ``readers.get_config`` and this is the
  offline default / validation fallback.
- :class:`AcquisitionProfile` -- default save format, light-sheet defaults and
  the procedures the controller offers.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectionProfile:
    """Remote Control socket settings.

    Attributes:
        host, port: where mesoSPIM's Remote Control TCP server listens. The
            server binds the local machine only unless the operator changes it.
        timeout_s: how long one request may take before the socket gives up.
        token: the Remote Control password. mesoSPIM ships with the public
            placeholder ``smart_mesospim``, which the server only accepts on
            the local machine; an operator who exposes the server on the
            network must set their own, and the driver must then be given it
            (``connection["token"]``).
        operation_poll_s: how often ``get_progress`` is asked while an accepted
            change (a move, a setting) is still running.
        operation_timeout_s: how long the driver waits for an ordinary change
            to finish before it gives up. Acquisitions use their own, longer
            budget (``AcquisitionProfile.acquire_timeout_s``).
    """

    host: str = "127.0.0.1"
    port: int = 42000
    timeout_s: float = 10.0
    token: str = "smart_mesospim"
    operation_poll_s: float = 0.05
    operation_timeout_s: float = 120.0


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


# Move commands: the server itself only reports a move as completed once the
# stage reads back within 1 um of every target, so one readback here is
# insurance, not the gate. An unconfirmed readback is not a failure.
MOVE = CommandProfile(
    confirm_tolerance=1.0,
    success_on_unconfirmed=True,
)

# Rotation: coarser tolerance (degrees).
MOVE_ROTATION = CommandProfile(
    confirm_tolerance=0.1,
    success_on_unconfirmed=True,
)

# State settings (filter / zoom / laser / intensity / shutter / ETL): the
# server applies them through the Core's state handler; confirm by reading
# the same keys back.
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
    # Total budget for one capture, start to stack-on-disk. The server accepts
    # ``acquire_start`` at once and the driver then polls its operation until
    # mesoSPIM reports the run finished, up to this ceiling (a real stack can
    # take minutes). Sized generously.
    acquire_timeout_s: float = 600.0
    # Pause between polls while a capture runs.
    acquire_poll_s: float = 0.5
    # How long to wait, after the run is reported finished, for the image
    # writer to stop growing the file. Normally the file is complete already.
    file_settle_timeout_s: float = 30.0
    # Named procedures the driver exposes to the controller, beyond the
    # focus/rotation moves the adapter always offers. Each is a Remote
    # Control call that moves the stage to a position the operator configured
    # in mesoSPIM, or a plain stop.
    procedures: tuple[tuple[str, str], ...] = (
        ("zero_stage", "define the current x/y/z position as mesoSPIM's own zero"),
        ("load_sample", "move the stage to the sample-loading position set in mesoSPIM"),
        ("unload_sample", "move the stage to the sample-unloading position set in mesoSPIM"),
        ("center_sample", "move the stage to the sample-centre position set in mesoSPIM"),
        ("stop", "stop the stage immediately"),
    )


ACQUISITION = AcquisitionProfile()
