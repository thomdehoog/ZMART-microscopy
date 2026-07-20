# Review — Leica driver: driver-owned config loading, config ladder, session-scoped origin

- **Date:** 2026-07-10
- **Reviewed commit:** `1932bd7` ("Leica: driver-owned config loading, config ladder,
  session-scoped origin") on branch `claude/leica-notebooks-validation-dssuf0`.
- **Review prompt:** `docs/reviews/leica_config_loading_review_prompt.md` (same branch).
- **Scope:** the single commit, inside
  `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` (all file:line references below
  are relative to that package unless a full path is given). Every claim was checked against
  the code at `1932bd7`; the package imports cleanly and its `__all__` is internally
  consistent (verified by import).
- **Method:** line-by-line read of the changed files plus the modules they call into
  (`shared.limits` callers, `motion/limits.py`, `commands/objectives.py`,
  `calibration/core/common.py`, `orientation/measure.py`), whole-repo reference searches for
  removed names and residual origin reads, and a critical read of the rewritten adversarial
  suite. Maintainer decisions stated in the prompt (defaults fallback, session-scoped origin,
  warn-only orientation check) are treated as given; findings below are about whether the
  implementation realizes them faithfully.

> **Status addendum (2026-07-10):** all 18 findings below (M1–M3, m4–m10, n11–n18) were
> fixed in commit `930b260` on branch `claude/leica-config-loading-review-jqybdr`, with
> regression tests for every behavioral change. Offline verification: 991 passed
> (unit + calibration), `run_ci.py --mock` PASSED, controller suite 35 passed. A review
> prompt for the fix commit is at
> `docs/reviews/leica_config_loading_fixes_review_prompt.md`.

**Verdict up front.** The core safety mechanics are implemented correctly: no path lets an
invalid or over-wide machine `limits.json` govern a move, no public API reaches an ungated
state, and the origin really is session-scoped with no residual connect-time restore. The
defects found are at the edges: one behavioral inconsistency in `connect_microscope` (a
corrupt `orientation.json` crashes the connection outright while the other two configs
degrade gracefully), one consequence of the fallback policy that deserves a louder warning
(the fallback can be *wider* than the operator's own envelope), and a handful of stale
docstrings/comments that still describe the old cross-session origin. No blockers.

---

## 1. Findings, ranked

### Major

**M1 — A corrupt `orientation.json` crashes `connect_microscope` entirely; the other two
configs degrade gracefully.**
`connection/session.py:149-151`.
The three configs have three different failure behaviors: limits fall back to the bundled
defaults (never raises), calibration degrades to `translations=None` with a warning
(`_load_objective_translations` catches everything), but the orientation load is unguarded:
`_orientation.rig_orientation()` → `load_orientation()` raises on unparseable JSON
(`json.JSONDecodeError`), a non-integer `rotate_deg` (`ValueError` from `int(...)`), or an
off-quarter value (`Orientation.__post_init__` raises on e.g. `rotate_deg: 45`).

*Failing scenario:* an operator (or a truncated write) leaves `orientation.json` in the
newest snapshot malformed → `connect_microscope()` raises → the adapter's `connect()` fails
→ the operator cannot open a session at all, even though the stated philosophy of this very
commit is "the session stays usable and bounded while the operator fixes the file." Worse,
the raise happens *after* `connect_python_client()` and the limits handshake: the CAM
client is connected and the gate registry holds its state, but `session_state` was never
installed and no handle exists to `disconnect()` — a half-torn-down connection.

*Suggested fix:* wrap the orientation load in the same posture as calibration — degrade to
`Orientation()` (identity, i.e. exactly the `load_orientation=False` meaning: images saved
as the camera produced them) with a loud warning naming the file and the notebook. If
crash-on-corrupt is deliberate (an unreadable measured turn silently saving unrotated images
is arguably worse than refusing), do it *before* opening the CAM client and say so in the
docstring — today the docstring only documents the switches, not the failure mode.

**M2 — The defaults fallback can be *wider* than the operator's own envelope, and neither
the warning nor a test says so.**
`commands/gate.py:366-370` (fallback trigger), `commands/gate.py:306-313` (warning text).
The bundled default envelope equals the physical backstop exactly
(`limits/defaults/limits.json` vs `motion/limits.py:47-52`, pinned by
`test_backstop_matches_the_historical_machine_envelope`). So the fallback offers no margin
beyond the backstop — and any machine file that validates *partially* is replaced wholesale
by that widest-permissible envelope.

*Failing scenario:* an operator has published a deliberately narrow envelope (say
`x: [40000, 60000]` to protect a mounted sample) and later hand-edits the file, introducing
a typo in one `functions` key. On the next connect the whole file is rejected and the
session is governed by the full-backstop defaults: `move_xy` to `x=120000` — a move the
operator's own limits file forbids — is **allowed**. The warning fires, but it says only
that the defaults are "NOT this machine's measured envelope"; it does not say the governing
envelope may now be *wider* than what the operator measured, which is the actual hazard.
This is the sanctioned maintainer decision realized faithfully — the finding is that its
sharpest consequence is invisible: the adversarial suite only tests attacks whose bad values
are *wider* than the defaults, so "falls back" and "the bad file governs" are
indistinguishable in the narrow-file direction, and nothing pins that the fallback replaced
a narrower envelope with a wider one.

*Suggested fix:* (a) extend the `_install_default_limits` warning to state that the
defaults may be wider than the machine's own (rejected) envelope and that the operator
should not rely on their published limits until the file validates again; (b) add one
adversarial test: a *valid, narrow* envelope plus a broken `functions` block → assert
`is_fallback` and assert a move outside the narrow envelope but inside the defaults is
**allowed** — pinning this consequence as chosen behavior rather than leaving it to be
rediscovered as a surprise.

**M3 — The adapter's module docstring still documents the deleted restore-at-connect
origin.**
`zmart_adapter/zmart_adapter.py:31-35`.
"…persisted machine-locally to `origin.json` in the newest machine snapshot (next to
`calibration.json` / `limits.json`) and restored by `connect` — the origin stays the frame
truth across sessions until set again." All three claims are now false: the origin lives in
`origin/`, not the snapshot; `connect` does not restore it; it is session-scoped. This is
the first thing a maintainer reads in the file whose behavior the commit changed, and it
contradicts the (correct) `set_origin` docstring 350 lines below.

*Suggested fix:* rewrite the "Scope of v1" bullet to match `set_origin`'s docstring and
README §5.

### Minor

**m4 — `publish_snapshot` docstring contradicts its own code.**
`config/machine.py:417` says the publish "carries a persisted `origin.json` forward when one
exists" — the exact behavior this commit removed; the inline comment eight lines later
(`config/machine.py:447-448`) correctly says the opposite. A maintainer reading only the
docstring will expect origin propagation. Fix: delete the clause.

**m5 — `adopt_orientation` docstring is stale on two counts.**
`orientation/measure.py:313-317`: "carrying the microscope's calibration, limits and frame
origin forward" (origin is no longer carried into snapshots), and "This snapshot is what
`rig_orientation` reads at save time" (adapter sessions now read the orientation once at
connect via `session_state`; only the calibration workflow still reads at save). Fix: drop
"and frame origin", say "read when the driver connects (and by the calibration workflow at
capture)".

**m6 — Stale cross-session-origin comment in the live-hardware validator.**
`tests/hardware/validate_zmart_adapter.py:163-167`: "…false once `set_origin` has ever
persisted a non-zero origin.json (it stays the frame truth across reconnects)". With
session-scoped origin, a fresh connection *always* starts frame == hardware, so the stated
reason for skipping the check is gone (the check could even move back into the read-only
phase now). The code still passes — only the comment misleads. Fix the comment; optionally
reinstate the read-only-phase frame check since it is now unconditional.

**m7 — An empty live objective name can erase a real name in the adopted calibration.**
`calibration/core/objective_pair.py:173-176` builds
`hardware_objectives = {slot: str(entry.get("name", ""))}`. `objective_by_slot`
(`commands/objectives.py:22`) skips `objectiveNumber == 0` placeholders, but a real slot
whose hardware record lacks a `name` yields `""` — and in `_apply_staging_payload`
(`calibration/core/adopt.py:100,109,122`) only `None` means "don't touch";
`update_objective` (`calibration/core/model.py:184-185`) happily writes `entry["name"] = ""`.

*Failing scenario:* LAS X reports a slot without a name (firmware quirk, simulator) → adopt
overwrites the config's human-set name with `""` → every later
`_objective_slot_for_label(config, "10x")` for that slot fails with "matched slots [];
expected one", and the operator has to hand-repair the JSON. Loud, but avoidable. Fix: build
the dict with a truthiness filter (`if entry.get("name")`), so unnamed slots simply keep
their config names.

**m8 — `_loaded_orientation`'s fallback silently re-reads the file and can disagree with
the connection's choices.**
`zmart_adapter/zmart_adapter.py:244-254`. When `session_state` has no entry for the client,
the helper falls back to a fresh `rig_orientation()` read. For a handle built by
`connect()`, this is unreachable during normal life — but it *is* reachable when a second
session's `disconnect()` uninstalls the shared client's state (the CAM client is one
module-level object per process, so both registries key the same id), or for test-built
handles. In those cases the fallback (a) ignores `load_orientation=False` and (b) can read a
*newer* file than the session loaded — the exact per-save re-reading the registry was built
to prevent — and (c) can raise on a corrupt file, unlike the None-tolerant registry path.
In practice the gate refuses acquires after an uninstall, so this mostly cannot produce a
wrongly-turned image; it is an inconsistency trap, not an active bug. Fix: log a warning
when the fallback is taken, or return `Orientation()` and document that handles not built by
`connect_microscope` save unrotated.

**m9 — The `_notes` "unmeasured" sentinel is an incidental marker, not a contract.**
`calibration/core/objective_pair.py:201-220`. The detection is correct today: the shipped
placeholder (`orientation/defaults/orientation.json`) carries `_notes`, and both writers of
measured files (`orientation/measure.py:277-283` staging, `orientation/measure.py:350-355`
adopt) emit exactly `{"schema_version", "rotate_deg"}` — no `_notes`. But nothing enforces
this: an operator who hand-edits the placeholder (sets `rotate_deg: 90`, leaves the notes)
gets a false "unmeasured" warning forever, and a future writer that adds an informational
`_notes` silently defeats the check. Fix: have `adopt_orientation` write a positive marker
(e.g. `"measured": true` or a `measured_at` timestamp) and key the warning on its absence;
keep `_notes` purely informational. Warn-only strength is the maintainer's call and the
message is genuinely actionable (names the notebook and the consequence) — both fine.

**m10 — Two coverage gaps in the rewritten adversarial suite.**
`tests/unit/test_limits_adversarial.py`. The rewrite is otherwise sharp — the
`clear_stage_limits` fixture means the "defaults were applied" assertions genuinely
distinguish the defaults from the attack values, and the `wider_than_backstop` /
`hand_widened` cases do assert that a move the wide file would allow still refuses. Missing:
(a) the narrow-envelope-widening case from M2; (b) a fallback→recovery re-handshake test
(connect against a broken file → `is_fallback`, fix the file, re-handshake → assert
`is_fallback` is False and the *machine* envelope governs). `test_second_handshake_rebinds…`
covers re-handshake narrowing but never starts from the fallback state.

### Nits

**n11** — `commands/gate.py:371-380`: the last-resort fail-closed path installs
`GateState(error=…)` but never resets the module-global stage envelope, so a previous
handshake's envelope stays in `motion/limits._stage_limits`. Unreachable for moves (every
mutating wrapper checks the gate first, which refuses), but worth either clearing or a
one-line comment saying the staleness is shadowed by the gate.

**n12** — `commands/gate.py:353-356`: `connect_handshake(stage_limits_path=X, load=False)`
silently ignores the explicit path. No current caller passes both; an assert or docstring
sentence would prevent a future surprise.

**n13** — The retired workflow tree still references removed exports:
`workflows/target_acquisition/workflow/retired/template.py:732-733`
(`drv.write_stage_limits_config`, `drv.current_stage_limits_path`) and
`retired/tests/test_polish.py:327-350` (monkeypatches them, plus the dropped
`LIMITS_SOURCE_*` exports). Neither CI workflow collects this tree and the retired package
docstring says it is off the active path, so nothing breaks silently — but anyone running
`pytest workflow/retired/tests/` now gets `AttributeError`s. A one-line note in the retired
package docstring ("references driver exports removed 2026-07; runs against older driver
checkouts only") would spare the archaeology. `LIMITS_SOURCES` itself still accepts all six
source values, so every existing ProgramData file keeps loading — confirmed.

**n14** — `connection/session.py:96`: the function-local
`from ..calibration.core import model` is load-bearing (a module-level import would be a
genuine cycle: package `__init__` imports `connection.session` eagerly, and calibration
modules import the package). It also points "up" the layer stack — `connection` now knows
about `calibration` — which README §7's dependency chain doesn't cover. Acceptable for a
front-door composition function, but the import deserves a comment saying the laziness is
required, and README §7 could add one line acknowledging `connection/session.py` as the
composition point that reaches into `commands.gate`, `orientation`, and `calibration`.

**n15** — `calibration/notebooks/calibrate_objective_pair.ipynb` lost its trailing newline
in this commit ("\ No newline at end of file").

**n16** — `orientation/__init__.py:28-30`: the module docstring shows the shipped
placeholder as `{"schema_version": 1, "rotate_deg": 0}` — without the `_notes` key that the
real file carries and that the calibration warning now keys on. Now that `_notes` is
load-bearing, the example understates the contract.

**n17** — README §4 quick start, step-2 comment (`README.md:133-136`): "…validates the
ProgramData limits.json … then installs the fail-closed gate for this client", followed by
`assert state.ok, state.error`. With the fallback, `state.ok` is true even for an invalid
file, and "fail-closed" no longer describes the handshake outcome (§3 right above gets it
right). One sentence ("an invalid file falls back to the bundled defaults — check
`state.limits.describe()['is_fallback']` if you need to know") would keep the front door
honest.

**n18** — `zmart_adapter/zmart_adapter.py:385-405`: `set_origin` sets `handle.origin`
*before* persisting, so when `write_origin` fails the op raises but the session's frame has
already moved to the new zero. The inline comment shows this is deliberate (re-running is
cheap, silence is worse), but the raise message and the op docstring could say "the frame
WAS set; only the on-disk record failed" so a controller-side caller doesn't assume
nothing changed.

---

## 2. The explicit call-outs the prompt asked for

- **Can an invalid/over-wide limits file ever govern a move?** No. The ordering in
  `_build_gate_from_file` (`commands/gate.py:263-292`) is validate-everything-then-apply:
  `stage_config.load` (schema, finite, min≤max, exact axes) → backstop containment →
  `shared.limits.load` of the same file with the validated envelope overlaid → only then
  `apply_stage_limits_from_config` + `_install`. Any exception leaves both the module-global
  envelope and the client's gate state untouched, and the caller then installs the defaults
  (or, if even those fail, a fail-closed state). There is no partial-application window. The
  per-move backstop check (`motion/limits.py:155-212`) remains independent and runs after
  the envelope check on every move. The one governance surprise runs in the *other*
  direction — see M2.
- **Can a session end up ungated through any public API?** No. A never-handshaken client
  refuses everything (`check_refusal` on `state is None`,
  `commands/gate.py:214-222`; pinned by `test_moves_refuse_before_any_handshake` and the
  `_Untouchable` sweep). The adapter always handshakes (its `connect` delegates to
  `connect_microscope`, which calls `connect_handshake` unconditionally —
  `connection/session.py:148`), so through the adapter the only reachable states are "valid
  file governs", "defaults govern (loud)", or "everything refuses". `set_stage_limits` is
  exported but only adjusts the in-memory envelope; it cannot open the gate.
- **Connect-loaded orientation/calibration vs what acquire/save uses.** Consistent for real
  sessions: `acquire` saves with `_loaded_orientation(handle)` (session_state), frame math
  uses `handle.translations` copied from session_state at connect; nothing else loads
  translations (`_load_objective_translations` in the deleted adapter location is gone, no
  dangling refs — verified by search). The calibration workflow deliberately reads
  `rig_orientation()` fresh at capture (`calibration/core/common.py:293-296`) and never
  installs session_state (it connects via `connect_python_client` +
  `connect_limits_handshake`, `calibration/core/objective_pair.py:159-164`) — a coherent
  split, since calibration wants the file as currently adopted. The only skew path is the
  adapter fallback described in m8.
- **`update_objective(name=None)` / origin-folder edge cases.** `name=None` is safe:
  `_objective_slot_for_label` requires exactly one match among the config's *existing*
  objectives, so `from_slot`/`to_slot` entries always exist and the
  "cannot create objective slot without a name" raise (`calibration/core/model.py:181`) is
  unreachable from `_apply_staging_payload`. Name refresh happens after label matching
  inside one adopt, and refreshing toward live names can only make future matching more
  truthful; an ambiguity fails loudly (`matched slots …; expected one`). The one real edge
  is the empty-string name, m7. Origin folder: `"origin"` can never match
  `is_snapshot_name` (`config/machine.py:76,108-110`), so
  `snapshots()`/`latest_snapshot()`/`ensure_snapshot` ignore it; `write_origin` works on a
  fresh machine with zero snapshots (test pinned); old `snapshot/origin.json` files from
  before the change are read by nothing (whole-repo search) and rot harmlessly — though an
  operator browsing ProgramData will see two `origin.json` locations, which is worth one
  sentence in the README's §3 if it ever confuses anyone. `write_origin`'s
  `.json.tmp` + `os.replace` is atomic on NTFS within the folder; a locked destination
  (antivirus/indexer) surfaces as the loud `RuntimeError` in `set_origin` — acceptable under
  the single-instrument-per-process invariant.
- **Misleading operator-facing statements.** M3, m4, m5, m6, n16, n17. The README itself
  (§3, §4 body, §5, §10) is accurate and reads well for the audience; the new notebook
  markdown in `calibrate_objective_pair.ipynb` is a model of the house style.

## 3. Areas verified correct (briefly, with the convincing reason)

- **Re-handshake semantics (A.5):** `_build_gate_from_file` unconditionally re-applies the
  envelope and re-installs the gate, so a re-handshake after fixing a file replaces the
  fallback fully; the only stale-global case is the double-broken path (n11), which the gate
  shadows.
- **Bundled-defaults containment (A.2):** defaults equal the backstop; the containment check
  is inclusive (`lo < backstop_lo or hi > backstop_hi`), and
  `test_backstop_matches_the_historical_machine_envelope` pins equality, so narrowing the
  backstop without regenerating the defaults fails CI rather than failing at connect.
- **`load=False` semantics (A.4):** "governed by defaults, never ungated" is stated in the
  `CONNECTION` dict comment, `connect_microscope`'s docstring, README §3 and §10, and pinned
  by `test_connect_skipping_limits_installs_the_default_fallback` — a caller expecting "no
  gate at all" is corrected by every surface they might read.
- **Origin session-scoping (B.1/B.2):** no residual connect-time reads (search), the frame
  starts all-zero (`ZmartHandle` default), `test_connect_does_not_restore_origin` pins it,
  and the machine-profile tests pin the folder layout and the publish-never-writes-origin
  invariant.
- **session_state lifecycle (C.3):** the registry holds a strong client reference (no id
  recycling), `disconnect` uninstalls both registries, and because
  `connect_python_client` returns the same module-level CAM object each time, a repeat
  `connect_microscope` rebinds rather than leaks. The two-live-handles teardown quirk is
  inherited from the gate's documented single-writer invariant, not introduced here.
- **Dead-code removal (E):** no active-tree references to
  `write_limits`/`current_path`/`limits_root`/`write_stage_limits_config`/
  `current_stage_limits_path`/`_atomic_write_json` remain (the calibration model keeps its
  own private `_atomic_write_json`, untouched); `__all__` is consistent (verified by
  import); the retired tree is genuinely uncollected (n13).
- **Connection-dict plumbing (F.2):** the adapter reads the three switches with
  `connection.get(..., True)`, so a controller passing a partial dict gets full loading —
  and the integration tests exercise `dict(adapter.CONNECTION)` end-to-end.
