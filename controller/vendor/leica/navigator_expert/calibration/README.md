# Objective calibration run guide

Step-by-step for running `calibrate_objectives.py` on the scope.

## 1. LAS X state

Before launching the script:

- Job is **currently selected** in LAS X (whatever you'll pass to `--job`).
- AFC / autofocus is **off**.
- No modal dialogs open.
- `ImageTransformation = TOPLEFT` in LAS X Advanced Settings.
- Stage parked over a region with **dense texture** (multiple cells in
  view at zoom 1.0 on the reference objective). Sparse fields break
  phase correlation.
- Reference slot has the right objective (default `--ref-slot 1`).
- `--ref-zoom` high enough to keep every target zoom ≥ 0.75 (Leica hardware
  floor). Rule: `ref_zoom ≥ 0.75 × max(target_mag) / ref_mag`. For the
  default layout (ref=10×, targets=20× and 40×), use `--ref-zoom 3.0`.
  If too low, the script clamps target zoom to 0.75 and warns — but FOV
  no longer matches the reference, which can degrade phase 4 voting quality.

## 2. Fast wiring test first

Sign convention + motor-delta only. ~30 s. Confirms acquisition,
config write, run-folder creation all work.

```bash
cd controller/vendor/leica
python navigator_expert/calibration/scripts/calibrate_objectives.py \
    --job Overview --target-slots 2
```

Expected output:

- `sign convention: ... label=...`
- `motor delta: (...)`
- `Live config:        .../calibration/config/config.json`
- `Run folder:         .../calibration/runs/<timestamp>/`

If anything errors here, **stop and diagnose** before running the long one.

## 3. Real run

For dry objectives, run image-based XY residual + verification at
z-galvo 0. Add `--measure-parfocal` only for an objective pair that
actually needs Z correction.
2-5 min for dry slot 2 without parfocal; longer if Z-stacks or multiple
targets are included.

**Slot 0 (40× water) constraint:** once water is on the coverslip you
cannot switch back to a dry objective without dragging it through the
residue. The script does not know this — it will happily switch in any
order and restores the reference (slot 1, dry) at the end regardless.
So **run dry targets first, slot 0 separately and last** (or in a
fresh session after applying water).

Dry targets only (slot 2):

```bash
python navigator_expert/calibration/scripts/calibrate_objectives.py \
    --job Overview --ref-slot 1 --target-slots 2 --ref-zoom 3.0 \
    --measure-xy --verify --max-iterations 3
```

Slot 0 (40× water), separate session after applying water — kill or
manually handle the final reference-restore so the dry 10× isn't pulled
back through water:

```bash
python navigator_expert/calibration/scripts/calibrate_objectives.py \
    --job Overview --ref-slot 1 --target-slots 0 --ref-zoom 3.0 \
    --measure-parfocal --measure-xy --verify
```

Phases (in order):

1. **Sign convention** — under reference objective, fits image-to-stage 2x2 transform.
2. **Motor-delta XY** per target — readback delta on objective switch.
3. **Parfocal Z** per target — optional Z-stacks both objectives,
   Brenner peak, verification stack.
4. **Image XY residual** per target — high-quality slice on each
   objective at z-galvo 0 unless parfocal is enabled; voting
   registration, sign-converted. `--max-iterations 3` repeats the
   measure/move/re-measure loop and persists the final cumulative
   correction; the default `--max-iterations 1` preserves single-pass
   behavior.
5. **Verification** per target — re-acquire at corrected XY+Z,
   report what's left.

## 4. Check the outputs

| File | Purpose |
|---|---|
| `navigator_expert/calibration/config/config.json` | Live config (overwritten each run) |
| `navigator_expert/calibration/config/stage.json` | Hand-edited stage limits + backlash params |
| `navigator_expert/calibration/runs/<ts>/config.json` | Snapshot of this run's config |
| `navigator_expert/calibration/runs/<ts>/report.json` | Diagnostics: brenner peaks, voting quality/confidence, residuals |

Sanity-check the report numbers:

- Sign convention `label` (e.g. `-Y +X`) and `residual_from_d4 < 0.3`.
- If `--measure-parfocal` was used: `dz_um` is in the right ballpark
  and `verification_residual_um` is near zero (~< 1 um).
- Image voting is trusted, with at least 2 agreeing methods; 4/4 is ideal.
- If iterative XY was used, `image_xy.iterations` shows each measured
  residual, whether it was applied, and the cumulative stage correction.
- Verification `residual_image_um` small (< 1-2 um for a clean run).

## 5. Smoke-test the cookbook (optional)

After a successful real run, prove the cookbook picks up the latest
values via `navigator_expert/calibration/config/config.json`:

```bash
python navigator_expert/examples/motorized_stage/single_target_stage_one_shot_backlash_correction.py \
    --job HiRes --source-slot 1 --target-slot 2
```

The cookbook reads `parcentric_xy.motor_um` and `residual_um` from the
canonical config and computes the command delta at runtime, before the
backlash takeup and the final acquire.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `sign-convention fit too far from D4` | Sparse texture, drift, or `--sign-move-um` too small. Move to a denser region or increase the move. |
| `LAS X not idle` | Modal dialog open, or scan still running. Dismiss and retry. |
| `move_xy_stage to ... failed` | Stage limits or position outside `stage.json` bounds. |
| Low voting confidence or untrusted image XY | Sparse texture, focus drift, wrong Z plane, or scale mismatch. Move to denser texture; use `--ref-zoom 3.0`; add `--measure-parfocal` only if the objective pair is not parfocal. |
| `target zoom X below hardware min 0.75; clamping` | `--ref-zoom` too low for the highest-mag target. Bump to `0.75 × max(tgt_mag) / ref_mag` or higher. |

## CLI reference

```
--job             LAS X job (must already be selected)
--ref-slot        Reference objective slot (default: 1)
--target-slots    One or more target slot(s) to calibrate
--measure-sign    Re-measure sign convention (default: reuse cached)
--measure-parfocal  Measure parfocal dZ via Z-stacks (slow)
--measure-xy      Measure image XY residual (z-galvo 0 unless parfocal)
--verify          Acquire at corrected position and report residuals
--ref-zoom        Reference zoom (default: 1.0)
--settle          Seconds after each objective switch (default: 3.0)
--sign-move-um    Sign-phase test-move size (default: 30 um)
--sign-settle     Seconds after each sign-phase move (default: 1.0)
--z-range-um      Z-stack half-range (default: 15 um)
--z-step-um       Z-stack step size (default: 1 um)
--scan-format     Image dimensions (default: "1024 x 1024")
--scan-speed      Scan speed in Hz (default: 600)
--max-iterations  Max image-XY refinement iterations (default: 1)
--xy-residual-threshold-um  Stop once remaining XY residual is below this (default: 0.5 um)
```
