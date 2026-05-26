# Calibration Notebooks Plan: Claude vs Codex

Compares `CALIBRATION_NOTEBOOKS_PLAN_claude.md` against `CALIBRATION_NOTEBOOKS_PLAN_codex.md`. Both are implementation-grade specs for the same design. They agree on the architecture; they differ on detail. This doc lists the convergences, the divergences, and which side to take in each disagreement.

---

## TL;DR

- **Architecture and gating are identical.** 5-cell objective notebook, 3-cell image-to-stage notebook, `current_config/` as the only live folder, campaign-style session layout, strict promotion gate (weak vote = no staging config), D4 residual raise, explicit promotion call.
- **Codex is more concrete about existing APIs and edge cases.** It names exact driver signatures, adds move/geometry verification, handles non-square pixels, slugifies objective names, and accounts for the high-to-low Z stack ordering in `configure_z_stack`. These are real bug-prevention measures and should be adopted.
- **Claude has better cross-cutting structure.** Explicit units table, glossary, and diff-against-shared-plan section. These should be carried forward.
- **One open verification.** Codex claims `register_voting(ref, tgt, pixel_um)` already returns image-um. If true (likely; check the algorithms module), drop Claude's px-to-um wrapper. If false, keep it.
- **Net: take Codex's body, layer Claude's organizational sections on top.**

---

## Convergences

Both plans agree on:

1. **Conceptual model.** `P_target = P_ref + translation`; `translation = motor_shift + correction`.
2. **Operator vs notebook split.** Operator owns LAS X; notebook does stage motion, acquisition, registration, analysis, save.
3. **Two notebooks, thin.** One function call per code cell. Workflow modules do the work.
4. **5-cell objective-pair notebook.** Config + Parfocality ref + Parfocality target + Parcentricity ref + Parcentricity target. Operator switches three times.
5. **3-cell image-to-stage notebook.** Config + Measure + Visualize/Save. Optional fourth cell for promotion.
6. **File layout.** `current_config/` for live, `sessions/<id>/configs|reports|notebooks|data/<kind>/` for staging.
7. **Production reads only `translation_*` and `image_to_stage`.** Diagnostics live in reports.
8. **Strict gating.** Weak voting -> report is saved; promotable config is NOT. Promotion later raises FileNotFoundError.
9. **D4 residual raise.** Above `D4_RESIDUAL_MAX`, the sign fit is rejected.
10. **`image_to_stage` is dimensionless** (image-um -> stage-um), a D4 rotation/reflection.
11. **Z-wide is the Z axis; z-galvo held at 0.** Brenner peak in a z-wide stack.
12. **No silent rescaling.** Pixel size and image size mismatch is a hard error in v1.
13. **No new `calibration/lib/registration.py`.** Reuse `navigator_expert.algorithms`.
14. **Promotion is explicit.** Separate notebook cell calling `promotion.promote_calibration(...)`; archives old live, logs to `.promotion.log`.
15. **Reference-objective focus is the anchor.** No ref-Brenner subtraction.

These do not need further debate.

---

## Divergences

For each, the recommendation column gives the side to take, with a one-line reason. "Verify" means the choice depends on a fact about the existing code that should be checked first.

| # | Topic | Claude | Codex | Best | Why |
| --- | --- | --- | --- | --- | --- |
| 1 | Registration return value | wrapper: px * pixel_size_um -> image-um | `register_voting(ref, tgt, pixel_um)` already returns `dx_um`, `dy_um` | **Verify and adopt Codex if true** | If the existing API returns um, the wrapper is dead weight. If it returns px, keep the wrapper but flag the asymmetry. |
| 2 | Pixel geometry | flat `pixel_size_um: float`, `image_size_px: tuple` | `ImageGeometry` dataclass with `pixel_w_um`, `pixel_h_um`, `pixel_size_um` (derived, raises if non-square) | **Codex** | Leica geometry actually has W/H separately. Codex's structure surfaces non-square pixels at the boundary instead of silently averaging. |
| 3 | Move verification | `drv.move_xy_stage(...)` directly | `move_xy_and_verify` / `move_zwide_and_verify` -- check result success + readback within tolerance | **Codex** | Real moves can fail silently or partially. Verification at the workflow layer is production-grade. |
| 4 | Acquisition wrappers | call `drv.acquire_single(...)`, save TIFF inline | `acquire_frame_to(session, name)` / `acquire_stack_to(session, dirname)`; tracks raw_files and exported_files separately | **Codex** | Codex names the real concern: existing `make_acquirer()` drops the exported path; workflow needs to own session-relative paths. Dual tracking helps debugging. |
| 5 | `drv.move_z` signature | `drv.move_z(client, target_um, z_mode="zwide")` | `drv.move_z(client, job_name, z_um, unit="um", z_mode="zwide")` | **Codex (verify)** | The driver likely requires `job_name`; Z-wide is per-job in Leica. Verify against driver and use the actual signature. |
| 6 | Brenner peak Z conversion | sub-step parabolic refinement with edge guard | uses existing `brenner_focus(stack, z_step_um)`; explicit conversion `focus_z = z_post + z_range_um - peak_um` because `configure_z_stack` orders high-to-low | **Codex** | Codex catches a real bug class: the existing `configure_z_stack` acquires the stack in reverse Z order, so the peak coordinate must be flipped. Claude's parabolic refinement is fine math but ignores this concern. |
| 7 | Objective filename | `f"objective_{from}_to_{to}.json"` inline | `slug()` helper that sanitizes spaces, slashes, dots | **Codex** | Defensive against names like `"100x oil"` or `"10x/0.4"`. Cheap. |
| 8 | Registration report entry | `{image_shift_um, voting_agreement}` | `{image_shift_um, trusted, confidence, agreeing: [...]}` | **Codex** | Codex lists which methods agreed. Useful when a vote is 3/4: "which one disagreed?" |
| 9 | D4 label format | `"FX"` (group element code) | `"-Y +X"` (human-readable axes) | **Codex** | Operator-facing. Group codes mean nothing to a non-mathematician. |
| 10 | `fitted_image_to_stage` (pre-snap) in report | not stored | stored alongside the snapped `image_to_stage` | **Codex** | Pre-snap matrix is the raw measurement; post-snap is canonical. Both useful when debugging "why did we snap to that label?" |
| 11 | Trust marker in report | `trusted: bool` | `config_written: bool` | **Codex** | "Was a staging config written?" is the actionable question. `trusted` is one input to that decision. |
| 12 | Raw positions in objective report | not included | `home_xy_um`, `home_z_um`, `xy_post_um`, `z_post_um` all present | **Codex** | Lets a reviewer re-derive `motor_shift = post - home` from the report alone. Cheap and useful. |
| 13 | Brenner curve in report | only `brenner_peak_z_um` (scalar) | full `{peak_z_um, scores, z_positions_um}` | **Codex** | Stack data is already on disk; storing the curve in the report enables curve re-inspection without reloading the stack. |
| 14 | `exported_files` tracking | not tracked | session owns raw_files (session data dir) and exported_files (LAS X export) | **Codex** | Surfaces "what did LAS X save?" alongside "what did we copy?". Useful if the operator needs to find the original LAS X export. |
| 15 | Image size axis order | `tuple[int, int]` undocumented | explicitly `[height, width]` matching numpy ndarray shape | **Codex** | Avoids an entire class of W/H mixup bugs. |
| 16 | Migration notes | no dedicated section | Section 15: don't delete old config, add backward-compat loader if needed | **Codex** | Production currently reads `calibration/config/config.json`. Codex names the transition concern. |
| 17 | Acceptance criteria | spread across validation/test sections | dedicated Section 16 with per-notebook + system criteria | **Codex** | Centralized "done" definition; easier to sign off against. |
| 18 | Key risks | spread across open questions and validation | dedicated Section 17 with 7 risks + mitigations | **Codex** | Helpful for reviewers; centralizes failure-mode thinking. |
| 19 | First-PR scope | implementation order only | implementation order + "minimal first PR" section (image_to_stage before objective_pair, validates rig independently) | **Codex** | Reduces microscope risk; rig validates image_to_stage in isolation before the more complex pair calibration is touched. |
| 20 | Units table | dedicated Section 5 enumerating every quantity | unit convention discussed in Section 4 but not exhaustively tabulated | **Claude** | A table mapping every named quantity to its units is the single best defense against unit bugs. Keep. |
| 21 | Glossary | Section 19 (12 terms) | none | **Claude** | Helpful for newcomers; cheap. Keep. |
| 22 | Diff section vs shared plan | Section 20 names every delta from the agreed plan | none | **Claude** | Tells a reviewer "here is what changed since we last agreed". Keep. |
| 23 | Driver API reuse list | implicit (function-by-function) | Section 5 lists every driver call + every algorithms import + every lasx_state helper to reuse | **Codex** | Concrete shopping list. Easier for the implementer. |
| 24 | `drv.check_idle` mention | not mentioned | listed in driver API | **Codex** | Real LAS X needs idle checks before some operations. |
| 25 | `reset_pan_roi_zstack`, `disable_z_stack`, `configure_z_stack` reuse | not explicitly called out | listed as helpers to reuse from `lasx_state.py` | **Codex** | These already exist; calling them out prevents reinvention. |
| 26 | `promote_calibration` return value | returns `None` | returns `{source, live_path, archived_previous}` | **Codex** | Useful for the notebook to print and for tests to assert. |

---

## Where Plans Are Roughly Tied (Either Is Fine)

- **Constants table.** Both reference existing `VOTING_MIN_AGREE`, `D4_RESIDUAL_MAX`, plus a new `CALIBRATION_ROOT_DEFAULT`. Same content, different presentation.
- **Notebook markdown copy.** Both have correct operator instructions with pixel-size and image-size warnings. Choose either.
- **Workflow function names.** `start_session` / `measure` / `save_and_visualize` / `measure_parfocality_*` / `measure_parcentricity_*` are identical.
- **Promotion log format.** Both: `<utc_now> <kind> <session_id> -> <live_path>`.
- **Schema versioning.** Both: `schema_version: 1`.

---

## Recommended Synthesis

Take Codex's plan as the body; layer Claude's organizational sections on top. Concretely:

**Adopt from Codex (almost all the code-level concerns):**

1. `ImageGeometry` dataclass with separate W/H pixel sizes (#2).
2. `move_xy_and_verify` / `move_zwide_and_verify` helpers (#3).
3. `acquire_frame_to` / `acquire_stack_to` with raw + exported file tracking (#4, #14).
4. The exact driver signatures and idle-check usage (#5, #24).
5. The Brenner Z conversion that flips the stack-relative peak using `z_post + z_range_um - peak_um` (#6).
6. `slug()` helper for objective filenames (#7).
7. Rich registration report entries with `trusted` / `confidence` / `agreeing` (#8).
8. Human-readable D4 label like `"-Y +X"` (#9).
9. `fitted_image_to_stage` + `image_to_stage` both in report (#10).
10. `config_written: bool` rather than `trusted` (#11).
11. Raw positions in the objective report (#12).
12. Full Brenner curve in the report (#13).
13. `image_size_px = [height, width]` (numpy order) explicitly documented (#15).
14. Migration notes section (#16).
15. Acceptance criteria section (#17).
16. Key risks section (#18).
17. Minimal first PR section (#19).
18. Driver / algorithms / lasx_state reuse lists (#23, #25).
19. Promotion return value (#26).

**Carry over from Claude:**

1. Units table enumerating every named quantity and its units (#20).
2. Glossary of terms (#21).
3. Section explicitly diffing against the shared plan (#22).

**Verify, then adopt:**

1. **Registration API contract** (#1, #5). Read `navigator_expert/algorithms/__init__.py` and the registration module to confirm:
   - Does `register_voting(ref, tgt, pixel_um)` exist and return `{dx_um, dy_um, trusted, confidence, agreeing}`?
   - Does `drv.move_z(client, job_name, z_um, ...)` take `job_name`?
   - Does `brenner_focus(stack, z_step_um)` exist as named?
   If yes, take Codex's signatures verbatim. If no, document the wrapper layer in `_common.py`.

---

## Areas Neither Plan Resolves

Both plans punt on the same issues. Worth surfacing for the next pass:

1. **Raw image format.** TIFF vs `.npy`. Both lean TIFF; not committed.
2. **Z-stack memory.** Stream-to-disk vs in-memory. Both note the question; neither commits.
3. **Promotion archive depth.** Keep all vs rotate. Both say keep all in v1.
4. **Voting registration robustness for large stage moves under ref.** Both keep voting; both note simpler may suffice.
5. **Operator workflow for copying templates.** Both say "operator copies manually." No helper, no CLI. Acceptable in v1.

---

## Single Implementation Spec, If You Want One Doc

If the goal is to land one canonical implementation spec rather than maintain two, merge as follows (rough section layout):

1. Goal / Scope / Non-goals -- either plan; both equivalent
2. Design ethos -- either; both equivalent
3. Conceptual model -- either
4. Z model -- Codex's framing; brief
5. **Units table -- from Claude**
6. Existing APIs to reuse -- **from Codex** (concrete imports)
7. Architecture diagram -- either
8. File layout -- either
9. Constants -- either
10. Common module (`_common.py` or `common.py`) -- **from Codex** (`ImageGeometry`, move/acquire/json helpers, slug, plot helpers)
11. Workflow API dataclasses + function signatures -- **from Codex** (richer fields)
12. Workflow step-by-step -- **mostly Codex**, but use Claude's numbered substep style for readability
13. Notebook contents -- either; choose one wording
14. JSON schemas -- **from Codex** (richer reports)
15. Validation rules / Error and trust matrix -- **Claude's table format** with Codex's content
16. Promotion semantics -- either
17. Migration notes -- **from Codex**
18. Acceptance criteria -- **from Codex**
19. Tests -- **from Codex** (more concrete cases)
20. Key risks -- **from Codex**
21. Implementation order + Minimal first PR -- **from Codex**
22. **Glossary -- from Claude**
23. **Diff against shared plan -- from Claude**
24. Open questions -- merge

The merged spec is roughly Codex with Claude's units table, glossary, and diff section inserted, plus Claude's table-style validation rules.
