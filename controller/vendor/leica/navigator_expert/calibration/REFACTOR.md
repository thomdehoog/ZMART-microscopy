# Calibration module refactor plan

Working document. Six steps implemented, then a seventh round of
cleanup landed `2026-04-30` after a hardware ablation revealed the
two-component (motor + residual) model was structurally wrong.

**v5 → v6 schema break, 2026-04-30**

The old schema decomposed parcentric correction into `motor_um` (firmware
`get_xy` delta on switch) and `residual_um` (a derived value that
folded the firmware shift back in). The cookbook applied
`motor + residual`. Algebraically equal to the optical-center
difference `c1 − c2`, but each term carries its own measurement
noise, and Phase 4 measured the residual at `home + motor_delta`
instead of at `home`, which means the registration was contaminated
by whatever the firmware did on the switch.

**Hardware proved this.** Three cookbook runs with the v5 model gave
landing errors of 15.36, 16.70, 19.59 µm. After a direct one-shot
measurement (move stage back to anchor before tgt acquire), the true
`c1 − c2` was found to be `(-13.83, +15.49) µm`, while the v5 config
had stored `motor + residual = (-31.75, +8.95) µm` — wrong by 26 µm in
X. The v6 schema records the shift directly. **A v6 calibration on
the same rig immediately gave a 3.35 µm cookbook landing**, near the
system noise floor (Cellpose centroid jitter + stage motor accuracy +
backlash takeup + registration noise).

Schema v6, the only schema:

```json
"objectives": {
  "<slot>": {
    "parcentric_xy": {
      "shift_um":  [-13.83, +15.49],   // registration with stage at home
                                       // both times — what cookbook applies
      "offset_um": [-7.02, +21.07]     // firmware get_xy delta — diagnostic
    },
    "parfocal_z": {
      "shift_um":  -3.0,               // focal-plane diff (Brenner)
      "offset_um": null                // not currently measured
    }
  }
}
```

Phase 5 (verification) was also dropped. Its residual was bounded
below by stage motor accuracy + settle + backlash + registration
noise, all of which are present during Phase 4 too — so it could
never tell you whether the calibration was right, only the rig's
noise floor. The cookbook landing test (different cell, different
stage XY, end-to-end) is the honest validation.

Phase 4 iteration (`--max-iterations`, `--xy-residual-threshold-um`)
also gone. Iteration was a workaround for the v5 model's
self-consistency loop; with v6's direct measurement, a single shot
is the answer.

The earlier "all six are implemented" status follows below for
historical reference. The current state is: schema v6, single-shot
parcentric shift via registration with stage parked at anchor, plus
optional parfocal Z, plus diagnostic offsets recorded. Old v5 configs
must be regenerated — there is no migration.

---

Working document. Six steps; **all six are implemented.**

Status:
- Step 1 (sign-bug fix): hardware-validated, run `20260429_213855` →
  `20260429_222430` showed verification residual `(+4.84, -10.00) → (-0.40, +0.00) µm`.
- Step 2 (parfocal opt-in): passed dry slot-2 hardware run.
- Step 3 (kill legacy shim): backlash cookbook smoke landed 12.96 µm.
- Step 4 (iterative XY): passed dry slot-2 iterative hardware validation,
  run `20260429_233109`.
- Step 5 (NaN-safe quality): in.
- Step 6 (file split): done. Three lib modules:
  - `lib/registration.py` — pure image-processing helpers (`register_phase`,
    `register_voting`, `_method_*`, `brenner_*`, `classify_d4`,
    `to_uint8`, `finite_*`).
  - `lib/lasx_state.py` — hardware glue (`reset_pan_roi_zstack`,
    `configure_z_stack`, `disable_z_stack`, `setup_reference_state`,
    `switch_to_target`, `make_acquirer`, `apply_stage_limits`,
    `apply_scan_format_and_speed`, `reselect_job`).
  - `lib/phases.py` — phase functions, each takes client + state and
    returns the value(s) the orchestrator persists plus a report
    fragment: `measure_sign_convention`, `measure_motor_delta`,
    `measure_parfocal`, `measure_xy_residual`, `verify_target`. Plus
    `_move_and_verify` (used only by sign convention).

  The orchestrator (`scripts/calibrate_objectives.py`, 421 lines) is
  CLI + setup + restore + persist. The per-target body reads like the
  docstring's phase list. Sizes: orchestrator 421, phases 412,
  registration 224, lasx_state 189.

Post-Step-6 follow-up fixes landed `2026-04-30`:
- Mojibake recovered in `calibrate_objectives.py` (cp1252-via-UTF8
  double-encoding from earlier patch passes; 178 chars cleaned, BOM
  stripped, line endings normalized).
- Sign-convention prose in `lib/registration.py` corrected: the comment
  said "ref features at +x/+y relative to tgt" but the code (and the
  regression test in `test_calibrate_objectives_registration.py`) returns
  the opposite. Now consistent.
- Iter-1-below-threshold bug in Phase 4 fixed: persisted `[0, 0]`
  instead of the actual measurement when iter1 was sub-threshold. Now
  always persists the measurement; threshold only governs iteration
  stop.
- `lib/lasx_state.py` logger changed from `getLogger("calibrate_objectives")`
  to `getLogger(__name__)` — a library module shouldn't claim a script
  logger name.
- Voting-fail mid-iteration now appends a stub iteration record so the
  report shows the failed attempt rather than a hidden break.
- Phase-4 report shape: ambiguous `image_xy.stage_dx_um` (which was
  written twice — first iter1's value, then overwritten with cumulative)
  renamed to `applied_stage_dx_um` / `applied_stage_dy_um` so iter1's
  per-method record in `iterations[0]` stays the source of truth for
  that iteration's measurement.

## Codex review notes

I would implement this, but only as staged changes. The direction is
right; the risk is treating this document as already authoritative.

- Keep the hardware facts precise. Slot 0 is the 40x/1.10 WATER
  objective in the current scope, not 40x/0.60.
- Do not commit live calibration numbers as durable truth. They are
  useful run evidence, but the source of truth is the generated
  `calibration/config/config.json` for the active machine state and the
  per-run reports under `calibration/runs/`.
- Keep the sign language explicit. `parcentric_xy.motor_um` is the
  objective-switch readback delta; `parcentric_xy.residual_um` is the
  stage correction after applying `image_to_stage`; the consumer-facing
  delta is currently `motor + residual` because Step 1 fixed the
  residual sign at the registration boundary.
- Do not delete the legacy shim before at least one cookbook consumer is
  migrated and smoke-tested against the canonical config. The shim is
  ugly, but it is still the path existing scripts use today.
- Replace the proposed `np.roll` regression with a zero-padded synthetic
  image shift. `np.roll` wraps content across the image border and can
  hide convention bugs that a microscope image would expose.
- Treat the 4.80 um cookbook landing result as evidence that the sign
  fix helped, not proof of a specific remaining error source. Single-cell
  Cellpose centroid noise, focus, backlash, and anchor position are all
  still plausible contributors.

## Cold-start context

### Repo + branch

- Path: `Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\controller`
- Branch: `refactor`
- No GitHub remote — no PRs, no force-push concerns. All commits stay
  local until the user pushes.

### Hardware slot layout (this scope)

| Slot | Objective | Notes |
|---|---|---|
| 0 | HC PL APO CS2 40x/1.10 WATER | **Run last and in a separate session.** Once water is on the coverslip, switching back to a dry objective drags it through residue. |
| 1 | HC PL APO CS2 10×/0.40 DRY | **Reference slot** for calibration. |
| 2 | HC PL APO CS2 20×/0.75 DRY | **Parfocal in practice** with slot 1 (dZ ≈ 0; measured 3 µm is Brenner-peak noise). Not parcentric — needs XY calibration. |

### Pre-run preconditions

Before invoking `calibrate_objectives.py`:

- LAS X open with `Overview` job currently selected.
- `ImageTransformation = TOPLEFT` (LAS X Advanced Settings).
- AFC / autofocus off; no LAS X modal dialogs open.
- Stage parked over a region with **dense, distinct texture** (multiple
  features visible at zoom 1.0 on the reference). Sparse fields kill
  phase correlation.
- The stage's current XY position becomes the calibration *anchor* —
  the script reads it via `drv.get_xy()` at start and uses it as the
  origin for sign-phase test moves and per-target measurements. Move
  the stage *before* invoking, not after.
- For cookbook smoke after Step 3: Cellpose installed (`pip install
  cellpose`), GPU available preferred but not required, the same job
  selected as was used during calibration.

### Memory files this work depends on

These live under `~/.claude/projects/.../memory/` and contain context
the user has flagged as load-bearing for calibration work:

- `project_calibration_script.md` — slot assignments, phase descriptions
- `project_calibration_zoom_floor.md` — `--ref-zoom × ref_mag ≥ 0.75 × max(tgt_mag)` rule
- `project_objectives_parfocal_not_parcentric.md` — slot 1/2 are parfocal in practice
- `project_calibration_open_residual.md` — sign-bug history (now resolved by Step 1)
- `feedback_no_calibration_values.md` — never memorize parfocal/parcentric numbers; re-run
- `feedback_idle_check_before_acquire.md`, `feedback_modal_dialogs_block_api.md` — API gotchas
- `feedback_voting_registration.md` + `reference_registration_benchmark.md` — origin of voting

Read MEMORY.md first; it's a thin index pointing at these.

### Cookbook job-name gotcha

The example in `examples/motorized_stage/single_target_stage_one_shot_backlash_correction.py`'s
docstring says `--job HiRes`, but the cookbook must use the **same job
that was calibrated against**. Today we calibrate against `Overview`,
so cookbook tests use `--job Overview`. The shim doesn't enforce
this; mismatch produces silent garbage.

## Why this refactor

After fixing the sign-bug in voting registration (commit `0be1e98`), the
calibration script works correctly but has a pile of issues that argue
against patching further on the existing structure:

- The sign-bug existed at the seam between `register_voting`'s output and
  the `image_to_stage` matrix from sign-phase. The two layers were
  developed against subtly different conventions, and the conversion
  between `motor`/`residual` (in the canonical config) and the legacy
  shim's `motor_delta_um = motor + residual` was where the sign error
  silently compounded.
- The `--measure-xy requires --measure-parfocal` constraint is wrong for
  hardware where the objectives are parfocal in practice. The script
  currently wastes ~3 min/target on Z-stacks to discover dZ ≈ 0, and
  applies a spurious −3 µm Z offset to the residual + verification
  acquires, which can introduce small lateral shift via aberration on
  tilted/thick samples.
- Dual config files (`config.json` canonical + `objective_offsets.json`
  legacy shim) need to stay in sync. They didn't, hence the sign-bug.
- The XY residual is single-pass; one bad measurement gives a permanent
  ~10 µm offset until re-cal.
- `register_voting` reports `quality=NaN` because `np.median([NaN, ...])`
  returns NaN.
- The script is ~1000 lines and crams helpers + phase code + orchestrator
  into one file.

## Architectural decisions

### A1. Where the sign convention is enforced
**Done in Step 1.** The four `_method_*` voting helpers now negate `dx`,
`dy` to match `register_phase`'s convention (negated PCC), which is
what the `image_to_stage` matrix from sign-phase was fitted against.

A comment block above the methods documents this. The Step 6 split will
move these into `lib/registration.py` so a unit test can pin the
convention against a synthetic shift — exactly the test that would have
caught the original bug.

### A2. Dual-config policy
**Kill the legacy shim.** Migrate cookbook scripts to read `config.json`
directly via a small consumer helper. Trade-offs:

| Option | Cost | Benefit |
|---|---|---|
| Keep shim, dedupe its writer | low diff | dual sources of truth remain; same failure mode possible |
| Generate shim deterministically with a tested helper | medium diff | testable, but still two files |
| **Kill shim, migrate consumers** | medium diff (1–3 lines per cookbook script) | one source of truth; consumers get parfocal Z for free |

Picked the third: the branch is `refactor`, no PR overhead, one-time
churn buys long-term simplicity. The replacement is:

```python
from navigator_expert.driver import calibration as cal

cfg = cal.load_calibration()
dx, dy = cal.get_parcentric_total_um(cfg, slot=2)   # = motor + residual
dz = cal.get_parfocal_total_um(cfg, slot=2)         # = motor (residual is diagnostic)
M  = cal.get_image_to_stage(cfg)
```

The accessor *computes* totals on read — does not store derived data,
which would invite drift.

### A3. Parfocal becomes opt-in
- Drop the `--measure-xy requires --measure-parfocal` enforcement.
- When `--measure-parfocal` is off but `--measure-xy` is on: acquire
  residual frame at `z-galvo = 0`; set `dz_um = 0` so verification math
  stays consistent.
- Operator who knows their objectives are parfocal saves ~3 min/target
  and avoids the spurious −3 µm Z aberration shift.
- Operator who doesn't know: pass `--measure-parfocal` once, observe
  `parfocal.residual_um < 1 µm`, drop the flag for subsequent runs.

### A4. Iterative XY refinement
- New flag `--max-iterations N` (default 1, preserves current behavior).
- New flag `--xy-residual-threshold-um T` (default 0.5).
- Loop: measure residual → update applied offset → re-acquire at new
  corrected position → re-measure → stop when `|residual| < T` or `N`
  exhausted.
- Persist the *final* (cumulative) residual to `config.json`; persist
  the per-iteration trajectory in the run report.

### A5. Module structure
The current ~1000-line script splits into:

```
calibration/
├── lib/
│   ├── registration.py    # pure functions, unit-testable
│   │                      #   register_phase, register_voting,
│   │                      #   _method_phase/_masked/_cv2_ncc/_orb,
│   │                      #   to_uint8, classify_d4, brenner,
│   │                      #   subpixel_peak, brenner_focus
│   ├── lasx_state.py      # hardware glue, isolated
│   │                      #   setup_reference_state, switch_to_target,
│   │                      #   reselect_job, apply_scan_format_and_speed,
│   │                      #   reset_pan_roi_zstack, configure_z_stack,
│   │                      #   disable_z_stack, make_acquirer,
│   │                      #   apply_stage_limits, _move_and_verify
│   └── phases.py          # phase functions, each takes a client +
│                          # state and returns (result, target_update)
│                          #   measure_sign_convention,
│                          #   measure_motor_delta,
│                          #   measure_parfocal,
│                          #   measure_xy_residual (with iteration loop),
│                          #   verify_target
├── scripts/
│   └── calibrate_objectives.py   # ~250-line orchestrator: CLI,
│                                 # phase ordering, persistence, logging
├── config/
│   ├── config.json        # canonical state (auto-written)
│   └── stage.json         # hand-edited (read-only from script)
├── runs/                  # per-run snapshots (gitignored)
└── REFACTOR.md            # this file
```

And new in `driver/`:

```
driver/
└── calibration.py         # consumer-facing accessors
                           #   load_calibration, get_parcentric_total_um,
                           #   get_parfocal_total_um, get_image_to_stage,
                           #   translate_stage_xy_between_objectives,
                           #   pixel_to_stage_xy_um (rewritten against
                           #     schema v5)
```

This is *not* a rewrite — `git mv`-style splits plus the targeted
bug fixes from Steps 2–4. Behavior is identical after Step 6.

## Implementation order

Each step is independently testable and committable.

### Step 1 — Fix the sign bug ✅ DONE (commit `0be1e98`)

Negation in four `_method_*`. Verification residual went from
`(+4.84, −10.00) µm → (−0.40, +0.00) µm`. Cookbook landing error
went from `19.68 µm → 4.80 µm` (4× improvement). Schema unchanged.

### Step 2 — Drop parfocal requirement for `--measure-xy` — DONE

**Files:** `calibrate_objectives.py` (CLI guard, ref-focus acquire,
target-focus acquire); `README.md` (remove the requires row, note that
parfocal is opt-in).

**Change:**
- Remove the `if args.measure_xy and not args.measure_parfocal: error`
  guard.
- When `--measure-parfocal` off & `--measure-xy` on: skip Z-stacks;
  acquire `img_ref_focus` and `img_tgt_focus` at `z-galvo = 0`;
  set `dz_um = 0`.

**Test:** run `--measure-xy --verify` (without parfocal) on slot 2.
Expect ~3 min runtime instead of ~6, residual quality ≥ current run.

### Step 3 — Kill the legacy shim, migrate consumers — DONE

**New file:** `driver/calibration.py` (helpers in A2). Add unit tests:
- `get_parcentric_total_um` — motor present, residual null, residual
  present.
- `translate_stage_xy_between_objectives` — ref↔target symmetry.
- `get_image_to_stage` — returns `np.ndarray`, validates shape.

**Edit:** `driver/__init__.py` — re-export new helpers, deprecate the
`load_objective_offsets` re-export.

**Edit cookbook scripts** under `examples/motorized_stage/` and any
other consumer:
- `single_target_stage_one_shot_backlash_correction.py`
- `single_target_stage_one_shot.py`
- `single_target_stage_iterative.py`
- `single_target_stage_iterative_backlash_correction.py`

Per script: 1–3 lines (replace `load_objective_offsets()` →
`load_calibration()`; replace `cfg["offsets"][slot]["motor_delta_um"]`
access pattern → `get_parcentric_total_um(cfg, slot)`).

**Delete:** `_write_legacy_compat` in `calibrate_objectives.py`,
the `legacy_paths` print block, and `vendor/leica/config/objective_offsets.json`.

**Keep** `driver/objective_offsets.py` for the metadata helpers
(`objective_by_slot`, `objective_summary`, `validate_slots`) which the
calibration script still uses; just remove the persistence/translate
functions tied to the old schema.

**Test:** rerun `single_target_stage_one_shot_backlash_correction.py`.
Landing error must stay < 10 µm (proves new consumer path matches).

**Observed:** migrated backlash cookbook completed using
`drv.load_calibration()`; landing error was 12.96 µm. That is above the
strict <10 µm target but below the off-anchor <20 µm smoke threshold.

### Step 4 — Iterative XY refinement

**Files:** `calibrate_objectives.py` (after Step 6, this lives in
`lib/phases.py:measure_xy_residual`).

**Status:** DONE. Dry slot-2 run `20260429_233109` stopped by threshold
after iteration 2. Iteration 1 applied `(-24.731, -12.121) um`; iteration
2 measured only `0.330 um` residual and was recorded as `applied: false`.
Verification residual was `(-0.040, -0.092) um` image-frame with 4/4
method agreement.

**Change:**
- Add `--max-iterations` (default 1) and `--xy-residual-threshold-um`
  (default 0.5).
- Loop in phase 4: measure → apply (`accumulated += residual_stage`) →
  move stage to `home + motor + accumulated` → re-acquire → re-measure.
  Stop when `|residual_stage| < threshold` or iterations exhausted.
- Save *final cumulative* residual to `config.json`.
- Save iteration trajectory to `report.json`:
  `per_target.<slot>.image_xy.iterations = [{i, residual_image, residual_stage, accumulated_stage, voting}, …]`.

**Note on anchor stability.** The "home" position above is the
calibration anchor — `home_xy = drv.get_xy(client)` captured at the
top of `main()`. Within one run this is fixed; across runs it depends
where the operator parked the stage. Iterative refinement converges
*at this anchor*; off-anchor targeting (e.g. cookbook landing) still
needs repeated measurement before assigning a cause. Parcentric error
may be spatially non-uniform, but Cellpose centroid noise, focus,
backlash, and sample drift are also plausible.

**Test:** run with `--max-iterations 3` on slot 2. After Step 1 the
first iteration should already be near-converged; iteration 2 reports
tiny additional correction; loop terminates early via threshold.

### Step 5 — Cosmetic: NaN-safe quality — DONE

**File:** `calibrate_objectives.py:register_voting` (Step 6: moves to
`lib/registration.py`).

**Change:** filter NaN qualities before `np.median`, or use
`np.nanmedian`. Defensive on `q=NaN` from `phase_cross_correlation`'s
error field.

**Test:** every voting run; aggregate `quality` is finite and per-method
non-finite diagnostics are serialized as `null`, not JSON `NaN`.

### Step 6 — File split

DONE for the high-risk helpers. No behavior changes intended.

**Implemented:**
- `calibration/lib/registration.py`: registration methods, voting,
  Brenner focus, D4 classification.
- `calibration/lib/lasx_state.py`: LAS X setup, Z-stack setup, job
  reselection, scan format/speed pinning, backlash-wrapped acquisition,
  stage-limit application.
- `calibrate_objectives.py`: remains the CLI/orchestrator plus phase-1
  sign measurement and the per-target phase ordering.

**Checked:** py_compile for script + new modules; CLI `--help`; focused
pytest `test_calibration_consumer.py` and
`test_calibrate_objectives_registration.py` (`6 passed`).

**Procedure:**
1. Create `lib/__init__.py`, `lib/registration.py`, `lib/lasx_state.py`,
   `lib/phases.py`.
2. `git mv` the relevant function bodies into the new files; fix imports.
3. Slim the orchestrator: it should read like the docstring's phase
   list — `setup_reference()` → `for ts in target_slots: switch();
   measure_motor(); maybe_measure_parfocal(); maybe_measure_xy();
   maybe_verify();` → `restore() + persist()`.
4. Add unit tests in `tests/calibration/registration/` — see the
   "Sign-convention regression test" subsection below.

#### Sign-convention regression test

The convention `register_voting` and the four `_method_*` helpers must
return is: **positive `dx_um, dy_um` mean ref features are at +x/+y
relative to tgt features** — i.e. PCC shift NEGATED. The
`image_to_stage` matrix from sign-phase is fitted under this same
convention; mismatching causes the Step-1 bug to recur.

A failing-test-first version (in pytest):

```python
import numpy as np
from navigator_expert.calibration.lib.registration import register_voting

def _make_pair(shift_px=(5, 3), size=256, seed=42):
    """Create a synthetic ref/tgt pair where tgt = np.roll(ref, shift).

    Convention: shift_px = (rows, cols) in numpy frame.
      shift > 0 means tgt features are at +y/+x relative to ref features
      (i.e., ref features are at -y/-x relative to tgt).
    """
    rng = np.random.default_rng(seed)
    ref = rng.integers(0, 65535, size=(size, size), dtype=np.uint16)
    # Smooth so PCC has features to lock onto:
    from scipy.ndimage import gaussian_filter
    ref = gaussian_filter(ref.astype(np.float64), sigma=2)
    tgt = np.roll(ref, shift_px, axis=(0, 1))
    return ref, tgt

def test_voting_returns_negated_shift():
    """If tgt = np.roll(ref, +5y +3x), ref features are at -3x, -5y
    relative to tgt features. The convention says positive dx_um, dy_um
    encode 'ref relative to tgt', so we expect (dx_um, dy_um) = (-3, -5)
    pixel-for-pixel.
    """
    pixel_um = 1.0
    ref, tgt = _make_pair(shift_px=(5, 3))  # row shift = 5, col shift = 3
    vote = register_voting(ref, tgt, pixel_um)
    assert vote["trusted"], f"voting did not converge: {vote['per_method']}"
    # Pixel-for-pixel: dx (cols) = -3, dy (rows) = -5
    assert abs(vote["dx_um"] - (-3.0)) < 0.5, vote
    assert abs(vote["dy_um"] - (-5.0)) < 0.5, vote
```

This test would have caught the Step-1 bug: pre-fix,
`vote["dx_um"]` was `+3.0` (un-negated PCC shift), test fails.
Post-fix, `vote["dx_um"]` is `-3.0`, test passes.

Also add convention assertions for each method individually so a
future contributor flipping one method gets a localized failure rather
than a quietly-bad voting result:

```python
import pytest
from navigator_expert.calibration.lib.registration import (
    _method_phase, _method_masked, _method_cv2_ncc, _method_orb,
)

@pytest.mark.parametrize("method", [_method_phase, _method_masked, _method_cv2_ncc, _method_orb])
def test_method_sign_convention(method):
    ref, tgt = _make_pair(shift_px=(5, 3))
    dx, dy, _ = method(ref, tgt, pixel_um=1.0, _mask_pct=30)
    assert abs(dx - (-3.0)) < 0.5, f"{method.__name__}: dx={dx}"
    assert abs(dy - (-5.0)) < 0.5, f"{method.__name__}: dy={dy}"
```

**Test:** end-to-end calibration output should be byte-identical to
Step 5's output (modulo timestamps).

## Test plan

### End-to-end (canonical, on hardware — ~3–6 min)

```
python navigator_expert/calibration/scripts/calibrate_objectives.py \
    --job Overview --target-slots 2 \
    --ref-zoom 3.0 --measure-xy --verify
```

Pass criteria:
- sign-phase `residual_from_d4 < 0.3` (unchanged)
- phase-4 verification residual within ±1 µm per axis
- cookbook landing error < 10 µm (proves consumer math is correct
  end-to-end)

### Unit tests (new, no hardware)

`tests/calibration/registration/`:
- `register_voting` on a synthetic ref/tgt pair with a known shift
  (e.g. `np.roll`): all four methods return values within tolerance,
  voting consensus matches the input shift in the documented sign
  convention. **Pins the sign convention against regression.**
- `classify_d4` on identity / 90°-rotation / reflection inputs.
- `brenner_focus` on a synthetic Gaussian-blur stack, peak at known
  slice.

`tests/driver/calibration/`:
- `get_parcentric_total_um` — motor present, residual null, residual
  present.
- `translate_stage_xy_between_objectives` — ref↔target symmetry.

### Cookbook smoke (after Step 3)

```
python navigator_expert/examples/motorized_stage/single_target_stage_one_shot_backlash_correction.py \
    --job Overview --source-slot 1 --target-slot 2
```

Landing error < 10 µm (anchor field) or < 20 µm (off-anchor field).

## Out of scope

- Cellpose-based picking improvements
- Galvo-pan calibration
- Stage-limits source/management
- Schema migration to v6 (current schema is fine; just compute totals
  on read)
- Replacing the voting algorithm itself
- Iterating sign-phase or parfocal Z (single-pass is fine for those)

## Open questions

- **Should `runs/` and `cookbook/` be gitignored?** Currently neither is
  in `.gitignore` and there is no `.gitignore` at the repo root. The
  refactor is a good moment to add one. Per-run output is operational
  log, not source.
- **Should `config.json` be tracked or gitignored?** Currently
  untracked. Tracked = canonical machine-state under version control,
  drifts every calibration run; gitignored = treated as machine-local
  state, requires fresh calibration per checkout. Suggest tracked, with
  a note in `README.md` that it's regenerated by the calibration
  script.

## History

| Date | Event |
|---|---|
| 2026-04-29 | Step 1 sign-bug fix landed (`0be1e98`). Plan drafted. |

---

## Appendix A — What the Step-1 bug was, and how it was diagnosed

This section preserves the empirical reasoning behind Step 1's fix so
that anyone touching `register_voting` later understands what the
regression test (Step 6) is guarding against, and why.

### The setup

Phase 4 of the calibration script does:

1. Acquire `img_ref_focus` on slot 1 (reference) at the calibration
   anchor.
2. Switch to slot 2 (target). Firmware applies its parcentric
   correction — the stage auto-moves by `motor_delta = c1 − c2 + ε`,
   where `c1`, `c2` are the optical-center offsets of each objective
   and `ε` is the firmware's residual error.
3. Acquire `img_tgt_focus` at the post-firmware position
   (`anchor + motor_delta`).
4. Register `img_ref_focus` vs `img_tgt_focus` to recover `ε` in
   image-space → convert to stage frame via `image_to_stage` →
   save as `parcentric_xy.residual_um`.

### What the right answer is

To put a sample point `P` at the optical center on slot 2, the stage
must be at `P − c2`. Starting from a position where `P` was at the
optical center on slot 1 (`stage = P − c1`), then switching to slot 2:

```
target_stage_slot2 = source_target_slot1 + (c1 − c2)
                   = source_target_slot1 + (motor_delta − ε)
```

So the cookbook should add `motor_delta − ε` as the offset, not
`motor_delta + ε`.

### What the bug was

The voting helpers (`_method_phase`, `_method_masked`, `_method_cv2_ncc`,
`_method_orb`) returned PCC-style shifts un-negated, while `register_phase`
(used in sign-phase) returned them negated. The `image_to_stage` matrix
was fitted against `register_phase`'s convention, so applying the matrix
to the un-negated voting output produced `−ε` where `+ε` was expected.

The script then saved `+ε` (sign-flipped) as `parcentric_xy.residual_um`,
and the legacy shim writer composed `motor_delta_um = motor + residual`,
which is `motor_delta + ε` — the wrong direction.

### How we proved it

Verification phase moves to `home + motor + saved_residual`. Under the
bug, that's `home + motor + ε`. The optical center on slot 2 is now
imaging:

```
sample_at_center = stage + c2
                 = home + motor + ε + c2
                 = home + (c1 − c2 + ε) + ε + c2
                 = home + c1 + 2ε
```

The reference slot-1 image at `home` shows `home + c1`. So the verification
image differs from the reference by **2ε** in sample/image frame.

Empirically (run `20260429_213855`):

| Axis | Original residual `ε` (image) | Verification residual (image) | Ratio |
|---|---|---|---|
| dx | +2.37 | +4.84 | **2.04×** |
| dy | −4.92 | −10.00 | **2.03×** |

Within 2% of the predicted 2.00× in both axes — strong proof the bug
was a pure sign flip, not a measurement-noise issue.

### The fix and what it achieved

Step 1 (`0be1e98`) negates `dx_um, dy_um` in each `_method_*`. After the
fix, the same end-to-end run produced:

| Metric | Pre-fix | Post-fix |
|---|---|---|
| Verification residual (image) | (+4.84, −10.00) µm | **(−0.40, +0.00) µm** |
| Cookbook landing error | 19.68 µm | **4.80 µm** |

The remaining 4.80 µm is a single cookbook smoke result. It is evidence
that the sign fix helped, but it does not prove the remaining error
source.

---

## Appendix B — Schema snippets

### `navigator_expert/calibration/config/config.json` (canonical, v5)

```json
{
  "schema_version": 5,
  "last_updated": "20260429_222430",
  "reference_objective_slot": 1,
  "image_to_stage": [[0.0, -1.0], [1.0, 0.0]],
  "objectives": {
    "1": {
      "is_reference": true,
      "anchor_xy_um": [32213.286, 28473.101],
      "calibrated_at": "20260429_213855",
      "name": "HC PL APO CS2    10x/0.40 DRY",
      "magnification": 10.0,
      "numerical_aperture": 0.4,
      "objective_number": 11506424,
      "immersion": "DRY"
    },
    "2": {
      "calibrated_at": "20260429_222430",
      "name": "HC PL APO CS2    20x/0.75 DRY",
      "magnification": 20.0,
      "numerical_aperture": 0.75,
      "objective_number": 11506517,
      "immersion": "DRY",
      "parcentric_xy": {
        "motor_um":    [-7.021, +21.074],
        "residual_um": [+4.924,  +2.374]
      },
      "parfocal_z": {
        "motor_um":    -2.987,
        "residual_um": +0.158
      }
    }
  }
}
```

Cookbook needs `motor + residual` for parcentric XY, i.e.
`(-2.097, +23.448)`. After Step 3, `cal.get_parcentric_total_um(cfg, 2)`
returns this directly.

### `vendor/leica/config/objective_offsets.json` (legacy shim, v3)

To be **deleted** in Step 3. Recorded here for migration reference:

```json
{
  "schema_version": 3,
  "timestamp": "20260429_222430",
  "method": "calibrate_objectives_compat",
  "coordinate_policy": "targets_in_reference_frame; switch_at_target; motor_delta_is_readback_only",
  "job": "Overview",
  "reference_slot": 1,
  "reference_objective": { /* same shape as canonical's objective entry */ },
  "sign_convention": {
    "image_to_stage_um": [[0.0, -1.0], [1.0, 0.0]]
  },
  "settle_s": 3.0,
  "offsets": {
    "2": {
      "target_slot": 2,
      "target_objective": { /* same shape */ },
      "motor_delta_um": [-2.097, +23.448],   /* <-- = motor + residual */
      "reference_xy_um": [32213.286, 28473.101],
      "target_xy_um":    [32211.189, 28496.548]
    }
  }
}
```

Consumer access pattern (today, to be replaced):

```python
cfg = drv.load_objective_offsets()
dx, dy = cfg["offsets"][str(slot)]["motor_delta_um"]
```

After Step 3:

```python
from navigator_expert.driver import calibration as cal
cfg = cal.load_calibration()
dx, dy = cal.get_parcentric_total_um(cfg, slot)
```

---

## Appendix C — Reference files (for grep-targets)

| File | Why a fresh session may need it |
|---|---|
| `navigator_expert/calibration/scripts/calibrate_objectives.py` | The orchestrator; everything Steps 2–6 touch |
| `navigator_expert/calibration/README.md` | Pre-run guide; Step 2 updates the troubleshooting row |
| `navigator_expert/driver/machine_config.py` | Persistence layer (`load_machine_config`, `update_target`, `save_calibration_report`, `make_run_dir`, `MACHINE_SCHEMA_VERSION`) |
| `navigator_expert/driver/objective_offsets.py` | Legacy `load_objective_offsets`; metadata helpers (`objective_by_slot`, `validate_slots`) we keep |
| `navigator_expert/driver/__init__.py` | Re-exports — Step 3 swaps the public API surface |
| `navigator_expert/test/test_registration_benchmark.py` (lines ~194–268) | Where the four registration methods originated |
| `navigator_expert/examples/motorized_stage/*.py` | Cookbook consumers Step 3 must migrate (4 scripts) |
| `vendor/leica/config/cookbook/motorized_stage/<ts>_backlash_correction/summary.json` | Where landing-error numbers from cookbook smoke runs land |
