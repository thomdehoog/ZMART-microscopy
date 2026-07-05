# Limits enforcement redesign — plan

Status: PLANNED (maintainer design decision 2026-07-05; see
`docs/reviews/MAINTAINER_DECISIONS.md` §7). Not yet implemented.

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
