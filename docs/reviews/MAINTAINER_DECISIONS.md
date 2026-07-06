# Maintainer Decisions on Review Findings

Recorded 2026-07-05 from the maintainer (Thom de Hoog), resolving policy questions the
review series (`docs/reviews/`) left open. Future work on these findings must follow
these decisions rather than the reviews' open-ended "decide" actions.

## 1. Hybrid reader stays — and must actually work

Having a hybrid reader is **essential**. The api-only and log-only readers must also
remain available as standalone modes. **The default mode for routed state reads is
`hybrid`** (decided 2026-07-05; applied to all six `*_mode` fields in
`StateReaderProfile`). Reads that decide command control flow or produce persisted
correctness artifacts continue to pin `mode="api"` explicitly at their call sites,
per the profile's own rule — the hybrid default governs cold/status reads.

Design rationale (maintainer, 2026-07-05): both sources can be stale, but for
**different fields** — their staleness profiles are complementary, so a hybrid read
wins in the far majority of cases. And when a **change** is commanded, the target
value is known, so confirmation needs only **one** of the two readers to witness the
expected value (guarded by the transition-witness gate); it does not need both to
agree, and the other leg's staleness is irrelevant.

Consequences for the findings:
- CF-01 (hybrid confirmation race's API leg self-blocks on its own in-flight claim):
  fix the mechanism (re-entrant claim / claim handoff) — do **not** delete the hybrid
  machinery. RF-03(b)'s "or delete" branch is off the table. The race semantics to
  preserve: first leg to admissibly witness the target confirms.
- LC-11/FD-11 (passive hybrid read race unreachable at shipped `"api"` defaults):
  resolved — hybrid is now the default for routed reads (see above).

## 2b. Backlash is a plain utility function, not config (decided 2026-07-06)

Backlash is **a utility function with baked-in default parameters** — nowhere near
limits, calibration, or any config/snapshot file. The `backlash` block is removed
from `limits.json` AND from the calibration schema/`calibration.json` (it was read
and validated in both but never consumed at runtime — a fossil). The motion
primitives `move_xy_with_backlash`/`correct_backlash` keep their default params
(`overshoot_um=50`, `settle_ms=100`, `tolerance_um=None`) and read no config. This
retires the "thread calibrated backlash from the snapshot" cluster (LA-01/LM-01):
there is no calibrated backlash to thread. Resolves the merge-review flags MR-01/MR-02
(no backlash block can fail the handshake, none to validate). `limits.json` becomes
`{schema_version, source, constraints, functions}`.

## 2. Backlash is a simple procedure, not acquisition logic

Backlash correction is simple: move somewhere, come back to the same position.

- In the **driver**, it should be a **procedure that lives outside acquisition**.
- In the **controller**, it should be exposed as an **acquisition option for the Leica
  driver** (an option the caller can enable per-acquire), consistent with how the
  mock's `backlash_correction` acquisition option already looks.
- Relevant findings: LA-01/LM-01/OP-02/DD-04 (calibrated backlash wiring), LM-02
  (correct_backlash contract).

## 3. Test strategy: three tiers, and the seam must be tested through the controller

There must be **full tests for (a) real hardware, (b) mock hardware, and (c) offline**.
The tests must include verification that the **zmart-adapter works**, and those tests
should **call through the controller** (`zmart_controller` Session → ops table →
adapter) so the seam itself is what's exercised — not the adapter functions in
isolation only.

## 4. Orphan test scripts may be deleted

The unused one-shot **test scripts** (FD-04's zero-reference list under
`tests/hardware/`) are approved for deletion. Git history preserves them.

## 5. `experimental/` may be reworked

The `experimental/lrp_edits` content may be touched/promoted (RF-05); it does **not**
need to be validated against hardware yet.

## 7. Limits are enforced at the lowest layer (decided 2026-07-05, evening)

Limits must be enforced as low as possible — in the command wrappers around the
native CAM functions — so nothing built on top can bypass them. Consequences:
the function-keyed gate moves from the adapter into `commands/`; **no bundled
default limits file is trusted for enforcement** (a wrong-machine default breaks
safety — the bundled file becomes a template; the notebook creates the real,
machine-local file, and connect verifies it is in place); a **hardcoded physical
backstop** for the motoric stage bounds everything independently; "no limit" is
an explicit `[]`, absent keys fail closed; calibration lives in the same config
area but is applied at the objective-change path. Mock + adversarial offline
gates precede any hardware use. Full plan: `docs/design/limits-enforcement.md`.

## 7b. One `limits.json`; three files per snapshot dir (decided 2026-07-06)

`function_limits.json` and `limits.json` are redundant (the stage envelope appears
in both). Collapse to **one `limits.json`** in the function-keyed format
(`constraints` + `functions` + `backlash`); `function_limits.json` is removed. Both
readers — the motion check (`motion/stage_config`) and the commands gate
(`commands/gate`) — read this single file (envelope from `constraints.stage.*`,
backlash from the `backlash` block). Each machine snapshot directory (mirroring the
driver path) therefore holds exactly three files: `limits.json`, `calibration.json`,
`origin.json`. Limits and calibration are separate concerns applied at different
points (limits = physical envelope at the command gate on every move, objective-
independent; calibration = per-objective translation applied at the objective-change
path), but they co-locate in the snapshot dir. The limits adopt no longer seeds a
bundled `calibration.json` (calibration `bundled_ok=False` too): a fresh-machine
limits adopt writes only `limits.json` and carries forward a *real* prior calibration
if present, never mints one from the template — calibration stays a loud in-memory
fallback until an explicit calibration adopt.

## 6. `confirmed` is best-effort — except acquire's idle gate

- `confirmed` does **not** have to be enforced on command paths: after **3 retries**,
  report the command as unconfirmed and move on (the honest `success` vs `confirmed`
  envelope stays; callers are not required to hard-fail on unconfirmed).
- **Exception — acquire:** the **idle** state must be **confirmed** for acquisition,
  because an acquisition can legitimately take a long time; treating "unknown/busy" as
  ignorable there is not acceptable.
- **No deadline on the idle wait (decided 2026-07-06) — a narrow exception, not a
  general no-deadlines policy.** The wait for confirmed idle is deliberately
  **unbounded** — no timeout, ever. A real acquisition can legitimately take an
  arbitrarily long time; a deadline that fires while it is still genuinely in progress
  would abort a live, valid acquisition, which is worse than waiting. This overrides
  CF-02/CF-03's "needs a real deadline" framing *for this one wait only*: a dead LAS X
  hanging forever is an acceptable failure mode here (nothing recoverable can be done
  about a dead LAS X anyway); killing a slow-but-alive acquisition to avoid that is
  not. Do not add a timeout to `check_idle`/`confirm_acquire`'s idle wait. This does
  **not** change anything else: other waits (command confirmation's 3-retry rule
  above, reader polling, settle waits) keep their existing bounded/best-effort
  behavior — the exception is scoped to the acquire idle-confirmation wait alone.
- Relevant findings: AS-01, LM-02, OP-01-adjacent seam checks, CF-02/CF-03 (superseded
  for the idle wait specifically by the no-deadline decision above; still applicable
  to any other unbounded wait that is not gating a live acquisition).
