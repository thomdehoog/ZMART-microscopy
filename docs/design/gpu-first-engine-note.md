# What a GPU-first engine means for us, with evidence

This note answers one question: now that the viewer must stay quick and
responsive at ten thousand positions with four channels showing, and the
graphics card is the place we optimise for, what does that mean concretely
for the engine described in `own-rendering-engine-and-position-register.md`
("the record") and in step 4 of `own-rendering-engine-detailed-plan.md`
("the plan")? It is written for a microscopist. Every graphics term is
explained the first time it appears. Facts are separated from inferences;
a fact is something read in the pinned source or stated in a specification,
an inference is my reasoning from those facts. Every neuroglancer path below
is relative to `viz_studio/frontend/node_modules/neuroglancer/lib/`, version
2.41.2. The paste-back list at the end is ordered by consequence.

A few words first. The *graphics card* (or *GPU*) is a second computer inside
the PC, built to do the same small sum on millions of pixels at once. The
*main thread* is the one line of work the browser runs the page on; anything
slow there freezes the page. A *texture* is a block of the card's memory that
holds pixels; an *upload* copies pixels into one. A *shader* is the small
program the card runs per pixel to turn stored numbers into a colour. A *draw
call* is one instruction from the page to the card, "draw these rectangles
with that shader"; a *uniform* is a number handed to the shader before it,
such as a brightness window. *WebGL2* is the browser's interface to the card;
*WebGPU* is its newer successor.

## 1. What neuroglancer does on the card, and what it does on the processor

**Facts, on the card.**

- *A texture per chunk.* Each chunk that reaches the card gets its own
  texture, created at upload and deleted at eviction
  (`sliceview/single_texture_chunk_format.js` lines 78 to 94). The texture's
  shape is worked out once per chunk shape and remembered
  (`sliceview/uncompressed_chunk_format.js` lines 69 to 74); a chunk with two
  non-unit axes becomes a flat texture, three becomes a volume texture (line
  287).
- *Sixteen-bit counts stay sixteen-bit integers.* A uint16 chunk is uploaded
  as the integer format `R16UI` with the array left as `Uint16Array`
  (`webgl/texture_access.js` lines 92 to 98 and 156 to 167); uint32 becomes
  `R32UI` (lines 106 to 112, 180 to 191); a 64-bit label becomes two 32-bit
  halves in `RG32UI` (lines 204 to 215); float32 becomes `R32F` (216 to 227).
  The shader reads them with an unsigned-integer sampler (the `u` prefix,
  line 128). Nothing is converted to 8-bit on the way.
- *Nearest-neighbour sampling only.* Every raw texture is set to `NEAREST`
  filtering with edges clamped (`webgl/texture.js` lines 17 to 38). Any
  smoothing between voxels is done by the shader itself, fetching the
  neighbours and mixing (`sliceview/volume/frontend.js` lines 43 to 65).
- *Windowing in the shader.* The brightness window is applied as
  `(value - low) * scale` on the count converted to a float
  (`webgl/lerp.js` lines 77 to 92 and 121); the default image program is
  `emitGrayscale(normalized())` (`sliceview/volume/image_renderlayer.js`
  lines 31 to 35), and the layer's opacity multiplies the alpha (lines 43 to
  51, uniform at 99 and 104). The window, colour and opacity are uniforms
  set before drawing (line 105); a program is compiled once per chunk format
  and histogram setting and cached (`sliceview/volume/renderlayer.js` line
  312). Our adapter relies on exactly this: window and colour are controls,
  a colour map is the one thing that recompiles
  (`viz_studio/options/neuroglancer-under/viewer.js` lines 1580 to 1600).
- *Blending between layers, one pass per layer.* Each visible layer is drawn
  in its own pass over an offscreen picture (a texture drawn into instead of
  the screen; `sliceview/frontend.js` lines 162 to 167 and 426 to 440); the
  first layer overwrites, later ones blend, additively when asked
  (`image_renderlayer.js` lines 112 to 120; `sliceview/renderlayer.js` 131
  to 141). Our adapter makes every channel a separate additive layer
  (`viewer.js` lines 676 to 688), so four channels are four passes, each
  re-walking its visible chunks and re-binding its textures.
- *Coarse under fine by the depth test, first writer wins.* The depth test
  is a per-pixel rule that lets a new fragment through only if it is nearer
  than what is already there. Neuroglancer turns it on with `LESS` and clears
  it per layer (`sliceview/frontend.js` lines 433 to 436), and every chunk is
  drawn at the same depth, zero (`sliceview/volume/renderlayer.js` line 80).
  With equal depths and `LESS`, whoever draws a pixel first keeps it; sources
  are ordered finest first (`sliceview/base.js` line 191, drawn at
  `renderlayer.js` 406), so a coarse chunk drawn later never paints over a
  fine one. That costs one compare per pixel and no overdraw.
- *One shared fill-value texture.* An absent chunk is given a one-voxel
  texture holding the fill value, with zero strides so every lookup lands on
  that voxel, shared per data type and fill value
  (`uncompressed_chunk_format.js` lines 253 to 315).
- *The time-sliced upload.* Deliveries are applied on the main thread until
  30 ms of wall-clock time have passed, then the rest wait 30 ms
  (`chunk_manager/frontend.js` lines 124 to 172); the upload itself is a
  `texImage2D` with a fresh texture each time (`texture_access.js` lines 280
  to 311, called from `single_texture_chunk_format.js` line 84). Neuroglancer
  never uses `texSubImage2D`, pixel unpack buffers or texture arrays
  (searched: none in the library).
- *Histograms on the card.* Extra 8-bit outputs of the offscreen picture
  receive the windowed value (`sliceview/frontend.js` 379 to 407;
  `renderlayer.js` 270 to 309); a program then scatters random samples into
  a 256-wide strip with additive blending and reads it back
  (`webgl/empirical_cdf.js` 73 to 193), which needs the float render targets
  neuroglancer requires at start-up (`webgl/context.js` 41 to 45).
- *Frame timing on the card.* A `FramerateMonitor` opens a timer query around
  every frame and reads results later without waiting
  (`util/framerate.js` 37 to 129; `display_context.js` 505 to 506 and 528 to
  529); only the three-dimensional panel acts on it.
- *Drawing on demand.* A redraw is scheduled once per animation frame only
  when something changed (`display_context.js` lines 486 to 488).

**Facts, on the processor.**

- Per frame, per source, the visible chunks are enumerated in JavaScript
  (`sliceview/frontend.js` lines 228 to 238; `renderlayer.js` 450), and each
  present chunk costs a texture bind, a uniform write and one draw call of
  six vertices (`single_texture_chunk_format.js` 59 to 62; `renderlayer.js`
  170 to 176). The rectangle's corners are computed by the vertex shader from
  the chunk box and the slice plane (lines 76 to 84), not by the page.
- The decoded bytes stay in the page after upload: `data` is kept
  (`single_texture_chunk_format.js` line 76) and freeing the card's copy only
  changes the state (`chunk_manager/frontend.js` 60 to 62), and the pointer
  readout reads that copy (`uncompressed_chunk_format.js` 237 to 251).
- Context loss is answered by reloading the page (`display_context.js` 329
  to 340).

**Inference.** For the flat view, neuroglancer already does the arithmetic
on the card: integer textures, windowing, colour, opacity and blending in the
shader, coarse-under-fine by the depth test. What a GPU-first engine moves is
the *organisation* around that arithmetic: four passes become one, a draw
call per chunk becomes one call per batch, a fresh texture per upload becomes
a slot in a pre-allocated pool, the page's second copy of every chunk goes
away, and the absent-ground answer comes from the register instead of a
fill-value texture found one request at a time. The shader work itself is
not where neuroglancer is slow.

## 2. WebGL2 facts that shape the design

Marked *spec* when it follows from the WebGL2 specification (OpenGL ES 3.0
brought to the browser), *measure* when only the microscope PC can say.

- *Integer formats.* `R16UI` and `R32UI` are required formats; they can be
  drawn into (colour-renderable) but cannot be filtered: a `LINEAR` setting
  makes the texture return zeros. So smoothing, if wanted, is our shader's
  job, as it is neuroglancer's. Converting a uint16 to a float in the shader
  is exact, because a 32-bit float holds every integer up to 16,777,216
  (2^24). There is no normalised 16-bit format in core WebGL2; the integer
  route is the right one. (spec)
- *Texture arrays.* A `TEXTURE_2D_ARRAY` is one texture holding many equal
  sized pictures in numbered slots (layers). WebGL2 guarantees at least 256
  layers and at least 2048 pixels a side; desktop cards commonly offer 2048
  layers and 16384 a side, which must be read from the card at start-up
  (`MAX_ARRAY_TEXTURE_LAYERS`, `MAX_TEXTURE_SIZE`; measure). Storage is
  allocated once with `texStorage3D` and one slot is filled with
  `texSubImage3D` without touching the others. A shader picks the slot by an
  integer, so tiles in one array can be drawn in one draw call; with a
  texture per tile, each tile needs its own bind and call. A 512-voxel
  uint16 slot is 512 KiB; 2048 slots are 1 GiB, which is the size of the
  whole graphics budget, so one array per format is enough. (spec for the
  minimums; the actual limits are measured)
- *Instanced drawing.* `drawArraysInstanced` draws the same rectangle N
  times in one call, each copy reading its own row of a small attribute
  buffer (its position in micrometres, its slot, its channel, its level);
  neuroglancer's own `webgl/quad.js` (lines 19 to 40) is exactly this
  helper. Thousands of rectangles cost one call. (spec)
- *How many tiles are on screen.* The card holds a screenful, not the plate.
  At 512-voxel tiles a 3840 by 2160 screen shows about 60 tiles per channel
  per level; at the record's 128-voxel tiles for the finest levels, about
  1,000, so 4,000 draw calls at four channels before the coarser chain. That
  is where a call per tile costs main-thread time and instancing earns its
  place. (inference from the record's tile sizes)
- *Uploads.* `texImage2D` allocates storage and fills it; `texSubImage*`
  fills existing storage. When the typed array matches the format exactly
  (`Uint16Array`, `RED_INTEGER`, `UNSIGNED_SHORT` into `R16UI`) the
  specification needs no conversion; whether Chromium's translation layer
  (ANGLE, over Direct3D 11 on Windows) copies anyway is not knowable from
  the specification. A pixel unpack buffer (`PIXEL_UNPACK_BUFFER`) lets the
  page hand bytes to a buffer first and fill the texture from it; whether
  that is faster in Chromium than a direct upload must be measured. Row
  alignment must be set to 1 for odd widths, as neuroglancer does
  (`texture_access.js` line 294). Chromium runs the card in a separate
  process, so every upload crosses a process boundary through shared memory;
  the cost per byte and per call is a property of the PC. (spec and
  Chromium architecture; the numbers: measure)
- *Timer queries.* `EXT_disjoint_timer_query_webgl2` gives elapsed card time
  for a span of commands, read later without stalling; the result must be
  discarded when the card reports a disjoint event. Chromium has shipped it,
  withdrawn it and restored it over the years, and it is unavailable on some
  drivers and under some blocklists; neuroglancer logs once and carries on
  without it (`util/framerate.js` 38 to 44). Whether it is present on the
  microscope PC's card and under the rig's SwiftShader mode is a measurement,
  and the protocol should record it. (spec; presence: measure)
- *No memory size.* WebGL2 has no call for the card's total or free memory;
  `WEBGL_debug_renderer_info` names the card and nothing more. The budget
  stays a number fixed in the protocol, as the record says. (spec)
- *Context loss.* The browser may take the card away at any time (a driver
  reset, a GPU-process crash, too many contexts, a laptop switching cards);
  every texture, buffer and program is gone and `webglcontextlost` fires.
  On Windows, a single card command that runs longer than about two seconds
  triggers the driver's timeout-and-recovery reset, which is a context loss
  for us; a long projection pass can cause it. (spec and Windows behaviour;
  inference that our passes could reach it)
- *Float render targets.* Drawing into 32-bit float textures needs
  `EXT_color_buffer_float`, and blending into them needs `EXT_float_blend`
  (`webgl/context.js` lines 41 to 55); integer targets are core but cannot
  blend at all. (spec)

## 3. "Compose in the shader", for this data

**What one pass does.** For every screen pixel, for each visible channel:
fetch the count from that channel's resident tile, apply the window, look
up or multiply the colour, scale by the channel's opacity, and add. Window,
colour and opacity are uniforms per channel; the colour map is a 256-wide
lookup texture, so choosing a map never recompiles (the adapter's one
recompile goes away). A program is compiled once per (data kind, channel
count). Four channels are four fetches per pixel, trivial for any card.

**The resolve pass, and why one pass is not quite enough.** Coarse-under-fine
is per channel: at one pixel channel A may have its fine tile and channel B
only a coarse one, so a single pass over all channels cannot draw one
rectangle for both. The clean answer is two stages: first, per channel,
*resolve* the finest resident tile into a screen-sized `R16UI` target plus a
mask, drawing finest first with the depth test as neuroglancer does (first
writer wins, no overdraw); then one *compose* pass reads the resolved planes
and writes the colour. The resolved planes are tiny (a 900 by 700 window at
four channels is about 5 MB), the compose pass costs the same whatever the
tile count, and the planes are also what a pointer readout, a live histogram
or a later projection would read. (inference; the record's "depth test or
paint order" is answered: depth test, in the resolve pass)

**The coverage mask.** Ground never imaged must draw as nothing, not black
(the adapter's `imaged()` alpha, `viewer.js` lines 1625 to 1642). Two
mechanisms, both used: *geometry* for whole tiles, because the register's
coverage says which tiles exist at each level, so an absent tile is simply
not drawn and costs neither a request nor a texture; and a *mask texture* for
tiles that are partly covered (a position's edge, a gap between positions).
A one-byte-per-voxel mask is half the size of the pixels again; packing eight
voxels to a byte makes it a sixteenth, and unpacking one bit in the shader is
one fetch and one shift. The mask must travel and land with its pixels, as
the record says. Where a collection overlaps another, the mask decides
whether the lower one shows through, and the collection's opacity is a
uniform in the compose pass. Overlap *within* a collection is already settled
by the composer in the tile's pixels, so the engine never resolves two tiles
of one collection at one pixel. (inference)

**Projections, later.** With a stack's planes in a texture array (one slot
per plane per tile), a projection is one shader pass that loops over the
slots at each pixel: a maximum is exact in any format; a sum kept as an
unsigned 32-bit integer is exact up to 65,537 full-scale planes and is
written to an `R32UI` target without blending; a mean is that sum divided by
the plane count at display time. A 32-bit float accumulator is exact only up
to 256 full-scale planes (65,535 by 256 is just under 2^24), so the integer
route is the honest one for sums. The limits: only *resident* planes can be
projected, so the range must be uploaded first (section 4); the loop runs
once per pixel per plane, and a range of hundreds of planes at a fine level
is where Windows's two-second reset becomes a risk, so long ranges are split
into passes of a stated size; and the resident bytes are viewport voxels
times two bytes times channels times planes (a 4K screen at four channels is
about 66 MB per plane), which bounds the range the card can hold and is why
the record's "whether whole-stack projections are precomputed is measured"
stays. The sampled meaning of a coarse projection is the record's, unchanged.
(spec for the arithmetic; the rest inference)

## 4. The upload path is the cost to minimise

**What to measure**, on the microscope PC, headed, on the real card:

- bytes uploaded per second and uploads per frame, over the ten-step trace;
- time per upload by size (128 and 512 voxel tiles) and format (`R16UI`,
  `R32UI`, the packed mask), with `texSubImage3D` into a pre-allocated array
  against `texImage2D` into a fresh texture, and with and without a pixel
  unpack buffer;
- main-thread time inside the upload calls (`performance.now` around them
  measures the hand-off, not the card's work), and completion time using a
  fence (`fenceSync` and `clientWaitSync` with a zero wait, polled) so the
  card's side is seen without stalling;
- frames in which an upload made the frame late, counted.

**How neuroglancer's budget works.** Its 30 ms is wall clock per batch of
deliveries, not per drawn frame, and a batch that overruns waits 30 ms
before the next (`chunk_manager/frontend.js` 124 to 172). Ours should be per
frame, spent before the draw, with a byte and an item bound, because one
512-voxel uint16 tile is 512 KiB and a cold 4K screen at four channels is
about 66 MB; at an upload rate that must be measured, that is several frames
at best, and the order (visible first, nearest the centre first) decides what
the operator sees while it lands. (inference)

**Decoding into the final form in the worker.** The Viewer's pieces are
little-endian bytes then zstd (`viz_studio/building/composer.py` lines 106
to 109). Decoding in the worker yields a byte buffer that is already the
exact layout the texture wants; viewing it as `Uint16Array` costs nothing
(`texture_access.js` 287 to 293 does this), and transferring the buffer
moves ownership without a copy. So the main thread converts nothing: it
receives a buffer, calls one `texSubImage3D`, and drops the buffer. The mask
is unpacked, packed or generated in the worker the same way. The page keeps
no second copy of the pixels; the readout and the panel's measurement use
the record's "bytes back" call, which asks the worker. A partial edge tile
is uploaded at its own size into a full slot and drawn with a scaled
rectangle, never padded on the processor. (inference)

**"Resident before visible."** Prefetch means *on the card*, not merely
decoded: the tier "prefetched" is defined as uploaded, so a step of the depth
or time slider is a change of slot index and a draw, with zero uploads on
the frame it happens. That puts the neighbouring planes inside the graphics
budget, spends upload time while the view is still, and is the whole
difference between a scrub that stutters and one that does not. (inference)

**Context loss, reconciled with "once and stays."** When the card is lost,
every slot is gone. Re-fetching a screenful is the slow path; the worker
keeping the *compressed* pieces of the visible and prefetch tiers (a few
megabytes) lets the page re-decode and re-upload without a request, and the
view in micrometres survives as the navigation section promises. Pixels go
to the card once in the normal case; the compressed copy is the insurance.
(inference)

## 5. Card time as a gate

- *Card time per frame*: one timer query around the frame's draw, and a
  second around the frame's uploads (queries cannot nest but can follow one
  another), results read a few frames later, disjoint frames discarded. This
  is what neuroglancer's monitor does for the whole frame; the adapter can
  expose its `getLastFrameTimesInMs()` so both engines report the same
  number the same way. (fact for neuroglancer; the split is ours)
- *Main-thread time per frame*: `performance.now` around the frame callback,
  plus the browser's long-task observer for stalls over 50 ms, plus a
  Chromium trace through the browser's protocol (the harness already uses
  Playwright, which can open a protocol session) for the GPU process's own
  timeline when a number needs explaining. The record's memory reader goes
  through the same protocol.
- *What the harness needs*: a headed, real-card mode of `drive.py` beside
  its SwiftShader mode (line 52), the card's name recorded from
  `WEBGL_debug_renderer_info` and whether the timer extension was present,
  the measurement handle gaining `gpuMsPerFrame` and `uploadMsPerFrame`
  beside the counters, and the same numbers from the adapter.
- *A fair comparison*: same page, window, card, data layer, trace and
  definition of settled; card and main-thread time reported beside latency,
  never instead of it, because the operator feels latency. A card-time gate
  is a budget per frame at four channels, fixed in the protocol after phase 0
  has measured the card, at the ninety-fifth percentile like the others.
- *Under SwiftShader* every card number describes the processor; such
  results are labelled and never compared with a headed run.

## 6. WebGPU

**What it adds.** Compute shaders: programs that run over data without
drawing, which suits a projection or a histogram directly, with atomic
counters. Storage buffers: the card reading arbitrary byte arrays, so a
uint16 tile could be read as packed 32-bit words without a texture at all.
Explicit queues and `writeTexture`, a clearer upload model. Timestamp
queries as a named feature, though browsers coarsen them for privacy.
Sixteen-bit integer textures exist and are equally unfilterable. (spec)

**What it costs.** No neuroglancer comparison on the same interface, so the
gates would compare two interfaces on one card. Support to verify on the
microscope PC: Chromium on Windows has shipped WebGPU since 2023 over
Direct3D 12, but a driver blocklist or a remote-desktop session can remove
it, and the rig's software mode would need its own flags. A second renderer
to write, test and keep, before the first has passed a gate.

**Recommendation.** Not for the first engine. Record `navigator.gpu` and the
adapter's description in the phase-0 protocol at no cost, so the fact is
known. Draw the boundary between the cache (tiers, identities, the worker)
and the renderer (pools, passes) so a renderer can be replaced, and revisit
at the projection milestone if the shader-pass projections hit the range,
precision or reset limits of section 3. (inference)

## 7. Risks the GPU-first choice introduces

- *A weak or shared card.* A laptop's integrated card shares main memory and
  is also the acquisition software's card; the 1 GiB budget then competes
  with everything. The budget is a protocol number per machine class, and
  the engine degrades by residency (coarser levels, fewer prefetched planes),
  never by refusing to draw.
- *No hardware graphics at all.* A remote-desktop session on Windows, a
  blocklisted driver or the rig's software mode gives SwiftShader. The engine
  must still run there, and the gates must say which renderer produced the
  number; a result on SwiftShader is a result about the processor.
- *Context loss becomes a bigger event* because more lives on the card; the
  compressed copy in the worker (section 4) is the answer, and a test with
  `WEBGL_lose_context` (neuroglancer uses it in `webgl/testing.js` line 27)
  belongs in the engine's tests.
- *Long shader passes* can trip Windows's reset; projection passes are split
  by a stated plane count. *Timer queries may be absent*; then the card gate
  cannot be read on that machine and the protocol says so rather than
  passing silently.

## Paste-back

**To the record's "The engine itself":**

- Replace "a texture per tile as neuroglancer does or slots in a texture
  array, decided by measurement" with: one pre-allocated texture array per
  internal format, sized to the budget, a tile a slot filled by
  `texSubImage3D`; the array's layer and size limits are read from the card
  at start-up and recorded; a texture per tile is the fallback only if
  the microscope PC's limits make the array too small, and that is measured
  once.
- Add: drawing is two stages, a resolve pass per channel into a screen-sized
  `R16UI` plane plus mask, finest first with the depth test so the first
  writer wins (neuroglancer's mechanism), then one compose pass that windows,
  colours, weights and adds every visible channel; the record's "depth test
  or paint order" is decided: depth test.
- Add: the page keeps no copy of the pixels after upload; the worker keeps
  the compressed pieces of the visible and prefetch tiers so a lost context
  is re-decoded and re-uploaded without a request; "resident" means on the
  card, and a prefetched slider neighbour is uploaded, not merely decoded.
- Add: the coverage mask is geometry for whole tiles (from the register) and
  a packed one-bit-per-voxel texture for partial tiles, travelling with the
  pixels; absent tiles are not drawn at all, so there is no fill-value
  texture.
- Add: rectangles are drawn instanced, one call per (format, channel, level)
  batch, with per-tile position, slot and scale in an attribute buffer; the
  main thread writes that buffer and uniforms and nothing else per frame.
- Add: programs are compiled once per (data kind, channel count); window,
  colour, opacity and the colour map (a lookup texture) are drawing inputs,
  so no operator action recompiles.
- Add to the upload budget: per frame, before the draw, bounded in bytes and
  items, visible first; the numbers from phase 0's upload measurements.
- Add to "Projections, later": computed on the card by one pass looping over
  resident plane slots, sum as unsigned 32-bit into an `R32UI` target, mean
  as sum over count at display, maximum exact; ranges split by a stated
  plane count against Windows's two-second reset; only resident ranges,
  which bounds the range and keeps the precompute question open.
- Add to "Measurement hooks": `gpuMsPerFrame` and `uploadMsPerFrame` from
  timer queries, absent-and-said-so when the extension is missing.

**To the plan's step 4:**

- 4.3 gains: the texture-array pools, the resolve-and-compose passes, the
  instanced batches, the packed mask, the colour-map texture, the per-frame
  upload budget, the lost-context test with `WEBGL_lose_context`.
- New 4.0, before the record: an upload micro-measurement on the microscope
  PC, headed, on the real card: bytes per second and time per upload by size
  and format, `texSubImage3D` into an array against `texImage2D` fresh, with
  and without an unpack buffer, completion seen by a fence; its numbers fix
  the upload budget and the pool sizes in the engine record.
- 4.4 gains: the adapter exposing neuroglancer's own frame timer through the
  same handle, so the comparison is like for like.
- Step 6's list gains WebGPU as the renderer to reconsider, with
  `navigator.gpu` recorded in phase 0.

**To the gates:**

- Add an engine gate: card time per frame at four channels, at the
  ninety-fifth percentile, within a budget the protocol fixes after phase 0
  measures the card; main-thread time per frame reported beside it; neither
  replaces the latency gate.
- Add to every gate: the renderer name and whether the timer extension was
  present are recorded with the result; a SwiftShader result is labelled and
  never compared with a headed one.
- Add to phase 0: a headed, real-card mode of `drive.py` beside the
  SwiftShader mode, and the card's name, its texture-array limits,
  `navigator.gpu` and the timer extension recorded in the protocol.
- Add a risk: a weak or shared card and a session without hardware graphics
  are machine classes with their own budget numbers; the engine degrades by
  residency and never refuses to draw.
