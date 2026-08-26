# Review Prompt — Manifest-Driven Automatic Frontend Refresh

## Purpose

This document is a hostile implementation review brief for a second agent. The reviewer must review the implementation that is currently on the feature branch, not merely review the design proposal. The goal is to find correctness, race, cache, publication-boundary, scalability, browser-integration, and maintainability defects that could make the live viewer show data that was not committed, fail to show committed data, corrupt operator state, or create unnecessary I/O.

The review should be adversarial. Do not assume that passing tests means the architecture is correct. Trace the production path and try to disprove the invariants.

## Repository and exact scope

Repository: `https://github.com/thomdehoog/ZMART-microscopy`

Branch: `agent/live-position-timepoint-publication`

Current implementation commit: `2698de4f3bfcc8a02a64fd6c9592595ac53d634c`

Draft PR: `https://github.com/thomdehoog/ZMART-microscopy/pull/8`

Actual comparison base: `claude/omezarr-neuroglancer-structure-srnwu6`

Base commit: `2027f911bb8f052f53956b0727994829f66cbedf`

Compare with:

```bash
git fetch origin agent/live-position-timepoint-publication \
  claude/omezarr-neuroglancer-structure-srnwu6
git checkout agent/live-position-timepoint-publication
git diff origin/claude/omezarr-neuroglancer-structure-srnwu6...HEAD
```

**Do not compare this branch against `main`.**

## Required first reading

Before reviewing implementation details, read completely:

1. `docs/design/manifest-driven-frontend-refresh-handoff.md`
2. `docs/design/live-position-timepoint-publication-decisions.md`
3. `docs/design/zero-copy-acquisition-optimizer.md`
4. `docs/design/live-writer-and-linked-views-plan.md`
5. `zmart-viewer/TESTING.md`

Then inspect the actual implementation and tests, at minimum:

- `zmart_live/manifest.py`
- `zmart_live/live_state.py`
- `zmart_live/model.py`
- `zmart_live/coordinator.py`
- `zmart_live/gateway.py`
- `zmart_live/viewroute.py`
- `zmart_live/shardlink.py`
- `zmart_live/scene.py`
- `zmart-viewer/app/server/announcements.py`
- `zmart-viewer/app/server/live_config.py`
- `zmart-viewer/app/server/server.py`
- `zmart-viewer/app/page/src/App.jsx`
- `zmart-viewer/app/page/src/AxisSlider.jsx`
- `zmart-viewer/app/page/src/engine.js`
- `zmart-viewer/app/page/src/live-refresh.js`
- `zmart-viewer/app/page/src/scene.js`

Read all directly relevant tests, especially:

- `zmart_live/tests/test_live_state.py`
- `zmart_live/tests/test_gateway.py`
- `zmart_live/tests/check_the_live_refresh_tests_can_fail.py`
- `zmart-viewer/tests/test_manifest_driven_refresh.py`
- `zmart-viewer/tests/test_frontend_live_refresh_contract.py`
- `zmart-viewer/tests/test_manifest_refresh_browser.py`
- existing manifest/gateway/scene/coordinator/replacement/announcement tests

Do not treat the design document as authoritative over the code. Verify every design claim against the current implementation.

## What the implementation is supposed to guarantee

The central boundary is **manifest publication**, not file existence.

A viewer must never infer that a position or timepoint is available because:

- an OME-Zarr directory exists;
- a Zarr shape has grown;
- chunks exist;
- a pyramid folder exists;
- timestamps changed;
- a filename appeared;
- a filesystem watcher fired;
- a route can technically return something.

The only authoritative visibility boundary is the atomic advancement of the committed manifest after canonical pixels, all advertised pyramids, generation-specific raw/seamless routes, metadata, and validation prerequisites are complete.

The microscope must remain completely independent of the viewer. The viewer must not need microscope notifications or control APIs.

## Non-negotiable invariants

Verify each of these by tracing code, writing tests where necessary, and attempting to violate the invariant.

### Publication truth

1. `positions/` remains the sole owner of pixel payloads.
2. Raw and seamless views remain metadata/routes only and remain zero-copy.
3. No completion inference from chunks, pyramid directories, timestamps, filenames, Zarr shape, or filesystem notification.
4. A notification can only trigger rereading committed truth; it can never itself prove readiness.
5. Damaged, foreign, truncated, malformed, or regressing committed state must never become a legitimate newer or lower revision.
6. A safe-empty manifest fallback must never be confused with authoritative revision zero or used to regress a previously accepted state.
7. Revision jumps must be safe: the system must not require every intermediate revision to have been observed by the watcher.
8. Duplicate announcements must be harmless.
9. Explicit replacement generations must not leak old-generation pixels or metadata into a new publication.

### Backend/live-state correctness

10. There is at most one authoritative watcher/state tracker per valid live run, even when multiple viewers or backend requests exist.
11. Dynamic open/close behavior does not leak watchers, threads, file descriptors, or stale run state.
12. The watcher observes only the small publication marker.
13. Watcher failures degrade safely and do not convert invalid state into visible data.
14. `/api/live-state` or `/api/config` is bounded by acquisition products/views rather than position count.
15. Committed-time availability is explicit and cannot expose a gap merely because the declared Zarr shape reaches a higher index.
16. If the implementation uses a high-water mark, prove contiguity. Otherwise it must use an explicit compact range representation.
17. ETags/conditional requests must correspond to an immutable state snapshot. Do not allow a cache key to identify a newer revision while the response body contains older state.
18. An SSE hint must never suppress a required notification merely because another code path happened to read the manifest first.

### Gateway/source identity

19. Stable raw/seamless source URLs remain stable across revisions.
20. Revision values must not be encoded into source URLs.
21. Revision changes must be represented as metadata/state, not as a new source identity.
22. The production gateway must remain fail-closed.
23. Raw and seamless sources must advance together when a publication affects both.
24. An affected source must refresh even when the source URL itself is unchanged.
25. Unrelated acquisition types must not cause metadata or pixel requests.

### Neuroglancer/frontend correctness

26. Refresh must occur inside the existing layer/source rather than rebuilding the viewer.
27. Camera and zoom remain unchanged.
28. Valid current z/time selection remains unchanged.
29. Annotations remain unchanged.
30. Contrast, LUT, opacity, visibility, and layer order remain unchanged.
31. Refresh must not create one source/layer per position.
32. Refresh must not globally clear every Neuroglancer cache.
33. Cache invalidation must be scoped to affected aggregate source identities.
34. Selective decoded-holder invalidation must be safe with Neuroglancer reference counting and must not cause stale data to survive the revision boundary.
35. An unchanged conditional check must cause no Neuroglancer work and no pixel/chunk requests.
36. A missed SSE event must eventually be recovered by reconnection and/or the slow conditional check.
37. Burst announcements must coalesce rather than cause a refresh storm.
38. A duplicate announcement must not cause redundant work.
39. The frontend must not accidentally refresh on generic filesystem/live-folder events for recognized ZMART runs.
40. Existing static and generic non-ZMART live-folder behavior must remain intact.

## Adversarial scenarios

### Scenario A — premature position visibility

1. Commit position A.
2. Verify A is visible and non-black.
3. Write position B pixels and metadata, but do not advance the committed manifest.
4. Trigger every watcher/announcement mechanism available.
5. Verify B remains absent while A remains visible and equally bright.
6. Commit B.
7. Verify B appears automatically.

A black screen is not an acceptable passing condition. The test must prove A remains visible and non-black.

### Scenario B — uncommitted timepoint

1. Commit t=0.
2. Write t=1 without committing it.
3. Verify the time control does not expose t=1.
4. Commit t=1.
5. Verify t=1 becomes available without reload.
6. Verify the existing selected timepoint is preserved when valid.

### Scenario C — timepoint gap

Attempt to publish t=2 while t=1 is not committed. Verify the frontend cannot infer a contiguous high-water mark from Zarr shape.

### Scenario D — duplicate/burst SSE

Emit the same revision repeatedly and then emit several revisions in rapid succession. Verify that the final state converges correctly without proportional metadata/cache work.

### Scenario E — lost notification

Suppress an SSE notification, reconnect the browser, and verify the conditional revision check discovers the committed change without a full reload.

### Scenario F — damaged manifest

Test truncated JSON, invalid JSON, wrong run identity, invalid revision, and regression below the last accepted revision. Verify the last known good scene remains stable and no bogus revision is published.

### Scenario G — replacement generation

Publish generation N, then generation N+1. Verify that stale generation N routes/metadata cannot remain visible after the new generation becomes authoritative.

### Scenario H — unrelated acquisition

Commit a change affecting acquisition A only. Verify acquisition B makes no metadata or pixel requests.

### Scenario I — cached empty spatial data

Start with an aggregate source whose spatial data is empty and cached. Publish the first position. Verify the empty result does not remain permanently cached.

### Scenario J — many positions

Create a run with a large number of positions and a small number of acquisition products. Verify live-state payload size and source/layer counts remain bounded by products/views, not positions.

### Scenario K — idle behavior

With no manifest changes, leave the viewer idle. Verify there is no repeated Neuroglancer work and no image/chunk request storm.

## Mutation review

Do not merely read the mutation tests. Inspect the mutation harness and ensure each mutation would actually make the implementation unsafe if the relevant assertion disappeared.

At minimum sabotage these properties one at a time:

1. Serve newly written pixels before manifest commit.
2. Derive time availability from declared Zarr shape/high-water index.
3. Ignore a changed `CompiledSource.revision`.
4. Put revision information into the source URL.
5. Replace selective invalidation with global cache invalidation.
6. Accept damaged manifest state as authoritative.
7. Make an SSE announcement itself authoritative instead of rereading the manifest.
8. Make duplicate announcements trigger full refreshes.
9. Make unrelated acquisition revisions refresh all sources.
10. Remove the positive “A remains bright” assertion from the premature-visibility test and verify that the test suite would then become vulnerable to a dishonest black-screen pass.

A mutation that merely causes a syntax/import failure is not a meaningful safety mutation. The test should fail because the behavioral assertion is violated.

## Performance review

Do not assume that selective invalidation is cheap. Measure it.

Look for:

- metadata request count per committed revision;
- chunk request count before and after an affected publication;
- requests caused by duplicate/burst announcements;
- requests caused by unrelated acquisition revisions;
- behavior when the viewer is idle;
- live-state payload size with many positions;
- watcher filesystem work per publication;
- number of active watchers as runs are opened/closed.

A revision change should not cause a full scene rebuild or an O(position-count) frontend state transfer.

## Browser qualification

Read `zmart-viewer/TESTING.md` and `zmart-viewer/run_tests.py` before making browser claims.

The decisive browser test is the real production scenario:

> Commit A → A appears and is measurably non-black → write B without commit → B remains invisible and A remains equally bright → commit B → B appears automatically without reload and operator state remains unchanged.

Also execute the corresponding t=0/t=1 scenario.

If Chromium is unavailable, do not call skipped tests visual verification. State exactly what executed and what did not.

## Review methodology

The reviewer should proceed in this order:

1. Read the handoff and architecture documents completely.
2. Inspect the actual diff from the specified base.
3. Trace one real `RunManifest.publish()` all the way through marker replacement, watcher detection, state validation, SSE, browser reconciliation, source refresh, gateway request, and pixel retrieval.
4. Trace the negative path where pixels exist but the manifest has not advanced.
5. Trace damage/regression/replacement-generation paths.
6. Inspect concurrency and lifetime behavior for multiple runs/viewers.
7. Inspect frontend cache/reference handling.
8. Run focused tests before broad tests.
9. Run browser scenarios if the environment supports them.
10. Run mutation/fault tests.
11. Run Ruff and `git diff --check`.
12. Review the final diff for accidental scope expansion or unrelated changes.

Do not stop at “tests pass.” Identify assumptions, races, stale design comments, unnecessary complexity, missing failure handling, and hidden scalability costs.

## Review output requirements

Return a structured review with:

### 1. Executive verdict

Choose one:

- **APPROVE** — no material correctness issue found.
- **APPROVE WITH FOLLOW-UP** — correct for intended use, but non-blocking hardening remains.
- **REQUEST CHANGES** — one or more material correctness/safety issues remain.
- **BLOCKED** — the environment prevents sufficient verification of a critical requirement.

Do not use “approve” merely because tests pass.

### 2. Findings

For every finding provide:

- severity: CRITICAL / HIGH / MEDIUM / LOW;
- exact file and line/function;
- failure mechanism;
- concrete reproduction or race sequence;
- why existing tests do or do not catch it;
- recommended fix;
- whether the fix should block merge.

Prioritize correctness over style.

### 3. Invariant audit

Create a checklist covering every non-negotiable invariant above and mark it:

- VERIFIED BY EXECUTION
- VERIFIED BY CODE READING
- NOT VERIFIED
- VIOLATED

Do not conflate these categories.

### 4. Test evidence

Report exact commands and results. Separate:

- unit tests;
- integration tests;
- mutation/fault tests;
- frontend build/static checks;
- browser execution;
- performance measurements.

### 5. Browser qualification

State explicitly whether the A/B and t=0/t=1 scenarios actually executed in a real browser. If not, explain exactly why.

### 6. Scope/design assessment

Identify any implementation decisions that diverge from the handoff and say whether each divergence is:

- an improvement;
- neutral;
- risky;
- incorrect.

### 7. Final recommendation

Give a merge recommendation and the smallest concrete set of changes required before merge if changes are requested.

## Important review constraints

- Do not rewrite the architecture simply because another design is aesthetically preferable.
- Preserve the zero-copy model.
- Preserve manifest-as-truth publication semantics.
- Do not introduce microscope-to-viewer coupling.
- Do not introduce per-position Neuroglancer sources/layers.
- Do not introduce revision-bearing URLs.
- Do not replace the manifest with polling, chunk scanning, or filesystem timestamps as a source of truth.
- Do not declare browser behavior verified unless the browser actually ran.
- Do not modify implementation code during this review unless explicitly asked. This document is a review task, not an implementation task.

## Definition of a successful review

A successful review either:

1. finds a real defect with a reproducible failure mechanism and clearly explains the required correction; or
2. provides strong evidence that the implementation satisfies the publication, concurrency, frontend state, cache, scalability, and failure-handling invariants, while clearly identifying anything that could not be executed in the available environment.

The review is successful only if it increases confidence in the implementation. Agreement with the design document by itself is not evidence.
