# Calibration Unblock: Remove Redundant z-stack stepSize Check

## Status

Design plan. Not implemented yet.

This is a small, surgical unblock patch. It removes one defensive cross-check
in `common.py` that fires on LAS X metadata rounding and blocks valid
objective-pair calibration runs.

## Problem

Objective-pair Step 2 (`measure_parfocality_reference`) failed in
`read_stack_z_positions` with:

```text
RuntimeError: z-stack stepSize inconsistent with begin/end/sections
(stepSize=2.051, derived=2.05077). Re-check the LAS X stack configuration.
```

The discrepancy is `0.00023 um` over a `2 um` step. The current tolerance is
`1 ppm` (`max(1e-6, 1e-6 * max(abs(expected_step), 1.0))`). The difference is
~110x the tolerance.

This is not an operator misconfiguration. LAS X reports `stepSize = 2.051`
because its `stepSize` field is rounded to 4 significant figures. The derived
value `2.05077` is the more precise step from `(end - begin) / (sections - 1)`.
They disagree at the 4th decimal because of LAS X's own display precision.

The workflow already computes z positions via:

```python
positions = np.linspace(begin_f, end_f, sections_int)
```

so `begin`, `end`, and `sections` are authoritative. The `stepSize` field is
redundant. The cross-check protects against nothing real and trips on vendor
noise.

## Decision

Remove the check. Do not tune another tolerance.

Rationale: relaxing the tolerance would still encode an implementer guess about
LAS X precision. Each guess becomes a future failure mode the next time LAS X
firmware reports the field slightly differently. The check has no real failure
mode behind it; the downstream computation already trusts begin/end/sections.
Delete is the right intervention, not relax.

## Scope

Touch:

- `calibration/workflows/common.py`
  - `read_stack_z_positions` only
- `test/test_calibration_workflows.py`

Hands off:

- `calibration/workflows/objective_pair.py`
- `calibration/workflows/image_to_stage.py`
- `calibration/workflows/promotion.py`
- `calibration/notebooks/`
- every other helper in `common.py`

The image_to_stage workflow does not call `read_stack_z_positions`. PR 8 (the
in-flight D4 figure merge) does not touch this code path.

## Hard Rules

1. ASCII only.
2. Do not add a new tolerance constant.
3. Do not add a replacement check with looser bounds.
4. Do not change any other validation in `read_stack_z_positions`.
5. Do not touch objective-pair math, image-to-stage workflow, or PR 8 work.

## Authoritative Metadata

After this patch, the workflow trusts exactly these LAS X fields per stack:

- `begin` (first z-wide position)
- `end` (last z-wide position)
- `sections` (slice count)
- `zDrive` (must contain "wide")

`stepSize` is informational only and is not validated.

## Task 1: Remove the stepSize Block

In `calibration/workflows/common.py`, inside `read_stack_z_positions`, remove
the entire block that reads `stack.get("stepSize")`, computes
`expected_step` / `actual_step` / `tol`, and raises
`"z-stack stepSize inconsistent..."`.

Keep:

- required `begin` / `end` / `sections` validation
- `sections == expected_slices` validation
- `sections >= 3` validation
- `zDrive` / z-wide validation
- `positions = np.linspace(begin_f, end_f, sections_int)`
- the final `return [float(z) for z in positions]`

The function shape after the removal:

```python
begin_f = float(begin)
end_f = float(end)
positions = np.linspace(begin_f, end_f, sections_int)
return [float(z) for z in positions]
```

No `stepSize` reads anywhere in the function. No tolerance constant. No new
helper.

## Task 2: Tests

### Grep first

Run:

```text
grep -n "stepSize\|step_size" test/test_calibration_workflows.py
```

If a test asserts stepSize mismatch raises, either delete it (the failure mode
no longer exists) or convert it into the new regression test that asserts no
raise. Do not leave a test that asserts an exception we no longer raise.

### New regression test

Add:

```text
test_read_stack_z_positions_ignores_rounded_step_size
```

Setup:

- Call `read_stack_z_positions(client, job_name, expected_slices=40)` directly
  with mocked job metadata.
- Job metadata has `begin = 0.0`, `end = 79.98003`, `sections = 40`,
  `zDrive = "z-wide"`, `stepSize = 2.051`
- Derived step is `2.05077...`

Assertions:

- `read_stack_z_positions` returns a list of 40 floats
- First value equals `begin`
- Last value equals `end`
- No exception is raised

### Other existing tests must keep passing unchanged

Watch:

- `test_read_stack_z_positions_falls_back_on_partial_normalized`
- `test_objective_pair_missing_stack_positions_raises`
- `test_objective_pair_z_stack_requires_at_least_three_slices`
- `test_objective_pair_z_stack_override_requires_at_least_three`
- `test_objective_pair_descending_stack_fits_peak_correctly`
- `test_objective_pair_stack_geometry_mismatch_raises`
- every `test_image_to_stage_*`
- every `test_objective_pair_*`

## Cross-Notebook Safety

The image-to-stage workflow does not call `read_stack_z_positions`. The patch
should not affect it. Confirm by running the full test file, not just
objective-pair tests:

```text
cd Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\controller\vendor\leica\navigator_expert
& "C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\python.exe" -m pytest test\test_calibration_workflows.py
```

## Expected Test Count

Current PR 7 baseline: 63.

After this patch:

- If an existing test asserts stepSize mismatch raises and is removed: 63
  (deleted one, added one regression test).
- If no such test exists and only the regression test lands: 64.
- Any other count change needs investigation before reporting done.

## Acceptance Criteria

1. `read_stack_z_positions` no longer reads or validates `stepSize`.
2. The function still validates `begin`, `end`, `sections`, and `zDrive`.
3. The new regression test passes.
4. All `test_image_to_stage_*` and `test_objective_pair_*` tests still pass.
5. On the rig: objective-pair Step 2 proceeds past z-position parsing without
   raising the stepSize-inconsistency error.

## Pause and Ask

Pause before implementing if:

- The stepSize block is more than ~10 lines and removing it changes flow that
  the rest of the function relies on.
- An existing test asserts the stepSize raise but with a non-obvious data
  shape that suggests the test was protecting a real bug rather than the
  defensive check.
- Removing the check causes any other test to fail.

## Report Back

When done, report:

- files changed
- final pytest count
- confirmation that objective-pair Step 2 can proceed past z-position parsing
- any deviations from this plan

## Going Forward: Defensive Checks Discipline

This patch is one instance of a broader pattern: defensive checks added without
a real failure mode behind them. Three rules apply to every future check:

1. **Provenance comment required.** Each non-trivial check carries a one-line
   comment naming what it catches: an incident, a spec requirement, or a
   measured failure mode. If we cannot write that comment honestly, the check
   does not go in.

2. **Tolerance from measurement, not intuition.** If a check has a numeric
   tolerance, that number has a source: an incident, a vendor spec, or a
   measured noise floor. Implementer intuition is not a source.

3. **"What if X?" is not justification.** X must have happened, or be
   required by a spec. Speculative defense costs complexity, masks real bugs,
   and creates future failure modes of its own.

Existing checks worth re-examining under this rule (separate review, not this
patch):

- **Reflection guard in `image_to_stage.measure()`** -- added defensively for
  mirrored optics. Never observed on the rig. Candidate for removal if no
  reflection-best result appears in production over the next several runs.
- **`allow_nan=False` in `write_json_atomic`** -- redundant with the `_f()`
  coerce-to-None helper. Belt over already-fastened suspenders.
- **PNG save fail-loud `RuntimeError`** -- turns rare I/O hiccups into hard
  failures on a diagnostic artifact. Silent skip with a warning would suffice.
- **`_finite_pair` and `_fmt_xy` NaN guards in `plot_d4_candidates`** -- review
  after PR 8. Weak-vote diagnostics can still render a no-winner D4 grid, so
  these guards may be useful. Do not remove without checking the current display
  paths.
- **`D4_RESIDUAL_MAX = 0.3`** -- threshold from implementer intuition, not
  from measured rig noise. Has not fired in production yet. Calibrate from
  rig data once enough runs exist.
- **Stage backlash tolerance `20 um`** -- same. Source unknown; not calibrated
  from measurement.

These are review candidates, not action items. Address one at a time, with the
provenance question answered honestly each time.
