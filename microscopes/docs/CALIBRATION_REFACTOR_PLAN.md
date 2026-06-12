# Calibration Refactor Plan

This plan covers a coordinated cleanup of the calibration subsystem:
schema simplification, file naming, vendor-neutral relocation, and the
`promotion` -> `adopt` rename. The pieces are interrelated -- done
together they leave the calibration system in a meaningfully cleaner
shape; done piecemeal each PR rewrites overlapping code.

The plan is meant to be self-contained. A reader (human or Codex) should
not need session history to act on it.

---

## 1. Why this exists

Four concerns motivated the rework:

1. **Canonical calibration data has drifted from its original
   three-layer intent.** The auto-memory note
   `smart_microscopy_three-layer_calibration_model` records the original
   design: `P_target = P_ref + translation`; calibration measures
   `translation = motor_shift + correction`; `motor_shift` and
   `correction` live in the per-run report only; only the **total
   translation** belongs in the canonical JSON. The current
   `calibration.json` (schema v9) stores all four sub-deltas
   (`offset_xy_um`, `shift_xy_um`, `offset_z_um`, `shift_z_um`) in the
   canonical file, conflating diagnostic detail with consumer data.

2. **`stage.json` mixes two unrelated concerns.** Stage safety **limits**
   are configured (hard floors the driver refuses to cross). **Backlash**
   is calibrated (measured empirically from the stage). Storing them in
   the same file is convenience without conceptual coherence.

3. **Translation math is vendor-neutral, but lives in the vendor
   package.** `calibration/vendor/leica/navigator_expert/core/model.py`
   does pure arithmetic on a dict -- no LAS X calls, no Leica-specific
   structures. It belongs alongside `shared/algorithms/` and
   `shared/output_layout/`. Only the acquisition side (notebooks and
   LAS X-talking helpers) is vendor.

4. **`promotion` is HR/marketing language in a scientific codebase.**
   The action is "take a validated session result and write it as the
   current canonical state". `adopt` reads more naturally and avoids the
   connotation.

---

## 2. Design principles (binding for this refactor)

Listed in priority order. Subsequent decisions inherit from these.

1. **Hard safety = `limits/.../defaults.json`.** Anything the driver refuses
   by default (out-of-range moves, future intensity ceilings, etc.) lives in
   the configured physical envelope. Target acquisition may narrow that
   envelope for one run and record it in `limits/.../current.json`, but callers
   must request that file explicitly. Limits are *configured*, not measured.

2. **Measured state = `calibration.json`.** Anything determined
   empirically from the instrument (optical translations between
   objectives, stage backlash) lives in `calibration.json`. The driver
   consumes these as configuration; they don't act as safety floors.

3. **The reference objective is a chosen origin.** Translations form a
   self-consistent graph in stage space. The reference is whichever
   entry has `translation_um == [0, 0, 0]`. Changing the reference is a
   pure math operation (`set_reference()` subtracts the new ref's
   translation from every other entry); no measurements need re-doing.

4. **Single source of truth + cached annotation.** A top-level
   `reference_objective_slot` field exists for human readability, but
   the `[0, 0, 0]` entry is the authority. The loader validates they
   agree and fails loudly on drift.

5. **Vendor split.** Acquisition (vendor-specific, talks to vendor APIs)
   stays in `calibration/vendor/<v>/<package>/`. Math and schema
   (vendor-neutral) go in `shared/calibration/`. A vendor package
   exports small `calibration_path()` / `limits_path()` helpers that
   workflows import to find the vendor-specific data files.

6. **Audit trail via `session_id`.** Each calibrated entry carries a
   `session_id` pointing at the session directory that produced it. The
   diagnostic breakdown (offset, shift, raw measurements, Brenner
   curves, plots) lives in that session directory; only the final
   `translation_um` triple ships to the canonical file.

7. **Backlash is calibrated, not configured.** Even though it's a
   stage-motion parameter, it's *measured*, so it lives in
   `calibration.json` next to the other measured state. Limit files stay pure
   configured safety.

8. **Migration is explicit, not implicit.** Reading config never mutates
   files. A separate `migrate_current_calibration.py` script (or
   explicit `load_calibration(path, allow_migrate=True)` opt-in) does
   the schema bump. Default `load_calibration()` on an old schema
   raises with a clear pointer to the migration command.

---

## 3. Target state

### 3.1. File layout

```
calibration/vendor/leica/navigator_expert/
+-- current/
|   +-- calibration.json    optical calibration + backlash; schema v11

limits/vendor/leica/navigator_expert/
+-- defaults.json           configured physical microscope envelope; schema v1
+-- current.json            last active working envelope; schema v1
```

The driver reads `limits/.../defaults.json` by default. Target acquisition
starts from that physical envelope, narrows to the run envelope, writes
`limits/.../current.json` with a `source` field, then explicitly reloads
`current.json` before applying it.

### 3.2. `calibration.json` schema v11

```json
{
  "schema_version": 11,
  "last_updated": "<YYYYMMDD_HHMMSS>",
  "reference_objective_slot": 1,
  "image_to_stage": {
    "matrix": [[a, b], [c, d]],
    "session_id": "<id of the calibrate_image_to_stage session, or null>"
  },
  "objectives": {
    "<slot>": {
      "name": "<human-readable name from LAS X hardware info>",
      "translation_um": [dx, dy, dz],
      "session_id": "<id of the calibrate_objective_pair session, or null>"
    }
  },
  "backlash": {
    "approach": "+X+Y",
    "overshoot_um": <float>,
    "settle_ms": <int>,
    "tolerance_um": <float>,
    "session_id": "<id or null if hand-tuned>"
  }
}
```

**Removed from v9:**

- `objectives.<slot>.offset_xy_um` -- moves to per-session breakdown only
- `objectives.<slot>.shift_xy_um` -- folded into `translation_um[:2]`
- `objectives.<slot>.offset_z_um` -- folded into `translation_um[2]`
- `objectives.<slot>.shift_z_um` -- folded into `translation_um[2]`

**Added in v11:**

- `objectives.<slot>.translation_um` -- single `[dx, dy, dz]` triple
- `objectives.<slot>.session_id` -- audit pointer
- `image_to_stage` becomes a dict (`matrix` + `session_id`)
- `backlash` block (moved from `stage.json`)

**Reference handling:**

- `reference_objective_slot` is a cached annotation for `cat`/`jq`
  convenience.
- Authoritative reference is `the slot whose translation_um == [0, 0, 0]`.
- Loader validates: `cfg["reference_objective_slot"]` must equal
  `get_reference_slot_from_data(cfg)`. Disagreement -> raise.

### 3.3. Migration formula (v9 -> v11) -- read this carefully

**XY translation in v11 is `shift_xy_um` from v9. NOT `offset_xy_um + shift_xy_um`.**

The current `model.py` already uses `shift_xy_um` only for the XY
translator (`offset_xy_um` is recorded for diagnostic firmware-jump
reasoning via `firmware_xy_after_switch` / `residual_xy_after_switch`,
not added to shift in production translation). The v9 -> v11 transform
therefore drops `offset_xy_um` entirely.

**Z translation in v11 is `offset_z_um + shift_z_um` from v9.**

Asymmetric on purpose: in v9 the Z translator IS the sum of both,
because `offset_z_um` is the firmware z-wide diff observed on switch and
`shift_z_um` is the Brenner-derived residual measured relative to
post-switch z-wide. Both are additive in the production Z translation
already.

So the v9 -> v11 mapping per objective entry is:

```
translation_um[0] = v9.shift_xy_um[0]
translation_um[1] = v9.shift_xy_um[1]
translation_um[2] = v9.offset_z_um + v9.shift_z_um
```

Reference entry: all four v9 fields are zero, so `translation_um = [0, 0, 0]`.

### 3.4. `limits/.../current.json` schema v1

```json
{
  "schema_version": 1,
  "source": "defaults | boundary_markers | cfg_fallback | scan_field | migration",
  "stage_um": {
    "x":       [<x_min>, <x_max>],
    "y":       [<y_min>, <y_max>],
    "z_galvo": [<z_galvo_min>, <z_galvo_max>],
    "z_wide":  [<z_wide_min>, <z_wide_max>]
  }
}
```

Flat schema. The file name already says "limits" -- no need to nest
under a `"limits"` key. `source` is provenance for humans and logs, not a
runtime branch. Future extensions (per-objective z, laser
intensity caps, detector gain ceiling, acquisition duration bounds, max
single-XY step) add as top-level keys when needed.

### 3.5. Driver stage-config API after the split

After PR #1, the driver stage-config API reads the split limits and
calibration files and exposes the current schema directly:

```python
# driver/stage/config.py
def load_stage_config(*, limits_path: Path | None = None,
                      calibration_path: Path | None = None) -> dict:
    """Read limits + current/calibration.json's backlash block.

    Returns:
        {
            "stage_um": <from selected limits file["stage_um"]>,
            "backlash": <from calibration.json["backlash"]>,
        }
    """
```

No compatibility mapping is kept. With no `limits_path`, the driver reads
`limits/.../defaults.json`. Consumers read `stage_cfg["stage_um"]` for limits
and `stage_cfg["backlash"]` for backlash.

**Backlash consumer audit (required as part of PR #1):**

`correct_backlash` in `driver/stage/movement.py` has hard-coded defaults
in its signature (`overshoot_um=50.0`, `settle_ms=100`,
`tolerance_um=20.0`). Those duplicate the values in the current
`stage.json`. After the split:

- The defaults stay (as a last-resort fallback so the driver doesn't
  raise if no calibration is loaded), but they are ONLY a fallback.
- The audit confirms every production caller passes the values from
  `stage_cfg["backlash"]` via `backlash_params=`, never relies on the
  function defaults.
- The `_apply_backlash_if_requested` helper in
  `driver/acquisition/capture.py` already accepts
  `backlash_params: dict | None` and uses `.get(..., default)` on each
  field -- that pattern stays; the defaults inside `.get()` keep matching
  the signature defaults so behavior is identical when params are
  missing.
- Add a docstring note on `correct_backlash` stating "defaults are a
  fallback; production should pass `**stage_cfg['backlash']` from
  `load_stage_config()`".

### 3.6. `shared/calibration/` (post-PR #2)

```
shared/calibration/
+-- __init__.py
+-- model.py        MOVED from calibration/.../core/model.py
+-- schema.py       optional: schema constants + validators
```

`model.py` after the move:

- Drops `default_path()` and `_calibration_root()`. Callers pass paths
  explicitly.
- Drops `get_offset_xy_um`, `get_shift_xy_um`, `get_offset_z_um`,
  `get_shift_z_um` (the data is gone from the JSON).
- Drops `firmware_xy_after_switch`, `residual_xy_after_switch`
  (depended on offset; only callers are model.py itself and examples).
- Adds `get_reference_slot(config)` -- derives from `[0, 0, 0]` entry,
  validates against cached `reference_objective_slot`.
- Adds `set_reference(config, new_ref_slot)` -- re-origins the graph;
  updates both the cached field and all translations.
- Adds `get_translation_um(config, slot)` -- single accessor for the
  `[dx, dy, dz]` triple.
- Simplifies `translate_xy_between_objectives`,
  `translate_z_between_objectives`, `translate_xyz_between_objectives`
  to subtract translations directly (no more offset/shift dual paths).
- Default `load_calibration(path)` REFUSES old schemas; the error
  points to the explicit migration script (see section 4).

### 3.7. Workflow imports

Before:

```python
from calibration.vendor.leica.navigator_expert.core import model as calib
cfg = calib.load_calibration()
ref = cfg["reference_objective_slot"]
tx, ty, tz = calib.translate_xyz_between_objectives(
    x, y, z, cfg, from_slot=ref, to_slot=target,
)
```

After:

```python
from shared.calibration import model as calib
from calibration.vendor.leica.navigator_expert import calibration_path
cfg = calib.load_calibration(calibration_path())
ref = calib.get_reference_slot(cfg)
tx, ty, tz = calib.translate_xyz_between_objectives(
    x, y, z, cfg, from_slot=ref, to_slot=target,
)
```

Same shape; shorter import; explicit path; explicit reference accessor.

### 3.8. `promotion` -> `adopt` rename

| Item | Before | After |
|---|---|---|
| File | `core/promotion.py` | `core/adopt.py` |
| Function | `promote_calibration(...)` | `adopt_calibration(...)` |
| Log filename | `.promotion.log` | `.adopt.log` |
| Notebook cell heading | "Promote" | "Adopt" |
| Docstrings / READMEs / errors | "promote/promoted/promotion" | "adopt/adopted/adoption" |

Affected files (~15 string sites + 1 file rename + 1 function rename):

- `calibration/vendor/leica/navigator_expert/core/promotion.py` (rename -> adopt.py)
- `calibration/vendor/leica/navigator_expert/core/model.py` (4 error strings + 1 docstring)
- `calibration/vendor/leica/navigator_expert/core/common.py` (1 docstring)
- `calibration/vendor/leica/navigator_expert/core/image_to_stage.py` (1 print)
- `calibration/vendor/leica/navigator_expert/core/objective_pair.py` (2 prints)
- `calibration/vendor/leica/navigator_expert/notebooks/calibrate_image_to_stage.ipynb` (cell heading)
- `calibration/vendor/leica/navigator_expert/notebooks/calibrate_objective_pair.ipynb` (cell heading)
- `calibration/vendor/leica/navigator_expert/README.md` (several lines)
- `driver/vendor/leica/navigator_expert/README.md` (architecture comments)
- `CLAUDE.md` (1 line)
- `README.md` (1 line)

---

## 4. Migration plan

### 4.1. Explicit, one-time migration script

Reading config never mutates files. The schema bump is a separate
explicit operation:

```
cd <repo root>
python -m calibration.vendor.leica.navigator_expert.migrate_current_calibration
```

or equivalently:

```
python calibration/vendor/leica/navigator_expert/migrate_current_calibration.py
```

The script is idempotent: if both files are already at the target
schema, it logs "already current" and exits 0.

**Steps the script performs:**

1. Read existing `calibration/vendor/leica/navigator_expert/current/calibration.json` (v9)
   and `calibration/vendor/leica/navigator_expert/current/stage.json` (v1).
2. Build the new v11 calibration dict:
   - For each entry in `objectives`:
     - Apply the formula from section 3.3:
       - `translation_um[0] = v9.shift_xy_um[0]`
       - `translation_um[1] = v9.shift_xy_um[1]`
       - `translation_um[2] = v9.offset_z_um + v9.shift_z_um`
     - Reference slot retains `translation_um = [0, 0, 0]` (all four
       v9 sub-fields are zero for it).
     - Drop `offset_xy_um`, `shift_xy_um`, `offset_z_um`, `shift_z_um`.
     - Set `session_id = null` (historical sessions are unrecoverable;
       new calibrations going forward fill it in).
   - `image_to_stage`: wrap as `{"matrix": <old matrix>, "session_id": null}`.
   - `backlash`: copy from `stage.json["backlash"]` verbatim; add `"session_id": null`.
   - `reference_objective_slot`: copy from v9 top-level field; validate
     it equals the slot whose computed `translation_um == [0, 0, 0]`.
     If they disagree -> abort with a clear error and write nothing.
3. Bump `schema_version` to 11; refresh `last_updated` to the migration timestamp.
4. Atomic-write new `calibration.json`.
5. Write `limits/vendor/leica/navigator_expert/current.json` containing
   `{"schema_version": 1, "stage_um": <old stage.json["limits_um"]>}`
   (note: rename old `limits_um` -> current `stage_um` to match the
   extensibility convention).
6. Delete `stage.json`. Git history is the backup -- the migration is
   one commit, so a single `git revert` returns the working tree to v9.
   No `.bak` fossil in the source tree.
7. Print a summary: "Migrated to v11. {N} objectives. Reference: slot {S} ({name})."

**What `load_calibration()` does on an old schema:**

- Detects `schema_version < 11`.
- Raises `OldSchemaError` (or similar) with the message:
  > "calibration.json is at schema v{N}; this code expects v11. Run
  > `python -m calibration.vendor.leica.navigator_expert.migrate_current_calibration`
  > to migrate. The migration is reversible via `git revert` on the
  > migration commit."
- Does NOT mutate any files. Loading is a read-only operation.

### 4.2. Verification pins for the migration

The current `calibration.json` has slot 1 (10x DRY) as the reference
and two calibrated pairs. The expected v11 `translation_um` triples
(computed against Python's float arithmetic so the migration unit test
can pin them exactly):

**Slot 0 (HC PL APO CS2 40x/1.10 WATER)**

| Component | v9 value | Folded into |
|---|---|---|
| `shift_xy_um` | `[-19.69708, 32.9913604275696]` | `translation_um[:2]` |
| `offset_z_um` | `-7.430000000000291` | `translation_um[2]` |
| `shift_z_um` | `10.175871798653134` | `translation_um[2]` |
| **`translation_um` (v11)** | -- | **`[-19.69708, 32.9913604275696, 2.7458717986528427]`** |

**Slot 2 (HC PL APO CS2 20x/0.75 DRY)** -- the 10 -> 20 calibration:

| Component | v9 value | Folded into |
|---|---|---|
| `shift_xy_um` | `[-6.458369500000001, 21.53989335]` | `translation_um[:2]` |
| `offset_z_um` | `-6.109999999999673` | `translation_um[2]` |
| `shift_z_um` | `2.401066210072713` | `translation_um[2]` |
| **`translation_um` (v11)** | -- | **`[-6.458369500000001, 21.53989335, -3.7089337899269594]`** |

**Slot 1 (HC PL APO CS2 10x/0.40 DRY)** -- the reference:

| Component | v9 value | v11 value |
|---|---|---|
| `shift_xy_um` | `[0.0, 0.0]` | `translation_um[:2]` |
| `offset_z_um` | `0.0` | `translation_um[2]` |
| `shift_z_um` | `0.0` | `translation_um[2]` |
| **`translation_um` (v11)** | -- | **`[0.0, 0.0, 0.0]`** |

A migration unit test should pin these three triples exactly.

### 4.3. Acceptance criteria (each PR)

For any PR landing under this plan, run from the repo root:

```
# Full driver suite
python -m pytest driver/vendor/leica/navigator_expert/tests/ -q

# Full workflow suite
python -m pytest workflows/vendor/leica/navigator_expert/target_acquisition/tests/ -q

# Hardware validator against the mock (full coverage including risky ops)
python driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py \
    --mock --allow-xy --allow-z --allow-objective --allow-acquire

# Stress runner against the mock (includes template round-trip and acquire terminal steps)
python driver/vendor/leica/navigator_expert/tests/hardware/stress_hardware.py \
    --mock --rounds 30 --cycles 4 --seed 1 \
    --allow-template-roundtrip --allow-acquire

# Focused gates for the validator and stress runner
python -m pytest \
    driver/vendor/leica/navigator_expert/tests/hardware/test_validate_hardware.py \
    driver/vendor/leica/navigator_expert/tests/hardware/test_stress_hardware.py -q
```

All commands must return exit 0.

For PR #1 specifically, two additional tests:

1. **Migration unit test**: pins the three triples in section 4.2 exactly,
   plus the slot 1 reference check `[0.0, 0.0, 0.0]`, plus the
   `reference_objective_slot` consistency check (it must equal the
   slot of the `[0, 0, 0]` entry).

2. **Save/load semantic round-trip**: load a v11 file, save it back,
   load it again, and assert **semantic equality** -- the
   `last_updated` field is allowed to differ between the saves (since
   save refreshes it). The semantic comparison:

```python
def semantically_equal(a: dict, b: dict) -> bool:
    """Equal except for last_updated, which is refreshed on every save."""
    a = {k: v for k, v in a.items() if k != "last_updated"}
    b = {k: v for k, v in b.items() if k != "last_updated"}
    return a == b
```

   (Or: inject a deterministic timestamp via monkeypatch for the test.
   Either approach is acceptable; pick one and document it inside the
   test.)

---

## 5. Sequencing

Three PRs in order. Don't bundle PR #1 and PR #2: PR #1 leaves
model.py in clean shape, then PR #2 relocates it without semantic
change. Bundling makes the diff hard to read.

### PR #1 -- schema v11 + file split + adopt rename + explicit migration

Single PR because all four changes touch overlapping files
(`model.py`, `promotion.py` -> `adopt.py`, notebooks, READMEs, error
messages, the new migration script).

Tasks:

1. Bump `SCHEMA_VERSION` to 11 in `model.py`.
2. Write `calibration/vendor/leica/navigator_expert/migrate_current_calibration.py`
   (the explicit migration script per section 4.1).
3. Update `load_calibration()` to detect old schemas and raise the
   `OldSchemaError` per section 4.1. Reads do NOT mutate files.
4. Refactor `model.py`:
   - Drop offset/shift accessors and the `firmware_*` / `residual_*`
     helpers.
   - Add `get_translation_um`, `get_reference_slot`, `set_reference`.
   - Simplify `translate_xy/z/xyz_between_objectives`.
5. Rename `promotion.py` -> `adopt.py`, `promote_calibration` ->
   `adopt_calibration`, `.promotion.log` -> `.adopt.log`.
6. Update notebooks to write v11 and use "adopt" cell headings.
7. Update the driver's stage-config loader per section 3.5: read limits from
   `limits/vendor/leica/navigator_expert/current.json`, backlash from
   `calibration.json["backlash"]`, and
   return the current shape (`{"stage_um": ..., "backlash": ...}`).
8. Backlash consumer audit per section 3.5: confirm every production caller
   passes `stage_cfg["backlash"]` through, document the function-signature
   defaults as fallbacks only.
9. Update the four caller files (`pipeline/target.py`,
   `pipeline/overview.py`, `pipeline/preflight.py`,
   `examples/objective_switch_target.py`).
10. Update test mocks (`tests/test_target_mock.py`,
    `tests/test_selection.py`, `tests/test_summary_schema.py`).
11. Sweep "promote" -> "adopt" in docstrings / READMEs / CLAUDE.md /
    root README.
12. Add the migration unit test and the semantic round-trip test from
    section 4.3.
13. Run the migration script against the repo's current
    `calibration.json` and commit the resulting v11 `calibration.json`
    + `limits/vendor/leica/navigator_expert/current.json` (and the
    deletion of `stage.json`) in the same PR
    so reviewers can see the actual data transformation. Git history
    on the migration commit IS the backup; no `.bak` files committed.

### PR #2 -- move calibration math to `shared/`

Tasks:

1. Move `calibration/vendor/leica/navigator_expert/core/model.py` ->
   `shared/calibration/model.py`.
2. `model.py` already lacks `default_path()` / `_calibration_root()`
   (dropped in PR #1).
3. Add `calibration_path()` and `limits_path()` helpers to
   `calibration/vendor/leica/navigator_expert/__init__.py`.
4. Update all imports in workflow code and tests.
5. Optional: split schema constants/validators into
   `shared/calibration/schema.py`.

Acceptance: same suite as PR #1.

### PR #3 (optional, later) -- limits schema extensions

Only when a real need surfaces. Don't speculate. Plausible additions
when the use case arrives:

- `per_objective_z_um` -- per-slot z-wide ceiling (40x oil tighter than 10x dry).
- `laser.max_intensity_global` / `laser.max_intensity_per_line`.
- `detector.max_gain`.
- `acquisition.max_frame_accumulation` / `max_z_stack_steps` / `max_scan_duration_s`.
- `motion.max_xy_step_um`.

Each new section needs driver-side enforcement at the relevant command
boundary (same shape as the existing stage-limit check).

---

## 6. Open questions for Codex

These are the decisions explicitly deferred to implementation:

1. **`microscope_agnostic_layer/DESIGN.md` alignment.** The agnostic-layer design was
   reviewed 2026-05-19 with 4 open decisions. Before starting PR #2 in
   particular, confirm none of those decisions conflict with the
   `shared/calibration/` layout proposed here. If the mid-layer plan
   already specs a calibration waist, prefer its names/paths over this
   plan's where they diverge.

2. **Older schemas in the wild.** This plan assumes v9 as the starting
   point. If any older `calibration.json` files exist anywhere in the
   lab (v6, v7, v8), confirm that the migration script's behavior on
   encountering them is acceptable. Recommend: fail loudly with a
   clear message ("schema vN not supported; manually upgrade to v9
   first or open an issue") rather than silently up-migrate.

3. **`stage.json` removal.** PR #1 deletes `stage.json` (git history
   is the backup; the migration is one commit, so `git revert`
   restores it). Don't commit a `.bak` fossil in the source tree.
   If you prefer a more conservative posture, keep `stage.json.bak`
   for one release as a local-only safety net (added to `.gitignore`,
   not committed), but the default plan is hard-delete in the
   migration commit.

4. **Backlash calibration notebook.** This plan reserves a
   `session_id` slot in the new `backlash` block but does not require
   a backlash notebook to exist. If/when one is added, the schema is
   ready. No action needed now beyond reserving the slot.

5. **`set_reference()` UX.** The math operation exists, but no
   user-facing surface invokes it. Recommend keeping it programmatic
   only for now; expose if/when an operator workflow needs to
   re-anchor.

6. **Notebook cell heading wording.** After rename, cells say "Adopt"
   instead of "Promote". Confirm this reads naturally to operators
   (the lab audience), not just technical readers.

---

## 7. Out of scope

- Time-series analysis or stability tracking (excluded by design
  philosophy -- those belong at a higher layer).
- LRP/pan/ROI calibration (unrelated subsystem).
- Pixel-size scaling calibration (constants in `driver/core/utils.py`;
  separate concern).
- `microscope_agnostic_layer/DESIGN.md` itself (that's the bigger vendor-neutral-waist
  plan; this refactor is one slice of it).

---

## 8. Definition of done

**PR #1 lands** ->

- Schema v11 in place.
- Single `calibration.json` (with backlash) at
  `calibration/vendor/leica/navigator_expert/current/calibration.json`.
- Clean `limits/vendor/leica/navigator_expert/current.json`.
- `limits/vendor/leica/navigator_expert/defaults.json` contains the configured
  physical microscope envelope.
- `migrate_current_calibration.py` is the only thing that writes the
  schema bump. `load_calibration()` raises on old schemas.
- `core/adopt.py` (renamed from `core/promotion.py`).
- The migration unit test pins the exact triples from section 4.2.
- The semantic round-trip test passes (last_updated allowed to differ).
- Backlash consumer audit complete: production callers explicitly pass
  `stage_cfg["backlash"]`; function defaults documented as fallbacks.
- All commands in section 4.3 return exit 0.

**PR #2 lands** -> `shared/calibration/model.py` is the canonical home
of translation math; vendor package exports `calibration_path()` /
`limits_path()`; workflow imports shortened. Same green suites.

**PR #3 (if it lands)** -> at least one new safety category in
the limits schema (probably per-objective z) actively prevents a real
misconfiguration the current global-only floor doesn't catch.
