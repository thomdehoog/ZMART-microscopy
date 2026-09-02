# Third review of the rendering-engine design record

Date: 2026-09-02

Reviewed: `docs/design/own-rendering-engine-and-position-register.md` on
ZMART-microscopy branch `claude/viewer-delivery-to-100`. The record's third
revision is commit `d80717b2`; the branch head while I read was `12c5f815`,
which adds only the brief for this round. The ZMART Viewer was read on its
own `claude/viewer-delivery-to-100` at `9b67bf8`. Neuroglancer was read as the
pinned 2.41.2 under `viz_studio/frontend/node_modules/neuroglancer/lib`, the
compiled form, which carries this project's own patches to the chunk manager.
Nothing on either branch was modified except to add this file.

This is the third round. The internal second review
(`docs/reviews/2026-09-02-second-review-of-the-rendering-engine-design.md`)
is treated below as my own; Codex's
(`docs/reviews/2026-09-02-second-review-of-the-rendering-engine-design-by-codex.md`)
as the other reviewer's. Both were checked, finding by finding and paste-back
item by paste-back item, against what the third revision now says. Every
"exists" or "does not exist" sentence below was checked by opening the file
and is given with a line number; where I could only reason rather than look,
the sentence says so. I ran nothing; every number is arithmetic from
constants in the code, with the case stated.

A few words used below, said once. A *tile* is one small square of one zoom
level of the picture, fetched, cached and drawn as a unit; a *chunk* is the
same idea on the storage side. A *gate* is a measurable condition a piece of
work must pass before the next piece begins. A *dirty box* is a rectangle of
the picture that a landing changed, published so a viewer knows which tiles
to refresh. *Settled* means the picture has stopped changing after a move.

## Verdict

**Accept with changes.** The third revision carries both second reviews
faithfully; I found no softening of the kind the brief asks me to catch, and
the four "not taken" refusals are argued, not waved away. The record is
ready to hand to the data-layer design, on the understanding that the
changes below are small enough to be taken *into* that record rather than
requiring a fourth revision of this one. None of them reopens a decision.
In order of consequence:

1. Two engine gates and one data-layer gate rest on fixtures the record
   calls "named" or "stated" and never names: the sparse and dense plates of
   the request gate, and the visible-channel fixture. A gate over an
   unnamed fixture can be won by choosing the fixture afterwards.
2. The harness's only "settled" instrument is a photograph that has not
   changed across two polls 0.2 seconds apart. Its coarsest honest reading
   is about 0.4 to 0.6 seconds, so it cannot judge the two 500 ms gates.
   The record already names the right instrument (the needed-versus-available
   counters); the gates should say that is the one that counts.
3. The content-generation protocol works without a global scan, and I say
   why below, but it is missing its gap rule: what a viewer does when it has
   missed one or more revisions' boxes (a reconnect, a relink, a page that
   was asleep). Without a stated rule an implementer will either rescan the
   whole cache or drop it, and the second is the blank screen this project
   patched out.
4. Two items in the "what neuroglancer does" list are ours, not
   neuroglancer's: retry with back-off (neuroglancer keeps a failed chunk
   failed until the source is invalidated) and a "decoding" budget (its
   fourth budget is for computed chunks, which nothing in the pinned build
   uses; the decode pool is bounded by a worker count, not a byte or item
   budget). Both are good rules; they should be labelled as ours.
5. The assembled slice tile's identity should carry a composition recipe
   version and should define "level" by decimation exponent rather than by
   array index, because positions will stop at 128 voxels while the composed
   picture continues, and because a change to the overlap or decimation
   rule would otherwise leave every kept tile silently wrong.

## What I read and how

- The record whole, then the two second reviews beside it, ticking each
  finding and each paste-back item as carried whole, carried weaker, or not
  carried.
- The corrected prior-art note and `git diff 176d5a61 d80717b2` on it, to
  see that the body changed and not only the preface.
- Neuroglancer 2.41.2's `chunk_manager/base.js`, `backend.js` and
  `frontend.js`; `async_computation/request.js` and `handler.js`;
  `sliceview/backend.js`, `base.js`, `frontend.js`, `volume/renderlayer.js`
  and `single_texture_chunk_format.js`; `visibility_priority/backend.js`;
  `display_context.js`; and which datasource decoders go through the pool.
- The patch script `viz_studio/frontend/scripts/patch_neuroglancer.mjs` and
  the patched regions of `backend.js` and `frontend.js`.
- The harness: `viz_studio/options/measure/real_run.py`, `drive.py`,
  `suite.py`, `data_server.py`, `acquisitions.py`, `run.py`, and
  `viz_studio/options/harness/src/main.js`; the `neuroglancer-under`
  adapter and the operator page's `engine.js`.
- The Viewer's `record` package (`model.py`, `coordinator.py`,
  `manifest.py`, `live_state.py`, `coarse.py`), `compose.py`, `building.py`
  and `server.py`; the storage library's `canvas.py` and `positions.py`; the
  bridge's `zarr_positions.py`, `output.py`, `bridge.py` and
  `viewer_service.py`; phases 0B and 1 of the lazy-pyramid design.

## Findings, ordered by consequence

### 1. Three gates name fixtures the record never names

**Facts.** The request gate reads "fewer on the named sparse plate and no
more on the named dense plate" (record, lines 686-688). The channel bullet
says how many channels are drawn at once "is a tested fixture, stated with
the gates" (121-125), and the gate says "the stated visible-channel fixture
draws within the latency and memory gates" (702-703). No sentence in the
record names a plate or states a channel count. The harness's fixtures are
`square`, `lopsided`, `sparse`, `scattered`, `colours`, a survey-and-detail
pair and a foreign store (`viz_studio/options/measure/acquisitions.py:164`,
`:188`, `:206`, `:236`, `:289`, `:400`, `:492`); the sparse canvas is a
small imaged patch in a large declared room (`:206-235`). Nothing there is
a dense plate of ten thousand positions, and nothing is bridge-written.

**Inference.** Each of the three references is circular: the gate points at
a fixture and the fixture is "the one the gate names". Name them in the
record, or say which document names them and that it is written before
step 3 runs. A reasonable choice: the sparse plate is the harness's
`sparse` canvas; the dense plate is a bridge-written run of the mock
instrument at the size the microscope PC can hold, stated in positions and
field size; the visible-channel fixture is a count (four is what the earlier
design's trace uses, `lazy-jpeg-pyramids-for-the-viewer.md:410`).

### 2. The harness's "settled" cannot judge a 500 ms gate

**Facts.** Two engine gates and one data-layer gate carry a 500 ms bound at
the ninety-fifth percentile (record, 673-676, 684-685). The harness decides
a picture is settled when two consecutive photographs are identical, polled
every 0.2 seconds, and needs two matches (`viz_studio/options/measure/drive.py:213-226`):
the earliest it can report "settled" is two polls after the last change,
about 0.4 seconds, and a screenshot itself takes tens of milliseconds. The
landing clock stops when the window is "measurably brighter" and its own
note says it is an upper bound because it includes photographing
(`suite.py:897-936`). Neuroglancer's needed-versus-available counters are
sent every 200 ms (`chunk_manager/backend.js:920`, `:942-955`), and the
harness page exposes `harness.counts()` for an engine that offers them
(`viz_studio/options/harness/src/main.js:504`). The record's measurement
hooks name the counters as what "settled" means (479-481, 526-531).

**Inference.** A 500 ms gate measured with an instrument whose floor is
0.4 seconds and whose jitter is of the same size will pass or fail on the
instrument, not on the engine. The gates should say that "settled" for the
500 ms bounds is read from the counters (needed equals available, polled
at a stated rate) or from a named event the engine emits, and that the
photograph is the correctness check beside it, not the clock. That is a
sentence in the gates and a small addition to `drive.py`, and it belongs in
the step-1 harness work, which the record already authorises.

### 3. The dirty-box protocol needs its gap rule

**Facts.** The record says the Viewer publishes, per revision, the boxes a
landing dirtied at each level, that the live-state document is the right
place, and that a cached tile's content generation is advanced "only for
tiles a landing touched" (421-437, 495-509). The live-state document
carries a revision per source (`zmart_viewer/record/live_state.py:240-250`).
The Viewer's own dirtying already computes exactly this: the set of
(row, column) pieces per level reached by the old and the new footprint of
every changed tile (`zmart_viewer/building.py:1530-1556`). The bridge today
relinks at most every thirty seconds (`application/parts/storage/viewer_service.py:60-92`),
and the adapter's refresh happens when the page is told a tile may have
landed (`viz_studio/options/neuroglancer-under/viewer.js:2605-2620`).

**Inference.** The protocol is sound (question 4 says why), but it assumes
a viewer sees every revision's boxes in order. A page that was asleep, a
Viewer that restarted, a second viewer opening mid-run, or a reader on the
share that saw the marker late (the record's own caution, 331-336) will
hold tiles stamped with a revision several steps behind. The record should
state the rule: the Viewer keeps the boxes of the last N revisions (or of
every revision since the last full publication) and a viewer that has
missed some asks for the range and replays them; if the range is gone, the
viewer treats every held tile as stale and replaces it, still drawing, never
dropping. Without this, "replace, never drop" has a hole exactly where the
share is slow.

### 4. Two scheduler items are ours, presented as neuroglancer's

**Facts.** The list is headed "What neuroglancer does that we must also do,
read from its pinned source" (438-439). Item "three kinds of nothing and one
of failed" says failed tiles are "retried with back-off, a stated limit, and
a visible permanent-failure state" (475-478). In the pinned source a failed
download sets the chunk to `FAILED` and keeps its error
(`chunk_manager/backend.js:142-145`); the only way back to `QUEUED` is the
source-wide invalidation (`backend.js:894-908`) or this project's patched
named-chunk calls (`backend.js:1113-1212`). There is no retry and no
back-off. Item "four budgets: graphics memory, main memory, downloads per
source level, and decoding" (451-453): the four capacities are graphics,
system, download per source queue level, and *compute*
(`backend.js:588-595`; `frontend.js:107-115`), and compute applies only to
chunks marked `isComputational` (`backend.js:94`, `:605-612`, `:642`); no source in
the pinned `lib` sets that flag (I searched). Decoding runs in the
asynchronous computation pool, bounded by a worker count of at most twelve
or the machine's cores (`async_computation/request.js:21`), with an
unbounded first-in-first-out queue of waiting tasks (`request.js:19`,
`:82`).

**Inference.** Both rules are right for us: a 404 that is an empty piece
must not be retried, a transient share failure should be, and decoding
needs a bound of its own because the worker count is not a budget. But a
list that says "read from its pinned source" should not include things the
source does not do. Mark those two as ours, and note beside the decode item
that neuroglancer's pool has no queue limit, which is a thing to do better.

### 5. The assembled tile's identity: recipe version and the meaning of "level"

**Facts.** The assembled slice tile's key is collection, placement,
orientation, slice axis and coordinate, moment, channel key, level, row,
column and content generation; only the stored projection carries a
"recipe version" (421-437). The composed picture keeps the overlap rule
"the one committed later lands on top" (203-206) and decimation (18-19).
The record lets bridge-written positions stop at 128 voxels while the data
layer keeps its own coarse levels (369-375), and defines level of detail by
"each level's voxel size in micrometres" (510-511). In the storage library
a position's copies are numbered from its own full size
(`zmart_storage/positions.py:131-166`), and the composer today refuses
stores whose level counts disagree (`zmart_viewer/compose.py:512-520`).

**Inference.** Two small additions save a cache flush later. First, a
composition recipe version on the assembled tile, so that changing the
overlap rule, the decimation, or the coverage-mask encoding invalidates
every kept and cached tile by key rather than by memory. Second, "level" in
every key should be the decimation exponent relative to the profile's full
resolution (0 for full, 4 for sixteen-fold), not an array index, because
once positions stop at 128 the index of "the 128 level" differs between a
position store and the composed picture. Both are one sentence each.

### 6. "Its own folder" and "several governed runs" say different things about a collection

**Facts.** The collections bullet says each collection is "its own
register, its own folder" and, three sentences later, that a collection
whose fields differ "is several governed runs, one complete profile each",
grouped by a run-level index (209-218). The Viewer holds one profile, one
layout and one run per folder (record 281; `zmart_viewer/record/manifest.py:360-385`;
`gateway.py` loads one layout per folder, as the second reviews checked).

**Inference.** The data-layer designer will read "its own folder" as a
rule and then meet a collection that is three folders. Say it once: a
collection is one or more run folders, each a governed run with one sealed
profile, and the run-level index is what makes them one collection; "its
own folder" is the common case, not the definition.

### 7. Phase 0's frozen fixtures, repetitions and tolerances have no home

**Facts.** Promise 1 says the fixtures, repetitions, budgets and tolerances
"are frozen before it runs and never relaxed after" (84-92); the phase-0
gate says "a stated number of repetitions and a declared tolerance"
(654-660). Neither the record nor the earlier design states the number or
the tolerance; the earlier design says thresholds "should be adjusted only
before running the trace, with the reason recorded"
(`lazy-jpeg-pyramids-for-the-viewer.md:464-467`). The real-run door today
opens one store once (`viz_studio/options/measure/real_run.py:92-125`).

**Inference.** A promise to freeze numbers is kept by writing them down
somewhere with a commit before the run. Name the document (a short
phase-0 protocol beside the results folder, or a section appended to the
earlier design) and say the run's result cites its commit. This is
procedure, not design, but it is the difference between promise 1 and a
sentence.

### 8. "Exactly what the patch does today" claims a little more than the patch does

**Facts.** The invalidation bullet says its four-sentence rule "is exactly
what the patch this repository maintains ... does today" (495-506). The
patch does the first two: a held chunk keeps drawing while its replacement
downloads beside the state machine, and one commit's replacements are
staged and delivered back-to-back with a two-second flush
(`chunk_manager/backend.js:1113-1182`; `frontend.js:226-236`). It does not
mark anything stale for a measurement to refuse, and a chunk the page does
not hold is simply re-queued (`backend.js:1164-1173`); the "dropped only
when the new coverage says its ground is gone" rule is nowhere in it.

**Inference.** Say "the first half of this is what the patch does today;
the stale flag and the coverage-driven drop are new". The rule is right;
the attribution is generous.

### 9. Where the harness cannot see: the Viewer's own reads and requests

**Facts.** The data-layer gates count "file operations on the Viewer's
side", "a fingerprint check, not a scan", and "one read at the storage
boundary" (662-670). The composer keeps `read_ms`, `build_ms`, `slabs_built`,
`encode_ms` and `encodes` (`zmart_viewer/compose.py:1039`, `:1091-1092`,
`:1416-1417`) and no read *count*. The harness's request ledger sits in
front of files the rig serves itself (`viz_studio/options/measure/data_server.py:63-149`);
the rig's real-run door serves a folder read-only from where it is
(`real_run.py:92-111`) and has no way to stand in front of a running
Viewer's composed route (`drive.py:168-202` builds its own address). The
fingerprint is one `stat` (`zmart_viewer/record/manifest.py:439-454`).

**Inference.** The first three data-layer gates are measured on the Viewer's
side, not the harness's: a read counter at the composer's storage boundary
(one line beside `read_ms`), and a test in the Viewer that counts directory
listings and `stat` calls on open and on relink. The fourth (no request for
uncovered tiles) is a ledger count, but only if the harness's ledger can
sit in front of the Viewer's route; today it cannot, so either the Viewer
logs its requests or the rig learns to proxy. Both belong in the step-1
harness work and should be named there.

### 10. Smaller corrections

- **The 200,000-read warming figure counts pieces that overhang the plate.**
  For the 2048 three-channel plate the kept levels are 4 to 8 and each
  position's copy at those levels is one chunk, so each position is read
  once per kept level per channel: 10,000 × 5 × 3 = 150,000 reads. The
  figure of 66,000 per channel that gives 200,000 comes from 625, 169, 49,
  16 and 4 pieces times 16, 64, 256, 1,024 and 4,096 positions each, which
  counts the edge pieces' full footprint beyond the plate. "On the order of
  200,000" (391-393) is honest as an order; "about 150,000, more with edge
  pieces and overlap" is the arithmetic.
- **Neuroglancer's context-loss "recovery" is a page reload**
  (`display_context.js:331-339`: on loss it prevents the default, on
  restore it reloads). The record lists "recovery from a lost graphics
  context" among things neuroglancer does (486-487); it does, in that way.
  Ours should keep the view in micrometres across it, which the navigation
  section already promises (543-545).
- **The re-scan refusal is per image file name, not per type.** The
  vendor-file move refuses to replace an existing image
  (`application/parts/storage/output.py:145-146`, called from
  `application/framework/bridge.py:707-709`), and a scan of the same
  positions repeats the labels (`bridge.py:702-705`). A re-scan of a
  *different* position list under the same type is not refused and lands in
  the same folder. The record's sentence (286-289) is true for the same
  labels; the data-layer record should refuse by collection, as it says.
- **The step-4 text does not list the (channel, kind) key** although the
  decisions section says it is "in step 2 and step 4" (579). Step 2 has
  it (718-719); step 4 does not need it, so drop "and step 4" or add it.
- **Terms still arriving unglossed**: *half-open* (139, 180; "includes
  its low edge and excludes its high edge, so a shared edge belongs to
  exactly one plane"), *least-recent-use* and *evicted* (441-442), and
  *worker* (488; "a helper the browser runs beside the page, on its own
  thread"). The glossary otherwise works: every term the second reviews
  listed is there, and the scheduler list now says what an operator would
  notice, which was the biggest readability problem last round.

## Answers to the eight questions

### 1. Were the second-round findings carried faithfully?

**My own sixteen findings and paste-back.** (1) Phase 0 runnable, the three
pieces of harness work authorised by name, the subtraction stated: carried
whole (84-92, 654-660, 706-710). (2) Replace, never drop, citing the patch:
carried whole (495-506), with finding 8's over-attribution. (3) Prior-art
body rewritten: carried whole; the diff shows both sections rewritten, not
prefaced (`git diff 176d5a61 d80717b2 -- docs/design/prior-art-larger-than-memory-3d-rendering.md`).
(4) Layout keeps whole pixels, observation is a separate document, the
derivation rule written once, the store's step draws, raw heights are
provenance, a tolerance flag at conversion: carried whole (126-144,
292-302). (5) One governed run per shape, cross-run index in the extension
and in step 2: carried whole (209-218, 303-306, 712-719), with finding 6's
wording. (6) Additive fields under the same schema, what an older Viewer
sees: carried whole (310-320). (7) The (channel, kind) key, `setChannel`'s
kind and the never-measured label row in the plan: carried whole (219-231,
718-719). (8) Codex's absolute top slice named in "Not taken": carried
whole (606-611). (9) The process-level memory gate beside the cache's own:
carried whole (688-691). (10) The request gate by plate: carried in words,
weaker in substance, because the plates are not named (finding 1). (11) One
plate case per bullet, "single-file levels": carried whole (349-355,
362-379, 389-395). (12) The scheduler list completed: carried whole, with
finding 4's two attributions. (13) Single-plane thickness, turned
positions, the meaning of time, which height draws: all four carried whole
(153-158, 172-174, 118-120, 134-137). (14) Placement and the slice's unit
in the key, generation off composed tiles: carried whole (421-437).
(15) Sharding of every level with more than one chunk, sub-128 levels
droppable only if the coarse pyramid is built: carried whole (369-379).
(16) The shard factor "about half, growing with the shard"; the refusal is
the bridge's; the glossary: carried whole (376-379, 286-289, 12-40).
Paste-back's stop condition in the order of work: carried (93-99, 729-730).

**Codex's six findings and paste-back.** (1) Three durable facts, the
lifecycle record separate from pixel commits, a versioned rule for the
marker and readers, one complete sealed profile per manifest, a run-level
catalogue: carried whole (292-321, 209-218). (2) Per-tile content
generation instead of the run-wide revision, three identities, slice axis
and coordinate, projection recipe version, window and colour as drawing
inputs, mask in the payload: carried whole (421-437), except that
"layout or presentation-transform identity" is carried as the placement
*mode* in the key and not as a calibration or presentation revision; under
aligned placement that is enough, under absolute placement the calibration
revision the observation record carries (303-306) must join the key, and
the record should say so when absolute placement is designed (finding 5 is
the neighbouring gap). (3) Half-open intervals, edge ownership, irregular
heights, centre-to-edge conversion, per-channel association, calibration
revision; side-view direction and per-overlay rule; sample mean named,
accumulator by input, overflow refused, result types, missing planes:
carried whole (138-144, 164-171, 175-193), with the geometry definitions
delegated to the data-layer record as Codex asked. (4) Prefetch and recent
behaviour, reprioritisation, coalescing, separate capacities, a per-frame
upload budget, cancellation per stage, buffer ownership, worker count
measured: carried whole (438-494); "what cancellation can stop at each
stage" is carried for downloads (461-464) and not for decoding, which is a
half-sentence to add. (5) The instrumentation phase, frozen fixtures, the
useful-picture definition reused, cold and warm, a tolerance, sparse and
dense, output-tile footprints, reads at the storage boundary, panel states
at application level, complete input fixtures: carried whole in words
(84-92, 654-703), weaker where fixtures are unnamed (finding 1) and where
the instrument cannot resolve the bound (finding 2); Codex's "compare pixel
values and masks, overlap order, level changes and revision changes
automatically" is carried only as the landing-footprint gate (692-693), and
a pixel-equivalence gate between the two engines on the same view is not
in the list. (6) `uint16`, one hundred by one hundred, no overlap, one depth
and one time printed beside the numbers: carried whole (342-347); the
re-scan fact corrected: carried (286-289); share scan and raw bytes
labelled hypotheses: carried whole (644-647). Codex's three cuts (one
universal identity, exactly one worker, a 32-bit sum) are all cut
(421-437, 488-494, 184-188). Codex's conditions on the contested decision
(fixtures fixed before, no threshold relaxed, neuroglancer remains on a
missed gate, later milestones or a failed engine can be stopped) are the
three promises (84-104), with "the result chooses the engine's scope"
carried as promise 3 and "chooses ... scheduler priorities" not carried in
those words, which I do not count as softening: the scheduler is specified
from the source and phase 0 measures the data layer, not the scheduler.

Nothing was carried that neither review asked for except the honest
labelling of the retry rule as neuroglancer's, which is finding 4.

### 2. Is the record ready to hand to the data-layer design?

Yes, with the items above carried into that record. Of the settled inputs
the brief lists, an implementer would still decide: the coordinate
convention of a dirty box (a box in the level's voxel coordinates, from
which either a 128 tile or a 512 piece can be derived, is the right one;
the Viewer today emits piece indices, `building.py:1530-1556`); the gap
rule (finding 3); the tile size at a level that is neither a single
position chunk nor a kept piece but is assembled lazily under the boundary
rule (383-388 says only "finest" and "kept"); the level numbering
(finding 5); and how many revisions of boxes the live-state document
keeps. Contradictory between sections: only finding 6's "its own folder".
Two decision points about kept levels read as one and should be said in
one sentence: phase 0 decides whether any coarse level is kept (396-398),
and the cost model measured in step 3 decides where the lazy-to-kept
boundary sits (405-419); the sub-128 decision hangs off the first, so it
is decided before step 2, which is the right order.

### 3. Are the three phase-0 promises enough, and kept by the rest?

Enough, and kept. Nothing in the order of work is built before phase 0
except the three named pieces of harness work (706-710), and the adapter
fix among them is a feature, not instrumentation, but it is named, which is
what promise 1 requires. The operator page stays on `neuroglancer-under`
in promise 2 (93-99) and again in step 4 (729-730). Promise 3 is repeated
in step 3 (720-722). The engine section's "measurement hooks, from the
first commit" (526-531) and "a texture format for 32-bit integers ... from
the start" (199-201) are engine work and fall under step 4. The one
weakness is finding 7: the promise to freeze numbers has nowhere to put
them.

### 4. Are the three tile identities right?

Right in their split. A raw chunk is one position's own bytes and carries
that position's generation; an assembled tile is many positions' bytes
under one placement and carries a content generation; a stored projection
adds its axis, half-open range, kind, recipe version and input generations.
Placement belongs in the assembled key and not in the raw key, because a
raw chunk's pixels do not change with placement, only where they are drawn,
and the record says this correctly (383-388 puts the source chunk at fine
levels and the composed piece at kept levels).

**Can the content generation be advanced without a global scan?** Yes,
concretely. The Viewer already computes, per landing and per level, the set
of piece coordinates the old and the new footprint reach
(`building.py:1530-1556`); published as boxes in level voxel coordinates,
those enumerate a bounded set of tile keys at each level (a 2048 position at
the 128 grid is 16 × 16 keys at level 0, 8 × 8 at level 1, and so on; a
replacement of many positions is the union). A cache indexed by
(collection, placement, ..., level, row, column) is touched only at those
keys: each held tile inside a box has its content generation stamped with
the landing's revision, and that is the whole update, proportional to the
tiles the landing touched and not to the cache. A request then carries the
current revision; an answer composed under revision r is valid for a key
whose last dirtying revision is at most r. A tile fetched after the landing
is stamped with the revision it was composed under, which the Viewer knows.
So the "content generation" can simply be "the revision at which this key
was last dirtied", kept per key, and it never requires walking the cache.
The two things the protocol needs beyond that are finding 3's gap rule and
the ordering sentence the record already promises (473-474): an answer
composed before a landing but arriving after it must be stamped with the
older revision so the stale check catches it.

**Still missing that would invalidate derivatives later**: the recipe
version and the level definition (finding 5); and, once absolute placement
exists, the calibration revision of the observation record must join the
assembled key beside the placement mode, or a re-calibration leaves kept
absolute tiles wrong. Say that now in one sentence so the key's shape does
not change twice.

### 5. Does the scheduler section match neuroglancer's behaviour?

I opened the sources again. Item by item against the record's list
(438-487):

- *Three tiers, admission by tier then priority*: correct. Tiers are
  visible, prefetch and recent (`chunk_manager/base.js:29-38`); the first
  two are heaps and the third a list (`backend.js:366-449`); a candidate is
  never evicted for one of lower tier, or of the same tier and no higher
  priority (`tryToFreeCapacity`, `backend.js:474-487`).
- *Composite priority, visible first, nearest centre first, coarser first*:
  correct. Priority is a base from visibility plus 10⁹ times the source's
  index in the visible-scale list minus the distance from the view centre
  (`sliceview/backend.js:62-63`, `:116-117`, `:139-150`;
  `visibility_priority/backend.js:37-42`). The scale list is built from the
  coarsest usable scale towards the finest (`sliceview/base.js:344-404`)
  and then reversed (`base.js:193`), so the coarsest has the highest index
  and the highest priority: coarser first, as the record says. The record
  asks the engine record to write the arithmetic and tie-break; it does not
  write them itself, which is fine at this level.
- *Prefetch driven by velocity, with a budget*: correct. A velocity
  estimator on the position feeds offsets with a probability from the
  error function; the budget is at most 32 chunks per direction, a 2-second
  horizon, a 0.05 probability cut-off and a velocity cap
  (`sliceview/backend.js:84-90`, `:128-130`, `:166-199`, `:353-415`);
  prefetch priority is scaled by 10¹³ (`base.js:60`) and can be switched
  off (`frontend.js:126`).
- *Item counts beside byte counts, four budgets*: correct on counts
  (`frontend.js:74-90`; `backend.js:488-515`); the fourth budget is compute,
  not decoding (finding 4).
- *A "how far" on every request*: correct. `requestedState` is graphics
  memory by default, or main memory, or worker memory
  (`backend.js:95-101`, `:147-153`, `:1013-1020`).
- *A fixed number in flight, counted in reads behind them*: correct in
  spirit. A download capacity per source queue level, with a chunk able to
  cost more than one slot (`backend.js:93`, `:197-208`, `:228`, `:588-595`).
- *Abort on pressure*: correct. A chunk not re-requested drops to the
  recent tier (`backend.js:1035-1058`), a queued one is removed
  (`backend.js:674-680`), and a download in flight is cancelled only when a
  higher-tier or higher-priority candidate needs its slot
  (`backend.js:809-846`, `:361-365`).
- *Priorities recomputed in one batch, throttled, maximum wins*: correct.
  A zero-delay batch (`backend.js:977-982`), the maximum tier and priority
  and the minimum "how far" per chunk (`backend.js:1013-1029`), and a
  200 ms throttle on graphics-memory changes (`backend.js:960-969`).
- *A time-sliced upload budget on the drawing thread*: correct, with a
  nuance. Pending deliveries are applied for at most 30 ms, then the rest
  waits 30 ms (`frontend.js:125`, `:137-172`); it is a slice with a pause,
  not tied to a frame, so "per frame" is our choice and a good one.
- *Deliveries carry buffer ownership; bytes back on request*: correct
  (`backend.js:778-808`; `frontend.js:321-326`).
- *Ordering between a revision bump and deliveries in flight*: neuroglancer
  offers a per-source "apply immediately" flag for order with other
  messages (`frontend.js:385-390`); the rule itself is ours to state.
- *Three kinds of nothing and one of failed*: the empty answer remembered
  until invalidation is correct (the adapter learned it,
  `neuroglancer-under/viewer.js:2605-2620`); the retry is ours (finding 4).
- *Needed-versus-available counters per row*: correct
  (`base.js:66-71`; `backend.js:920-955`; `sliceview/backend.js:157-161`,
  `:192-196`).
- *Sources memoised, tile objects pooled*: correct (`frontend.js:363-373`;
  `backend.js:237-261`).
- *Coarse standing in for fine*: neuroglancer draws every visible scale
  finest-first with a depth test so the finer wins
  (`sliceview/frontend.js:426-440`; `volume/renderlayer.js:406`); the
  record's "coarse rectangles first, finer over them" is the same result by
  another order and says so.
- *Decode pool*: correct. Zarr's zstd and blosc decoding go through the
  asynchronous computation pool (`datasource/zarr/codec/zstd/decode.js`,
  `.../blosc/decode.js` call `requestAsyncComputation`), lazily launched up
  to min(12, cores) workers (`async_computation/request.js:17-31`, `:58-88`),
  cancellable only while waiting (`request.js:68-81`). Because decoding
  happens inside `download()`, neuroglancer's download timer includes it
  (`backend.js:338-360`), which is what the phase-0 breakdown assumes
  (654-660).
- *Context loss*: a reload (`display_context.js:331-339`); see finding 10.
- *Pinned plane over budget*: the promotion loop stops when nothing can be
  evicted (`backend.js:474-487`, `:737-757`); the picture stays partial.

Nothing in the section contradicts the pinned source. Two items are
mislabelled as neuroglancer's (finding 4).

### 6. Are the gates measurable as written, with the harness after step 1?

Per gate, with the instrument that would measure it:

- **Phase 0**: server work from the composer's `read_ms`, `build_ms`,
  `encode_ms` (`compose.py:1039`, `:1091`, `:1416`); transfer from the
  ledger's per-request times (`data_server.py:63-149`); download-plus-decode
  from neuroglancer's statistics (`chunk_manager/frontend.js:276-289`;
  `backend.js:323-330`); hand-off, upload and draw by subtraction, as the
  record says (656-658). Measurable once the ten-step trace exists in the
  real-run door, which step 1 authorises.
- **Opening reads the register, never lists the positions folder**: a
  Viewer-side counter of directory listings, not the harness (finding 9).
- **A relink costs a fingerprint check**: the same counter over `stat`
  calls; the fingerprint is one `stat` (`manifest.py:439-454`).
- **A coarse tile is one read; the marker moves after every dirty piece is
  current**: a read counter beside `read_ms`; the Viewer's existing
  dirtying tests (`building.py:1530-1556`) and the synchronous rebuild rule
  (`record/coarse.py:234-286`) extended to bridge-written runs.
- **No request for an output tile without committed coverage**: the
  ledger's `missing` count, if the ledger can sit in front of the Viewer's
  route (finding 9); else a Viewer-side request log.
- **A new live position visible within 500 ms at p95**: the landing clock
  (`suite.py:897-936`) over many landings from `_does_it_keep_up`
  (`suite.py:939`), with the start event the marker's rename time and the
  finish read from the counters, not the photograph (finding 2). The record
  says the events are named (674-675) and does not name them.
- **First picture no slower, within tolerance, cold and warm**: the
  real-run door's clock plus the earlier design's useful-picture rule
  (`lazy-jpeg-pyramids-for-the-viewer.md:446-451`), which needs the
  coverage-bounded drawn share (`real_run.py:71-89`, `:120`); measurable
  after the adapter fix, since today the adapter draws an empty photograph
  for a bridge-written store (`viewer-delivery-implementation-plan-100-percent.md:134-144`).
- **Navigation p95 no worse; a settled pan or zoom within 500 ms**: the
  gestures exist (`drive.py:341-390`) and the clock does not resolve the
  bound (finding 2).
- **Requests fewer on sparse, no more on dense, bytes no more**: the ledger
  (`data_server.py:63-149`; `suite.py:1007-1040`), once the plates are
  named (finding 1).
- **Process memory 1 GiB over twenty repetitions, growth under a tenth or
  20 MiB**: no instrument. `drive.py` reads nothing about memory (I
  searched); it needs a browser-protocol metrics read per cycle. The cache's
  own accounting is a unit test in the engine. Without the first, the gate
  cannot be measured and a leak hides.
- **A landing dirties exactly its footprint, byte for byte; no stale tile
  reaches a measurement**: the engine's dirty-key set and cache contents
  compared before and after a scripted landing, a new counter on the
  measurement handle; the harness can then compare photographs of the
  footprint region (`suite.py:1143-1174` has the mask helpers).
- **Every panel state reaches the screen the same way**: the panel's own
  tests (`application/parts/canvas/viewer-panel-authority.test.js`, as
  Codex checked); the record rightly puts this at application level
  (694-698).
- **Opens our own data on complete fixtures**: the real-run door with the
  adapter fix; the fixture must be a bridge-written run of the mock
  instrument with channels, depth and time, which does not exist yet as a
  fixture and should be written in step 1.
- **The visible-channel fixture within the gates**: unmeasurable until the
  count is stated (finding 1).

So: two gates cannot be measured with the harness even after step 1 as
written (process memory; the 500 ms bounds at their stated precision),
three are measured on the Viewer's side and should say so, and three point
at unnamed fixtures. None of this reopens the gates' substance.

### 7. Are the numbers and their cases right?

Yes, with one arithmetic note. Fields of 512 voxels, `uint16`, one channel,
one plane, one moment, chunks of 128, levels 512 down to 8: seven levels,
16 + 4 + 1 + 1 + 1 + 1 + 1 = 25 chunk files and eight descriptions, 33 per
position, 330,000 for the plate; bytes 512² × 2 × 4/3 ≈ 0.70 MB per
position, 6.5 GiB. Fields of 2048, three channels: nine levels,
256 + 64 + 16 + 4 + 5 × 1 = 345 chunks per channel, 1,035 plus ten
descriptions, 10.45 million files; bytes 2048² × 2 × 3 × 4/3 ≈ 33.5 MB per
position, 312 GiB. The levels with more than one chunk are the finest four
and the five coarser are one file each (354-355): correct. After sharding
levels 0 to 3 as one shard per level per channel, keeping level 4 as one
chunk per channel and dropping the sub-128 levels: 12 + 3 = 15 chunk files
plus six descriptions, about 21 per position, about 210,000 for the plate,
so "about 200,000" (375) holds. Kept levels for the 2048 plate: a side of
204,800 voxels, one per cent of the area from level 4, pieces of 512 give
625 + 169 + 49 + 16 + 4 = 863 per channel-plane, 2,589 for three channels,
each 512 KiB uncompressed, 1.26 GiB: "about 2,600" and "about 1.3 GiB"
(394-395) hold. One coarsest piece covers 64 × 64 = 4,096 positions:
"four thousand" (391) holds. Warming: 150,000 reads by the position-once
count, 200,000 by the piece-footprint count (finding 10); at a few
milliseconds per file open on a share that is twelve to thirty minutes,
so "tens of minutes by estimate" (393-394) holds and is labelled. The
constants: chunk 128 (`application/parts/storage/zarr_positions.py:54`),
smallest copy 8 (`:85`; `zmart_storage/positions.py:131-166`), one plane
per chunk (`zmart_storage/canvas.py:2136-2139`), piece 512
(`zmart_viewer/compose.py:659`), one per cent (`compose.py:680`,
`:1143-1165`), no shard from the bridge (`zarr_positions.py:163-177`),
full-size level only in the library (`canvas.py:2126-2131`).

### 8. What is still wrong?

False as written: nothing outright. Ours stated as neuroglancer's: the
retry with back-off and the decoding budget (finding 4). Over-attributed:
"exactly what the patch does today" (finding 8). Fact stated a little too
broadly: the re-scan refusal (finding 10). Hypotheses are labelled where
they should be (644-651), and the warm-read estimate says "by estimate".
What a biologist would not follow: four terms (finding 10); the glossary
otherwise works, and the scheduler list is now readable at the microscope.
In "Not taken", all four reasons hold: the conditional engine is the
owner's decision, stated with what is forgone; the absolute top slice is
refused with the flat-plate reason, which the writer's own docstring
supports (`zarr_positions.py:322-362`); the later milestones leave the
first engine and not the plan; the run-wide revision in the key was the
record's own error and is corrected.

## Is the record ready for the data-layer design?

It is. The inputs the data-layer record takes as settled are settled: the
three documents the bridge writes and when, the versioned extension with the
collection index, the frame's definition list with half-open plane
intervals, coverage as committed positions only, dirty boxes per revision
in the live-state document, the cost model with its inputs and guard, tile
sizes by level, sharding of every level with more than one chunk, the
single-file-levels decision hung off phase 0, the additive terminal state,
the re-scan rule and the (channel, kind) window key. What the data-layer
designer would still decide is small and belongs in that record anyway: the
coordinate convention and retention of dirty boxes and the gap rule
(finding 3), the tile size at lazily assembled middle levels, "level" as a
decimation exponent and a recipe version on assembled tiles (finding 5),
and the one wording that reads as a contradiction (finding 6). The gates
need three fixtures named and two instruments the record does not yet know
it lacks (findings 1, 2 and the memory read in question 6), all of which
are step-1 harness work the record already authorises in kind. I would not
hold the data-layer record for a fourth revision of this one; I would
carry these items into it and correct the two attributions in place.

## Paste-back: changes to take before or into the data-layer record

> Name the sparse plate, the dense plate and the visible-channel count in
> the gates, or name the document that fixes them and its commit. Say that
> the 500 ms bounds are read from the needed-versus-available counters or a
> named engine event, not from the photograph, and add that reader to the
> step-1 harness work with a browser-protocol memory read per trace cycle.
> State the dirty-box gap rule: boxes in level voxel coordinates, kept for a
> stated number of revisions in the live-state document, replayed by a
> viewer that missed some, and a full replace-never-drop when the range is
> gone. Label retry-with-back-off and the decoding budget as ours, and note
> that neuroglancer's decode queue is unbounded. Add a composition recipe
> version to the assembled tile's identity, define "level" as the
> decimation exponent from the profile's full resolution, and say that the
> calibration revision joins the assembled key when absolute placement is
> built. Say a collection is one or more run folders under one index, not
> "its own folder". Name where phase 0's repetitions, tolerances and
> budgets are frozen. Soften "exactly what the patch does today" to the
> first two sentences of the rule. Say the first three data-layer gates are
> counted on the Viewer's side and that the coverage gate needs the ledger
> in front of the Viewer's route or a Viewer-side request log. Say the
> re-scan refusal is per image name today. Gloss *half-open*,
> *least-recent-use*, *evicted* and *worker*.
