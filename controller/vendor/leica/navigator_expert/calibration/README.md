# Objective calibration run guide

How to run `calibrate_objectives.py` on the scope. The script's module
docstring is the canonical reference; this guide is the on-scope
checklist.

## 1. LAS X state

Before launching:

- The job you'll pass to `--job` is **selected** in LAS X.
- AFC / autofocus is **off**, no modal dialogs.
- `ImageTransformation = TOPLEFT` in LAS X Advanced Settings.
- Stage parked over a region with **dense texture** at zoom 1.0 on
  the reference objective. Sparse fields break the registration.
- Reference objective in focus (operator-set z-wide). Z-galvo is
  forced to 0 by the script.
- `--ref-zoom` high enough that every target zoom stays ≥ 0.75
  (Leica hardware floor): `ref_zoom ≥ 0.75 × max(target_mag) / ref_mag`.
  Default layout (ref=10×, targets=20×): use `--ref-zoom 3.0`.

## 2. Fast wiring test

Sign convention + firmware-XY-delta only. ~30 s. Confirms
acquire / config write / run-folder creation.

```bash
cd controller/vendor/leica
python navigator_expert/calibration/scripts/calibrate_objectives.py \
    --job Overview --target-slots 2
```

Expected output:

- `sign convention: ... label=...`
- `firmware xy delta on switch: (...)`
- `Live config:        .../calibration/config/config.json`
- `Run folder:         .../calibration/runs/<timestamp>/`

If anything errors here, **stop and diagnose** before the long run.

## 3. Real run

Add `--measure-shift-z` and/or `--measure-shift-xy` to populate the
v9 calibration fields the cookbook actually uses:

```bash
python navigator_expert/calibration/scripts/calibrate_objectives.py \
    --job Overview --ref-slot 1 --target-slots 2 --ref-zoom 3.0 \
    --measure-shift-z --measure-shift-xy --z-range-um 25 --z-step-um 1
```

**Slot 0 (40× water) constraint**: once water is on the coverslip
you cannot switch back to a dry objective without dragging it
through the residue. The script switches in any order and restores
the reference at the end. So **run dry targets first, water-immersion
slots separately and last** (or in a fresh session after applying water).

## 4. Verify the outputs

| File | Purpose |
|---|---|
| `calibration/config/config.json` | Live v9 config (overwritten each run) |
| `calibration/config/stage.json` | Hand-edited stage limits + backlash params |
| `calibration/runs/<ts>/config.json` | Snapshot of this run's config |
| `calibration/runs/<ts>/report.json` | Diagnostics per phase |

Sanity-check the report:

- Sign convention `label` (e.g. `-Y +X`) and `residual_from_d4 < 0.3`.
- If `--measure-shift-z` ran: Brenner peak in the expected ballpark,
  `shift_um` < the half z-range.
- If `--measure-shift-xy` ran: voting `trusted: true`, ≥ 2 agreeing
  methods (4 / 4 is ideal), per-method estimates clustered tightly.

## 5. Smoke-test the cookbook

Once `config.json` is v9-shaped, run an example to confirm the
cookbook reads + applies the new fields:

```bash
python navigator_expert/examples/objective_switch_target.py \
    --job Overview --source-slot 1 --target-slot 2
```

The cookbook calls `drv.translate_xyz_between_objectives` against
`config.json`, and the output `summary.json` includes the
predicted vs measured landing.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `sign-convention fit too far from D4` | Sparse texture, drift, or `--sign-move-um` too small. Move to a denser region or increase the move. |
| `LAS X not idle` | Modal dialog open, or scan still running. Dismiss and retry. |
| `move_xy_stage to ... failed` | Stage limits in `stage.json` or stage already outside bounds. |
| Low voting confidence on shift_xy | Sparse texture, focus drift, or scale mismatch. Move to denser texture; use higher `--ref-zoom`; consider running `--measure-shift-z` first so the target image acquires in focus. |
| `target zoom X below hardware min 0.75; clamping` | `--ref-zoom` too low for the highest-mag target. Bump to `0.75 × max(tgt_mag) / ref_mag` or higher. |

## CLI reference

The complete list (with current defaults) is `--help` on the script.
Key flags:

```
--job              LAS X job (must already be selected)
--ref-slot         Reference objective slot (default: 1)
--target-slots     One or more target slots
--measure-sign     Re-measure sign convention (default: reuse cached)
--measure-shift-z  Measure z-wide focus residual via a Brenner stack
--measure-shift-xy Measure optical-axis XY shift via voting registration
--ref-zoom         Reference zoom (default: 1.0)
--settle           Seconds after each objective switch (default: 3.0)
--sign-move-um     Sign-phase test-move size (default: 30 um)
--z-range-um       Brenner stack half-range (default: 15 um)
--z-step-um        Brenner stack step size (default: 1 um)
--scan-format      Image dimensions (default: "1024 x 1024")
--scan-speed       Scan speed in Hz (default: 600)
```
