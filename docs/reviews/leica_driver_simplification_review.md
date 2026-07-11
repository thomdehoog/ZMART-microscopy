# Leica driver simplification review — `navigator_expert`

Reviewed 2026-07-11, branch `claude/review-workflows-controller-leica-yd625w`. Scope:
`zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` (production code first, tests second).
Method: every production module was read (the largest — `commands.py`, `confirmations.py`,
`parsers.py`, `objective_pair.py` — in full or in structural passes over every function); every
"dead" claim below was verified by a repo-wide grep for callers, including `.ipynb` notebooks and
the `workflows/` tree; the full offline suite was run (1091 passed, 1 skipped for the missing
LAS X runtime — expected off the rig); and the gate, config loading, parsers, calibration model,
and adapter surface were adversarially probed with hostile inputs against the mock LAS X client.
Nothing under `tests/hardware/` was executed, and no code path that talks to an instrument was
touched. Deliberate choices recorded in `docs/reviews/MAINTAINER_DECISIONS.md` (hybrid readers §1,
limits at the lowest layer §7, unbounded acquire idle wait §6, backlash as plain utility §2b) were
treated as settled and are not re-litigated here.

## 1. Overview

The architecture is sound and layered the right way. All live commands funnel through one dispatch
backbone (`commands/dispatch.py::confirm_and_fire`) driven by per-command frozen profiles
(`config/profiles.py`); a fail-closed limits gate sits below everything at the command wrappers
(`commands/gate.py`, maintainer decision §7) with a hardcoded physical backstop underneath that
(`motion/limits.py`); state reads route through one capability table with api/log/hybrid legs
(`readers/router.py` + `capabilities.py`, decision §1); and the `zmart_adapter` is a clean ops
table over all of it — the workflow layer touches only the 13 controller ops. The three setup
notebooks (limits, orientation, calibration) are the only other entry points.

Size: ~21,600 production lines, ~25,400 test lines (~0.86:1 offline-test:prod once the intentional
live-hardware harness is excluded — healthy), plus 137 generated report files (3.2 MB) still
tracked in git. The commands layer is 5,134 lines, readers 2,175, scanfields 2,918,
experimental/lrp_edits 1,681, acquisition ~2,470, calibration core ~2,250, adapter 1,368.

Verdict: **structurally healthy, locally overweight**. The safety architecture is genuinely good
and the docs are unusually caring. The bloat is not architectural; it is sediment from the review
rounds: a retired workflow tree that pins ~400 driver lines alive, a 1,681-line "experimental"
mirror API with ~130 live lines, dead knobs and double wiring left by successive hardening passes,
a handful of compatibility shims for callers that no longer exist, and 3.2 MB of committed run
logs. Roughly **2,500–3,500 production lines and ~2,000 test lines could be deleted with no loss
of capability**, most of it in a few concentrated places.

## 2. What this tree could lose entirely

The deletion budget, largest first. SAFE = mechanical and behavior-preserving today;
JUDGMENT = needs one named decision, after which the deletion is also mechanical.

| # | What | Lines / size | Class | Blocking decision |
|---|---|---|---|---|
| 1 | `tests/_report/` tracked artifacts (63 run reports, 63 driver logs, jsonl, ci_summary) | 137 files, 3.2 MB | SAFE | none — already gitignored (`.gitignore:20`); `git rm -r --cached` |
| 2 | `experimental/lrp_edits/` dead mirror API: all of `z.py` (270), `general.py` (151), `focus.py` (151), the unconsumed `scan.py` setters (~170) and `roi.py` authoring helpers, keeping the ~130 live lines (`galvo_pan_for_pixel`, pan get/set, `_set_job_attr`) | ~1,200–1,400 | JUDGMENT | decision §5 allows rework; resolve the README "load-bearing" vs `experimental/` mismatch by promoting the live core and deleting the rest |
| 3 | `tests/hardware/probe_four_readers.py` + its pytest gate + run_ci step (superseded by `validate_readers_side_by_side.py`, which does the same reads with pass/fail gating; the router decision it informed is settled, `profiles.py:87–118`) | ~750 | JUDGMENT | decision §4 already approves deleting orphan hardware scripts |
| 4 | Driver code alive only because `workflows/target_acquisition/workflow/retired/` (12,766 lines, quarantined) still imports it: `strip_template_in_place` (strip_restore.py:165–258), `parse_rgn_tile_colors` + per-tile bounding boxes + carrier/timelapse parsing (parsers.py:743–796, 859–896), `translate_*_between_objectives` + `set_reference` (model.py:260–333), four `LIMITS_SOURCE_*` constants + `_validate_source` (stage_config.py:31–44, 136–144), `objectives.validate_slots`, `gate` freeze/thaw + `stage_cfg` status plumbing | ~420 driver lines | JUDGMENT | declare `retired/` dead; each deletion is then SAFE |
| 5 | Test boilerplate: parametrize `TestConfirmFunctions` and `TestRetryBackoff` in `test_core_driver.py` (2,738 lines, 205 tests), table-drive `test_set_*_model`; the three stale `BENCH_PROMPT*.md` files pinned to a deleted branch/commit | ~800–900 | SAFE/JUDGMENT | none for the parametrization; prompts can move to docs or go |
| 6 | Commands-layer sediment: profile-side `confirm_fn` double wiring, dead `_dispatch` knobs, no-op poll-window injection, duplicated error-check tail, repeated timing-dict literal (details in §4) | ~200–230 | SAFE | none |
| 7 | The 16 thin `_confirm_*` wrappers over `_run_spec` + 3 bespoke loops that fit the shared skeleton (confirmations.py) | ~220 | JUDGMENT | pure dedupe, but touches confirmation code — do it in one reviewed pass |
| 8 | Dead reader tails: `api_reader.get_fov`/`get_base_fov`/`get_job_by_name` (356–401), `log_reader` parity tail (569–573, 609–623), the stale `parse_lrp` re-export shim (parsers.py:57–59) | ~85 | JUDGMENT (shim: SAFE) | zero callers anywhere, but per the maintainer's rule every change inside readers/ is the maintainer's call — the three read paths themselves are untouched |
| 9 | Retirement debris from the companion-XML era: `ome.py` `check_ome_xml_file`/`fix_ome_xml_file` (208–234, 407–461), `ome_canonical.pixels_dims`/`companion_xml` (74–89, 197–210), `product.PositionIndex` + `SavedAcquisition.xml_paths` | ~130 | SAFE/JUDGMENT | `pixels_dims`/`companion_xml` are SAFE now; the rest needs the "no sidecar layout ever returns" call |
| 10 | `config/machine.py` shims: never-invoked `migrate_legacy_snapshots` (161–194), the always-False second tuple element of `resolve()` (220–234), the unused `kind` arg of `require_machine_local`, test-only `read_origin` | ~110 | JUDGMENT | the migration is delete-or-wire; the shims are SAFE |
| 11 | `calibration/core/model.py` `load_translations` (219–232, zero callers; `session.py:124–127` re-implements it inline) | ~14 | SAFE | none |
| 12 | Operator-inspection tooling with no in-repo caller but README promises: `parse_lrp` deep parser (~250), `save_and_read_lrp` (~32), `get_lasx_settings` + XML helpers (~110), `select_job` pure api/log confirm modes + `prime_cluster` machinery (~135) | ~500 | JUDGMENT | keep if the operator-notebook promise is real; the select_job modes are bench diagnostics for the hybrid race and the safest to keep |

Ranked honestly: items 1, 3, 5, 6, 8 are near-free. Item 2 is the single biggest win. Item 4 is
one decision that unlocks a dozen small deletions across five modules — the retired workflow tree
is the root that keeps most of the driver's fossils watered.

## 3. Wiring

The adapter's surface maps cleanly onto the layers below; nothing calls a symbol that does not
exist and no signature drift was found. Verified call-by-call: `connect` →
`connection/session.connect_microscope` (which runs `gate.connect_handshake`, loads orientation
and calibration into `connection/session_state`); `set_xyz`/`get_xyz` → `readers.get_xy` /
`get_job_settings` (api-pinned), `gate.check_refusal`, `motion.limits._check_xy/z_limits`,
`motion.movement.move_xy_with_backlash`, `commands.move_z`; `acquire` →
`scanfields.get_template_state`/`strip_template`, `commands.select_job`,
`motion.correct_backlash`, `acquisition.capture.acquire`, `acquisition.save.save`;
`get_info` → `scanfields.save_experiment`/`parse_scan_positions` (keyword signatures match);
`set_origin` → `config.machine.MACHINE.write_origin`; `get_state` → `gate.describe` +
`_setup_readiness` over `session_state`. The offline suite exercises this seam end-to-end
(`test_zmart_adapter.py`, 1,695 lines) and the whole suite is green.

Config plumbing flows as documented: `limits.json` resolves through ProgramData
(`machine.resolve`), is validated whole by `stage_config.load`, containment-checked against
`STAGE_BACKSTOP_UM`, then installed **twice from the same payload** — as the gate's function
policy and as the module-global stage envelope. Adversarial probing confirmed every malformed
file (wrong types, min>max, wider than backstop, missing keys, unknown keys, non-JSON, empty)
falls back to the bundled defaults loudly, and moves stay bounded in every case (§8).

Three wiring blemishes, none broken:

- **Duplicate definition of the same envelope check.** One `set_xyz` from a workflow is
  range-checked up to four times: adapter pre-flight (gate + `_check_xy_limits`,
  `zmart_adapter.py:618–631`) and again inside the wrapper (`commands.py:1207–1210, 1462–1467`)
  — both layers reading the same numbers from the same file. The adapter's copy is documented,
  deliberate whole-move atomicity (keep it); the wrapper-internal gate-plus-envelope pair is a
  genuine 100 % overlap *except* that `_check_*_limits` alone carries the hardcoded backstop.
  If one goes, keep `_check_*_limits` and reduce the gate's `set_xyz` role to handshake state —
  but §7 names the gate as the chokepoint, so this is the maintainer's call, not a cleanup.
- **A phantom defense.** `move_galvo_to_pixel` re-calls the gate mid-transaction with the
  composed pan values and a comment claiming "the machine file may constrain the absolute pan
  further" (`commands.py:1374–1380`). It cannot: `LeicaLimits.check` (gate.py:211–237) discards
  values for any function outside `set_xyz`/`set_objective`/the setter keys, and
  `stage_config.validate_payload` *rejects* a limits file containing a `move_galvo_to_pixel`
  entry. The real pan safety is `PAN_LIMIT` plus the finiteness check just above. Fix the comment
  or drop the second call; the adversarial test's docstring (`test_limits_adversarial.py:292`)
  repeats the same fiction.
- **Dual import identity.** The package is importable both as top-level `navigator_expert` (the
  machine dir on `sys.path`; `__init__.py:133–140` then adds the repo root) and as
  `zmart_drivers.leica...navigator_expert`. If one process ever imports it under both names, the
  gate registry and session state exist twice and a handshake under one name does not gate the
  other. Today every caller uses the top-level name, so this is a loaded footgun, not a bug —
  worth a guard or a one-line warning in the README.

Orphan subsystems (reachable from no entry point at all): `experimental/lrp_edits/z.py`,
`general.py`, `focus.py`; the `api_reader`/`log_reader` fov/job-by-name tails; and the items in
§2 row 4 once `retired/` is declared dead. Everything else is reachable from the adapter, the
notebooks, or `run_ci.py`.

One cross-module smell rather than a wiring break: the adapter calls the underscore-private
`_limits._check_xy_limits`/`_check_z_limits`, and the top-level `__init__.py` imports privates
(`_readback`, `_check_api_error`, `_safe_float`, `_stage_limits`, …) purely so
`test_core_driver.py` can reach them through the facade. Tests should import from the defining
modules; the facade should export only the public surface (~15 lines, SAFE, and it stops
advertising internals to operators reading `dir(drv)`).

## 4. Findings

Ordered by value. Line estimates are net of any replacement code.

**F1. Committed generated artifacts — `tests/_report/` (SAFE, 3.2 MB / 137 files).**
`git ls-files` confirms 137 tracked files under
`navigator_expert/tests/_report/` — driver logs, per-run hardware reports, `ci_summary.json` —
all regenerated by `run_ci.py` (its docstring says so) and already covered by `.gitignore:20`;
they were committed before the rule existed. Nothing reads historical files: the only reader
(`run_ci.py:341–348`) filters to reports written by the current run. `git rm -r --cached` the
directory. If `BENCH_EVAL_2026-07-07.md` is human-authored and wanted, move it to `docs/`.

**F2. The retired workflow tree is the fossil root (JUDGMENT, ~420 driver lines + clarity).**
`workflows/target_acquisition/workflow/retired/` (12,766 lines) is outside this review's scope,
but it is the *only* caller of a dozen driver symbols (§2 row 4 lists them with line refs). Every
prior review round left these "in case retired/ comes back". One explicit decision — retired/ is
history, git remembers it — converts all of them into safe deletions and ends the recurring
"is this dead?" analysis cost. This is the highest-leverage single decision available.

**F3. `experimental/lrp_edits/` — promote the 130 live lines, delete the rest (JUDGMENT,
~1,200–1,400 lines).** Production reaches exactly `galvo_pan_for_pixel`,
`roi_translation_to_pan`, `lrp_get_pan`/`lrp_set_pan`, and the `_set_job_attr` family (via
`commands.move_galvo_to_pixel`). Grep over `.py` and `.ipynb`: zero notebooks, zero workflows,
zero controller use of anything else — `z.py`, `general.py`, `focus.py` in their entirety, the
`scan.py` speed/format/rotation setters, and the ROI authoring helpers are a parallel file-based
mirror of the live `set_*` API that nobody drives. Meanwhile the README (§6) declares the package
"load-bearing … not 'unstable'", contradicting its `experimental/` quarantine. Recommended shape:
move the pan/ROI math the driver actually uses into `scanfields/` (it edits scanfield LRP files —
that is where a reader would look), delete the rest, and drop the eleven facade re-exports of
never-called names. Maintainer decision §5 explicitly permits this rework. Readability gain is
real: the current facade offers a biologist ~30 `lrp_*`/`make_*` names of which zero are needed.

**F4. Commands-layer sediment from the hardening rounds (SAFE, ~200–230 lines).**
Each of these is a knob or wire that successive automated passes added or preserved and nothing
uses:

- *Double confirm wiring.* `config/profiles.py:32–57` imports all 24 confirm functions and binds
  them as `confirm_fn` on every profile; every wrapper in `commands.py` then overrides with a
  target-bound partial, so the profile side is unreachable (the profile docstring admits it:
  "commands always override this", profiles.py:170–172). Remove the profile bindings and the
  fallback branch (`commands.py:213`). ~70 lines, and one behavior is defined in one place again.
- *Dead retry knobs.* `retry_backoff`/`retry_escalate` are threaded through
  `dispatch._fire_block`, `confirm_and_fire`, `CommandProfile`, and `_dispatch` overrides
  (`commands.py:159–161`), yet no profile and no production caller ever sets them — only
  `test_core_driver.py` (six near-identical tests, each repeating the same 12-line patch block
  with the same comment verbatim). Delete the exponential-backoff machinery and its tests, keep
  the plain immediate retry. ~40 lines production, ~200 test.
- *No-op poll-window injection.* `commands.py:215–228` plus `_has_bound_keyword` exist to inject
  a per-profile `confirm_poll_s` into confirm partials via partial-introspection, but no profile
  deviates from the shared default and every confirm already defaults to `CONFIRM_POLL_S`
  internally (confirmations.py:312–313). ~22 lines of indirection a reader must decode for zero
  behavior.
- *Copy-pasted error-check tail.* `_scan_resonant_error_check` (commands.py:336–346) duplicates
  `_default_error_check`'s classification/logging tail verbatim; delegate after the no-change
  special case. ~15 lines.
- *Repeated timing literal.* The identical four-key timing dict is built six times in
  `dispatch.py` (276–283, 299–307, 341–349, 362–369, 433–441, 446–454); one small helper
  collapses them. ~30 lines.
- *Dead spec field.* `ConfirmSpec.default_tolerance` (confirm_specs.py:147) is read only by a
  test that asserts it matches the wrapper signature default — one dead copy checked against
  another; tolerances actually come from profiles. Tolerances are currently defined in three
  places; make it one. ~10 lines plus the test.

**F5. Half-finished confirmation dedupe (JUDGMENT, ~220 lines).** `confirmations.py` was
refactored to the good `CONFIRM_SPECS` table + `_confirm_readback` skeleton, but stopped halfway:
16 thin 8–14-line `_confirm_*` wrappers still forward fixed arguments to `_run_spec`
(lines 471–483, 591–603, 671–753, 761–796, 888–970), and three bespoke loops (`_confirm_zoom`,
`_confirm_image_format`, `confirm_objective`) re-duplicate the exact skeleton they sit next to,
differing only by a label or message detail. Finish the refactor: bind
`partial(_run_spec, "zoom", …)` at the call sites (natural after F4's first bullet) and fold the
three loops into the skeleton. Behavior-identical; `test_confirm_specs`'s wrapper/table
correspondence check gets rewritten once.

**F6. Readability: the biologist-facing surface vs. the machinery (JUDGMENT, mostly free).**
The operator-facing layers (session.py, movement.py, orientation/, the notebooks, the README) are
exemplary — calm, explanatory, exactly per CLAUDE.md. The machinery underneath is another
register entirely: `confirm_select_job.py` speaks of "transition-admissible evidence",
"inadmissible baseline", "source-coherent no-op proof"; `router.py` of "capped single-flight
legs". A maintainer can learn it, but nobody could confidently change `confirm_select_job.py` in
six months without a day of archaeology — and its api/log pure modes plus the default-off
`prime_cluster` machinery (~135 lines, confirm_select_job.py:258–370) are exercised by nothing in
production (`selected_job_confirm_source` is hard-wired `"hybrid"`, `prime_cluster` default
False, only a test sets it True). The hybrid race itself is bench-justified and stays (decision
§1); the question to the maintainer is whether the pure modes are living diagnostics or removable
scaffolding. Two smaller register fixes are free: `_reading_value_after`
(confirmations.py:250–258) carries an explicit test-accommodation branch in production ("tests
sometimes patch routed readers with their old plain return shape") — fix the fixtures instead;
and gate.py tells its defaults-fallback story three times (module docstring 50–59,
`_install_default_limits` 372–397, `connect_handshake` 427–435) — tell it once, ~30 lines.

**F7. `calibration/core/objective_pair.py` intra-file duplication (JUDGMENT, ~130 lines).**
The core math is ~60 lines and fine. The ceremony around it repeats:
`measure_parfocality_reference` (571–651) and `measure_parfocality_target` (659–740) share ~55
lines verbatim (one `_measure_parfocality(session, role)` helper); lines 813–823 inline-copy the
existing `_clear_parcentricity_target` helper under a comment that restates it; the
IPython-display/close boilerplate appears three times; the report and summary dicts repeat ~15
formatted fields. A behavior-preserving pass takes the file from 1,068 to ~930 lines and makes
the four-cell notebook flow much easier to follow. Keep the invalidation-ladder comments
(477–484) — they are load-bearing.

**F8. Companion-XML retirement debris (SAFE ~45, JUDGMENT ~85).** The flat no-sidecar layout is
the contract (`product.py:1–6`, `save.py:118–119`), but the sidecar era left:
`ome_canonical.pixels_dims` + `companion_xml` (74–89, 197–210 — zero callers, SAFE),
`ome.check_ome_xml_file`/`fix_ome_xml_file` (208–234, 407–461 — callers are one test file and
mocks asserting they are *not* called), `product.PositionIndex` (facade-exported, test-only) and
`SavedAcquisition.xml_paths` (never populated; docstring admits "retained for back-compat";
README still advertises it at line 325). Delete the SAFE pair now; the rest goes with one "the
sidecar layout is not coming back" decision.

**F9. `config/machine.py` compatibility shims (SAFE ~10, JUDGMENT ~100).**
`migrate_legacy_snapshots` (161–194) is a migration nothing invokes — flagged by two prior review
rounds (LM-27, FD-08) and still unwired; wire it into `ensure_snapshot()` or delete it, because a
migration that never runs silently ignores any real legacy snapshot. `resolve()` returns a tuple
whose second element "is always False, kept for older callers" — the callers no longer exist;
return a `Path`. `require_machine_local`'s `kind` argument is accepted and discarded.
`read_origin` has no Leica caller. Each shim is the same disease: a hardening round preserved
compatibility with code that had already been deleted.

**F10. Reader housekeeping — all JUDGMENT by the maintainer's rule; the three read paths stay.**
The API reader, the log reader, and the hybrid router that combines them are essential core
(decision §1); nothing here proposes removing a path. Within that boundary: (a)
`api_reader.get_fov`/`get_base_fov`/`get_job_by_name` (356–401) and `log_reader.get_fov`/
`get_base_fov`/`read_zwide_um`/`get_job_by_name` (569–573, 609–623) predate the router, which
derives these via `derived.py`; repo-wide grep finds zero callers outside their own tests
(~80 lines). (b) `router.get_job_by_name`/`get_fov`/`get_pending_dialog` (~35 lines) are
reachable only from the four-reader probe harness (§2 row 3) and go with it. (c) A shape idea,
not a deletion: router.py's six public wrappers (`get_xy`, `get_jobs`, `get_hardware_info`, …,
lines 358–520) are the same eight-line body repeated with only the datum name and kwargs
changing; since `capabilities.DATUMS` already names every datum, the wrappers could be generated
from the table (or collapsed to one `read(datum, client, …)` plus thin aliases), keeping the
exact same three-path behavior and public names while removing ~120 lines of repetition — the
same table-drives-the-boilerplate move the confirmations layer already made. Separately and
outside readers/: the comment at `parsers.py:57–59` re-exports `parse_lrp` "so the lrp_edits
package can keep importing it" — it does not; the premise is false (3 lines, SAFE).

**F11. Test-suite trims (SAFE ~400–500, JUDGMENT ~1,150).** Details verified against the tree:
`test_core_driver.py` (2,738 lines, 205 tests) contains ~40 near-identical confirm-function
bodies a `(fn, readback, expected)` table collapses (~200 lines), the six retry-backoff clones
(~200, deleted outright under F4), and ~18 four-line `test_set_*_model` clones (~90).
`calibration/tests/integration/test_workflows.py` (2,761) could table-drive its six rerun
invalidation tests and slice-artifact trio (~150–250) but reads well as is. `probe_four_readers`
(§2 row 3) and the three stale `BENCH_PROMPT*.md` files (~408 lines, pinned to a deleted branch
and commit) go. Keep unchanged: `test_limits_adversarial.py` (1,088 lines — despite the name it
is the parametrized safety net for the gate: fail-closed before handshake, backstop containment,
hand-widened-file attacks, and an AST sweep guaranteeing no wrapper ships ungated),
`mock_lasx_api.py` (a behavioral fake whose realistic vendor error strings are load-bearing for
the transient/permanent classifier), and the hardware validator set minus the probe.

**F12. Doc drift (SAFE, small).** The README is impressively accurate overall; four real drifts:
(a) README §3 line 79 says `machine.py` resolves "calibration (image↔stage matrix, per-objective
translation)" — the matrix is gone; `calibration/README.md:16` states explicitly that "no
image-to-stage matrix lives here". (b) README §6 line 325 advertises `SavedAcquisition.xml_paths`,
which is never populated (F8). (c) README §6 declares `experimental/` load-bearing while the
package name and module headers say experimental (F3 resolves this either way). (d)
`MAINTAINER_DECISIONS.md` §7b describes `limits.json` as `{schema_version, source, constraints,
functions}` — the shipped file is now fully flat with none of those wrapper keys; worth a
one-line addendum so the decisions record matches the code it governs. Module docstrings
otherwise match behavior; the long prose is mandated by CLAUDE.md and mostly earns its place.

**F13. Adapter acquire validates options after output-root discovery (SAFE, ordering only).**
`zmart_adapter.acquire` resolves `output_root` (line 843) before `_with_defaults` validates the
options dict (845), so a caller's typo in `options` surfaces as an unrelated "output_root could
not be discovered" error when AutoSave discovery also fails. Validate options first; three lines
move. Related known wart, already documented as a gotcha: a bad `acquisition_type` raises in
`Naming` *after* the scan fired, wasting the capture — moving the `Naming` construction before
`_capture.acquire` would fix the waste for free.

**F14. Hardcoded tunables that belong in the profiles/config layer (JUDGMENT, no lines saved —
this one adds a few).** The maintainer's design rule is that every tunable a user or a different
machine might change lives in profiles/config. The config ladder itself is good and carries most
of them; these are the stragglers found while reading, each with a suggested home:

- `utils.py:76–77` — `PAN_LIMIT = 0.00775` and `GALVO_FIELD_FRACTION = 0.667` are **measured,
  machine-specific galvo numbers** hardcoded in a shared utils module. These are the clearest
  case: they belong with the machine's other measured values (a galvo block in the machine
  snapshot, or at minimum `LasxApiProfile`'s sibling). A different Stellaris will have different
  values and today would need a source edit.
- `utils.py:25–27` — `RECEIPT_TIMEOUT = 2` and `CONFIRM_POLL_S = 3` live in utils; profiles
  reference them as defaults. Moving the definitions into `config/profiles.py` makes profiles the
  one tuning surface the README already advertises.
- `dispatch.py:59` — `ECHO_SETTLE_TIMEOUT_S = 1.0`, module-level with a comment that it is read
  at call time "so tests can shrink it"; that is a profile field wearing a workaround.
- `api_reader.py` signature defaults (`timeout=1.0, poll_interval=0.01, max_retries=3` on every
  reader) duplicate what `StateReaderProfile` already owns for routed calls; direct callers get
  the hardcoded copies. One source: let the raw readers default from the profile too.
- `prechecks.check_idle` — poll sleep `0.05` and `heartbeat=30.0` (the OBJECTIVE profile binds
  `timeout` but not `heartbeat`).
- `scanfields`: `strip_restore._RESTORE_SAVE_TIMEOUTS = (120, 120, 180, 240)`, the
  `save_timeout=120` defaults, `transaction.apply_lrp_change`'s `confirm_delays=(2, 4, 8, 16)`,
  and `files.save_experiment(timeout=30)` vs the adapter's own `timeout=60` at
  `zmart_adapter.py:1129` — four escalation ladders tuned on the bench, none reachable from
  config. A small `ScanfieldsProfile` would hold them.
- `ome_canonical.py:29–30` — `JOB_SETTINGS_READ_TIMEOUT_S = 1.0`, `JOB_SETTINGS_API_TIMEOUT_S =
  0.25`; `acquisition/files.py`'s `DEFAULT_EXPORT_*` waits (exposed as `save()` params but not
  profile-backed); `zmart_adapter/info.py:17`'s output folder name `"ZMART-microscopy"`.

Two deliberate exemptions, so nobody "fixes" them: `motion.limits.STAGE_BACKSTOP_UM` is
hardcoded **on purpose** — it is the file-independent safety layer and must never be
configurable; and the backlash parameters (`overshoot_um=50`, `settle_ms=100`, `passes=3`) are
baked-in by explicit maintainer decision §2b ("backlash is a plain utility function, not
config").

**Simplifying refactors worth sketching (beyond deletions).** (1) *Finish the confirm table*
(F5): before — profile binds `_confirm_zoom`, wrapper rebinds `partial(_confirm_zoom, …)`,
`_confirm_zoom` forwards to `_run_spec("zoom", …)`, spec row holds the extractor; after — wrapper
binds `partial(_run_spec, "zoom", …)`, spec row unchanged. Three definitions of one behavior
become one; the table remains the single source of truth. (2) *One envelope check per layer*
(Wiring §3): wrapper Phase A keeps `_limits_refusal` for handshake state and `_check_*_limits`
for numbers+backstop; the gate's `set_xyz` numeric ranges become the single place only if the
maintainer re-reads §7 that way — otherwise leave as is and delete nothing here. (3) *Flatten the
machine-config ladder* (F9): `resolve()` returning a bare `Path` ripples through three callers and
removes tuple-unpacking noise from every read. Not recommended: merging api_reader/log_reader
(decision §1), collapsing GateState/GateStatus/LimitsStatus (the detached-status split is what
keeps test code from mutating live gate state), or touching the dispatch backbone's shape.

## 5. Real bugs (flagged, not fixed)

Found by adversarial probing (§8) and code reading, ranked by how plausibly a real operator hits
them. None is a stage-safety hole — in every motion-relevant case the layered checks fail closed.

1. **Locale decimal commas silently corrupt tile sizes 100×.**
   `parsers._parse_size_string` (parsers.py:75–102) strips every non-digit/non-dot character, so
   an `imageSize` of `"290,63 um x 290,63 um"` — the format a German/Dutch-locale LAS X can emit —
   parses as **29063.0 µm** instead of 290.63 µm. Reproduced:
   `_parse_size_string("290,63 um x 290,63 um")` → `{'x': 29063.0, …}`. Tile sizes feed the
   adapter's `get_info()` positions and geometry planning. Plausible on any non-English rig.
2. **Calibration translations are never checked for finiteness.** `validate_calibration`
   accepts `translation_um: [NaN, 0, 0]` on any non-reference slot and `update_objective`
   writes it (model.py:93–108, 180–195; reproduced — NaN config validates and
   `get_translation_um` returns `(nan, 0.0, 0.0)`). A NaN reaching the adapter makes `get_xyz`
   return NaN frame coordinates *silently* (`_delta_or_warn` only warns when translations are
   missing, not non-finite); a NaN *move* is caught by the gate's range check (verified: refused).
   One `math.isfinite` sweep in `validate_calibration` closes it.
3. **Strict type equality in `allowed` lists refuses valid operator input.** gate.py:205 uses
   `type(value) is type(candidate)`, so a limits file with `{"allowed": [2.0, 4.0]}` refuses
   `set_zoom(…, 2)` (reproduced: "set_zoom=2 not allowed; expected one of [2.0, 4.0]"). Fail-closed
   direction, but a biologist typing `2` at the scope gets refused for a reason the message does
   not explain. Accept int↔float numeric equality (bools excluded) or document it.
4. **Slot-numbering mismatch between bundled calibration and limits.** The shipped
   `calibration/defaults/calibration.json` carries slots `"0","1","2"` (with this rig's measured
   µm values), while `limits/defaults/limits.json` allows `objective_slot` 1–6 and the mock uses
   1-based slots. If the rig truly reports a slot 0, the gate refuses `set_objective` to it; if it
   does not, the bundled calibration's slot 0 is a stale entry. Also note
   `MachineProfile.resolve_calibration` seeds every *new named* calibration set from this
   rig-measured file, so a fresh lens setup starts pre-populated with another setup's numbers
   (marked unmeasured, so preflight flags it — but the values still travel).
5. **`diagnostics=True` loses the one failure it was built to explain.** On an API-read timeout
   `_capped_api_read` returns `None` and `_route_read` propagates bare `None` even with
   `diagnostics=True` (router.py:126–129, 228–231), contradicting the documented
   error-carrying-Reading contract at router.py:220–224. Timeout — the hung-CAM case the whole
   machinery exists for — is the one mode invisible to diagnostics callers.
6. **Reset-only `set_z_stack_definition` refuses with a wrong message when a limit is
   configured.** A pure reset sends `values=[]`; `LeicaLimits.check` then raises "has a configured
   limit but the wrapper supplied no value" (gate.py:230–235; reproduced). A reset commands no
   constrained value; the refusal (and its "programming error" framing) is wrong, though only
   reachable when a machine file actually constrains that setter.
7. Minor, listed for completeness: `ome.fix_ome_tiff` appends the relocated tag-270 value without
   TIFF word alignment (ome.py:387–392) and rewrites the file byte-for-byte even when there is
   nothing to fix (329–339, 359–369); `_ascii_channel` silently drops a non-ASCII channel name to
   `None` instead of transliterating like its sibling `_ascii` (ome_canonical.py:393–420 — a
   "µGFP" channel loses its name); `log_reader.get_jobs` can list a job under an ambiguous
   duplicate name despite "fails closed" docstrings (log_reader.py:386–391); the confirmation
   race can report a leg "still pending" that completed in the final tick
   (confirmations.py:137–160, cosmetic); `roi.make_ellipse` emits `n_points+1` vertices against
   its docstring.

## 6. Overengineered-looking but KEEP

These earned their weight; do not simplify them:

- **The layered motion safety**: gate fail-closed state → machine envelope → hardcoded
  `STAGE_BACKSTOP_UM` checked per-move after the envelope, plus `_require_finite` refusing
  NaN/inf/bool/strings (motion/limits.py). Probing confirmed every layer does its job, including
  boundary inclusivity and the "hand-widened file cannot authorize a move the backstop forbids"
  property. Decision §7 territory.
- **The defaults-fallback ladder in `gate.connect_handshake`** — twelve hostile-file probes all
  degraded loudly to bounded defaults, never to an ungated or dead session. The provenance marker
  (`source: machine` vs `defaults`) correctly kept a hand-copied unmarked file from counting as
  measured, and `_setup_readiness` surfaces exactly that.
- **The three-path reader stack as such** — the API reader, the log reader, and the hybrid
  router that races them are essential core, not redundancy to be deduplicated (maintainer
  decision §1): the two sources go stale on *different* fields, which is exactly why both exist.
  The select_job hybrid confirmation race carries dated bench evidence in the profile comments
  ("api leg measured-wrong on the real scope") — the kind of fact that vanishes if this code is
  simplified away. Reader findings in this report (F10) are housekeeping and shape only, and all
  marked JUDGMENT.
- **The unbounded acquire idle wait and never-refire posture** (profiles.py ACQUIRE,
  `check_idle(timeout=None)`) — deliberate per decision §6: a real acquisition has no upper
  bound, so a deadline would abort live, valid acquisitions. Not a missing timeout; do not add
  one.
- **`strip_restore.py`'s backup/rollback/count-verify ladder and sidecar-only stripping** — it
  protects the operator's hand-drawn template, and every branch encodes an observed failure.
- **The adapter's whole-move pre-flight** duplicating the gate — both legs checked before either
  fires, so a doomed z leg can never strand the stage at a new XY with old focus.
- **Atomic tmp-file writes everywhere** (materialize, save's summary, model.py with fsync,
  machine snapshots with monotonic-timestamp guard) — each protects operator data.
- **`test_limits_adversarial.py` and `mock_lasx_api.py`** — the safety suite and a fair
  behavioral fake, both already well factored.
- **`success` vs `confirmed` result envelope** with `success_on_unconfirmed=True` — decision §6;
  `movement.py` shows the intended consumption pattern (require `confirmed` where physics
  matters).

## 7. Per-module verdicts

Production modules; "clean" means read and nothing worth reporting.

| Module | Verdict |
|---|---|
| `commands/commands.py` (1643) | Sound Phase A/B/C structure; ~120 lines of dead knobs/no-op injection (F4), one phantom gate check (Wiring); wrappers themselves are thin and uniform. The 21 `set_*` wrappers have zero in-repo callers outside tests but are the documented operator API — keep. |
| `commands/confirmations.py` (1149) | Good table design, refactor half-finished (F5, ~220 lines); one test-accommodation branch in production (F6); race is heavy but justified. |
| `commands/dispatch.py` (752) | Healthiest big file; correct, careful; ~30 lines of repeated timing literals; dead backoff knobs (F4). |
| `commands/gate.py` (488) | The safety core — keep almost all; ~35 lines of test/retired-only status plumbing; fallback story told three times. |
| `commands/confirm_select_job.py` (381) | Live hybrid path; ~135 lines of pure-mode/priming scaffolding production never runs (F6); densest read in the driver. |
| `commands/errors.py` (242), `settings.py` (152), `prechecks.py` (76) | Clean; errors.py tail duplicated once in commands.py (F4). |
| `commands/confirm_specs.py` (188) | Good; one dead field making tolerances triple-defined (F4). |
| `commands/objectives.py` (62) | `objective_by_slot` live; `validate_slots` retired-only (F2). |
| `config/profiles.py` (449) | Fully live except the dead confirm_fn bindings (F4) and backoff fields; the bench-dated comments are valuable — keep them. |
| `config/machine.py` (473) | Sound snapshot design; ~110 lines of shims/dead migration (F9); origin semantics told three times. |
| `readers/router.py` (539) | Essential core (decision §1) — earns its lines; ~35 derived wrappers with no live caller and ~120 lines of repeated wrapper boilerplate that the capability table could generate (F10, all JUDGMENT); one diagnostics-contract bug (§5.5). |
| `readers/api_reader.py` (513) | Essential core; healthy; ~60 caller-less lines (F10, JUDGMENT); `get_lasx_settings` block is JUDGMENT operator tooling; signature-default tunables duplicate the profile (F14). |
| `readers/log_reader.py` (623) | Essential core, live and load-bearing (dialog diagnostics, select-job log leg); ~20 caller-less parity lines (F10, JUDGMENT); DST/tail-cap/latin-1 handling all earned. |
| `readers/log_wait.py` (216), `capabilities.py` (157), `derived.py` (92) | Clean, live. |
| `scanfields/parsers.py` (1109) | Core live via the adapter's one entry point; three-rung fallback ladder is real complexity, not duplication; ~115 lines of retired-only output (F2) and the comma-decimal bug (§5.1). |
| `scanfields/planning.py` (443) | Live; the 501-step brute-force overlap search is a perf smell, not bloat. |
| `scanfields/lrp.py` (380) | `_get_job_names` live; the ~250-line deep parser is README-promised operator tooling with no in-repo caller (F12/§2 row 12). |
| `scanfields/files.py` (313), `transaction.py` (187), `_convert.py` (25) | Clean, live; `save_and_read_lrp` caller-less. |
| `scanfields/strip_restore.py` (395) | Keep; `strip_template_in_place` retired-only (F2). |
| `experimental/lrp_edits/` (1681) | ~130 lines live; the rest is a dead mirror API (F3) — the single largest deletion. |
| `acquisition/save.py` (319), `capture.py` (64), `files.py` (114), `naming.py` (97), `materialize.py` (130) | Clean; atomicity logic justified; one 2-line alias in materialize. |
| `acquisition/ome.py` (461) | Live TIFF patcher; companion-XML half retired (F8); two minor repair-path warts (§5.7). |
| `acquisition/ome_canonical.py` (645) | The one OME writer (no duplicate with ome.py — checker vs writer); two dead functions (F8); `_ascii_channel` inconsistency. |
| `acquisition/lasx_native_autosave.py` (500) | Keep; two-phase mtime wait encodes real failure modes; one parsed-never-read field. |
| `acquisition/product.py` (140) | Mostly clean; `PositionIndex`/`xml_paths` are sidecar-era vestiges (F8). |
| `calibration/core/objective_pair.py` (1068) | Core math fine; ~130 lines of intra-file ceremony duplication (F7). |
| `calibration/core/common.py` (553), `adopt.py` (298) | Clean; adopt's origin-protection checks are load-bearing; one dup normalization block shared with ome_canonical (~20 lines, optional). |
| `calibration/core/model.py` (333) | ~85 lines only serve retired/tests (F2); no finiteness validation (§5.2). |
| `motion/limits.py` (212), `movement.py` (179), `stage_config.py` (309) | limits/movement: exemplary, keep byte-for-byte; stage_config carries ~35 lines of retired-only source constants (F2). |
| `connection/session.py` (267), `session_state.py` (71), `lasx_runtime.py` (66) | Clean; session.py is the doc standard the rest should meet. |
| `orientation/__init__.py` (150), `measure.py` (371) | Clean, exemplary docs. |
| `zmart_adapter/zmart_adapter.py` (1248), `info.py` (90) | Clean wiring, verbose but accurate docstrings; option-validation ordering nit (F13); no gate of its own by design. |
| `utils.py` (297), `_file_utils.py` (66), `run_ci.py` (383), `__init__.py` (277) | utils/_file_utils clean and fully live, but utils hardcodes the machine-specific galvo constants and the shared timing knobs that belong in profiles (F14); run_ci earns its length (no pytest.ini duplication); `__init__` should stop re-exporting privates and the never-called lrp names (Wiring, F3). |
| `limits/`, `orientation/`, `calibration/` notebooks + defaults | Clean and small; no committed outputs; calibration default carries rig-measured values incl. the suspect slot 0 (§5.4). |
| Tests: `tests/unit/` (14,117) | Green; concentrated boilerplate in `test_core_driver.py` (F11); `test_limits_adversarial.py` keep as-is. |
| Tests: `tests/hardware/` (6,816) | Intentional live harness; `probe_four_readers` superseded (~750, §2 row 3); three stale bench prompts (~408); minor helper duplication in stress_hardware (~30). |
| Tests: `tests/helpers/`, `tests/data/`, conftests | Clean; single shared limits provisioner; data is legitimate vendor-format fixtures (2.4 MB). |
| Tests: `calibration/tests/` (3,068) | Green; readable; optional table-driving (~150–250). |
| `tests/_report/` | Delete from git (F1). |

Not read line-by-line: the bodies of `tests/hardware/validate_hardware.py`/`stress_hardware.py`
(structure, entry points, and run_ci wiring verified; content sampled), the middle thirds of
`parsers.py`'s individual RGN parsers and `lrp.py`'s per-element parsers (structure and callers
verified; probed with garbage input), and the notebook JSON beyond their code cells. Everything
else listed above was read.

## 8. Verification and adversarial testing record

Software-only, per the ground rules; nothing under `tests/hardware/` was executed and no
instrument-facing path was invoked.

- **Suites**: `tests/unit` + `calibration/tests` — **1091 passed, 1 skipped** (the skip is the
  LAS X runtime loader test, correctly guarded off-rig), 24 subtests, ~42 s. The one initial
  failure was this container missing `ome-types` — an environment gap, not a code bug; the test
  itself is a good schema gate.
- **Limits gate probes** (mock client + provisioned snapshots): NaN/inf/bool/string/None move
  targets all refused with actionable messages; range bounds inclusive at both ends; unknown
  command name raises KeyError by contract; never-handshaken client fail-closed. Found §5.3
  (int/float strictness) and §5.6 (reset refusal).
- **Hostile `limits.json` handshake probes** (12 cases: wider-than-backstop, min>max, missing/
  extra keys, non-JSON, empty, string ranges, float/empty slot lists, non-list setter): every
  case fell back loudly to bundled defaults with `is_fallback=True`, and an out-of-envelope move
  still refused in every state. The machine-provenance marker behaved correctly.
- **Parser probes**: garbage and truncated RGN/XML/LRP raise `ET.ParseError` out of the public
  parsers (the adapter documents raising here; the acquire path is separately protected by the
  template-state "unreadable" check). Found §5.1 (comma decimals). `Naming` sanitizes path
  traversal and enforces kebab-case.
- **Calibration model probes**: empty/old-schema/malformed configs all refused with clear
  messages; found §5.2 (NaN accepted).
- **Adapter surface probes** (mock client): wrong-typed coordinates fail before any command;
  NaN/huge targets refused by the gate with the gate's message; unknown actuators/procedures/
  options/jobs all raise precise ValueErrors; closed handle refuses everything.
- **Untested by design** (needs an instrument): the CAM transport (`UpdateAwaitReceipt`/echo
  semantics), hybrid-race timing against a real log stream, native AutoSave collection, backlash
  physics, and the additive-z assumption the adapter docstring itself flags as wanting one
  hardware pass.
