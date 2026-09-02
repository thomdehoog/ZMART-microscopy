# The rendering engine and the register: a detailed plan, for discussion

Date: 2026-09-02. Status: a proposal to discuss, not a decision. Nothing
here is implemented. It expands the six steps in the "Order of work" of the
design record (`own-rendering-engine-and-position-register.md`, fourth
revision) into work items, each tied to the files that exist today and to
the gaps found by reading them. Where a choice belongs to the owner, it is
marked **Decide** and collected in the first section, so the discussion can
start there.

Two repositories are involved and they are read together throughout: the
microscope repository (`ZMART-microscopy`, the bridge, the operator page,
the measurement rig and the storage library) and the Viewer
(`zmart-viewer`, the record package, the composer and the server). Paths
below say which one they belong to.

## Words used below

The design record's glossary applies. Three more: the *rig* is the
measurement harness under `viz_studio/options/`, a small web page driven by
a Python script in a real Chromium; a *route* is one address the Viewer's
server answers, such as `/api/config`; the *publisher* is the Viewer's one
class that writes the record and the pixels of a governed run.

Sizes are rough and for discussion only: *small* is a day or two, *medium*
is up to a week, *large* is more than a week. They assume one person who
knows both repositories.

## The decisions this plan needs, up front

Everything else in this document follows from these nine. Each has a
recommendation; the reasons are in the step it belongs to.

1. **Phase 0 runs through the Viewer, not the rig's own file server.** The
   rig's "external run" door today serves stores from its own small server
   and opens one store, not a run. Phase 0 is meant to time the existing
   Viewer, whose server composes pieces and whose timers we want. So the
   door gains a mode that starts a Viewer beside the page and points the page
   at it. *Recommended: yes; without it the server-side breakdown cannot be
   taken at all.*
2. **Which runs phase 0 measures.** A real run from the Leica, as large as
   the microscope PC holds; and a dense run written by the bridge from the
   mock instrument, whose largest demonstrated size is a 96-well plate at
   nine fields per well (864 fields of 256 pixels). *Recommended: both, and
   the protocol names the Leica run by folder before it is measured.*
3. **The bridge writes the register by becoming a client of the Viewer's
   publisher**, which then also writes the pixels, rather than keeping the
   storage library's position writer and adding documents beside it.
   *Recommended: the publisher. It already shards every level, rebuilds
   coarse pieces from committed positions in the same step, and refuses the
   things the record must refuse. Two pixel writers would be two truths.
   The cost is that a governed run's folder shape differs from today's
   `positions/<type>/*.ome.zarr`, and the profile must be sealed before the
   first capture, which needs the frame size from the instrument first.*
4. **Where the new documents live.** The observation and lifecycle documents
   go under the governed run's own `views/live/metadata/` folder beside the
   publication marker; the collection index goes one level up, at the
   experiment run's folder, as `zmart-collections.json`, because a
   collection spans governed runs. *Recommended as stated.*
5. **Request accounting lives in the Viewer**, as a small counter per route
   and a byte tally, served on a new `/api/accounting` route, rather than a
   proxy ledger in front of it. *Recommended: Viewer-side; a proxy adds a
   hop to the very thing being timed.*
6. **Memory is read per process**, with the browser's protocol used only to
   learn which process is the renderer and which is the graphics process.
   *Recommended, because the gate names those two processes and the page's
   own heap number does not cover the graphics process.*
7. **The Viewer's unreferenced `record/coarse.py`** states the "committed
   positions only, same step" law but nothing imports it; the bake path
   implements the law separately. *Recommended: the data-layer record
   either routes the bake through it or retires it; it is not left as a
   second statement of one rule.*
8. **The protocol's numbers.** Proposed for discussion: five repetitions per
   trace step, cold and warm reported separately; a tolerance of one tenth
   or 50 ms, whichever is larger; a graphics-memory budget of 512 MiB for
   the engine's cache; the dirty-box retention count left to step 2.
9. **Step nine of the trace on the Leica** ("publish one new position during
   the session") needs either a live scan while the trace runs or a staged
   copy of one position moved into place by hand. *Recommended: a live scan
   of one position through the bridge, because it exercises the real path,
   with the staged copy as the fallback written into the protocol.*

## Step 1. The harness work phase 0 needs, then phase 0 itself

The design record authorises this work by name. Reading the rig shows how
much of it is specified and how little exists.

### What exists

- The rig: a page (`viz_studio/options/harness/`) and a driver
  (`viz_studio/options/measure/drive.py`) that launches Chromium, opens the
  page on one option, photographs it, and can pan and zoom it. Options are
  `neuroglancer-under`, `viv-under`, `viv-inside` and `jpeg-under`.
- The external-run door: `viz_studio/options/measure/run.py --external-run
  <folder>` calls `real_run.py`, which opens **one store** read-only through
  the rig's own file server, waits for the picture to stop changing, and
  writes time, requests, bytes and the share of the box that was drawn.
- The request ledger in the rig's own server
  (`viz_studio/options/measure/data_server.py`), counting pieces and
  description files apart, with an artificial per-request delay.
- The named canvases the rig writes for itself, including `sparse`.
- Cold-versus-warm opening, in a different script
  (`viz_studio/measure_a_run_of_positions.py --cold`), with a guard that
  refuses a browser that is not really cold.
- Counters in the neuroglancer adapter, but only paints and let-goes; no
  "needed versus available".
- On the Viewer's side, the composer's own timers and its read counter at
  the storage boundary (`zmart_viewer/compose.py`: `tile_reads`, `read_ms`,
  `build_ms`, `encode_ms`), and the governed run's per-phase accounting in
  `building.py`. None of it is served on any route, and the server keeps no
  per-route counts at all.

### What is missing

- The ten-step trace exists only as a list in
  `docs/design/lazy-jpeg-pyramids-for-the-viewer.md`. Nothing runs it.
- "Settled" is decided by two identical photographs 0.2 s apart, a floor of
  about half a second, which cannot judge a 500 ms gate.
- No memory reader of any kind in the rig.
- No way to open a whole run through the rig; one store only.
- No share mode; the artificial delay stands in for it.
- The adapter places a bridge-written five-axis store beside the view, so
  its box photographs empty. The failing test is marked as expected to
  fail, strictly, in `viz_studio/tests/test_a_foreign_run_can_be_measured.py`.
- No protocol document.

### Work items

1.1 **The door opens a run through the Viewer** (medium). `run.py
--external-run` gains `--through-the-viewer`: it starts
`zmart_viewer.server.make_server(data_dir=<run>, live=True, allow_open=True)`
exactly as the bridge's `viewer_service.start` does, opens the folder with
`POST /api/stores/open`, and points the page's `&data=` parameter at that
Viewer. The page's coverage call, which today asks the rig's own server,
falls back to "unbounded" when the data server is a Viewer, and says so in
the result. The rig's own server keeps serving the synthetic rows unchanged.
Done when the same run opens both ways and the result file records which
way it was opened.

1.2 **The adapter fix** (small to medium). Find why the navigation lands
outside a five-axis OME-Zarr 0.5 store whose per-level translations sit
beside each level: the suspects are the opening-position adjustment and the
"every height begins at nought" transform in
`viz_studio/options/neuroglancer-under/viewer.js`. Done when the strict
expected-failure mark comes off that test and the companion test still
passes.

1.3 **A settled clock from counters** (medium). The adapter exposes, per
row, how many chunks the view needs and how many have arrived, read from
neuroglancer's own chunk bookkeeping in the pinned version; the exact
field is found in this item and written into the adapter's comment. The
driver's `settle()` waits for needed to equal available on every row and
keeps the photograph as a cross-check, reporting both times. Done when a
synthetic row settles by the counters within the photograph's time on the
`square` canvas, and the difference between the two is recorded.

1.4 **The ten-step trace** (medium to large). `real_run.py` runs the ten
steps in order with the driver's existing gestures: open cold and fit;
first useful picture by the earlier design's definition (nine tenths of
covered visible area answered plus one non-background piece); settle; pan
one viewport; zoom to one well; zoom to source-pixel scale; enable four
channels and change each window; revisit the first two views; publish one
new position; close and reopen warm. Every step records time to settled by
counters, requests, bytes, and the breakdown of item 1.6. Cold and warm are
taken from the existing `--cold` guard, moved into the rig. Done when the
trace runs end to end on the mock bridge's run in this repository's test
environment, headless.

1.5 **The memory reader** (small to medium). The driver asks the browser's
protocol which process is the renderer and which is the graphics process,
then reads their resident memory per repetition through the operating
system, so the gate's "renderer and graphics process together" is what is
measured. Done when twenty repetitions of the trace produce the growth
number the gate reads.

1.6 **The breakdown on both sides** (medium). Viewer side: a new
`/api/accounting` route serving the composer's timers and read counter,
the governed run's phase accounting, and per-route request counts and
bytes, resettable per trace step by a `POST`. Page side: download and
decode as neuroglancer reports them, and the residual (hand-off, upload,
draw) as one labelled number. Done when a trace step's total equals the sum
of the parts plus the residual, within the tolerance.

1.7 **The dense fixture** (small). A script that drives the bridge and the
mock instrument to a run of a stated size, reusing the test helper that
already starts the bridge and images fields one call at a time
(`application/workflows/target_acquisition/steps/scan_the_overview/live-bridge.js`).
The size is fixed in the protocol.

1.8 **The protocol document** (small), `docs/design/phase-0-protocol.md`:
the runs by folder, the ten steps with their gestures in pixels and
micrometres, repetitions, cold and warm definitions, local disk and share
paths on the microscope PC, the tolerance, the memory budget, and the one
sentence the result must take the form of. Committed before phase 0 runs.

1.9 **Phase 0 itself**, on the microscope PC: the trace on the Leica run
and on the dense mock run, from local disk and from the share, cold and
warm. The result is one sentence naming the layer that fails, if any, and
the breakdown table beside it.

### Done when

Items 1.1 to 1.8 are merged with their tests, the protocol is committed,
and phase 0's sentence is written into the record.

### Decide

Decisions 1, 2, 5, 6, 8 and 9 above.

## Step 2. The data-layer design record

This step writes a design record, with one review pass, before anything in
step 3 is built. The reading done for this plan settles some of its
contents already and leaves the rest as questions for that record.

### What exists

- The record package in the Viewer, whose one writer is `LivePublisher`
  (`zmart_viewer/record/coordinator.py`). It seals a profile, writes
  numbered layout revisions with whole-pixel origins, writes pixels for
  every level with a shard per level, publishes commit events of three
  closed kinds, and replaces the marker `signed.json` in one rename. Its
  reader refuses a marker that changes state without advancing the
  revision.
- Today's only live caller of the publisher is the Viewer's own replay
  route. The bridge does not use it; it writes position stores through the
  storage library (`application/parts/storage/zarr_positions.py`), five
  axes, 128-voxel chunks, no sharding, every height at nought, the recorded
  plane heights replaced by one median step, and the channel record copied
  into the store's attributes.
- The bridge knows, at scan start, the planned positions in stage
  micrometres and the acquisition record with its channels; at each landing,
  the driver's record with per-plane x, y, z in micrometres, the plane's
  time and channel indices, and the vendor file paths. No wall-clock time is
  recorded anywhere; the mock and the Leica both hard-code the time index.
- The Leica adapter reports the frame size in micrometres before capture,
  from the job's image size, so a profile can be sealed at scan start.
- Coverage: the storage library's coverage record exists but is written
  only by the tile-canvas path, never for positions; the operator page
  passes no coverage to its engine; the engine already accepts coverage
  regions in voxels and scales them by the voxel size.
- Dirtying: the Viewer computes, per landing, the set of dirty pieces per
  level in `building.py`, but only for its own bake; the page is told only
  "something changed" over the change stream and re-reads the live-state
  document.
- The live-state document already carries, per source, the revision, the
  layout revision and the committed time ranges as half-open intervals.

### What the record must settle, and the answers this plan proposes

2.1 **The writer.** Decision 3: the bridge hands each landed volume to the
publisher, which places it by the whole-pixel origin the bridge computes
from the planned stage position and the profile's voxel size, writes the
pixels, rebuilds the coarse pieces, and publishes the commit. The storage
library's position writer stays for the tile-canvas path and is no longer
the bridge's path for positions. The profile is sealed in `_start_scan`
from the instrument's frame size, pixel size, channel record, planes and
data type; a scan whose first capture disagrees with the sealed profile is
refused with a sentence, the same way a channel-count mismatch is refused
today.

2.2 **The observation document.** One immutable file per landing under the
governed run's `views/live/metadata/observations/`, named by position and
generation, holding the per-plane x, y, z in micrometres, the plane's time
and channel indices, the vendor file names, and a wall-clock time stamped
by the bridge at landing with the clock named. The commit event's `notes`
field references it. The rule deriving the layout origin from the
observation is written here once.

2.3 **The lifecycle document and the terminal publication.** One file
`lifecycle.json` beside the marker with the terminal state, time and
reason, and the positions skipped or never coming. It is published by
replacing the marker with a copy carrying one extra field naming the file.
The record must verify that the marker's reader ignores unknown fields; the
reader checks the schema name and reads named fields, so an extra field
passes today, and a test pins that.

2.4 **The collection index.** `zmart-collections.json` at the experiment
run's folder: for each collection a stable identity, its display name, its
acquisition type, the governed runs that make it up in order, and the
index's own revision. The re-scan rule: a scan of a type that already has
a governed run in this experiment is refused unless the request names a
new collection instance, which becomes a new governed run folder listed
after the old one.

2.5 **The coordinate frame.** Stage z direction, handedness and units as
the instruments report them; a recorded plane centre becomes two voxel
edges as half-open intervals with the lower plane owning a shared edge;
irregular steps beyond a tolerance flagged at conversion, the tolerance
decided in this record; the calibration revision starts at one.

2.6 **Coverage.** The Viewer derives coverage in memory from the layout and
the committed set at each revision and serves it as an indexed snapshot on
the live-state document, per source, in voxels of level 0, with the
revision it belongs to. The operator page passes it to the engine through
the hook that already exists. Committed positions only.

2.7 **The dirty-box protocol.** Per accepted revision, the Viewer publishes
the boxes of that landing in level-voxel coordinates per level on the
live-state document, keeps the boxes of the last N revisions, and answers a
request for a range; a page that missed more than N treats every held tile
as stale. The change stream stays "something changed". N is decided here.

2.8 **The cost model and the kept coarse levels.** The Viewer's one-per-cent
pinning and its bake already keep and patch coarse levels; the record
states the measured cost model over the planned positions, the tile sizes
at every level, and the single-file-levels decision, with the numbers to
be filled in by step 3's measurement.

2.9 **Sharding.** Through the publisher, every level of a governed run is
already sharded per its profile; the record states the shard sizes for a
position-sized run and confirms that the "every store has every level" rule
of the composer is not needed for governed runs.

2.10 **The window key.** The window authority's key becomes (channel, kind)
with "slice" the only kind; the Viewer's measure route and the panel's
`setChannel` carry the kind; label rows are never measured.

2.11 **The orphan module.** Decision 7 on `record/coarse.py`.

### Done when

The record is written, reviewed once by two reviewers, and its decisions
are in; the numbers it leaves to measurement are listed by name.

### Decide

Decisions 3, 4 and 7 above, and the tolerances in 2.5 and 2.7.

## Step 3. The data layer built and measured under neuroglancer

### Work items, in order

3.1 **The bridge as a publisher client** (large). `_start_scan` seals and
stores the profile, writes the layout revision from the planned positions,
and creates the governed run folder; `_keep_position_as_zarr` becomes
`_publish_the_position`, converting the vendor planes into one volume as
today and handing it to the publisher with the observation document. The
scan worker's end publishes the lifecycle document. The viewer service
opens the governed run folder once and never relinks by counting stores.
Tests: the three documents appear with the right contents on a mock-bridge
run; a re-scan of the same type is refused by collection; the folder opens
in a Viewer with no bridge running.

3.2 **Coverage and dirty boxes on the live-state document** (medium), with
the operator page passing coverage to the engine.

3.3 **The window key by kind** (small to medium), in both repositories.

3.4 **The collection index and the panel's grouping by identity** (medium).

3.5 **Measurement** (medium): the data-layer gates from the record, run
by the rig through the Viewer on the dense mock run and on a Leica run,
with the cost model's numbers filled in on local disk and on the share.
This is also the baseline the engine must beat.

### Done when

Every data-layer gate in the record holds, counted on the Viewer's side.
If every gate of the earlier design also holds, promise 3 applies and the
engine's first brief shrinks to the features it exists for.

## Step 4. The engine design record, then the engine

### The record (medium), one review pass

The first brief: a flat top view over the positions as the stores place
them today, rectangles only, slices only, channels as an overlay. It
decides the numbers the design record leaves to it: the priority
arithmetic and tie-break, the prefetch and upload budgets in items and
bytes and milliseconds, the retry limit and the group timeout. It states
the three identities as data structures, the worker's message contract,
the texture pools by format, and the measurement handle with the same
counters the adapter exposes after item 1.3.

### The engine, in stages

4.1 **Source and cache, headless** (large): the three identities, the
tiers, the dirty-box consumer, the three kinds of nothing and one of
failed, the fixed requests in flight, all testable in Node without a
browser, against a recorded set of Viewer answers.

4.2 **The worker** (medium): fetch and decode of the Viewer's pieces off
the drawing thread, buffers handed over with ownership.

4.3 **The renderer** (large): WebGL2, a textured rectangle per tile at its
micrometre position, coarse under fine within a channel, the coverage mask,
alpha per source and channel, the window and colour as drawing inputs, the
time-sliced upload.

4.4 **The fourth option beside neuroglancer** (medium): the rig's option
folder, the same page interface, the same gesture module, the same
measurement handle, so every existing row and the ten-step trace run on it
unchanged.

4.5 **The numbers** (medium): every engine gate from the record, cold and
warm, on the sparse and the dense plate, over twenty repetitions for
memory.

### Done when

Every engine gate holds; only then does the operator page offer the new
engine, and neuroglancer stays available beside it.

## Step 5. Later milestones

Each with a short record, a review pass and its own gates, in this order:
labels (a data kind never measured and a 32-bit integer texture format,
then the layer on the operator page); the maximum projection, then mean and
sum, with the arithmetic the design record states; selectable placement
modes, aligned with its stated meaning first, then absolute with its
default projection or slab; turned positions; the side view with its own
slider and the two contract changes; the navigation extras.

## Step 6. Three-dimensional rendering

Only after step 5, choosing its representation from measurements, with the
prior-art notes as the starting reading.

## Sequence and sizes, in one table

| Step | What | Size | Depends on |
|---|---|---|---|
| 1.1 | The door opens a run through the Viewer | medium | decision 1 |
| 1.2 | The adapter fix for five-axis stores | small to medium | nothing |
| 1.3 | A settled clock from counters | medium | nothing |
| 1.4 | The ten-step trace | medium to large | 1.1, 1.3 |
| 1.5 | The memory reader | small to medium | nothing |
| 1.6 | The breakdown on both sides | medium | 1.1 |
| 1.7 | The dense fixture | small | nothing |
| 1.8 | The protocol document | small | 1.4 to 1.7 |
| 1.9 | Phase 0 on the microscope PC | days on site | 1.1 to 1.8 |
| 2 | The data-layer design record and its review | medium | 1.9, decisions 3, 4, 7 |
| 3.1 | The bridge as a publisher client | large | 2 |
| 3.2 to 3.4 | Coverage, dirty boxes, window key, collection index | medium each | 3.1 |
| 3.5 | The data-layer measurement and the baseline | medium | 3.1 to 3.4 |
| 4 | The engine record, then the engine in five stages | large | 3.5 |
| 5 | Later milestones | each medium to large | 4 |
| 6 | Three dimensions | large | 5 |

Items 1.2, 1.3, 1.5 and 1.7 have no dependencies and can start at once, in
parallel with the discussion of the decisions.

## Risks worth naming now

- **The profile must be sealed before the first capture.** The Leica
  reports the frame size from the job, but the data type and the plane
  count come from the first capture today. If the instrument cannot promise
  them, the profile is sealed from the first capture and the layout written
  then, one landing late; the record must say which.
- **The share.** The marker's fingerprint includes the inode, and a reader
  on another machine may see a rename late; both are to be tested on the
  real share in phase 0, and the protocol includes that test.
- **The 500 ms gate.** With the settled clock still from photographs, no
  500 ms number is trustworthy; item 1.3 is a prerequisite of every latency
  gate, not a nicety.
- **Two repositories.** The record package, composer and server are in the
  Viewer; coverage, sharding of the storage library and the rig are in the
  microscope repository. Every step above that spans both is merged in
  both, and the plan's tests run in both.
