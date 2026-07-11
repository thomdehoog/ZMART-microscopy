# Hardware validation — how to run today's validation on the scope

Canonical bench entry point is **run_ci** (the individual `validate_*.py`
scripts stay directly runnable for debugging):

```powershell
cd zmart_drivers/leica/stellaris5_y42h93/navigator_expert

# Mock/offline gate: no microscope, no LAS X
python run_ci.py

# Hardware gate: live LAS X validators, reversible moves/settings, and acquire smoke
python run_ci.py --hardware
```

`--hardware` runs, in order: **first a mock limits self-check** (the fail-closed
limits gate proven against the in-process mock, in THIS install, before LAS X
is touched — if it fails the run **hard-aborts and no hardware validator
runs**, so a broken limits gate can never reach the stage), then the passive
reader probe (api/log/hybrid), the side-by-side reader parity + routed
reader-mode validator, the zmart_controller↔adapter move/state/acquire
round-trip, and the
end-to-end driver validator once per reader route (`--state-reader-mode api`,
`log`, and `hybrid` explicitly), each with an acquire command.
Hardware validation uses only production driver modules — nothing under
`experimental/` (maintainer decision).

## Prerequisites

- LAS X running (simulator or scope) with the NavigatorExpert CAM add-in;
  no modal dialog open (a dialog blocks the whole CAM API).
- A template/experiment loaded with **at least two jobs** (e.g. Overview +
  HiRes) so job-selection round-trips have a target.
- Stage clear (no sample you care about): `--hardware` moves XY in a
  10-position pattern (±25 µm around the current position) and does a ±2 µm
  z-galvo round-trip, plus one or more capture+save smoke checks. Park the
  stage inside the calibrated envelope first — the validators refuse to move
  if the start position is outside limits. That refusal is a **SKIP**, not a
  failure (the LAS X simulator commonly homes at 0,0, outside a real machine's
  envelope): it means "reposition to exercise this phase," not "the driver is
  broken."
- **Machine-local limits available in ProgramData** (the single `limits.json`
  in the newest snapshot under `C:\ProgramData\zmart-microscopy\...`, alongside
  `calibration.json` or `calibrations/<name>/calibration.json`,
  `orientation.json` + `origin.json`). If ProgramData is empty, the repo
  defaults are copied there first. Every validator runs the connect-time limits
  handshake (`limits: connect handshake` in the report): it validates schema,
  finite numbers, and containment within the hardcoded physical backstop
  (`motion.limits.STAGE_BACKSTOP_UM`). Run the three setup notebooks on the rig
  to replace defaults with measured values. (`--mock` uses a hermetic
  ProgramData root and exercises the same real handshake.)
- Driver requirements installed (`pip install -r requirements-dev.txt`).

## What `--hardware` changes on the instrument (all restored in `finally`)

- Reversible per-job settings: zoom, scan speed, resonant flip, sequential
  mode, scan-field rotation, image format, frame/line accumulation+average,
  pinhole, detector gain (only if the detector exposes a writable range).
- Job selection: every reported job is selected once, then the original is
  restored. (`validate_readers_side_by_side --allow-job-switch` is NOT part of
  the run_ci set — it pops the manual-turret dialog; run it manually if wanted.)
- Stage: the XY pattern and z-galvo round-trip above; the adapter validator
  additionally does `set_origin` + small frame moves and a job switch, restored.
- Acquisition: the adapter validator reads the notebook-critical live
  `get_info()` snapshot (output root, tile positions, focus positions) and one
  acquire+save smoke through LAS X native AutoSave. Each end-to-end reader route
  runs an acquire command in its reader mode; file materialization is proven once
  through the adapter path.
- **NOT touched by run_ci**: objective turret. Opt in via a direct run only
  when the operator wants it, e.g.
  `python tests/hardware/validate_hardware.py --yes --allow-objective --allow-acquire`.

Every attempted change — including failed attempts and every restore — is
recorded in the Markdown run report with its success+CONFIRMED /
success+UNCONFIRMED / FAILED result, attempt counts, and timing.

## Expected duration

- `python run_ci.py`: mock/offline, no LAS X required.
- `python run_ci.py --hardware`: ~15–30 min against a live LAS X session
  (dominated by per-command confirmation
  polling: up to 3 × 3 s readback windows per setting write, × 3 reader
  routes). Against the in-process mock the same paths run in seconds.

## Where the results land

- **Markdown run reports** (one per validator run, human-readable):
  `tests/_report/hardware_run_report_<YYYYMMDD-HHMMSS>.md` — run metadata
  (date, host, mock-or-live, driver commit), summary table per phase, timing
  overview (per-phase and per-reader-mode latency, slowest actions,
  unconfirmed/failed changes), then the chronological detail of every
  attempted action. Paths are printed at the end of the run_ci output.
  Direct script runs write to the working directory unless `--report-dir`
  is given.
- JSONL step records: `tests/_report/hardware_validate_{api,log,hybrid}.jsonl`,
  `zmart_adapter_validate.jsonl`; step summary in `ci_summary.json`.

## Reader modes

The side-by-side validator reads every routed datum (xy, jobs, selected_job,
scan_status, hardware_info, job_settings) explicitly in `mode="api"`,
`mode="log"`, and `mode="hybrid"` through `readers.router`, records value /
provenance / freshness (age) / latency per mode, and cross-checks modes
against each other (xy within 1 µm; discrete values equal). Router-level
hybrid reads are verified working against the mock (they degrade to the api
leg when no fresh log value exists). A log-mode `None` is the router's
fail-closed answer for a stale/absent log and is recorded as SKIP; a hybrid
`None` while api delivered is recorded as a structured FAIL, not a crash.
(The hybrid *confirmation* race's API-leg self-block, CF-01, is fixed; the
select_job round-trips in `--hardware` exercise the repaired race — check
the report for which leg confirmed, and how fast.)

## Offline gates (no LAS X)

Normal CI (`python run_ci.py`, default offline mode) keeps the hardware
suite's health checked via the mock-backed wrappers, which also assert the
run report is produced:

```powershell
python -m pytest -q tests/hardware   # test_validate_*.py + test_stress_hardware.py
python tests/hardware/validate_readers_side_by_side.py --mock --yes   # offline smoke
python tests/hardware/validate_hardware.py --mock --allow-xy --allow-z --allow-objective --allow-acquire
```

The limits enforcement itself has a permanent adversarial gate in normal CI
(`tests/unit/test_limits_adversarial.py`): malformed/poisoned limits files,
NaN/inf targets, unset-envelope refusals, backstop containment, and
gate-bypass attempts through every entry point (commands, adapter,
controller). It must stay green before any bench run.
