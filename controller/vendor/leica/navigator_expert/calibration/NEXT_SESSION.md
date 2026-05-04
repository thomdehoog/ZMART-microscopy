# Next session — calibration follow-up

Picking up after the v6 schema break landed (commit `12de0e7`,
2026-04-30). Three things to finish; everything else is done and
hardware-validated.

## TL;DR of where we are

- **Architecture is clean.** One `image_to_stage` matrix +
  `parcentric_xy.{shift_um, offset_um}` and `parfocal_z.{shift_um,
  offset_um}` per target.
- **Cookbook math works.** v6 calibration produced a 3.35 µm landing
  error at-anchor (down from ~16 µm with the old motor + residual model).
  7.64 µm at ~290 µm off-center.
- **Parfocal Z is now wired** into the cookbook — it reads
  `drv.get_parfocal_shift_um(cfg, slot)` and applies via z-galvo before
  the target acquire (cookbook line ~395, the `set_z_stack_definition`
  block right before `move_xy_stage`).
- **Affine diagnostic** confirmed: rotation between slot 1 and slot 2
  is `0.033°` (negligible), scale mismatch `~0.5%` (minor — accounts for
  ~1.5 µm at 290 µm off-center). Not worth folding into the calibration
  pipeline unless someone wants <2 µm at edge of FOV.

## What's left

### 1. Cookbook crash: `parse_tile_geometry: imageSize ''`

`single_target_stage_one_shot_backlash_correction.py` line ~334. Right
after `drv.move_xy_stage` to source position, `drv.parse_tile_geometry`
sometimes returns an empty `imageSize`. LAS X transient — readback
hasn't settled when we ask. Affects all the cookbook scripts that read
geometry post-move.

Fix: wrap in retry-with-backoff or add a `time.sleep(0.5)` before the
call. ~10 lines.

### 2. Schema v6 → v7 cleanup

Operator complaints from session that landed in MEMORY:

- Slot 1 entry looks different from slot 2 entry (asymmetric structure).
- `anchor_xy_um` is operational state, doesn't belong in calibration config.
- `magnification`, `numerical_aperture`, `immersion`, `objective_number`
  aren't used by any code path.
- `is_reference` per slot is redundant with `reference_objective_slot`.
- `calibrated_at` per slot is redundant with top-level `last_updated`.

Proposed v7:
```json
{
  "schema_version": 7,
  "last_updated": "20260430_HHMMSS",
  "reference_objective_slot": 1,
  "image_to_stage": [[0, -1], [1, 0]],
  "objectives": {
    "1": {
      "name": "HC PL APO CS2 10x/0.40 DRY",
      "parcentric_xy": { "shift_um": [0, 0], "offset_um": [0, 0] },
      "parfocal_z":    { "shift_um": 0,      "offset_um": null }
    },
    "2": {
      "name": "HC PL APO CS2 20x/0.75 DRY",
      "parcentric_xy": { "shift_um": [16.38, 22.35], "offset_um": [-7.02, 21.07] },
      "parfocal_z":    { "shift_um": -50.23,         "offset_um": null }
    }
  }
}
```

Files to touch:
- `driver/machine_config.py` — schema docstring + `MACHINE_SCHEMA_VERSION`,
  `_objective_identity()` (drop fields), `set_reference()` (drop anchor),
  `update_target()` signature stays the same.
- `driver/calibration.py` — no changes needed (consumer API doesn't care
  about removed fields).
- `scripts/calibrate_objectives.py` — drop the `set_reference` anchor
  call and the per-target `set_reference()` summary fields, simplify the
  ref entry write.
- `test_calibration_consumer.py` — schema version + drop dropped fields
  in `_config()`.

Hard schema break — recalibrate after, no migration. The current v6
config file regenerates on next run.

### 3. Re-run calibration + cookbook end-to-end

Once 1 + 2 are done:

```bash
# park stage at calibration anchor (anywhere with texture)
python vendor/leica/navigator_expert/calibration/scripts/calibrate_objectives.py \
    --job Overview --ref-slot 1 --target-slots 2 \
    --ref-zoom 3.0 --measure-parfocal --measure-xy --z-range-um 100 --z-step-um 2

# park back at anchor
python vendor/leica/navigator_expert/examples/motorized_stage/single_target_stage_one_shot_backlash_correction.py \
    --job Overview --source-slot 1 --target-slot 2 --fov-bbox-margin 3.0
```

Expected: cookbook lands < 5 µm with 20× in focus.

### 4. (Optional, but worth it) Add one runtime registration step in the cookbook

Compensates for everything the static calibration doesn't model: rotation,
scale mismatch, off-anchor spatial drift, source-image Cellpose centroid
noise. Promotes the cookbook from ~3-7 µm (calibration-bound) to <1 µm
(registration-bound).

Sketch:

```
1. Slot 1 source acquire + Cellpose pick   (unchanged)
2. Translate pixel → target_command_xy via shift
3. Switch + match FOV to source            (new: keep zoom equal)
4. Move + backlash + acquire matched-FOV target image
5. register_voting(source_img, target_img) → image-frame offset
6. Convert via image_to_stage → stage offset
7. Move by -stage_offset
8. Set final (bbox-derived) zoom
9. Backlash + acquire final image
```

Cost: one extra acquire (~5 s). Calibration still required — without it,
the matched-FOV target image won't overlap the source enough to register.
Would replace step (3) onwards in
`single_target_stage_one_shot_backlash_correction.py`. ~30 lines.

## Things deliberately deferred

These showed up during the session but aren't blockers — punt to a
later session unless the user re-asks:

- **Backlash multi-cycle.** Operator reported imaging-based observation
  that multiple cycles improve repeatability. Encoder-side test showed
  position is identical after 1, 2, …, 5 cycles to 0.1 nm — the encoder
  doesn't see whatever the operator saw. Could be controller reporting
  commanded position rather than actual. The `--backlash-cycles` flag
  is wired in the one-shot cookbook and works; keep at default 1 unless
  there's a new diagnostic.
- **Rotation / scale into Phase 4.** Diagnostic measured 0.033° / 0.5%.
  Implementation would replace `register_voting`'s translation-only
  output with a full `AffineTransform`. ~50 LOC in `lib/registration.py`
  + schema bump. Worth ~1.5 µm at 290 µm off-center. Skip unless someone
  needs sub-3 µm landings at the edge of the FOV.
- **Slot 0 (40× water).** Not calibrated. The dry-pair-only docstring
  in cookbook scripts needs adding once slot 0 work begins. The slot 0
  switch must be its own session (water → dry can't happen mid-session
  without dragging water through residue — see your memory note).
- **GetZ readback.** No `PyApiGetZ` in LasxApi. `parfocal_z.offset_um`
  stays `null`. Could be added by extending the LAS X client wrapper
  if needed.
- **Cookbook `correct_backlash` consolidation.** Each cookbook has its
  own local copy of `correct_backlash`. Migrate them to import
  `drv.correct_backlash` from `stage_motion.py`. Trivial sweep — 8
  cookbook scripts, one-liner each.
- **Legacy `driver/objective_offsets.py`.** Module + its predecessor
  calibration script (`test/measure_objective_offsets.py`) + its tests
  (`test_objective_offsets_unit.py`) are still present. Nothing in the
  active flow uses them; they exercise the v3 schema. User said leave
  them alone for now. Delete in a follow-up cleanup pass once confident
  no notebook imports the legacy module directly.

## State of the working tree right now

- `calibration/config/config.json` — v6, last calibration crashed at
  Phase 4. Values shown are from the previous successful v6 run
  (parcentric `(16.38, 22.35)`, parfocal `−50.23`). Parfocal hit the
  edge of the search range (`tgt_brenner_peak_um = 4.17` near top of
  100 µm stack) — re-run with `--z-range-um 100` once cookbook is fixed.
- `calibration/config/config.v5.bak.json` — preserved for reference,
  not used by any code. Safe to delete.
- `calibration/scripts/measure_parcentric_only.py` and
  `measure_objective_affine.py` — diagnostic scripts. Both committed
  (the parcentric one was; affine wasn't yet, see below).
- `calibration/scripts/measure_objective_affine.py` — **not committed
  yet.** Useful diagnostic, hands-off operator workflow. Worth committing
  as part of the next session's first commit.
- The cookbook's `--backlash-cycles` flag was added but the local
  `correct_backlash` definition still differs from `drv.stage_motion`.
  Both still work identically, but consolidating is the cleanup work
  noted above.

## What did NOT change today (anchors for sanity)

- `lib/registration.py` — `register_voting` still translation-only.
  Sign convention prose corrected earlier in session. 4 methods, voting
  by largest cluster within `tolerance_um`. Quality is `finite_median`
  of agreeing methods.
- `lib/lasx_state.py` — no changes from the file split. `make_acquirer`
  closure still wraps every acquire with `correct_backlash`. The
  calibration script uses this; the cookbook does its own backlash
  inline (with the new `cycles` param).
- `driver/calibration.py` — consumer API stable: `load_calibration`,
  `get_parcentric_shift_um`, `get_parcentric_offset_um`,
  `get_parfocal_shift_um`, `translate_stage_xy_between_objectives`,
  `pixel_to_stage_xy_um`. These are what cookbooks call. v7 schema
  cleanup shouldn't need to touch this file.

## Validation checklist for next session

After applying 1 + 2 and re-running:

- [ ] `python -m py_compile` clean on all 4 calibration files +
      8 cookbooks + 3 driver files.
- [ ] 6 focused tests still pass (`test_calibrate_objectives_registration.py`,
      `test_calibration_consumer.py`).
- [ ] `calibrate_objectives.py --help` runs (no encoding crashes).
- [ ] Calibration runs end-to-end with `--measure-parfocal --measure-xy`.
- [ ] Cookbook lands < 5 µm at-anchor with 20× in focus.
- [ ] Optional: cookbook off-center pick (`--pick-pixel 300 300`) still
      lands < 10 µm.

If those pass, this work is done. Commit, move on to slot 0 / galvo /
whatever's next.
