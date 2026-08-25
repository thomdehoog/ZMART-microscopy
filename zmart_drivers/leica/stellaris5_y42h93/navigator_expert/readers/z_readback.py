"""Z readback that stays honest when the drive carries the job's z-stack.

Why this exists
---------------
LAS X hands the driver no Z position readout. What the job settings call
``zPosition`` is the job's own last-issued setpoint, and it stops being
refreshed for whichever drive the job's z-stack is defined on: a ``move_z``
on that drive is accepted and executed, yet the settings keep reporting the
old value. (Measured on the simulator 2026-08-25, every route through the
CAM API and every Leica log exhausted; see ``docs/design`` and the memory
note ``lasx_z_readback``.) A reader that trusts that field on a stacked drive
returns a stale number with a confident label, and a confirmation built on
it re-sends the move — five ``SetZPosition`` for one request.

The saved experiment does update. ``PyApiSaveExperiment`` makes LAS X write
the ``.lrp`` from its live block objects, and each job's Master
``ATLConfocalSettingDefinition`` carries a ``ZPosition`` (metres) for the
drive named by its ``ZUseMode``. That is still the commanded value of the
job the move went through — not a hardware reading, and it cannot detect a
drive that did not go where it was told — but it is current, costs ~0.4 s,
needs no GUI and changes no job.

So this reader makes one decision per call, from data it already has:

* the requested drive is free (no stack, or the stack is on the other
  drive) -> the ordinary settings read, byte-for-byte the current path;
* the requested drive is the stack drive -> save the experiment and read
  the job's ``ZPosition`` from the ``.lrp``.

The decision is a lookup on the ``stack`` block of the same settings dict
the ordinary read fetches, so the free path pays nothing extra. That is a
requirement, pinned by the unit tests counting calls.

Dependency direction:
    - Imports: ``.router`` (settings read), ``.derived`` (settings-shape
      parsing), ``.parsing`` (the stack block), ``..scanfields.files``
      (the save), stdlib.
    - Imported by: nothing yet — the wiring into ``move_z``'s confirmation
      and the routed readers is a separate, reviewed change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..scanfields.files import save_and_read_lrp
from .derived import z_um_from_settings
from .parsing import stack_from_settings
from .router import get_job_settings

log = logging.getLogger(__name__)

Z_DRIVES = ("z-galvo", "z-wide")

# The ``.lrp`` names the drive a job's ZPosition belongs to by number, on the
# ``ZUseMode`` attribute of the setting definition. Same table the LRP
# editors use (``experimental/lrp_edits/z.py``); repeated here rather than
# imported so a core reader does not depend on the experimental package.
LRP_Z_USE_MODES = {"0": "z-wide", "1": "z-galvo"}


@dataclass(frozen=True)
class ZReading:
    """One Z position with its provenance.

    ``source`` says which path answered: ``"settings"`` (the ordinary job
    settings read) or ``"lrp"`` (the experiment was saved and parsed).
    Callers that persist the value — calibration, ``get_info`` — should keep
    the source beside it, because the two mean different things: the
    settings value tracks the drive, the ``.lrp`` value is the last command
    the job issued.
    """

    z_um: float
    drive: str
    job_name: str
    source: str


def _check_drive(drive: str) -> None:
    if drive not in Z_DRIVES:
        raise ValueError(f"unknown Z drive {drive!r}; expected one of {Z_DRIVES}")


def stacked_drive(settings) -> str | None:
    """The drive the job's z-stack is on, or None when the job has no stack.

    Read off the ``stack`` block of the raw job settings, through the one
    stack parser the rest of the driver uses.
    """
    stack = stack_from_settings(settings)
    if stack is None:
        return None
    return stack.get("zDrive")


def drive_is_stacked(settings, drive: str) -> bool:
    """True when *drive* is the one carrying the job's z-stack.

    This is the whole decision the reader makes, and it is a dictionary
    lookup on data already in hand — no extra CAM traffic on either answer.
    """
    _check_drive(drive)
    return stacked_drive(settings) == drive


def z_um_from_lrp(lrp_data, job_name: str, drive: str) -> float:
    """*job_name*'s Master ``ZPosition`` from parsed ``.lrp`` data, in µm.

    The file holds one ``ZPosition`` per setting definition, for the drive
    its ``ZUseMode`` names. Asking for the other drive is refused rather than
    answered with the wrong axis under the right label.
    """
    _check_drive(drive)
    job = lrp_data["jobs"].get(job_name)
    if job is None:
        raise RuntimeError(
            f"No such job {job_name!r} in the saved experiment; it has {list(lrp_data['jobs'])}"
        )
    attrs = job.get("Master", {}).get("attrs", {})
    file_drive = LRP_Z_USE_MODES.get(attrs.get("ZUseMode"))
    if file_drive != drive:
        raise RuntimeError(
            f"The saved experiment holds {job_name!r}'s ZPosition for "
            f"{file_drive!r} (ZUseMode={attrs.get('ZUseMode')!r}), not for {drive!r}"
        )
    raw = attrs.get("ZPosition")
    if raw is None:
        raise RuntimeError(f"{job_name!r}'s Master setting carries no ZPosition")
    return float(raw) * 1e6


def read_z(client, job_name: str, drive: str, *, mode=None) -> ZReading:
    """*drive*'s Z position for *job_name*, honest about a stacked drive.

    Raises ``RuntimeError`` when neither path can answer — never a stale
    number. ``mode`` is the state-reader mode for the settings read, as for
    the routed readers.
    """
    _check_drive(drive)
    settings = get_job_settings(client, job_name, mode=mode)
    if not settings:
        raise RuntimeError(f"read_z: could not read job settings for {job_name!r}")

    if not drive_is_stacked(settings, drive):
        return ZReading(
            z_um=z_um_from_settings(settings, drive),
            drive=drive,
            job_name=job_name,
            source="settings",
        )

    log.debug("read_z: %s carries %s's z-stack; saving the experiment to read it", drive, job_name)
    lrp_data = save_and_read_lrp(client)
    if lrp_data is None:
        raise RuntimeError(
            f"read_z: {drive} carries {job_name!r}'s z-stack, so the settings value is "
            f"stale, and the experiment save failed — no current Z available"
        )
    return ZReading(
        z_um=z_um_from_lrp(lrp_data, job_name, drive),
        drive=drive,
        job_name=job_name,
        source="lrp",
    )
