# Adversarial review — merge `function_limits.json` into one `limits.json` (§7b)

Reviewed commit: **592a323** `refactor(limits): merge function_limits.json into one limits.json (§7b)`
Branch: `claude/smart-drivers-code-review-ky4phc`
Against: decision §7b (`docs/reviews/MAINTAINER_DECISIONS.md`) and plan amendment 8 (`docs/design/limits-enforcement.md`).
Base dir: `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`.
Reviewer: independent adversarial gate. Date: 2026-07-06.

## Verdict

- **NO BYPASS FOUND.** Every mutating entry point still refuses fail-closed when the single
  `limits.json` is missing / old-format / poisoned, and no crafted merged file lets an
  out-of-envelope stage move reach hardware. All fail-closed semantics are preserved.
- **Two-reader agreement: AGREE** on the numbers governing stage moves; no axis is left
  ungated and no file makes the two readers disagree in a way that permits an unsafe move
  (details below).
- Findings: **MR-01** (Low–Med, flagged), **MR-02** (Low, flagged, pre-existing),
  **MR-03 / MR-04** (informational, verified safe). **No code changes made** — the one
  behavioural regression is in the *safe* (fail-closed) direction, and "fixing" it would
  *loosen* a safety gate, which needs a maintainer call.

## Two-reader-agreement verdict (attack #1)

The merged `limits.json` is read by two paths at connect (`commands/gate.connect_handshake`):

1. `motion/stage_config.load(limits_path)` — derives `stage_um` from `constraints.stage.*`
   and validates it to **exactly** `{x, y, z_galvo, z_wide}` (unknown axis → raise, missing
   axis → raise, non-finite → raise, min>max → raise).
2. `shared.limits.load(limits_file, functions=FUNCTION_LIMIT_KEYS, constraint_overrides=…)`
   — parses `constraints` + `functions`, **overlaying the envelope stage_config just
   validated** onto the `stage.*` constraints via `constraint_overrides`.

Agreement is **structural, not coincidental**:

- The gate builds `constraint_overrides` from `stage_cfg["stage_um"]` (reader 1's validated
  output), so the numbers the gate enforces for `@stage.*` are *exactly* reader 1's numbers —
  never the file's raw copy.
- `shared.limits.parse` requires every override key to name an existing constraint, and
  reader 1 requires exactly the four `stage.*` constraints. A **missing** `stage.x` fails
  BOTH (reader 1: "missing axis"; override: "matches no constraint"). An **extra** `stage.w`
  fails reader 1 ("unknown axes ['w']"). Either way the whole handshake fails closed — there
  is **no gap where neither reader checks an axis**, and no z_galvo/z_wide naming mismatch is
  reachable (both sides use the same four names). Probes PROBE-E/G confirm.
- The only residual divergence is a hand-crafted `functions` entry that uses an **inline**
  numeric constraint (e.g. `set_xyz.x_um: {min:-1e9,max:1e9}`) instead of `@stage.x`. The
  gate's function-check then uses the inline bound, so `x=999999` passes the *gate* layer
  (PROBE-H). This is **defended in depth**: `move_xy`/`move_z` independently enforce the
  applied envelope + hardcoded backstop via `motion.limits._check_xy_limits` /
  `_check_z_limits`, which refuse the same target end-to-end
  (`X=999999.0 outside limits [1000.0, 130000.0]`, verified driving the full `commands.move_xy`
  against a client that explodes on any native access). This inline-vs-reference property is a
  **pre-existing** `shared.limits` design characteristic, unchanged by the merge, and cannot
  yield an unsafe stage move.

Net: for the axes that command hardware, the two readers agree, and the motion layer is a
second, envelope-exact gate that no `functions`-block trickery can widen.

## Findings

### MR-01 — Backlash is now coupled to the safety handshake (fail-closed) — FLAGGED (Low–Med)
`motion/stage_config.py:266-268` (`load` raises on missing `backlash`) and
`:174-188` (`_validate_backlash` raises on a bad-typed field).

Evidence: PROBE-B — a merged file with a valid `constraints`/`functions` envelope but **no
`backlash` block** makes `connect_handshake` fail closed (`ok=False`), so the whole session
goes read-only. PROBE-C/PROBE-I — a poisoned backlash type (`overshoot_um:"boom"`,
`settle_ms:"NaN"`) likewise fails the *entire* handshake.

Why it matters: pre-merge, `stage_config.load` read backlash from **`calibration.json` with a
bundled fallback** (`default_calibration_path()`), so a backlash problem could *never* take
down the limits handshake — backlash was explicitly "values, not enforcement." Post-merge,
backlash lives in `limits.json` and is read on the enforcement path, so a non-enforcement value
can now disable the enforcement gate entirely. The task's stated expectation (point 3) is that
a constraints-present / backlash-missing file should **degrade to default backlash and still
gate**. It does not — it fails closed. Note the internal inconsistency: the *adopt* path
(`_carry_backlash`, `stage_config.py:297-312`) **does** degrade to `_DEFAULT_BACKLASH`; only the
runtime *read* fails closed.

Direction is **safe** (fail-closed → no unsafe move), so this is an availability/robustness +
design-intent issue, not a safety hole. **Flagged, not fixed:** loosening a safety gate's
validation to "degrade" is a maintainer decision; making it degrade unilaterally would trade a
safe failure for a softer one. Recommend the maintainer confirm whether missing/invalid backlash
should degrade-to-default (per the §7b "backlash = values, not enforcement" framing) or stay
fail-closed, and align `load` with `_carry_backlash` either way.

### MR-02 — `_validate_backlash` accepts non-finite values — FLAGGED (Low, pre-existing)
`motion/stage_config.py:174-188`. `float(backlash["overshoot_um"])` / `_um` fields are coerced
but **not** checked for finiteness (unlike `_validate_limits`, which rejects non-finite). PROBE-D:
a `NaN` `overshoot_um` **passes** validation and the handshake **succeeds**. Not a safety hole:
every backlash leg routes through the gated `move_xy` + hardcoded backstop, and `_require_finite`
refuses a `NaN` target at move time. This validator is **byte-identical to pre-merge** (not
merge-introduced), but the merge elevated backlash into the handshake-critical file, so the gap
is now more prominent. Suggest adding an `isfinite` check on the `_um` fields for symmetry with
the stage-limit validator.

### MR-03 — Unknown top-level sections truly ignored — VERIFIED SAFE (info)
`shared.limits.parse` reads only `schema_version`/`source`/`constraints`/`functions`. PROBE-F: a
merged file carrying an extra top-level `"evil": {stage.x:{min:-9e9,max:9e9}}` section (plus an
inflated backlash) parses with **zero effect** — constraints are sourced only from
`payload["constraints"]`, so a sibling section cannot smuggle in or alter a constraint. The new
lock test `test_unknown_top_level_section_is_ignored` (`shared/limits/tests/test_spec.py`) pins
this AND proves a poisoned constraint / `NaN` bound still fails (`match="finite"`).
`shared/limits/spec.py` is **unmodified** by the commit — no loosening for the zeiss / mesospim
drivers that share it.

### MR-04 — Inline-constraint two-reader divergence caught downstream — VERIFIED SAFE (info)
See the agreement section; PROBE-H proves the motion layer refuses end-to-end. Pre-existing;
no action.

## Section checklist

- **#1 Two-reader divergence** — AGREE; no ungated axis; inline divergence defended in depth. See above.
- **#2 backlash validation hole** — shared parser truly ignores `backlash`/siblings (MR-03).
  Poisoned backlash → fail-closed (MR-01), except non-finite which passes but is caught at move
  time (MR-02). No bypass; no crash-into-unprotected-state.
- **#3 Migration fail-closed** — old flat `stage_um` file → handshake fails closed naming
  `limits.json` (PROBE-E). Missing backlash → fails closed (MR-01; note: *not* degrade). Fresh
  machine (no snapshot) → fails closed naming `limits.json`, moves refused (fresh-machine probe).
- **#4 Calibration seeding stop** — `publish_snapshot` seeds calibration with `bundled_ok=False`;
  only `stage_config.adopt_limits` and `calibration/core/adopt.py` call `publish_snapshot`
  (grepped). A limits/fresh adopt writes **only `limits.json`** (probe step 3). An explicit
  calibration adopt (override passed) **does** write `calibration.json` (probe step 5). The loud
  in-memory calibration READ fallback still fires (`calibration_path()` → bundled with warning,
  probe step 2).
- **#5 Bypass hunt** — every mutating wrapper refuses when the gate is unloaded/invalid, now
  against the single file (`check_refusal` fail-closed on `state is None` / `error`). The AST
  completeness sweep still catches a newly-added ungated wrapper (injected `move_evil` →
  detected). `commands.py`/`zmart_adapter.py` diffs are comment-only.
- **#6 Regressions** — `shared/limits/spec.py` unmodified; zeiss/mesospim green. Backstop
  containment at handshake still enforced against the merged file (over-wide envelope → refused,
  "reach outside the physical backstop"). Residual `function_limits.json` references are all in
  the **separate mesospim driver** (its own constant/file, out of §7b scope), not the leica driver.

## Gate numbers (run by the reviewer, this checkout)

| Gate | Result |
|---|---|
| Driver `run_ci.py --no-cov` (offline) | **909 passed, 3 skipped** — lint clean — RESULT PASSED |
| Driver `pytest tests/` | 890 passed, 2 skipped, 18 subtests |
| Adversarial suite (`test_limits_adversarial.py`) + stage_config + machine + backlash | 158 passed |
| Controller (`zmart_controller/tests`) | **35 passed** |
| `shared/limits/tests` | **30 passed** |
| Zeiss (from `zmart_drivers/zeiss/zenapi`) | **50 passed**, 1 deselected |
| Mesospim (from `zmart_drivers/mesospim`) | **130 passed**, 11 deselected |
| Workflows | 177 passed, 61 skipped |
| Mock `validate_hardware --mock` (all phases) | pass=113 warn=0 **fail=0** skip=2 |
| Mock `validate_zmart_adapter --mock --allow-move` | pass=40 warn=0 **fail=0** skip=3 |
| Mock `validate_readers_side_by_side --mock` | parity 18/18, 0 timeouts |

Mock-validator markdown reports and temp `zmart_microscopy_mock_root_*` dirs deleted after the run.

## Fixes / flags summary
- Fixes applied: **none** (working tree unchanged).
- Flags: **MR-01** (backlash coupling → missing/invalid backlash fails handshake instead of
  degrading; safe direction, but contradicts the "backlash = values" intent and the `_carry_backlash`
  degrade path — maintainer to confirm intent), **MR-02** (non-finite backlash accepted; pre-existing;
  caught at move time).
