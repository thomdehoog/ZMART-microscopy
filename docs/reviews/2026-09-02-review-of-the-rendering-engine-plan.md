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
