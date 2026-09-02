# A rendering engine of our own, and the register that feeds it

Date: 2026-09-02. Status: high-level design for discussion. Nothing here is
implemented; this records the choices made in conversation so they can be
gone over one by one.

## What we want, in one paragraph

A drawing engine that is ours, fitted to microscope acquisitions: many
thousands of positions placed anywhere on the stage, any number of channels,
depth and time, transparency where the picture is sparse, labels drawn as
labels, and an honest picture of what is still arriving. It should be at least
as fast as neuroglancer on our own data, and it should get there by owning the
lookup: which positions a tile touches, which pyramid level answers it, and
what is precomputed rather than assembled on the fly.

## Choices already made

- **We build it ourselves.** Not Viv, not deck.gl; both were measured and are
  slower than neuroglancer for this work. Neuroglancer's chunk scheduling and
  rendering are the reference and the inspiration, not the dependency.
- **Neuroglancer stays as the reference.** It remains the engine the harness
  compares against. The new engine replaces it on the operator page only once
  it beats it on the harness's own numbers.
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
- **Labels are a first-class layer.** Segmentation and label images draw with
  their own shader: integer values, a colour per object, one object
  highlighted, no brightness window.
- **One three-dimensional stage space.** The engine's world is the stage in
  micrometres, with x, y and z. Every position sits at its own x, y, z corner
  from the acquisition record, and every plane of it at its own height. The
  two-dimensional view is a plane through that space at the depth the slider
  chooses, measured in stage micrometres rather than in plane numbers, so an
  overview taken at one height and a focus stack spanning another share one
  z axis and one slider. A position is drawn on the view plane when the plane
  falls inside the depth its voxels cover, by the voxel-edge rule; a position
  the plane misses is not drawn, and the slider's travel is the union of what
  every position covers. Neuroglancer forced every store's height to nought to
  get them on screen together; owning the space removes that trick, and it is
  the same space a volume renderer draws later.
- **Three ways of slicing that space, all two-dimensional.**
  1. *Absolute.* Positions sit at their true x, y, z. The slider moves a
     horizontal plane down through the whole space from the top, and each
     position is drawn only where that plane passes through its own depth.
     This is how the picture is really laid out on the stage.
  2. *Aligned.* The z-stacks are lined up so one move of the slider cuts
     through all of them at the same relative depth: dropped to the table
     (bottoms aligned), raised to the ceiling (tops aligned), or a custom
     offset per stack. The slider then moves in relative depth, and every
     stack is on screen at once, however differently they were focused.
  3. *From the side.* The view turns ninety degrees into the screen, so the
     screen's vertical axis is z and "up" on the stage runs down into the
     screen: a cross-section along x and z, or along y and z, at the row the
     other slider chooses. Still a slice, drawn the same way; no volume
     rendering.
- **Two directions, two placements, and projections.** The direction of the
  view is from the top or from the side. In either direction the placement is
  absolute or aligned. And in either direction the picture is a single slice
  at the slider's depth, or a projection through a chosen range of depth:
  the sum, the mean, or the maximum of every plane in that range. A maximum
  projection from the top is the ordinary way to see a whole stack at once;
  the same from the side is a stack's profile.
- **What a projection means for brightness.** A sum can exceed what the
  camera's numbers can hold, and a mean flattens them, so a projection is
  never drawn through a slice's declared window. Its window is measured, per
  channel, per kind of projection, and is said to be measured. Projections
  of a whole stack are precomputed and kept per position, per channel and
  per level alongside the kept coarse levels, because they are asked for
  again and again and change only when that position lands; a projection of
  a custom range is assembled on demand.
- **What the side view costs, said plainly.** Every position store keeps its
  pyramid decimated in height and width only, one plane per chunk. A slice
  from the side reads one row out of every plane's chunk, which is many small
  reads for one screen. Either the kept levels carry a copy chunked along z
  for the side view, or the side view is accepted as slower on fine levels;
  which one is a measurement, and it goes in the data-layer record.
- **Objects may be placed anywhere.** A position is drawn at its true
  micrometre placement in that space, on or off any chunk grid. Rotation is
  left open for later but nothing in the design forbids it.
- **Transparency at any layer.** Every source and every channel has an alpha,
  so a sparse acquisition lets whatever lies beneath it show through, at any
  depth of the stack of layers.
- **Collections are the unit of loading.** Focussing, overview and target are
  different acquisition types, and each is its own collection: its own
  register, its own positions folder, its own heading in the panel with an
  eye and an opacity for the whole, and its own choice of placement, absolute
  or aligned. Collections are loaded together or one at a time, and one run
  may hold any number of them. This is the grouping the Viewer and the panel
  already use; the new engine keeps it rather than flattening everything into
  one list.
- **The display contract stands.** Channel names and colours come from the
  acquisition record, there is one authority for the display window (the
  panel and the Viewer's measurement), a window is either declared, measured
  and provisional, measured and settled, or absent, and the engine draws
  nothing through a window nobody has given it. The engine consumes this
  contract; it never rediscovers it.
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
  transfers work as sources; new positions are written as 0.5.
- **What this rules out, on purpose.** Serving tiles straight out of TIFF
  files. It would need a second tile server and a second cache path, and the
  conversion is already paid at landing.
- **The register records the origin.** Which TIFFs a position came from, so
  provenance survives the conversion.

## The register: one file, four readers

The link that makes ten thousand positions possible is a register of the
acquisition, written before the first field lands.

- **Who writes it.** The bridge, at scan start, at the same moment it publishes
  the display contract (`zmart-acquisition.json`). It already holds the whole
  list of planned positions then.
- **What it holds.** Every planned position: its label, its stage coordinates,
  its expected size in voxels and micrometres, its channels, depth and time
  extents. As fields land, the writer commits each one to the register, so the
  register also says what has arrived.
- **Who reads it.**
  1. The Viewer, instead of listing folders and reading every store's
     description on every check.
  2. Coverage: which positions exist, per level, so nothing empty is ever
     requested, uploaded or drawn.
  3. The incremental coarse pyramid, to know which kept tiles a landing
     dirties.
  4. The engine's own lookup: which positions touch a tile at a level.
- **What already exists.** The Viewer has a manifest-governed way to open a
  live run, used by its replay and its governed picture. The bridge's position
  writer does not write one yet.
- **The open question, first in line.** Whether the Viewer's existing manifest
  fits the bridge's writer as it is, or needs a variant for positions planned
  ahead versus positions arriving.

## The data layer: what is kept, what is assembled

Ten thousand positions is won or lost here, not in the renderer.

- **Fine levels are assembled on demand.** At fine zoom a tile lies inside one
  position; answering it is one read. Nothing needs precomputing.
- **Coarse levels are kept and patched.** Zoomed out, one tile covers
  thousands of positions. Those levels are precomputed on disk and updated
  incrementally as each position lands, touching only the tiles the landing's
  footprint dirties. This is the persistent, incremental form of the bake the
  Viewer already has, and what the lazy-pyramid design was written for.
- **The rule for where the boundary sits.** By fan-in, not by size. A level is
  served lazily while any tile of it touches at most K positions, and kept
  from the first level where a tile touches more than K. K is measured on the
  harness: the point where assembling a tile on the fly takes longer than the
  frame can wait, on a local disk and on a share. The current code pins levels
  by their share of total voxels; that rule answers a different question.
- **Why keeping is cheap.** The kept levels are coarse and hold a small share
  of all voxels, so they cost little disk even on a huge plate.
- **Small files.** Many positions with their own pyramids make many files.
  Sharded zarr version 3 stores, which the writer can already produce, are the
  known answer; to be measured, not assumed.

## The engine itself

- **Tiles, not arrays.** A tile is addressed by source, level, time, channel,
  depth, row, column, and the source's revision. The drawing path never sees
  zarr; a data source turns tile addresses into decoded pixels, in workers.
- **Level of detail.** Chosen from the zoom against each level's voxel size in
  micrometres; a coarser level stands in while the finer one loads.
- **Placement.** Each tile is a textured quad at its true micrometre position,
  following the voxel-edge rule already settled for the composite, so the
  half-voxel disagreements do not return.
- **Channels as a colour overlay, the way it is now.** Every channel is drawn
  in its own colour or colour map and the channels add together on the
  screen, so a place that recorded green and red is yellow; each has its own
  window, colour, colour map, eye and opacity, exactly the controls the panel
  offers today. One texture per tile per channel; window, colour, colour map
  and alpha as shader inputs. Packing several channels into one texture is a
  later saving, not a starting point.
- **Cache.** Two tiers with byte budgets: decoded pixels on the CPU side and
  uploaded textures on the GPU side, least recently used, with the current
  plane pinned.
- **Prefetch.** The ring around the view at the current level, and the
  neighbouring depth and time planes while the operator is scrubbing, since
  that is the motion a stack viewer lives on.
- **Keep the last good picture.** A tile stays on screen until its replacement
  has arrived; a slow tile never stalls a frame; requests that scrolled away
  are cancelled.
- **Invalidation.** Tiles are keyed by revision. The Viewer publishes, per
  revision, the rectangles a landing dirtied at each level; the engine drops
  only the tiles that intersect them. Today the Viewer publishes only "something
  changed" and the page drops every cached chunk on relink, so this is a new
  route on the Viewer side, built on footprint knowledge the composer already
  has.
- **Sparse.** Coverage from the register decides which tiles exist at each
  level. Nothing else is requested, uploaded or drawn.
- **Measurement hooks.** The same handle the harness and the panel rely on
  today: which layers are held and with what window, the current plane, and
  pixel-exact placement, so the new engine is measured the same way as the
  old.

## Facts checked against the code, and what is new

- Exists: the Viewer's change event stream and revisioned live-state document;
  per-piece validators during a live run; segmentation rows in the Viewer's
  config; the manifest-governed live run; byte-exact footprint knowledge in
  the composer and bake patcher; the harness's synthesised coverage.
- New: a register written by the bridge; coverage on the operator page; dirty
  rectangles published per revision; the fan-in rule; a kept-and-patched
  coarse pyramid for bridge-written runs; the engine.
- Not yet measured, and decisive: where neuroglancer's time goes on a sparse
  plate (decoding, upload, or scheduling), and whether serving pre-decoded
  tiles from the Viewer removes the need for worker decoding at all.

## Gates

The engine is done when, on the harness, on a sparse plate of many positions:

- first picture is no slower than neuroglancer's;
- navigation latency at the ninety-fifth percentile is no worse;
- bytes fetched for the same navigation are fewer, because empty tiles are
  never asked for;
- memory stays within the budget the cache was given;
- a landing during viewing dirties exactly its footprint and nothing else;
- every panel state (declared, provisional, settled, waiting, unreadable,
  absent) reaches the screen the same way it does with neuroglancer.

## Order of work

1. The data-layer design record: register, coverage, dirty rectangles, the
   fan-in rule, sharding. Written first, because the engine depends on it.
2. One review pass on that record, the way the last two rounds were done.
3. Measurements on the harness that fix K and say where neuroglancer's time
   goes.
4. The engine design record, then the engine in stages: data source and cache
   headless and testable without a browser; the renderer; the fourth option
   beside neuroglancer; the numbers.
