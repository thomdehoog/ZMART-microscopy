# Master review: workflows, controller, and Leica driver

- **Date:** 2026-07-12, branch `claude/review-workflows-controller-leica-yd625w`
  (based on `claude/forfable4-document-11mxsx`; that branch was not modified).
- **What this is:** the consolidated record of a deep simplification review of the
  three main areas — `workflows/target_acquisition`, `zmart_controller`, and the
  Leica driver (`zmart_drivers/leica/.../navigator_expert`) — followed by the
  application of every finding that did not need a maintainer decision. Four
  detailed reports back this document:
  - `controller_simplification_review.md`
  - `leica_driver_simplification_review.md`
  - `workflows_simplification_review.md`
  - `completeness_critic_report.md` (a second pass asking "what did the others miss?")
- **Review criteria** (as directed): end-to-end wiring, bloat and overengineering,
  dead-code fossils, README/doc drift, readability for the biologist audience,
  hardcoded tunables that belong in profiles, and offensive adversarial testing —
  software only, never against hardware. Guiding principle: the best code is the
  code that is deleted, as long as the general functionality and ideas stay.

## The bottom line

The branch removes **30,429 net lines** (236 files, +1,606 / −32,035, review
docs excluded) while every capability survives: the v4 notebook and React
workflows, the webapp, the controller's full 13-op surface, both real driver
adapters, and the entire safety stack. Every offline test suite is green after
the change — controller 37, workflows 277 (both operator notebooks execute
end to end), Leica 1,028 + 84 subtests, mesoSPIM 130, shared 30 — and `ruff`
is clean across the tree. Ten regression tests were added for the bugs fixed.

The architecture itself was found to be sound in all three areas. The bloat was
sediment from many AI-assisted hardening rounds — a superseded workflow
generation kept on life support, defensive knobs nothing sets, committed
build artifacts, and compatibility shims for callers that no longer exist —
not structural problems.

## Wiring verdict: connected

Verified call-by-call in both directions. Every controller op resolves to a
real function in all three drivers (Leica, mesoSPIM, mock) with matching
signatures; every Session method the live workflow calls exists; the webapp,
notebooks, and React widgets all reach the same public workflow steps; the
driver adapter maps cleanly onto its internal layers. The one genuine seam —
the acquire record having no cross-driver contract — is now fixed (below).

## What was removed, by area

**Workflows (−14,600 lines).** The retired driver-coupled generation was fully
superseded by the live controller-only flow and reachable only from the v3.2
notebook: `workflow/retired/` with its tests, the `pipeline/` shim, the v3.2
notebook, three modules and three functions nothing live imported. Git history
is the archive. Also: essay docstrings in `_hijack`/`_geom`/`_mock_provider`
deduplicated, and the click-debounce window and channel palette given one home
(`_ui_constants.py`) instead of three.

**Leica driver (−1,600 production/test lines, plus 3.2 MB / 140 generated
files untracked).** Commands-layer sediment (unreachable profile-side confirm
wiring, never-set retry-backoff knobs, a no-op poll-window injection, repeated
timing dicts, a dead spec field); zero-caller companion-XML helpers;
compatibility shims in `config/machine.py`; six symbol families whose only
caller was the deleted retired tree; near-identical test clones table-driven;
stale bench prompts deleted; private helpers no longer re-exported by the
facade.

**Controller (small by design).** The controller was the healthiest area
(433 source lines, almost no slop). Fixes: `resolve()` no longer returns its
own argument, a dead guard dropped, test overfits corrected, review-fossil
prose removed.

## Real bugs found and fixed (each with a regression test)

1. **Acquire-record drift (all three areas).** The record had no contract:
   Leica returned `images`, mesoSPIM `image_files` + an integer `planes`
   count, the mock only `filename` — and the workflow read only `images`, so
   image handling silently no-oped on two of three drivers. Fixed end to end:
   `images` is now the stated cross-driver convention (README), the mock and
   mesoSPIM fill it, and the workflow reads all shapes through one reader
   (`record_channel_paths`), which also now understands a plane *count* as
   opposed to a plane *manifest*. The critic pass caught that the first fix
   had misread mesoSPIM's `planes` as a list; that is corrected and tested.
2. **German-locale tile sizes parsed 100× wrong.** `"290,63 um"` from a
   non-English LAS X parsed as 29,063 µm. The size parser now treats the comma
   as a decimal mark.
3. **Calibration accepted NaN translations** and `get_xyz` would silently go
   NaN (moves were already refused by the gate). `validate_calibration` now
   rejects non-finite values with a clear message.
4. **Diagnostics mode lost the API-timeout case** — the one failure it exists
   to explain. Timeouts now return the documented error-carrying `Reading`.
5. **Controller module leaked session privates** (`zmart_controller._ops`).
   Underscore names are no longer delegated.
6. **A `None` identity placeholder poisoned `get_instruments()` for everyone**
   with an opaque error far from the mistake; non-callable ops registered fine
   and died later. Both are now refused at registration, where the mistake is.
7. **An options typo in Leica `acquire` surfaced as an unrelated output-root
   error, and a bad `acquisition_type` wasted a capture.** Validation and
   naming now run before anything fires.

## Adversarial testing record (software only, no hardware paths)

The safety stack held: 12 hostile `limits.json` files all fell back loudly and
stayed bounded; NaN/inf/bool/string move targets refused; the adapter surface
rejected every hostile input before motion; controller lifecycle edges (failed
connect, raising teardown, double disconnect) all behaved. The unbounded
post-acquisition idle wait is deliberate and stays (acquisition time cannot be
predicted).

## Decisions honored

- The API/log/hybrid reader stack is essential core — untouched (housekeeping
  ideas are recorded as JUDGMENT in the Leica report, F10).
- `experimental/lrp_edits` stays exactly where and as it is — not promoted,
  not deleted. Only the README sentence about it was made honest.
- The unbounded acquire idle wait stays.
- All tunables should live in profiles: both reports carry a catalogue of
  every hardcoded tunable with a suggested profile home (workflows §3.5,
  Leica F14). The plumbing itself is a maintainer decision; only the
  triplicated UI constants were single-homed.

## Open items for the maintainer (JUDGMENT — deliberately not applied)

1. **Gate strictness:** a limits file with `allowed: [2.0]` refuses an
   operator's `2` (int vs float). Relax to numeric equality or document it.
2. **Slot numbering:** bundled calibration carries slots 0–2, limits allow
   1–6, and new named calibration sets seed from this rig's measured file.
3. **Reset-only `set_z_stack_definition`** is refused with a wrong message
   when a limit is configured.
4. **Half-finished confirmations dedupe** (~220 lines) and the router's six
   repeated read wrappers (~120 lines) — both are shape refactors that keep
   behavior identical.
5. **`objective_pair.py` ceremony** (~130 lines of intra-file duplication).
6. **Tunables-to-profiles plumbing** (the catalogues above).
7. **Small leftovers:** gate.py tells its fallback story three times (safety
   prose — trim needs care); `confirmations._reading_value_after` carries a
   test-accommodation branch that should die with a fixture sweep; the
   `pure` api/log modes and `prime_cluster` in `confirm_select_job` are
   exercised by nothing in production.
8. **Out of scope but flagged:** `shared/` (813 load-bearing lines) has never
   been reviewed; the Zeiss driver is a fork still carrying the sediment just
   deleted from Leica; the mock's `run_procedure` record shape disagrees with
   both real adapters (no live consumer reads it today).

## Commit trail

Reviews: `6cc5186`/`16e1f69`/`2989787` (controller), `5205646`/`eebb1d4`
(workflows), `3643787` (Leica). Fixes: `a2e9c19` (controller), `db8dd65`
(workflows + artifact untracking), `d5e16e1` (Leica), `4a7f549`
(retired-only symbols, mesoSPIM record handling, critic findings).
