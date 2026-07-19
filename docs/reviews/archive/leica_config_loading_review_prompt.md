# Code review request — Leica driver: driver-owned config loading, config ladder, session-scoped origin

You are reviewing a single commit on branch `claude/leica-notebooks-validation-dssuf0`
(commit `1932bd7`) in the ZMART-microscopy repo. All work is inside the Leica driver package:

```
zmart_drivers/leica/stellaris5_y42h93/navigator_expert/
```

This is a **safety-adjacent** change to a real microscope driver: it touches the stage-limits
enforcement gate, the connection path, the frame-origin model, and operator-facing setup notebooks.
The audience for docstrings/notebooks/READMEs is **microscopists and biologists who are learning**,
not software engineers (see the repo `CLAUDE.md`), so also judge operator-facing prose on clarity and
gentleness, not just correctness.

Review thoroughly and adversarially. I care much more about finding real defects, safety regressions,
and behavioral inconsistencies than about style. Assume the offline test suite already passes
(`python -m pytest -q tests/unit calibration/tests` → 985 passed; `python run_ci.py --mock` →
1017 passed) — your job is to find what the tests do NOT catch.

---

## What the change does (intended design)

The change reshapes how the driver loads and enforces its four machine-local configs
(`limits.json`, `orientation.json`, `calibration.json`, and the frame origin). Seven parts:

1. **Driver owns loading.** New `connect_microscope(...)` in `connection/session.py` opens the CAM
   client and loads limits + orientation + calibration, with per-file switches
   `load_limits` / `load_orientation` / `load_calibration` (all default `True`). The zmart adapter's
   `connect()` now delegates to it instead of loading configs itself. Per-connection orientation +
   calibration live in a new registry `connection/session_state.py` (keyed by `id(client)`, sibling to
   the existing `commands/gate.py` registry).

2. **Config ladder — limits ▸ orientation ▸ calibration.** Each layer is bounded by the layers below
   it, never itself: the limits notebook is bounded only by the hardcoded physical backstop;
   `set_orientation`'s stage moves are bounded by limits (not calibration); `calibrate_objective_pair`
   is bounded by limits and *expects* a measured orientation (warn-only if unmeasured), not by
   calibration.

3. **Limits: defaults-fallback instead of fail-closed (SAFETY-CRITICAL — scrutinize hardest).**
   `commands/gate.connect_handshake(client, *, load=True)`: when `load=False`, or when the machine
   `limits.json` fails to validate, the handshake installs the **bundled default** envelope (marked
   `is_fallback=True`, loudly warned) instead of the old fail-closed `GateState(error=...)`. Only if
   even the bundled defaults are unusable does it go fail-closed. A client that never handshook at all
   still refuses fail-closed.

4. **Origin: session-scoped, own folder.** `config/machine.py` gains `origin_dir()` /
   `origin_path()` = `snapshot_root()/origin/origin.json`. `write_origin`/`read_origin` use that
   folder, independent of the dated snapshots. `publish_snapshot` no longer copies origin forward. The
   adapter no longer restores origin at connect (`_restore_persisted_origin` and `_ORIGIN_KEYS`
   deleted); `set_origin`'s docstring/return updated. A fresh connection is an absolute frame until
   `set_origin` runs.

5. **Adapter delegates + routes loaded orientation.** `zmart_adapter.connect()` calls
   `_session.connect_microscope(...)` with load flags read from the connection dict, and reads
   `translations` from `session_state`. The acquire path uses a new `_loaded_orientation(handle)`
   (reads `session_state`, falls back to `rig_orientation()` when absent) instead of calling
   `_orientation.rig_orientation()` directly. `disconnect()` now also `_session_state.uninstall`s.

6. **Objective name refresh + calibration orientation warning.**
   `calibration/core/objective_pair.start_session` captures `session.hardware_objectives = {slot: name}`
   from live `get_hardware_info`, and warns (soft) if orientation is still the shipped placeholder
   (detected by a `_notes` key). `calibration/core/adopt._apply_staging_payload` refreshes each touched
   slot's `name` from those live names. New `calibration/core/model.load_translations(...)`.

7. **Dead legacy removed** (`motion/stage_config.write_limits`/`current_path`/`limits_root`,
   `_atomic_write_json`, and their `__init__.py` exports + tests), plus a stale
   `get_focus_points` expectation removed from the adapter validator test (get_focus_points now lives
   only in the workflow layer, never the adapter).

Decisions that were explicitly chosen by the maintainer (do not flag these as "wrong", but DO verify
the implementation faithfully realizes them): origin is session-scoped with no auto-restore; origin
lives in its own folder; no-limits/invalid-limits falls back to the bundled defaults; calibration
warns (does not hard-refuse) when orientation is unmeasured.

---

## Files to read (primary)

- `connection/session.py` — `connect_microscope`, `_load_objective_translations`
- `connection/session_state.py` — new registry
- `commands/gate.py` — `connect_handshake`, `_build_gate_from_file`, `_install_default_limits`
- `config/machine.py` — `origin_dir`/`origin_path`/`read_origin`/`write_origin`, `publish_snapshot`, module docstring
- `motion/stage_config.py` — legacy removal
- `zmart_adapter/zmart_adapter.py` — `connect`, `_loaded_orientation`, `disconnect`, `set_origin`, the acquire path, `CONNECTION` defaults
- `calibration/core/objective_pair.py` — `start_session`, `_warn_if_orientation_unmeasured`, dataclass field
- `calibration/core/adopt.py` — `_apply_staging_payload`, `adopt_calibration`
- `calibration/core/model.py` — `load_translations`
- `__init__.py` — exports
- Tests: `tests/unit/test_limits_adversarial.py`, `test_zmart_adapter.py`, `test_machine_profile.py`,
  `test_stage_config.py`, `test_connect_microscope.py` (new), `calibration/tests/integration/test_workflows.py`
- Docs: `README.md`, `calibration/notebooks/calibrate_objective_pair.ipynb`

---

## What I specifically want you to check

### A. The limits defaults-fallback (highest priority — this softens a deliberate safety posture)

1. **Can a bad machine file ever GOVERN a move?** Trace `connect_handshake` → `_build_gate_from_file`
   → `_install_default_limits`. Confirm that on ANY validation failure (malformed JSON, wrong schema,
   min>max, NaN/Inf, unknown/missing axis, wider-than-backstop, missing/extra/typo function key, bad
   inline function constraint) the *machine* values are fully discarded and only the bundled defaults
   are installed. Look for any partial-application path where the module-global stage envelope
   (`motion/limits.apply_stage_limits_from_config`) or the gate `FunctionLimits` could be left holding
   the bad file's numbers after an exception mid-way through `_build_gate_from_file`.

2. **Backstop independence.** Confirm the hardcoded per-move backstop check
   (`_check_xy_limits`/`_check_z_limits`, `STAGE_BACKSTOP_UM`) is still independent and still bounds
   every move even when the fallback defaults are in force. Are the defaults themselves guaranteed to
   sit within the backstop (they equal it today — is that assumption load-bearing and safe)?

3. **Never-handshook path.** Confirm a client that never called `connect_handshake` still refuses
   fail-closed in `check_refusal` (state is None). Confirm the adapter always handshakes at connect, so
   through the adapter the only reachable states are "valid file governs" or "defaults govern", never
   "ungated".

4. **`load=False` semantics.** Is `load_limits=False` → default envelope the right, safe reading of
   "don't load limits"? Could a caller reasonably expect "no gate at all", and if so is the current
   behavior surprising? Is it possible to reach an *ungated* state through any public API?

5. **Idempotency / re-handshake.** A second `connect_handshake` on the same client rebinds state and
   the module-global envelope. With the fallback path, does a re-handshake after a file is fixed
   correctly replace the fallback with the real envelope? Any stale module-global left from a prior
   fallback?

6. **Adversarial test rewrite.** I rewrote `test_limits_adversarial.py` from "fail closed" to
   "falls back to defaults". Read the new assertions critically: do they still actually prove the bad
   values are not in force (e.g. the `wider_than_backstop` and `hand_widened` cases assert a move the
   wide file would allow is still refused)? Did I weaken any assertion in a way that would let a real
   regression pass? Is the module docstring's stated policy honest?

### B. Origin session-scoping and relocation

1. **No residual connect-time restore.** Grep for any remaining path that reads the origin at connect
   or otherwise re-adopts a persisted origin into a fresh session. Confirm `handle.origin` starts at
   the all-zero absolute frame.

2. **`origin/` folder vs snapshot listing.** Confirm `"origin"` can never be mistaken for a snapshot
   (`is_snapshot_name`), so `snapshots()`/`latest_snapshot()`/`ensure_snapshot` ignore it. Confirm
   `write_origin` no longer depends on a snapshot existing (works on a fresh machine), and that
   `set_origin`'s removal of the old "no snapshot → memory only" branch is correct (write_origin now
   always returns a real path).

3. **Atomicity & concurrency.** `write_origin` uses a `.json.tmp` + `os.replace`. Is the tmp path
   unique enough (single-instrument-per-process assumption)? Any Windows-specific `os.replace`
   concerns given the driver targets a Windows LAS X PC?

4. **Migration / leftovers.** Old snapshots may still contain `origin.json` from before this change.
   Confirm those are harmlessly ignored (never read), and that there's no place that still reads
   `snapshot/origin.json`. Should there be a one-time migration, or is "ignore and let it rot"
   acceptable? Note any operator-visible confusion (two origin.json locations).

5. **Semantics.** Given origin is now session-scoped, is there any workflow or doc that still implies
   cross-session origin persistence and would now mislead an operator?

### C. session_state registry and orientation routing

1. **Consistency of translations source.** The adapter reads `translations` from `session_state` into
   `handle.translations`. Confirm every consumer (`_objective_delta_um`, get/set_xyz) uses the handle
   consistently, and that nothing still loads translations independently (the old adapter
   `_load_objective_translations` and `_cal_model` import were removed — confirm no dangling refs).

2. **Orientation: loaded-at-connect vs read-at-save.** The adapter now uses `_loaded_orientation`
   (session_state), falling back to `rig_orientation()` when session_state is absent (e.g. test
   handles built without `connect_microscope`). Meanwhile `calibration/core/common.py` still reads
   `rig_orientation()` fresh at capture. Is this split intentional and correct? Could a real session
   ever hit the fallback and silently use a *different* orientation than what connect loaded? Is
   caching orientation for a whole session (vs reading fresh each save) a behavior change any workflow
   depends on?

3. **Lifecycle.** `disconnect` uninstalls both gate and session_state. Reconnect on a new client
   installs fresh. Any leak or stale-id risk given `id(client)` keying and the documented
   single-instrument-per-process invariant? What happens if `connect_microscope` is called twice for
   the same client?

### D. Calibration name refresh + orientation warning

1. **`update_objective(..., name=None)` safety.** In `_apply_staging_payload`, `to_slot` is updated
   with `name=live_names.get(to_slot)` which may be `None`. Confirm `to_slot` is ALWAYS an existing
   slot (so `name=None` won't hit the "cannot create objective slot without a name" raise), given
   `_objective_slot_for_label` requires exactly one match in the loaded config. Is there any path where
   `to_slot` or `from_slot` is new and `name=None` would raise mid-adopt?

2. **Label matching vs refreshed names.** Names are refreshed AFTER `_objective_slot_for_label`
   matches labels against the (possibly stale) base-config names. Confirm the matching still works
   (it matches by magnification token) and that refreshing names can't change which slot a subsequent
   re-adopt matches.

3. **Placeholder detection.** `_warn_if_orientation_unmeasured` treats presence of a `_notes` key in
   `orientation.json` as "unmeasured". Is that a robust signal? Confirm `adopt_orientation` writes
   NO `_notes`, and the shipped default DOES. Is there a false-positive/negative risk (e.g. an operator
   hand-editing the file, or a future schema adding `_notes` for another reason)? Is warn-only the
   right strength, and is the message actionable for a biologist?

4. **hardware_objectives population.** Confirm `objective_by_slot` skips empty/placeholder slots and
   that `{slot: name}` is what adopt expects. Backward compatibility: sessions/stubs without
   `hardware_objectives` (older callers, tests) must still adopt fine via `getattr(..., None)`.

### E. Dead-code removal & exports

1. Confirm nothing in the Leica package (or sibling drivers / workflows) still imports the removed
   `write_limits` / `current_path` / `limits_root` / `write_stage_limits_config` /
   `current_stage_limits_path`. Note: there is a `workflows/target_acquisition/.../retired/tests` that
   monkeypatched some of these — confirm it is genuinely retired/uncollected and not silently broken in
   a way that matters.
2. Confirm `LIMITS_SOURCES` / `_validate_source` still accept every `source` value that any existing
   ProgramData file or fixture may carry (I kept the source constants even though the per-run writer is
   gone). Is dropping the `LIMITS_SOURCE_*` exports from `__init__.py` safe?
3. `__init__.py`: `connect_microscope` added to `__all__` and imported — confirm no star-import breakage
   and that the export list is internally consistent.

### F. Cross-cutting correctness

1. **Import cycles / order.** `connect_microscope` does function-local imports of gate/orientation/
   session_state; `session.py` also imports the calibration model lazily. Confirm no new import cycle
   and that `connection` importing `calibration` (a higher layer) is acceptable per the driver's stated
   dependency direction (README §7). If it inverts the intended layering, flag it.
2. **Connection dict plumbing.** `CONNECTION` gained `load_limits/load_orientation/load_calibration`.
   Confirm the adapter reads them with correct defaults (`connection.get(..., True)`) and that a
   controller passing a partial dict still behaves.
3. **Docs vs behavior.** Verify the README §3/§4/§5/§10, `machine.py`/`gate.py` docstrings, and the
   calibration notebook markdown now match the actual behavior — especially any lingering "fail-closed"
   or "restored across sessions" wording that this change contradicts.

---

## Deliverable

For each finding: the file:line, a concrete failing scenario (inputs/state → wrong outcome), a severity
(blocker / major / minor / nit), and a suggested fix. Rank by severity. Call out explicitly:

- Any path where an invalid/over-wide limits file could still govern a move, or where a session could
  end up ungated.
- Any inconsistency between the connect-time-loaded orientation/calibration and what acquire/save/
  frame-math actually uses.
- Any `update_objective(name=None)` or origin-folder edge case that raises or corrupts state mid-adopt.
- Any operator-facing doc/notebook statement that is now misleading.

If you conclude a given area is correct, say so briefly with the reasoning that convinced you — don't
pad. A short list of real, verified issues is worth far more than a long list of speculative ones.

For deeper context, the original implementation plan is at
`/root/.claude/plans/magical-percolating-noodle.md` (Context + per-file change list + verification).
