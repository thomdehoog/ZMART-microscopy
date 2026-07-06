# Implementation review — limits enforcement at the commands layer

Independent final review of commit `474c3a6` ("feat(limits): enforce limits at
the commands layer with no default fallback") against
`docs/design/limits-enforcement.md` (incl. Amendments 1–7) and
`docs/design/limits-enforcement-review.md` (PR-01..PR-10). Reviewed
adversarially: the goal was to prove the gate bypassable or the migration
dishonest. Paths below are relative to
`zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` unless rooted.

Reviewer changes made on this branch (not committed): one production fix and
two test-suite strengthenings, listed under IR-01 and IR-02. All suites were
re-run after the changes (numbers at the end).

---

## Findings

### IR-01 — NaN pixel target composes a NaN galvo pan that evades both checks (HIGH — FIXED)

`commands/commands.py:1324` (pre-fix). `move_galvo_to_pixel`'s composed-pan
check was:

```python
if abs(new_pan[0]) > _PAN_LIMIT or abs(new_pan[1]) > _PAN_LIMIT:
    raise RuntimeError(...)
```

`abs(nan) > _PAN_LIMIT` is **False**, so a NaN pixel target (`px`/`py` — e.g.
a segmentation centroid of an empty mask) or a corrupt current pan read from
the LRP composes `new_pan = nan` and sails past the angular limit. The
function-keyed gate does not catch it either: the default machine file
(bundled template and `build_function_limits_payload`) maps
`move_galvo_to_pixel` to `null` (reviewed-unlimited), so
`state.limits.check(...)` returns without inspecting the values. The NaN was
then written into the `.lrp` (`lrp_set_pan` stringifies it) and
`load_experiment` — whose key is also `null` — fired it into LAS X. This is
exactly the NaN attack class the commit claims to have closed for moves
(`_require_finite`), missed on the one mutating surface that does not go
through `motion/limits.py`. (`inf` was already refused: `abs(inf) > limit` is
True.)

**Fix (applied):** finiteness check on the composed pan inside `_edit`,
before the angular-limit comparison (`commands/commands.py:1324-1331`,
plus `import math`). Refusal raises inside the transaction, so
`lrp_set_pan` never writes and `load_experiment` never fires; the wrapper
returns its fail-closed `success=False` dict.

**Test (added):**
`test_limits_adversarial.py::test_poisoned_pixel_target_cannot_compose_a_nan_galvo_pan`
(2 params). Verified **red** against the unfixed commit (the poisoned pan
reached `lrp_set_pan`), green with the fix.

### IR-02 — AST completeness sweep missed the raw-receipt fire shape (MEDIUM — FIXED, test-side)

`tests/unit/test_limits_adversarial.py::test_every_dispatching_wrapper_declares_and_calls_the_gate`
flagged only functions referencing `_dispatch` / `_dispatch_setting` /
`confirm_and_fire` / `apply_lrp_change` by name. A new public wrapper in
`commands.py` that builds a model and calls
`api_obj.UpdateAwaitReceipt()` / `UpdateAsync()` **directly** — precisely the
shape `scanfields/files.py:184/258` already uses in this codebase, so a
realistic copy-paste shape — would have shipped ungated without failing the
sweep. **Fix (applied):** the sweep now also treats any
`UpdateAwaitReceipt`/`UpdateAsync` attribute reference as reaching the fire
path.

### IR-03 — no driver-wide guard against a NEW ungated fire module (FLAGGED)

The three-way completeness enforcement covers `commands/commands.py` (AST
sweep + mapping totality + behavioral poisoned-client refusals) and the two
known mutators in `scanfields/files.py` (dedicated AST test). A brand-new
module firing `UpdateAwaitReceipt` on a mutating `PyApi*` object (the way
`files.py` was before this commit gated it) is caught by nothing — a
driver-wide sweep is non-trivial because `readers/api_reader.py` legitimately
fires `UpdateAwaitReceipt` for `Get*` reads and `PyApiPing`. Verified today's
surface is clean (every `UpdateAwaitReceipt`/`UpdateAsync`/`Model.Command`
site outside `commands/`+`scanfields/files.py` is a read: `readers/`,
`config/profiles.py`, `acquisition/files.py`). Recommend a driver-wide AST
sweep with an explicit read-allowlist as a follow-up; policy, not fixed here.

### IR-04 — `gate.uninstall()` is dead code; disconnect leaves gate state installed (NOTE — FLAGGED)

`commands/gate.py:172` is called by nothing (only the test conftest clears
the registry). After `adapter.disconnect`, the client's gate state (and the
strong client reference) persists for the process lifetime; direct
`commands.*` calls with the old client object still pass the gate. Not a
bypass introduced by this change — the commands layer has no session concept
and the handle-level `_require_open` still guards adapter ops; the strong-ref
registry is what makes the id-recycling claim sound (verified: a
never-handshaken client always starts fail-closed,
`test_stale_gate_state_does_not_govern_a_new_client`). Suggest wiring
`disconnect → gate.uninstall(handle.client)` or deleting `uninstall`; policy.

### IR-05 — presence-only gate args: setter/acquire VALUES are not checkable, and the old op param names drifted (NOTE — FLAGGED)

All `set_*` wrappers and `select_job` pass `{"job_name": job_name}`; `acquire`
passes `{"job_name": ...}` only. The old adapter gate passed richer values
(`set_state` got the changeable dict with param `job`; `acquire` got the
resolved options). Consequences: (a) a machine file cannot numerically bound
setter values (e.g. laser intensity) through the gate — only `job_name`; (b) a
constraint written against the OLD param name (`set_state.job`) silently never
checks, because `FunctionLimits.check` skips params absent from the call's
values. No practical regression today — every non-`set_xyz` entry has always
been `null` — and the deviation was declared, but operators authoring
constraints for `set_state`/`acquire` should know only `job_name` (and for
`move_galvo_to_pixel`: `pan_x`/`pan_y`; for `save/load_experiment`: `name`)
are enforceable. Worth documenting the checkable param names per key in the
template; policy.

### IR-06 — `confirm_and_fire` / `_fire_with_receipt` remain in the public API (NOTE — FLAGGED)

`__init__.py:91-92,298` export the dispatch backbone in `__all__`. A notebook
one-liner `drv.confirm_and_fire(client, client.PyApiMoveHardwareXY, ...)`
bypasses the gate — equivalent in power to holding the raw client, which no
in-process gate can defend against, but exporting it advertises the bypass.
No production/repo code calls it outside `commands/` and tests (verified).
Consider un-exporting; policy.

### IR-07 — numpy scalar targets: no production over-rejection (VERIFIED OK)

`_require_finite` accepts `int`/`float` and therefore `np.float64` (a `float`
subclass — verified by execution); it **refuses** `np.float32`/`np.int64`
(fail-closed refusal, not a silent pass) and `bool` (correct). Checked the
real callers: workflow targets go through
`calibration/core/model.py:312-339` which coerces `float(...)`;
`focus.py`/`_acquire.py` positions originate from template/JSON parses
(Python floats) or `float()` coercions; `pick` arrays are `dtype=np.float64`.
No production path feeds `np.float32`/numpy-int targets to `move_xy`/`move_z`.

### IR-08 — minor test-quality gaps (NOTE — not fixed)

- `test_poisoned_move_z_targets_refuse` asserts the refusal dict but not
  "native never fired" (no mock z-position probe; the XY variant does check
  stage position). Structural reading of `move_z` shows the gate+motion check
  precede `_dispatch`, and the `_Untouchable` sweep covers the no-state case.
- `_BAD_FUNCTION_LIMITS_TEXTS["constraint_nan_min"]` carries a no-op
  `.replace("NaN", "NaN")` — cosmetic.

---

## Bypass hunt — verdict: **no bypass found** (after IR-01 fix)

Surfaces walked, each to its fire site:

| Path | Verdict |
|---|---|
| All 26 `commands.py` wrappers | gate called in Phase A, before any model build / client attribute touch (behaviorally proven by the `_Untouchable` poisoned-client sweep over the full `MUTATING_COMMANDS` set) |
| `move_xy`/`move_z` unit conversion | gate + `_check_xy/z_limits` (envelope → backstop, finite/type-strict) inside the same pre-fire try; numeric strings, bools, NaN/inf, None all refuse before `_dispatch` |
| `move_galvo_to_pixel` | gate up front (state check) + composed-pan gate + `PAN_LIMIT` + finiteness (IR-01 fix) inside the transaction, before `lrp_set_pan`; the LRP load itself is additionally gated (`load_experiment`) |
| `dispatch.confirm_and_fire` / `_fire_with_receipt` | no production caller outside `commands.py` (exported though — IR-06) |
| `readers` `PyApiCommand` command channel | fires `Get*` command names only; `PyApiPing`/`GetXY`/`GetJobSettings`/`GetConfocalHardwareInfo`/`GetJobsInformation` — reads |
| `scanfields/files.py` save/load | gated with their own keys before the receipt fires; `transaction.apply_lrp_change` and `strip_restore` route exclusively through them |
| `experimental/lrp_edits` (`reset_pan`, ROI writers) | mutate via `apply_lrp_change` → gated save/load; offline file edits execute only through gated `load_experiment`/`select_job`/`acquire` (documented disposition) |
| `motion/movement.py` (`move_xy_with_backlash`, `correct_backlash`) | route through gated `commands.move_xy` (incl. the overshoot waypoint leg) |
| `acquisition/capture.py`, adapter `acquire`, autofocus procedure | route through gated `commands.acquire`/`select_job`; `lasx_native_autosave` is file collection, fires nothing |
| Adapter `set_xyz` | whole-move pre-flight preserved: gate (both legs) + `_check_xy_limits` + `_check_z_limits` BEFORE any motion; refusals raise per the ops contract |
| Adapter `set_state`/`run_procedure` | ungated at the adapter, but every effect runs through gated wrappers (`select_job`, `move_xy` via `correct_backlash`, `acquire`) — verified refusals surface as RuntimeError in `test_mutating_ops_refuse_without_a_limits_handshake` |
| Adapter `set_origin` | verified it fires **no** native command: reads via readers, writes `origin.json` in place into the newest snapshot (`write_origin` — no `publish_snapshot`, cannot mint limits files); ungated disposition is sound |
| Controller `Session` | thin ops-table forwarding to the adapter; refusal originates at the commands layer (`test_controller_session_bypass_refuses_at_the_commands_layer`) |
| Crafted machine files | template refused (`require_machine_local`), NaN/Infinity/unknown-axis/min>max/truncated/non-JSON/missing-key/unknown-key/wider-than-backstop all refuse the handshake and leave the session read-only (22 parametrized attacks, verified against the validator code, not just docstrings) |
| Template laundering | `publish_snapshot._seed_file(bundled_ok=False)` omits both limits files with no machine-local prior; a calibration-only adopt cannot mint enforceable limits (test verified); a prior machine-local copy is carried forward correctly |
| State abuse | never-handshaken client refuses; failed handshake refuses every key (`state.limits is None` branch); second client isolated; re-handshake rebinds; hand-widened `set_stage_limits` pinned + bounded by backstop and by the machine file's `set_xyz` constraint |

Residual (accepted by the design): a caller holding the raw CAM client can
always fire natively; the gate binds every *supported entry point*, which is
what the maintainer decision requires.

## Gate-state soundness

- **Registry**: `id(client) -> (client, GateState)` with a deliberate strong
  reference — id recycling onto a never-handshaken client is impossible;
  claim verified in code and by test. One-instrument-per-process invariant
  documented consistently in `gate.py`, `motion/limits.py`, and the amended
  `shared/limits/spec.py:40-44`.
- **Failure state**: `connect_handshake` never raises; any failure installs
  `GateState(limits=None, error=...)` — `check_refusal` then refuses every
  mapped key with the recorded reason (code-verified, `gate.py:214-215`).
  Unmapped command name ⇒ `KeyError` (loud programming error, native never
  fires).
- **Thread-safety**: plain dict get/set under the documented single-writer
  convention (same as `commands/dispatch.py`); no torn state possible under
  the GIL for these operations.
- **Errors**: refusals name the command, the path tried, the snapshot root,
  and the notebook factory; no credentials/secrets in any message.
- **Lifecycle gap**: disconnect does not uninstall (IR-04).

## Spec compliance — amendments

| Amendment | Verdict |
|---|---|
| 1. Wrapper→key mapping + completeness test (PR-01) | **Delivered.** `MUTATING_COMMANDS` (28 wrappers → 8 keys), totality tests, AST sweep (strengthened, IR-02), behavioral sweep. Deviation `select_job → set_state`: sound — job selection was already the `set_state` op surface in the old adapter gate. |
| 2. Whole-move pre-flight stays; refusal contracts (PR-02) | **Delivered.** Adapter `set_xyz` checks gate+envelope for BOTH legs before any motion; adapter/controller raise, wrappers return fail-closed dicts (the amended plan's contract; the review's "should raise" alternative was resolved this way and applied consistently). |
| 3. `null` spelling kept, `[]` dropped (PR-03/10) | **Delivered.** Shared spec semantics untouched; template rewritten with the 3 new keys, all `null`. |
| 4. Gate state location pinned (PR-04/09) | **Delivered.** Module registry keyed by client identity; `spec.py` guidance amended in the same change; rebind + second-client tests present. Invariant "asserted" via tests rather than a runtime assert — acceptable. |
| 5. No-fallback covers BOTH files; callers updated (PR-05/06) | **Delivered.** `require_machine_local` for both files; `defaults_path()`/`load()` strict; `preflight.py`, `image_to_stage.py`, `objective_pair.py` run the real handshake and abort with the actionable error; calibration.json fallback intentionally retained; fixtures via `publish_snapshot`. |
| 6. PR-07 surfaces dispositioned | **Delivered.** `save/load_experiment` + `move_galvo_to_pixel` gated with their own keys (galvo pan hole IR-01 found and fixed); `lrp_edits`/autosave/`set_origin` dispositions documented and verified accurate against the code. |
| 7. Backstop (PR-08) | **Delivered.** `STAGE_BACKSTOP_UM` in `motion/limits.py` with the verify-on-rig comment, values pinned to the historical envelope by test; containment checked at the handshake AND per-move after the envelope; `adopt_limits` also refuses outside-backstop envelopes; `set_stage_limits` widening pinned as-is and flagged for the maintainer (matches the declared deviation). |

Declared deviations — verdicts: `select_job→set_state` sound;
save/load-experiment returning `None` on refusal keeps their existing failure
contract (refusal logged at ERROR; `apply_lrp_change` aborts on `None`) —
sound; presence-only gate args — sound today, with the IR-05 caveat.

## Test quality — verdict: strong, migration honest

- The suite (now 104 tests) asserts **refusal semantics**, not non-crash:
  `success is False` + message content, stage position unchanged on the mock,
  envelope never applied after a failed handshake, and the `_Untouchable`
  poisoned client proves the native client is untouched for every one of the
  28 wrappers. Attack classes covered: malformed JSON (both files, 22+13
  variants), NaN/inf/string/None/huge targets, state abuse (no handshake,
  failed handshake, widened memory envelope, widened file, second client,
  stale state), gate abuse (missing key, null-vs-absent), bypass via
  commands/adapter/controller, template laundering, backstop pins. Gap found
  and closed: NaN galvo pan (IR-01).
- **No weakened tests.** Every deleted assertion in the diff was replaced by
  an equivalent or stronger one exercising the real handshake against real
  machine-local files (e.g. `test_connect_configures_stage_limits` →
  `test_connect_runs_the_limits_handshake` with envelope + provenance
  readback; `_load_function_limits` unit tests → handshake-level tests). The
  old boundary pins (130001 / ±201 / 25001) survive verbatim in
  `test_core_driver.py`.
- **Hermetic fixture** (`tests/helpers/limits_fixtures.py`):
  `install_permissive_limits` is NOT autouse — it is installed per specific
  client object by tests about command mechanics, and the autouse
  `_clean_limits_gate` conftest fixture clears the registry around every
  test, so it cannot leak or mask a gate failure in unrelated tests; the
  package-root autouse fixture keeps `SMART_MICROSCOPY_ROOT` per-test tmp.
  `provision_machine_limits` snapshots run the REAL handshake. The mock
  validators provision a hermetic root and run the real handshake too.
- Completeness guards: mapping totality catches an unmapped wrapper at the
  vocabulary level; the AST sweep (post-IR-02) catches both dispatch-helper
  and raw-receipt shapes in `commands.py` plus the two `files.py` mutators;
  the behavioral sweep catches a wrapper whose gate call is unreachable.
  Remaining hole: a new fire site in a new module (IR-03, flagged).

## Suite results (this review's runs, after fixes; artifacts deleted)

| Gate | Result |
|---|---|
| Driver `run_ci.py` offline (lint + tests + coverage) | **PASSED** — ruff clean; 906 passed, 3 env skips, 18 subtests |
| Adversarial suite alone | 104 passed |
| Controller + shared + workflows (repo root) | 296 passed, 61 skipped |
| zeiss zenapi (from its root) | 50 passed, 1 deselected — shared-spec finite change is drift-safe |
| mesospim (from its root) | 130 passed, 11 deselected — own limits module, untouched |
| `validate_hardware.py --mock --allow-xy --allow-z --allow-objective --allow-acquire` | pass=113 warn=0 fail=0 skip=2 (commit claimed 108/0 — count drift only, zero failures) |
| `validate_readers_side_by_side.py --mock --yes` | parity 26/26, 0 API timeouts |
| `validate_zmart_adapter.py --mock` | pass=19 warn=0 fail=0 skip=4 |

Generated artifacts (`hardware_run_report_*.md`, `tests/_report/`) removed.

## Reviewer changes on this branch (uncommitted)

1. `commands/commands.py` — `import math`; finiteness refusal on the composed
   galvo pan in `move_galvo_to_pixel._edit` (IR-01).
2. `tests/unit/test_limits_adversarial.py` —
   `test_poisoned_pixel_target_cannot_compose_a_nan_galvo_pan` (2 params;
   red without the IR-01 fix); AST sweep extended with
   `UpdateAwaitReceipt`/`UpdateAsync` fire detection (IR-02).

## Overall verdict

**APPROVE with the above fixes.** The chokepoint is where the design says it
must be, fail-closed on every failure mode I could construct, the no-fallback
migration is honest, and the backstop is real. One genuine production hole
(IR-01, NaN galvo pan) was found and closed during this review; four policy
items are flagged for the maintainer (IR-03..IR-06), none of which blocks.
