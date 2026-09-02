# A rendering engine of our own, and the register that feeds it

Date: 2026-09-02, revised the same day after two independent reviews:
`docs/reviews/2026-09-02-review-of-the-rendering-engine-design.md` (verdict:
accept with changes) and
`docs/reviews/2026-09-02-review-of-the-rendering-engine-design-by-codex.md`
(verdict: rethink). Status: high-level design for discussion. Nothing here
is implemented. This records the choices made in conversation, corrected
where a review showed a stated fact to be wrong, and the decisions taken on
every finding, including the ones not taken and why.

A few words used below, said once: a *tile* is one small square of one
level of the picture, the unit that is fetched, cached and drawn; *fan-in*
is how many positions one tile touches; *sharding* is bundling many small
chunk files into one large file with a table at the end; *decimation* is
the way our pyramids are made, keeping every second voxel along height and
width and every plane along depth; a *dirty region* is the part of the
picture a landing changed; *alpha* is how see-through a thing is drawn; a
*collection* is one acquisition type of one run, such as the overview.

## What we want, in one paragraph

A drawing engine that is ours, fitted to microscope acquisitions: many
thousands of positions placed anywhere on the stage, any number of channels,
depth and time, transparency where the picture is sparse, labels drawn as
labels, and an honest picture of what is still arriving. It should be at least
as fast as neuroglancer on our own data, and it should get there by owning the
lookup: which positions a tile touches, which pyramid level answers it, and
what is precomputed rather than assembled on the fly.

## The one decision that was contested, and how it stands

Both reviews point out that the earlier design record
(`lazy-jpeg-pyramids-for-the-viewer.md`, phase 1) says a new renderer is
considered only after the phase-0 measurement on the microscope PC shows the
installed engines cannot meet the bound, and that this measurement has not
been run. Codex's verdict rests on that: "rethink", make the engine
conditional again.

The decision, as the project's owner made it and as it is kept here: the
engine is built. The reasons are not only speed. It is wanted for
transparency at any layer, for placing positions anywhere on a stage in
three dimensions, for labels, for views from the side and projections later,
for owning the lookup over ten thousand positions, and for not depending on
an engine whose coordinate spaces and all-or-nothing invalidation cost this
project weeks. Those reasons stand whatever the measurement says. This
record therefore supersedes the "only if the installed engines fail" clause
of the earlier design for the renderer, and says so plainly rather than
leaving two records that contradict each other. The stop on the compact
eight-bit and JPEG pyramid experiment in that earlier design is untouched.

What is taken from the objection, because it is right: phase 0 runs first,
on the microscope PC, with its time broken down into server work, transfer,
decoding, hand-off to the drawing thread, upload and drawing, on the same
pixels, views and cache states. That breakdown is the baseline the engine
must beat and it says which of the engine's parts matter most. The data
layer is built and measured under the existing engine before the new one is
written. "At least as fast as neuroglancer" is a hypothesis with a gate, not
a premise.

## Choices already made

- **We build it ourselves.** Not Viv, not deck.gl. On the harness, deck.gl
  (`viv-inside`) is plainly and repeatedly slower; `viv-under` matched
  neuroglancer on a single plane change and lost on movement, because
  neuroglancer fetches and schedules off the drawing thread and drops work
  that has been superseded. Neuroglancer's scheduling and rendering are the
  inspiration, not the dependency. What it does that we must also do is
  listed under the engine, because both reviews found the first draft
  underestimating it.
- **Neuroglancer stays as the reference.** It remains the engine the harness
  compares against, and it is replaced on the operator page only once the
  new engine beats it on the harness's own numbers, over the same data layer.
- **Two dimensions first, with depth and time on sliders.** The engine draws
  one plane at a time: one moment in time, one depth, every visible channel.
  The operator moves through depth and time with the two sliders the panel
  already has, with play buttons that step and wrap; neighbouring planes are
  prefetched while scrubbing. A run with one depth or one moment shows no
  slider for it.
- **The data is five-dimensional.** Time, channel, depth, height, width, any of
  which may be one long. Any number of channels.
- **One three-dimensional stage space, defined before it is used.** The
  engine's world is the stage in micrometres, with x, y and z. Two facts the
  first draft got wrong: the position writer, not neuroglancer, sets every
  position's height to nought on purpose, because a flat plate scanned under
  a focus map otherwise composes into a stack two dozen planes deep and the
  operator sees almost nothing; and no file on disk holds a capture height
  today, it lives in the bridge's memory and is cleared at the next scan. The
  writer also replaces the recorded plane heights by one median step. So the
  register carries, per position and per plane, the raw recorded height in
  micrometres, never replaced by a median, while the stores may go on saying
  nought. And before any placement uses those heights, the data-layer record
  defines the coordinate frame: which way stage z points, handedness, units,
  the voxel-edge convention already settled for x and y, the relation between
  the recorded stage height and the specimen's height, and the calibration
  the numbers belong to. Placement modes are presentation transforms with
  their own provenance; the acquisition's geometry is never rewritten.
- **Placement: aligned at the low edge is today's behaviour and the default;
  absolute comes later.** Every position beginning at height nought is
  alignment at the low edge of each stack, which the operator will know as
  "table"; alignment at the high edge is "ceiling"; both are named by the
  edge until the direction of stage z is guaranteed. Aligned placement means
  one meaning, chosen: a common offset in micrometres from the aligned edge,
  each stack showing the plane whose voxel interval contains that offset, and
  a shorter stack absent beyond its own depth. A normalised fraction through
  each stack is a different question and, if ever wanted, a separate mode. A
  custom offset per stack is a later mode that cannot be precomputed.
  "Absolute" placement, each position at its true recorded height, is a later
  mode: it needs the heights from the register and the frame above, and for a
  flat collection it needs a projection or a slab as its default, or a slice
  through it shows two fields out of fifty.
- **Views: from the top first, from the side later.** The side view stays in
  the design as a later milestone. Said precisely now, because the first
  draft was not: a side view is a cross-section along x and z at one y, or
  along y and z at one x, so it needs a slider for the axis it cuts at; a
  projection in the side view reduces along that same axis, y or x, never
  along z, which is already on the screen. It changes two contracts the first
  engine keeps: the view record gains a direction, because the gesture module
  and every overlay project in stage x and y today, and dirty regions must be
  boxes. It reads one row out of every plane's chunk at fine levels, and a
  transposed copy of the data for it is a data product of its own.
- **Projections: later, with their meaning stated.** Maximum, mean and sum
  through a chosen range are wanted and stay in the design; none is in the
  first engine. Their arithmetic is written down before they are built: the
  pyramid keeps every plane and halves only height and width, so a projection
  taken at a coarse level is a projection of the samples that level keeps,
  not of every full-size pixel under a coarse one; a coarse maximum can miss a
  small bright object the decimation dropped, and a coarse sum is not the
  total signal over the area. The display and any export name that sampled
  meaning. A sum needs a 32-bit accumulator; a mean across unequal or missing
  ranges is a sum and a count, never a mean of means; across stacks with
  different z steps only the mean is offered, since a sum tracks plane
  density; a range ending between planes says whether the edge plane is in,
  by the voxel-edge rule; a projection's identity carries its axis, kind and
  range; labels are never projected. Whether whole-stack projections are
  precomputed per position is measured, and a precomputed one changes on a
  landing, a later timepoint and a replacement alike.
- **Labels are a first-class layer, written second.** Segmentation and label
  images draw with their own shader: integer values, a colour per object,
  one object highlighted, no brightness window, no projection. Nothing on the
  bridge side produces them yet and the operator page has no label layer, so
  the shader is a second milestone. In the first engine from the start: a
  distinct data kind for labels that is never measured, never windowed and
  never projected, and a texture format for 32-bit integers.
- **Channels as a colour overlay, the way it is now.** Every channel is drawn
  in its own colour or colour map and the channels add together on the
  screen, so a place that recorded green and red is yellow; each has its own
  window, colour, colour map, eye and opacity. Adding is between channels
  only. Where two positions of one collection overlap, the one committed
  later lands on top, which is the rule the Viewer's record already states;
  overlapping positions are never added, because that would brighten seams
  and change what a pixel means.
- **Transparency at any layer.** Every source and every channel has an alpha,
  so a sparse acquisition lets whatever lies beneath it show through. Ground
  that has not landed is drawn as absent, distinct from a black pixel that
  was acquired; the cache carries a coverage mask beside the pixels for this.
- **Collections are the unit of loading, with a durable identity.** Focussing,
  overview and target are different acquisition types, and each is its own
  collection: its own register, its own positions folder, its own heading in
  the panel with an eye and an opacity for the whole, and its own placement.
  The panel groups by the acquisition's display name today; a collection
  gets a stable identity distinct from its name, so two scans of the same
  type are never merged by accident. A collection whose fields differ in size
  is several profiles, one per size, which is what the Viewer's record package
  already asks for.
- **The display contract stands, carried all the way to the shader.** Channel
  names and colours come from the acquisition record; there is one authority
  for the display window; a window is declared, measured and provisional,
  measured and settled, or absent; the engine draws nothing through a window
  nobody has given it, and never falls back to the camera's range or the
  data type. Both reviews found the same gap: the authority is keyed per
  channel only, and the first draft's tile address and cache carried no data
  kind. So the identity that travels from the register through the cache to
  the shader is: collection, source and its generation, time, the stable
  channel key, level, orientation, slice or projection with its kind and
  range, tile row and column, and revision; and beside the pixels, the data
  kind and type, the window with its state, and the coverage mask. A
  projection is its own kind with its own measured window and its own
  provisional or settled state; a slice's window is never reused for it.
  Coarse standing in for fine is allowed only within one channel.
- **What stays as decided before.** Decimation pyramids, capability
  negotiation between bridge and Viewer, omitting the OME channel block when
  a window is undecided, and the stop on the eight-bit and JPEG pyramid
  experiment.
- **The small JPEG previews stay separate.** They serve target detection and
  the gallery under their own measured preview contract, and never reach the
  canvas.

## Inputs: two ways in, one form inside

- **Two accepted inputs.** The flat OME-TIFF convention the microscope
  writes today (one file per plane, or one file holding channels, listed
  plane by plane in the capture record), and OME-Zarr 0.4 or 0.5 with axes
  in the OME order: time, channel, depth, height, width (t, c, z, y, x).
- **One form inside.** Everything is served to the engine as OME-Zarr 0.5
  positions with those five axes. That is what the bridge's position writer
  already makes from the vendor's TIFFs the moment a field lands, so a TIFF
  input means conversion at the door, not a second reader in the engine.
- **0.4 is read, not written.** The Viewer opens 0.4 stores today; new
  positions are written as 0.5. The engine only ever sees the Viewer's pieces.
- **What this rules out, on purpose.** Serving tiles straight out of TIFF
  files.
- **The register records the origin.** Which TIFFs a position came from, so
  provenance survives the conversion.

## Not now: three-dimensional rendering

- No volume rendering in this design. Every view is a slice or a projection,
  drawn flat.
- The door is left open by a clean separation of three things, and by nothing
  else: the tile source, the cache policy, and the drawing. A volume renderer
  later reads the same register and the same source, and chooses its own
  representation from measurements and a proper reading of the primary
  sources. The first draft promised more than that, a fixed atlas and "the
  same cache with one more coordinate", and Codex was right that the survey
  behind it rested partly on abstracts and that three-dimensional bricks
  change filtering, borders, transfer and sampling. That promise is
  withdrawn; the first engine carries no three-dimensional abstraction it
  does not use.
- The two prior-art notes stay as reading for that phase:
  `prior-art-larger-than-memory-3d-rendering.md` (which now says where it
  overreached) and `prior-art-napari-progressive-loading.md`. What they teach
  that is durable: bounded residency, multiscale chunks, an explicit lookup,
  and a coarse fallback.

## The register: the Viewer already has one, the bridge has to write it

Both reviews found the same thing: the Viewer's `record` package is the
register this design describes, and a second "one file" beside it would be
two truths. The work is on the bridge's side, plus a versioned extension.

- **What exists, in the Viewer.** A sealed profile per acquisition type
  (frame shape, dtype, voxel size, levels, channel names, room along time),
  agreed before the run starts; a run whose acquisition changes must start a
  new instance. A numbered, never-edited layout revision holding every
  planned position with its origin including depth, created whole before the
  first pixel. A commit event per arrival, a replacement as a new immutable
  generation rather than an overwrite, and later timepoint commits. An
  append-only event history, a small signed truth file replaced by rename,
  and a fingerprint that is one file-system call. A rule that a zoomed-out
  piece is rebuilt from committed positions only and republished in the same
  step as the position. A Viewer on another computer opens such a run from
  the files alone, with no bridge.
- **What the bridge writes today.** Only the position store, and the channel
  contract at scan start. Every scan of a type lands under one folder; a
  re-scan is refused because the store exists. The Viewer opens the folder as
  an ordinary transfer, listing it and reading every store's description,
  and reopens it every thirty seconds while it grows.
- **What the bridge must write, and when.** The profile at scan start, beside
  the channel contract it already publishes there; a layout revision listing
  every planned position with its stage corner including the raw recorded
  height; and a commit per landing. The bridge already holds the whole list
  of planned positions at scan start, so nothing new has to be known, only
  written.
- **The versioned extension, all of it small.** A stable identity for the run
  and for each collection, distinct from the display name and the acquisition
  type. Planned and observed placement kept apart, with the coordinate frame
  and calibration they belong to. Provenance of the vendor files. A reference
  to the one acquisition display contract. A terminal state for the run,
  completed, stopped or failed, with time and reason; the record has none
  today, and a stopped run must not look like a slow live run for ever. A way
  to say a planned position was skipped or will never arrive; the event kinds
  today are committed, timepoint committed and replaced. One profile per
  frame shape. A schema version. And one correction to the existing record:
  its layout revision describes itself as what the run has done so far while
  holding the whole plan from the start; the wording is fixed, not copied.
- **Planned, arrived, never coming.** While the run is live a planned but
  absent position is drawn as its own state, a faint outline of expected
  ground. When the run reaches its terminal state it becomes "not acquired"
  or "skipped". Coverage is the committed positions only.
- **A re-scan of the same type** is a new collection identity and a new
  folder, however familiar its label. Silent overwriting is not an option.
- **A folder without a register**, from before this work, keeps the Viewer's
  read-only discovery path or gets a plain refusal; it never needs a bridge.
- **Two cautions for a network share**, to be tested on the real one: the
  fingerprint includes the inode, which some network file systems do not
  keep stable; and a reader on another machine may see a renamed truth file a
  little late.
- **Who reads it.** The Viewer, instead of listing folders; coverage, per
  level, derived in memory from ten thousand rectangles and handed to the
  page as an indexed snapshot, never the whole plan rewritten after every
  landing; the kept coarse pyramid; and the engine's own lookup.

## The data layer: what is kept, what is assembled, with the numbers

Ten thousand positions is won or lost here, not in the renderer. Both
reviews supplied arithmetic from the writer's own constants (chunks of 128
voxels, no sharding, levels halving down to eight voxels, one plane per
chunk, composed pieces of 512). "Ten thousand" is meaningless without the
field size, channels, depth, time, overlap, codec, shard shape and whether
the disk is local or a share; the numbers below say which case they are.

- **What a plate is on disk, two cases.** Ten thousand flat monochrome fields
  of 512 voxels: about 330,000 files and 6.5 GiB of raw pyramid. Ten thousand
  flat three-channel fields of 2048 voxels: about 10.5 million files and
  312 GiB. Depth and time multiply the chunk files and bytes; a deep
  three-channel run passes a billion small files. The vendor's TIFFs are
  beside all of it. Five of the levels per position are tiny files that exist
  only so a coarse level has something to point at.
- **Where it breaks first: the folder scan.** Every relink reads every
  store's description, tens of thousands of reads on such a plate, repeated
  every thirty seconds while the scan grows. On a share that scan takes
  longer than the interval. The register removes it, and it is the first
  target.
- **Second: the file count.** Small-file metadata work on Windows or a share,
  backup and antivirus, break before anything in the register or the
  renderer. Sharding the position stores is the answer, and it is a
  prerequisite of the ten-thousand claim, not an optimisation after the
  engine. Two facts: the storage library can bundle a shard when asked, but
  only the full-size level, and the bridge's writer never asks; and bundling
  the full-size level alone leaves millions of files in the other levels, so
  the sharding design must cover every file-dominant level. Sharding must
  never touch the kept coarse levels, which are patched one piece at a time:
  a partial write into a shard rewrites about half the shard, which the
  Viewer measured. Whether a position still needs its tiny levels once the
  coarse levels are kept elsewhere is decided in the data-layer record.
- **Third: the bridge's write rate** on a share, hundreds of directory entries
  per position, and any per-landing bookkeeping that grows with the number of
  positions.
- **Tile sizes, said first.** The composed pieces are 512 voxels; the source
  chunks are 128. "A fine tile inside one position is one read" is only true
  if the engine's fine tile is the source chunk, aligned to it; a 512 tile
  over a full-size position is sixteen reads per channel and plane. The
  data-layer record fixes the engine's tile size per level with that in
  mind; the default is the source chunk at the finest levels and the composed
  piece at kept levels.
- **Fine levels are assembled on demand.**
- **Coarse levels are kept and patched, if the measurement says so, in one
  canonical placement, per channel and not cheap.** Zoomed out, one 512-piece
  at the coarsest level touches four thousand positions, and warming the kept
  levels of three channels is on the order of 170,000 chunk reads: seconds on
  a local drive, tens of minutes on a share. Whether those levels are kept on
  disk is decided by the phase-0 breakdown: the earlier design's phase 1
  already says that if cold open or coarse warm is the problem, the answer is
  inside the composer, and persistence only where repeated opens show a
  benefit. If kept, they are per channel: for a three-channel plate of
  2048-voxel fields the current one-per-cent rule keeps about 2,600 channel
  pieces, about 1.3 GiB uncompressed for one plane and one moment, and depth,
  time, projections and side copies multiply it. They are kept in the
  low-edge alignment, which is the default and what exists. Patching is
  synchronous with the landing and off the stage's own path, as the Viewer's
  rule works today, unless the data-layer record introduces an explicit
  derived revision; then a kept tile stamped with an older revision is either
  composed lazily from the current one or withheld, and is never served as
  current. Persistence on disk and residency in memory are separate decisions
  with separate rules.
- **The boundary rule: a measured cost model, fan-in among its inputs.** A
  level is served lazily while assembling any of its tiles costs less than the
  frame can wait, and kept beyond that. Fan-in is the first input, and the
  composer already knows which tiles fall in each piece; but one position is
  not one read, so the model counts source chunks and bytes per output tile,
  the codec, channels and planes per frame, overlap, whether the block cache
  is warm, how many reads run in parallel, and local disk against the share,
  with cold and warm percentiles recorded separately and a guard so that one
  exceptional tile does not force a whole level to disk. The Viewer's
  existing one-per-cent rule answers disk rather than latency; the kept set
  is the union. The boundary is evaluated over the planned positions in the
  register, so it never moves under the operator while a scan lands.

## The engine itself

- **Tiles, not arrays.** A tile is addressed by the full identity above:
  collection, source and generation, time, stable channel key, level,
  orientation, slice or projection with kind and range, row, column,
  revision. The drawing path never sees zarr.
- **What neuroglancer does that we must also do.** Its chunk manager
  prioritises visible, predicted-next and recently used chunks; caps
  concurrent downloads; aborts a lower-priority download for a higher one;
  evicts by both system and graphics memory; runs queueing, downloading and
  decoding off the drawing thread in cancellable workers; and gives every
  chunk an explicit state from new to queued to downloading to decoded to
  uploaded to failed to expired. The first draft named byte budgets,
  least-recent use, prefetch and cancellation and left the rest out. The
  engine specifies: a priority order (visible first, nearest the view centre
  first, coarser levels first); a fixed number of requests in flight;
  abort of a superseded request; retry with back-off and a failed state;
  fairness between channels and collections; stale results dropped by
  revision; the hand-off from worker to drawing thread; what happens when the
  pinned plane alone exceeds the budget; and recovery from a lost WebGL
  context. Holding fetches while the hand moves is one rule among these, not
  a substitute for them, and none of it "costs nothing".
- **One worker that fetches and decodes, from the start.** The measured
  advantage of neuroglancer was fetching and scheduling off the drawing
  thread; decoding stays there too, because raw pixels from the Viewer would
  double the bytes over a share.
- **Level of detail** from the zoom against each level's voxel size in
  micrometres; a coarser level of the same channel stands in while the finer
  loads.
- **Placement.** Each tile a textured rectangle at its true micrometre
  position, by the voxel-edge rule already settled.
- **Cache.** Two tiers with byte budgets, least recently used, the current
  plane pinned. On the graphics side, pools by tile dimensions and internal
  format (sixteen-bit counts, eight-bit counts, 32-bit sums, 32-bit labels),
  a texture per tile as neuroglancer does or slots in a texture array,
  decided by measurement; the lookup from tile to texture lives in
  JavaScript. WebGL2 cannot say how much graphics memory there is, so the
  budget is a number somebody sets. The cache keeps the source data type and
  the coverage mask; nothing is converted on the way unless the conversion is
  lossless and stated.
- **Invalidation.** Tiles are keyed by revision. The Viewer publishes, per
  revision, the regions a landing, a later timepoint or a replacement dirtied
  at each level, as boxes, from the old and the new footprint alike; the
  engine drops only the tiles that intersect them. Today the event stream
  says only "something changed" and the page drops every cached chunk on
  relink; the live-state document already carries a per-source revision and
  is the right document to grow boxes into. The composer's footprint of a
  turned position is its bounding box, which is conservative and enough for
  invalidation, not byte-exact geometry.
- **Sparse.** Coverage from the register decides which tiles exist at each
  level. An empty piece already costs a request and no bytes today, so the
  saving is in requests, and the gate says so.
- **Measurement hooks, from the first commit.** The same handle the harness
  and the panel rely on today, plus the breakdown instrumentation phase 0
  uses, so the new engine is measured by the same harness, on the same
  pixels, as the old.

## Navigation

Most of this exists and is kept; the first engine draws the flat top view
only, so the gesture module stays as it is.

- **Dragging pans, the plain wheel zooms**, from one shared module every
  engine uses unchanged; every other gesture is refused on purpose and
  counted. **Zoom holds the point under the mouse.** Both exist and stay.
- **Depth and time on sliders, not gestures.**
- **The view is in stage micrometres, and it survives** a change of engine,
  a relink, and a run that has captured nothing yet.
- **Look at this.** `lookAt(centre, zoom)`; with the register, jumping to a
  position or a well by name is a lookup, and "fit what has arrived" is
  possible mid-scan.
- **A drag can be lent out** to a drawing tool, and **one projection** places
  every mark; both kept.
- **A readout follows the pointer** in stage x and y already; z and the pixel
  value under the pointer are the additions.
- **Later, with the side view:** the view record gains a direction, a slider
  for the axis the section cuts at, overlays hidden or re-projected, the drag
  panning in x or y and z.
- **After the numbers, none a gate:** a scale bar; keyboard nudges;
  double-click to centre; pinch; zoom limits; the view in the page address
  and remembered per run; the view saved as a picture.

## Decisions on the two reviews

Every finding was checked against the code before being taken; both reviews
say what they checked and were right on every fact I re-checked.

Taken from the first review and folded in above: height is not on disk and
the writer zeroes it; the Viewer's record package is the register; the
plate arithmetic; shard positions and never the patched levels; fan-in from
the plan; a worker from the start; per-format pools and a JavaScript lookup;
priority and concurrency; requests rather than bytes as the gate; the
(channel, kind) key and the label kind; dirty regions as boxes; the
corrected facts; the smaller first engine.

Taken from Codex's review and folded in above: phase 0 runs first with a
breakdown and the performance claim is a gated hypothesis; the register is a
versioned extension of the Viewer's record with stable identities, terminal
state, planned versus observed placement, frame provenance and a legacy
path; the coordinate frame and z datum are defined before any placement
uses heights and the raw plane heights are kept; aligned placement has one
stated meaning and edge-based names; the side view's own slider and
projection axis; projection arithmetic and its sampled meaning; labels as a
distinct data kind, never projected; the end-to-end identity through cache
and shader; the coverage mask and the later-commit-on-top rule for
overlaps; the cost model in chunks and bytes with tile sizes stated first,
no single global K, kept tiles never served stale; kept levels conditional
on the measurement and per channel and not cheap; sharding of every
file-dominant level as a prerequisite of the claim; the withdrawn atlas and
"same cache for 3D" promises; the removal of "every renderer" and "all moved
to WebGPU"; "costs nothing" struck.

Not taken, and why:

- **"Rethink": making the engine conditional on phase 0.** The order is
  taken, the condition is not; see the section on the contested decision.
  The engine is the owner's decision for reasons beyond speed, and this
  record supersedes the earlier "only if" clause rather than contradicting
  it in silence.
- **Cutting the kept coarse levels until measured** is taken in substance and
  refused in wording: they stay in the design as the answer the numbers
  point to, and the measurement decides whether they are built.
- **Cutting labels, projections, alignment and the side view from the
  design.** They leave the first engine, not the plan; each is a named later
  milestone, and what each needs so nothing has to be undone is in the first
  engine and the register.
- **The first review's suggestion that neuroglancer's coordinate spaces are a
  cost we underestimate.** Codex is right that ten thousand positions are
  already hidden behind one composed source, so that cost is small today; it
  becomes real at the later milestones, which is why they are later.

## Facts checked against the code, and what is new

- Exists: the Viewer's record package (profile, layout revision, commit
  event, generations, signed truth file, synchronous coarse rebuild, opening
  from files alone); the change event stream and revisioned live-state
  document; file-identity validators on live pieces; segmentation rows in
  the Viewer's standalone config; bounding-box footprints in the composer
  and bake patcher; the harness's synthesised coverage; the shared gesture
  module with pointer-anchored zoom; the sliders; the view in micrometres;
  the pointer readout in x and y; sharding of the full-size level in the
  storage library; neuroglancer's texture per chunk and off-thread workers in
  the pinned version.
- New: the bridge writing the register; the versioned extension; height and
  the frame in the register; coverage on the operator page; dirty boxes per
  revision; the cost model; the kept-and-patched coarse pyramid for
  bridge-written runs, if measured necessary; sharding in the bridge's
  writer for every file-dominant level; the end-to-end identity; a label
  data kind; a label layer on the operator page; the engine itself.
- Not yet measured, and decisive: the phase-0 breakdown on the microscope
  PC; the cost model on a local disk and on the real share; whether a
  position still needs its tiny levels; the bridge's conversion rate on a
  share; whether whole-stack projections need precomputing.

## Gates

Phase 0, on the microscope PC, before anything is built: the earlier
design's ten-step trace over the existing Viewer and engine, with time broken
down into server work, transfer, decoding, hand-off, upload and drawing, on
a real run, cold and warm, local disk and share. Its result is the baseline
and says which layer fails, if any.

The data layer is done when, under `neuroglancer-under`, on a stated plate:

- opening a run reads the register and never lists the positions folder;
- a relink of a grown run costs a fingerprint check, not a scan;
- if coarse levels are kept, a coarse tile is one read, and a landing
  patches exactly the pieces its footprint dirties before the new revision is
  published;
- coverage removes every request for a position that has not arrived;
- a new live position is visible within 500 ms at the ninety-fifth
  percentile, the earlier design's own gate.

The engine is done when, on the harness, over the same data layer, on the
same pixels:

- first picture is no slower than neuroglancer's;
- navigation latency at the ninety-fifth percentile is no worse, and a
  settled pan or zoom completes within 500 ms at that percentile;
- requests for the same navigation are fewer, and bytes no more;
- memory stays within the budget the cache was given;
- a landing during viewing dirties exactly its footprint and nothing else;
- every panel state (declared, provisional, settled, waiting, unreadable,
  absent) reaches the screen the same way it does with neuroglancer, and no
  absent window ever reaches the shader;
- it opens our own data as it is written today, unchanged: a bridge run
  whose fields arrived as our flat OME-TIFFs and were converted at the door,
  and an OME-Zarr transfer of ours in 0.4 or 0.5 with the five axes.

## Order of work

1. Phase 0 on the microscope PC, with the breakdown. Nothing in this record
   is authorised to be built before its numbers exist.
2. The data-layer design record: the bridge writing the Viewer's register and
   the versioned extension; the coordinate frame and z datum; coverage;
   dirty boxes; the cost model and tile sizes; sharding of every
   file-dominant level in the bridge's writer; the tiny-levels decision; the
   terminal state; the re-scan rule. One review pass.
3. The data layer built and measured under `neuroglancer-under`: its gates,
   and the baseline the engine must beat.
4. The engine design record with the first brief: flat top view over the
   positions as the stores place them today, slices only, channels as an
   overlay, the end-to-end identity, the scheduler as specified, the worker,
   the per-format pools, the measurement handle. One review pass. Then the
   engine in stages: source and cache headless and testable without a
   browser; the renderer; the fourth option beside neuroglancer; the numbers.
5. Later milestones, each with a short record and the same discipline:
   labels; the maximum projection, then mean and sum; aligned placement with
   its stated meaning, then absolute with its default; the side view with its
   own slider and contract changes; the navigation extras.
6. Only after that: the three-dimensional phase, choosing its own
   representation from measurements.
