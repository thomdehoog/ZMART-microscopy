# Review of the detailed plan for the rendering engine and the register

Date: 2026-09-02. Reviewer: the internal reviewer, working from the brief in
`docs/design/own-rendering-engine-plan-review-prompt.md`. Nothing was
implemented and nothing outside this file was changed.

What was read, in place: ZMART-microscopy on `claude/viewer-delivery-to-100`
at `63befe91` (which includes `c287e8f3`, the commit that added the plan);
the ZMART Viewer on its own `claude/viewer-delivery-to-100` at `9b67bf8`;
neuroglancer 2.41.2 as pinned under `viz_studio/options/node_modules`. The
document under review is `docs/design/own-rendering-engine-detailed-plan.md`.
The design record it expands is
`docs/design/own-rendering-engine-and-position-register.md`, fourth revision.
The earlier design's ten-step trace is in
`docs/design/lazy-jpeg-pyramids-for-the-viewer.md`, lines 402 to 467.

Throughout, a sentence marked **Fact** is something I read in a file at a
line I name. A sentence marked **Inference** is my reading of what those
facts mean; it could be wrong, and the owner should weigh it as an opinion.

## Verdict

**Usable with changes**, as a basis for discussion. The plan reads the two
repositories carefully and nearly every claim it makes about the code is
true. Its weakness is in two places that matter most to the owner's
decisions. First, decision 3 (the bridge becomes a client of the Viewer's
publisher) is recommended with the largest consequences left unnamed, and
one of them is not a cost but a precondition: the publisher exists in two
diverged copies, one in each repository, and the plan does not say which one
the bridge would use. Second, one unnamed risk undermines all of phase 0 as
the plan would run it: the rig launches its browser with software rendering,
so a phase 0 taken through the rig on the microscope PC would time a
software renderer, not the graphics card the operator's window uses. Both
are fixable in the plan without changing its shape. The nine decisions are
mostly the right nine, but two of them (1 and 7) are not really the owner's
to decide, and two more (3 and 6) quietly change what the record settled and
should say so.

## Findings, in order of consequence

### 1. The rig's browser runs on software rendering, so phase 0 through the rig would not measure the graphics card

**Fact.** The driver launches Chromium with
`SOFTWARE_GL = ["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]`
(`viz_studio/options/measure/drive.py` line 52, used at lines 146 and 151).
SwiftShader is a renderer that runs on the processor instead of the graphics
card. The test fixture does the same (`viz_studio/tests/conftest.py` lines
319 to 326). The older script the plan borrows the cold guard from knows
this: its `--window` help text says that on Windows a real window "is the
only way the graphics card is used at all; headless reports..."
(`viz_studio/measure_a_run_of_positions.py` lines 513 to 514). The earlier
design asks phase 0 to record the "browser/PyWebView engine, WebView2 version,
GPU renderer" (`lazy-jpeg-pyramids-for-the-viewer.md` line 415).

**Inference.** The plan's items 1.4, 1.5 and 1.9 run the ten-step trace
through this driver on the microscope PC. Unless the driver gains a
real-window, real-GPU mode, the timings, the "browser residual" (upload and
drawing are exactly the parts a graphics card changes) and the graphics-process
memory would all describe a machine the operator never uses. The memory
reader of item 1.5 is worst affected: under SwiftShader there may be no
separate graphics process to read at all. This is a risk the plan does not
name, and it belongs in item 1.4's scope and in the protocol document as a
recorded fact about every result.

### 2. The publisher exists in two diverged copies, and decision 3 does not say which one the bridge would be a client of

**Fact.** The Viewer's record package is `zmart_viewer/record/` in the
Viewer repository. The microscopy repository carries its own copy as
`zmart_live/` (same file names: `coordinator.py`, `coarse.py`, `manifest.py`
and the rest). The two `coordinator.py` files differ by 690 diff lines, and
ten of the module files differ. The microscopy repository's tests and its
own measurement script import the copy, not the Viewer's:
`from zmart_live.coordinator import LivePublisher` in
`viz_studio/tests/test_live_publication_gateway.py` line 10,
`viz_studio/tests/test_the_composer_obeys_the_manifest.py` line 54, and
`viz_studio/building/measure_a_governed_run_at_scale.py` line 77. The bridge's
viewer service imports the Viewer proper: `from zmart_viewer import server`
(`application/parts/storage/viewer_service.py` line 122).

**Inference.** The plan's argument for decision 3 is "two pixel writers
would be two truths". As things stand there are already two copies of the
one writer, and a bridge that imports `zmart_live` would write a governed run
that the installed Viewer (`zmart_viewer.record`) reads with different code.
Decision 3 should therefore be stated as "the bridge imports the installed
Viewer's `zmart_viewer.record`, and `zmart_live` is retired or pinned as a
copy of it", or the reverse; either way it is a decision the plan must add,
and it is a precondition of item 3.1, not a detail of it. This also changes
the claim in step 2's "What exists": the publisher's "only live caller is the
Viewer's own replay route" is true for the Viewer's copy, and the microscopy
copy has callers of its own.

### 3. Decision 3 loses the channel identity the position writer carries today, and the plan does not say so

**Fact.** Today the bridge writes, at scan start, `zmart-acquisition.json`
into `positions/<type>/` (`application/framework/bridge.py` lines 882 to
887), and every position store gets a copy of that description under its own
`zmart` attributes: `acquisitionDisplaySchema`, `acquisitionType`,
`displayWindowSource` and the whole `channels` list
(`application/parts/storage/zarr_positions.py` lines 192 to 214). Each
channel in that list carries a stable `key`, its `index`, a `label`, an
optional `color`, `range`, `displayWindow` and `windowProvenance`
(`application/parts/storage/acquisition_description.py` lines 95 to 175).
The Viewer reads that list back from the store's attributes to build its rows
(`zmart_viewer/library.py` lines 372 to 400, `_channels_the_acquisition_named`),
and the viewer service turns those rows into what the operator page's engine
and panel are given, including `channelIndex`, `color` and a declared
`window` (`viewer_service.py` lines 352 to 434).

**Fact.** The Viewer's publisher takes channels as names only:
`channels: tuple[str, ...] | None` (`zmart_viewer/record/coordinator.py` line
203), the profile holds `channels: tuple[str, ...]` (`record/model.py` line
745), and the publisher's OME-Zarr writer describes a position with those
names (`coordinator.py` lines 705 to 711 calling `describe_the_position`).
That writer writes an `omero` block only when every channel has a display
window and otherwise omits the block (`record/omezarr.py` lines 354 to 390,
524 to 528); it writes no `zmart.channels` attribute at all (no such key
appears in `omezarr.py`). Colour for a bare name comes from a wavelength
table or is white (`record/model.py` lines 1697 to 1702).

**Inference.** A governed run written through the publisher, as the plan
proposes, would carry channel names but not the keys, colours, ranges and
window provenance the acquisition display contract gives the operator page
today. The record's "versioned extension" explicitly asks for "a reference to
the one acquisition display contract and, through it, the map from stable
channel key to array index, label, colour, valid range, window and window
state" (record, "The register", the "versioned extension" bullet), and the
plan's step 2 has no item for it. This is the concrete thing decision 3 costs
that the plan leaves out, and it is what the brief asks about by name. The
fix is one item in step 2 ("where the acquisition display contract lives in
a governed run and how the Viewer's rows are built from it") and a test in
3.1 that a three-colour mock run opens with three named, coloured rows.

### 4. Decision 3 changes the folder shape in ways the plan names only in passing, and several readers of today's shape would break

**Fact.** Today's shape is `<run>/positions/<type>/<type>_<label>.ome.zarr`
(`bridge.py` line 736, `zarr_positions.py` line 119). The publisher's shape is
`<folder>/data/survey.ome.zarr/<position_id>` for the pixels
(`coordinator.py` lines 486 to 508), `<folder>/views/live/live.ome.zarr` for
the linked picture (line 520), and `<folder>/views/live/metadata/` holding
`signed.json` and `events.jsonl` (`record/manifest.py` lines 87 to 89).

**Fact.** Readers of today's shape: the rig's external-run door looks for
`*.ome.zarr` under `positions/<type>/` (`real_run.py` lines 58 to 64) and
would find nothing under the publisher's shape; the viewer service counts
`*.ome.zarr` in the positions folder to decide when to relink
(`viewer_service.py` lines 316, 344); target detection and focus scoring read
the store path off `record["zarr"]` (`application/parts/microscope/detection.py`
lines 66 to 74, `focus_score.py` line 95).

**Inference.** Item 3.1 says the viewer service "opens the governed run
folder once and never relinks by counting stores", which covers one reader.
The rig's door (item 1.1) and the detection and focus readers are not
mentioned, and the plan does not say where the governed run folder itself
sits relative to `<run>/positions/<type>/` and `<run>/<type>/data/` (the
vendor files, `application/parts/storage/output.py` lines 79 to 86). Decision
4 places the collection index "one level up, at the experiment run's folder",
which presumes a governed run folder per collection instance under it, but
the name and place of that folder are never stated.

### 5. Today's "scan finished" signal is an HTTP announcement, and the lifecycle document of 2.3 either duplicates it or replaces it

**Fact.** When a scan ends, the bridge posts `/api/announce` with
`{"finished": <type>}` (`bridge.py` line 722, `viewer_service.py` lines 275
to 291). The Viewer keeps a set of finished acquisition names and uses it to
answer "settled" versus "provisional" (`zmart_viewer/server.py` lines 795 to
820). This is not on disk; a Viewer opened later from the files alone does not
know the scan ended.

**Inference.** The plan's 2.3 lifecycle document is the durable form of that
signal, which is right. The plan should say that the announcement route
either stays as a fast path with the document as truth, or goes; otherwise
step 3 ends with two ways of saying "finished" that can disagree.

### 6. The record's step 2 assumed the bridge's own writer would shard; decision 3 reopens that, and the plan should say it is a change

**Fact.** The record's "Order of work" step 2 includes "sharding of every
level with more than one chunk in the bridge's writer", and its data-layer
section says "the storage library can bundle a shard, but only the full-size
level, and the bridge's writer never asks". Today that is exactly so: the
storage library bundles only level 0 (`zmart_storage/canvas.py` lines 2128 to
2139, `if shard is not None and level == 0`), and the position writer never
passes `shard` (`zarr_positions.py` lines 163 to 177). The publisher writes
shards for every level (`coordinator.py` line 786).

**Inference.** So decision 3 is genuinely the owner's, and the plan is right
to raise it; but it replaces a settled item of the record (make the storage
library's writer shard every level) with a different one (drop that writer
for the bridge's positions). The plan presents it as a choice between two
equal routes; it should present it as a departure from the record's step 2,
with the storage-library route as the one the record wrote down.

### 7. Item 1.6's "done when" cannot fail as written

**Fact.** Item 1.6 defines the page side as "download and decode as
neuroglancer reports them, and the residual (hand-off, upload, draw) as one
labelled number", and its done-when as "a trace step's total equals the sum
of the parts plus the residual, within the tolerance".

**Inference.** If the residual is the total minus the measured parts, the
equation holds by construction. A completion condition that can fail would
be, for example: the server's own per-request time (request received to
response sent) agrees with the composer's timers within the tolerance, and
the page's download time for the same requests is no less than the server's
time. The record's phase-0 gate also lists "transfer" as its own part, and
nothing in 1.6 measures transfer separately from download-plus-decode; the
difference between the server's send time and the page's receive time is the
natural instrument, and it should be named.

### 8. Step nine of the trace, on today's path, is bounded below by the thirty-second relink

**Fact.** After the first position of a type, later landings only ring the
doorbell (`viewer_service.py` lines 250 to 272); the folder is linked again
only when the page asks for status and at least `A_PICTURE_MAY_STAND_FOR =
30.0` seconds have passed (lines 71 to 108, 294 to 326).

**Inference.** The plan's decision 9 recommends a live scan of one position
for step nine on the Leica. On today's path the landing-to-visible number
will be about thirty seconds by construction, plus a full reopen of the
composed picture. That is a fair baseline for the register to beat, and the
record says the 500 ms gate "cannot be attempted before the bridge writes the
register", but the protocol must say that phase 0's step nine measures the
relink path, or the result sentence will name the wrong layer.

### 9. Item 1.1 through the Viewer needs three things the plan does not list

**Fact.** The harness page asks its own server, not the data server, for
coverage: `fetch('/api/coverage?image=...')` at `viz_studio/options/harness/src/main.js`
lines 422 to 428, and it throws when no regions come back (lines 444 to 452).
The rig's server synthesises a whole-extent region only from a store it can
find in its own `data_dir` (`data_server.py` lines 363 to 402). The Viewer
serves stores at `/data/<number>/<name>/|zarr3:` addresses (`server.py` line
1522) and, opened on a folder of position stores, composes a scene into its
session's `scenes` folder (`zmart_viewer/loading.py` lines 98 to 125), so the
store the page must name is the scene's name, learned from `/api/config`. The
Viewer's server sends no cross-origin header of its own; the bridge adds one
by wrapping the handler (`viewer_service.py` lines 481 to 512).

**Inference.** So 1.1 has to: start the Viewer with the same cross-origin
shim; open the positions folder (not the run folder, if it is to match the
operator's path) and read the scene's address from the answer; and give the
page a coverage answer for a store the rig's server cannot see. The plan's
"falls back to unbounded" hides the third and says nothing of the first two.
"Medium" is still believable if these are written down.

### 10. Item 1.3's field is already findable

**Fact.** Neuroglancer 2.41.2 keeps, per render layer,
`LayerChunkProgressInfo` with `numVisibleChunksNeeded`,
`numVisibleChunksAvailable`, `numPrefetchChunksNeeded` and
`numPrefetchChunksAvailable` (`lib/chunk_manager/base.d.ts` lines 61 to 66),
and its own layer bar draws a progress bar from the visible pair
(`lib/ui/layer_bar.js` lines 381 to 394). The adapter already reaches into
the chunk queue manager (`viz_studio/options/neuroglancer-under/viewer.js`
line 2082) and already exposes per-row standing (lines 2492 to 2530).

**Inference.** Item 1.3 can name the field now rather than "find it in this
item". The one thing to check in the item is what "available" means for the
gate: whether it counts a chunk on the graphics card or one merely decoded.

### 11. The `zmart_live` copy also changes the claim about `coarse.py`

**Fact.** In the Viewer, nothing imports `zmart_viewer/record/coarse.py`
(searched the whole Viewer repository). In the microscopy copy,
`zmart_live/tests/browser/production/production_run.py` line 215 imports
`from zmart_live.coarse import CoarseChunk, contributors_to`.

**Inference.** The plan's claim is true of the Viewer and false of the copy.
Decision 7 is really a housekeeping note for whoever owns the record package,
not a decision that gates any step; it should move out of the nine.

### 12. Two risks in the risks section are misdescribed

**Fact.** The plan says "the data type and the plane count come from the
first capture today". The Leica job reports `sections` (its number of z
planes) before capture (`zmart_drivers/leica/.../readers/parsing.py` lines
180 to 192), and the adapter uses it to stamp plane heights
(`zmart_adapter.py` lines 1012 to 1030). I found no bit depth or data type in
the job's parsed settings.

**Inference.** The plane count is knowable at scan start; the data type may
not be. The risk should say so, and the record should decide whether a
profile may be sealed with the data type taken from the acquisition
configuration (the operator's job) rather than from the first file.

## Answers to the eight questions

### Question 1. Are the plan's claims about the code true?

- **The rig's external-run door opens one store through the rig's own file
  server, not a run through the Viewer.** True. `real_run.the_store_to_open`
  returns one store name (lines 40 to 68); `measure` opens it with the rig's
  own `drive.Harness`, which starts `make_measurement_server` over the folder
  (`drive.py` lines 109 to 114) and points the page's `data` parameter at
  itself (lines 196 to 199). `run.py` only forwards to `real_run.measure`
  (lines 112 to 126).
- **"Settled" is two byte-identical photographs 0.2 s apart.** True with a
  qualification. `settle()` returns after two consecutive equal comparisons,
  which is three photographs in a row with a 0.2 s sleep between each
  (`drive.py` lines 213 to 226). The floor is two sleeps plus three
  screenshots, roughly half a second, as the plan says.
- **The adapter's counters hold paints and let-goes but no
  needed-versus-available.** True. `counted` holds `overlayPaints`,
  `groundPaints`, `enginePaints`, `letGoes`, `lastAsked` (`viewer.js` lines
  306 to 308), incremented at 2673 and read at 2696 to 2698. Nothing reads
  neuroglancer's chunk progress.
- **No memory reader exists in the rig.** True. No memory, heap or process
  reading appears in `viz_studio/options/measure/*.py`; the only mention in
  `measure_a_run_of_positions.py` (line 382) is about the disk cache.
- **The ten-step trace exists only as a list.** True. It is the numbered
  list at `lazy-jpeg-pyramids-for-the-viewer.md` lines 402 to 416; nothing in
  the rig runs it.
- **No protocol document exists.** True. `docs/design/` holds no
  `phase-0-protocol.md`.
- **The composer keeps timers and a read counter that no route serves, and
  the server keeps no per-route counts.** True. `tile_reads` and the
  `read_ms`, `build_ms`, `encode_ms` costs live in `zmart_viewer/compose.py`
  (lines 756 to 760, 1011, 1039, 1091, 1416); no route in `server.py` serves
  them, and `server.py` holds no request counter. The governed picture's
  `accounting` in `building.py` (lines 748 to 759) is likewise unserved.
- **The record has one writer whose only live caller is the replay route.**
  True for the Viewer's copy with a qualification. `LivePublisher` is
  constructed in the Viewer only by `rehearsal.replay_the_dataset` (line
  200), reached from `/api/stores/replay` (`server.py` lines 923 to 924). The
  microscopy repository's tests and `measure_a_governed_run_at_scale.py`
  construct the diverged `zmart_live` copy (finding 2).
- **The bridge writes position stores through the storage library with no
  sharding and every height at nought.** True. `zarr_positions.py` calls
  `_declare_one` without `shard` (lines 163 to 177); the corner's z is `0.0`
  (lines 356 to 362); the recorded heights are replaced by one median step
  (lines 313 to 319).
- **`record/coarse.py` is imported by nothing.** True in the Viewer; false
  for the microscopy copy (finding 11).
- **The marker's reader checks the schema name and reads named fields, so an
  extra field passes.** True. `CommittedState.from_json` refuses a wrong
  `schema` (`manifest.py` lines 176 to 180) and reads `revision`,
  `layout_revision`, `run_id`, `by_store`, `updated_at` (lines 181 to 210);
  nothing refuses unknown keys. One note: the fingerprint is the marker's
  modification time, change time, size and inode (lines 439 to 455), so the
  copied marker will change the fingerprint and readers will re-read; that is
  what the plan wants.
- **The Leica adapter reports the frame size before capture.** True. It is
  in `get_state`'s `observed` as `frame_size` from the job's geometry
  (`zmart_adapter.py` lines 1149 to 1158, 1178), and the bridge reads it
  (`bridge.py` lines 342 to 367).
- **Neither instrument records a wall-clock time at a landing.** True with a
  qualification. The mock hard-codes `"t": 0` (`mock_driver.py` line 350).
  The Leica reads `t` from the saved image index and defaults to nought
  (`zmart_adapter.py` line 941), which is "not hard-coded but always nought
  today" rather than hard-coded. No wall-clock stamp is written by either;
  the mesoSPIM adapter, which the plan does not consider, does write
  `captured_at` (`mesospim_zmart_adapter.py` line 279).
- **The five-axis placement bug is pinned by a strict expected-failure
  test.** True. `@pytest.mark.xfail(strict=True, ...)` at
  `test_a_foreign_run_can_be_measured.py` lines 129 to 138 on
  `test_the_positions_the_microscopes_bridge_writes_are_drawn` (line 139),
  with its companion `..._can_be_measured` at line 90 passing.

Other claims checked in passing: the 864-field plate is real
(`application/a-whole-96-well-plate.spec.js` lines 65 and 95) and the mock's
frame is 256 pixels (`mock_driver.py` line 449); the live-state document does
carry per-source revision, layout revision and half-open committed time ranges
(`record/live_state.py` lines 39 to 80); the bake computes dirty pieces per
level (`building.py` lines 1530 to 1555), but per derive of the governed
picture rather than per landing, which the plan should say; the operator
page's engine is given `coverage: null` (`application/parts/canvas/viewer.js`
line 976); the storage library records coverage only in its canvas writer
(`zmart_storage/canvas.py` line 1123) and `_declare_one` records none; and
the bridge already refuses a channel-count mismatch with a sentence
(`bridge.py` lines 872 to 876), which is the pattern 2.1 wants to copy.

### Question 2. Are the nine decisions the right nine, and are the recommendations sound?

1. **Phase 0 through the Viewer.** Not the owner's to decide: the record's
   phase-0 gate is "over the existing Viewer and engine, with time broken
   down into server work (the composer's own build and encode timers)", which
   is only possible through the Viewer. The recommendation is right; the item
   is under-specified (finding 9). Keep it as a work item, drop it from the
   decisions.
2. **Which runs.** The owner's, and the recommendation is sound with two
   additions: the record's phase-0 gate asks for "a real run"; the dense mock
   is the engine gate's plate, so adding it to phase 0 is more than the record
   asked and should be said (it is cheap, and I would keep it). And the mock's
   256-pixel frame makes its plate unlike a Leica plate; the protocol should
   state that frame size or the mock should take a frame size.
3. **The bridge as a client of the publisher.** The owner's, and a departure
   from the record's step 2 (finding 6). The recommendation is defensible,
   but the plan leaves out: which copy of the publisher (finding 2); the
   channel identity and the acquisition display contract (finding 3); the
   folder shape and its other readers (finding 4); the terminal announcement
   (finding 5); the profile needing the data type before the first capture
   (finding 12); that the publisher refuses a volume whose (z, y, x) shape
   differs from the profile (`coordinator.py` lines 744 to 752) and refuses to
   reopen a run whose arrays disagree in time and channel room (lines 448 to
   470), so a scan whose job changes mid-way must start a new governed run;
   that a run whose whole-pixel origins do not land on the chunk grid gets no
   pointer-linked view and is served only through the governed picture
   (`rehearsal.py` lines 190 to 193, `coordinator.py` lines 1826 to 1832),
   which is the normal case for stage positions and means every read goes
   through the composer; and the viewer service's open-and-relink path, which
   today opens the positions folder and links again by counting stores
   (`viewer_service.py` lines 294 to 350) and would need to open the governed
   folder through `loading.live_run_view` (`loading.py` lines 60 to 68)
   instead. I would still decide for the publisher, on the strength of
   finding 6's evidence that the storage library shards only level 0, but only
   with the package question settled first.
4. **Where the documents live.** The owner's for the collection index; the
   observation and lifecycle documents' place is settled by the record
   ("under the governed run"). The recommendation is sound. Unnamed
   consequence: the experiment run folder today holds `positions/<type>/`
   and `<type>/data/`; the plan should draw the whole tree once.
5. **Accounting in the Viewer.** The record offers either a ledger in front
   or a Viewer-side log, so this is the owner's, and the recommendation is
   right. One consequence: the rig's ledger counts pieces and descriptions
   apart (`data_server.py` lines 57 to 60, 93 to 146); the Viewer's route must
   do the same or the "no request for an uncovered tile" gate cannot be
   counted.
6. **Memory per process.** The owner's, but it changes the record's wording
   ("read through the browser's own protocol") to "process ids through the
   protocol, resident memory through the operating system". I think the
   change is right, because the browser's protocol does not report the
   graphics process's memory (inference), but the plan should say it is a
   change. Two consequences unnamed: no process-reading library is in the
   repository's dependency files that I could find, and under the rig's
   software rendering there may be no graphics process to read (finding 1).
7. **`coarse.py`.** Not the owner's; a maintainer's note (finding 11).
8. **The protocol's numbers.** The owner's. Five repetitions per step is
   thin for a ninety-fifth percentile; the record's latency gates are at that
   percentile, and five samples cannot give one. Twenty for latency steps,
   five for the cold open, is a better proposal.
9. **Step nine on the Leica.** The owner's, and the recommendation is right;
   see finding 8 for what the number will mean.

Two decisions are missing from the nine: which publisher package the bridge
uses (finding 2), and whether the rig gains a real-GPU mode for phase 0
(finding 1).

### Question 3. Does step 1 deliver phase 0 as the record and its three promises require?

Against the record's "Order of work" step 1, item by item: the ten-step trace
in the door (1.4); the adapter fix (1.2); the breakdown on both sides (1.6);
the settled clock from counters (1.3); the memory reader (1.5, with the
qualification in decision 6); the read counter at the composer's storage
boundary (exists; served by 1.6); the ledger or Viewer-side log (1.6 and
decision 5); the protocol document (1.8); phase 0 itself (1.9). Every named
item has a work item.

Against the record's phase-0 "Gates" paragraph: server work, download plus
decode and the residual are in 1.6; "transfer" has no instrument (finding 7);
"on a real run" is 1.9; cold and warm is 1.4; local disk and share is 1.9;
the frozen protocol is 1.8; the one-sentence result is 1.9. So one gap:
transfer.

What step 1 adds beyond the record: 1.1 is implied by the record, not extra;
1.7 (the dense fixture) is the engine gate's plate brought forward, harmless
and useful, but not authorised by name. Nothing in step 1 builds the engine
or the data layer early. The 1.1 coverage fallback and the `/api/accounting`
route are harness instrumentation.

Does 1.1's through-the-Viewer mode change what phase 0 measures? No; it makes
phase 0 measure what the record describes. The existing door measures one
store through a plain file server, which the record never describes. The one
thing to insist on is that the through-the-Viewer mode opens the positions
folder the way the viewer service does, so step nine measures the operator's
actual relink path (finding 8).

The promises: promise 1 holds if 1.8 is committed before 1.9 and the run's
sentence cites that commit, which the plan says. Promise 2 is not touched by
step 1. Promise 3 is referenced in step 3's done-when.

### Question 4. Is each "done when" a test that can fail?

- 1.1: yes, weakly. "Same run opens both ways and the result records which
  way" can fail; but it should also assert the through-the-Viewer result has a
  server-side breakdown and the other does not.
- 1.2: yes. The strict expected-failure mark coming off is a real test.
- 1.3: yes, but the cross-check ("settles by counters within the
  photograph's time") passes whenever the counters are merely earlier; add
  "and the photograph taken at the counters' moment is the settled one".
- 1.4: no. "Runs end to end headless" passes when nothing crashes. It should
  assert every step recorded a time, requests and bytes above nought, and
  that step nine changed the picture.
- 1.5: no. "Twenty repetitions produce the growth number" is an assertion.
  A test that can fail: a deliberate leak (hold decoded arrays across
  repetitions) is reported as growth above the gate.
- 1.6: no, as written (finding 7).
- 1.7: has no done-when at all. Propose: the script writes a run of the
  stated size and the Viewer opens it with that many positions listed.
- 1.8: a process check ("committed before phase 0 runs"), acceptable.
- 1.9: the sentence and the table; acceptable as an outcome, not a test.
- Step 2: "reviewed once by two reviewers" is a process check; the list of
  numbers left to measurement is checkable.
- 3.1: real tests, good. 3.2 to 3.4: none stated. 3.5: "every gate holds",
  checkable if each gate has its counter.
- Step 4: stage-level done-whens are absent; only the step's is stated.

### Question 5. Is the sequence right?

- 1.4 depends on 1.2, which the table omits: the trace's stated done-when is
  on the mock bridge's run, a five-axis store the adapter cannot draw today.
  It also depends on 1.6 (it records the breakdown) and on 1.7 or some mock
  run; the table names only 1.1 and 1.3.
- 1.6's Viewer side has no dependency on 1.1 and can start now in the Viewer
  repository; its page side depends on 1.3's reach into neuroglancer. Split
  it.
- 1.8 depends on decisions 8 and 9 as well as on 1.4 to 1.7.
- 3.3 (the window key by kind) does not depend on 3.1 and could go with step
  1 or step 2's review.
- The claim that 1.2, 1.3, 1.5 and 1.7 can start now holds. 1.7 is nearly
  done already: `a-whole-96-well-plate.spec.js` drives the bridge to 864
  fields through `live-bridge.js`.
- Missing from the table: the package decision of finding 2 before 3.1, and
  the real-GPU mode of finding 1 before 1.9.

### Question 6. Are the sizes believable?

- 1.6: double. Two repositories, a new route with reset semantics, reaching
  neuroglancer's download and decode statistics (its
  `requestChunkStatistics` RPC, `base.d.ts` lines 55 to 56), and a tolerance
  test that can fail.
- 1.7: halve. The spec exists; the work is a command-line door and an output
  path.
- 1.4: large, not medium-to-large. "Zoom to one well" on a Leica run needs
  well coordinates the run does not carry, so the protocol has to state them
  per run, and ten gestures with cold and warm and the breakdown is a full
  week's work in one file that is 125 lines today.
- 3.1: double, and split. With findings 2 to 5 it touches the bridge, the
  viewer service, detection, focus scoring, the rig's door, the channel
  contract and tests in both repositories.
- 1.2, 1.3, 1.5, 2, 4.x: believable as stated, with 1.5 gaining the real-GPU
  question.

### Question 7. What does step 2 leave out?

Against the record's step 2: profile, layout, commits, observation and
lifecycle (2.1 to 2.3); the versioned extension and collection index (2.4,
but see below); the coordinate frame with half-open intervals (2.5);
coverage (2.6); dirty boxes (2.7); cost model, tile sizes, single-file levels
(2.8); sharding (2.9, now via the publisher, finding 6); terminal state
(2.3); re-scan by collection (2.4); the (channel, kind) key (2.10). Two of
the record's extension items are missing: the reference to the acquisition
display contract and the channel-key map (finding 3), and the schema
version. The record's one wording fix ("what the run has done so far") is
also not carried.

Against "Handing over": the retention count (2.7) and the z-step tolerance
(2.5) are named; the tile size at lazily assembled middle levels is covered
by 2.8's "tile sizes at every level"; the exact shape of the observation and
lifecycle documents is proposed in 2.2 and 2.3; **the numerical guard's
share is not named anywhere in step 2**. Add it to 2.8.

What the plan settles that the record left open: nothing improperly; 2.2 and
2.3 propose shapes, which is the data-layer record's job, and the plan calls
them proposals. What the plan reopens that the record settled: the writer
(finding 6), which it should acknowledge.

### Question 8. What is still wrong?

- False or over-stated: "two identical photographs" (three, two equal
  comparisons); "coarse.py is imported by nothing" (true for one copy);
  "only live caller is the replay route" (true for one copy); "the plane
  count comes from the first capture" (the Leica job reports `sections`).
- Hypotheses stated as fact: that the bridge can seal the profile at scan
  start (data type unknown from the job, finding 12); that "the publisher
  refuses the things the record must refuse" (it refuses shape and room
  mismatches, but it does not refuse a re-scan by collection; that is new
  code in 2.4).
- What a biologist would not follow: "the three kinds of nothing and one of
  failed" (4.1) and "the three identities" are the record's terms used
  without a gloss; "resettable per trace step by a POST" needs "a request
  that clears the counters"; "residual" is defined once in 1.6 and used in
  the risks without it. The decisions section is otherwise clear.
- In the risks section, "Two repositories" is a fact of life, not a risk;
  the real risk under it is the diverged copy (finding 2). Risks not named:
  software rendering in the rig (finding 1); the thirty-second relink
  dominating step nine (finding 8); five repetitions cannot give a
  ninety-fifth percentile (decision 8); the rig runs the Leica run's
  gestures without a plate layout (question 6).

## Which decisions I would take differently, and why

I would take decisions 1 and 7 out of the list: the first is settled by the
record's own definition of phase 0, the second is a maintainer's tidy-up. I
would add two: which copy of the publisher the bridge imports, with the other
retired (finding 2), and whether the rig gains a real-window, real-GPU mode
before phase 0 runs on the microscope PC (finding 1); I would answer the
first "the installed Viewer's package" and the second "yes, and the protocol
records the renderer". On decision 3 I agree with the recommendation, because
the storage library shards only its full-size level and the publisher shards
every level with a coarse rebuild in the same step, but I would not adopt it
until the plan states the channel-contract item, the folder tree, the
terminal announcement's fate and the readers that change (findings 3 to 5).
On decision 8 I would raise the repetitions for latency steps to twenty so
the ninety-fifth percentile the record asks for can be computed at all. On
decisions 2, 4, 5, 6 and 9 I agree, with the consequences named above
written into the plan.

## Question 9: every efficiency neuroglancer uses, and where we do better

Added after the brief gained its ninth question (commit `9fed45db`). Source
read: neuroglancer 2.41.2 under
`viz_studio/frontend/node_modules/neuroglancer/lib/`; every path below is
relative to that folder. The two copies of the package in the repository
(`viz_studio/frontend` and `viz_studio/options`) report the same version.
"The record" means the "The engine itself" section of the design record;
"the plan" means step 4 of the detailed plan. For each mechanism I say what
the source does, then whether the record and the plan **carry** it, **drop**
it with a stated reason, or **miss** it (neither carry nor explain).

### How neuroglancer is fast, mechanism by mechanism

**1. Three priority tiers, and eviction that respects them.** Fact: chunks
are `VISIBLE`, `PREFETCH` or `RECENT` (`chunk_manager/base.js` lines 29 to
39). The two ordered tiers are kept in pairing heaps and the recent tier in a
linked list used as least-recently-used (`chunk_manager/backend.js` lines 366
to 450). Room is freed only from a chunk of a lower tier, or of the same tier
with lower priority (`tryToFreeCapacity`, lines 474 to 487), so a visible
chunk is never evicted for a prefetch. Verdict: **carried**, in the record's
"three tiers, and admission by tier then priority" and in the plan's 4.1
("the tiers").

**2. A composite priority, and "the maximum wins".** Fact: a layer's
visibility decides the tier and a base priority
(`visibility_priority/backend.js` lines 37 to 41, with
`PREFETCH_PRIORITY_MULTIPLIER = 1e13` at `base.js` line 60); within a view,
priority is `BASE_PRIORITY = -1e12` plus `SCALE_PRIORITY_MULTIPLIER = 1e9`
times the source's index (coarser sources sit later in the list, so they come
first) minus the distance from the view centre to the chunk
(`sliceview/backend.js` lines 56 to 57 and 139 to 158). When two layers ask
for one chunk, the lower tier wins, then the higher priority
(`chunk_manager/backend.js` lines 1013 to 1027). Verdict: **carried**; the
record names "visible first, nearest the view centre first, coarser first"
and "the maximum winning where two rows want one tile", and leaves the
arithmetic to the engine record, which the plan's step 4 record item repeats.

**3. Prefetch from the view's velocity.** Fact: a `VelocityEstimator` keeps an
exponentially weighted mean and variance of the view's motion
(`util/velocity_estimation.js` lines 3 to 44). Per chunk axis, the estimator
is projected into chunk units, and the probability that the view reaches
chunk *i* within `PREFETCH_MS = 2000` ms is read off a normal distribution;
chunks are queued in the prefetch tier with that probability as priority
until it drops under `PREFETCH_PROBABILITY_CUTOFF = 0.05` or
`MAX_SINGLE_DIRECTION_PREFETCH_CHUNKS = 32` is reached, and a velocity above
`MAX_PREFETCH_VELOCITY` disables it on that axis (`sliceview/backend.js` lines
353 to 408). Prefetch also runs along the non-display axes (the sliders)
through `fixedPositionWithinChunk` (line 379). A global switch turns it off
(`chunk_manager/backend.js` line 590). Verdict: **carried** ("prefetch driven
by the view's velocity ... in the pan direction and along the sliders"), with
the budget left to the engine record. Inference: the record does not say
that prefetch is probabilistic rather than a fixed ring; the engine record
should choose one and say why, because a fixed ring on a sparse plate
prefetches empty ground.

**4. Budgets with item and byte counts.** Fact: every capacity is a pair of
limits (`chunk_manager/frontend.js` lines 74 to 90; `AvailableCapacity`,
`chunk_manager/backend.js` lines 488 to 514). The defaults are: graphics
memory 1,000,000 items and 1 GB; system memory 10,000,000 items and 2 GB;
downloads 100 items with no byte limit; computed chunks 128 items and 500 MB
(`data_management_context.js` lines 44 to 59). Verdict: **carried** ("item
counts beside byte counts on every budget"). Qualification: the record says
neuroglancer's decode pool "is bounded only by its worker count and queues
without limit"; that is true of the helper pool for blosc, zstd, JPEG and PNG
(`async_computation/request.js` lines 19 to 21 and 82 to 84: up to twelve
workers, an unbounded pending map), but neuroglancer does bound *computed
chunk sources* by the 128-item compute capacity. The record's "a bound on
decoding is ours" stands for the helper pool.

**5. A concurrent download limit and abort under pressure.** Fact: at most
100 downloads are in flight (the download capacity's item limit); a queued
chunk of higher tier or priority evicts a downloading chunk, whose
`AbortController` is aborted (`chunk_manager/backend.js` lines 339 to 365 and
809 to 868); a chunk no longer requested falls to the recent tier, and a
queued chunk in the recent tier is removed outright (lines 665 to 673 and
1035 to 1063). Two download queues exist so a source that depends on another
source's chunks cannot deadlock it (lines 236 to 246, 591 to 594). Verdict:
**carried** ("a fixed number of requests in flight", "abort on pressure",
with the in-flight download running to completion unless a higher-priority
tile needs its slot). The record's "counted in reads behind them" is an
addition of ours.

**6. Priorities recomputed in one batch, throttled.** Fact: a change in view
schedules one recomputation on a zero-delay timer (`chunk_manager/backend.js`
lines 977 to 983 and 999 to 1008); graphics-memory changes are throttled to
`LAYER_CHUNK_STATISTICS_INTERVAL = 200` ms (lines 920 and 960 to 968); the
visible set is recomputed only when the pixel size or the view changes
(`sliceview/base.js` lines 133 to 170) and the frontend debounces its own
visible-chunk refresh (`sliceview/frontend.js` line 267). Verdict:
**carried** for the batch ("priorities recomputed in one batch per view
change, throttled"); **missed** for draw-on-demand: neuroglancer redraws only
when something changed (`display_context.js` lines 89 to 91 and 370, on
`animationFrameDebounce`, `util/animation_frame_debounce.js` lines 17 to 34),
and neither the record nor the plan says the engine will do the same rather
than run a continuous loop. Small, but it decides idle power and the
"idle frame" row the harness already measures.

**7. "How far" a chunk is wanted, and reading its bytes back.** Fact: a
request names the state it needs, and the least demanding wins
(`chunk_manager/backend.js` line 1020); `SYSTEM_MEMORY_WORKER` keeps decoded
bytes in the worker without sending them (`base.js` line 20); a page can ask
for one chunk's bytes on demand through an RPC that raises the chunk's
priority to infinity (`sliceview/backend.js` lines 409 to 431). Verdict:
**carried** ("a 'how far' on every request"; "the page can ask for a tile's
bytes back").

**8. Chunk objects pooled, and statistics kept per state and tier.** Fact:
freed chunk objects are reused (`chunk_manager/backend.js` lines 237 to 285);
counts and bytes are kept per state, tier and memory kind in one array
(`base.js` lines 40 to 58; `backend.js` line 326) and per layer as
needed-versus-available for visible and prefetch chunks
(`sliceview/backend.js` lines 155 to 158 and 194 to 196; `frontend.js` lines
330 to 341). Verdict: **carried** ("tile objects pooled";
"needed-versus-available counters per row").

**9. Time-sliced application of deliveries on the drawing thread.** Fact:
pending chunk updates are applied until a 30 ms deadline, then the rest wait
`chunkUpdateDelay = 30` ms (`chunk_manager/frontend.js` lines 125 to 170).
Verdict: **carried** ("a time-sliced upload budget on the drawing thread, in
milliseconds per frame"). Qualification: neuroglancer's slice is by wall
clock per batch, not per drawn frame; the engine record should say which.

**10. Buffers transferred, not copied.** Fact: a chunk's `serialize` pushes
its `ArrayBuffer` onto the transfer list (`sliceview/volume/backend.js` lines
31 to 39), and every RPC posts with that list (`worker_rpc.js` lines 174 to
185; promise replies carry `transfers`, lines 54 to 70). Verdict: **carried**
("deliveries carry ownership of their buffers"; plan 4.2 "buffers handed over
with ownership").

**11. Fetch and decode off the drawing thread, in two layers of workers.**
Fact: the whole chunk manager runs in one worker (`chunk_worker.bundle.js`);
zarr chunks are downloaded and decoded there (`datasource/zarr/backend.js`
lines 54 to 96), and the heavy codecs are handed to a second pool of up to
`min(12, hardwareConcurrency)` helper workers with transfer
(`datasource/zarr/codec/blosc/decode.js` line 26, `zstd/decode.js` line 26;
`async_computation/request.js` lines 21 and 58 to 84). Verdict: **carried**
with a smaller starting point: the record begins with one fetch-and-decode
worker and grows to a pool if measured necessary; the plan's 4.2 says "the
worker". Inference: the Viewer's pieces are compressed, so the measurement
the record promises is the right way to settle it, but the protocol should
name the codec so the number means something.

**12. Chunks shared between layers over one source.** Fact: chunk sources
are memoised by constructor and options, so two layers over one store share
one source and its chunks (`chunk_manager/frontend.js` lines 357 to 377);
texture layouts and shaders are memoised on the graphics context
(`webgl/context.js` line 32). Verdict: **carried** ("sources memoised by a
stable key so two rows over one source share tiles").

**13. A chunk layout per slice orientation.** Fact: when a source offers
several chunk layouts, the one whose chunks have the largest slice area for
the current view matrix is chosen (`sliceview/base.js` lines 39 to 52, 92 to
116, 181 to 186); layouts are built near-isotropic or flat under a cap of
2^18 voxels per chunk (lines 199 to 290). Only sources that declare
alternatives benefit: the precomputed format does (`datasource/precomputed/frontend.js`
line 359), a zarr store gets one layout from its chunk shape
(`datasource/zarr/frontend.js` line 170). Verdict: **dropped with a reason**
for the first brief, which is a flat top view only; **missed** for step 5's
side view, where neither the record nor the plan says which layout the side
view reads. Inference: our chunks are one plane thick (`zarr_positions.py`
line 169 and the Viewer's pieces), so a side view over them is one read per
plane per column of pixels; the data-layer record should say whether a
second layout is written for the side view or the view accepts that cost.

**14. The level chosen from the screen's pixel size.** Fact: the finest
level whose voxel is no smaller than 1.1 times the screen pixel times a
per-layer render-scale target is chosen, and every coarser level is kept in
the visible list as a fallback, coarsest first (`sliceview/base.js` lines 344
to 410, `renderScaleTarget` at `sliceview/renderlayer.js` lines 32 to 33).
Verdict: **carried** in outline ("level of detail from the zoom against each
level's voxel size in micrometres"). Two things neither the record nor the
plan states: the 1.1 margin, and that the whole coarser chain is requested
for every view. Inference: on a composed picture the chain is cheap; on ten
thousand position stores opened as separate sources it is not, which is one
more reason the engine must read composed pieces, and a reason our lookup
can bound the chain (see below).

**15. Coarse standing in for fine, by draw order and the depth test.** Fact:
the visible sources are reversed to finest-first (`sliceview/base.js` line
191) and drawn in that order (`sliceview/volume/renderlayer.js` line 406)
with the depth test on and `LESS` (`sliceview/frontend.js` lines 433 to 436),
so a coarser chunk drawn later cannot overwrite a finer one already drawn.
Verdict: **carried** ("coarse standing in for fine done by drawing coarse
rectangles first and finer ones over them, within one channel"); the order is
reversed but the effect is the same. The engine record should pick one,
because the depth-test way costs nothing per pixel and the paint-over way
costs overdraw.

**16. Adaptive downsampling from the measured frame rate.** Fact: a
`FramerateMonitor` times frames with `EXT_disjoint_timer_query_webgl2`
(`util/framerate.js` lines 8 to 44) and a downsampling calculator lowers the
render resolution during continuous camera motion, but only in the
perspective (three-dimensional) panel and only for volume rendering
(`perspective_view/panel.js` lines 215 to 227 and 890 to 899). The slice view
has no such mechanism; its only knob is the render-scale target. Verdict:
**missed**, and rightly not needed before step 6; the record's step 6 should
list it.

**17. A texture per chunk, and a shared fill-value texture.** Fact: each
chunk gets its own texture on upload and frees it on eviction
(`sliceview/single_texture_chunk_format.js` lines 78 to 90); texture layouts
are memoised per chunk shape (`sliceview/uncompressed_chunk_format.js` lines
70, 99, 206); an absent chunk draws from one shared fill-value texture (lines
253 to 275). Verdict: **carried** ("a texture per tile as neuroglancer does
or slots in a texture array, decided by measurement"; the fill value is our
"asked and empty"). The plan's 4.3 "texture pools by format" is the record's
"pools by tile dimensions and internal format".

**18. The shader cache, with window and colour as uniforms.** Fact: shaders
are compiled once per (chunk format, channel count, histogram setting) and
cached on the graphics context (`webgl/dynamic_shader.js` lines 31 to 57;
`sliceview/compressed_segmentation/chunk_format.js` lines 77 to 83;
`sliceview/volume/renderlayer.js` lines 312 and 419 to 428); brightness and
colour are uniforms, never a recompile. Verdict: **carried implicitly** ("the
window and its state, colour and opacity are drawing inputs, not identity, so
changing brightness never fetches"; plan 4.3 "the window and colour as
drawing inputs"); neither says "compiled once per format", which is the part
that keeps a channel toggle under a frame.

**19. Compressed segmentation for labels.** Fact: label chunks can be stored
block-wise compressed and decoded in the shader from an unsigned integer
texture (`sliceview/compressed_segmentation/chunk_format.js` lines 66 to 110;
`decode_common.js` lines 17 to 134), encoded in a helper worker
(`async_computation/encode_compressed_segmentation.js`). Verdict: **missed**
for step 5: the record's label milestone names "a 32-bit integer texture
format" and says nothing about compression; the plan's step 5 repeats it.
Inference: our label maps are per-position and small, so plain 32-bit
textures are probably enough, but the step-5 record should say so with a
number.

**20. Range requests and a cached shard index.** Fact: a sharded zarr array
reads its index once per shard as a byte range at the start or end of the
file, caches it as a chunk in the system-memory budget
(`datasource/zarr/codec/sharding_indexed/decode.js` lines 28 to 63;
`chunk_manager/generic_file_source.js` lines 15 to 64), then reads each
sub-chunk by its own range (lines 65 to 118); HTTP ranges are `Range:
bytes=a-b` with Chrome's cache turned off for ranged reads
(`kvstore/http/read.js` lines 20 to 24). Verdict: **dropped with a reason**:
the engine fetches composed pieces from the Viewer's routes and never opens a
shard itself; the Viewer reads shards on the server side and keeps its own
remembered shard tables (`zmart_viewer/record/shardlink.py` lines 413 to
431). Carried, then, on the other side of the wire.

**21. Whole-source invalidation, and the patch this repository carries.**
Fact: stock invalidation re-queues every chunk of a source and tells the
page to drop its whole copy (`chunk_manager/frontend.js` lines 214 to 217);
the repository's patch adds named-chunk refresh with grouped delivery and a
2,000 ms flush, and named-chunk invalidation (`chunk_manager/backend.js`
lines 1128 to 1215). Verdict: **carried** ("replace, never drop"; the group
timeout; the dirty-box protocol). This is the mechanism our engine improves
on most directly.

**22. Failed stays failed.** Fact: a failed chunk keeps `FAILED` until the
source is invalidated, and a request for it throws the stored error
(`sliceview/backend.js` lines 419 to 421). Verdict: **carried and improved**
(the record's retry with back-off, a limit and a visible permanent state).

**23. Histograms on the graphics card.** Fact: the slice view renders into an
offscreen framebuffer with extra colour attachments and computes data
histograms there per frame (`sliceview/frontend.js` lines 164 to 169 and 383
to 396). Verdict: **dropped with a reason** that the record gives elsewhere:
the window authority measures once, server-side, through the Viewer's
measure route, so the engine has no per-frame histogram. Not an efficiency
we need.

### Where our own lookup does better than neuroglancer on our data

All of the following are inferences from the source above and the record.

- **The register instead of listing.** Neuroglancer has no notion of a run;
  it opens each store by reading its description, and the Viewer today lists
  the positions folder on every relink (`viewer_service.py` lines 294 to
  350; the record's "where it breaks first"). With the register, opening is
  one profile, one layout and one marker; there is nothing in neuroglancer to
  match because it never had the problem.
- **Coverage from the register instead of empty requests.** Neuroglancer asks
  for every chunk that intersects the view (`sliceview/backend.js` lines 143
  to 158) and learns emptiness one 404 at a time, after which the fill-value
  texture stands in (`uncompressed_chunk_format.js` lines 253 to 275). Our
  engine knows from coverage which tiles exist at each level before asking,
  which is the "never asked" kind of nothing and the sparse-plate request
  gate. The adapter today already bounds the view to coverage
  (`viz_studio/options/neuroglancer-under/viewer.js` lines 2649 to 2654) but
  cannot stop neuroglancer asking inside the bound.
- **The fan-in rule and precomputed coarse levels.** Neuroglancer's coarse
  fallback chain (mechanism 14) requests every coarser level of every source
  for every view; over a composed picture that is a few pieces, over many
  position stores it is thousands. Our lookup knows, per tile, how many
  positions it touches, so the data layer keeps a level when its fan-in makes
  lazy assembly too slow and the engine bounds the fallback chain to the next
  kept level rather than walking to the coarsest. Neuroglancer has no cost
  model; the level is chosen by pixel size alone.
- **Dirty boxes instead of source-wide invalidation.** Mechanism 21: stock
  neuroglancer drops the whole source; the patch names chunks but the page
  still has to be told "something changed" and re-read the live state. The
  dirty-box protocol makes the invalidation exact per revision and lets a
  page that missed revisions catch up by range.
- **Identity that includes generation and revision.** Neuroglancer's chunk
  key is a grid position within a source; nothing in the key says which
  generation of a position or which run revision produced it, which is why a
  stale delivery cannot be told from a fresh one (the record's "ordering
  between a revision bump and deliveries already in flight"). Our three
  identities carry that, so a late delivery is discarded by comparison, not
  by luck.
- **A bounded decode queue.** Mechanism 4: the helper pool's pending map is
  unbounded; the record's bound on decoding with back-pressure is a genuine
  improvement on a fast pan.
- **Retry with back-off.** Mechanism 22: a transient share failure is
  permanent to neuroglancer until a source-wide invalidation, which on a
  network share is the common failure. Ours retries with a limit.
- **Coverage-aware prefetch.** Mechanism 3: neuroglancer's prefetch is
  probabilistic in chunk space and does not know which chunks exist; ours
  can skip uncovered ground and spend the budget on chunks that will draw.
- **Per-source alpha and a coverage mask** are things neuroglancer can do
  per layer and the record wants per source and channel; they are features,
  not efficiencies, and cost a little per pixel; the engine gate on four
  channels covers that.
- **What neuroglancer does that the literature adds and we do not need
  yet.** Tile-based progressive loading with a fixed ring and a two-level
  cache (the napari prior-art note in `docs/design/prior-art-napari-progressive-loading.md`)
  is what neuroglancer already does better with its velocity model; the
  three-dimensional prior art (`prior-art-larger-than-memory-3d-rendering.md`)
  belongs to step 6, where mechanism 16 belongs too.

### What this adds to the earlier answers

Nothing in step 4 of the plan builds a mechanism neuroglancer lacks in a way
that would slow the first brief; the first brief is a strict subset of what
neuroglancer does for a flat view, plus the register-driven lookup. The gaps
worth writing into the plan are small and specific: draw-on-demand
(mechanism 6), the 1.1 level margin and the bounded fallback chain
(mechanism 14), which of the two coarse-under-fine methods (mechanism 15),
"compiled once per format" (mechanism 18), and, for step 5 and step 6, the
side-view layout (mechanism 13), compressed labels (mechanism 19) and
frame-rate adaptive downsampling (mechanism 16).

## Paste-back

- Add a decision: the bridge imports `zmart_viewer.record` (the installed
  Viewer's package) and `zmart_live` is retired or pinned as a copy; make it
  a precondition of 3.1.
- Add a risk and a work item: `drive.py` launches Chromium with SwiftShader
  (line 52); phase 0 needs a real-window, real-GPU mode and the protocol
  records the renderer.
- Add to step 2: the acquisition display contract in a governed run (keys,
  colours, ranges, window provenance) and how the Viewer's rows are built
  from it; the schema version; the numerical guard's share in 2.8.
- Name decision 3's costs: the folder tree; the rig's door, detection and
  focus scoring reading `record["zarr"]`; the `/api/announce {"finished"}`
  signal versus the lifecycle document; the publisher's shape and room
  refusals; no pointer-linked view off the chunk grid; the data type at
  profile sealing (the plane count is knowable from the Leica job).
- Rewrite 1.6's done-when so it can fail, and add a transfer instrument
  (server send time against page receive time).
- Fix the dependency table: 1.4 depends on 1.2, 1.6 and a mock run; split
  1.6 into a Viewer side that can start now and a page side after 1.3; 3.3
  can go earlier.
- Name the field for 1.3: `LayerChunkProgressInfo.numVisibleChunksNeeded`
  and `numVisibleChunksAvailable`.
- State that phase 0's step nine on today's path measures the thirty-second
  relink, and that five repetitions cannot give a ninety-fifth percentile.
- Move decisions 1 and 7 out of the list; say that decision 3 departs from
  the record's "sharding in the bridge's writer" and that decision 6 changes
  the record's "through the browser's own protocol".
- Correct: "three photographs, two equal comparisons"; `coarse.py` and the
  publisher's callers are described per copy; the mesoSPIM adapter does
  stamp `captured_at`.
- From question 9: state that the engine draws on demand and recomputes
  the visible set once per frame; state the level-choice margin (neuroglancer
  uses 1.1) and bound the coarse fallback chain to the next kept level;
  choose between depth-test and paint-over for coarse-under-fine; say
  shaders are compiled once per format with window and colour as uniforms;
  say prefetch is coverage-aware and whether it is probabilistic or a fixed
  ring.
- From question 9, for steps 5 and 6: name the chunk layout the side view
  reads; say whether labels use neuroglancer's compressed segmentation or
  plain 32-bit textures, with a size; list frame-rate adaptive downsampling
  under step 6.
- Correct the record's note on neuroglancer's decode bound: the helper pool
  for blosc, zstd, JPEG and PNG is unbounded, but computed chunk sources are
  bounded by a 128-item compute capacity.
