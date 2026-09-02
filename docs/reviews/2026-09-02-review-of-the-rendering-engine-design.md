# Independent review of the rendering-engine design record

Date: 2026-09-02

Reviewed: `docs/design/own-rendering-engine-and-position-register.md` on
ZMART-microscopy branch `claude/viewer-delivery-to-100` at commit `5284da89`
(the record itself was last changed at `ab9f3f9f`, which is the commit the
brief names; the one commit after it adds only the brief). The ZMART Viewer was
read on its own `claude/viewer-delivery-to-100` at commit `9b67bf8`. Nothing on
either branch was modified except to add this file. Every "exists" or "does not
exist" claim below was checked by opening the file and is given with a line
number; where I could only reason rather than look, the sentence says so.

## Verdict

**Accept with changes.** The record's two central ideas are sound and are the
right order of work: a register of the acquisition written before the first
field lands, and a data layer that keeps the coarse levels and assembles the
fine ones. Most of what it says exists does exist. But the record is broader
than the evidence it rests on, and three things in it are not so much choices
to review as facts that turn out to be wrong or missing:

1. The stage height that the whole "one three-dimensional stage space" rests on
   is not written anywhere on disk today. The position writer sets every
   position's height to zero on purpose, and the capture records that hold the
   real height live only in the bridge's memory and are cleared at the next
   scan. The register must carry the height before any of the three slicing
   modes can be built, and the record does not say so.
2. The "absolute" placement mode re-creates, by design, the exact fault that
   the writer's zero height was introduced to cure: a flat plate scanned under
   a focus map lands its fields on two dozen different planes, and a one-voxel
   slice shows two or three of them. The record presents absolute placement as
   "how the picture is really laid out" and makes it mode one, without saying
   that for the commonest acquisition it shows almost nothing.
3. The Viewer already has a planned-ahead register. Its `record` package holds a
   sealed profile per acquisition type, a numbered layout of every planned
   position whether or not it has arrived, a commit event per arrival, and a
   small signed file that a reader can check with one `stat` call. The record
   asks, as its first open question, whether that manifest "fits or needs a
   variant". The evidence says it fits well, that what is missing is small
   (height in micrometres per plane, provenance, and a way to say a planned
   position will never come), and that the real work is teaching the bridge to
   write it.

Beyond those, the engine section borrows three-dimensional machinery (a brick
atlas with a lookup texture) that a two-dimensional tile engine does not need,
underestimates the one thing the harness actually measured neuroglancer to be
better at (fetching and scheduling off the drawing thread, not decoding), and
sets a "fewer bytes" gate that the current server makes almost impossible to
win because an empty piece already costs no bytes. The side view and the
projections each break a part of the contract the record says is carried
through unchanged. None of that is fatal; all of it should be corrected in the
record before the data-layer design is written, because the data-layer design
inherits every one of these assumptions.

I would also change the order of work in one respect: build the data layer
(register, coverage, kept coarse levels, dirty rectangles) behind the existing
`neuroglancer-under` option first and measure, and let the engine be authorised
by that measurement rather than by this record. The harness's own real-run
finding is that a plane change costs the same on both engines and the
difference is scheduling; if the data layer removes the folder scans and the
fan-in, the engine may not be the bottleneck that is left.

## What I read and how

- The record, the two prior-art notes, the 100% implementation plan, the
  earlier review of the migration, and the lazy-pyramid design.
- The code the record names, in both repositories, and a few files beside
  them that the claims depend on: the bridge's scan loop, the position
  writer, the storage writer's chunking, the Viewer's composer, its `record`
  package, its live-run registry and server, and the harness's results and
  contract documents.
- I ran nothing. This is a design review, and every number in the
  ten-thousand-position estimate is arithmetic from constants in the code,
  with the assumptions stated.

A note on the writing rule in `CLAUDE.md`: the record is mostly in full
sentences and is readable. A few terms arrive unexplained for a biologist:
*fan-in*, *sharding*, *atlas*, *decimated*, *dirty rectangle*, *alpha*,
*quad*, *indirection*, *K*. Each is used as if known. I gloss them where they
first appear below; the record should do the same.

## Findings, ordered by consequence

### 1. The height a position was taken at is not on disk, and the design needs it everywhere

**Facts.** `application/parts/storage/zarr_positions.py:322-362`,
`_the_corner_of`, returns a corner of `(0.0, y, x)`: the height is set to
nought for every position, and the docstring at lines 331-354 says this is
deliberate and is "the single most important line in this module for whether
an operator ever sees their scan". The capture record that holds the real
height (`z_um` on each plane) is kept in `_records` in the bridge's memory
(`application/framework/bridge.py:660`) and cleared at every scan start
(`bridge.py:232` and `:889`). Nothing writes the planned positions or their
heights to a file: the only run-level file the bridge publishes at scan start
is the channel contract, `zmart-acquisition.json`
(`application/parts/storage/acquisition_description.py:14`, `bridge.py:880-887`),
which holds channels and nothing about positions. The neuroglancer option
separately re-bases whatever height a store does carry to nought
(`viz_studio/options/neuroglancer-under/viewer.js:1089-1147`).

**What the record says.** "Every position sits at its own x, y, z corner from
the acquisition record" (line 40) and "Neuroglancer forced every store's height
to nought to get them on screen together; owning the space removes that trick"
(lines 47-49).

**Inference.** The first sentence has no source to draw from, and the second
names the wrong culprit: the trick is the writer's as much as the engine's, and
removing it means changing what the writer records, not what the engine
draws. The register is the right place for the height, per position and per
plane, in micrometres, and the store may go on saying nought for the sake of
the composed picture, which today lands tiles at their stored heights
(`zmart_viewer/compose.py:489-560`, `read_the_transfer`, takes the corner from
each store). The record must say which of the two carries the truth and how the
composer is told. Until it does, none of the three slicing modes has data.

### 2. Absolute placement re-creates the "overview never shows up" fault, and the kept coarse pyramid cannot serve two placements from one set of tiles

**Facts.** The writer's docstring (`zarr_positions.py:337-348`) records the
measurement: a flat six-well scan under a focus map composed into a stack
twenty-two planes deep with two or three fields per plane, and the operator saw
"two fields out of fifty-four, or none". The writer's z step for a single-plane
capture is 1 µm (`zarr_positions.py:313-319`), so under the record's voxel-edge
rule a flat field is drawn only when the view plane is within one micrometre of
its capture height.

**Inference.** The record's mode one, "absolute", draws exactly that picture:
a plate of ten thousand flat fields, each on its own plane, of which a slice
shows the few whose focus height happens to match. It is the honest geometry,
and it is nearly useless for the acquisition that matters most, unless the
default for a flat collection is a projection or a slab rather than a slice.
Today's arrangement, every position at nought, *is* the record's "table"
alignment; the record should say that table alignment is the current
behaviour and the default, and that absolute placement is the new mode.

The second half of this finding is about cost. The kept coarse levels are
composed tiles: one 512-voxel piece at a coarse level holds thousands of
positions already blended into one picture. Which positions appear in a given
coarse tile at a given depth depends on the placement mode: under table
alignment every flat field is on plane nought; under absolute placement they
are spread over the focus map; under a custom offset per stack they are
anywhere. So one set of kept tiles serves one mode. The record's "coarse levels
are kept and patched" (line 199) does not say for which placement, and a
custom per-stack offset cannot be precomputed at all. The honest options are:
keep the coarse levels in one canonical placement (plane index, which is table
alignment and what exists), serve the other placements at coarse zoom from
projections or not at all, or keep a second pyramid per mode and pay for it.
The data-layer record needs to choose.

### 3. The display contract has no key for a projection, and a label has no window to refuse

**Facts.** The one window authority the migration built is keyed per channel:
`viz_studio/options/windows.js` chooses the page's word, then the run's
declared window, then a measurement, then nothing, and the panel sends every
row's answer to the engine through `viewer.setChannel(index, { window })`
(`viz_studio/options/contract.md:56`; the 100% plan, "One authority for the
display window"). The panel measures every row as it goes up
(`application/parts/canvas/viewer-panel.js`, `measureEveryRow`, referenced at
line 1512). The contract's `setChannel` has no notion of what kind of picture
the channel is being drawn as, and no kind of row that is not a brightness
channel.

**What the record says.** A projection "is never drawn through a slice's
declared window. Its window is measured, per channel, per kind of projection"
(lines 72-75). Labels draw with "no brightness window" (line 37).

**Inference.** As the authority stands, the moment the operator switches a
channel from slice to maximum projection, the panel's row for that channel
still holds the slice's declared or measured window and will send it to the
engine on the next `setChannel`, and the engine will draw the projection
through it. That is a window applied to numbers it was not measured on, which
is precisely the fault the contract exists to prevent. The fix is not in the
engine: the authority's key must become (channel, kind of picture), with
"slice" the default kind, and the panel must show which kind its window
belongs to. For labels the panel needs a row kind that is never measured and
never given a window, or `measureEveryRow` will measure a segmentation as if it
were fluorescence and send the result. Both are small, and both are contract
changes that belong in the data-layer record, not the engine's.

### 4. The Viewer's record package is already a planned-ahead register; the record asks the wrong first question

**Facts.** In the Viewer:

- `zmart_viewer/record/model.py:696-750`, `AcquisitionProfile`: one sealed
  description per acquisition type, agreed before the run starts, holding
  frame shape, dtype, voxel size, levels, channel names and room along time.
- `model.py:1045-1120`, `PositionPlacement`: one planned tile with an
  `origin` axis map (which includes `z`; `building.py:1514-1527` reads the
  z, y, x of every planned position's corner in micrometres), a grid cell or
  none, and the analysis regions.
- `model.py:1250-1300`, `SceneLayoutRevision`: a numbered, never-edited
  snapshot of every planned position, with a `final` flag.
  `building.py:664` calls the layout's extent "every planned position,
  arrived or not". `record/coordinator.py:320-355` accepts either explicit
  places or grid cells and refuses a planned rectangle with a hole in it.
- `model.py:1400-1447`, `CommitEvent`: one record per arrival, with
  `position_generation` for a re-scan of the same position, `timepoint`,
  channels, levels and free `notes`; no field for the vendor files it came
  from.
- `record/manifest.py:1-58` and `:439-455`: an append-only history
  (`events.jsonl`), a small truth file (`signed.json`) replaced by rename, and
  a `fingerprint` that is one `stat` call and reads no bytes.
- `record/coarse.py:1-50`: the rule that a zoomed-out piece is rebuilt from
  committed positions only and republished in the same step as the position.
- `zmart_viewer/live.py:394-460` and `record/gateway.py:476-487`: a run is
  manifest-governed when `views/live/metadata` exists beside it, and the
  Viewer opens such a run from files alone.

In the microscopy repository, the bridge's route is different: the position
writer writes only the store (`zarr_positions.py:92-189`), and
`viewer_service.py` has the Viewer open the folder as an ordinary transfer,
re-opened at most every thirty seconds while it grows
(`application/parts/storage/viewer_service.py:71-92`). Opening a transfer
lists the folder and reads every store's description in a thread pool
(`compose.py:489-511`).

**Inference.** The record's "what already exists" paragraph (lines 185-187) is
true but undersells it. The Viewer's manifest is not merely "a way to open a
live run"; it is the register the record describes, minus four things: height
per plane in micrometres (the profile has voxel size and the placement has an
origin, so this is a question of what the bridge writes into `origin`, not of
schema), provenance of the vendor files (a `notes` field exists; a proper
field is a one-line addition), a way to say a planned position will never
arrive (see question 2 below), and positions of differing sizes within one
collection (the profile seals one frame shape; a collection whose targets
differ in size would need one profile per size, which the Viewer's own
docstring says is the intended answer). The first question in line is
therefore not "does it fit" but "what does the bridge have to write, and when",
and the answer is: the profile at scan start, a layout revision listing every
planned position with its stage corner including height, and a commit per
landing, exactly as `record/identity.py:60-95` describes.

### 5. The ten-thousand-position estimate: the first thing that breaks is the folder scan on a share, not the renderer

The record says ten thousand positions "is won or lost" in the data layer
(line 194). The numbers agree, and they say where.

**Assumptions, stated.** A flat overview of a plate: 10,000 positions laid out
100 by 100 with no gaps, each field 1024 by 1024 voxels of `uint16`, three
channels, one plane, one moment. Fields the size a Stellaris writes at a
common setting; the Viewer's own profiles mention 1152 and 2304 frames, so the
estimate is a little kind. A ten-plane focus stack per position is given as a
variant.

**Per position store, as `zarr_positions.py` writes it.** Chunks of 128 by 128
(`zarr_positions.py:54`), no sharding (the call at lines 163-177 passes no
`shard`; `zmart_storage/canvas.py:2130-2140` bundles only when asked, and only
the full-size level), and levels halving down to 8 voxels
(`zarr_positions.py:85`; `zmart_storage/positions.py:131-166`): for a 1024
field that is eight levels of 1024, 512, 256, 128, 64, 32, 16 and 8 voxels. One
plane of one channel takes 64 + 16 + 4 + 1 + 1 + 1 + 1 + 1 = 89 chunk files. With
three channels: 267 chunk files, plus nine description files, in about 130
folders (zarr version 3 files each chunk under `c/t/c/z/y/`), so roughly 400
directory entries per position. Uncompressed, one channel-plane is 2 MiB and
its pyramid adds a third: about 8 MiB per position for three channels.

**The plate.** About 2.8 million chunk files, 4 million directory entries, and
80 GiB before compression (perhaps 30 to 55 GB on disk after zstd, on
fluorescence), beside 60 GB of vendor TIFFs that are kept untouched. Note that
five of the eight levels of every position are single tiny files of a few
hundred bytes that exist only so that a coarse level has something to point
at: 150,000 such files on this plate. With a ten-plane stack: 27 million chunk
files.

**The composed picture the Viewer builds over it.** Pieces of 512 voxels
(`compose.py:660`), the same eight levels as the positions (`compose.py:512-520`
refuses tiles that disagree about their level count, so the picture has
exactly the positions' levels). The picture is 102,400 voxels square at level
0. Pieces per channel-plane per level: 40,000, 10,000, 2,500, 625, 169, 49, 16
and 4. The pinned share of one per cent (`compose.py:680`, `:1143-1165`) keeps
levels 4 to 7 (level 3 is 1.56 per cent of the voxels and is not kept): 238
pieces per channel-plane, 714 for three channels, about 375 MB in memory or,
baked, on disk. That is comfortably inside the ten-per-cent budget.

**Fan-in, which is the record's word for how many positions one piece
touches.** At level k a 512-piece covers 512 × 2^k full-size voxels, so it
touches 4^(k-1) positions: 1 at level 1, 4 at level 2, 16 at level 3, 64 at
level 4, 256, 1024 and 4096 at level 7. Composing one coarsest piece of one
channel means opening 4096 files of 8 by 8 voxels. Warming the four pinned
levels of one channel-plane is about 56,000 chunk reads; three channels,
170,000. On a local NVMe drive at a tenth of a millisecond per read that is
around twenty seconds; on a network share at five to ten milliseconds per file
open it is fifteen to thirty minutes. The Viewer's measured ladder agrees in
shape: the warm took 133 seconds at 8,281 positions and 270 seconds at 16,384
on four cores in a container (`docs/measured/MEASURED_the_ladder_of_surveys.md`,
"The definitive ladder").

**Where it breaks first.** Not in the renderer: one composed source is one
layer to neuroglancer, and the composer's per-piece cost is flat with survey
size (`compose.py:1-9`). It breaks in the folder scan. Every relink reads the
descriptions of every store, nine files each, so 90,000 reads for this plate,
repeated every thirty seconds while the scan grows
(`viewer_service.py:92`). On a share that single scan takes longer than the
interval. This is the cost the register removes, and it is the right first
target. Second is the file count itself: 2.8 million files (27 million for a
stack) is beyond what a Windows share or a backup tool handles gracefully,
which is what the Viewer's own sharding module says in its first paragraph
(`zmart_viewer/record/shardlink.py:8-14`). Third is the bridge's write rate:
about 400 directory entries per position on a share costs a second or more per
position in metadata alone, and a scan that lands a position a second falls
behind its own conversion.

**Register entries.** Ten thousand positions at a few hundred bytes each is
five to eight megabytes of JSON. That must never be read whole on every check;
the Viewer's fingerprint-then-tail-read design is the right shape. Coverage
per level should be derived from the register in memory (ten thousand
rectangles is nothing in a browser), not stored per level.

**Sharding, said precisely.** Sharding means bundling many small chunk files
into one large file with a table at the end. It is the answer for the
*position* stores, where the writer fills each level in one assignment
(`zarr_positions.py:184-188`) and so writes each shard once. It is the wrong
answer for the *kept coarse levels*, which are patched one piece at a time: the
Viewer's spike note measured that a partial write into a shard re-reads and
rewrites the whole shard, costing about half the shard per write, and says the
per-commit bake is unsharded on purpose for exactly this reason
(`docs/measured/NOTE_the_shard_is_written_once.md`, "The trap worth writing
down"). The record's single line "sharding for the file count" must be split
into those two statements.

### 6. What neuroglancer does that the record has not accounted for

**Facts.** The harness's one measurement on a real acquisition
(`viz_studio/options/RESULTS.md:66-79`) found a single plane change to cost
the same on neuroglancer and `viv-under` (3.0 s and 268 requests against 3.5 s
and 200), and a drag of twenty planes to cost 303 requests against 1266. Its
explanation: "Neuroglancer's queue drops work that has been superseded and its
fetching happens off the drawing thread; Viv sees every load through, on the
thread it draws with." The synthetic table is flagged stale and was taken in
software rendering (`RESULTS.md:22-27`); in it `viv-inside` (deck.gl) is "the
only column that is plainly and repeatedly slower" (`RESULTS.md:156-160`), and
the other two overlap. Neuroglancer's adapter is 2,713 lines, of which a large
part works around the engine's all-or-nothing invalidation
(`neuroglancer-under/viewer.js:2005-2100`, `:2605-2672`).

The Viewer answers a piece with no committed tiles, or an all-zero piece, with
no body at all: `compose.py:1386-1418` returns `None`, and the server sends an
empty not-found reply (`zmart_viewer/pieces.py:878-886`;
`zmart_viewer/server.py`, `_send_empty(HTTPStatus.NOT_FOUND)`). The engine
remembers empty pieces and does not ask again
(`neuroglancer-under/viewer.js:2612-2616`).

**Inference, on each of the four parts the brief names.**

- *Chunk scheduler.* The record has the important pieces (hold while the hand
  moves, cancel what scrolled away, coarse first, metered uploads). It lacks a
  priority order among what is wanted, which in neuroglancer is by distance
  from the view centre and by level, and it lacks a statement of how many
  requests are in flight at once. Both are small and both decide the feel.
- *Worker decoding.* The record's open question, "whether serving pre-decoded
  tiles from the Viewer removes the need for worker decoding at all"
  (lines 344-345), misreads the measurement. The measured win was the fetching
  and the scheduling being off the drawing thread, not the decoding; decoding
  a 512-by-512 `uint16` piece from zstd is well under a millisecond in a
  browser. Pre-decoded pieces would double the bytes over a share for no
  gain. Keep one worker that fetches, decodes and hands back a buffer from the
  start; adding it later means rewriting the cache's edges.
- *Texture management.* The record proposes "one large atlas texture cut into
  fixed-size slots, with a small lookup" (lines 235-238). In WebGL2 that is a
  texture array with one slot per layer, and it is the right shape for the
  GPU tier. But a lookup *texture* is three-dimensional machinery: a volume
  ray marcher needs the shader to find bricks by itself, whereas a
  two-dimensional tile engine draws each tile as its own small rectangle with
  its slot number as a uniform, and the lookup can stay in ordinary
  JavaScript. The record should say so, because a GPU-side lookup is real
  complexity that the first engine does not need. It should also say that a
  slot has one format, so `uint16` channels, `uint8` channels, 32-bit
  projection sums, and `uint32` labels are four texture arrays, not one, and
  that WebGL2 cannot tell the page how much graphics memory there is, so "the
  budget the cache was given" is a number somebody types.
- *Coordinate spaces.* The record dismisses these as a cost of neuroglancer's
  generality. Its own design has three placements, two directions, a
  per-collection placement choice and a per-position height: that is a
  coordinate-space system in all but name, and the side view is a change of
  basis. Simpler than rank-n transforms, yes; free, no. See finding 7.

**On the gates.** "Bytes fetched for the same navigation are fewer, because
empty tiles are never asked for" (lines 353-354) cannot be won by coverage
alone: an empty piece already costs a request and no bytes, and neuroglancer
does not ask twice. The gate should be "requests fewer, bytes no more". The
"first picture no slower" gate is largely a data-layer gate: with the same
server, the same pieces and a kept coarse level, either engine draws the first
picture at the speed the server answers.

**Is "at least as performant" achievable?** For the flat, top-down view over
one collection, plausibly yes, because the measured difference between engines
is scheduling and the domain-specific savings (no folder scans, no fan-in at
the coarse end, coverage-driven requests) are on the data side and benefit any
engine. That is also why I would gate the engine on a measurement made with
the new data layer under the existing option (see "What I would cut").

### 7. The side view breaks three things the record says are kept unchanged

**Facts.** The shared gesture module works in a view of `{ centre: { x, y },
zoom }` and hands a lent drag the pointer's place as stage `x, y`
(`viz_studio/options/gestures.js:87-108`, `:178-191`, `:222-241`). The canvas
projects and unprojects in two stage axes and every overlay (targets, marks,
the plan) is placed through it (`application/parts/canvas/viewer.js:518-525`,
`:1658-1668`). Dirty regions in the Viewer are sets of `(row, column)` pieces
per level (`zmart_viewer/building.py:1530-1556`; `compose.py:810-856`), that
is, rectangles across the specimen. Position chunks are one plane per chunk
(`zmart_storage/canvas.py:2138`).

**Inference.** In the side view the screen's vertical is z. The gesture module
would still report a drag as a change of `centre.y`; a mark drawn on the side
view through the canvas's `unproject` would be recorded at a stage `y` that is
really a height; and a landing's dirty rectangle in y and x says nothing about
which side-view tiles (in x and z) it touched. The record's "plugs into the
same module through `getView` and `setView` ... and adds no gestures of its
own" (lines 282-283) is true only if the view record grows a direction and the
canvas's overlays are hidden or re-projected in the side view. The record
should say that the side view changes the view contract and the invalidation
contract, and should add the cost estimate from finding 5: at fine levels a
side slice reads one row of every plane's chunk, so a 128-by-128 chunk is read
to use 128 voxels of it, and one screen row across a hundred-field plate is
thousands of reads.

### 8. The fan-in rule is the right question, but K depends on more than disk versus share, and the boundary must come from the plan

**Facts.** The pinned share rule (`compose.py:1143-1165`) keeps the coarsest
level and every level whose voxel count is at most one per cent of the full
level; it is blind to field size and to how sparse the plate is. The composer
already computes exactly what fan-in needs: which tiles fall in each piece at
each level (`compose.py:932-957`, `_tiles_in_each_piece`).

**Inference.** For the plate in finding 5 the two rules agree (both keep from
level 4, with K around 16 to 64). They diverge for small fields (a 256-voxel
field has fan-in 16 at level 1 and 64 at level 2, where the share rule still
waits until level 4) and for sparse plates (a plate of scattered wells has a
low maximum fan-in at levels the share rule would keep). So fan-in is the
better rule for latency, and the share rule remains the right rule for disk:
keep the union, and say so. K depends on, besides local disk versus share:
the chunk size at that level (below level 3 each position contributes several
files per piece), how many reads run in parallel, how many channels and planes
one frame needs (a projection multiplies by the plane count), and whether the
composer's block cache is warm. And K must be evaluated over the *planned*
positions in the register, as a maximum over tiles, or the boundary would move
while a scan lands and the kept levels would change under the operator.

On synchronous versus lagging patches: the Viewer's existing rule is
synchronous, a coarse piece is rebuilt and republished in the same step as the
position (`record/coarse.py:24-33`), and the display contract's "a landing
dirties exactly its footprint" gate assumes one revision is one consistent
picture. Keep it synchronous per landing. It is cheap: a landing touches one
piece per kept level per channel-plane, and patching a 512-piece in place is
milliseconds. Do it off the stage's critical path, which the bridge already
does for the conversion (`bridge.py:707-713`).

### 9. Smaller corrections to "facts stated as facts"

- "Sharded zarr version 3 stores, which the writer can already produce"
  (lines 211-212): `zmart_storage.canvas` can, for the full-size level only
  (`canvas.py:1277-1284`, `:2130-2140`); the bridge's position writer never
  asks for it (`zarr_positions.py:163-177`). Half true.
- "Neuroglancer forced every store's height to nought" (line 47): the writer
  does too, first (`zarr_positions.py:331-362`). See finding 1.
- "A readout under the pointer: stage x, y, z ... (none exists yet)"
  (lines 315-318): the readout already follows the pointer in stage x and y
  (`application/parts/canvas/viewer.js:865-877`). What is new is z and the
  pixel value.
- "Both [Viv and deck.gl] were measured and are slower than neuroglancer"
  (lines 19-20): `viv-inside` is plainly slower; `viv-under` overlaps on the
  stale table and matched neuroglancer on a single plane change on the real
  acquisition; the difference was in movement (`RESULTS.md:66-79`,
  `:156-160`). Fair as a conclusion, overstated as a fact.
- "Segmentation rows in the Viewer's config" (line 337): true
  (`zmart_viewer/library.py:500`, `server.py:1602`), but nothing on the
  operator page draws them and nothing in a bridge run produces them. A label
  layer is entirely new on the operator side.
- "The Viewer publishes only 'something changed'" (line 258): true for the
  event stream (`zmart_viewer/live.py:180-230`, `say_something_changed`); the
  live-state document does carry a per-source revision and the committed time
  ranges (`record/live_state.py:60-80`), which is a little more than
  "something changed" and is the right document to grow rectangles into.

The remaining "exists" claims I checked are true as written: the shared gesture
module with zoom anchored at the pointer and counted refusals
(`gestures.js:58-65`, `:222-241`, `:244-250`); the panel's depth and time
sliders with play buttons that step and wrap and hide when there is no axis
(`viewer-panel.js:365-455`, `:1418-1502`); the view held in micrometres and
carried across a change of engine (`canvas/viewer.js:441`, `:996`, `:1043`,
`:1628-1650`); `lookAt`, `project`, `unproject` and the lent drag; the pinned
share rule; the change event stream and revisioned live-state document
(`server.py:638`, `:660`, `:692-720`); per-piece validators (`server.py:528-589`);
byte-exact footprint knowledge in the composer and bake patcher
(`compose.py:55-93`, `building.py:1008-1048`, `:1530-1556`); and the
harness's synthesised coverage (`viz_studio/options/measure/data_server.py:185-208`).

## Answers to the eight questions

### 1. Is "at least as performant as neuroglancer" achievable in WebGL2 without the parts the record dismisses?

Plausibly, for the flat top-down view over a collection, and for the reasons
in finding 6: the measured difference between the two installed engines was
scheduling and off-thread fetching, not drawing, and the savings the record
counts on are on the data side. The record underestimates worker fetching
(it treats it as decoding and wonders whether pre-decoded pieces remove the
need), texture formats (one atlas cannot hold four kinds of number), request
prioritisation and concurrency, and the coordinate work its own three
placements and two directions imply. It overestimates what it needs from the
three-dimensional cache pattern: a lookup texture and shader-side
substitution are for ray marching, and a tile engine does that in JavaScript
with a rectangle per tile. It also sets a bytes gate it cannot win (empty
pieces already cost nothing) and should replace it with a request-count gate.

### 2. Does the register design hold up?

The shape holds up because it already exists in the Viewer (finding 4). The
answers to the four cases:

- *Planned and never lands.* The layout lists it; no commit names it; coverage
  is committed positions only. The engine should draw planned-but-absent
  ground as a distinct state ("expected", a faint outline) rather than as
  nothing, because "honest picture of what is still arriving" is the record's
  own promise (line 11). That needs a commit event kind for "will not arrive",
  which the model does not have (`model.py:1452`, `EVENT_TYPES`), or a final
  layout revision that drops the position. Add one or the other.
- *A scan stopped part way.* The bridge already announces the end of a scan
  whether finished or stopped (`bridge.py:718-722`, `viewer_service.a_scan_finished`).
  That announcement should also seal the layout as final with the arrived set,
  so a reader on another machine can tell "stopped after 3,000 of 10,000" from
  "still going".
- *A re-scan of the same type.* The bridge refuses it today because the
  position store already exists (the earlier review, finding 5). The Viewer's
  model has `position_generation` on a commit (`model.py:1429`) for exactly
  this; the bridge should either write the new generation or start a new
  collection instance under a new profile id. Either is fine; silently
  overwriting is not, and the record should say which.
- *Opened from another machine with no bridge.* Works by construction: the
  register is files beside the run, the Viewer opens a manifest-governed run
  from the files (`live.py:394-460`), and the fingerprint is a `stat`
  (`manifest.py:439-455`). Two cautions for a share: the fingerprint includes
  the inode, which some network filesystems do not keep stable, and
  rename-over-the-old is atomic on NTFS and SMB but a reader on a different
  machine may see the new file a little late. Neither is a design fault;
  both belong in the data-layer record as things to test on the real share.

### 3. Is the fan-in rule right?

Right question, incomplete rule: finding 8. Keep fan-in for latency and share
for disk, take the union, compute K from the plan not the arrivals, and patch
synchronously with each landing, off the stage's path.

### 4. Which slicing modes and projections cost more than the record admits?

- *Absolute placement* costs a data source that does not exist (finding 1)
  and, for a flat plate under a focus map, shows almost nothing in a slice
  (finding 2). It needs the height in the register and a projection or slab
  default for flat collections.
- *Aligned placement* is what exists (every position at nought is table
  alignment). "Table" and "ceiling" are well defined for stacks of different
  depths: relative depth d in micrometres, each stack's plane chosen by the
  voxel-edge rule at its own step, and stacks shorter than d simply absent at
  that depth, which is honest. The hidden cost is that the kept coarse
  pyramid is per placement (finding 2), and a custom offset per stack can
  never be precomputed.
- *The side view* costs the view and invalidation contracts (finding 7) as
  well as the reads the record does flag.
- *Projections.* Taken from a decimated level along z they are honest, and
  this is worth saying because the record wonders about it: the pyramid keeps
  every plane and halves only y and x (`canvas.py:2199-2206`;
  `zarr_positions.py:186-187`), so the maximum, sum or mean over z of the
  level-k image equals the level-k image of the same projection taken at full
  size. A mean over decimated voxels is a mean of the voxels that level keeps,
  which is what that level is. What is not honest: a sum over a custom range
  in aligned mode across stacks with different z steps (the number of planes
  in the range differs per stack, so the sum tracks plane density rather than
  signal; a mean is fair), and any projection whose range ends fall between
  planes (say whether the edge plane is in or out, by the voxel-edge rule).
  The cost the record does not state: a sum overflows `uint16` after a few
  planes, so sums need 32-bit storage and a 32-bit texture format, doubling
  bytes on disk and on the card, and a precomputed projection per position per
  channel per level per kind is three more pyramids.

### 5. Is the display contract carried through without a gap?

Following one channel: register (name, colour, key from
`zmart-acquisition.json`) to the tile cache (keyed by source, level, t, c, z,
row, column, revision) to the shader (window, colour, alpha as inputs). The
channel identity survives, because the tile key carries `c` and the shader
input is per channel. The gaps are the ones in finding 3: the projection has
no key in the window authority, so a slice's window can be applied to a
projection; a label row can be measured; and "coarse stands in for fine" is
safe only because the stand-in is the same channel at another level, which
should be stated as a rule so nobody later substitutes across channels.
Provisional versus settled follows the acquisition's liveness today
(`server.py`, the announce route, 100% plan section 3) and the record's
"projections of a whole stack ... change only when that position lands"
(lines 76-79) is consistent with it, provided a re-scan (new generation)
invalidates the precomputed projection through the revision key. The side
view invents no window but has no dirty regions (finding 7), so a landing
could leave a stale side-view tile on screen labelled as current: that is the
"provisional drawn as settled" case to guard.

### 6. Is the ten-thousand-position claim honest?

Honest in direction, silent on the numbers: finding 5 supplies them. The
register removes the folder scan (90,000 description reads per relink on this
plate), the kept coarse levels remove the fan-in at the coarse end (170,000
chunk reads to warm three channels), and sharding the position stores removes
most of 2.8 million files. What the record leaves out: sharding must not touch
the patched levels; five of eight levels per position are tiny files that
exist only to be pointed at, and the record should decide whether a position
still needs them once the coarse levels are kept (it does not, and dropping
them halves the file count again); and the bridge's conversion rate on a share
is the next wall after the scan.

### 7. What would you cut?

See the section below.

### 8. Are the facts stated as facts true?

Mostly. The wrong or half-true ones are in findings 1, 5 (sharding) and 9.

## What I would cut from the first engine, and what must not be cut

**Cut, to reach the gates sooner.**

- *The side view.* It changes two contracts and its fine-level cost is real;
  nothing in the gates needs it.
- *Absolute placement.* Until the register carries height and the composer has
  a placement mode, it has no data; and its default for a flat scan needs a
  decision first.
- *Custom per-stack offsets.* Cannot be precomputed and adds a control nobody
  has asked for yet.
- *Sum and mean projections.* They need 32-bit storage and a second texture
  format. Keep the maximum projection only, which fits `uint16` and is the one
  a microscopist reaches for.
- *Precomputed per-position projections.* Compute the maximum projection on
  demand from the position's own levels first and measure; precompute only if
  it is slow.
- *Labels.* No producer exists on the bridge side and the operator page has no
  label layer today. Keep the tile key and the texture-format decision open
  for `uint32`; do not write the shader yet.
- *The GPU-side lookup.* Draw a rectangle per tile with its slot as a
  uniform; the lookup lives in JavaScript.
- *OME-Zarr 0.4 as an engine concern.* The Viewer already reads it; the engine
  only ever sees the Viewer's pieces.
- *The navigation extras* (keyboard nudges, pinch, view in the address,
  screenshot, scale bar, double-click). Worthwhile, small, and not gates; do
  them after the numbers.

**Must not be cut, because leaving it out would have to be undone.**

- *Height per position and per plane in micrometres in the register*, even
  though the first engine draws with every position at nought. Adding it
  later means rewriting every register on disk.
- *Planned versus arrived as two states in the register*, with a way to say a
  planned position will never come.
- *Tiles keyed by revision*, and dirty regions published per revision as
  three-dimensional boxes (level, z range, row range, column range) even
  though the first engine uses only the y-x rectangle. Rectangles are what
  the side view would have to undo.
- *The window authority keyed by (channel, kind of picture)*, with slice the
  only kind at first. Adding the key later touches the panel, the Viewer's
  measure route and the engine at once.
- *A worker that fetches and decodes from the start.*
- *Texture arrays with an explicit format per array*, not one atlas.
- *The measurement handle* (`layersForMeasurement`, the current plane,
  pixel-exact placement) from the first commit, so the new option is
  measured by the same harness as the old.
- *The collection as the unit* of register, loading and panel heading.
- *The gesture module unchanged*, and therefore the flat view only.

**One re-ordering.** Build the data layer first, as the record says, but put
it under `neuroglancer-under` and run the gates before writing a line of the
engine. If the gates pass, the engine is a later project with a smaller
brief; if they fail, the measurement says which part of the engine to write.
That is the same discipline the lazy-pyramid review applied to the JPEG
engine, and it applies here for the same reason: the harness's own real-run
numbers put the cost in the data path.

## Paste-back: changes the record should take before any implementation starts

> Correct the record before the data-layer design is written. State that the
> position writer, not only neuroglancer, sets every height to nought, that no
> file on disk holds a position's capture height, and that the register must
> carry height per position and per plane in micrometres from its first
> version. Rename today's arrangement as the "table" alignment and the
> default, and demote absolute placement to a later mode that needs a
> projection or slab default for flat collections. Say that the kept coarse
> levels are kept in one canonical placement and which one. Replace the open
> question "does the Viewer's manifest fit" with a statement that the Viewer's
> `record` package is the register (profile, layout revision, commit event,
> signed truth file) and list the four additions: height, provenance, a
> "will not arrive" event or final layout, and one profile per frame shape.
> Split "sharding for the file count" into: shard the position stores, never
> the patched coarse levels. Add the plate arithmetic (files, bytes, reads,
> register size) and name the folder scan on a share as the first thing that
> breaks. Make the fan-in rule the union of fan-in and share, computed from the
> planned positions, with synchronous patching off the stage's path. In the
> engine section: keep a fetching-and-decoding worker from the start, describe
> the GPU tier as texture arrays with one format each and a JavaScript lookup,
> add request priority and concurrency, and change the bytes gate to a request
> gate. Key the window authority by (channel, kind of picture) and give labels
> a row kind that is never measured. Say that the side view changes the view
> and invalidation contracts and that dirty regions are published as boxes.
> Move the side view, absolute and custom placement, sum and mean projections,
> precomputed projections, labels and the navigation extras out of the first
> engine. Gate the engine itself on the data layer measured under
> `neuroglancer-under`. Gloss fan-in, sharding, atlas, decimation, dirty
> rectangle and alpha where they first appear.
