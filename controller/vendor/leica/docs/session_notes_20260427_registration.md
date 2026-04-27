# Session notes — 2026-04-27: cookbook + registration

Picking up where today left off.

## What was shipped (commits on `dev`)

| Commit | Subject |
|---|---|
| `6942b59` | Iterative NCC refinement cookbook script (motorized stage) |
| `4445887` | Galvo cookbook with cluster-vote registration |
| `0dfe8fe` | Drop defensive sleeps and check_idle from galvo cookbook |
| `9e689bb` | Update objective offsets calibration |
| `9293895` | Add reusable `registration.py` module |

Hardware-validated:

- **Stage one-shot** (`cookbook/motorized_stage/single_target_stage_one_shot.py`): ~3 µm landing on 10×→20×.
- **Stage iterative** (`cookbook/motorized_stage/single_target_stage_iterative.py`): converges to 1–2 µm noise floor (limited by motor backlash, not algorithm).
- **Galvo cookbook** (`cookbook/galvo_pan/single_target_galvo_one_shot.py`): 4/4 voting methods agree to <1 µm spread, ~12 µm landing error (almost certainly out-of-focus aliasing — see open items).
- **`vendor/leica/registration.py`**: reusable module, no LAS X imports, single `register()` entry point. Used in: nothing yet (cookbook still has inline copy). Migrate when convenient.

## What we learned about registration and FOV

### Pixel size, not camera format
Both PCC and NCC compare arrays element-wise. Same shape, same µm/px, same orientation. Camera format is convenient when both images come from the same scope at the same scan settings, but it's pixel size that has to match.

### Always downsample the finer image, never upsample the coarser
Upsampling fabricates pixels via interpolation; downsampling preserves real information. **Rule**: register at the **coarser** of the two pixel sizes.

### FOV must overlap, or registration is invalid
Running PCC on a full 10× field against a smaller 20× field means most of the source has no counterpart — the FFT smears that mismatch into the spectrum and you get borderline peaks that look like ambiguity but are really FOV mismatch. NCC fails outright (template > image error).

**Crop the larger-FOV image to the smaller's physical FOV before registering.**

### Crop centre is the cell of interest, not the image centre
When the cell is off-centre in the source, cropping at source's geometric centre throws away the part of the source the target actually sees. Crop around the picked cell's pixel in source, around the optical / galvo centre in the target.

### Direction-symmetric registration prep
Source → target can go in either magnification direction. The robust abstraction:

1. **Crop** whichever has the **larger FOV** (around the cell's physical location in each image).
2. **Resample** whichever has the **finer pixel size** down to the coarser.
3. Both end up at the smaller physical FOV at the coarser pixel size.

This is implemented in `registration.py::prepare_pair`.

### Voting beats single-method gates
PCC, masked PCC, NCC, and ORB+RANSAC have orthogonal failure modes (FFT artefacts, periodic patterns, neighbour-cell ambiguity, featureless regions). Any single hard threshold either rejects borderline-correct matches (false alarms) or accepts silent wrong matches.

**Cluster the four estimates by tolerance, take the largest agreeing subset, median within.** Single user knob: `--agreement-tolerance-um` (default 2 µm). Implemented in `registration.py::cluster_vote`.

Validated: 4/4 methods on a real 10×→20× pair agreed to 0.79 µm spread.

### PCC sign convention (skimage)
`phase_cross_correlation(ref, mov)` returns `shift` such that `mov = shift_op(ref, +shift)`. So source content at `(y, x)` appears in `mov` at `(y + shift_y, x + shift_x)`.

That's image-axis math. Stage axes are handled separately by the calibrated `image_to_stage_um` matrix in `pixel_to_stage_xy_um`. **Don't double-apply.** If you find yourself writing `+X, -Y` in caller code, you're probably going to double-apply something the calibration matrix already handles.

## What we learned about hardware

### Don't put `check_idle` or `time.sleep` between `move_xy_galvo` and `_acquire_one`
Defensive queries cause "Scan not started after 15s" timeouts. The example script has none and works. Removing our defensive calls turned a 100% failure into a clean run. (Saved as memory.)

### Stage Y motor has backlash
Phase 1 of `measure_objective_offsets.py`:

| Stage move | Image shift magnitude | Ratio |
|---|---|---|
| +30 µm X | 29.5 µm | 98% |
| +30 µm Y | 25.6 µm | 85% |

The 15% Y deficit is **backlash** on a fresh +Y move from rest, not a real scale anomaly. The D4 snap correctly recovers the true geometry. **Standard fix**: always approach each axis from the same direction (overshoot + return). Not yet implemented in any script.

### Cookbook scripts are missing parfocal Z correction
This is the biggest finding from `test_parcentric_calibration.py`:

- `measure_objective_offsets.py` measures only **XY motor delta**, not focus offset.
- `test_parcentric_calibration.py` measures both:
  - **Parfocal dZ between 10× and 20×: −2.57 µm** (validated to 0.91 µm residual)
  - **Parcentric XY: 6.82 µm** (real, small)

The 66 µm shift our galvo cookbook saw was **almost certainly out-of-focus aliasing**, not real parcentric drift:

1. Cookbook acquires source at 10× at whatever focus.
2. Switches to 20× — no parfocal correction.
3. 20× image is ~2.6 µm out of focus → low contrast / different visible structures.
4. Cellpose / NCC locks onto a different cell than intended.
5. Reported "66 µm" is wrong-cell aliasing, not drift.

**This is the highest-leverage fix for cookbook landing accuracy.** Once parfocal is applied after objective switch, cookbook landing should drop from 12 µm to ~1–2 µm.

## Open items, prioritised

### 1. Apply parfocal dZ in cookbook scripts (high leverage, easy)
After every `drv.set_objective(client, ..., target_slot)` in the cookbooks, set Z to `current_z + parfocal_dZ`. The dZ comes from the parcentric calibration's `calibration.json`, **not** `objective_offsets.json` (which doesn't have it).

**Decision needed**: extend `measure_objective_offsets.py` with a Z-stack phase, or have cookbook scripts consume `test_parcentric_calibration.py`'s output? The latter is faster but creates two calibration files. The former is cleaner long-term.

### 2. Calibration script needs backlash compensation
`measure_objective_offsets.py` Phase 1 currently does fresh +X then fresh +Y from rest. The Y measurement is contaminated by backlash, giving a D4 residual of 0.172 (clean would be <0.05). Fix:

```python
# Before each axis measurement
move_to(target − overshoot)   # always approach from the same direction
move_to(target)
acquire()
```

10–20 lines of code. Would drop the residual to clean and remove the false alarm.

### 3. Calibration script should refuse / warn on high D4 residual
Currently silently snaps even when the residual is 0.172 (way above clean). Add a guard:

```python
if residual > 0.05:
    log.warning("High D4 residual %.3f — investigate before trusting calibration", residual)
    # OR raise / abort if residual > 0.1
```

### 4. Cookbook iterative refinement: same-direction approach
Each refinement iteration's stage correction direction is unpredictable (±X, ±Y on each pass). Every direction reversal eats backlash → that's why the iterative cookbook hits the 1–2 µm noise floor instead of going sub-µm.

Fix: in the refinement loop, always approach the target from the same direction per axis (overshoot −X, −Y by ~5 µm, then move forward). Not yet done; see (2) for the same pattern.

### 5. Migrate cookbook scripts to use `vendor/leica/registration.py`
Currently the galvo cookbook has all the registration logic inline (~400 lines). It can be replaced with an import + a single `register()` call. Saves duplication and makes the cookbook 30% smaller. Stage iterative has its own (different) NCC code that could also use this module.

Risk: changes a working flow. Do it after parfocal is in and verified.

### 6. Investigate the new `test_parcentric_calibration.py` modifications
`git status` shows local-only changes to this script that pre-date today's session. Worth a glance — they may already include some of the improvements above.

## How to verify next session

1. Run `test_parcentric_calibration.py --job Overview --ref-slot 1 --target-slot 2` — confirm parfocal dZ and parcentric numbers are stable run-to-run.
2. Patch the galvo cookbook to apply parfocal dZ after the objective switch.
3. Re-run the galvo cookbook — landing error should drop dramatically (target: <2 µm).
4. If parfocal alone isn't enough, look at the overlay PNG to see if Cellpose is still picking different cells in the final FOV.

## Files to know about

- `vendor/leica/registration.py` — new reusable module
- `vendor/leica/cookbook/motorized_stage/` — stage one-shot + iterative cookbooks
- `vendor/leica/cookbook/galvo_pan/single_target_galvo_one_shot.py` — galvo cookbook
- `vendor/leica/test/test_parcentric_calibration.py` — full XY+Z calibration with autofocus
- `vendor/leica/test/measure_objective_offsets.py` — XY-only calibration (older, simpler, currently used by cookbooks)
- `vendor/leica/test/test_registration_benchmark.py` — where the four registration method functions originally lived
- `vendor/leica/config/objective_offsets.json` — current calibration (XY motor delta + sign matrix)
- `vendor/leica/config/alignment/calib_20260427_214826/` — today's full calibration (XY + Z + parfocal), gitignored
