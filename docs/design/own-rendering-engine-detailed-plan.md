# The rendering engine and the register: a detailed plan, for discussion

Date: 2026-09-02, second revision. Status: a proposal to discuss, not a
decision. Nothing here is implemented. It expands the six steps in the
"Order of work" of the design record
(`own-rendering-engine-and-position-register.md`, fourth revision) into work
items, each tied to the files that exist today and to gaps found by reading
them, with the decisions that belong to the owner collected first.

The first revision was reviewed twice, by Codex ("rework",
`docs/reviews/2026-09-02-review-of-the-rendering-engine-plan-by-codex.md`)
and internally ("usable with changes",
`docs/reviews/2026-09-02-review-of-the-rendering-engine-plan.md`, whose ninth
section compares the engine against every speed mechanism in the pinned
neuroglancer). A design note on the graphics card
(`docs/design/gpu-first-engine-note.md`) was written at the owner's request.
Every finding was checked against the code; the section "Decisions on the
two reviews and the note" says what was taken and what was not. The
owner also gave two directives after the first revision, and they now sit
above everything else in this plan.

Two repositories are involved and are read together throughout: the
microscope repository (`ZMART-microscopy`: the bridge, the operator page,
the measurement rig and the storage library) and the Viewer
(`zmart-viewer`: the record package, the composer and the server). Paths
say which one they belong to.

## Words used below

The design record's glossary applies. A few more. The *rig* is the
measurement harness under `viz_studio/options/`, a small web page driven by a
Python script in a real Chromium. A *route* is one address the Viewer's
server answers, such as `/api/config`. The *publisher* is the Viewer's one
class that writes the record and the pixels of a governed run. A
*transaction* is a group of writes that is either wholly published or not
at all, so a reader never sees half of it. The *card* is the graphics
processor; *resident* means held in the card's memory; an *upload* moves
pixels from the page to the card; a *shader* is the small program the card
runs per pixel; a *texture array* is one block of card memory holding many
tiles in numbered slots; *instanced drawing* draws many rectangles in one
command. A *fixture* is a frozen dataset a measurement is repeated on.
*SwiftShader* is a software imitation of a graphics card that Chromium can
use when there is none.

Sizes are rough, for one person who knows both repositories: *small* is a
day or two, *medium* up to a week, *large* more than a week. Both reviews
said the first revision's sizes were too small; they have been raised where
the reviews said why.

## Two directives from the owner

1. **The viewer must be very fast and very responsive at scale.** Scale
   means ten thousand positions with four channels visible. Every latency
   gate below is stated for the dense plate first; the sparse plate is the
   second case, not the headline.
2. **The graphics card is the primary optimisation target.** Pixels go to
   the card once and stay there. Windowing, colour, channel blending, the
   coverage mask, alpha and, later, projections happen in the shader. The
   main thread only schedules. Uploads are the cost to minimise. Gates
   measure the card's own time. No performance number is taken through
   SwiftShader; phase 0 and every engine number are measured on the real
   card, and a result taken without one is labelled and never compared.

## Settled, and not asked again

The reviews pointed out that three of the first revision's nine decisions
were already settled by the record or belong to a maintainer. They are
recorded here so the list below holds only what the owner must choose.

- **Phase 0 runs through the Viewer.** The record defines phase 0 as a
  breakdown that includes the composer's own timers, so the run must pass
  through the Viewer's server; the rig's own file server cannot produce it.
- **Memory is read per process**, renderer and graphics process together,
  because that is what the record's gate names. The browser's protocol
  identifies the processes; the operating system reports their memory.
- **The engine is built for the card, on WebGL2 first.** WebGL2 is what
  neuroglancer uses, so the comparison is on the same interface and the same
  card. WebGPU is recorded in phase 0 (whether the browser offers it) and
  reconsidered at the projection milestone, not before.
- **The Viewer's unreferenced `record/coarse.py`** is retired, with its
  invariant tests migrated to the active bake path, unless step 2's spike
  shows its interface fits the new transaction. That is a maintainer's call
  inside step 2.
- **The kept-coarse branch is chosen by phase 0's sentence**, before step 2
  is written, as the record already says. The first revision deferred the
  numbers to step 3; that was wrong, and step 2 cannot be designed without
  the branch.

## The decisions this plan needs, up front

Six decisions, each with a recommendation; the reasons are in the step it
belongs to.

1. **Which fixtures phase 0 measures.** The earlier design requires six
   roles: a representative small run; a multi-channel overview large enough
   to exercise plate-scale zoom; the largest available real run; a live
   replay with positions arriving at the acquisition rate; a sparse
   fluorescence run with dim puncta and bright outliers; and a stack plus a
   one-plane overview for the depth contract. *Recommended: name one frozen
   folder per role, by path and content hash, in the protocol; one dataset
   may serve several roles where the protocol says so and shows it. The
   dense mock run (a 96-well plate at nine fields per well, 864 fields, the
   largest the bridge has demonstrated) covers the plate-scale role and the
   live replay; the Leica run covers the largest real run; the remaining
   roles need a fixture each, named before phase 0.*
2. **One Viewer-owned publication transaction, designed in step 2 with a
   spike, and which package carries it.** The first revision recommended
   that the bridge simply become a client of the Viewer's publisher. Both
   reviews showed that the publisher as it stands does not provide what the
   record requires: it writes each position's own pyramid, the layout and the
   marker, but it does not bring the run-wide coarse picture current before
   the marker moves (that is done afterwards by a separate bake path), its
   commit accepts no observation reference, its channels are bare names
   without the acquisition contract's keys, colours, ranges and window
   provenance, and it has no terminal-only marker replacement. *Recommended:
   one Viewer-owned transaction is still the right shape, because two pixel
   writers would be two accounts of the experiment; but it is designed in
   step 2, starting from the publisher and extending it, and proved by a
   small spike before step 3 is scheduled. The bridge imports the installed
   Viewer's `zmart_viewer.record`; the microscopy repository's diverged copy
   `zmart_live` is retired or pinned as a copy, which is a precondition of
   step 3.*
3. **Request accounting lives in the Viewer**, on a new `/api/accounting`
   route, rather than in a proxy in front of it. *Recommended: Viewer-side,
   because a proxy adds a hop to the thing being timed; with monotonic
   snapshots and a trace identifier per step, never a global reset, so the
   accounting request and late requests from the previous step cannot
   contaminate the next.*
4. **The protocol's numbers.** *Recommended: twenty whole traces per
   fixture, cache state and storage, which is what the memory gate already
   needs and the least that yields a ninety-fifth percentile; the percentile
   computed as stated in the protocol; a tolerance of one tenth or 50 ms,
   whichever is larger, applied to comparisons with neuroglancer only, never
   to the absolute 500 ms and 1 GiB gates; the card's memory budget for the
   engine's cache fixed after phase 0 measures the card, inside the 1 GiB
   combined process ceiling, not the 512 MiB the first revision guessed;
   the dirty-box retention count left to step 2.*
5. **The live landing in the trace's ninth step.** *Recommended: two modes.
   A scripted bridge landing from the mock instrument for the repeated
   numbers, because it is reproducible; and one real Leica landing as
   confirmation. A hand-staged position is completed outside the watched
   folder and renamed into place in one step, never copied in while
   visible, or the trace measures partial arrival. Before the register
   exists, the protocol defines which event in today's bridge counts as
   "publication".*
6. **What happens to a scan when publication fails or is slow.** Today the
   Viewer is optional to the bridge: if it cannot be started, the operator
   loses the live picture and the scan continues. Making the Viewer's
   package the writer changes that boundary. *Recommended: acquisition never
   waits on publication. The stage moves on; a failed publication is
   recorded in the lifecycle document and shown on the operator page as
   "not published"; the scan is never stopped by the Viewer's library. The
   exact policy is written in step 2 and tested in step 3.*

## Step 1. The harness work phase 0 needs, then phase 0 itself

The design record authorises this work by name. Reading the rig shows how
much of it is specified and how little exists, and the reviews showed that
several of the first revision's instruments would have measured the wrong
thing.

### What exists

- The rig: a page (`viz_studio/options/harness/`) and a driver
  (`viz_studio/options/measure/drive.py`) that launches Chromium **with
  SwiftShader**, opens the page on one option, photographs it, and can pan
  and zoom it.
- The external-run door: `run.py --external-run <folder>` calls
  `real_run.py`, which opens **one store** read-only through the rig's own
  file server, waits for the picture to stop changing, and writes time,
  requests, bytes and the share of the box that was drawn.
- The rig's request ledger in its own server, counting pieces and
  description files apart, with an artificial per-request delay.
- The named canvases the rig writes for itself, including `sparse`.
- Cold-versus-warm opening in a different script
  (`viz_studio/measure_a_run_of_positions.py --cold`), with a guard that
  refuses a browser that is not really cold.
- In the neuroglancer adapter, counters for paints and let-goes only. In the
  pinned neuroglancer itself, per-layer counts of visible chunks needed and
  available (`LayerChunkProgressInfo.numVisibleChunksNeeded` and
  `numVisibleChunksAvailable`), and a frame timer built on the card's timer
  queries that only the three-dimensional panel uses.
- On the Viewer's side, the composer's timers (`read_ms`, `build_ms`,
  `encode_ms`) and a counter `tile_reads` that counts **rectangles asked
  for**, not blocks read from storage, because each rectangle may be served
  from the composer's block cache or span several blocks. None of it is
  served on any route; the server keeps no per-route counts.

### What is missing

- The ten-step trace exists only as a list in
  `docs/design/lazy-jpeg-pyramids-for-the-viewer.md`. Nothing runs it.
- "Settled" is decided by three identical photographs, 0.2 s apart, and a
  failure to settle within sixty tries returns silently. Its floor is about
  half a second, so it cannot judge a 500 ms gate.
- No memory reader. No real-card mode. No way to open a whole run through
  the rig. No share mode. No protocol document.
- The adapter places a bridge-written five-axis store beside the view, so
  its box photographs empty; the failing test is marked as expected to
  fail, strictly, in `viz_studio/tests/test_a_foreign_run_can_be_measured.py`.
- No coverage for a run of position stores: the Viewer has none to give and
  the page passes none, so the "useful picture" definition (nine tenths of
  the **covered** visible area answered) has no denominator today.

### Work items

1.0 **A real-card mode of the rig** (small to medium). The driver gains a
headed mode that launches Chromium with hardware graphics, records the
renderer's name, the card's texture-array limits, whether the timer-query
extension is present and whether WebGPU is offered, and refuses to write a
phase-0 result if the renderer reports software. SwiftShader stays for the
deterministic pixel tests in the suite. Done when, on a machine with a card,
the mode reports a hardware renderer and the SwiftShader mode reports
software, and a result taken in SwiftShader is labelled as such in its file.

1.1 **The door opens a run through the Viewer** (medium). `run.py
--external-run` gains `--through-the-viewer`: it starts the Viewer's server
with a temporary writable working folder, the real run as the folder to
open, and the narrowest opening capability (no construction or replay
routes), as the bridge's viewer service does; it opens the folder through
the Viewer's open route and points the page's data address at it. The two
modes do not show the same picture: the direct mode opens one store, the
Viewer mode composes the whole run, and the result file says which. Done
when the same run opens both ways, the result records the mode, a
before-and-after listing of the run folder proves nothing was written into
it, and the result carries the Viewer's accounting from item 1.6a.

1.2 **The adapter fix for five-axis stores** (small to medium). Find why the
navigation lands outside a five-axis OME-Zarr 0.5 store whose per-level
translations sit beside each level; the suspects are the opening-position
adjustment and the "every height begins at nought" transform in
`viz_studio/options/neuroglancer-under/viewer.js`. Done when the strict
expected-failure mark comes off that test, the companion test still passes,
and the test asserts the intended navigation and placement values, not only
a non-empty photograph.

1.3 **A settled clock from counters** (large). The adapter exposes, per row,
neuroglancer's own needed-versus-available counts, bound to the view
generation after each gesture, so a stale count for the previous view or a
trivial "nought equals nought" cannot pass. The driver waits for a non-zero
need on covered ground, needed equal to available, and one paint after
that; a timeout is a recorded failure, never a silent return. The photograph
is kept as a cross-check and both times are reported. Done when tests with a
delayed and an out-of-order delivery fail as they should, a synthetic row
settles by the counters within the photograph's time on the `square`
canvas, and the difference between the two clocks is recorded.

1.4 **The ten-step trace** (large). `real_run.py` runs the ten steps in
order with the driver's existing gestures: open cold and fit; first useful
picture by the earlier design's definition; settle; pan one viewport; zoom
to one well; zoom to source-pixel scale; enable four channels and change
each window; revisit the first two views; publish one new position; close
and reopen warm. Cold and warm come from the existing guard, moved into the
rig. Done when the trace runs headless on the dense mock run in the test
environment and its result validates against a schema that requires every
field of every one of the ten steps, including the useful-picture time with
its covered-area denominator and the live landing's start and finish
events.

1.5 **The memory reader** (medium). The driver asks the browser's protocol
for the renderer process of the measured page and the browser's graphics
process, reads their working set through the operating system with peak
sampling, and computes the gate exactly as the earlier design states it:
at most 1 GiB together over twenty repetitions, the last ten cycles growing
by less than a tenth or 20 MiB. Done when an injected allocation in the page
raises the reading by the expected amount and its release lowers it, and
the process identities are pinned in the result.

1.6a **Accounting in the Viewer** (medium to large). A counter at the true
storage boundary: block reads that miss the composer's block cache, with
bytes, beside the existing rectangle count and timers; per-route request
counts, status, ranges and body bytes; the governed run's phase accounting;
all served on `/api/accounting` as monotonic snapshots with a trace
identifier, never reset. Done when a test with a known number of block reads
and bytes reports exactly that number, a known set of requests reports
exactly those counts, and two trace steps in a row report disjoint numbers.

1.6b **Timing spans on the page** (medium). Non-overlapping, time-stamped
spans, never a residual by subtraction: the server's own span from the
accounting above; retrieval through decode as neuroglancer reports it, with
the note that the server's span lies inside it; upload and draw from the
card's timer queries where present and from the main thread's clock
otherwise, marked which. Done when injected delays in each span appear in
that span alone.

1.7 **The dense fixture** (small to medium). A script that drives the bridge
and the mock instrument to a run of a stated size, reusing the test helper
that already starts the bridge and images fields one call at a time
(`application/workflows/target_acquisition/steps/scan_the_overview/live-bridge.js`),
and the remaining fixture roles of decision 1 generated or named. Done when
the run's position count, field shape, channels, depth and time match the
frozen numbers, the files carry the bridge's lineage, the scan reports
complete, and a Viewer opens it.

1.8 **The protocol document** (small to medium),
`docs/design/phase-0-protocol.md`: the fixtures by path and hash per role;
the ten steps with their gestures in pixels and micrometres; twenty whole
traces per cell; cold and warm definitions; local disk and share paths on
the microscope PC; the tolerance and where it applies; the machine, card,
renderer, driver, browser and commits recorded; the percentile calculation;
the result schema; and the one sentence the result must take, which names
the kept-coarse branch. Done when a validator script accepts the document
and refuses one with a missing cell, and it is committed before phase 0.

1.9 **Phase 0 itself**, on the microscope PC, on the real card: every
fixture-by-storage-by-cache cell with all repetitions, failed measurements
recorded as failures, commits and card recorded, and the sentence naming the
layer that fails, if any, and the kept-coarse branch.

### Done when

Items 1.0 to 1.8 are merged with their tests, the protocol is committed,
and phase 0's sentence and table are written into the record.

### Decide

Decisions 1, 3, 4 and 5.

## Step 2. The data-layer design record

A design record with one review pass and one spike, before anything in step
3 is built. The reviews turned several of the first revision's "proposed
answers" back into questions for this record, with reasons.

### What exists

- The record package in the Viewer, whose one production writer is the
  publisher (`zmart_viewer/record/coordinator.py`). Through a sealed profile
  from `plan_the_writing` it writes a shard per level; a hand-built profile
  may omit shards. It writes numbered layout revisions with whole-pixel
  origins, publishes commit events of three closed kinds, and replaces the
  marker `signed.json` in one rename. Its reader refuses a marker that
  changes state without advancing the revision.
- What the publisher does **not** do: bring the run-wide coarse picture
  current before the marker (a separate bake path in `building.py` reacts
  afterwards, so the marker cannot today promise that a new field and its
  zoomed-out picture agree); accept an observation or notes on a commit;
  carry the acquisition contract's channel keys, colours, ranges and window
  provenance; replace the marker for a terminal state only. Its linked
  plain-file view has two modes, one that rewrites the whole run per landing
  and one at run end with two documented operator defects.
- The bridge writes position stores through the storage library, five axes,
  128-voxel chunks, no sharding, every height at nought, the recorded plane
  heights replaced by one median step, and copies the acquisition contract
  into each store's attributes. The bridge knows the planned positions and
  the channel record at scan start, and at each landing the per-plane x, y,
  z, time and channel indices and the vendor files. The Leica records start
  and finish times per capture; neither instrument records the bridge's
  landing time.
- The Leica reports frame size in micrometres and pixel size before capture,
  from the job; the data type is known only at the first capture today.
- Coverage is never written for positions; the engine accepts coverage
  regions in voxels through a hook that exists.
- The Viewer computes dirty pieces per level per landing for its bake; the
  page is told only "something changed".

### What the record must settle, each with its own evidence

2.0 **The spike** (medium). Before the record is finished: a small
throw-away programme that drives the publisher, extended as narrowly as
possible, through one landing of a mock-bridge position with an observation
reference, sharded levels, the coarse pieces brought current before the
marker, the acquisition contract carried, and a terminal-only marker
replacement, and shows a Viewer opening the result. Evidence: the spike
runs; its diff against the publisher is measured in lines; what it could not
do is listed.

2.1 **The transaction.** Its order: write and validate the observation;
write every retained level of the position with the shard the profile
declares; bring every kept coarse piece the landing dirties current; write
the pointer and layout products; then, and only then, advance the pixel
marker. A separate locked terminal-only replacement that changes no pixel or
layout revision. The linked-view mode chosen with its scaling and defects
stated. The failure policy of decision 6. Evidence: the transaction written
as a numbered sequence with what each step refuses; a test list.

2.2 **The observation document.** One immutable file per landing beside the
marker, named by position and generation: per-plane x, y, z in micrometres,
time and channel indices, vendor file names, and a landing time stamped by
the bridge with the clock named. The commit event references it. The rule
deriving the layout origin from the observation is written once, with the
run's x, y and z datum and the exact rounding from stage micrometres to
run-relative whole pixels, so raw stage coordinates never reach the
publisher's position map. Evidence: the schema with a version; a worked
example.

2.3 **The lifecycle document and the terminal publication.** One file beside
the marker with the terminal state, time, reason, the positions skipped or
never coming, and any publication failures. Published by the terminal-only
replacement. The new reader's behaviour: on a same-revision fingerprint
change it reads the lifecycle and changes planned positions to "not
acquired" or "skipped"; the document is immutable; a terminal run refuses
to resume. Evidence: the schema; the reader rules as tests; a test that an
older reader ignores the extra field, which the marker's reader already
does.

2.4 **The collection index.** At the experiment run's folder: per
collection a stable identity, display name, acquisition type, the governed
runs in order, and the index's revision, replaced atomically; the re-scan
rule that a scan of a type with an existing governed run is refused unless
the request names a new collection instance. Evidence: schema; the
interrupted-write case.

2.5 **The coordinate frame.** Stage z direction, handedness and units as the
instruments report them; a recorded plane centre as two voxel edges in
half-open intervals, with which plane owns a shared edge decided here with
its reason; irregular steps beyond a tolerance flagged at conversion; the
calibration revision starting at one. Evidence: worked examples for a
regular, an irregular and a reversed stack.

2.6 **Coverage.** Derived in memory from the layout and the committed set
at each revision, served on the live-state document per source in voxels of
level 0 with its revision, committed positions only. For today's
position-store folders, before the register exists, the same footprints
from the composer's placements, so phase 0 has its denominator. Evidence: a
test that coverage never includes an uncommitted position.

2.7 **The dirty-box protocol, and the content generation it yields.** Per
accepted revision the boxes in level-voxel coordinates per level; the last N
kept; a range query; the gap rule. The record shows, with an example, how a
later engine derives a tile's content generation from the boxes without
scanning its cache. Evidence: N with its reason; the example.

2.8 **The cost model and the kept coarse levels.** The branch chosen by
phase 0's sentence. The model over the planned positions; the tile size at
every level including the lazily assembled middle levels, named
explicitly; the single-file-levels decision; the numerical guard's share (the
fraction of a level's tiles that may exceed the budget before the level is
kept). Evidence: the numbers from phase 0 in a table.

2.9 **Sharding.** The shard declared for every retained level with more
than one chunk, sized for a position-sized run, and a test that every such
level of a governed run is in fact one shard. The composer's "every store
has every level" rule shown unnecessary for governed runs.

2.10 **The folder tree, provenance and the display contract.** The complete
hierarchy of an experiment run with governed runs: where the vendor TIFFs
and their metadata stay, where `zmart-acquisition.json` lives, and how the
acquisition contract (stable channel keys, indices, labels, colours, ranges,
windows and their provenance, including a window not yet resolved) reaches
both the Viewer's rows and an independent OME reader. Relative, portable
references. Schema versions on every document. Migration of every consumer
of today's `positions/<type>/*.ome.zarr` shape: the rig's door, detection,
focus scoring and the viewer service. Evidence: a folder listing of one
example run; the list of consumers with their change.

2.11 **The window key by kind.** (channel, kind) with "slice" the only kind;
the measure route and `setChannel` carry the kind; label rows are never
measured. Evidence: the two-kinds-on-one-channel case written out.

2.12 **The package.** The bridge imports `zmart_viewer.record`; `zmart_live`
retired or pinned; `record/coarse.py` retired or routed, per the spike.
Evidence: the import list of both repositories after the change.

### Done when

Each item above has its evidence in the record; the spike has run; the
record is reviewed once by two reviewers; the numbers it leaves to
measurement are listed by name.

### Decide

Decisions 2 and 6.

## Step 3. The data layer built and measured under neuroglancer

The first revision's single "bridge as a publisher client" hid six
independent failure boundaries. They are split.

3.1a **Profile and layout at scan start** (medium). The bridge seals the
profile from the instrument's exact pixel shape, data type, channels, planes
and room along time, which the instrument interface must expose before the
first capture; an instrument that cannot is refused with a sentence, and
"one landing late" is not a fallback. The layout is written from the planned
positions through the datum and rounding of 2.2. Tests: the profile and
layout exist before any pixel; a mismatching first capture is refused.

3.1b **Pixels through the transaction** (large). Each landing converts the
vendor planes into one volume as today and hands it to the transaction.
Tests: pixel equivalence with today's writer, voxel for voxel; every
retained multi-chunk level is one shard; the marker never moves before the
coarse pieces the landing dirties are current, proved by reading both at
the marker's fingerprint change.

3.1c **Observation and commit** (medium). Tests: the observation exists and
is referenced by the commit; its landing time and per-plane positions match
the driver's record.

3.1d **Terminal publication** (medium). Tests: completed, stopped and failed
runs each publish the lifecycle without changing the pixel or layout
revision; a terminal run refuses to resume; a publication failure appears in
the lifecycle and the scan continues, per decision 6.

3.1e **The Viewer's governed open path** (medium). The viewer service opens
the governed run once through a new path with a capability check and
follows it through the marker; the thirty-second relink by store count is
gone for governed runs. Tests: opening cost independent of position count;
no relink over a run of a stated size; a folder without a register keeps the
old path.

3.1f **Provenance and consumers** (medium). The vendor files and the
acquisition contract stay where 2.10 says; the rig's door, detection and
focus scoring read the new shape. Tests: each consumer's existing test
passes on a governed run.

3.2 **Coverage and dirty boxes on the live-state document** (medium to
large). Tests: committed-only coverage; revision and range queries; exact
boxes at every level; the retention gap; delivery to the page and through
the engine hook.

3.3 **The window key by kind** (small to medium), in both repositories.
Tests: two kinds on one channel; labels never measured; every panel state;
refusal of an absent window at the shader.

3.4 **The collection index and the panel's grouping by identity** (medium to
large). Tests: stable identity; ordering; revision; same-type re-scan
refused; interrupted index write; Viewer grouping.

3.5 **Measurement** (medium to large, with days on site). The data-layer
gates, run by the rig through the Viewer on the frozen fixtures, local disk
and share, cold and warm, with the cost model's numbers filled in. A
versioned result file per gate. This is the baseline the engine must beat.

### Done when

Every data-layer gate holds, counted on the Viewer's side, with a result
file each. If every gate of the earlier design also holds, promise 3 applies
and the engine's first brief shrinks to the features it exists for.

## Step 4. The engine, built for the card

### 4.0 The upload measurement (small to medium), before the record

On the microscope PC, headed, on the real card: bytes per second and time
per upload by size and format; a sub-image upload into a texture array
against a fresh texture per tile; with and without an unpack buffer;
completion observed by a fence. Its numbers fix the upload budget and the
pool sizes in the engine record. Done when the measurement runs on two
different cards and the protocol records both.

### The engine record (medium to large), one review pass

The first brief: a flat top view over the positions as the stores place
them today, rectangles only, slices only, channels as an overlay. It decides
the numbers the design record leaves to it: the priority arithmetic and
tie-break, the prefetch and upload budgets in items, bytes and milliseconds,
the retry limit and the group timeout. It states the three identities as
data structures, the worker's message contract, and the measurement handle
with the same counters the adapter exposes after item 1.3, plus the card's
time per frame and upload time per frame from timer queries, absent and
said so where the extension is missing.

Its card-first content, from the GPU note and the ninth review section:

- One pre-allocated texture array per internal format, sized to the
  budget, a tile a slot; the array's limits read from the card at start and
  recorded; a texture per tile only if the card's limits make the array too
  small, measured once.
- Drawing in two stages: a resolve pass per channel into a screen-sized
  integer plane plus mask, finest first with the depth test so the first
  writer wins (the record's "depth test or paint order" is decided: depth
  test); then one compose pass that windows, colours, weights and adds every
  visible channel.
- Rectangles drawn instanced, one call per format, channel and level batch,
  with per-tile position, slot and scale in one attribute buffer; the main
  thread writes that buffer and the uniforms and nothing else per frame.
- The page keeps no copy of the pixels after upload; the worker keeps the
  compressed pieces of the visible and prefetch tiers, so a lost context is
  re-decoded and re-uploaded without a request. "Resident" means on the
  card; a prefetched neighbour is uploaded, not merely decoded.
- The coverage mask is geometry for whole tiles, from the register, and a
  packed one-bit-per-voxel texture for partial tiles; absent tiles are not
  drawn at all, so there is no fill-value texture.
- Programs compiled once per data kind and channel count; window, colour,
  opacity and the colour map (a lookup texture) are drawing inputs, so no
  operator action recompiles.
- The upload budget per frame, before the draw, bounded in bytes and items,
  visible first, with the numbers from 4.0.
- Drawing only when something changed, as neuroglancer does, never a
  continuous loop; the level chosen with a stated margin against the
  screen's pixel size; the coarse fallback chain bounded to the next kept
  level rather than walked to the coarsest.
- Prefetch decided as probabilistic from velocity or a fixed ring, with the
  reason, and coverage-aware either way, so no budget is spent on ground
  that will not draw.
- The decoding bound with back-pressure, and retry with back-off and a
  limit, marked as ours.

### The engine, in stages

4.1 **Source and cache, headless** (large). Tests enumerate the state
machine, eviction by tier, content generation, retry, the dirty-range
consumer and the three kinds of nothing, in Node against a recorded set of
Viewer answers.

4.2 **The worker** (medium). Tests: transfer of ownership, cancellation,
decode failure, back-pressure, and the compressed-piece retention for
context loss.

4.3 **The renderer** (large). Tests: a pixel-reference test against a fresh
composition; the texture budget honoured; a forced context loss recovered
without a request; a stale frame never presented as current; the mask
correct on partial tiles.

4.4 **The fourth option beside neuroglancer** (medium). Done when every
existing harness row and the ten-step trace run on it with the same result
schema, and the adapter exposes neuroglancer's own frame timer through the
same handle, so the comparison is like for like.

4.5 **The numbers** (medium to large, with days on site). Every engine gate,
cold and warm, on the frozen fixtures, over twenty traces.

### Gates added to the record's list

- The card's time per frame at four channels on the dense plate, at the
  ninety-fifth percentile, within a budget the protocol fixes after phase 0
  measures the card; the main thread's time per frame reported beside it;
  neither replaces the latency gate.
- Every result records the renderer's name and whether the timer extension
  was present; a SwiftShader result is labelled and never compared with a
  headed one.
- A weak or shared card and a remote session without hardware graphics are
  machine classes with their own budget numbers; the engine degrades by
  residency and never refuses to draw.

### Done when

Every engine gate holds with a result file each. Only then does the
operator page offer the new engine, and neuroglancer stays beside it.

## Step 5. Later milestones

Each with a short record, a review pass and its own gates, and no
implementation starts until its record supplies them. In order: labels (a
data kind never measured, a 32-bit integer texture format, whether
compressed label encoding is needed stated with a number, then the layer on
the operator page); the maximum projection, then mean and sum, computed on
the card as passes over resident planes with the accumulator precision
WebGL2 allows and its limits stated; selectable placement modes, aligned
first, then absolute with its default projection or slab; turned positions;
the side view with its own slider, the two contract changes, and the chunk
layout it reads decided; the navigation extras.

## Step 6. Three-dimensional rendering

Only after step 5, choosing its representation from measurements, with the
prior-art notes as the starting reading, frame-rate adaptive downsampling
(which neuroglancer uses only in its three-dimensional panel) on its list,
and WebGPU reconsidered with what phase 0 recorded.

## Sequence and sizes

| Step | What | Size | Depends on |
|---|---|---|---|
| 1.0 | A real-card mode of the rig | small to medium | nothing |
| 1.1 | The door opens a run through the Viewer | medium | 1.6a for its accounting; can start now |
| 1.2 | The adapter fix | small to medium | nothing |
| 1.3 | A settled clock from counters | large | nothing |
| 1.4 | The ten-step trace | large | 1.1, 1.2, 1.3, 1.6b, a fixture from 1.7 |
| 1.5 | The memory reader | medium | can be built now; its done-when needs 1.4 |
| 1.6a | Accounting in the Viewer | medium to large | nothing |
| 1.6b | Timing spans on the page | medium | 1.3, 1.6a |
| 1.7 | The fixtures | small to medium | decision 1 for the frozen shapes |
| 1.8 | The protocol | small to medium | decisions 1, 3, 4, 5; drafted early, frozen after 1.4 to 1.7 |
| 1.9 | Phase 0 on the microscope PC | days on site | 1.0 to 1.8, the named fixtures, the machine |
| 2.0 | The spike | medium | 1.9's kept-coarse sentence |
| 2 | The data-layer record and its review | medium to large | 1.9, 2.0, decisions 2 and 6 |
| 3.1a to 3.1f | The bridge and the transaction, six parts | medium to large each | 2 |
| 3.2 to 3.4 | Coverage and dirty boxes, window key, index | medium to large | 2; integrated after 3.1 |
| 3.5 | The data-layer measurement | medium to large, days on site | 3.1 to 3.4 |
| 4.0 | The upload measurement | small to medium | 1.0; can run beside phase 0 |
| 4 | The engine record, then five stages | large | 3.5, 4.0 |
| 5 | Later milestones | medium to large each | 4 |
| 6 | Three dimensions | large | 5 |

Items 1.0, 1.1, 1.2, 1.3, 1.5 (the reader, not its done-when), 1.6a and
1.7 (the generator) can start now, in parallel with the discussion of the
decisions.

## Risks worth naming now

- **The coarse picture after the marker.** Without the transaction of 2.1,
  a newly acquired field can appear at one zoom and stay old at another;
  that is the risk the whole of decision 2 exists to remove, and the spike is
  how it is retired early.
- **The profile before the first capture.** The instrument must promise
  the exact pixel shape, data type, channels, planes and time room before
  the scan starts. The Leica reports frame and pixel size from the job; the
  data type is the open item, and an instrument interface change is in
  3.1a.
- **The fault boundary.** Making the Viewer's package a writer could delay
  a stage move or stop conversion; decision 6 keeps acquisition ahead of
  publication, and step 3 tests it.
- **The channel contract.** The publisher as it stands would lose the
  stable keys, colours, ranges and window provenance the position writer
  carries today; 2.10 keeps them.
- **The share.** The marker's fingerprint includes the inode, and a reader
  on another machine may see a rename late; both are tested on the real
  share in phase 0.
- **A settled clock that agrees with itself.** Two stale clocks can agree;
  1.3 binds the counters to the view generation and to a paint, and a
  timeout is a failure.
- **Software rendering.** Any number taken through SwiftShader says nothing
  about the card; 1.0 refuses to write one as a phase-0 result.
- **A weak or shared card, or a remote session.** These are machine classes
  with their own budgets, and the engine never refuses to draw.
- **Two repositories and two copies.** The record package, composer and
  server are in the Viewer; a diverged copy of the record package lives in
  the microscopy repository beside the rig; 2.12 retires it.

## Decisions on the two reviews and the note

Every finding was checked against the code before being taken.

Taken from both reviews:

- decisions 1, 6 (process memory) and 7 moved out of the list as settled or
  a maintainer's call; decision 3 recast as a Viewer-owned transaction
  designed and spiked in step 2, with its costs written in (the coarse
  picture after the marker, the observation reference, the channel
  contract, the folder tree and its consumers, the linked-view mode, the
  fault boundary and failure policy, the package);
- phase 0 repaired: a real block-read counter with bytes, a settled clock
  bound to the view generation with a failing timeout, real coverage for
  the useful-picture denominator, twenty whole traces, the six fixture roles
  named, non-overlapping timing spans instead of a residual, the
  thirty-second relink stated for the ninth step on today's path, the
  scripted landing plus a Leica confirmation, the staged copy renamed into
  place;
- the kept-coarse branch moved to phase 0's sentence and step 2; the
  numerical guard, the lazy-middle tile size, the datum and rounding,
  schema versions, the terminal reader's behaviour and the sharding test
  added to step 2; the edge-ownership and document-path choices moved
  inside step 2 as decisions with reasons;
- every "done when" rewritten as a test or measurement that can fail; 1.6
  split; 3.1 split six ways; the dependency table corrected; sizes raised
  for 1.3, 1.5, 1.6, step 2, 3.1, 3.2, 3.4, 3.5 and 4.5;
- the claims corrected: three photographs; the Leica's own start and finish
  times; the rectangle counter; the publisher's shards through the sealed
  profile only; the mesoSPIM's capture time.

Taken from the ninth review section and the GPU note: the card-first
content of the engine record; draw-on-demand; the level margin and the
bounded fallback chain; the depth-test choice; programs compiled once;
coverage-aware prefetch; the upload measurement as 4.0; the card's time per
frame as a gate; the renderer recorded on every result; the side-view
layout, compressed labels and adaptive downsampling placed in steps 5 and 6;
WebGPU recorded and reconsidered at the projection milestone.

Taken with a qualification:

- The internal review's "1.7 is essentially done": a 96-well specification
  exists, but with an hour's timeout and no frozen shape or lineage check,
  so the item stays, small to medium.
- Codex's "expose exact profile inputs before scan start": taken as an
  instrument-interface requirement in 3.1a with a refusal, not as an
  assumption that every instrument can already do it.

Not taken:

- Codex's suggestion that the 512 MiB cache budget be explained inside the
  1 GiB ceiling. The number is withdrawn instead; the budget is fixed after
  phase 0 measures the card, which the GPU note shows is the only honest
  way to choose it.
