# Second review of the rendering-engine design

Date: 2026-09-02

## Verdict: accept with changes

The revision has answered the reason for my earlier `rethink` verdict openly,
and it has put the work in a defensible order: measure the existing path, design
and test the data layer under Neuroglancer, and only then design the first small
engine. I accept the owner's decision to build that engine as a product choice,
not as a conclusion proved by performance evidence.

The record is not ready to hand unchanged to the data-layer design. Its proposed
register additions do not yet fit the existing immutable records, its tile
revision would defeat its own selective invalidation, and several scientific and
measurement rules still leave the implementer to choose the answer. These are
repairable specification faults. They do not require abandoning the chosen
engine or the revised order of work.

## Scope and evidence

I read ZMART-microscopy commit
`51085440d5db136a9592534021a8f431448b5aa5` on my branch
`codex/second-review-own-rendering-engine`. The review brief in that commit still
names `3bbf9c0b`; that is its parent design revision, while `51085440` adds the
brief. I followed the user's later and more specific instruction to review
`51085440`. I read ZMART Viewer commit
`9b67bf8e843b5b80145f210fb3b180e2fce554ff`. I also compared the scheduler with
Neuroglancer 2.41.2, pinned at `application/package.json:38`, using its source at
commit `e13f1f4c62918f2ea07b12f2116bdcb6767b1499`.

I read “The one decision that was contested” first, “Decisions on the two
reviews” second, and then the record from the beginning. I read both earlier
reviews, both prior-art notes, phases 0 and 1 of the lazy-pyramid record, the
“What 100% does not do” section, and `CLAUDE.md`. This was a read-only design and
source review. I did not implement or run the proposed engine.

## Findings, ordered by consequence

### 1. The register extension still combines facts known at different times and records that have different meanings

**Facts.** The record says that the bridge writes the complete layout at scan
start, including each position's “raw recorded height”, and that nothing new has
to be known (`docs/design/own-rendering-engine-and-position-register.md:249-254`).
The scan plan is known then, but the observed coordinates and vendor files are
not. The bridge calls the microscope's `acquire` first and receives the capture
record afterwards; only then does it convert the field and append that record to
memory (`application/framework/bridge.py:702-713`).

The existing `SceneLayoutRevision` is an immutable description with one
`profile_id` for all its positions (`zmart_viewer/record/model.py:1250-1291`). A
`CommitEvent` is specifically a declaration that pixels and their dependencies
are ready. It requires a position, channels, levels and readiness checks
(`model.py:1400-1528`). `RunManifest.publish` advances `by_store` for every such
event (`zmart_viewer/record/manifest.py:743-880`), and both the gateway and live
state treat every event as an arrived position (`record/gateway.py:169-191`;
`record/live_state.py:287-324`). A terminal event or a skip event therefore
cannot simply be added to the current `EVENT_TYPES` tuple without being mistaken
for published image data.

The collection model is also unresolved. The new record says that every
collection has its own register, but that one collection may contain several
profiles (`own-rendering-engine-and-position-register.md:157-165`). The existing
gateway loads exactly the one profile named by the layout
(`zmart_viewer/record/gateway.py:222-258`), and `LivePublisher` accepts one profile
and writes one hard-coded collection (`record/coordinator.py:181-198`,
`:502-512`). There is no run-level catalogue that discovers several collection
registers after position-folder listing is removed.

**Inference.** The data-layer record must define three separate durable facts.
The planned layout should contain the intended stage position known before
capture. An immutable observation associated with the pixel commit should hold
the actual x, y and z for each captured plane, together with its time/channel
coordinates and source-file provenance. A lifecycle record should hold terminal
and skip events without making them look like pixels. The signed publication
marker and every gateway fold then need a versioned rule for all three kinds.

The same record must choose how heterogeneous fields are represented. The
simplest compatible choice is one homogeneous acquisition instance and one
complete sealed profile per manifest, with a small run-level catalogue grouping
those instances into the collection the operator sees. The alternative is a
larger schema change that puts a profile reference on every placement and teaches
the coordinator, manifest, gateway, routes and composer to use it. Leaving this
choice to implementation would put scientific geometry and run discovery into
code by accident.

### 2. A global revision in every tile key contradicts selective dirty-region reuse

**Facts.** The record includes `revision` in the identity of every tile
(`own-rendering-engine-and-position-register.md:173-177`, `:362-365`). It also
says that after revision changes, the engine drops only cached tiles that
intersect the published dirty boxes (`:400-408`). A tile cached under revision 7
does not have the same key as an otherwise identical request under revision 8.
No rule in the record aliases or promotes an untouched revision-7 tile to
revision 8.

The proposed address also says “slice or projection with its kind and range” but
does not explicitly name a slice coordinate. Orientation says which way the
picture faces; it does not say which z, x or y section is being shown. Layout or
placement revision, calibration/presentation-transform identity, and the version
of a projection recipe are absent. Each can change an assembled or derived tile
without changing a position store's pixel generation.

**Inference.** As written, every landing makes every requested address new, so
the cache must miss globally even while the invalidation text promises local
reuse. Keep the run revision as the snapshot against which an answer is
validated, but key reusable tile content by its own generation or validator.
Alternatively, specify how all untouched entries are relabelled in one safe step;
that is more bookkeeping and should be justified.

There should not be one universal key for every tier. A raw source-chunk key, an
assembled slice-tile key and a stored projection key have different dependencies.
The slice key needs its axis and exact section coordinate. An assembled tile also
needs the layout and presentation transform that placed its sources. A projection
needs its axis, half-open physical range, reduction recipe/version and the
generations of its inputs. Data kind and numeric type validate a cache entry and
select its texture pool. The window, colour, opacity and provisional/settled
state are drawing inputs, not pixel identity; changing brightness must not fetch
or recompute pixels. The coverage mask belongs with the tile payload and changes
with that tile's content generation.

### 3. The geometry is much clearer, but exact plane selection and projection arithmetic remain scientific choices

**Facts.** The revision now preserves raw plane heights, demands a calibrated
stage/specimen frame, uses low and high voxel-edge names, gives aligned placement
one physical meaning, and gives a side section its own x/y slider and line-of-sight
projection axis (`own-rendering-engine-and-position-register.md:82-121`). Those
are substantial corrections.

The current writer receives a stage point at the centre of the frame and turns it
into the low x/y voxel corner by subtracting half a frame
(`application/parts/storage/zarr_positions.py:322-362`). The revised record does
not yet say how a recorded z plane centre becomes its two voxel edges, especially
when adjacent recorded heights are irregular. “The plane whose voxel interval
contains that offset” is ambiguous exactly where two intervals meet unless the
intervals are half-open and the last outer edge has a stated rule. It also does
not say whether per-channel readings of nominally the same plane must agree or
are preserved separately.

For side views, the record leaves overlays “hidden or re-projected” and does not
fix which direction stage z appears on screen (`:435-437`). For projections, it
says that across stacks with different z steps only a mean is offered
(`:130-135`). An ordinary arithmetic mean still weights every acquired plane
equally; stacks sampled more finely therefore represent physical depth
differently. A 32-bit unsigned sum also overflows for more than 65,537 maximum
`uint16` planes, and the output type of a mean is not named.

**Inference.** Before implementation, define observed plane centres and derive
half-open plane intervals, including terminal edges, duplicate heights, reversed
acquisition order and irregular spacing. State the exact conversion from planned
stage centre to voxel edges, preserve observed x and y as well as z, and bind all
of it to a calibration revision. Later side-view records must choose screen-axis
direction and either hide or re-project each overlay rather than offer both as an
implementation choice.

A projection over a physical depth should either use each plane's represented
thickness as a weight or be explicitly named a sample mean whose value can depend
on sampling density. The accumulator must be selected from the input type and
maximum plane count, with overflow refused; “32-bit” is not a universal answer.
The range should be half-open in micrometres, and the result type and missing-data
rule should be stated for maximum, mean and sum.

### 4. The scheduler still omits parts of the Neuroglancer behavior that the decisions section says were taken

**Facts.** The revised engine now names priorities, a request limit, pre-emption,
retry, fairness, stale-result rejection, worker-to-main-thread hand-off, oversized
pinned planes and WebGL context loss
(`own-rendering-engine-and-position-register.md:366-381`). Neuroglancer 2.41.2
has separate `VISIBLE`, `PREFETCH` and `RECENT` tiers, numeric priority inside the
first two, item and byte capacities for download, computation, system memory and
graphics memory, and different requested states for CPU-resident and GPU-resident
chunks (`src/chunk_manager/README.md:14-59`;
`src/chunk_manager/frontend.ts:101-145`;
`src/chunk_manager/backend.ts:1232-1321`). Its front end also stops starting GPU
copies after a per-frame deadline (`src/chunk_manager/frontend.ts:101-180`).

Neuroglancer uses a data-management worker plus a separate asynchronous
computation pool of up to twelve workers. The pool can cancel a task while it is
waiting, but `requestAsyncComputation` does not stop a task already posted to a
worker (`src/async_computation/request.ts:17-37`, `:84-123`). The record instead
fixes “one worker” and asserts that raw pixels would double network bytes
(`own-rendering-engine-and-position-register.md:382-385`). Its current Viewer
pieces are zstd-compressed (`zmart_viewer/compose.py:659-670`), so the ratio to
raw data depends on the specimen and must be measured.

**Inference.** Still specify explicit prefetch and recent-retention behavior,
per-view reprioritisation, coalescing of duplicate requests, separate download,
decode/compute, hand-off and upload capacity, and a per-frame upload budget. The
last item was in my earlier finding and in the cited napari lesson, but is absent
from the revised engine body; this is a genuine softening. State what cancellation
can stop at each stage and how transferred buffers are reclaimed.

One worker is a hypothesis, not part of scheduler parity. A single worker can
manage several asynchronous fetches but can serialize CPU decoding. Choose one or
a pool from the measured codec and hand-off cost, while keeping the drawing thread
free in either case.

### 5. Several gates need definitions or new instruments before they can be won honestly

**Facts.** The current measurement server records requests, response bytes,
concurrency and elapsed request time (`viz_studio/options/measure/data_server.py:63-149`).
The external-run measurement records one time to a settled picture, a request
ledger and a photograph (`viz_studio/options/measure/real_run.py:92-118`). The
harness page opens a drawing option directly; it does not include the operator
panel (`viz_studio/options/harness/src/main.js:444-522`). The panel's declared,
provisional, settled, waiting and unreadable behavior is instead covered by
separate JavaScript tests (`application/parts/canvas/viewer-panel-authority.test.js:9-142`).
There is currently no instrument there for the proposed server/decode/handoff/
upload/draw breakdown, graphics-memory residency, per-tile dirtying or shader
inputs.

“First picture is no slower” has no definition of useful picture, repetitions,
cold/warm state or tolerance (`own-rendering-engine-and-position-register.md:533-538`).
“Requests ... are fewer” cannot be won on a warm navigation where both engines
make zero requests, or on a workload where both request the mathematical minimum
(`:539`). “Memory stays within the budget” can always pass if the budget is set
after the result (`:540`). The coverage data gate speaks of removing every
request “for a position”, although the browser requests composed tiles, some of
which contain both arrived and absent positions (`:529`).

**Inference.** Permit and name an instrumentation-only phase before the baseline;
otherwise “nothing ... built before its numbers exist” forbids the work needed to
obtain those numbers. Freeze the fixtures, repetitions, budgets and tolerances
before running. Reuse the earlier definition of a useful picture, report process
cold and warm separately, and compare confidence intervals or a declared
tolerance within which the new engine counts as no slower, rather than literal
single-run equality.

Require fewer requests on a named sparse, cold trace and no more requests on all
other traces. Define the coverage gate as zero requests for an output tile whose
footprint contains no committed coverage. Define a read at the storage boundary,
not merely an HTTP request. Add instruments for source reads, decode and transfer
queues, cache bytes, graphics allocations, uploads, dirty-key sets and stale
frames. Run panel-state equivalence in an application-level harness or stop
calling it a harness gate. Finally, compare pixel values and masks, overlap order,
level changes and revision changes automatically; “same pixels” in an
introductory sentence is not itself a correctness gate.

### 6. The scale arithmetic is useful, but three statements presented as current facts are not established

**Facts.** The two storage examples agree with the code when their unstated type
is `uint16`. A 512×512 position has seven levels down to 8, 25 spatial chunks per
channel and eight description files, giving about 330,000 files and 6.51 GiB for
10,000 monochrome, one-plane, one-timepoint fields. A 2048×2048 position has nine
levels and 345 spatial chunks per channel; three channels plus descriptions give
about 10.45 million files and 312.5 GiB. The source chunk is 128
(`application/parts/storage/zarr_positions.py:54`, `:163-177`), the composed
piece is 512 (`zmart_viewer/compose.py:659`), and the storage library applies a
requested shard only to level 0 (`zmart_storage/canvas.py:2090-2140`). The record's
roughly 2,600 kept channel pieces and 1.3 GiB are also correct for a contiguous
100×100, no-overlap, `uint16`, three-channel plate at one depth and time.

The record says a repeated scan of one type is currently refused
(`own-rendering-engine-and-position-register.md:244-248`). In fact, the bridge
resets the in-memory records and reuses the same names
(`application/framework/bridge.py:849-889`); its position path calls the
low-level `_declare_one` (`application/parts/storage/zarr_positions.py:92-177`),
whose `mode="w"` empties an existing store (`zmart_storage/canvas.py:1966-1969`).
The future rule—new collection identity and folder—is correct, but the statement
about today's behavior is false.

The record also states that a folder scan on the share takes longer than the
thirty-second interval (`own-rendering-engine-and-position-register.md:300-304`)
while later listing the real-share cost model as unmeasured (`:509-512`). It
states that raw pixels would double bytes, although compression makes that
data-dependent. Both are estimates or hypotheses, not checked facts.

**Inference.** Print `uint16`, 100×100 contiguous placement, no overlap, and one
depth and time beside the numerical example. Keep the 170,000-read figure as an
order-of-magnitude estimate, not a measured duration; an ideally aligned
2048-pixel case touches about 150,000 one-chunk position levels across five kept
levels and three channels before overlap and cache effects.

Sharding need not preserve every level currently written. Every retained level
whose small-file count is material needs a sharding design, but a level can be
dropped instead if no independent OME-Zarr consumer or Viewer route needs it and
the measured kept product supplies the corresponding zoom. That decision depends
on independent opening of a position, the linked-view contract, actual z/time/
channel counts, write-once versus patched data, range-read cost and results on the
real share. Patched kept levels should remain unsharded unless a different
partial-write design is measured.

## Answers to the eight questions

### 1. Were my earlier findings carried faithfully?

1. **The conditional engine decision:** the record does something weaker than I
   asked, and labels the refusal honestly. It takes phase 0, the breakdown, the
   data-layer-first comparison and the performance gate, but not my condition
   that a failed named metric authorise the engine. This is not a softened
   “taken” claim; it is the contested decision stated plainly.
2. **Use the existing register:** mostly taken, but weaker in the body. The
   versioned extension, stable identities, terminal outcome, planned/observed
   separation, provenance, display-contract reference and legacy path are all
   present. The body lacks the run-level index for several collections and does
   not show how observation, skip and terminal records coexist with pixel commits
   and signed truth. “One profile per frame shape” is not the rule the current
   package enforces.
3. **Define z and the later views:** substantially taken. Raw plane heights,
   frame provenance, low/high edges, one micrometre-based aligned meaning, the
   side slider and the side projection axis are present. Exact plane intervals,
   observed-coordinate timing, side orientation and overlay behavior remain
   weaker than requested.
4. **Carry the display contract through the cache and shader:** substantially
   taken. Stable collection/channel/source identity, types, format pools, window
   state, masks, overlap order and projection-specific windows are present. The
   missing slice coordinate, geometry/recipe dependencies and global-revision
   contradiction mean the identity is not yet complete or minimal.
5. **Specify the scheduler and make performance a fair hypothesis:** partly
   taken. The record adds most named states and failure cases and uses the same
   data layer. It omits metered uploads, detailed prefetch/recent behavior,
   separate compute capacity and request coalescing, while fixing one worker
   without measurement.
6. **Replace global fan-in K with a measured cost model:** taken as asked. The
   model includes chunks, bytes, codecs, channels, planes, overlap, cache state,
   concurrency and storage medium; it separates persistence from memory and
   refuses stale kept tiles. The outlier guard still needs a numerical rule.
7. **Make the ten-thousand claim include files, bytes, tile sizes and sharding:**
   taken in substance. The arithmetic and level-0-only sharding qualification are
   present, and the tiny-level decision is left to the next record. The fixture
   assumptions and unmeasured share timing need clearer labels.
8. **Withdraw the premature three-dimensional architecture:** taken faithfully.
   The first engine carries no atlas or three-dimensional abstraction, and the
   prior-art note opens with the correction. The note should now remove or mark
   its later, still-visible “every serious system” and fixed-atlas claims rather
   than ask a reader to remember that the opening retracts them.

The earlier paste-back is therefore mostly present. Its engine condition was
explicitly refused; its register, geometry, identity, measured cost, sharding and
small-first-engine requests were accepted. The half-carried parts are the
collection index, event compatibility, exact geometry, complete cache identity
and upload scheduling. The record also keeps later labels, projections,
alignment and side views as product milestones, which I did not ask it to do but
which does not burden the first engine. Mandating exactly one worker is another
addition; unlike the later milestones, it should be removed until measured.

### 2. Is the geometry defined tightly enough to implement without choosing its meaning in code?

Not yet. The scientific intent is now clear, but an implementer would still have
to choose how an observed stage-centre height becomes voxel edges; how irregular,
duplicate or reversed plane centres define half-open intervals; which plane owns
an exact shared edge; how observations across channels and times are associated;
and which calibration revision interprets them. For side views they would choose
the screen direction of z and whether each overlay is hidden or re-projected.
For projections they would choose physical weighting, range inclusion, output
type, overflow and missing-plane rules. These choices belong in the data-layer
record or the later mode records, never only in code.

### 3. Is the register extension complete and consistent with the Viewer record?

No, for the concrete reasons in finding 1. A sealed profile contains much more
than frame shape: axes, dtype, voxel size, overlap, topology, ownership, halo,
levels, chunks/shards, codecs, channels and time room
(`zmart_viewer/record/model.py:696-750`). Fields that differ in any of those
scientifically or structurally significant properties need different complete
profiles, not merely one profile per size. The present layout and gateway can use
only one such profile per manifest.

Planned coordinates fit an immutable layout. Observed plane coordinates and
vendor provenance do not exist at layout creation and need an immutable record
published with the capture. Terminal and skip facts are not pixel commits and
need a separately named lifecycle record or separate versioned stream; the signed
truth file must cover them without adding them to `by_store`, and readers must
fold them without calling skipped positions arrived. A run-level catalogue is
needed to discover and order several collection manifests. With those choices,
the profile can stay sealed, layouts can stay immutable, events can stay
append-only and the small publication marker can remain the authority.

### 4. Is the end-to-end identity right and minimal?

No. It is missing the slice axis and coordinate, layout/presentation-transform
identity, and a derivation-recipe version for stored projections. A composite
tile also needs an unambiguous dependency on all contributing source generations,
not a singular “source generation” whose meaning is left open.

The run-wide revision should not be part of reusable tile content identity unless
the record defines how unchanged content is promoted between revisions. It
belongs in snapshot validation. Window values and their declared/provisional/
settled state also do not belong in a pixel key; they are shader state. Data kind
and type belong in immutable source metadata and cache-entry validation, and the
coverage mask belongs in the payload. Split raw-chunk, assembled-tile and derived-
tile identities rather than forcing all three through one address.

### 5. Does the scheduler now cover what Neuroglancer does?

It covers the main outline but not the full behavior. Still missing are explicit
promotion and demotion among visible, prefetch and recent tiers; periodic
reprioritisation as the view changes; duplicate-request coalescing; separate item
and byte capacities for download, computation, system memory and graphics
memory; a CPU-only requested state for prefetched data; and a per-frame deadline
for main-thread GPU uploads. Cancellation needs stage-by-stage meaning because
Neuroglancer aborts downloads but its async pool only cancels work that is still
waiting. Worker count and decode parallelism should be measured rather than set
to one. Retry limits, jitter and permanent-failure visibility can be completed in
the engine record.

### 6. Are the numbers and assumptions stated so that ten thousand means one thing?

The arithmetic is good, but the examples need to say `uint16`, one timepoint, one
plane, and—in the kept-level calculation—a contiguous 100×100 grid with no
overlap. “Raw pyramid” correctly excludes compression; the file count does not.
The 128 source chunk and 512 composed-piece distinction is accurate. The kept
cost is an estimate and should remain conditional on local/share, cold/warm
measurements.

The sharding prerequisite applies to every retained file-dominant level, not
automatically every level the current writer creates. Tiny levels may instead be
dropped if the independent-position and linked-view contracts still work and a
measured kept product supplies those zooms. Position data are written once and
can be sharded; coarse global data are patched repeatedly and should not be
sharded under the current whole-shard rewrite behavior. The real share's metadata
latency, range-read behavior, write rate and the actual channel/z/time fixture
decide the boundary.

### 7. Are the gates measurable and in the right order?

The order is right. The gates are not all measurable as written.

- Phase 0 needs an explicitly authorised instrumentation step. The existing rig
  cannot yet separate server, transfer, decode, hand-off, upload and draw or
  measure graphics memory. The exact real-run fixture, repetitions and local/
  share cache conditions must be frozen before the trace.
- The first two data gates can be observed with filesystem-call counters. The
  coarse gate must define “one read” and test that the publication marker moves
  only after every dirty output is current. The coverage gate must speak in
  output-tile footprints, not requests for positions. The 500 ms landing gate
  needs enough arrivals to calculate a p95 and a precise start and finish event.
- “First picture” must reuse the earlier useful-picture definition. “No slower”
  and “no worse” need a declared tolerance and repeated cold/warm traces. The
  request gate must allow equality on dense and warm traces while requiring a
  reduction on the named sparse trace. The memory budget must be fixed in advance
  and include worker buffers, main-thread arrays and graphics allocations over
  repeated navigation. Dirtying and shader inputs require new counters. Panel
  states require an application-level test because the current harness has no
  panel. The 0.4/0.5 input gate needs complete fixtures, including a full
  bridge-written multi-position run, channels, z and time, rather than the
  external harness's current first-store opening.

Without those additions, a fast first blank frame, a globally missed cache, an
oversized predeclared memory budget or correct panel text with wrong shader state
could all pass.

### 8. What is still wrong?

The false current fact is the claim that a repeated same-type bridge scan is
refused; it can overwrite same-named stores. The share scan taking more than
thirty seconds and raw responses doubling bytes are unmeasured inferences stated
as facts. “Any number of channels” should mean no schema-imposed limit, not an
unbounded promise to draw all channels simultaneously within the latency and
memory gates. State a tested visible-channel fixture and the behavior beyond it.

For a biologist, `profile`, `generation`, `revision`, `shader`, `codec`,
least-recently-used caching and the “signed truth file” still need short plain
definitions. In particular, `signed.json` is a publication marker replaced in one
indivisible filesystem step, not a cryptographic signature. The corrected
prior-art note should remove
its retracted universal wording from the later body. The “Not taken” reasoning is
otherwise fair: it distinguishes the owner's refusal from findings accepted in
substance and does not pretend that phase 0 authorised the engine.

I checked every item in the record's “Exists” list. The results are:

| Existing item | Result and evidence |
|---|---|
| Profile, immutable layout, commit events and generations | Present. `zmart_viewer/record/model.py:696-980`, `:1045-1152`, `:1250-1395`, `:1400-1577`; replacement generations are used in `record/coordinator.py:1699-1760`. The one-profile limitation above is real. |
| Append-only history, publication marker and one-call fingerprint | Present. `zmart_viewer/record/manifest.py:1-58`, `:116-211`, `:395-455`, `:662-880`. “Signed” is the filename/role, not cryptography. |
| Synchronous coarse rebuild and opening from files alone | Present. `zmart_viewer/record/coarse.py:1-50`, `:234-286`; `record/coordinator.py:1783-1806`; `record/gateway.py:117-257`, `:479-516`. |
| Change stream, revisioned live state and file validators | Present. `zmart_viewer/live.py:1-9`, `:180-230`, `:622-685`; `record/live_state.py:127-364`; `server.py:522-603`. The validators identify files, not dirty revisions. |
| Segmentation rows in standalone configuration | Present at `zmart_viewer/server.py:1593-1616`; the record correctly calls the operator label layer new. |
| Bounding-box footprints and synthesised coverage | Present. `zmart_viewer/compose.py:65-90` and `building.py:1530-1556` provide conservative rectangles; `viz_studio/options/measure/data_server.py:363-400` synthesises full coverage and marks it as such. |
| Shared gestures, sliders, micrometre view and x/y pointer readout | Present. `viz_studio/options/gestures.js:58-311`; `application/parts/canvas/viewer-panel.js:327-446`, `:1410-1499`; `application/parts/canvas/viewer.js:439-617`, `:856-877`, `:1624-1669`. |
| Full-size sharding in the storage library | Present only for level 0 when requested, as the record says: `zmart_storage/canvas.py:2090-2140`. The bridge does not request it. |
| Neuroglancer texture per chunk and off-thread work | Present in 2.41.2: `src/sliceview/single_texture_chunk_format.ts:122-155`, `src/chunk_manager/README.md:1-59`, and `src/async_computation/request.ts:17-123`. Active async computations are not cancelled by that last file. |

## What I would cut

The first-engine scope is now appropriately small: keep the flat top slice,
channels, current controls, identities, masks, scheduler and measurement hooks.
I would not restore labels, projections, alignment, side views, navigation extras
or three-dimensional preparation to that milestone.

I would cut three premature commitments from the record itself: one universal
tile identity containing a global revision, exactly one worker, and a 32-bit sum
for every possible stack. I would also cut the unmeasured sentences that the
share scan exceeds thirty seconds and raw data doubles bytes, and the obsolete
universal atlas wording from the prior-art note. Keep coarse persistence only as
the conditional answer it now is, and let the data-layer measurement choose
whether tiny position levels are sharded or absent.

## Position on the contested decision

I accept the reasoning as an owner's product decision, but not as technical proof
that a new renderer is necessary: Neuroglancer can represent labels, transforms
and side views, while the register and sparse lookup are data-layer work, so those
features alone do not establish that replacement is cheaper. What the owner gives
up by deciding now is the option to avoid the lifetime cost of a second renderer
if the new data layer makes Neuroglancer satisfactory. That is a legitimate trade
if made knowingly. To keep phase 0 from becoming ceremony, the record must promise
that its fixtures and thresholds are fixed before measurement, its result chooses
the engine's scope and scheduler priorities, no threshold is relaxed afterwards,
Neuroglancer remains the operator engine if the replacement misses any gate, and
later milestones or a failed engine can still be stopped even though the intent
to build the first engine is settled.

## Paste-back before the data-layer design record

> Separate the planned layout from observations learned after capture. Publish
> actual per-plane x/y/z and vendor provenance with the pixel commit, and define
> terminal and skip records so they advance signed truth without becoming arrived
> pixels. Add a run-level catalogue for several collections. A manifest has one
> complete sealed profile, not merely one profile per frame shape, unless the
> model and every reader are explicitly extended for per-position profiles.
>
> Replace the run-wide revision in reusable tile keys with a per-tile content
> generation or define how untouched entries are promoted. Split source-chunk,
> assembled-slice and derived-projection identities. Add the slice coordinate,
> layout/presentation revision and projection-recipe version; keep window and
> colour as shader state, not pixel identity.
>
> In the coordinate record, settle half-open plane intervals, exact edge
> ownership, irregular heights, centre-to-edge conversion and calibration
> revision. Define physically weighted versus sample means, range inclusion,
> result types, missing planes and overflow before projections are built.
>
> Complete the scheduler with prefetch/recent promotion, reprioritisation,
> request coalescing, separate fetch/decode/transfer/upload capacities and a
> per-frame upload budget. Measure worker count; do not require exactly one.
>
> Add the instrumentation needed before phase 0, freeze fixtures, repetitions,
> budgets and margins, and revise the request, coverage, memory, dirtying and
> panel-state gates as described above. Correct the overwrite fact, label the
> share and compression statements as hypotheses, and print `uint16`, 100×100,
> no overlap, one depth and one time beside the ten-thousand-position numbers.
