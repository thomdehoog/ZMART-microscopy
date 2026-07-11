# Adversarial review — limits-enforcement plan

Reviews `docs/design/limits-enforcement.md` (backed by
`docs/reviews/MAINTAINER_DECISIONS.md` §7) against the code at HEAD
(`34dcb09`). Target driver:
`zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` (paths below are
relative to it unless rooted at repo). Findings are numbered `PR-0x` with a
classification (BLOCKER / ADJUST / NOTE), evidence, and a concrete amendment.
The plan is **not** modified here; the amended-plan delta and a GO/NO-GO sit at
the end.

The plan's core intuition is correct and the code confirms real bypasses worth
closing (workflows and calibration mutate through `commands.move_*` directly,
never through the adapter gate — see PR-01/PR-07). But three points as written
are not implementable against the actual code without change (PR-01, PR-02,
PR-03), and several more are under-specified (PR-04..PR-06).

---

## PR-01 — "one gate per command wrapper" collides with the op-keyed file (BLOCKER)

**Claim in plan (item 1):** the function-keyed gate "moves down into the
commands layer so every mutating command wrapper checks it before firing,
exactly like `_check_xy_limits` today," and `_MUTATING_OPS` "survives as a
test: every mutating command wrapper must carry the gate (enumerated)."

**Evidence.** `function_limits.json` is keyed by **five adapter op names**, not
command-wrapper names:
`zmart_adapter/zmart_adapter.py:112`
`_MUTATING_OPS = ("set_origin", "set_xyz", "set_state", "run_procedure", "acquire")`
and `limits/defaults/function_limits.json` `functions` block enumerates exactly
those five. The commands layer has **~30 mutating wrappers** —
`set_zoom`, `set_scan_speed`, `set_scan_resonant`, `set_scan_mode`,
`set_sequential_mode`, `set_scan_field_rotation`, `set_image_format`,
`set_objective`, `set_z_stack_*` (x3), `set_frame_*`/`set_line_*` (x4),
`set_pinhole_airy`, `set_detector_gain`, `set_laser_intensity`,
`set_laser_shutter`, `set_filter_wheel_*` (x2), `move_xy`, `move_galvo_to_pixel`,
`move_z`, `acquire`, `select_job` (`commands/commands.py:319..1446`). One adapter
op (`set_state`) fans out to *all* the `set_*` setters; `set_xyz` fans out to
`move_xy` **and** `move_z`; `run_procedure` to `select_job`/objective/job-setup.
There is no 1:1 "wrapper = op" mapping, so "every wrapper carries *the* gate"
is not well defined against the current schema.

Second-order fact worth stating plainly: today **every non-`set_xyz` entry in
`function_limits.json` is `null`** (`set_origin`, `set_state`, `run_procedure`,
`acquire` all `null`), and `set_xyz`'s constraints are `@stage.x/@stage.y/…`
which are overlaid from the *same* `stage_cfg` envelope that already drives
`_check_xy_limits`/`_check_z_limits` (`zmart_adapter.py:219-223`). So the
function-keyed gate currently enforces **nothing the stage-envelope check does
not already enforce**, except provenance-rich messages and the load-time
completeness discipline. The real deliverables of the redesign are the
completeness enumeration + backstop, not new numeric checks — that should be
said, so the work is not over-scoped.

**Amendment.** Before implementation the plan must pin the taxonomy:
- Decide whether the file stays op-keyed (5 ops) with an explicit, enumerated
  **wrapper→op mapping** (each of the ~30 wrappers declares which op key it
  gates on), or is re-keyed to per-wrapper granularity (schema + file rewrite;
  `parse`'s `functions=` set becomes the wrapper list).
- The completeness test then asserts *that mapping* is total over the wrapper
  set (a new wrapper with no mapping entry fails the offline suite), which is
  the enforceable form of the `_MUTATING_OPS` idea.
- Name the artifact that lists the wrappers (a module constant, the analogue of
  `_MUTATING_OPS`, living in `commands/`).

---

## PR-02 — per-command gating destroys whole-move pre-flight atomicity (BLOCKER)

**Evidence.** The adapter deliberately pre-flights **the entire move (XY *and*
Z targets) before any motion**:
`zmart_adapter.py:575-585`
```
_check_limits(handle, "set_xyz", {"x_um": abs_x, "y_um": abs_y})
_limits._check_xy_limits(abs_x, abs_y)
try:
    _check_limits(handle, "set_xyz", {z_param: z_target})
    _limits._check_z_limits(z_target, z_mode)
...
# then, only after both pass:
_motion.move_xy_with_backlash(handle.client, abs_x, abs_y)   # :588 physically moves
z_result = _commands.move_z(...)                              # :590
```
with the comment (`:569-573`) stating the intent: "so a doomed z leg can never
leave the stage at a new XY with the old focus." If the *only* gate is inside
each wrapper, `commands.move_xy` fires (and the stage physically moves) before
`commands.move_z`'s check runs, so an out-of-range Z leg leaves the stage at a
new XY with the old focus — exactly the failure the adapter guards against.
`commands.move_xy` also swallows the `RuntimeError` from `_check_xy_limits` and
returns a soft `{"success": False}` dict (`commands.py:1079-1087`), a *different*
contract from the adapter gate, which **raises** `LimitViolation` with
provenance — so "remove the adapter gate, rely on the wrapper" also silently
downgrades error quality and turns a hard refusal into a status dict a caller
may ignore.

**Amendment.** The plan's "the adapter's gate is then redundant and is removed"
must be qualified: the **whole-move pre-flight (combined XY+Z check before any
motion) must be preserved**. Either (a) the adapter keeps a pre-flight that
calls the same shared check for both legs before firing (accept the "duplicate"
as intentional defense-in-depth, which the existing comment already frames), or
(b) introduce a combined move primitive in `commands/` that checks both legs
then fires both. Also decide the wrapper's error contract: a limit violation
should raise (not become a soft dict) so callers cannot proceed past it.

---

## PR-03 — `[]` sentinel conflicts with the already-shipped `null` spec (ADJUST)

**Evidence.** The plan (item 6) mandates "explicit no-limit = `[]`, absent =
fail closed." But the shared, multi-driver spec **already implements exactly
that semantics using `null`**, and actively rejects `[]`:
- `shared/limits/spec.py:165` `if entry is None: return` (null = reviewed,
  deliberately unlimited).
- `shared/limits/spec.py:236-241` a **missing** declared function → `LimitsError`
  (absent = fail closed) — already done.
- `shared/limits/spec.py:254` `if not isinstance(entry, dict): raise LimitsError`
  → a JSON `[]` (a list) is neither `null` nor an object, so it is a **hard
  error today**. Adopting `[]` requires editing the shared parser used by other
  drivers (zeiss also imports `shared.limits`: see
  `zmart_drivers/zeiss/zenapi/…/test_limits.py`) and rewriting
  `function_limits.json` (which currently uses `null`).
- For **axis** limits the same is true: `motion/stage_config.py:109` requires
  `len(values) == 2`; an axis mapped to `[]` fails validation, and an **absent**
  axis already raises (`stage_config.py:107`). So "absent = fail closed" is
  already the behavior on both files.

**Amendment.** Drop the `[]` change. Keep `null` as the "reviewed-and-unlimited"
sentinel — it already delivers the plan's intent (explicit unlimited vs.
fail-closed-on-absent) with zero churn and without touching the shared spec that
other drivers depend on. If the maintainer insists on `[]` for ergonomics, scope
it as a deliberate shared-spec change (update `spec.py`, `_validate_limits`,
`function_limits.json`, and zeiss's file+tests in the same PR) and call out the
cross-driver blast radius. Either way, "absent = fail closed" needs **no new
code** — say so.

---

## PR-04 — where does the relocated `FunctionLimits` live? handle vs. module (ADJUST)

**Evidence.** Command wrappers take **`client`, not `handle`**
(`commands.py:1048` `move_xy(client, …)`, `:1247` `move_z(client, …)`,
`:1354` `acquire(client, …)`). The `FunctionLimits` object lives on the
**per-session handle** (`zmart_adapter.py:156` `function_limits: Any | None`),
and the shared spec explicitly insists on that scoping:
`shared/limits/spec.py:39-43` "hang it off the driver handle, never off a
module — two instruments in one process must not share an envelope." Moving the
gate into `commands.*` (which only sees `client`) forces one of:
- a **module global** (like `motion/limits.py:26` `_stage_limits`, already a
  module global) — contradicts the spec's guidance and re-creates the exact
  two-instrument hazard the spec warns about; or
- threading the `FunctionLimits` through every wrapper (new param), or attaching
  it to the `client`.

**Amendment.** The plan must state explicitly where the envelope + gate state
lives after the change and reconcile it with `spec.py:39-43`. The defensible
choice, consistent with the existing `_stage_limits` module global and the
dispatch **single-writer** assumption (`commands/dispatch.py:20-24`), is a
module-scoped envelope with a documented **single-instrument-per-process**
invariant — but then `spec.py`'s docstring guidance must be amended in the same
change so the two do not contradict, and the adversarial suite must include a
"second connect in one process rebinds the envelope" test.

---

## PR-05 — "no silent fallback" is mechanically under-specified and has real callers (ADJUST)

**Evidence.** The fallback is not in `load()`; it is in the **path resolver**,
which drops the `is_fallback` flag:
`config/machine.py:177-188` `resolve()` returns `(path, is_fallback)`, but
`limits_path()` (`:216-218`) and therefore `default_stage_limits_path()`
(`stage_config.py:69-77` → `__init__.py:344`) return the **bundled path
silently**. `stage_config.load()` then reads a perfectly valid file and cannot
tell it was the fallback (`stage_config.py:182,187`). So "`load()` refuses to
silently substitute defaults" requires new code: `load()`/connect must consult
`resolve()`'s `is_fallback` and raise. This is not written in the plan.

Real callers that break the moment it raises (not just tests):
- `workflows/target_acquisition/pipeline/preflight.py:124`
  `drv.load_stage_config(limits_path=drv.default_stage_limits_path())` — the
  live workflow entry, which will now raise on any machine without a snapshot.
- `zmart_adapter.py:189` `_configure_stage_limits` — already `try/except →
  None` (`:192-198`), so it degrades to read-only cleanly (good), but connect's
  warning path (`:276-279`) becomes the *normal* path on unprovisioned
  machines.
- `calibration/core/common.py:182,204` move the stage via `drv.move_xy` /
  `drv.move_z`, which depend on `set_stage_limits()` having run at connect; with
  the envelope gone they fail with "Stage limits not configured."

**Amendment.** Specify the mechanism: `resolve → is_fallback → raise` in
`load()` (or a new strict loader used by connect), with the connect handshake
catching it and entering read-only. Enumerate and update each live caller
(`preflight.py:124` must handle "no envelope → read-only/abort with the
notebook pointer"). Provide the fixture story: tests use
`MachineProfile(programdata_root=tmp_path)` + `publish_snapshot(...)` (infra
already exists — `tests/unit/test_zmart_adapter.py:146,175`,
`tests/unit/test_stage_config.py`) to provision a real snapshot instead of
leaning on the bundled file.

---

## PR-06 — splitting limits-fallback from calibration-fallback is only half-coherent (ADJUST)

**Evidence.** `machine.py` resolves `limits.json`, `function_limits.json`, and
`calibration.json` through the **same** `resolve()`/`_resolve_logged` fallback
(`machine.py:68-72, 177-218`). Two coupling problems for "calibration is out of
scope":
1. `stage_config.load()` reads **both** limits and calibration in one call
   (`stage_config.py:187-188`). Removing the limits fallback while keeping the
   calibration fallback is doable because `resolve()` is per-file, but `load()`
   must apply the strict rule to the limits leg only — that split has to be
   coded deliberately, not assumed.
2. `function_limits.json` **also** falls back independently
   (`zmart_adapter.py:217` `MACHINE.resolve(FUNCTION_LIMITS_FILENAME)`), and it
   is a *limits* file. If limits.json stops falling back but function_limits.json
   keeps falling back, the gate would load bundled constraints while the stage
   envelope refuses — inconsistent. Function-limits fallback removal is
   therefore **in scope**, not out.
3. Calibration is not as "out of scope" as stated: calibration workflows **move
   the stage** through `drv.move_xy`/`drv.move_z`
   (`calibration/core/common.py:182,204`), which the relocated gate will now
   intercept. So calibration paths need a provisioned envelope/function-limits
   even though calibration.json's own fallback stays.

**Amendment.** State the split precisely: (a) `limits.json` and
`function_limits.json` fallbacks are removed together (both are limits);
(b) `calibration.json` fallback (objective translations,
`zmart_adapter.py:294`) is intentionally retained; (c) note that calibration
workflows are now gated by the commands-layer envelope and need a real limits
file to move — they are not exempt.

---

## PR-07 — bypass surface beyond the stage: scanfields, galvo-pan lrp, autosave (ADJUST)

**Evidence.** Mutations that do **not** go through a gated `commands.*` wrapper,
so a commands-layer gate on move/set/acquire will not intercept them:
- `scanfields/files.py:170,238` fire `PyApiSaveExperiment.UpdateAwaitReceipt`
  and `PyApiLoadExperiment.UpdateAwaitReceipt` directly on the client. Loading
  an experiment/scan-field template changes **what `acquire` will scan** (the
  stored scan-field pattern moves the stage during acquisition). Ungated.
- `commands/move_galvo_to_pixel` (`commands.py:1141,1211-1220`) mutates galvo
  pan by editing the `.lrp` file inside `apply_lrp_change`; it enforces its own
  `_PAN_LIMIT` but is **not** in `_MUTATING_OPS` and has no `function_limits`
  entry — a command-level mutation the enumerated set currently omits.
- `experimental/lrp_edits/*` edit `.lrp` files that LAS X later executes
  (RF-05; may be reworked, not hardware-validated) — a mutation channel wholly
  outside the commands gate.
- The `lasx_native_autosave` exporter (`zmart_adapter.py:632`) is an
  alternate save path.

Confirmed clean: `readers/api_reader.py` and `config/profiles.py` uses of
`UpdateAwaitReceipt` are **reads** (Ping/GetXY/GetJobSettings), not mutations.

**Amendment.** The enumerated mutating-wrapper set (PR-01) must make an explicit
in/out decision for each: `move_galvo_to_pixel` (gate or document its
`_PAN_LIMIT` as the sanctioned check + `null` in the file), and the
`scanfields` load/save (either route through a gated wrapper or document why a
template load needs no envelope check). Otherwise the "nothing built on top can
bypass" guarantee is false as written.

---

## PR-08 — backstop constants: values, placement, and the validator seam (NOTE)

**Evidence.** Defensible values come straight from the bundled envelope and
match the existing test expectations:
`limits/defaults/limits.json` → x `[1000,130000]`, y `[1000,100000]`,
z_galvo `[-200,200]`, z_wide `[0,25000]`; and
`tests/unit/test_core_driver.py:1959,1978,1982` assert `130001`, galvo `201`,
zwide `25001` are rejected — i.e. these numbers are already the de-facto
envelope. There is **no vendor-spec source** in the repo wider than these, so
using them as the backstop (per the plan's "historical machine envelope,
verify-on-rig") is the only defensible choice.

Placement: `motion/limits.py` is the right home — it is stdlib-only
(`limits.py:16-19`) and already imported by both `commands` (runtime check) and
`__init__`; a driver-local constant there is importable by both the runtime
`_check_*` and a connect-time file validator without a cycle. Crucially, the
**backstop-containment check cannot live in `shared/limits/spec.py`** (it is
cross-driver and cannot know Leica travel) nor cleanly in
`stage_config._validate_limits` (also schema-only) — it belongs in the
**connect handshake** (driver-local), which the plan already designates as the
validator (item 3). One caveat: x_min/y_min = 1000 are margins, not physical
zero, so a legitimately wider future calibration would be rejected by the
backstop; keep the loud verify-on-rig comment and never widen without rig data.

**Amendment.** Put the constants in `motion/limits.py`; add the
backstop-containment assertion in the connect handshake (over the *effective*
`stage_cfg` envelope, since `function_limits` `stage.*` is overlaid from it and
cannot drift — `zmart_adapter.py:219-223`); state the exact numbers and the
verify-on-rig comment.

---

## PR-09 — concurrency/ordering of the in-memory envelope (NOTE)

**Evidence.** `commands/dispatch.py:20-24` states command dispatch "assumes a
single writer … commands are single-threaded by convention," and `_stage_limits`
is already a module global (`motion/limits.py:26`). Connect sets the stage
envelope (`zmart_adapter.py:276`) then the function limits
(`:279`) before any command — under single-writer there is no real
connect/first-command race. The genuine hazard is only the **two-connects-in-one-
process** rebind if the function envelope also becomes module-global (PR-04).

**Amendment.** Document the single-instrument-per-process invariant next to the
envelope state; add an adversarial test that a second `connect()` does not leave
a stale envelope governing the first session. No locking needed if the invariant
holds.

---

## PR-10 — scope discipline / mock-first gate (NOTE)

- The `[]` change (PR-03) is YAGNI churn with no safety gain over `null`, and it
  reaches into the shared cross-driver spec — recommend cutting it.
- The plan correctly keeps calibration co-location out of scope (item 7) and
  defers backstop tuning to the rig while using historical values now — both
  consistent with the mock-first gate.
- Nothing in the plan *requires* bench hardware to validate the enforcement
  logic: the connect handshake, fail-closed refusals, backstop containment, and
  completeness test are all exercisable on `MockLasxClient`
  (`tests/helpers/mock_lasx_api.py`) with `programdata_root=tmp_path` snapshots.
  The one bench-only artifact is the `set_limits.ipynb` factory (driving
  to physical corners), which the plan already fences behind the mock+adversarial
  gate — keep it there. Ensure the adversarial suite (poisoned/malformed files,
  NaN/inf, unset-envelope refusal, per-entry-point bypass) provisions its
  fixtures via `publish_snapshot`, not the bundled file.

---

## Amended-plan delta (minimum changes before implementation)

1. **Taxonomy first (PR-01).** Define the enumerated commands-layer
   mutating-wrapper set and an explicit wrapper→limits-key mapping; decide
   op-keyed-with-mapping vs. per-wrapper re-key. The completeness test asserts
   that mapping is total. Acknowledge that today's function-limits enforce only
   the stage envelope + provenance, so the real deliverables are
   completeness + backstop.
2. **Preserve whole-move atomicity (PR-02).** Keep a combined XY+Z pre-flight
   before any motion (retain the adapter pre-flight as intentional, or add a
   combined commands primitive). Make limit violations **raise**, not return a
   soft dict.
3. **Keep `null`, drop `[]` (PR-03).** "Absent = fail closed" already exists in
   `spec.py`/`_validate_limits`; no new sentinel. If `[]` is truly required,
   scope it as a shared-spec change touching zeiss too.
4. **Pin envelope state location (PR-04).** State handle-vs-module explicitly;
   if module-global, amend `spec.py:39-43` guidance and add the single-process
   invariant + rebind test.
5. **Specify the fallback-removal mechanism and its callers (PR-05, PR-06).**
   `resolve → is_fallback → raise` for **both** `limits.json` and
   `function_limits.json`; keep `calibration.json` fallback; update
   `preflight.py:124` and the calibration move paths; provision fixtures via
   `publish_snapshot`.
6. **Close/annotate the non-wrapper bypasses (PR-07).** Explicit in/out decision
   for `move_galvo_to_pixel`, `scanfields` load/save, `lrp_edits`, autosave.
7. **Backstop in `motion/limits.py`, containment in connect (PR-08).** Use the
   bundled numbers, verify-on-rig comment, check the effective envelope.
8. **Document single-writer invariant + rebind test (PR-09).**

## Recommendation: **NO-GO** (conditional)

The design direction is sound and well-motivated by the code, but **three
BLOCKERs** (PR-01 taxonomy, PR-02 atomicity, and PR-03's conflict with the
shipped spec) mean the plan as written cannot be implemented faithfully — it
would either fail to define the chokepoint, regress move-atomicity, or break the
shared cross-driver spec. These are all resolvable on paper. Fold the
amended-plan delta into `limits-enforcement.md`, then it is a **GO** for the
mock-first implementation.
