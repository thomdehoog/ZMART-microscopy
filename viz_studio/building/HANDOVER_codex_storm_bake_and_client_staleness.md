# ZMART storm-bake and client-staleness handover

Status recorded on 2026-08-14 from the 24-core T400 workstation.

## Verdict

The backend bake defect is reproduced and repaired on the working branch. A
governed bake now catches up without a later client request, cannot be regressed
by an older concurrent derive, and retries transient Windows sharing violations.

The client fix is **not finished**. The smaller automated real-wheel gate passes,
but the operator-scale 40x40/core-32 demonstration still ended with pixels that
F5 repaired. The manifest and bake stamp were both at revision 1600 before that
reload, so this remaining failure is client-side staleness, not a bake that is
still behind. Do not call the branch shippable and do not run the final full suite
until this exact manual sequence has been made into a red automated gate.

## Isolation and branch

- Working clone:
  `C:\ProgramData\MinicondaZMB\home\t.de\ZMART-microscopy_ladder-codex-storm-20260814`
- Branch: `codex/diagnose-storm-bake-catchup`
- Base: `f4056177`
- Remote branch:
  `https://github.com/thomdehoog/ZMART-microscopy/tree/codex/diagnose-storm-bake-catchup`
- Clean demonstration/build clone pinned to the current candidate:
  `C:\ProgramData\MinicondaZMB\home\t.de\ZMART-microscopy_ladder-codex-demo-20260814-0e2f597f`
- Python environment:
  `C:\ProgramData\MinicondaZMB\home\t.de\zmart-ladder-venv`
- Playwright browsers:
  `C:\ProgramData\MinicondaZMB\home\t.de\ms-playwright`
- Node/npm must come from:
  `C:\ProgramData\MinicondaZMB\envs\lasxapi_extended`
- All fixtures created in this campaign are below:
  `D:\zmart-codex-diagnosis-20260814`

The original clone and Claude's work were not modified. Existing `D:\zmart-*`
fixtures were not deleted. In particular, `D:\zmart-demo-spiral15` remains the
preserved broken run from the previous campaign.

## Pushed commits

- `5b62c1da Repair governed bake catch-up after commit storms`
- `0e2f597f Serialize live chunk refreshes without replacing render objects`

These commits are intentionally on the separate Codex branch. The second commit
is a useful candidate and diagnostic step, not a completed client fix.

## Audit of the four inherited behavior changes

1. Invalidation routing was already backed by a regression test and was kept.
2. ETag revalidation was already backed by a regression test and was kept.
3. The worker-side captured-state verification had no red test and was reverted.
4. Frontend replace-in-place delivery initially had no red test and was reverted.
   A later measured red test showed object replacement freeing a GPU texture still
   referenced by a render pass, so an object-preserving form was restored. It
   turns the small real-wheel gate green, but the 40x40 manual failure proves it
   is not sufficient by itself.

The memory-pressure hypothesis was tested with normal and raised queue budgets.
The persistent post-storm/F5 difference did not follow the memory limits, and the
worker reported ample GPU/system budgets with no pending update backlog in the
smaller reproduction. Memory pressure is not the established root cause.

## Backend diagnosis and fix

### Out-of-order bake regression

Concurrent derives ran outside the bake guard. A newer snapshot could be baked
and installed first, followed by an older snapshot that regressed the on-disk
bake and its stamp.

The fix serializes the full derive -> bake -> install sequence. The regression
test is:

`test_an_older_derive_cannot_regress_the_bake_behind_a_newer_one`

### Catch-up had no independent driver

A bake could stop behind the manifest when demand stopped. Reading a piece later
could incidentally trigger recovery, which made an early judge produce a false
green.

Announcements now notify held governed runs. Each run owns a coalescing background
catch-up worker. It waits for 250 ms of announcement quiet before deriving, so a
continuous storm is not starved by eager background bakes. The relevant tests are:

- `test_the_bake_catches_up_after_demand_stops`
- `test_background_catch_up_waits_for_the_announcement_storm_to_quiet`

### Windows reader/writer collision

The watched run exposed `PermissionError [WinError 5]` while replacing a staged
baked chunk whose destination was held by a reader. Only Windows sharing-shaped
errors are retried, with bounded backoff for at most five seconds. The regression
test is:

`test_the_bake_retries_a_transient_windows_sharing_violation`

## Client diagnosis and current candidate

The strongest client measurement was **124 simultaneous downloads of the same
chunk**. Multiple refresh promises mutated, serialized, and freed the same worker
chunk object out of order. A frontend-only swap ledger could not see that worker
damage, so its earlier zero count was not evidence of absence.

The worker candidate now owns one refresh pump per source:

- one batch in flight per source;
- newer invalidations coalesced into the next batch;
- different keys within one batch may still download concurrently;
- a two-second timeout aborts stuck work;
- no unbounded cache of absent keys was introduced.

This reduced measured same-key overlap to zero. An early version discarded a
successful result whenever the same key had become pending again; that caused the
picture to appear only when the storm ended and was removed.

The frontend candidate preserves an existing chunk object's identity when a
replacement arrives:

```js
Object.assign(chunk, source.getChunk(update));
```

The old GPU allocation is freed first when appropriate, and the normal shared
state transition uploads the new data. This fixed the smaller red test where the
source map claimed 5/5 visible chunks while a render pass still pointed at an old
object whose texture had been freed.

All campaign-only swap ledgers and forced-upload paths were removed. The read-only
`ChunkSource.zmartProbe` remains because it provides worker-side ground truth.

## Automated evidence so far

The decisive focused candidate run is preserved at:

`D:\zmart-codex-diagnosis-20260814\pytest-clean-final-two-gates`

It reported:

- live coverage advancing from 29.5% to 64.1%;
- 16 visible advances during the 20 commits/s storm;
- the smaller real-wheel storm/F5 comparison passing;
- `2 passed in 71.57s`.

Other focused results:

- no-black-blink Neuroglancer guard: passed;
- invalidation routing, replacement/operator state, and ETag/SSE browser guards:
  `3 passed in 19.78s`;
- backend governed-bake, announcement, and manifest-refresh guards:
  `44 passed in 54.20s`;
- `git diff --check`, Python compile, and Node syntax checks: passed.

The shareable smaller test is:

`viz_studio/tests/test_a_commit_storm_under_zooming.py::test_every_zoom_shows_the_survey_after_a_storm_of_landings`

Nickname: **real-wheel commit-storm gate**.

The full viewer suite has **not** been run.

## Operator-scale failure that supersedes the smaller green gate

The candidate was built from a clean clone and the guarded build verified a
944 KB chunk worker, a 1,575 KB async worker, and every required patch marker.
The operator then ran:

```text
show_a_run_growing.py --across 40 --spiral --core 32 --every 0.05 \
  --quick-page --port 0
```

in a fresh Codex-owned fixture. The final zoom-storm run is preserved at:

`D:\zmart-codex-diagnosis-20260814\demo-zoom-storm-0e2f597f-20260814-2140`

Observed behavior:

- the page appeared quickly once fixture preparation completed;
- the spiral visibly advanced during acquisition;
- the operator zoomed during the storm;
- the picture stopped because the acquisition actually completed;
- manifest revision reached 1600 at 23:37:55;
- `baked.json` simultaneously reached `events: 1600, tail: 1600, layout: 1`;
- F5 visibly repaired the picture.

That last point is the current release blocker. It proves the remaining defect is
in connected client state/content, even though the smaller automated test passes.

Afterward the server was deliberately stopped. The open page reported that it
could not hear the server and high-resolution tiles slowly disappeared. That is
ordinary cache eviction while offline: evicted CPU/GPU tiles cannot be refetched
without their origin. It must not be confused with the earlier connected F5
repair. The server was restored on the same `http://127.0.0.1:53201/` URL for the
operator, but that process is session-local and should not be assumed durable.

## Why the current automated gate missed it

The existing test uses a 14x14 survey with a small precommitted centre. Its live
landing phase lasts only about seven seconds. The manual recipe uses a 40x40
survey, a 32x32 committed core, and 576 live landings over roughly 29 seconds.
The small gate therefore does not reproduce the duration, number of active
chunks, or navigation/eviction history of the operator's failure.

## Next diagnostic step

Before another production change, parameterize or add an operator-scale variant
of the real-wheel gate using exactly:

- across: 40;
- precommitted core: 32x32;
- landing interval: 0.05 seconds;
- eager page check: 150 ms;
- real `mouse.wheel` zoom and canvas drag throughout the live phase;
- a quiet wait after manifest and bake both reach 1600;
- screenshots and full-canvas pixel coverage at each zoom band before reload;
- the same measurements after page reload.

On the red run, capture before F5:

- `window.zmartChunkInvalidation` delivery counters;
- `ChunkSource.zmartProbe` for held keys, states, refresh batches, absent keys,
  overlaps, pending keys, and whether a pump is still running;
- visible-needed versus visible-available chunk counts;
- frontend source-map chunk identity/state and whether CPU/GPU data exists;
- queue memory capacities and pending updates;
- `/data/` response statuses and ETags for disputed keys;
- manifest revision and `baked.json` stamp without making a data request that
  could itself drive recovery.

Only after this sequence is reliably red should another client fix be attempted.
The leading question is whether a long zooming run loses invalidation state for a
chunk that is temporarily absent from the worker while a stale frontend/GPU
object survives. That is a hypothesis, not yet a finding; the earlier absent-key
experiment did not heal the smaller run, so it must earn its keep against the
operator-scale red test.

## Separate clean-install blocker

A fresh `npm ci` exposed a build-order defect. The package's `postinstall` patches
the Neuroglancer source modules and then demands matching anchors in
`chunk_worker.bundle.js` before that worker stub has been compiled. The guarded
postinstall exits nonzero. Running the repository build afterward compiles the
already-patched modules and then verifies every marker successfully, but CI's
documented `npm ci && npm run build` sequence would stop at the first command.

This install-order problem must receive a narrow reproducibility fix before the
one final full-suite run. Do not work around it with a stale `node_modules` tree.

## Acceptance bar

The change is ready only when all of these are true:

1. The exact 40x40/core-32 real-wheel storm is red before the fix and green after.
2. Every baked level closes its holes after the storm quiets without client demand.
3. A cold client sees the complete survey.
4. Pre-F5 and post-F5 images match at every tested zoom band.
5. There are zero black transients during the storm.
6. The clean install/build order is reproducible.
7. Focused guards remain green.
8. The full suite is run exactly once at the very end and passes.

