# A rendering engine of our own, and the register that feeds it

Date: 2026-09-02, revised the same day after the first independent review
(`docs/reviews/2026-09-02-review-of-the-rendering-engine-design.md`).
Status: high-level design for discussion. Nothing here is implemented; this
records the choices made in conversation, corrected where the review showed
a stated fact to be wrong, and the decisions taken on each of its findings.

A few words used below, said once: a *tile* is one small square of one
level of the picture, the unit that is fetched, cached and drawn; *fan-in*
is how many positions one tile touches; *sharding* is bundling many small
chunk files into one large file with a table at the end; a *texture array*
is one block of graphics memory holding many tiles of the same kind of
number, each in its own numbered slot; *decimation* is the way our pyramids
are made, keeping every second voxel along height and width and every
plane along depth; a *dirty region* is the part of the picture a landing
changed; *alpha* is how see-through a thing is drawn.

## What we want, in one paragraph

A drawing engine that is ours, fitted to microscope acquisitions: many
thousands of positions placed anywhere on the stage, any number of channels,
depth and time, transparency where the picture is sparse, labels drawn as
labels, and an honest picture of what is still arriving. It should be at least
as fast as neuroglancer on our own data, and it should get there by owning the
lookup: which positions a tile touches, which pyramid level answers it, and
what is precomputed rather than assembled on the fly.

## Choices already made

- **We build it ourselves.** Not Viv, not deck.gl. On the harness, deck.gl
  (`viv-inside`) is plainly and repeatedly slower; `viv-under` matched
  neuroglancer on a single plane change and lost on movement, because
  neuroglancer fetches and schedules off the drawing thread and drops work
  that has been superseded. Neuroglancer's scheduling and rendering are the
  inspiration, not the dependency.
- **Neuroglancer stays as the reference.** It remains the engine the harness
  compares against, and it is replaced on the operator page only once the
  new engine beats it on the harness's own numbers.
- **Two dimensions first, with depth and time on sliders.** The engine draws
  one plane at a time: one moment in time, one depth, every visible channel.
  The operator moves through depth and time with the two sliders the panel
  already has, with play buttons that step and wrap, and each move is a new
  plane to draw, prefetched from the neighbouring planes while scrubbing. A
  run with one depth or one moment shows no slider for it. Three dimensions
  come later, and the cache and data path are built so a volume renderer can
  reuse them.
- **The data is five-dimensional.** Time, channel, depth, height, width, any of
  which may be one long. Any number of channels.
- **One three-dimensional stage space, and the truth about height.** The
  engine's world is the stage in micrometres, with x, y and z. Two facts the
  first draft got wrong: the position writer, not only neuroglancer, sets
  every position's height to nought on purpose, because a flat plate scanned
  under a focus map otherwise composes into a stack two dozen planes deep
  with two or three fields on each, and the operator sees almost nothing; and
  no file on disk holds a position's capture height today, it lives in the
  bridge's memory and is cleared at the next scan. So the register carries
  the height per position and per plane, in micrometres, from its first
  version, while the stores may go on saying nought. Which of the two the
  composer places by is the placement mode below.
- **Placement: the table is the default, absolute comes later.** Today's
  arrangement, every position beginning at height nought, is the "table"
  alignment: bottoms aligned, one slider through every stack at the same
  relative depth. That is what a map of a plate is, and it stays the default.
  "Ceiling" (tops aligned) and a custom offset per stack are variants of the
  same idea. "Absolute" placement, each position at its true capture height,
  is a later mode: it needs the height from the register, and for a flat
  collection it needs a projection or a slab as its default, or a slice
  through it shows two fields out of fifty. A custom offset per stack can
  never be precomputed and is last.
- **Views: from the top first, from the side later.** The side view (the
  screen's vertical is z; a cross-section along x and z or y and z) is wanted
  and stays in the design, but it changes two contracts the first engine
  keeps unchanged: the view record must gain a direction, because the
  gesture module and every overlay project in stage x and y today, and dirty
  regions must be boxes rather than rectangles. It also reads one row out of
  every plane's chunk at fine levels. It is a later milestone with those
  costs named.
- **Projections: maximum first, sum and mean after.** A maximum projection
  fits the camera's numbers and is the one a microscopist reaches for; it is
  in the first engine. A sum overflows sixteen bits after a few planes and a
  mean is a different kind of number, so both need 32-bit storage and a
  second texture format; they follow once the first engine stands. A
  projection over a decimated level is honest, because the pyramid keeps
  every plane and halves only height and width. Two rules for later: a sum
  over a custom range across stacks with different z steps tracks plane
  density rather than signal, so only the mean is offered across stacks; and
  a range that ends between planes says whether the edge plane is in or out,
  by the voxel-edge rule. Whether whole-stack projections are precomputed per
  position is measured, not assumed; on demand first.
- **Labels are a first-class layer, written second.** Segmentation and label
  images draw with their own shader: integer values, a colour per object,
  one object highlighted, no brightness window. Nothing on the bridge side
  produces them yet and the operator page has no label layer, so the shader
  is a second milestone. What is in the first engine from the start, because
  adding it later would touch everything: a row kind for labels that is never
  measured and never given a window, and a texture format for 32-bit
  integers.
- **Channels as a colour overlay, the way it is now.** Every channel is drawn
  in its own colour or colour map and the channels add together on the
  screen, so a place that recorded green and red is yellow; each has its own
  window, colour, colour map, eye and opacity, exactly the controls the panel
  offers today.
- **Transparency at any layer.** Every source and every channel has an alpha,
  so a sparse acquisition lets whatever lies beneath it show through, at any
  depth of the stack of layers.
- **Collections are the unit of loading.** Focussing, overview and target are
  different acquisition types, and each is its own collection: its own
  register, its own positions folder, its own heading in the panel with an
  eye and an opacity for the whole, and its own choice of placement. A
  collection whose fields differ in size is several profiles, one per size,
  which is what the Viewer's record package already asks for.
- **The display contract stands, with one more key.** Channel names and
  colours come from the acquisition record; there is one authority for the
  display window; a window is declared, measured and provisional, measured
  and settled, or absent; the engine draws nothing through a window nobody
  has given it. The review found the gap: the authority is keyed per channel
  only, so a slice's window would be applied to a projection of the same
  channel, which is a window used on numbers it was not measured on. The key
  becomes (channel, kind of picture), with "slice" the only kind at first,
  and the panel says which kind its window belongs to. A label row is a kind
  that is never measured. Coarse standing in for fine is allowed only within
  one channel, never across channels.
- **What stays as decided before.** Decimation pyramids, capability
  negotiation between bridge and Viewer, omitting the OME channel block when
  a window is undecided, and the stop on eight-bit and JPEG pyramid work
  until this design has its numbers.
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
- **0.4 is read, not written.** The Viewer opens 0.4 stores today, so older
  transfers work as sources; new positions are written as 0.5. The engine
  only ever sees the Viewer's pieces, so the version is the Viewer's concern.
- **What this rules out, on purpose.** Serving tiles straight out of TIFF
  files. It would need a second tile server and a second cache path, and the
  conversion is already paid at landing.
- **The register records the origin.** Which TIFFs a position came from, so
  provenance survives the conversion.

## Not now: three-dimensional rendering

- No volume rendering in this design. Every view is a slice or a projection,
  drawn flat.
- The door is left open on purpose: the stage space is three-dimensional,
  every position carries its x, y, z in the register, and the tile cache and
  data source do not know how they will be drawn. A volume renderer later
  reads the same cache and the same register and adds a draw path; it
  changes nothing above.
- Nothing in the engine, the register or the data layer may be shaped in a
  way that would have to be undone for it. That is the whole of the promise
  made to three dimensions now.
- **When it comes, it is WebGPU.** The browser-native out-of-core volume
  renderers have all moved to WebGPU and compute-shader ray marching; the
  two-dimensional engine is WebGL2, and the three-dimensional phase should
  assume WebGPU. The four ideas they share, bricks, a fixed budget of
  graphics memory, a lookup, and coarse standing in for fine, are in the
  cache below in their two-dimensional form. The survey is
  `prior-art-larger-than-memory-3d-rendering.md`; Kiln and the Residency
  Octree are the two to read first, because the second is built for several
  volumes at once, which is our channels and collections.
- **Prior art to read when the time comes.** napari's "Progressive loading
  for 2D and 3D" (napari/napari pull request 9067, June 2026, experimental
  and opt-in): viewport-bounded three-dimensional sub-volume tiles fetched
  front to back, the coarsest level kept resident as a backdrop while finer
  tiles stream in, streaming paused while the camera moves, chunk-sized
  partial texture updates into double-buffered volume textures, and uploads
  metered to the frame rate. It is Python, vispy and desktop OpenGL, so
  nothing of it is reusable code for a browser engine, but its shape is the
  shape we would want. Two smaller merged pieces are worth knowing: a manual
  lock on the multiscale level for 2D and 3D (pull request 8917) and a
  half-voxel offset fix (pull request 9065), the same disagreement we settled
  with the voxel-edge rule. Details in `prior-art-napari-progressive-loading.md`.

## The register: the Viewer already has one, the bridge has to write it

The review's most useful finding. The first draft asked whether the Viewer's
manifest "fits or needs a variant". It fits: the Viewer's `record` package is
the register this design describes, and the work is on the bridge's side.

- **What exists, in the Viewer.** A sealed profile per acquisition type
  (frame shape, dtype, voxel size, levels, channel names, room along time),
  agreed before the run starts. A numbered, never-edited layout revision
  listing every planned position with its origin in the run's coordinates,
  including depth, whether or not it has arrived. A commit event per arrival,
  with a generation number for a re-scan of the same position. An
  append-only event history, a small signed truth file replaced by rename,
  and a fingerprint that is one file-system call and reads no bytes. A rule
  that a zoomed-out piece is rebuilt from committed positions only and
  republished in the same step as the position. A run is opened from these
  files alone, on any machine, with no bridge.
- **What the bridge writes today.** Only the position store, and the channel
  contract at scan start. The Viewer opens the folder as an ordinary
  transfer, listing it and reading every store's description, and reopens it
  every thirty seconds while it grows.
- **What the bridge must write, and when.** The profile at scan start, beside
  the channel contract it already publishes there; a layout revision listing
  every planned position with its stage corner including height; and a
  commit per landing. The bridge already holds the whole list of planned
  positions at scan start, so nothing new has to be known, only written.
- **Four additions to the Viewer's record, all small.** Height per plane in
  micrometres (a question of what the bridge writes into the origin, not of
  schema); provenance of the vendor files (a proper field beside the free
  notes); a way to say a planned position will never arrive (a new event
  kind, or a final layout revision that drops it); and one profile per frame
  shape within a collection.
- **Planned, arrived, and never coming.** The engine draws a planned but
  absent position as its own state, a faint outline of expected ground,
  because "an honest picture of what is still arriving" is the promise.
  Coverage is the committed positions only.
- **A scan stopped part way.** The bridge already announces the end of a
  scan whether it finished or was stopped; that announcement also seals the
  layout as final with the arrived set, so a reader on another machine can
  tell "stopped after three thousand of ten thousand" from "still going".
- **A re-scan of the same type.** The bridge refuses it today because the
  position store exists. Either the new capture is written as a new
  generation of the same position, which the Viewer's commit event already
  allows for, or the scan is a new collection instance under a new profile.
  Silent overwriting is not an option. Decided in the data-layer record.
- **Two cautions for a network share**, to be tested on the real one: the
  fingerprint includes the inode, which some network file systems do not
  keep stable; and a reader on another machine may see a renamed truth file a
  little late.
- **Who reads it.** The Viewer, instead of listing folders; coverage, per
  level, derived in memory from ten thousand rectangles; the kept coarse
  pyramid, to know which tiles a landing dirties; and the engine's own lookup,
  which positions touch a tile at a level.

## The data layer: what is kept, what is assembled, with the numbers

Ten thousand positions is won or lost here, not in the renderer. The review
supplied the arithmetic from the writer's own constants; it is kept here so
the design is argued from numbers. Assumptions: a flat plate of ten thousand
positions, a hundred by a hundred, each field 1024 by 1024 voxels of
sixteen-bit counts, three channels, one plane, one moment; chunks of 128
voxels, no sharding, eight pyramid levels down to eight voxels, as the
position writer makes them; composed pieces of 512 voxels.

- **What the plate is on disk.** About 267 chunk files and nine description
  files per position, in about 130 folders: roughly 2.8 million chunk files
  and 4 million directory entries for the plate, about 80 GiB before
  compression, beside the vendor's TIFFs. A ten-plane stack per position
  makes it 27 million files. Five of the eight levels per position are tiny
  files of a few hundred bytes that exist only so a coarse level has
  something to point at: 150,000 of them.
- **Where it breaks first: the folder scan.** Every relink reads every
  store's description, nine files each, 90,000 reads on this plate, repeated
  every thirty seconds while the scan grows. On a share that single scan
  takes longer than the interval. The register removes it, and it is the
  first target.
- **Second: the file count.** Millions of small files are beyond what a
  Windows share or a backup tool handles gracefully. Sharding the position
  stores is the answer, and the writer can already bundle the full-size
  level when asked; the bridge's writer never asks. Sharding must never touch
  the kept coarse levels, which are patched one piece at a time: a partial
  write into a shard rewrites about half the shard, which the Viewer measured
  and wrote down. Whether a position still needs its five tiny levels once
  the coarse levels are kept elsewhere is decided in the data-layer record;
  dropping them halves the file count again.
- **Third: the bridge's write rate.** About four hundred directory entries per
  position on a share costs a second or more per position in metadata alone,
  and a scan that lands a position a second falls behind its own conversion.
- **Fine levels are assembled on demand.** At fine zoom a tile lies inside one
  position; answering it is one read.
- **Coarse levels are kept and patched, in one canonical placement.** Zoomed
  out, one 512-voxel piece at the coarsest level touches four thousand
  positions, and warming the kept levels of three channels is about 170,000
  chunk reads: seconds on a local drive, tens of minutes on a share. Those
  levels are precomputed on disk and updated as each position lands,
  touching only the pieces the landing's footprint dirties, synchronously
  with the landing and off the stage's own path, the way the Viewer's rule
  already works. They are kept in the table placement, which is the default
  and what exists; a different placement at coarse zoom is served from
  projections or not at all, and a custom offset per stack cannot be
  precomputed. The kept levels for this plate are a few hundred megabytes,
  well inside the ten-per-cent budget.
- **The boundary rule: fan-in and share, from the plan.** A level is served
  lazily while any tile of it touches at most K positions, and kept from the
  first level where a tile touches more than K; the composer already knows
  which tiles fall in each piece. K depends on local disk versus share, on
  the chunk size at that level, on how many reads run in parallel, on how
  many channels and planes one frame needs, and on whether the composer's
  block cache is warm; it is measured on the harness. The Viewer's existing
  rule, keep every level holding at most one per cent of the voxels, answers
  disk rather than latency; the two agree on this plate and diverge for small
  fields and sparse plates, so the kept set is the union of both. K is
  evaluated over the planned positions in the register, as a maximum over
  tiles, so the boundary never moves under the operator while a scan lands.

## The engine itself

- **Tiles, not arrays.** A tile is addressed by source, level, time, channel,
  depth, row, column, and the source's revision. The drawing path never sees
  zarr.
- **One worker that fetches and decodes, from the start.** The measured
  advantage of neuroglancer was fetching and scheduling off the drawing
  thread, not decoding; decoding a piece takes well under a millisecond.
  Pre-decoded pieces from the Viewer would double the bytes over a share for
  no gain, so that idea is dropped. Adding the worker later would mean
  rewriting the cache's edges, so it is there from the first commit.
- **Requests have an order and a limit.** Wanted tiles are fetched nearest
  the view centre first and coarser levels first, a fixed number in flight at
  once, and a request that scrolled away is cancelled. Both decide the feel.
- **Level of detail.** Chosen from the zoom against each level's voxel size in
  micrometres; a coarser level stands in while the finer one loads.
- **Placement.** Each tile is a textured rectangle at its true micrometre
  position, following the voxel-edge rule already settled, so the half-voxel
  disagreements do not return.
- **Channels.** One texture slot per tile per channel; window, colour, colour
  map and alpha as shader inputs; channels add together.
- **Cache, in the two-dimensional shape.** Two tiers with byte budgets:
  decoded pixels on the CPU side and uploaded tiles on the GPU side, least
  recently used, with the current plane pinned. The GPU tier is texture
  arrays, one per kind of number (sixteen-bit counts, eight-bit counts,
  32-bit sums, 32-bit labels), each a fixed set of slots. The lookup from
  tile to slot lives in ordinary JavaScript and each tile is drawn as its own
  rectangle with its slot number as an input; a lookup texture on the card
  is three-dimensional machinery for ray marching and the first engine does
  not need it. WebGL2 cannot say how much graphics memory there is, so the
  budget is a number somebody sets, with a sensible default.
- **Coarse stands in for fine, within a channel.** When the tile the view
  wants is not resident, the coarsest resident tile of the same channel that
  covers the place is drawn instead, so the picture is whole at once and
  sharpens as tiles arrive. Never across channels.
- **The hand comes first.** While the operator is dragging or scrubbing, new
  fetches are held and the frame budget goes to drawing what is resident;
  fetching resumes the moment the hand rests. Uploads to the GPU are metered
  per frame so no single upload stalls a frame.
- **Prefetch.** The ring around the view at the current level, and the
  neighbouring depth and time planes while the operator is scrubbing.
- **Keep the last good picture.** A tile stays on screen until its replacement
  has arrived; a slow tile never stalls a frame.
- **Invalidation.** Tiles are keyed by revision. The Viewer publishes, per
  revision, the regions a landing dirtied at each level as boxes (level,
  depth range, row range, column range), even though the first engine uses
  only the row and column part; the engine drops only the tiles that
  intersect them. Today the Viewer's event stream says only "something
  changed" and the page drops every cached chunk on relink; the live-state
  document already carries a per-source revision and is the right document
  to grow boxes into. The composer and the bake patcher already know the
  footprint byte-exactly.
- **Sparse.** Coverage from the register decides which tiles exist at each
  level. Nothing else is requested, uploaded or drawn. An empty piece already
  costs a request and no bytes today, and neuroglancer does not ask twice, so
  the saving is in requests, not bytes; the gate below says so.
- **Measurement hooks, from the first commit.** The same handle the harness
  and the panel rely on today: which layers are held and with what window,
  the current plane, and pixel-exact placement, so the new engine is measured
  by the same harness as the old.

## Navigation

Most of this exists and is kept; the first engine draws the flat top view
only, so the gesture module stays as it is.

- **Dragging pans, the plain wheel zooms.** That is the whole of the gesture
  table for the flat view, settled in `viz_studio/CONTROLS.md` and carried by
  one shared module (`viz_studio/options/gestures.js`) that every engine uses
  unchanged. Every other gesture that could move the operator is refused on
  purpose and counted. The new engine plugs into the same module through
  `getView` and `setView` in micrometres and adds no gestures of its own.
- **Zoom holds the point under the mouse.** Exists in the shared module and
  stays exactly as it is.
- **Depth and time on sliders, not gestures.**
- **The view is in stage micrometres, and it survives** a change of engine,
  a relink, and a run that has captured nothing yet.
- **Look at this.** `lookAt(centre, zoom)` is how the page and the workflow
  steer the canvas. With the register, jumping to a position or a well by
  name becomes a lookup, and "fit what has arrived" becomes possible before a
  scan is complete.
- **A drag can be lent out** to a drawing tool, and **one projection**
  (`project`, `unproject`) places every mark, both kept.
- **A readout follows the pointer** in stage x and y already; z and the pixel
  value of each visible channel under the pointer are the additions.
- **The hand comes first** (see the engine).
- **Later, with the side view:** the view record gains a direction, overlays
  are hidden or re-projected, and the drag pans in x or y and z.
- **Worth adding after the numbers, none a gate:** a scale bar; keyboard
  nudges for pan, zoom, depth, time and fit; double-click to centre; pinch on
  touch screens; zoom limits; the view in the page address and the last view
  remembered per run; the view saved as a picture with its scale bar.

## Decisions on the first review

The review is at `docs/reviews/2026-09-02-review-of-the-rendering-engine-design.md`.
Its verdict was "accept with changes" and one re-ordering. Every finding
was checked against the code before being taken; what was checked is said
in the review itself. Taken, and already folded into the sections above:

- the height is not on disk and the writer zeroes it on purpose; the
  register carries it from day one; table alignment is today's arrangement
  and the default; absolute placement is later and needs a projection or slab
  default for flat collections;
- the Viewer's record package is the register; four additions; the bridge
  writes profile, layout and commits;
- the ten-thousand-position arithmetic, and the order in which things break;
- shard the position stores, never the patched coarse levels; kept levels in
  one canonical placement; fan-in and share as a union, from the plan,
  patched synchronously off the stage's path;
- a worker that fetches and decodes from the start; texture arrays with one
  format each and a JavaScript lookup; request priority and concurrency; the
  gate on requests rather than bytes;
- the window authority keyed by (channel, kind of picture); a label row kind
  that is never measured; stand-in within a channel only;
- the side view changes the view and invalidation contracts; dirty regions
  published as boxes from the start;
- the corrections to stated facts (the pointer readout exists; sharding is
  full-size level only; `viv-under` matched neuroglancer on a plane change;
  segmentation rows exist in the Viewer but nothing on the operator page
  draws them; the live-state document already carries a revision);
- the cuts from the first engine: side view, absolute and custom placement,
  sum and mean projections, precomputed projections, the label shader, the
  GPU-side lookup, the navigation extras.

Not taken, and why:

- **Making the engine conditional on the data-layer measurement.** The
  review proposes building the data layer under `neuroglancer-under`, running
  the gates, and writing the engine only if they fail. The order is right and
  is kept: the data layer comes first and is measured under
  `neuroglancer-under`, which also sets the baseline the engine must beat.
  But the engine is not only about speed. It is wanted for transparency at
  any layer, for placement anywhere including the side view later, for
  labels, for owning the lookup, and for not depending on an engine whose
  coordinate spaces and all-or-nothing invalidation cost this project weeks.
  Those reasons stand whatever the measurement says. The engine goes ahead
  after the data layer, with the smaller first brief the cuts give it, and
  its gates are the measured numbers.
- **Cutting labels, projections and the side view from the design.** They are
  cut from the first engine, not from the design. Each is a named later
  milestone, and what each needs from the first engine so that it does not
  have to be undone (a label row kind and a 32-bit integer format, a
  (channel, kind) window key, boxes for dirty regions, height in the
  register) is in the first engine.
- **The claim that neuroglancer's coordinate spaces are free of cost for us.**
  The review is right that three placements and two directions are a
  coordinate-space system in all but name; the first engine has one placement
  and one direction, which is why it is first. The cost is paid when the
  later milestones come, and it is smaller than rank-n transforms.

## Facts checked against the code, and what is new

- Exists: the Viewer's record package (profile, layout revision, commit event,
  signed truth file, synchronous coarse rebuild); the change event stream and
  revisioned live-state document; per-piece validators during a live run;
  segmentation rows in the Viewer's config; byte-exact footprint knowledge in
  the composer and bake patcher; the harness's synthesised coverage; the
  shared gesture module with pointer-anchored zoom; the sliders; the view in
  micrometres; the pointer readout in x and y; sharding of the full-size level
  in the storage writer.
- New: the bridge writing the register; height in the register; a
  "will not arrive" event; coverage on the operator page; dirty boxes
  published per revision; the fan-in rule; a kept-and-patched coarse pyramid
  for bridge-written runs; the (channel, kind) window key; a label row kind;
  a label layer on the operator page; the engine itself.
- Not yet measured, and decisive: K on a local disk and on the real share;
  whether a position still needs its tiny levels once coarse levels are kept;
  the bridge's conversion rate on a share; whether whole-stack projections
  need precomputing.

## Gates

The data layer is done when, under `neuroglancer-under`, on a plate of many
positions:

- opening a run reads the register and never lists the positions folder;
- a relink of a grown run costs a fingerprint check, not a scan;
- the kept coarse levels answer a coarse tile in one read, and a landing
  patches exactly the pieces its footprint dirties, synchronously;
- coverage removes every request for a position that has not arrived.

The engine is done when, on the harness, on the same plate:

- first picture is no slower than neuroglancer's over the same data layer;
- navigation latency at the ninety-fifth percentile is no worse;
- requests for the same navigation are fewer, and bytes no more;
- memory stays within the budget the cache was given;
- a landing during viewing dirties exactly its footprint and nothing else;
- every panel state (declared, provisional, settled, waiting, unreadable,
  absent) reaches the screen the same way it does with neuroglancer;
- it opens our own data as it is written today, unchanged: a bridge run
  whose fields arrived as our flat OME-TIFFs and were converted at the door,
  and an OME-Zarr transfer of ours in 0.4 or 0.5 with the five axes. No
  other format is a gate, and no conversion tool outside the writer is
  needed.

## Order of work

1. The data-layer design record: the bridge writing the Viewer's register,
   the four additions, coverage, dirty boxes, the fan-in rule, sharding of
   the position stores, the tiny-levels decision, the re-scan decision.
   First, because everything else depends on it.
2. One review pass on that record, the way the last rounds were done.
3. The data layer built and measured under `neuroglancer-under`: the four
   data-layer gates, and the baseline numbers the engine must beat.
4. The engine design record with the smaller first brief: flat top view,
   table placement, slices and the maximum projection, channels as an
   overlay, the contract carried through with the (channel, kind) key, the
   worker, the texture arrays, the measurement handle. Then the engine in
   stages: data source and cache, headless and testable without a browser;
   the renderer; the fourth option beside neuroglancer; the numbers.
5. Later milestones, each with its own short record: labels; sum and mean
   projections; absolute placement and the projection or slab default;
   the side view with its two contract changes; the navigation extras.
6. Only after that: the three-dimensional phase, starting from the two
   prior-art notes and the same cache.
