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

## 6. `confirmed` is best-effort — except acquire's idle gate

- `confirmed` does **not** have to be enforced on command paths: after **3 retries**,
  report the command as unconfirmed and move on (the honest `success` vs `confirmed`
  envelope stays; callers are not required to hard-fail on unconfirmed).
- **Exception — acquire:** the **idle** state must be **confirmed** for acquisition,
  because an acquisition can legitimately take a long time; treating "unknown/busy" as
  ignorable there is not acceptable.
- Relevant findings: AS-01, LM-02, OP-01-adjacent seam checks, CF-02/CF-03 (the idle
  and acquire waits still need real deadlines so "confirmed idle" cannot become "hang
  forever" — a dead LAS X must produce an error, not an eternal wait).
