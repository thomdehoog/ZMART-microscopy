# Z readback on a stacked drive: what LAS X gives, and what the driver does

Status: settled and merged (PR #15, 2026-08-26). Driver:
`zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`. Measured on the
STELLARIS simulator on this machine, 2026-08-25/26, with the operator
watching the LAS X display; real-scope confirmation deliberately not
pursued — the API-shape findings are instrument-independent.

## The finding

The CAM API has no Z position readout. What the driver reads as the
position — `zPosition` in the job settings from `GetJobSettingsByName`,
on the API leg and the log leg alike (the log leg parses the same JSON) —
is the job's own last-issued setpoint, serialised by native `LCS.exe` from
the ATL block. It follows the drive only while that drive carries no
z-stack. **For the drive the job's stack is defined on (`stack.zDrive`),
it freezes**: a `move_z` there is accepted and executed (`SetZPosition …
Error="0"`, seen on the display) and the settings keep the old value. Per
drive, not per job: with the stack on the galvo the galvo freezes and
z-wide follows; with the stack on z-wide the reverse.

Every other route was exhausted before this was accepted (the memory note
`lasx_z_readback` holds the full table): all 62 `PyApi*` objects and 67
shared-object models carry Z only as inputs; the raw command channel drops
unknown names silently; `GetJobsInformation` and `GetConfocalHardwareInfo`
carry no position; every Leica log records the command, never a resulting
position; no pipe, socket, COM object, event or config verbosity switch
exposes it. The live value exists inside the CAM host process
(`ServerStateNode_ZDrive.CurrentHardwarePosition`, rendered on the GUI's
XYZ panel) and nothing hands it to a client — exposing it is a one-line
change on Leica's side, which has been asked for.

What the driver did on that drive before: `confirm_move_z` polled the
frozen field for its window, the profile re-fired, and a single request
became five `SetZPosition` commands over 12.5 s ending in `confirmed=False`
for a move that had happened. Anything persisting `zPosition` was stale by
construction for that drive.

## What LAS X does give: the saved experiment

`PyApiSaveExperiment` (wrapped in `scanfields/files.py::save_experiment`,
`save_and_read_lrp`) makes LAS X write the `.lrp` from its live block
objects. Each job's Master `ATLConfocalSettingDefinition` carries
`ZPosition` (metres) for the drive its `ZUseModeName` names —
`"z-galvo"` or `"z-wide"`, LAS X's own spelling, beside the numeric
`ZUseMode` (1 and 2 on this LAS X; the experimental LRP editors' table
`{0: z-wide, 1: z-galvo}` is wrong, see below). One `ZPosition` per job,
for that drive only. Measured: 0.4–0.5 s round trip, no dialog, no job
change, the file overwritten in place under LAS X's
`User_0\ScanningTemplates`. It is the commanded value of the job the move
went through — current, but the same kind of thing as the settings field,
not a hardware reading.

Two saved experiments, one per stack drive, are committed as fixtures
under `tests/data/z_readback/`.

## The fix, and where it lives

One change, in the reader: `readers/derived.py::z_um_from_settings`, the
function every Z number in the driver comes from, falls back to the saved
experiment when the requested drive is the one carrying the job's stack.
The decision is a lookup on the `stack` block already in the settings, so
the free drive costs nothing extra; the stacked drive costs the one save.
The routed reader (`read_zwide_um`), `confirm_move_z` and the adapter's
hardware snapshot pass the client and job name the save needs, and do
nothing else — the confirmation only compares. The two settings
normalisers were made idempotent so the confirmation's copy goes through
the same extractor. The behavioural mock freezes the stacked drive's
`zPosition` the way LAS X does, so the path is exercised offline.

Result on the simulator: `move_z` on the stacked drive confirms in one
attempt, ~1 s, `confirmed=True`; the free drive is unchanged (0.1–0.2 s).

### The principle this follows

The readers — api, log, hybrid, chosen by `STATE_READERS` — are the
single source of truth. When a value is wrong, it is fixed where the
reader makes it, so every consumer gets the fix at once. Confirmations
call the reader and compare; they do not grow fallbacks, knobs or second
sources of their own. Three PRs that did exactly that (#11–#14: a
`z_stack_drive_readback` profile knob, `confirmed=None` semantics with a
backbone change, a dedicated confirmation branch) were reverted in favour
of the thirty-line reader change above.

### What "confirmed" means for Z

On either drive, `confirmed=True` means LAS X accepted the command as
given and recorded it — not that the drive has arrived. XY has a hardware
readback (`GetStageHwPosition`); Z has none. Arrival on the real scope is
a matter of settle time sized to the travel, or of the image (an AF sweep
or focus metric). Worth measuring there: whether `SetZPosition`'s
`<Result>` returns only after the move completes (a long move against the
`lcsCommand.log` timestamps). If it does, the fire itself is the arrival
signal.

## Open items

- `experimental/lrp_edits/z.py::Z_USE_MODES` is `{0: "z-wide", 1:
  "z-galvo"}`; LAS X writes 1 = z-galvo, 2 = z-wide. `lrp_set_z_use_mode("z-wide")`
  would write 0. Use `ZUseModeName`, or 2.
- `tests/hardware/validate_hardware.py phase_z` logs PASS when its
  settings read times out and returns `None` — a Z phase that does nothing
  reports green. Its job round-trip (`SelectJob 'HiRes'`) once wedged the
  CAM API on the simulator until the GUI was touched.
- `SynchronizeFocusDrives` must be `True` on any LAS X the driver runs
  against (it is a job-switch focus-sync flag, not a readback).
- This machine's machine-local `limits.json` is in the old
  `constraints/stage.*` schema, so every session runs on the bundled
  default limits with a warning; the simulator's stage sits at (0, 0),
  outside that envelope, so `move_xy` is refused there.
- The log reader's own `read_zwide_um(job_name, snapshot)` has no client
  and cannot save; on a stacked drive it raises. The routed reader is the
  one to use.
