# Limits enforcement redesign — plan

Status: PLANNED, amended after adversarial plan review (see
`limits-enforcement-review.md`, findings PR-01..PR-10). Maintainer design
decision 2026-07-05, `docs/reviews/MAINTAINER_DECISIONS.md` §7.

## Amendments (adversarial review outcomes)

1. **Wrapper→key mapping defined (PR-01):** every mutating command wrapper
   declares a `function_limits` key; the file keeps its existing op-level key
   vocabulary, each wrapper mapping to one key. A completeness test enumerates
   all mutating wrappers (those dispatching through the fire path) and fails
   if any lacks a declared key — the commands-layer successor of the adapter's
   `_MUTATING_OPS` guard.
2. **Adapter whole-move pre-flight STAYS (PR-02):** only the function-keyed
   gate relocates down. The adapter's atomic XY+Z pre-flight (refuse before
   either axis fires) is protection the per-command checks cannot replicate
   and remains as defense in depth. Commands-level limit refusals never fire
   the native call and return the fail-closed result-dict idiom; the
   adapter/controller translate to raises per the ops error contract.
3. **Explicit-unlimited spelling is `null`, not `[]` (PR-03/PR-10):** the
   shipped shared schema already implements the maintainer's concept —
   explicit `null` = deliberately unlimited, absent key = fail closed, lists
   rejected — and is shared with the zeiss driver. Concept kept, spelling kept.
4. **Gate state location pinned (PR-04):** connect installs the validated
   limits/gate state in a module-level registry keyed by client identity
   (commands see `client`, not the adapter handle); single-process,
   single-writer invariant documented and asserted.
5. **No-fallback covers BOTH files (PR-05/PR-06):** `limits.json` and
   `function_limits.json` lose the bundled fallback together;
   `machine.py` resolution returns explicit provenance (`is_fallback`) and
   enforcement refuses on fallback; `workflows/.../preflight.py` and the
   calibration workflow provision explicit machine-local files instead of
   inheriting the bundled ones. Calibration *values* application stays
   out of scope (objective-change path), but calibration moves execute
   through `commands.move_*` and are therefore gated like everything else.
6. **Known bypasses covered or explicitly dispositioned (PR-07):**
   save/load-experiment (PyApiSave/LoadExperiment) and `move_galvo_to_pixel`
   (LRP pan write) get function-limit keys; offline `lrp_edits`/template file
   edits do not command hardware at write time and are documented as gated at
   the point LAS X executes them (job selection/acquire), not at file-write.
7. **Backstop (PR-08):** physical-envelope constants live in
   `motion/limits.py` (values from the historical machine envelope, loud
   verify-on-rig comment); runtime checks apply backstop after the file
   envelope; the connect handshake validates file-envelope containment.

8. **One `limits.json`; three files per snapshot (decision §7b,
   2026-07-06 — supersedes the "BOTH files" wording in amendment 5):**
   `function_limits.json` and `limits.json` were redundant (the stage
   envelope appeared in both). They are collapsed into **one** `limits.json`
   in the function-keyed format — `constraints` (the `stage.*` envelope) +
   `functions` (the gate policy) — and
   `function_limits.json` is removed everywhere (constant, publish write,
   handshake read, bundled template, fixtures, tests). Both readers now read
   this single file: `motion/stage_config.load()` derives the envelope from
   `constraints.stage.*`; the
   commands gate (`commands/gate`) parses `constraints` + `functions` via
   `shared/limits`. (Decision §2b, 2026-07-06 — supersedes the "`backlash`
   block" wording above: backlash was removed from `limits.json` entirely; it
   is a plain motion utility with baked-in default params, not config. A stray
   `backlash` key left in an older file is ignored by both readers.) Each
   machine snapshot dir holds
   exactly three files: `limits.json`, `calibration.json`, `origin.json`. The
   limits adopt no longer seeds a bundled `calibration.json`
   (`bundled_ok=False` for calibration too): a fresh-machine limits adopt
   writes only `limits.json` and carries a *real* prior calibration forward if
   present, never mints one from the template — calibration keeps its loud
   in-memory READ fallback (`machine.calibration_path()`) until an explicit
   calibration adopt. The backstop, the connect handshake
   (schema/finite/backstop-containment/read-only-on-fail), the commands-layer
   gate, the completeness AST-sweep, and all fail-closed semantics are
   preserved exactly.

## Design philosophy (maintainer)

Limits are enforced **as low as possible** — at the command wrapper that
populates the native CAM function's model — so nothing built on top (adapter,
controller, workflows, notebooks) can interfere with or bypass them. Safety
must not depend on which entry point a caller used.

## Current state (verified at HEAD)

| Concern | Where enforced today | Verdict vs philosophy |
|---|---|---|
| Stage XY limits | `commands.py:1078` → `motion.limits._check_xy_limits` (inside `move_xy`, before fire) | Already at the right layer |
| Stage Z limits | `commands.py:1300` → `_check_z_limits` | Already at the right layer |
| Envelope source | in-memory `_stage_limits`, set by `set_stage_limits` / `apply_stage_limits_from_config(stage_config.load())` | OK, but `load()` **falls back to the bundled defaults file** with only a log warning |
| Function-keyed limits | zmart_adapter only (`_MUTATING_OPS` gate) | **Too high** — direct `commands.*` callers bypass it |
| Absolute backstop | none | Missing |
| "No limit" semantics | absent key ≈ unlimited in places | Must become explicit |

## Target design

1. **One chokepoint, in `commands/`.** The function-keyed limits gate moves
   down into the commands layer so every mutating command wrapper checks it
   before firing, exactly like `_check_xy_limits` today. The adapter's gate is
   then redundant and is removed; its `_MUTATING_OPS` completeness idea
   survives as a test: *every mutating command wrapper must carry the gate*
   (enumerated, so a new command cannot ship without it).

   > Superseded by Amendment 8 / §7b (collapsed into the single `limits.json`).
2. **No default limits file for enforcement.** A bundled default that silently
   applies can be the wrong machine's envelope — that breaks safety rather
   than providing it. `limits/defaults/limits.json` stops being a runtime
   fallback and becomes a **template** only. Enforcement requires an explicit,
   machine-local limits file, deliberately created.
3. **Connect-time limits handshake.** `connect` verifies the machine-local
   limits file exists in the expected location, validates it (schema +
   backstop containment + finite numbers), and records provenance (path,
   mtime, source). Missing/invalid ⇒ the session still connects for
   *read-only* use, but **every mutating command refuses** with an error that
   says exactly what is wrong and points to the notebook that creates the
   file.
4. **The notebook is the file factory.** `limits/notebooks/set_stage_limits.ipynb`
   is the documented way to create/update the machine-local limits file
   (drive to the physical corners, capture, write). The limits folder stays;
   what changes is that no shipped file is silently trusted.
5. **Hardcoded absolute backstop for the motoric stage.** Physical travel
   constants in `motion/limits.py`, checked independently of (and after) the
   file envelope, so even a hand-widened file cannot command a move outside
   the physical envelope. File envelopes must validate as *within* the
   backstop.
6. **Explicit "no limit" = `[]`.** Not everything needs a limit, but every
   limit decision must be explicit: a function/axis key mapped to `[]` means
   "deliberately unlimited"; an **absent** key means "no decision" and fails
   closed. Schema validation enforces finite numbers, min ≤ max, and rejects
   NaN/Infinity.

   > Superseded by Amendment 3 (the spelling is `null`; lists are rejected).
7. **Calibration co-located, enforced elsewhere.** Calibration values live in
   the same machine-local config area but are applied at their own natural
   chokepoint — the objective-change path (per-objective translation onto the
   right actuator). Out of scope for this change beyond keeping file layout
   compatible.

## Gating (maintainer)

Mock first: the full redesign is validated against `MockLasxClient`,
including a permanent adversarial suite (malformed/poisoned limits files,
NaN/inf targets, unset-envelope refusals, gate-bypass attempts through every
entry point: commands, adapter, controller). Only after the offline +
adversarial gates are green does it go to the scope, where the connect-time
handshake doubles as the on-microscope check.

## Migration notes

- Tests and mock validators currently lean on the bundled fallback; they must
  provision an explicit limits file (fixture) instead — this is expected churn
  and makes the tests honest.
- `apply_stage_limits_from_config(stage_config.load())` keeps working; `load()`
  simply refuses to silently substitute defaults (clear error instead).
- Manual `set_stage_limits(...)` stays: an explicit operator action is
  legitimate; the hardcoded backstop still bounds it.
- Backstop constants: derive from the machine's physical travel; until
  verified on the rig, use the historical machine envelope values as the
  backstop with a loud comment (verify-on-rig), never wider.
- The workflows' tighter runtime envelopes (boundary markers / scan field)
  keep narrowing within the file envelope, as today.
