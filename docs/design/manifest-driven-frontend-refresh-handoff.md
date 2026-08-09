# Manifest-driven live frontend refresh

**Status:** implementation handoff; the publication and zero-copy storage
foundations exist, but this frontend integration is not implemented yet.

| Coordinate | Value |
| --- | --- |
| Repository | `https://github.com/thomdehoog/ZMART-microscopy` |
| Working branch | `agent/live-position-timepoint-publication` |
| Review base | `claude/omezarr-neuroglancer-structure-srnwu6` (`2027f911`) |
| Draft pull request | `https://github.com/thomdehoog/ZMART-microscopy/pull/8` |
| This document | `docs/design/manifest-driven-frontend-refresh-handoff.md` |

Do not compare this branch directly with `main`. It is intentionally based on
the earlier OME-Zarr/Neuroglancer structure branch. Use:

```bash
git diff origin/claude/omezarr-neuroglancer-structure-srnwu6...HEAD
```

## Decision in one sentence

The viewer is independent of the microscope and discovers new data by observing
the run's **atomic committed publication revision**; filesystem polling,
filesystem notifications and server-sent events are only triggers to reread that
truth and can never make data visible themselves.

## Why this exists

A smart-microscopy run changes while Neuroglancer is open:

- a complete new position can arrive;
- an existing position can gain a complete timepoint;
- a published position/timepoint can be explicitly replaced by a new immutable
  generation; and
- realized scene membership can change when a new position is committed.

The browser must follow those changes without being coupled to the microscope.
It must also never show a position or timepoint merely because some chunks have
appeared. A publication unit becomes visible only after all of the following are
complete and validated:

1. canonical pixels in `positions/`;
2. every advertised power-of-two pyramid level;
3. the generation-specific zero-copy routes required by both raw and seamless
   views;
4. metadata-only raw and seamless view descriptions;
5. the immutable acquisition profile and scene/layout ownership revision; and
6. the final cross-check that the gateway can serve the advertised encoded
   chunks from the canonical stores.

Only then may `zmart-live/committed.json` advance. That atomic replacement is
the visibility boundary. Files existing before it means only that a writer is
working.

This is visualization publication, not stitching. The seamless view hides
nominal overlap according to the declared ownership policy; a later stitcher is
a separate derived-data job.

## Non-negotiable invariants

The implementation must preserve these properties:

1. **The microscope does not drive the viewer.** No successful microscope HTTP
   callback, Python callback or message is accepted as evidence that data is
   complete.
2. **The manifest is truth.** Only a higher, valid `CommittedState.revision`
   changes browser-visible availability.
3. **Announcements are hints.** Missing, duplicated, delayed or invented SSE or
   filesystem events cannot expose uncommitted data.
4. **Polling is a trigger, not a readiness test.** Poll one tiny publication
   marker or its HTTP representation. Never scan chunks, timestamps across the
   OME-Zarr tree, pyramid folders, route files or position names to infer
   completion.
5. **Old-or-new, never partial.** While a candidate generation is written, the
   open viewer keeps serving the previous committed generation. After the
   atomic commit it can move to the next complete generation.
6. **Pixels have one owner.** `positions/` owns all compressed pixel payloads.
   `views/` contains metadata and routes only and must never acquire a physical
   `c/` payload tree.
7. **Stable source addresses.** A revision belongs in the source description,
   not in the source URL. Do not append `?revision=N` or create a new
   Neuroglancer source on every commit.
8. **Bounded frontend state.** Compile one source per view/acquisition product,
   never one source per position. A 10,000-position run must not produce 10,000
   frontend sources or a refresh payload listing all 10,000 positions.
9. **Selective refresh.** Refresh the raw/seamless sources affected by the
   committed acquisition change. Leave unrelated acquisition types and views
   untouched.
10. **Preserve operator state.** Refreshing must retain camera position, zoom,
    selected z/time where valid, contrast, LUTs, opacity, channel visibility,
    layer order and annotations.
11. **Committed time only.** A declared `t` capacity is not availability. The
    time control may expose only timepoints derived from published manifest
    events.
12. **Fail closed without blanking good data.** If the next manifest/configuration
    is damaged or temporarily unreadable, retain the previous complete view,
    show that it may be stale and retry. Do not show the candidate and do not
    replace a valid image with a black screen.

## Existing implementation: read this before changing code

Most of the machinery already exists. This task is an integration, not a new
live-view subsystem. Read the following in order.

### 1. Publication decisions and zero-copy contract

- `docs/design/live-position-timepoint-publication-decisions.md`
  - atomic publication units;
  - revision as truth and announcement as hurry-up;
  - source refresh without page reload;
  - acquisition-profile sealing and overlap ownership.
- `docs/design/zero-copy-acquisition-optimizer.md`
  - `positions/` pixel ownership;
  - metadata-only raw/seamless views;
  - strict overlap/chunk/pyramid/shard geometry;
  - generation-specific routing and fail-closed gateway behavior.
- `docs/design/live-writer-and-linked-views-plan.md`
  - especially Phase 1 and Phase 2 under live publication;
  - historical physical-view language is superseded where the zero-copy
    optimizer document says so.

### 2. Durable publication truth

- `zmart_live/manifest.py`
  - `RunManifest.fingerprint()` cheaply notices replacement of the truth file;
  - `RunManifest.committed()` returns `CommittedState`;
  - `CommittedState.revision` is run-wide and monotonic;
  - `CommittedState.by_store` records the latest revision per position;
  - `RunManifest.events(after=..., published_only=True)` reads only committed
    history and already supports an incremental tail cursor;
  - `RunManifest.publish()` appends/fsyncs history and atomically replaces
    `committed.json` last.
- `zmart_live/model.py`
  - `CommitEvent` and the event types `position_committed`,
    `timepoint_committed` and `position_replaced`;
  - readiness fields, acquisition identity, layout revision and timepoint.
- `zmart_live/coordinator.py`
  - the actual write, inspect, route-generation, rollback and publication order;
  - do not add a second, weaker publication route around this coordinator.

### 3. What the viewer is allowed to read

- `zmart_live/gateway.py`
  - reloads its cached live state when the manifest fingerprint changes;
  - rejects uncommitted timepoints/generations and invalid route identity;
  - is already integrated into the production data-serving path.
- `zmart_live/viewroute.py` and `zmart_live/shardlink.py`
  - stable virtual chunk routing to exact encoded ranges in canonical shards;
  - route identity and encoded-byte validation.
- `zmart_live/scene.py`
  - `CompiledSource.url` is stable;
  - `CompiledSource.revision` and `layout_revision` already travel beside it;
  - `compile_for_neuroglancer()` produces a payload bounded by views/layers,
    not by positions.

### 4. Existing backend notification path

- `viz_studio/backend/announcements.py`
  - `Announcements` fans one event out to every browser using SSE;
  - the existing `FolderWatcher` watches `Library.revision()`, which is generic
    filesystem discovery and is **not** sufficient publication truth for a
    `zmart_live` run.
- `viz_studio/backend/server.py`
  - `/api/events` implements the existing SSE connection;
  - `/api/config` rebuilds the current frontend description;
  - `config_now()` currently caches against `Library.revision()`;
  - the request path already calls `answer_from_a_live_run()` so uncommitted
    live pixels fail closed;
  - preserve the ordinary non-`zmart_live` folder-viewing behavior.

### 5. Existing frontend refresh path

- `viz_studio/frontend/src/App.jsx`
  - opens one `EventSource('/api/events')`;
  - `catchUp()` coalesces bursts and remembers an event received during an
    outstanding request;
  - `applyConfig()` preserves layer controls;
  - navigation coordinates are restored after a real scene reshape;
  - reconnect already performs an initial catch-up.
- `viz_studio/frontend/src/engine.js`
  - `syncLayers()` and `syncSources()` update existing layers instead of
    rebuilding the page;
  - `forgetWhatWasReadAbout()` selectively removes cached source metadata;
  - `letGoOfDecodedPieces()` is currently broad and must not become the default
    response to every live commit;
  - `framesSeen` currently detects per-store growth for the older many-store
    layout and suggests the shape of the source-revision implementation.
- `viz_studio/frontend/src/scene.js`
  - translates backend descriptions into stable Neuroglancer layer/source
    specifications.

### 6. Tests that explain the intended behavior

- `zmart_live/tests/test_manifest.py`
- `zmart_live/tests/test_gateway.py`
- `zmart_live/tests/test_scene.py`
- `zmart_live/tests/test_coordinator.py`
- `zmart_live/tests/browser/`
- `viz_studio/tests/test_live_publication_gateway.py`
- `viz_studio/tests/test_announcements.py`
- `viz_studio/tests/test_a_run_arriving.py`
- `viz_studio/tests/test_the_newer_format_arriving_live.py`
- `viz_studio/tests/test_writing_into_one_store.py`
- `viz_studio/tests/test_engine_is_not_disturbed.py`
- `viz_studio/tests/test_masks_luts_and_refresh.py`

The browser harness contains useful mechanisms but is not proof that this
production integration exists. Follow the path from a real
`RunManifest.publish()` through the production backend and the actual React
frontend.

## Target architecture

```text
independent writer/coordinator
    |
    |  write canonical position/timepoint and every pyramid
    |  write immutable-generation raw/seamless routes and metadata
    |  validate gateway-readable encoded chunks
    v
atomically replace zmart-live/committed.json       <-- publication truth
    |
    | one backend watcher notices only the marker changed
    v
existing /api/events SSE                           <-- hurry-up signal
    |
    | browser fetches authoritative live state/config
    v
compare run/layout/source revisions
    |
    | refresh only affected stable Neuroglancer sources
    v
new complete data appears; operator state remains
```

The backend, not every open browser, should watch the local publication marker.
One watcher can fan out through the existing `Announcements` object. This keeps
idle work independent of the number of browser tabs.

The writer does not need to know that a viewer exists. An optional direct nudge
from a writer can reduce latency, but it must remain dispensable and must never
carry authority. The implementation is correct when a writer that knows nothing
about `viz_studio` still becomes visible after advancing the manifest.

## Proposed backend implementation

### A. Add a manifest watcher for live runs

Introduce a narrowly scoped watcher, for example `ManifestWatcher`, rather than
teaching the generic `FolderWatcher` to infer ZMART publication semantics.

Its responsibilities are:

1. open the run with `RunManifest.open(run_root)`;
2. retain the last manifest fingerprint and last valid committed revision;
3. check `RunManifest.fingerprint()` at a modest interval, initially about one
   second;
4. only when the fingerprint changes, read `RunManifest.committed()` or a new
   strict reader appropriate to the server;
5. announce when a valid revision is greater than the last announced revision;
6. tolerate a jump from revision 41 directly to 44 and catch up to the latest;
7. ignore duplicate, regressing or malformed state, retain the old state and
   report degraded freshness; and
8. stop with the server and keep only one watcher per opened live run.

`RunManifest.committed()` deliberately turns damaged state into an empty state
for safe pixel serving. A watcher must not interpret that temporary revision
drop as a new scene. Consider adding an explicit strict read method or using
`RunManifest.open()`/validation in a way that distinguishes “nothing has ever
been published” from “the truth file is damaged.”

Polling here is deliberately uninteresting: it stats one tiny file. It does not
parse the history on every tick and does not inspect any OME-Zarr file. On
Windows/SMB, filesystem notifications and metadata caching require real
qualification; a notification can be an immediate nudge, while the periodic
marker check remains the recovery path.

### B. Expose authoritative bounded live state

Either extend `/api/config` cleanly or add a cheap endpoint such as:

```http
GET /api/live-state
```

with a bounded answer resembling:

```json
{
  "schema": "zmart-live-frontend-state/1",
  "run_id": "run-123",
  "revision": 42,
  "layout_revision": 7,
  "sources": {
    "overview:seamless": 42,
    "overview:raw": 42,
    "target:seamless": 39,
    "target:raw": 39
  },
  "committed_time_ranges": {
    "overview:seamless": [{"start": 0, "stop": 14}],
    "overview:raw": [{"start": 0, "stop": 14}],
    "target:seamless": [{"start": 0, "stop": 5}],
    "target:raw": [{"start": 0, "stop": 5}]
  }
}
```

The exact schema should follow the compiled scene and frontend vocabulary
rather than copying this example mechanically. Requirements are:

- source revisions come from `CompiledSource.revision`;
- source URLs remain unchanged;
- the response is bounded by acquisition products/views, not positions;
- timepoint availability is derived from committed `CommitEvent`s, not array
  shape or files on disk;
- availability uses half-open ranges or another unambiguous representation; a
  single high-water mark is valid only if contiguous publication is separately
  enforced, which the current manifest does not assume;
- run identity and layout revision are explicit;
- responses are not served from a stale HTTP cache (`Cache-Control: no-store`
  or correctly implemented conditional requests/ETags);
- the frontend can cheaply determine that nothing changed without rebuilding
  the complete scene.

The append-only event reader already keeps a cursor. Reuse it to maintain
derived timepoint availability instead of rereading all history after every
commit. Do not enlarge `committed.json` with an ever-growing list unless a
measured need justifies a schema change and migration plan.

### C. Send an SSE nudge after observing a commit

Reuse `/api/events` and `Announcements`. A message may remain the current
generic `changed` event, or carry `run_id` and the observed revision to improve
deduplication. In either case:

- the payload is never applied as publication truth;
- the browser fetches current authoritative state after receiving it;
- duplicate events do nothing after revision comparison;
- an event received during an outstanding request causes one further catch-up,
  not an unbounded request queue; and
- reconnect performs a current-state read.

A slow browser-side safety check of `/api/live-state`, for example every 5–10
seconds, is acceptable as protection against a lost notification. It is still
only a revision trigger: unchanged replies do not touch Neuroglancer. Prefer a
conditional request so the normal answer is `304 Not Modified` or an equally
small revision response.

### D. Keep ordinary folder viewing intact

`viz_studio` also opens OME-Zarr folders that have no ZMART manifest. The new
path should be selected only when a valid `zmart-live` run is detected. Existing
generic live-folder discovery and static viewing must continue to work, with
their current tests left green.

## Proposed frontend implementation

### A. Track revisions separately from addresses

Retain in frontend state:

- current `run_id` and global revision;
- current `layout_revision`;
- last applied revision per compiled source; and
- committed time availability per source/view.

Reject or visibly report a response that changes `run_id`, regresses revision,
or disagrees internally. Do not quietly reinterpret one run as another.

Extend the existing `framesSeen`/`syncSources()` pattern with source revisions.
When a source revision is unchanged, leave its data source and cache completely
alone. When it advances, refresh that stable source inside its existing layer.

### B. Refresh the source, not the page or all layers

For each affected source:

1. remove the memoized metadata/configuration for that source URL;
2. make the existing layer resolve that stable source again;
3. invalidate decoded data only for the affected view when a newly committed
   position/timepoint may occupy coordinates Neuroglancer previously found
   empty; and
4. let Neuroglancer request only chunks needed for the current viewport.

Do not call the current broad `letGoOfDecodedPieces()` for every commit without
first narrowing it to affected sources and measuring the requests it causes.
Neuroglancer cache APIs used here are partly internal, so pin their behavior
with tests. If chunk-coordinate-level invalidation is not practical, invalidating
the one affected aggregate view source is acceptable; rebuilding the page or
unrelated sources is not.

Both raw and seamless products normally change when their acquisition receives
a commit, so refreshing those two small sources is expected. A target
acquisition commit must not disturb overview sources, and vice versa.

### C. Preserve operator state using the existing mechanisms

Do not replace the React application or Neuroglancer viewer. Reuse:

- `layerKey()` and the existing state reconciliation for contrast, LUT,
  visibility and opacity;
- the current navigation snapshot/restore by axis name;
- the persistent annotation layer;
- `catchUp()` burst coalescing and `missedWhileAsking`; and
- `syncLayers()` incremental source/layer updates.

Only clamp time/z when the previous selection is not valid in the newly
committed state. A new position must not recenter the operator automatically.

### D. Treat committed timepoints as availability

The storage profile may reserve timepoint room at acquisition start. That keeps
array metadata stable but does not mean those future moments exist.

The time slider must stop at committed availability. When a position's next
complete timepoint commits, the relevant source revision and available time
advance together. A view can show positions with that committed timepoint and
leave other positions absent where their corresponding moment is not committed;
it must never read their partly written moment.

If a future implementation grows the declared Zarr `t` shape, metadata resize,
routes and chunks must still be one publication transaction. That is outside the
current declared-room convention and must not be slipped into this task without
new design and tests.

## Publication and refresh race analysis

The implementation must reason explicitly about these orderings:

### Candidate being written

The watcher sees no new committed revision. The frontend remains on the old
revision. Gateway requests continue to resolve through the last committed
generation, even if candidate files already exist.

### Commit lands between two watcher checks

The next marker check observes the new fingerprint/revision and announces it.
Latency is at most the check interval; correctness is unchanged.

### Several commits land in one interval

The watcher may observe only the newest revision. That is fine: history retains
the individual events, derived availability processes their committed tail, and
the viewer catches up directly to the newest complete state.

### SSE event is missed or duplicated

A duplicate is removed by monotonic revision comparison. A disconnect causes
EventSource to reconnect and the existing `onopen` catch-up reads current state.
A slow conditional live-state check prevents a silently lost hint from leaving
the page stale indefinitely.

### Event arrives during a config request

Keep the existing `missedWhileAsking` behavior: complete the current request and
make one more request. Do not start parallel configuration rebuilds.

### Manifest is unreadable during refresh

Retain the previous applied revision and image, surface a stale/degraded warning
and retry. Never treat a safe empty-state fallback as a legitimate revision
regression.

### Browser already cached an empty future location

Committed time controls prevent browsing future `t` values. A newly occupied
spatial location or explicit replacement still requires invalidation of the
affected aggregate view source so cached absence cannot survive the commit.

## Required tests

Tests must cover the real path, not only a synthetic browser server.

### Manifest watcher and API tests

1. Writing canonical chunks without committing produces no live revision change
   and no announcement.
2. Writing pyramids, routes or view metadata without committing also produces no
   announcement.
3. One atomic manifest commit produces one effective revision advance.
4. Duplicate observations/events do not cause duplicate refresh work.
5. Revisions can jump and the derived event cursor catches up correctly.
6. Damaged/regressing/wrong-run manifest state retains the previous good state
   and reports failure instead of publishing an empty or foreign scene.
7. Source revisions and timepoint availability are derived only from published
   events.
8. The live-state/config payload remains bounded as position count grows.
9. Ordinary folders without `zmart-live` retain their existing behavior.

### Frontend unit/integration tests

1. Unchanged source revisions cause no Neuroglancer metadata or chunk requests.
2. An overview commit refreshes raw and seamless overview sources only.
3. A target commit does not refresh overview sources.
4. Stable URLs stay stable across revisions.
5. Camera, zoom, z/time, contrast, LUT, opacity, order, visibility and
   annotations survive refresh.
6. A burst of events is coalesced and the newest revision wins.
7. A failed state/config request keeps the previous image and displays a stale
   warning.
8. A lost SSE hint is recovered on reconnect or the slow revision check.
9. Cached empty data in an affected view is actually invalidated after commit.
10. No broad cache flush occurs for an unrelated source.

### Load-bearing real-browser test

The central acceptance test is:

```text
commit position A
    -> A is drawn and measurably non-black

write all or part of position B, but do not commit it
    -> A remains drawn with unchanged non-zero brightness
    -> B remains invisible in raw and seamless views

commit B after all canonical pyramids/routes/views validate
    -> B appears automatically without a page reload
    -> A remains drawn
    -> camera and controls do not move or reset
```

The positive assertion on A is mandatory. A black screen can otherwise make the
“B is invisible” assertion pass dishonestly.

Add the analogous timepoint test:

```text
commit position A at t=0
write A at t=1 without committing
    -> the time control does not expose t=1
commit A at t=1
    -> the time control advances and t=1 draws without page reload
```

Also cover an explicit replacement generation and verify raw/seamless switch
together.

### Prove the tests can fail

Before trusting the suite, deliberately sabotage at least these invariants and
record that the intended test turns red:

- announce or expose a position before `committed.json` advances;
- derive time availability from Zarr shape rather than committed events;
- ignore source revision changes;
- put the revision into the source URL;
- globally invalidate all sources on every commit;
- accept a damaged/regressing committed state; and
- remove the positive “A remains bright” assertion from the browser scenario.

Use the repository's existing mutation/fault-campaign style rather than relying
only on a manual edit that is not reproducible.

## Performance expectations

Measure rather than assume these properties:

- idle cost is one tiny manifest check per backend watcher interval, independent
  of browser count and position count;
- no pixel request is made merely because the watcher checked the marker;
- a commit rebuilds bounded live state and reads only the committed history tail;
- a commit refreshes only the affected raw/seamless acquisition sources;
- no page reload occurs;
- no one-source-per-position regression occurs; and
- Neuroglancer refetches visible affected chunks, not the complete dataset.

Test at least a many-position synthetic run and inspect request counts. The
logical chunk grid can still be large even though sharding controls physical
file count; refresh must not accidentally ask for every logical chunk.

## Explicit non-goals

Do not expand this implementation into:

- microscope control or a microscope-specific notification protocol;
- stitching, blending, drift correction or seam registration;
- analysis-worker implementation;
- OME-Zarr scenes serialization;
- changing the strict acquisition overlap/chunk/shard optimizer;
- growing beyond declared timepoint capacity;
- physical view chunks or copied pyramids;
- one source/layer per position; or
- full Windows/SMB qualification beyond documenting and testing what the
  available environment can establish.

## Suggested implementation sequence

1. Add tests for strict manifest-driven watcher behavior before changing the
   backend.
2. Add the manifest watcher and bounded authoritative live-state/config adapter.
3. Connect it to the existing `Announcements` SSE fan-out while retaining
   non-ZMART behavior.
4. Add source revisions and committed time availability to the frontend schema.
5. Extend `syncSources()`/`syncLayers()` for selective stable-source refresh.
6. Add failure handling and the slow lost-hint recovery check.
7. Run the real backend/browser publication and timepoint scenarios.
8. Add reproducible sabotage/mutation cases and request-count assertions.
9. Update this document and the two live-publication design documents with the
   verified implementation status and remaining environmental limitations.

## Definition of done

This work is complete only when all of the following are demonstrated:

- a writer with no knowledge of the viewer becomes visible solely by completing
  the normal coordinator publication transaction;
- no filesystem artifact except a valid higher committed revision can trigger
  visibility;
- raw and seamless views advance together after their routes and metadata are
  ready;
- new positions, appended timepoints and explicit replacements appear in an
  already-open production frontend without page reload;
- lost/duplicate notifications cannot permanently stale or incorrectly advance
  the viewer;
- operator state is preserved;
- refresh work stays bounded by affected views rather than positions;
- existing static and generic live-folder behavior remains green;
- mutation tests prove the safety assertions can fail; and
- the exact tests run, browser actually used, skipped visual checks and untested
  Windows/SMB boundaries are reported honestly.

## Validation commands to begin with

Use the repository environment rather than silently creating a parallel stack.
At minimum, run the focused production suite already used on this branch:

```bash
.venv/bin/pytest -q \
  zmart_live/tests \
  viz_studio/tests/test_live_publication_gateway.py
```

Then run the affected `viz_studio` announcement, live-arrival, refresh and
browser tests. Read `viz_studio/TESTING.md` and `viz_studio/run_tests.py` before
claiming the browser suite ran: a skipped browser test or an unavailable
Chromium executable is not visual verification. Also run Ruff on changed Python
files and `git diff --check`.

Repository-wide collection may require optional imaging/browser dependencies
not needed by this focused production path. Report such environmental blockers
separately; do not use them to conceal failures in the affected tests.
