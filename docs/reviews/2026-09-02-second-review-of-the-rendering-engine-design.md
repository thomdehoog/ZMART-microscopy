# Second review of the rendering-engine design record

Date: 2026-09-02

Reviewed: `docs/design/own-rendering-engine-and-position-register.md` on
ZMART-microscopy branch `claude/viewer-delivery-to-100` at commit `51085440`.
The record itself was last changed at `3bbf9c0b`, which is the commit the brief
names; the one commit after it adds only the brief. The ZMART Viewer was read on
its own `claude/viewer-delivery-to-100` at `9b67bf8`. Neuroglancer was read as
the pinned 2.41.2 under `viz_studio/frontend/node_modules/neuroglancer/lib`,
which is the compiled form of the source and carries this project's own patches
to the chunk manager. Nothing on either branch was modified except to add this
file. Every "exists" or "does not exist" sentence below was checked by opening
the file and is given with a line number; where I could only reason rather than
look, the sentence says so.

This is the second round. The internal first review
(`docs/reviews/2026-09-02-review-of-the-rendering-engine-design.md`, verdict
"accept with changes") is treated below as my own; Codex's
(`docs/reviews/2026-09-02-review-of-the-rendering-engine-design-by-codex.md`,
verdict "rethink") as the other reviewer's. Both were checked, finding by
finding, against what the revised record now says.

A few words used below, said once. A *tile* is one small square of one
zoom level of the picture, fetched, cached and drawn as a unit. A *chunk* is
the same idea on the storage side: one small block of an image file. A
*register* is the written plan of an acquisition: which positions are
planned, where each sits, and which have arrived. *Invalidation* is the act of
telling a viewer that some tiles it holds are out of date. A *gate* is a
measurable condition a piece of work must pass before the next piece begins.

## Verdict

**Accept with changes.** The revised record is right in its shape, complete
in most of what the two reviews asked for, and honest about the one decision
it refused. The decisions section is fair: on every finding I re-checked, what
it says was taken is in the body, with four exceptions named below, and what
it says was not taken is argued rather than waved away. The changes are
specific and none of them reopens the design:

1. Phase 0 as the record describes it cannot be run with the harness as it
   stands, and the record's own sentence "nothing in this record is
   authorised to be built before its numbers exist" forbids the work that
   would make it runnable. That is the finding that decides whether phase 0
   has teeth, and it is the first thing to fix.
2. The invalidation rule, "drop only the tiles that intersect", re-creates
   the blank screen this project measured, patched into its pinned
   neuroglancer and documented at length. The rule should be "replace, never
   drop", and the record already owns the evidence.
3. The prior-art note's correction is a preface above a body that still says
   the opposite. The decisions section lists the two universal claims as
   removed; they are not.
4. The register extension puts the raw recorded height into a layout whose
   placement field holds whole numbers of pixels, and "one profile per frame
   shape" turns out to mean one governed run per frame shape, which the
   record does not say and the order of work does not provide for.

The contested decision is discussed in its own section at the end. In short:
the reasoning is sound as written, the order it takes from the objection is
the part that matters, and the record still has to promise three things for
phase 0 to mean something.

## What I read and how

- The record, in the order the brief asks: the contested-decision section,
  the decisions section, then the rest.
- Both first reviews, side by side with the record, checking each finding
  and each paste-back item for whether it landed whole, landed weaker, or
  did not land.
- The corrected prior-art note, phases 0 and 1 of the lazy-pyramid design,
  and "What 100% does not do" in the 100% plan.
- The Viewer's `record` package (`model.py`, `coordinator.py`,
  `manifest.py`, `gateway.py`, `identity.py`, `coarse.py`, `live_state.py`),
  its composer and its building module; the bridge's position writer,
  viewer service and scan loop; the storage library's chunking; the harness's
  driver, suite, real-run door and results; the `neuroglancer-under` adapter
  and the operator page's engine list; the patch script that this repository
  applies to neuroglancer on every install.
- Neuroglancer 2.41.2's `chunk_manager/base.js`, `backend.js` and
  `frontend.js`, `async_computation/request.js` and `handler.js`,
  `sliceview/backend.js` and `base.js`, `visibility_priority/backend.js`,
  and `sliceview/single_texture_chunk_format.js`.
- I ran nothing. Every number is arithmetic from constants in the code, with
  the case stated.

## Findings, ordered by consequence

### 1. Phase 0 cannot be run as written, and the record forbids building what it needs

**Facts.** The record says phase 0 is "the earlier design's ten-step trace
over the existing Viewer and engine, with time broken down into server work,
transfer, decoding, hand-off, upload and drawing, on a real run, cold and
warm, local disk and share" (record, lines 516-520), and that "nothing in this
record is authorised to be built before its numbers exist" (551-552). The
engine section says the new engine will carry "the breakdown instrumentation
phase 0 uses" (412-415), which presumes that instrumentation exists.

The harness today: the real-run door opens one store once and records
seconds to a settled picture, requests and bytes
(`viz_studio/options/measure/real_run.py:1-22`, `:92-112`); "settled" means
the screenshot stopped changing (`viz_studio/options/measure/drive.py:213-226`).
The 100% plan says in as many words that this door "is one opening of one
store, not the plan's ten-step trace, memory proxy, or 'reproduce one known
Viewer measurement within a tolerance' gate", and that the `neuroglancer-under`
adapter draws an empty photograph for a bridge-written five-axis 0.5 store,
recorded as an expected failure
(`docs/design/viewer-delivery-implementation-plan-100-percent.md:134-144`).
Nothing under `viz_studio/options/measure` or `harness/src` times decoding,
upload or drawing (I searched for those words; the suite's functions are the
picture-shape checks, landing latency and request counts, `suite.py:59-1065`).

What neuroglancer itself can tell a measurer: per-source statistics by chunk
state and priority tier with system and graphics bytes, plus total download
time and count (`chunk_manager/base.js:40-59`; `backend.js:323-330`,
`:346-348`; `frontend.js:276-289`), where "download" runs from request to
decoded because the zarr datasource decodes inside its download
(`datasource/zarr/async_computation.js:3`). Uploads to the graphics card are
applied on the drawing thread in slices of thirty milliseconds with a
thirty-millisecond pause between slices (`frontend.js:120-172`) and are not
timed. So server work and transfer can be separated on the Viewer's side
(the composer keeps `build_ms` and `encode_ms`, `zmart_viewer/compose.py:1091`,
`:1412-1416`), download-plus-decode can be read off neuroglancer, and the
hand-off, upload and draw parts of the breakdown have no instrument at all.

**Inference.** As written, phase 0 is a promise without an instrument. The
record must say, in the order of work, that three pieces of harness work are
authorised before phase 0 and are not "the engine": the ten-step trace in the
rig's external-run door, the adapter fix so that a bridge-written five-axis
store is drawn rather than placed beside the view, and the breakdown
instrumentation on both engines. Without that sentence, a literal reader of
"nothing is built before its numbers exist" cannot produce the numbers, and a
generous reader will build whatever they like under the word
"instrumentation". The record should also say which parts of the breakdown
cannot be measured on neuroglancer (hand-off, upload, draw) and will be
estimated by subtraction, so nobody later claims a precision the numbers do
not have.

### 2. "Drops only the tiles that intersect" re-creates the blank this project measured and patched

**Facts.** The record's invalidation rule: the Viewer publishes dirty boxes
per revision and "the engine drops only the tiles that intersect them"
(400-403). The `neuroglancer-under` adapter records what dropping looks like:
the share of the window holding picture went 0.2726 to 0.0000 to 0.1839
across one refresh, "a flash of empty screen every few seconds, at exactly
the moment the operator is watching most closely"
(`viz_studio/options/neuroglancer-under/viewer.js:2012-2018`). This
repository maintains one patch against its pinned neuroglancer for exactly
this, applied on every install (`viz_studio/frontend/package.json:9`;
`viz_studio/frontend/scripts/patch_neuroglancer.mjs:1-36`): the worker side
re-queues only the named chunks and tells the page nothing, so the stale
pixels keep drawing while the fresh bytes download; the page side swaps old
for new in one JavaScript turn so no frame shows a gap
(`node_modules/neuroglancer/lib/chunk_manager/backend.js:1183-1212`,
`frontend.js:226-236`). A second patched call, `refreshChunks`, goes further:
it downloads the replacements for one commit's footprint beside the state
machine, stages them, and delivers them back-to-back so the change appears in
one frame, with a two-second flush if a download stalls
(`backend.js:1113-1182`). The operator page's engine module calls it
(`viz_studio/frontend/src/engine.js:585-632`).

**Inference.** The engine specification must not say "drop". It must say:
a tile inside a dirty box is marked stale and keeps drawing until its
replacement arrives; the replacements of one landing land together, in one
frame; a stale tile is never handed to a measurement or a readout as
current; and a stale tile whose replacement never comes (the ground was
replaced and the old footprint is now empty) is dropped only when the new
revision's coverage says so. That is what the project already built into
somebody else's engine, and it is the one place where the record is weaker
than the code it means to replace. It also bears on the contested decision:
"all-or-nothing invalidation cost this project weeks" is true, and the cost
has been paid, in the form of a fork the project now carries inside
`node_modules`. See the last section.

### 3. The prior-art note's correction is a preface; the body still says what was withdrawn

**Facts.** The decisions section lists, as taken from Codex, "the removal of
'every renderer' and 'all moved to WebGPU'" (record, 469-470). The note now
opens with a correction that says these claims "are not supported"
(`docs/design/prior-art-larger-than-memory-3d-rendering.md:9-23`). The body
below it is unchanged: the next heading is still "The one idea every one of
them shares", its first sentence still "Every serious system below does the
same four things" (25-27), and the closing section still says "Bricks, a
fixed atlas, indirection and coarse-for-fine substitution are the design.
Our two-dimensional tiles are bricks with a depth of one, and the tile cache
should be written so that a brick with depth is the same object with one
more coordinate" and "WebGPU is where the browser-native work has gone ...
the three-dimensional phase should assume WebGPU" (120-131). The revision
commit touched sixteen lines of this file, all of them the preface
(`git diff ac72b520 3bbf9c0b`).

**Inference.** This is the "taken in the decisions section but only
half-present in the body" case the brief asks me to catch. A reader who
starts at the heading, as readers do, meets the withdrawn claim as the
note's thesis. Rewrite the two sections so they say what the preface says,
or strike them and leave the survey entries and the correction.

### 4. The layout's placement holds whole pixels; the raw height in micrometres cannot live there

**Facts.** The record says the bridge must write "a layout revision listing
every planned position with its stage corner including the raw recorded
height" (249-252), and separately that the extension carries "planned and
observed placement kept apart, with the coordinate frame and calibration
they belong to" (257-258). In the Viewer, a placement's `origin` is passed
through `_frozen_axis_map`, which turns every value into an `int`
(`zmart_viewer/record/model.py:288-295`, `:1079`, `:1087`); the publisher
takes positions as `dict[str, dict[str, int]]`
(`zmart_viewer/record/coordinator.py:196`); and the building module turns
the origin into micrometres by multiplying the whole number by the profile's
one voxel size per axis (`zmart_viewer/building.py:1513-1527`). So a height
of 1234.7 µm, or a stack whose planes were recorded at irregular heights,
has no representation in the layout: the layout can say "plane index 3 of a
profile whose z step is 5 µm", nothing else. The writer today records one
median step and nought for every corner
(`application/parts/storage/zarr_positions.py:313-319`, `:322-362`).

**Inference.** Line 250-252 and line 257-258 describe two different
documents and the record should say so plainly: the layout revision keeps
its whole-pixel origin, which is the placement the stores and the composer
use (today, nought in z); the observed stage placement in micrometres, per
position and per plane, is a new document in the extension; and the rule
that derives the first from the second (round to the profile's voxel; z to
nought under aligned placement, to a plane index under absolute) is written
down once. There is a second, smaller ambiguity in the same bullet: the
record keeps the raw plane heights in the register and lets the store keep
its median step (88-92), so a stack has two answers to "where is plane
four", and an implementer of absolute placement would have to decide which
one draws. The record should decide: the store's regular step draws, the
raw heights are provenance and the input to a later calibration, and a
stack whose recorded steps differ from the median by more than a stated
tolerance is flagged at conversion.

### 5. "One profile per frame shape" is one governed run per frame shape

**Facts.** The record says a collection whose fields differ in size "is
several profiles, one per size, which is what the Viewer's record package
already asks for" (163-165). In the Viewer, a layout revision names exactly
one `profile_id` (`model.py:1274`), a publisher is constructed with one
profile (`coordinator.py:190`), a run folder's manifest names one `run_id`
and refuses another (`manifest.py:360-385`), and the gateway loads one
layout and one profile per run folder (`gateway.py:218-232`). The profile's
own docstring says a change of frame size "starts a new acquisition
instance with its own profile" (`model.py:706-712`).

**Inference.** A target collection with two field sizes is therefore two
run folders, two manifests, two layouts and two composed sources, and the
Viewer's "collection" in that case is an index over them. The record's
extension has a stable collection identity but no index that says "these
three governed runs are one collection" and no line in the order of work
for it; Codex asked for "one overarching index when a workflow contains
several collections" (Codex, 281) and the request was not carried. The
panel heading, eye and opacity "for the whole" (159-160) need that index.
This is small to write and expensive to add later, because it is the thing
every cache key and every panel row hangs off.

### 6. A new event kind breaks older readers fail-closed, and the terminal flag already exists

**Facts.** The extension asks for "a way to say a planned position was
skipped or will never arrive; the event kinds today are committed,
timepoint committed and replaced", and "a schema version" (262-264). In the
Viewer, `EVENT_TYPES` is the closed list (`model.py:597`), a commit with any
other kind raises at construction (`model.py:1452-1456`), and a truth file
of any other schema is refused as "damaged or belongs to another schema"
(`manifest.py:176-178`, `:425-431`). `SceneLayoutRevision` has a `final`
flag (`model.py:1281`) that nothing in the package sets (I searched for
`final=True` and `final =` under `zmart_viewer/record`).

**Inference.** The record must choose the mechanism, because the two
choices have different consequences for a Viewer on another computer. A new
event kind under a bumped schema makes every older Viewer refuse the whole
run, which is the design's safe direction but is also a run nobody can look
at until the Viewer is updated. Additive fields under the same schema (a
`final` layout revision listing the positions that will never come, a
terminal state in the truth file that older readers ignore) keep older
Viewers reading, at the cost of them showing a stopped run as a slow one.
Either is defensible; the record should say which and what the older Viewer
sees.

### 7. The window authority's new key is in the identity, not in the order of work

**Facts.** My first review's finding 3 said the display-window authority is
keyed per channel only, that switching a channel to a projection would send
the slice's window to the engine, and that the fix is a contract change in
the panel and the Viewer's measure route, belonging in the data-layer record
(first review, 150-178). The record takes the (channel, kind) key into the
end-to-end identity and says a projection has its own measured window
(166-180), and gives labels a kind that is "never measured, never windowed"
(142-144). The panel still measures every row that lacks a declared window
(`application/parts/canvas/viewer-panel.js:1384-1395`), `setChannel` carries
`visible, colour, window, lut` and no kind (`viz_studio/options/contract.md:56`),
and the order of work's data-layer step lists the register, frame, coverage,
dirty boxes, cost model, sharding, tiny levels, terminal state and re-scan
rule, not the authority's key (553-557).

**Inference.** Taken in the identity, missing from the plan. The contract
change (`setChannel` gains a kind; `measureEveryRow` skips label rows; the
Viewer's measure route is keyed by kind) should be named in step 2 or step
4 so it is not discovered when the first projection is drawn.

### 8. Codex's "first engine is an absolute top slice" was refused without being named

**Facts.** Codex's paste-back asks that "the first authorized engine [be]
only an absolute top slice" (Codex, 225, 309). The record's first engine
draws "the flat top view over the positions as the stores place them
today" (560-562), which is aligned placement at the low edge (98-100), and
argues at length why absolute placement shows two fields out of fifty for a
flat plate (108-111). The "Not taken" list does not mention it (472-489).

**Inference.** The reasoning in the body is right, and it is my own
finding 2 that supplied it, but a decisions section that promises to say
"what was not taken, with reasons" should list this one. Codex reading the
record would find their first-milestone recommendation contradicted in
silence, which is the thing the record says it will not do.

### 9. The memory gate is weaker than the earlier design's and lets a leak hide

**Facts.** The engine gate reads "memory stays within the budget the cache
was given" (540). The record itself says WebGL2 cannot report how much
graphics memory there is and the budget "is a number somebody sets"
(396-397). The earlier design's gate is at the process: "over 20 repetitions
of the navigation trace, the combined renderer/GPU process memory is at most
1 GiB and the final ten cycles grow by less than 10% or 20 MiB, whichever is
larger" (`docs/design/lazy-jpeg-pyramids-for-the-viewer.md:460-462`).
Neuroglancer's own accounting is likewise a count of what it believes it
holds (`backend.js:488-515`, `:632-666`), not what the driver holds.

**Inference.** A cache that honours its own budget while textures leak, or
while the browser keeps decoded images the cache has forgotten, passes the
record's gate and fails the operator. Keep both: the cache's accounting as a
unit test, and the earlier design's process-level gate as the one that
counts.

### 10. "Requests fewer" depends on which plate, and the record does not say which

**Facts.** The engine gate reads "requests for the same navigation are
fewer, and bytes no more" (539). The `neuroglancer-under` adapter already
binds the view to the coverage record's bounds (`viewer.js:228`, `:2654-2658`), and
the harness measures requests bounded and unbounded on its sparse canvas
(`suite.py:1007-1040`). Coverage in the new engine decides which tiles
exist at each level (409-411).

**Inference.** On a dense plate, neuroglancer bound to coverage and the new
engine ask for the same tiles; "fewer" cannot be won there and a failure to
win it means nothing. On a sparse plate, per-tile coverage removes requests
inside the bounding box that neuroglancer still makes. The gate should name
both fixtures and say "fewer on the sparse plate, no more on the dense one".

### 11. The data-layer bullet blends two plate cases in one sentence

**Facts.** "One 512-piece at the coarsest level touches four thousand
positions, and warming the kept levels of three channels is on the order of
170,000 chunk reads" (329-331) comes from my first review's 1024-voxel
case (first review, 276-282). The same bullet continues "for a three-channel
plate of 2048-voxel fields the current one-per-cent rule keeps about 2,600
channel pieces, about 1.3 GiB" (336-339), which is Codex's 2048-voxel case
(Codex, 138-149). For 2048-voxel fields the kept levels are 4 through 8 and
a 512-piece covers 16, 64, 256, 1024 and 4096 positions there; with 625,
169, 49, 16 and 4 pieces per level, warming one channel-plane is about
66,000 reads and three channels about 200,000. The order of magnitude
holds; the case does not.

Also, "five of the levels per position are tiny files" (298-299) counts the
128-voxel level, which is one file of 32 KiB for `uint16`. "Single-file
levels" is the honest phrase; "tiny" invites a reader to think they cost
nothing to drop, and the cost of dropping them is finding 15's question.

**Inference.** Say the case once per bullet. Nothing else changes.

### 12. The scheduler list is right in outline and still short of what neuroglancer does

This is question 5; the details are there. Summarised: the record names a
priority order, an in-flight cap, abort, retry, fairness, stale-drop by
revision, hand-off, over-budget pinning and context loss (366-381).
Neuroglancer additionally has a three-tier admission rule that never evicts
a chunk to admit a lower-priority one, a prefetch driven by the estimated
velocity of the view, item counts beside byte counts on every budget, a
"how far" request (worker memory, main memory, graphics memory), a
time-sliced upload budget on the drawing thread, a way for the page to ask
for a chunk's bytes back, an ordering guarantee between deliveries, and
per-layer "needed versus available" counters that are what "settled" means.
None of these is large; every one of them decides the feel, and two of them
(the counters and the "how far" request) decide whether the harness can
measure the new engine the way it measures the old.

### 13. Geometry an implementer would still decide

The frame, the datum, the raw heights, aligned placement's one meaning, the
edge-based names and the side view's slider and axis are all now defined
(82-121). Four things are not:

- **How thick a single-plane position is under aligned placement.** The
  writer gives a flat capture a z step of 1 µm
  (`zarr_positions.py:313-319`), so under "each stack showing the plane whose
  voxel interval contains that offset" (103-104) a plate overview is visible
  only for offsets inside its first micrometre and vanishes when the
  operator steps into any stack. Today's adapter behaves that way: "browsing
  them walks above the flat captures" (`viewer.js:1103-1105`). The record
  should say whether a one-plane position is one voxel thick or is drawn at
  every offset, because the first is honest and the second is what an
  operator looking at an overview under a stack wants.
- **Whether a position may be turned.** The composer's footprint of "a
  turned position" is mentioned (406-408) and `compose.Tile.footprint`
  returns a rotated tile's bounding box (`compose.py:65-90`), but the
  placement bullet says every tile is "a textured rectangle at its true
  micrometre position" (389-390). Either the first engine draws rotation or
  it refuses a turned layout; say which.
- **What "time" means across collections.** The identity carries a time
  index; a profile declares room along time (`model.py:746`); two
  collections with different moment counts share one slider. Index or
  wall-clock, and whose index, is not said.
- **Which height draws a stack's planes** (finding 4, second half).

### 14. The identity: one field that does not belong, two that are missing

The identity (173-179): collection, source and its generation, time, stable
channel key, level, orientation, slice or projection with kind and range,
row, column, revision; beside the pixels, data kind and type, window with
state, coverage mask.

- **Generation does not belong on a composed tile.** A generation is per
  position (`model.py:1429`; `coordinator.py:1698-1766`). A kept coarse tile
  is composed from thousands of positions with their own generations, so
  "source and its generation" is not one number there; the revision is what
  identifies it, and generation belongs only on a tile that is one
  position's own chunk. Say so, or an implementer will invent a rule.
- **Placement is missing.** The record says the kept coarse levels serve
  one placement (341-342) and that a custom offset cannot be precomputed
  (106-107). A tile at (level, row, column, slice) under aligned placement
  and the same address under absolute placement hold different pixels.
  Placement, or the derived-product identity that stands for it, must be in
  the key of every composed tile, or absolute placement later poisons the
  cache of aligned.
- **The slice's unit is missing.** "Slice with kind and range" needs to
  say whether the range is a plane index of the composed picture or an
  offset in micrometres from the aligned edge, because the two disagree
  the moment stacks have different steps.

Nothing else on the list is extra. Orientation is constant in the first
engine and costs nothing to carry.

### 15. Sharding must cover every level with more than one chunk; the levels below 128 voxels can go, on one condition

**Facts.** The bridge's writer keeps copies down to 8 voxels because the
composed picture "has exactly as many zoomed-out copies as a single position
does" (`zarr_positions.py:56-85`); the composer refuses a transfer whose
stores disagree about level count and offers "the copies every tile has"
(`compose.py:512-520`). The pointer-linked view, which is the other consumer
of a position's copies, needs them only down to the piece size, 128
(`zmart_storage/positions.py:131-166`). The storage library bundles only the
full-size level (`zmart_storage/canvas.py:1277-1284`, `:2126-2131`); the
bridge passes no shard at all (`zarr_positions.py:163-177`).

**Inference.** For 2048-voxel fields the levels with more than one chunk
are 0 through 3 (256 + 64 + 16 + 4 chunks per channel-plane); levels 4
through 8 are one file each. If the data layer keeps its own coarse levels,
the composer's "same level count" rule can be relaxed for bridge-written
runs, and the positions can stop at 128 voxels: the plate's file count for
three flat channels falls from about 10.5 million to about 2.6 million on
the sub-128 levels alone. Sharding levels 0 through 3 as one shard per
level per channel-plane then leaves about 15 chunk files and a handful of
description files per position, about 200,000 for the plate. So: shard every
level that has more than one chunk, drop the levels below the piece size,
and the decision depends on exactly one thing, whether the kept coarse
pyramid is built (328-336). If phase 0 says it is not, the positions must
keep their tiny levels and those levels need bundling or a folder-per-level
answer of their own.

### 16. Smaller corrections

- "The Viewer measured [that a partial write] rewrites about half the
  shard" (313-315): the note says a factor of (N+1)/2 of the shard per
  patch (`docs/measured/NOTE_the_shard_is_written_once.md:40-48`). "About
  half, growing with the shard" is the honest phrase.
- "A re-scan is refused because the store exists" (245-246): true of the
  bridge's route; Codex noted that the storage library opens a fresh store
  in write mode (Codex, 43). The refusal is the bridge's, not the library's,
  and the data-layer record should keep it that way on purpose.
- Terms still arriving unglossed for a biologist: *provenance* (97, 258),
  *handedness* (93), *back-off* (376), *percentile* (354, 527, 531, 538),
  *codec* (290, 352), *residency* (223, 345), *inode* (276), *schema* (264),
  *generation* (238, 363), *footprint* (402, 497, 527, 541), *append-only*
  (239), *texture array* and *internal format* (392-394). Each needs half a
  sentence where it first appears. The opening gloss is good and should
  simply be longer.

## Answers to the eight questions

### 1. Were the findings carried faithfully?

**My own eight findings and paste-back.** Height is not on disk, the writer
zeroes it, the register carries it per plane: carried (83-92), with the
schema problem of finding 4 above. Table alignment renamed as default,
absolute demoted with a projection or slab default: carried (98-111). Kept
coarse levels in one placement, named: carried (341-342). The Viewer's
record is the register plus four additions: carried, and extended by
Codex's list (226-266); "one profile per frame shape" is carried but not
what it entails (finding 5). Sharding split in two: carried (309-316).
Plate arithmetic and the folder scan first: carried (293-304), with the
blended case of finding 11. Fan-in as the union with the share rule,
computed from the plan, synchronous patching off the stage's path: carried
whole (342-346, 347-358). Worker from the start, per-format pools and a
JavaScript lookup, priority and concurrency, request gate: carried (382-399,
409-411); the choice between a texture per tile and slots in an array is
left to measurement rather than settled, which is reasonable. The (channel,
kind) key and the label row kind: carried into the identity, not into the
plan (finding 7). The side view changes two contracts, dirty regions as
boxes: carried (112-121, 400-403). What leaves the first engine: carried
(122-144, 549-569). Gating the engine on the data layer under
`neuroglancer-under`: not taken, argued. Glossing: partly (finding 16).

**Codex's eight findings and paste-back.** (1) Conditional engine: order
taken, condition refused, argued in the open (31-59, 474-478); the
attribution argument ("a comparison after all four have been built cannot
say which one cured the measured problem", Codex 25) is answered by the
order, which measures the data layer under the old engine before the new
one exists. (2) Extend the Viewer's record: carried whole, including the
layout wording fix, the legacy path, terminal state, planned versus
observed, provenance, display-contract reference and schema version
(255-278); the cross-collection index is not carried (finding 5). (3) The
z frame and aligned meaning: carried (92-111), with the "per-plane
coordinate vector versus median" point left half-resolved (finding 4). The
side view's slider and axis: carried (112-121). (4) End-to-end identity,
format pools, coverage mask, overlap order, no window fallback: carried
(145-180, 391-399), with finding 14's gaps; the register's map from stable
channel key to array index, colour and valid range is implied by "a
reference to the one acquisition display contract" (259) rather than
stated. (5) Scheduler: carried as a list (366-381) that question 5 completes;
"costs nothing" struck; the claim made a gated hypothesis (58-59). (6) Cost
model in chunks and bytes, no single K, guard, lag only behind an explicit
derived revision, persistence separate from residency: carried whole
(342-358). (7) Two plate cases with the tuple, sharding every file-dominant
level as prerequisite: carried (286-316). (8) Atlas and "same cache for 3D"
withdrawn: carried in the record (206-224); in the prior-art note only as a
preface (finding 3). Paste-back's "first engine is an absolute top slice":
refused without being named (finding 8). Paste-back's "persistent coarse
products unless measured necessary": carried as "kept ... if the
measurement says so" (328-336) and named in "Not taken" as a refusal of
wording only (479-481), which is fair.

Nothing was carried that neither review asked for, with one welcome
exception: the record's own observation that a collection's identity must
be distinct from its display name so two scans are never merged (161-163)
came from Codex's finding 4 and was generalised sensibly.

### 2. Is the geometry defined tightly enough?

Nearly. The frame, datum, raw heights, aligned placement's single meaning,
the edge-based names and the side view's slider and projection axis are
defined, and defined before use. An implementer would still decide the
four things in finding 13 and the two-truths question in finding 4. Of
these, the thickness of a single-plane position under aligned placement is
the one that changes what an operator sees on the first day, and it should
be settled in the record, not in code.

### 3. Is the register extension complete and consistent with the Viewer's record?

Consistent with the sealed profile (nothing proposed changes a profile after
sealing), with the immutable layout (revisions are still numbered and never
edited; the wording fix at 264-266 is a docstring change), and with the
signed truth file (nothing proposed writes to it without a rename). Two
things conflict as written: the raw micrometre height cannot go into the
layout's whole-pixel origin (finding 4), and a new event kind is not
"append-only" from an older reader's point of view (finding 6). "One profile
per frame shape" is enough for the Viewer's record and not enough for the
record's own notion of a collection, because it means one governed run per
shape and the extension has no index over runs (finding 5). Add the index,
say which document holds observed placement, and say what an older Viewer
does with a newer run.

### 4. Is the end-to-end identity right and minimal?

Right in what it separates (what a tile is, in the key; what a tile means,
beside the pixels), and minimal except for generation on composed tiles.
Missing, and expensive to add later: placement, and the unit of the slice
range (finding 14). If placement is not in the key before absolute
placement is built, every kept tile and every cached tile of aligned
placement must be thrown away when absolute arrives. Everything else that
Codex listed (data kind and type, window with state, coverage) is present
and in the right place.

### 5. Does the scheduler specification cover what neuroglancer does?

I opened the pinned sources. What the record's list (366-381) has that the
code has: a priority order, a cap on requests in flight (`backend.js:591-595`,
one download capacity per source level), abort of a download
(`backend.js:361-365`), explicit states (`base.js:17-27`), a failed state
with the error kept (`backend.js:142-145`), eviction by system and graphics
memory (`backend.js:557-569`, `:726-758`), and work off the drawing thread
(`request.js:17-88`). What the code has that the record's list still lacks:

- **Three tiers, and admission by tier then priority, not least-recent
  use.** Chunks are visible, prefetch or recent (`base.js:29-38`); the first
  two are ordered heaps, the third an LRU list (`backend.js:366-449`). A
  chunk is never evicted to admit one of lower tier, or of the same tier
  and no higher priority (`tryToFreeCapacity`, `backend.js:474-487`). The
  record's cache is "least recently used, the current plane pinned"
  (391-392); plain LRU would evict a visible tile to admit a prefetch. Say
  the admission rule.
- **The priority is a composite.** Within the visible tier: a base from
  the panel's visibility, plus 10⁹ times the source's index in the list of
  visible scales, minus the distance from the view centre
  (`sliceview/backend.js:62-63`, `:116-117`, `:139-157`;
  `visibility_priority/backend.js:37-42`). The record's "visible first,
  nearest the centre first, coarser first" (374-375) is the same order in
  words; the record should write the arithmetic and the tie-break, because
  "coarser first" and "nearest first" conflict at the edge of the screen.
- **Prefetch is predicted from the view's velocity**, not only "neighbouring
  planes while scrubbing" (78): a velocity estimator on the position feeds
  prefetch offsets and their priorities (`sliceview/backend.js:84-90`,
  `:128-130`, `:166-197`), scaled by `PREFETCH_PRIORITY_MULTIPLIER`
  (`base.js:60`), switchable (`frontend.js:126`). The record needs a
  prefetch rule with a budget, in the pan direction as well as along the
  sliders.
- **Every budget has an item count beside its byte count**
  (`frontend.js:74-90`; `backend.js:488-515`), and there are four budgets:
  graphics, system, download per source level, and compute
  (`frontend.js:107-115`; `backend.js:588-595`). The record has "two tiers
  with byte budgets" (391). A count matters when tiles are small and many.
- **A "how far" on every request.** A chunk can be asked to stop in worker
  memory, main memory or graphics memory (`backend.js:95-101`, `:147-153`,
  `:1013-1020`). The panel's window measurement and the pointer readout
  (432-434) want pixels in main memory without an upload; the record's
  scheduler has no such request.
- **Download slots per chunk** (`backend.js:93`, `:197-208`): a request may
  cost more than one slot. For us the cost is on the server, where one
  512-tile may be sixteen reads (320-326); "a fixed number of requests in
  flight" (376) should say whether the number counts requests or the reads
  behind them, and the cost model should feed it.
- **Abort on pressure, not on supersede.** A chunk that is no longer wanted
  drops to the recent tier; if still queued it is removed
  (`backend.js:675-680`, `:1031-1033`); if downloading it runs to completion
  unless a higher-priority chunk needs its slot, in which case it is
  cancelled (`backend.js:810-824`, `:837-846`). The record says "abort of a
  superseded request" (376). Either rule is defensible; they differ in
  wasted bytes and in the number of requests the harness counts, and the
  303-versus-1266 measurement (`RESULTS.md:66-79`) came from neuroglancer's.
- **Priorities are recomputed in one batch per change**, on a zero-delay
  timer, with a mark generation so a chunk wanted by two layers gets the
  highest priority and the lowest "how far" (`backend.js:977-1064`,
  `:1013-1029`); graphics-memory changes re-trigger it throttled at 200 ms
  (`backend.js:960-969`). That is neuroglancer's whole answer to "fairness
  between channels and collections" (378): none, the maximum wins, and
  channels are separate layers with equal base priority. The record should
  say whether it wants the same.
- **The upload budget is a time slice on the drawing thread**: pending
  deliveries are applied for at most thirty milliseconds, then the rest
  waits thirty milliseconds (`frontend.js:120-172`). The record's
  "hand-off from worker to drawing thread" (379) needs a number like that,
  in milliseconds or bytes per frame.
- **The page can ask for a chunk's bytes back** (`frontend.js:321-326`;
  `backend.js:778-783`), and deliveries carry ownership of their buffers
  (`backend.js:784-808`). The readout of "the pixel value under the pointer"
  (433-434) needs the first; the record has neither.
- **Ordering.** A source can ask for its deliveries to be applied
  immediately rather than queued, to keep order with other messages
  (`frontend.js:385-390`). "Stale results dropped by revision" (378-379)
  needs a sentence about the order between a revision bump and deliveries
  already in flight.
- **Three kinds of "nothing" and one of "failed".** Neuroglancer keeps a
  failed chunk failed until invalidated; there is no retry
  (`backend.js:142-145`, `:338-360`). The adapter learned that an empty
  piece is remembered forever (`viewer.js:2612-2616`), and the Viewer
  answers an empty piece with an empty not-found body
  (`compose.py:1399-1410`). The record promises "retry with back-off and a
  failed state" (377) but does not separate never-asked (coverage), asked
  and empty (remembered until the revision changes), and failed (retried).
  It should, or a 404 will be retried with back-off forever.
- **Counters that define "settled".** Each layer counts visible chunks
  needed and available, and prefetch likewise, sent every 200 ms
  (`backend.js:920-955`; `sliceview/backend.js:157-161`, `:192-196`). That
  is what neuroglancer's progress indicator reads. The harness's "settled"
  is a screenshot that stopped changing (`drive.py:213-226`); the new
  engine's measurement handle (412-415) should expose the same counters so
  both engines can be judged by the same definition.
- **Sources are memoised by a stable key** so two layers over one source
  share chunks (`frontend.js:363-373`); chunk objects are pooled and reused
  (`backend.js:237`, `:249-261`). Small; mention both as measurement-driven.
- **One backend worker plus a decode pool.** The chunk manager runs in one
  worker and hands decoding to up to min(12, cores) further workers,
  launched lazily, with a first-in-first-out queue and cancellation only
  for tasks not yet started (`request.js:17-31`, `:58-88`;
  `handler.js:18-39`). The record's "one worker that fetches and decodes"
  (382-385) is a choice, and a fine one to start with; the record should
  say what happens when decoding is slower than downloading (back-pressure
  on the in-flight cap) and that the decoder for zstd must live in that
  worker.
- **Invalidation as replace, not drop** (finding 2). The stock all-or-nothing
  RPC (`backend.js:894-908`) is what the record means to escape; the
  project's patched named-chunk refresh with one-frame delivery and a
  two-second flush (`backend.js:1113-1182`) is what it must at least equal.

Also for the record's own honesty: neuroglancer keeps one texture per chunk,
created on upload and deleted on eviction
(`sliceview/single_texture_chunk_format.js:78-91`), and draws every visible
scale of a layer in one pass with a depth test so the finer scale wins where
it exists (`sliceview/frontend.js:426-440`; scales chosen and reversed at
`sliceview/base.js:169-193`). That is how "a coarser level of the same
channel stands in while the finer loads" (386-388) is done there; the record
may do it in JavaScript by drawing coarse rectangles first, and should say
which.

### 6. Are the numbers stated so that "ten thousand" means one thing?

Yes, with finding 11's blended bullet. The two cases (293-299) match
Codex's table (`Codex, 127-132`) and the writer's constants: chunks of 128
(`zarr_positions.py:54`), copies down to 8 voxels (`:85`;
`zmart_storage/positions.py:131-166`), one plane per chunk
(`canvas.py:2136-2139`), pieces of 512 (`compose.py:659`), the one-per-cent
rule (`compose.py:680`, `:1143-1165`), no shard from the bridge
(`zarr_positions.py:163-177`), full-size level only in the library
(`canvas.py:2126-2131`). The tile-size statement (320-326) is right and is
the thing Codex asked to be said first. The kept-levels cost (336-339) is
Codex's arithmetic and is right for the 2048 case. Whether sharding must
cover every level, or some levels can go: finding 15, and it depends on
whether the kept coarse pyramid is built.

### 7. Are the gates measurable and in the right order?

Phase 0: not measurable with the harness as it stands (finding 1). The five
data-layer gates: "never lists the positions folder" and "a relink costs a
fingerprint check" are measurable by counting file operations on the
Viewer's side; "a coarse tile is one read" by the composer's own counters;
"a landing patches exactly the pieces its footprint dirties before the new
revision is published" by the Viewer's existing dirtying tests
(`building.py:1530-1556`) extended to bridge-written runs; "coverage removes
every request for a position that has not arrived" by the harness's request
ledger (`suite.py:1007-1040`); and the 500 ms landing gate by the harness's
landing clock (`suite.py:897-936`), whose note says it is an upper bound
because it includes photographing. One caution on the last: today's bridge
relinks at most every thirty seconds
(`application/parts/storage/viewer_service.py:60-92`), so the 500 ms gate is
unwinnable until the bridge writes the register and the Viewer serves the
run as governed; the gate is therefore in the right place, after step 2,
and the record should say that it cannot be attempted before.

The seven engine gates: the memory gate lets a leak hide (finding 9); the
request gate needs its plates named (finding 10); "opens our own data as it
is written today" (545-547) is a gate that `neuroglancer-under` fails on the
rig today (100% plan, 134-144), so the comparison for it has no baseline
until the adapter is fixed, which is finding 1 again. The rest are
measurable and in the right order, provided the phase-0 instrumentation
exists on both engines.

### 8. What is still wrong?

False as written: the prior-art note's body (finding 3); "a layout revision
listing every planned position with its stage corner including the raw
recorded height" as a description of the Viewer's layout (finding 4);
"about half the shard" as the measured factor (finding 16). Inference
stated as fact: "on a share that scan takes longer than the interval" (303)
is arithmetic from an assumed five to ten milliseconds per file open, not a
measurement, and should say so. What a biologist would not follow: the
unglossed terms in finding 16, and the scheduler paragraph (366-381), which
is a list of nouns a maintainer recognises and a reader at the microscope
does not; one sentence per item saying what the operator would notice
without it ("without a cap on requests in flight, a fast pan floods the
server and the picture arrives all at once, late") would fix it. In the
"Not taken" section, all four reasons hold; the section is incomplete rather
than wrong (finding 8).

## The contested decision, in one paragraph

The reasoning is sound as written, and I accept it, on three promises. It
is sound because the earlier "only if" clause was written to stop a speed
project, the compact-picture engine, and the reasons the owner gives here
are not about speed: transparency at any layer, positions placed in three
dimensions, labels drawn as labels, side views and projections later, and
ownership of the lookup and the invalidation. A measurement cannot decide
whether those are wanted, and the record is right to say so rather than
hide the decision behind a gate it would not obey. What the owner should
know they are forgoing, concretely, is this: several of those reasons are
things neuroglancer already does and the adapter has not exposed. It has
per-layer opacity, segmentation layers, orthogonal views and arbitrary
layer transforms (the adapter's own `everyHeightBeginsAtNought` places
layers in z through exactly that machinery, `viewer.js:1088-1147`), and the
one reason that was purely a cost, all-or-nothing invalidation, has already
been paid for by a patch this project applies on every install
(`package.json:9`, `patch_neuroglancer.mjs`). So the phase-0 breakdown could
have told the owner whether adapter work reaches those features cheaper
than an engine does, and deciding now forfeits that answer. That is a real
loss and it is the owner's to accept, and the maintained fork inside
`node_modules` is itself the strongest argument on the owner's side: a
dependency you must patch to make correct is a dependency you already half
own. For phase 0 to keep its teeth the record must promise, first, that the
harness work phase 0 needs is authorised by name (finding 1), because a
gate nobody can run is not a gate; second, that the operator page stays on
`neuroglancer-under` throughout and the engine is adopted only on the seven
gates over the same data layer, which the record says (71-73) and should
repeat as a stop condition in the order of work; and third, that the
phase-0 result is written down as one sentence naming the layer that fails,
if any, before step 2 begins, and that if the data layer under the old
engine passes every gate of the earlier design, the engine's first brief is
reduced to the features it exists for and must still beat the old engine on
the harness's numbers. With those three sentences the decision is a
preference for ownership, stated honestly, with a measurement that can
still shrink it; without them it is a preference for ownership with a
measurement that decorates it.

## Paste-back: changes the record should take before the data-layer record is written

> Authorise, by name and before phase 0, the three pieces of harness work
> phase 0 needs: the ten-step trace in the external-run door, the adapter
> fix so a bridge-written five-axis store is drawn, and the breakdown
> instrumentation on both engines; say which parts of the breakdown (hand-off,
> upload, draw) cannot be measured on neuroglancer and are found by
> subtraction. Add a stop condition to the order of work: the operator page
> stays on `neuroglancer-under` until the engine passes its seven gates over
> the same data layer, and if the data layer under the old engine passes the
> earlier design's gates, the engine's first brief shrinks to its features
> and keeps its gates. Change the invalidation rule from "drops only the
> tiles that intersect" to "marks them stale, keeps drawing them, and replaces
> one landing's tiles together in one frame", and cite the patch this
> repository already maintains. Rewrite the prior-art note's "one idea every
> one of them shares" and "what of it applies to us" sections so they say
> what the new preface says. Say that the layout's origin stays in whole
> pixels and that observed placement in micrometres is a new document in
> the extension, with the rule deriving one from the other; say that the
> store's regular step draws and the raw heights are provenance. Say that
> one profile per frame shape means one governed run per shape and add a
> cross-run collection index to the extension and to step 2. Choose between
> a new event kind under a bumped schema and additive fields under the same
> schema, and say what an older Viewer sees. Add the (channel, kind) key of
> the window authority, `setChannel`'s kind and the label row that is never
> measured to step 2 or step 4. Name Codex's "absolute top slice first" in
> "Not taken", with the flat-plate reason. Put placement and the slice's
> unit into the tile identity and take generation off composed tiles.
> Complete the scheduler list with admission by tier and priority, the
> composite priority and its tie-break, velocity-driven prefetch with a
> budget, item counts on every budget, a "how far" on every request, a
> time-sliced upload budget, a way to read a tile's bytes on the page, the
> three kinds of nothing and one of failed, and the needed-versus-available
> counters that define "settled". Keep the earlier design's process-level
> memory gate beside the cache's own. Name the sparse and dense plates for
> the request gate. Decide how thick a single-plane position is under
> aligned placement, whether the first engine draws a turned position, and
> what "time" means across collections. State one plate case per bullet in
> the data layer and say "single-file levels" rather than "tiny". Say that
> the sub-128 levels can be dropped only if the kept coarse pyramid is
> built, and that sharding covers every level with more than one chunk.
> Gloss provenance, handedness, back-off, percentile, codec, residency,
> inode, schema, generation, footprint, append-only, texture array and
> internal format where they first appear.
