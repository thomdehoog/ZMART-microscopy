# Claude review plan: objective calibration and driver-owned preflight

## Review boundary

Review only the changes made after commit `cccd9e6` on branch
`claude/forfable4-document-11mxsx`. The work may still be uncommitted, so inspect
both `git diff cccd9e6` and the working tree. Do not modify files, commit, push,
or run real microscope hardware.

The changed surface should be limited to:

- Leica objective-pair calibration, adoption, connection state, and adapter;
- the objective-pair calibration notebook and offline tests;
- driver-readiness consumption in the v4 notebooks and browser workflow;
- focused workflow/driver tests supporting those changes.

Treat unrelated pre-existing code and formatter warnings as outside scope unless
the new diff makes them reachable or materially more dangerous.

## Intended behavior to verify

1. Calibration remains wholly driver-owned. `zmart_controller` must remain a
   thin forwarding surface, and v4/web must not calculate, select, or apply
   objective translations.
2. The Leica profile selects the active `water_lens_setup` calibration. Missing
   limits, orientation, or calibration files seed bundled defaults. Corrupt or
   unusable calibration must never allow an uncompensated cross-objective move.
3. Driver preflight reports configuration evidence and a single readiness
   verdict. It must distinguish a measured 0-degree orientation from the shipped
   unmeasured identity placeholder, reject corrupt files that falsely claim
   `measured: true`, and verify both active-objective and run-origin slots exist
   in the loaded calibration.
4. Objective translation is `(motoric X, motoric Y, z-wide)`. `ΔT.z` must always
   be realized through z-wide. An explicitly selected z-galvo may realize only
   ordinary requested frame-Z motion. Repeated moves must not accumulate `ΔT.z`.
   Every required Z leg must be preflighted before any XY or Z motion.
5. The calibration notebook never selects objectives or changes Navigator Expert
   jobs. The operator changes only the objective while retaining one job. Every
   measurement reads, reports, records, and verifies the actual slot/name.
6. An established reference slot is authoritative. A conflicting first-cell
   `reference_slot` must fail with an actionable choice: use another calibration
   session or use the established reference.
7. Each target is stored as an absolute translation relative to the common
   zero-reference objective. Pairwise and reverse translations are inferred as
   `T[to] - T[from]`; offline 10→20, 10→40, and 10→60 measurements must cover all
   16 ordered mappings including four identities.
8. Objective-pair acquisitions perform exactly five motoric-XY backlash
   jog-and-return passes immediately before each of the four acquisitions. They
   must have zero intended net displacement, never touch Z/galvos/job/objective,
   remain scoped out of orientation and other workflows, and never enter
   calibration JSON.
9. Calibration concerns exclude XY and Z galvos. Their settings are not zeroed;
   the notebook instructs the operator to leave them unchanged between jobs.
10. Reference and target XY acquisitions must use exactly the same physical
    pixel size in µm/pixel, fine enough for credible sub-micrometre registration.
    Their scan/zoom settings may differ. The driver must refuse mismatched
    physical pixel sizes.
11. Z-stack focus measurement remains passive. Only the later XY acquisitions
    set z-wide to the measured reference/target focus. Saved XY images use the
    adopted camera-to-stage orientation; Z translation is independent of that
    2-D rotation.
12. V4 notebooks and the website consume only the driver's opaque readiness
    verdict. They must refuse before acquisition when the Leica driver reports
    an unmeasured orientation, missing calibration, uncalibrated active slot, or
    uncalibrated origin slot. Drivers without the optional verdict must remain
    compatible.

## Adversarial review questions

- Can a stale, malformed, partially populated, or misleading configuration be
  reported ready?
- Can an objective change be missed because the code reads a configured job
  objective rather than the live active objective?
- Can a manual job change, wrong reference, wrong target, same-slot target, or
  rerun leave an adoptable stale staging file?
- Can target adoption overwrite the authoritative reference, lose session/slot
  provenance, infer the wrong sign, or mix objective names with slots?
- Can z-galvo absorb any part of objective `ΔT.z`, or can repeated calls add the
  translation more than once?
- Can a failed second Z leg leave a misleading success record? Are all targets
  checked before the backlash-compensated XY move begins?
- Can five-pass calibration backlash leak into orientation, normal acquisition,
  or persisted JSON?
- Can v4 or web bypass readiness through a different entry path, stale captured
  state, target-job selection, page refresh, or demo compatibility fallback?
- Are notebook instructions operationally exact and minimal, with no stale
  “same zoom” wording where “same physical pixel size” is required?
- Do missing defaults remain safe while still being honestly identified as
  defaults/placeholders rather than microscope measurements?

## Required validation

Use the repository's prepared environment when available:

```bash
PY=/Users/thomdehoog/miniconda3/envs/zmart-microscopy-fresh-20260711/bin/python
```

Run:

```bash
$PY -m ruff check \
  zmart_drivers/leica/stellaris5_y42h93/navigator_expert \
  workflows/target_acquisition

$PY zmart_drivers/leica/stellaris5_y42h93/navigator_expert/run_ci.py

$PY -m pytest -q zmart_controller/tests --tb=short

MPLBACKEND=Agg $PY -m pytest -q \
  zmart_controller/tests \
  workflows/target_acquisition/tests \
  zmart_drivers/leica/stellaris5_y42h93/navigator_expert/tests/unit/test_zmart_adapter.py \
  --tb=short
```

Parse every changed notebook as JSON and parse every code cell with `ast.parse`.
Also run `git diff --check` and verify generated CI report files are not left in
the final diff.

Do not treat the unavailable LAS X runtime on macOS as a defect; the one runtime
test should skip. Report the three known, unrelated Ruff-format warnings only as
pre-existing diagnostics if they remain confined to `motion/movement.py`,
`tests/unit/test_limits_adversarial.py`, and `tests/unit/test_stage_backlash.py`.

## Expected report

Lead with findings, ordered Critical → High → Medium → Low. Every finding must
include:

- an exact file and line reference;
- the violated intended behavior;
- a concrete failure scenario and impact;
- the smallest appropriate remediation;
- whether an existing test should have caught it and the adversarial test to add.

Then list validation commands and exact outcomes. If there are no findings, say
so explicitly and identify any remaining real-hardware-only assumptions, most
importantly whether Leica's API reports the newly active objective slot/name
after a manual objective switch while the Navigator Expert job remains unchanged.
