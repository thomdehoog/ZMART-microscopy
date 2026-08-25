# Z readback on a stacked drive: what LAS X gives, and what the driver does with it

Status: reader built and unit-tested (`readers/z_readback.py`, 2026-08-26);
the wiring into commands and readers below is a plan, not started. Driver:
`zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`.

## The finding (simulator, 2026-08-25; every route exhausted)

The CAM API has no Z position readout. What the driver reads as the position
— `zPosition` in the job settings from `GetJobSettingsByName`, on both the
API leg and the log leg (which parses the same JSON) — is the job's own
last-issued setpoint, serialised by native `LCS.exe` from the ATL block. It
follows the drive only while that drive carries no z-stack. **For the drive
the job's stack is on (`stack.zDrive`), it freezes**: a `move_z` there is
accepted and executed (`SetZPosition … Error="0"`, seen on the display) and
the settings keep the old value. Per drive, not per job; no other job's
settings, no CAM object, no raw command, no Leica log, no event, pipe,
socket or COM object reports it. The live value exists only inside the CAM
host process (`ServerStateNode_ZDrive.CurrentHardwarePosition`) and on the
GUI; exposing it is a one-line change on Leica's side.

What the driver does today on that drive: `confirm_move_z` polls the frozen
field for a window, the `MOVE_Z` profile re-fires — five `SetZPosition` for
one request, 12.5 s — and returns `confirmed=False` for a move that
happened; the return move then reports `confirmed=True` against a value that
never changed. Anything persisting `zPosition` (focus positions in
`get_info()`, calibration) is stale by construction for the stacked drive.

**The saved experiment updates.** `PyApiSaveExperiment` (already wrapped:
`scanfields/files.py::save_experiment`, `save_and_read_lrp`) makes LAS X
write the `.lrp` from its live block objects; each job's Master
`ATLConfocalSettingDefinition` carries `ZPosition` (metres) for the drive
its `ZUseMode` names (`0` z-wide, `1` z-galvo). Measured: 0.4–0.5 s round
trip, no dialog, no job change, file overwritten in place under LAS X's
`User_0\ScanningTemplates`. It is the commanded value of the job the move
went through — current, but not a hardware reading: it cannot detect a drive
that did not go where it was told.

## Decisions (Thom, 2026-08-25/26)

- The driver stays a pure API client. No GUI route of any kind.
- **Fallback in the reader:** if the requested drive is the one carrying
  the job's z-stack, save the experiment and read that job's `ZPosition`
  from the `.lrp`; otherwise the ordinary settings read.
- **The fallback must not slow the ordinary read.** The decision is a lookup
  on the `stack` block already in the settings dict — zero extra calls.
- `SynchronizeFocusDrives` must be `True` on any LAS X the driver runs
  against (it is a job-switch focus-sync flag, not a readback).

## What exists now

`readers/z_readback.py`, tests in `tests/unit/test_z_readback.py` (12):

- `stacked_drive(settings)` / `drive_is_stacked(settings, drive)` — the
  decision, off `stack_from_settings` (the driver's one stack parser).
- `z_um_from_lrp(lrp_data, job_name, drive)` — Master `ZPosition` in µm;
  refuses a drive the file does not hold (`ZUseMode` disagrees) and a
  missing job.
- `read_z(client, job_name, drive, *, mode=None) -> ZReading(z_um, drive,
  job_name, source)` — settings path when the drive is free (tests count:
  one settings read, no save); save-and-parse when it is the stack drive
  (one save); raises rather than returning a stale number when the save
  fails.

Nothing imports it yet.

## The wiring, in order — each its own commit, suites green

### 1. The routed readers answer through `read_z`

`router.read_zwide_um` (and the log reader's twin) become thin calls to
`read_z(..., "z-wide")`; add `read_zgalvo_um` the same way rather than
leaving the galvo without a named reader. Result carries `source`.
*Measured by:* `test_state_readers` unchanged; `test_z_readback` call-count
tests; a routed-reader test asserting the free path makes exactly one
settings read.

### 2. `confirm_move_z` stops polling a frozen field

At entry, read the settings once (it does already, through `_readback`).
If `drive_is_stacked(settings, ZMODE_KEY[z_mode])`: do not poll, do not let
the profile re-fire. Save once, compare the `.lrp` value to the target
within tolerance, and return a result whose meaning is stated:
`{"success": True, "confirmed": <decision A>, "logs": [...]}`, with the
`.lrp` value and the words "stack drive: LAS X records the command, not the
position" in the log entry. The free drive keeps today's polling.
The `MOVE_Z` profile's re-fire must be suppressed for that branch — either
`confirm_move_z` returns before the profile's re-fire logic sees an
unconfirmed result, or the profile gains a per-call `refire_on_unconfirmed`
override; the review decides which.
*Measured by:* `test_core_driver` `confirm_move_z` cases unchanged for the
free drive; new cases: stacked drive → exactly one `SetZPosition`, one
save, no poll loop; stacked drive with failed save → `success=True,
confirmed=None`, message says why.

### 3. What persists `zPosition` says where it came from

`get_info()` focus positions and the calibration report take the value from
`read_z` and store `source` beside it. A stacked-drive value is labelled
`lrp`; consumers that need a hardware reading (calibration) treat `lrp` as
"commanded" and say so in their report.
*Measured by:* the calibration and `get_info` tests assert the field.

### 4. Docstrings stop saying "live"

`derived.z_um_from_settings` / `zwide_um_from_settings` and the README
describe `zPosition` as the job's stored z reference that tracks the drive
only while the drive carries no stack. `Z_USE_MODES` gets one owner
(`readers/z_readback.LRP_Z_USE_MODES` vs `experimental/lrp_edits/z.py`
— merge, do not keep both in step).

### 5. The live validator's Z phase cannot pass by doing nothing

`tests/hardware/validate_hardware.py phase_z` logs PASS when `_settings()`
times out and returns `None`; it must report SKIP/FAIL with the reason.
With the fallback in place, `--allow-z` exercises both drives and reports
`source` for each.

## Decision A — what `confirmed` means on the stack drive (for the review)

The result-dict contract is `confirmed: bool | None`. On the stack drive the
`.lrp` can confirm that LAS X *accepted the command*, not that the drive is
there. Options: (i) `confirmed=True` when the `.lrp` matches the target —
reads naturally, overstates what is known; (ii) `confirmed=None` with the
`.lrp` value in the message — honest, but callers treating `None` as
"unknown" may retry or warn; (iii) a third value, `"accepted"` — precise,
but changes a contract every wrapper shares. Recommendation: (ii), with the
log entry carrying the value, until a caller demonstrates a need for (iii).

## Out of scope

The Leica ticket (a CAM readback of `CurrentHardwarePosition`), any GUI
route, the real-scope confirmation, and the decompiled sources (scratchpad
only; recipe in the memory note).
