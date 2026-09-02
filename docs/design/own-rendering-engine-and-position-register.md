# A rendering engine of our own, and the register that feeds it

Date: 2026-09-02, third revision, after two rounds of independent review by
two reviewers each (`docs/reviews/2026-09-02-review-of-the-rendering-engine-design.md`,
`…-by-codex.md`, `…-second-review-…`, `…-second-review-…-by-codex.md`).
Status: high-level design for discussion. Nothing here is implemented. This
records the choices made in conversation, corrected where a review showed a
stated fact to be wrong, and the decisions taken on every finding, including
the ones not taken and why. The second round's verdicts were both "accept
with changes"; the changes are in.

## Words used below, said once

A *tile* is one small square of one zoom level of the picture, the unit that
is fetched, cached and drawn; a *chunk* is the same idea on the storage side,
one small block of an image file. A *piece* is the Viewer's word for a
composed tile of 512 voxels. *Fan-in* is how many positions one tile touches.
*Sharding* is bundling many small chunk files into one large file with a
table at the end. *Decimation* is the way our pyramids are made: every second
voxel along height and width, every plane along depth. A *dirty region* is
the part of the picture a landing changed. *Alpha* is how see-through a thing
is drawn. A *collection* is one acquisition type of one run, such as the
overview. A *profile* is the Viewer's sealed description of an acquisition
(frame shape, data type, voxel size, levels, chunking, channels, room along
time), agreed before the run starts and never changed. A *generation* is the
count of times one position has been captured; a *revision* is the count of
times the whole run's picture has changed. *Provenance* is the record of where
a number came from. *Handedness* says whether the three stage axes follow the
right-hand rule. A *percentile* is a value that a stated share of measurements
fall below; the ninety-fifth is "all but the slowest one in twenty". A *codec*
is the way pixels are compressed on disk. *Residency* is what is currently
held in memory. An *inode* is a file system's own number for a file. A
*schema* is the agreed shape of a record. A *footprint* is the area of the
picture a position covers. *Append-only* means records are added and never
changed. A *texture* is a block of graphics memory holding pixels; a *texture
array* holds many tiles of the same kind of number in numbered slots; an
*internal format* is which kind of number a texture holds. A *shader* is the
small program the graphics card runs to turn stored numbers into colours.
*Back-off* is waiting a little longer before each retry. The Viewer's
"signed truth file" is a small publication marker replaced in one indivisible
file-system step; it is not a cryptographic signature.

## What we want, in one paragraph

A drawing engine that is ours, fitted to microscope acquisitions: many
thousands of positions placed anywhere on the stage, any number of channels,
depth and time, transparency where the picture is sparse, labels drawn as
labels, and an honest picture of what is still arriving. It should be at least
as fast as neuroglancer on our own data, and it should get there by owning the
lookup: which positions a tile touches, which pyramid level answers it, and
what is precomputed rather than assembled on the fly.

## The one decision that was contested, and how it stands

The earlier design record (`lazy-jpeg-pyramids-for-the-viewer.md`, phase 1)
says a new renderer is considered only after the phase-0 measurement on the
microscope PC shows the installed engines cannot meet the bound, and that
measurement has not been run. Codex's first verdict rested on that:
"rethink". Both second reviews accept the decision below as the owner's
product decision, and both ask for the same promises so that phase 0 keeps
its teeth. The promises are made.

The decision, as the project's owner made it: the engine is built. The
reasons are not only speed. It is wanted for transparency at any layer, for
placing positions anywhere on a stage in three dimensions, for labels, for
views from the side and projections later, for owning the lookup over ten
thousand positions, and for not depending on an engine whose all-or-nothing
invalidation and coordinate spaces cost this project weeks. This record
supersedes the "only if the installed engines fail" clause of the earlier
design for the renderer, and says so plainly. The stop on the compact
eight-bit and JPEG pyramid experiment in that design is untouched.

What the owner is knowingly forgoing, in the reviewers' words, because it
should be written where the decision is: several of those reasons are things
neuroglancer already does and the adapter has not exposed (per-layer opacity,
segmentation layers, orthogonal views, layer transforms), and the one cost
that was purely a cost, all-or-nothing invalidation, has already been paid
for by a patch this repository applies to its pinned neuroglancer on every
install. Phase 0 could have said whether adapter work reaches those features
cheaper than an engine does; deciding now forfeits that answer. The strongest
argument on the owner's side is the same patch: a dependency you must patch
to make correct is a dependency you already half own.

The three promises that keep phase 0 meaningful:

1. **Phase 0 runs first, and the harness work it needs is authorised by
   name** (see the order of work): the ten-step trace in the rig's external-run
   door, the adapter fix so that a bridge-written five-axis store is drawn
   rather than placed beside the view, and the breakdown instrumentation on
   both engines. Its fixtures, repetitions, budgets and tolerances are frozen
   before it runs and never relaxed after. Its result is written down as one
   sentence naming the layer that fails, if any, before the data-layer record
   is written.
2. **The operator page stays on `neuroglancer-under` throughout.** The new
   engine is adopted only when it passes its gates over the same data layer,
   on the same pixels; if it misses any gate, neuroglancer remains the
   operator's engine, and a later milestone or a failed engine can be stopped
   even though the intent to build the first engine is settled.
3. **If the data layer under the old engine passes every gate of the earlier
   design**, the engine's first brief shrinks to the features it exists for,
   and it must still beat the old engine on the harness's numbers.

## Choices already made

- **We build it ourselves.** Not Viv, not deck.gl. On the harness, deck.gl
  (`viv-inside`) is plainly and repeatedly slower; `viv-under` matched
  neuroglancer on a single plane change and lost on movement, because
  neuroglancer fetches and schedules off the drawing thread and drops work
  that has been superseded. What neuroglancer does that we must also do is
  written out under the engine, from its pinned source.
- **Neuroglancer stays as the reference.** It remains the engine the harness
  compares against and the operator's engine until the new one passes its
  gates over the same data layer.
- **Two dimensions first, with depth and time on sliders.** The engine draws
  one plane at a time: one moment in time, one depth, every visible channel.
  The two labelled sliders with play buttons stay; neighbouring planes are
  prefetched while scrubbing; a run with one depth or one moment shows no
  slider for it. *Time* is a moment index within a collection; a collection
  with fewer moments is absent beyond its last; aligning collections by
  wall-clock time is a later question.
- **The data is five-dimensional.** Time, channel, depth, height, width, any of
  which may be one long. "Any number of channels" means the schema imposes no
  limit; how many are drawn at once within the latency and memory gates is a
  tested fixture, stated with the gates, and the behaviour beyond it (the
  panel hides the rest) is said.
- **One three-dimensional stage space, defined before it is used.** The
  engine's world is the stage in micrometres, with x, y and z. Two facts the
  first draft got wrong: the position writer, not neuroglancer, sets every
  position's height to nought on purpose, because a flat plate scanned under
  a focus map otherwise composes into a stack two dozen planes deep and the
  operator sees almost nothing; and no file on disk holds a capture height
  today. The writer also replaces the recorded plane heights by one median
  step. So the register keeps, per position and per plane, the raw recorded
  height in micrometres, as provenance and as the input to a later
  calibration, and the store's regular step is what draws; a stack whose
  recorded steps differ from the median by more than a stated tolerance is
  flagged at conversion. Before any placement uses those heights, the
  data-layer record defines the coordinate frame: which way stage z points,
  handedness, units, how a recorded plane centre becomes its two voxel edges
  (half-open intervals, which plane owns a shared edge, irregular, duplicate
  or reversed heights), how observations across channels and moments are
  associated, and the calibration revision the numbers belong to. Placement
  modes are presentation transforms with their own provenance; the
  acquisition's geometry is never rewritten.
- **Placement: aligned at the low edge is today's behaviour and the default;
  absolute comes later.** Every position beginning at height nought is
  alignment at the low edge of each stack, which the operator will know as
  "table"; alignment at the high edge is "ceiling"; both are named by the
  edge until the direction of stage z is guaranteed. Aligned placement has
  one meaning: a common offset in micrometres from the aligned edge, each
  stack showing the plane whose half-open voxel interval contains that
  offset, a shorter stack absent beyond its own depth. One decision the
  reviews asked for: a single-plane position (a flat field) is drawn at every
  offset under aligned placement, because an operator looking at an overview
  under a focus stack wants the overview to stay; it is one voxel thick only
  under absolute placement. A normalised fraction through each stack is a
  different question and, if wanted, a separate mode. A custom offset per
  stack is a later mode that cannot be precomputed. "Absolute" placement,
  each position at its true recorded height, is a later mode: it needs the
  heights, the frame, and for a flat collection a projection or a slab as
  its default, or a slice through it shows two fields out of fifty.
  Placement is part of every composed tile's identity, so the two modes never
  share a cache entry.
- **Views: from the top first, from the side later.** A side view is a
  cross-section along x and z at one y, or along y and z at one x, so it
  needs a slider for the axis it cuts at; a side projection reduces along
  that same axis, never along z. It fixes which way stage z runs on the
  screen, and for each overlay says whether it is hidden or re-projected. It
  changes two contracts the first engine keeps (a direction in the view
  record; dirty regions as boxes), reads one row out of every plane's chunk at
  fine levels, and a transposed copy for it is a data product of its own.
- **Turned positions.** The composer can place a turned position and knows
  its bounding box. The first engine draws rectangles only and refuses a
  layout with a turned position, saying so; rotation is a later milestone.
- **Projections: later, with their meaning stated.** Maximum, mean and sum
  through a chosen range are wanted and stay in the design; none is in the
  first engine. Their arithmetic is written before they are built: the
  pyramid keeps every plane and halves only height and width, so a projection
  at a coarse level is a projection of the samples that level keeps; a
  coarse maximum can miss a small bright object the decimation dropped and a
  coarse sum is not the total signal over the area, and the display names
  that sampled meaning. A mean is a *sample* mean, weighting every acquired
  plane equally, and is named so, because stacks sampled more finely then
  represent physical depth differently; a mean weighted by each plane's
  thickness is a later option. A mean across unequal or missing ranges is a
  sum and a count, never a mean of means; the range is half-open in
  micrometres; the accumulator is chosen from the input type and the plane
  count with overflow refused, not "32-bit" for everything; the result type
  and the missing-plane rule are stated for each kind; across stacks with
  different z steps only the mean is offered; labels are never projected. A
  projection's identity carries its axis, kind, range and recipe version.
  Whether whole-stack projections are precomputed is measured; a precomputed
  one changes on a landing, a later timepoint and a replacement alike.
- **Labels are a first-class layer, written second.** Integer values, a
  colour per object, one highlighted, no brightness window, no projection.
  Nothing on the bridge side produces them yet and the operator page has no
  label layer, so the shader is a second milestone. In the first engine from
  the start: a distinct data kind for labels that is never measured, never
  windowed and never projected, and a texture format for 32-bit integers.
- **Channels as a colour overlay, the way it is now.** Every channel is drawn
  in its own colour or colour map and the channels add together on screen;
  each has its own window, colour, colour map, eye and opacity. Adding is
  between channels only. Where two positions of one collection overlap, the
  one committed later lands on top, the rule the Viewer's record already
  states.
- **Transparency at any layer.** Every source and every channel has an alpha.
  Ground that has not landed is drawn as absent, distinct from an acquired
  black pixel; the cache carries a coverage mask beside the pixels.
- **Collections are the unit of loading, with a durable identity and an
  index.** Focussing, overview and target are different acquisition types,
  and each is its own collection: its own register, its own folder, its own
  heading in the panel with an eye and an opacity for the whole, and its own
  placement. The panel groups by display name today; a collection gets a
  stable identity distinct from its name. A collection whose fields differ
  in size or in any other sealed property is several governed runs, one
  complete profile each, and a small run-level index says which governed
  runs make up one collection and orders them; the panel heading, the eye
  and the opacity hang off that index, and so does every cache key.
- **The display contract stands, carried all the way to the shader.** Channel
  names and colours come from the acquisition record; there is one authority
  for the display window; a window is declared, measured and provisional,
  measured and settled, or absent; the engine draws nothing through a window
  nobody has given it, and never falls back to the camera's range or the data
  type. The authority's key becomes (channel, kind of picture), with "slice"
  the only kind at first; `setChannel` gains the kind; the panel's
  measure-every-row skips label rows; the Viewer's measure route is keyed by
  kind. A projection has its own measured window and its own provisional or
  settled state. Coarse standing in for fine is within one channel only. The
  identity of a tile and what is drawn beside it are separated under the
  engine.
- **What stays as decided before.** Decimation pyramids, capability
  negotiation between bridge and Viewer, omitting the OME channel block when
  a window is undecided, and the stop on the eight-bit and JPEG pyramid
  experiment.
- **The small JPEG previews stay separate.**

## Inputs: two ways in, one form inside

- **Two accepted inputs.** The flat OME-TIFF convention the microscope
  writes today, and OME-Zarr 0.4 or 0.5 with axes in the OME order: time,
  channel, depth, height, width (t, c, z, y, x).
- **One form inside.** Everything is served to the engine as OME-Zarr 0.5
  positions with those five axes; a TIFF input is converted at the door,
  which the position writer already does the moment a field lands.
- **0.4 is read, not written.** The engine only ever sees the Viewer's pieces.
- **Ruled out, on purpose.** Serving tiles straight out of TIFF files.
- **The register records the origin.** Which TIFFs a position came from.

## Not now: three-dimensional rendering

- No volume rendering in this design. Every view is a slice or a projection,
  drawn flat.
- The door is left open by a clean separation of three things, and by nothing
  else: the tile source, the cache policy, and the drawing. A volume renderer
  later reads the same register and source and chooses its own representation
  from measurements and a proper reading of the primary sources.
- The first draft's promises of a fixed atlas and "the same cache with one
  more coordinate" are withdrawn. The prior-art note
  (`prior-art-larger-than-memory-3d-rendering.md`) is corrected in its body,
  not only in a preface: what the systems it surveyed share is bounded
  residency, multiscale chunks, an explicit lookup and a coarse fallback, and
  nothing more universal than that. `prior-art-napari-progressive-loading.md`
  stays as reading for that phase.

## The register: the Viewer already has one, the bridge has to write it

All four reviews agree: the Viewer's `record` package is the register this
design describes, and a second file beside it would be two truths. The work
is on the bridge's side, plus a versioned extension that respects what the
package already refuses to change.

- **What exists, in the Viewer.** A sealed profile per governed run. A
  numbered, never-edited layout revision holding every planned position with
  its origin in whole pixels of the profile's voxel grid, including depth,
  created whole before the first pixel, with a `final` flag nothing sets yet.
  A commit event per arrival, a replacement as a new immutable generation, and
  later timepoint commits; the event kinds are a closed list and a reader
  refuses any other. An append-only event history, the publication marker
  replaced by rename, and a fingerprint that is one file-system call. A rule
  that a zoomed-out piece is rebuilt from committed positions only and
  republished in the same step as the position. Opening from the files alone,
  on any machine, with no bridge. One profile, one layout and one run per
  folder.
- **What the bridge writes today.** Only the position store and the channel
  contract at scan start; every scan of a type under one folder. A re-scan of
  the same type is refused today because the vendor-file move refuses to
  replace an existing image; the store writer itself would empty an existing
  store if it were reached, so the refusal is the bridge's and the data-layer
  record keeps it on purpose. The Viewer opens the folder as an ordinary
  transfer, listing it and reading every store's description, and reopens it
  every thirty seconds while it grows.
- **What the bridge must write, and when, in three documents.** At scan
  start: the profile and the layout revision, with every planned position at
  its intended stage position, in whole pixels as the layout requires, and z
  at nought under the default placement. With each landing: a commit, and a
  new immutable *observation* record beside it holding the actual x, y and z
  of every captured plane in micrometres, its moment and channel coordinates,
  and the vendor files it came from; these are not known at scan start and do
  not belong in the layout. At the end: a lifecycle record. The rule that
  derives the layout's placement from the observation (round to the profile's
  voxel; z to nought under aligned placement, to a plane index under
  absolute) is written once.
- **The versioned extension.** A stable identity for the run and for each
  collection, distinct from the display name and the acquisition type, and
  the run-level index that groups governed runs into collections. The
  observation record above, with the coordinate frame and calibration
  revision it belongs to. A reference to the one acquisition display contract
  and, through it, the map from stable channel key to array index, label,
  colour, valid range, window and window state. A lifecycle record holding a
  terminal state for the run (completed, stopped, failed, with time and
  reason) and the positions skipped or never coming; it is a separate record
  or stream, so it advances the publication marker without being mistaken
  for pixels, and readers fold it without calling a skipped position arrived.
  The mechanism for that is chosen, not left: additive fields under the same
  schema (the layout's unused `final` flag with the list of positions that
  will never come; a terminal state in the marker that older readers ignore),
  so an older Viewer on another machine still opens the run and shows a
  stopped run as a slow one, rather than a bumped schema that makes every
  older Viewer refuse the whole run. A schema version. And one wording fix in
  the existing record: its layout revision calls itself "what the run has done
  so far" while holding the whole plan.
- **Planned, arrived, never coming.** While the run is live a planned but
  absent position is drawn as its own state, a faint outline of expected
  ground. At the terminal state it becomes "not acquired" or "skipped".
  Coverage is committed positions only.
- **A re-scan of the same type** is a new collection instance, a new governed
  run and a new folder, however familiar its label, and the index says which
  is current. Silent overwriting is not an option.
- **A folder without a register** keeps the Viewer's read-only discovery path
  or gets a plain refusal; it never needs a bridge.
- **Two cautions for a network share**, to be tested on the real one: the
  fingerprint includes the inode, which some network file systems do not
  keep stable; and a reader on another machine may see a renamed marker a
  little late.
- **Who reads it.** The Viewer, instead of listing folders; coverage, derived
  in memory from the register and handed to the page as an indexed snapshot,
  never the whole plan rewritten after every landing; the kept coarse
  pyramid; the engine's own lookup.

## The data layer: what is kept, what is assembled, with the numbers

Ten thousand positions is won or lost here, not in the renderer. "Ten
thousand" is meaningless without the case, so every number below names it.
All cases: sixteen-bit counts, one plane, one moment, a contiguous plate of a
hundred by a hundred positions with no overlap, chunks of 128 voxels, no
sharding, levels halving down to eight voxels, one plane per chunk, composed
pieces of 512, as the writer and the composer make them.

- **What the plate is on disk.** Fields of 512 voxels, one channel: about
  330,000 files and 6.5 GiB of raw pyramid. Fields of 2048 voxels, three
  channels: about 10.5 million files and 312 GiB. Depth and time multiply the
  chunk files and bytes; a deep three-channel run passes a billion small
  files. The vendor's TIFFs are beside all of it. For a 2048 field, the levels
  with more than one chunk are the finest four; the five coarser levels are
  one file each, and the coarsest are a few hundred bytes.
- **Where it breaks first: the folder scan.** Every relink reads every store's
  description, tens of thousands of reads on such a plate, repeated every
  thirty seconds while the scan grows. Whether one scan exceeds the interval
  on the real share is a hypothesis from an assumed few milliseconds per file
  open, to be measured in phase 0; on a local drive it does not. Either way
  the register removes it, and it is the first target.
- **Second: the file count.** Small-file metadata work on Windows or a share,
  backup and antivirus, break before anything in the register or the
  renderer. Sharding the position stores is a prerequisite of the
  ten-thousand claim. The storage library can bundle a shard, but only the
  full-size level, and the bridge's writer never asks; bundling that level
  alone leaves millions of files, so the design shards every retained level
  with more than one chunk, one shard per level per channel-plane. The
  single-file levels below the piece size of 128 can be dropped instead of
  sharded, on one condition: that the data layer keeps its own coarse levels,
  so the composer's "every store has every level" rule can be relaxed for
  bridge-written runs; the pointer-linked view needs positions only down to
  128. If phase 0 says the coarse levels are not kept, the positions keep
  their single-file levels and those need bundling of their own. With both
  done, the 2048 three-channel plate is about 200,000 files. Position data is
  written once and shards well; the kept coarse levels are patched one piece
  at a time and are never sharded, because a partial write into a shard
  rewrites about half of it, growing with the shard, which the Viewer
  measured.
- **Third: the bridge's write rate** on a share, hundreds of directory entries
  per position, and any per-landing bookkeeping that grows with the number of
  positions.
- **Tile sizes, said first.** "A fine tile inside one position is one read" is
  only true if the engine's fine tile is the source chunk of 128, aligned to
  it; a 512 tile over a full-size position is sixteen reads per channel and
  plane. Default: the source chunk at the finest levels, the composed piece
  at kept levels. A read is counted at the storage boundary, not as an HTTP
  request.
- **Coarse levels are kept and patched, if the measurement says so, in one
  canonical placement, per channel, and not cheap.** For the 2048
  three-channel plate, one coarsest piece touches four thousand positions,
  and warming the kept levels of three channels is on the order of 200,000
  chunk reads: seconds on a local drive, tens of minutes on a share by
  estimate. The one-per-cent rule keeps about 2,600 channel pieces, about
  1.3 GiB uncompressed for one plane and one moment; depth, time,
  projections and side copies multiply it. Whether they are kept on disk is
  decided by the phase-0 breakdown, as the earlier design's phase 1 already
  says. If kept: in the low-edge alignment, per channel, patched
  synchronously with the landing and off the stage's own path, as the
  Viewer's rule works today, unless the data-layer record introduces an
  explicit derived revision; then a kept tile stamped with an older revision
  is composed lazily from the current one or withheld, never served as
  current. Persistence on disk and residency in memory are separate decisions
  with separate rules.
- **The boundary rule: a measured cost model, fan-in among its inputs.** A
  level is served lazily while assembling any of its tiles costs less than the
  frame can wait, and kept beyond that. Fan-in is the first input, and the
  composer already knows which tiles fall in each piece; but one position is
  not one read, so the model counts source chunks and bytes per output tile,
  the codec, channels and planes per frame, overlap, whether the block cache
  is warm, how many reads run in parallel, and local disk against the share,
  with cold and warm percentiles recorded separately and a numerical guard
  (a level is kept when more than a stated share of its tiles exceed the
  budget, not when one does). The Viewer's one-per-cent rule answers disk
  rather than latency; the kept set is the union. The boundary is evaluated
  over the planned positions in the register, so it never moves under the
  operator.

## The engine itself

- **Three identities, not one.** A raw source chunk is identified by
  collection, governed run, position and its generation, moment, stable
  channel key, level, plane, row, column. An assembled slice tile is
  identified by collection, placement, orientation, slice axis and its
  coordinate in the unit the placement uses (a plane index of the composed
  picture under aligned placement, micrometres from the aligned edge when
  stacks differ), moment, stable channel key, level, row, column, and a
  *content generation* of its own, which the dirty-box protocol advances
  only for tiles a landing touched; the run-wide revision is the snapshot an
  answer is validated against, not part of the key, or every landing would
  empty the cache. A stored projection adds its axis, half-open range, kind,
  recipe version and the generations of its inputs. Data kind and type
  validate an entry and choose its texture pool; the window and its state,
  colour and opacity are drawing inputs, not identity, so changing brightness
  never fetches; the coverage mask travels with the tile's payload. A
  composed tile does not carry one "source generation": its inputs are many
  positions, and the content generation stands for them.
- **What neuroglancer does that we must also do**, read from its pinned
  source, each item with what an operator would notice without it:
  - *three tiers, and admission by tier then priority*: tiles are visible,
    prefetched or recent; a visible tile is never evicted to admit a prefetch;
    plain least-recent-use would do exactly that, and the picture in front of
    the operator would flicker while the picture next door loaded;
  - *a composite priority with a written tie-break*: visible first, nearest
    the view centre first, coarser first, with the arithmetic and the
    tie-break stated, because "nearest" and "coarser" disagree at the edge of
    the screen;
  - *prefetch driven by the view's velocity*, with a budget, in the pan
    direction and along the sliders; without it a steady pan always arrives
    late;
  - *item counts beside byte counts on every budget*, and four budgets:
    graphics memory, main memory, downloads per source level, and decoding;
    without counts, many small tiles exhaust a byte budget's bookkeeping;
  - *a "how far" on every request*: worker memory, main memory or graphics
    memory, so the pointer readout and the panel's measurement can have
    pixels without an upload;
  - *a fixed number of requests in flight*, counted in reads behind them
    where one tile is many reads, with back-pressure when decoding is slower
    than downloading; without it a fast pan floods the server and the
    picture arrives all at once, late;
  - *abort on pressure*: a tile no longer wanted drops to the recent tier and
    a queued one is removed; a download in flight runs to completion unless a
    higher-priority tile needs its slot; this is the rule behind the
    303-versus-1266 request measurement and is kept;
  - *priorities recomputed in one batch per view change*, throttled, with the
    maximum winning where two rows want one tile; that is neuroglancer's
    whole answer to fairness between channels and collections, and it is
    ours too;
  - *a time-sliced upload budget on the drawing thread*, a stated number of
    milliseconds per frame; without it one large upload stalls a frame;
  - *deliveries carry ownership of their buffers*, and the page can ask for a
    tile's bytes back, for the readout;
  - *ordering between a revision bump and deliveries already in flight*,
    stated;
  - *three kinds of nothing and one of failed*: never asked (coverage), asked
    and empty (remembered until the revision changes), and failed (retried
    with back-off, a stated limit, and a visible permanent-failure state);
    without the distinction an empty answer would be retried for ever;
  - *needed-versus-available counters per row*, which is what "settled"
    means and what the harness measures; the measurement handle exposes them
    so both engines are judged by the same definition;
  - *sources memoised by a stable key* so two rows over one source share
    tiles; tile objects pooled;
  - *coarse standing in for fine* done by drawing coarse rectangles first
    and finer ones over them, within one channel;
  - *recovery from a lost graphics context*, and what happens when the pinned
    plane alone exceeds the budget.
- **Work off the drawing thread, from the start.** Fetching and decoding run
  in a worker; the decoder for the Viewer's compressed pieces lives there. How
  many workers is measured, not fixed: one fetch-and-decode worker is the
  starting point, a pool if decoding proves slower than downloading. Whether
  the Viewer should ever serve raw pixels is a hypothesis, since its pieces
  are compressed and the ratio depends on the specimen; it is measured, not
  assumed either way.
- **Invalidation: replace, never drop.** A tile inside a dirty box is marked
  stale and keeps drawing until its replacement arrives; the replacements of
  one landing land together, in one frame; a stale tile is never handed to a
  measurement or a readout as current; a stale tile whose replacement never
  comes is dropped only when the new revision's coverage says its ground is
  gone. This is exactly what the patch this repository maintains against its
  pinned neuroglancer does today, after the stock all-or-nothing rule made
  the picture empty and refill on every landing; the first draft's "drop
  only the tiles that intersect" would have recreated that blank, and is
  withdrawn. The Viewer publishes, per revision, the regions a landing, a
  later timepoint or a replacement dirtied at each level, as boxes, from the
  old and the new footprint alike; the live-state document already carries a
  per-source revision and is the right document to grow boxes into. The
  composer's footprint of a turned position is its bounding box: conservative
  and enough for invalidation, not byte-exact geometry.
- **Level of detail** from the zoom against each level's voxel size in
  micrometres.
- **Placement.** Each tile a textured rectangle at its true micrometre
  position, by the voxel-edge rule already settled.
- **Cache.** Tiers with byte and item budgets, admission by tier and priority,
  the current plane pinned. On the graphics side, pools by tile dimensions and
  internal format (sixteen-bit counts, eight-bit counts, wider accumulators
  for projections, 32-bit labels); a texture per tile as neuroglancer does or
  slots in a texture array, decided by measurement; the lookup from tile to
  texture lives in JavaScript. WebGL2 cannot say how much graphics memory
  there is, so the budget is a number fixed before measurement. The cache
  keeps the source data type and the coverage mask; nothing is converted on
  the way unless lossless and stated.
- **Sparse.** Coverage from the register decides which tiles exist at each
  level. An empty piece already costs a request and no bytes today, so the
  saving is in requests, and the gate says on which plate.
- **Measurement hooks, from the first commit.** The same handle the harness
  and the panel rely on today, the needed-versus-available counters, a way
  to read a tile's bytes, and the breakdown instrumentation phase 0 uses, so
  the new engine is measured by the same harness, on the same pixels, by the
  same definition of settled, as the old.

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
  value under the pointer are the additions, and need the "how far" request
  and the bytes-back call above.
- **Later, with the side view:** a direction in the view record, a slider for
  the axis the section cuts at, overlays hidden or re-projected per overlay,
  the drag panning in x or y and z.
- **After the numbers, none a gate:** a scale bar; keyboard nudges;
  double-click to centre; pinch; zoom limits; the view in the page address
  and remembered per run; the view saved as a picture.

## Decisions on the four reviews

Every finding was checked against the code before being taken. The first
round is summarised in the previous revision's decisions, all still in force.
From the second round, both reviewers found the same softening and the same
gaps, and both are taken:

- phase 0 is now runnable: the harness work it needs is authorised by name,
  the parts of the breakdown neuroglancer cannot time (hand-off, upload,
  draw) are found by subtraction and said so, and the three promises above
  give it a stop condition;
- the invalidation rule is "replace, never drop", citing the maintained patch;
- the prior-art note's body now says what its preface says;
- the layout keeps whole-pixel origins, the observation record is a separate
  document written with each landing, and the store's regular step draws
  while raw heights are provenance;
- "one profile per frame shape" means one governed run per shape, and the
  cross-run collection index is in the extension and in step 2;
- the lifecycle record is additive under the same schema, and what an older
  Viewer sees is said;
- the (channel, kind) key, `setChannel`'s kind and the never-measured label
  row are in step 2 and step 4;
- three identities instead of one, with placement and the slice's unit in
  the key, a per-tile content generation instead of the run-wide revision,
  and generation off composed tiles;
- the scheduler list completed from neuroglancer's source, item by item, with
  what the operator would notice;
- the process-level memory gate beside the cache's own; the request gate
  named by plate; "first picture" and "no slower" defined with a tolerance
  and cold and warm runs; the coverage gate in output-tile footprints; reads
  counted at the storage boundary; panel states tested at application level;
  the input gate on complete fixtures;
- the single-plane thickness, turned positions and the meaning of time
  decided; one plate case per bullet; "single-file levels"; the sub-128
  levels droppable only if the coarse pyramid is built; sharding of every
  level with more than one chunk;
- the re-scan fact corrected (refused at the vendor-file move, not at the
  store); the share scan and raw-bytes sentences labelled hypotheses; the
  shard-rewrite factor stated honestly; worker count measured; the sum's
  accumulator chosen by input, not "32-bit"; the sample mean named; the
  glossary extended; "any number of channels" bounded by a fixture.

Not taken, and why:

- **"Rethink": making the engine conditional on phase 0.** Refused in the
  first round and, in the second, accepted by both reviewers as the owner's
  product decision on the three promises now made. The record says what the
  owner forgoes, in the reviewers' own words, where the decision is.
- **Codex's "the first engine is an absolute top slice".** Not taken, and the
  first revision was wrong to leave it unnamed. The first engine draws the
  positions as the stores place them today, which is alignment at the low
  edge, because absolute placement has no data until the register carries
  heights and, for a flat plate under a focus map, shows two fields out of
  fifty in a slice. Absolute placement follows once the frame and the heights
  exist.
- **Cutting labels, projections, alignment and the side view from the
  design.** They leave the first engine, not the plan; each is a named later
  milestone, and what each needs so nothing has to be undone is in the first
  engine and the register.
- **Keying reusable tiles by the run-wide revision.** This was the first
  revision's own choice, not a reviewer's; Codex showed it would empty the
  cache on every landing, and it is replaced by the content generation above.

## Facts checked against the code, and what is new

- Exists: the Viewer's record package (profile, whole-pixel layout revision
  with an unused `final` flag, commit event, generations, closed event list,
  publication marker, synchronous coarse rebuild, opening from files alone,
  one run per folder); the change stream and revisioned live-state document;
  file-identity validators on live pieces; segmentation rows in the
  standalone config; bounding-box footprints in the composer and bake
  patcher; synthesised coverage in the harness; the shared gesture module
  with pointer-anchored zoom; the sliders; the view in micrometres; the
  pointer readout in x and y; sharding of the full-size level in the storage
  library; neuroglancer's texture per chunk, three-tier chunk manager,
  velocity prefetch, decode pool and time-sliced uploads in the pinned
  version; this repository's patch that replaces chunks in place; the
  bridge's refusal of a re-scan at the vendor-file move.
- New: the bridge writing the profile, layout, commits, observation and
  lifecycle records; the versioned extension and the collection index; the
  coordinate frame; coverage on the operator page; dirty boxes per revision;
  the cost model; the kept coarse pyramid for bridge runs, if measured
  necessary; sharding in the bridge's writer for every level with more than
  one chunk; the three identities; the (channel, kind) window key; a label
  data kind; a label layer on the operator page; the harness work phase 0
  needs; the engine itself.
- Hypotheses, said as such: that a folder scan on the share exceeds the
  relink interval; that raw pixels from the Viewer would cost more bytes than
  compressed pieces; that one worker suffices.
- Not yet measured, and decisive: the phase-0 breakdown on the microscope
  PC; the cost model on a local disk and on the real share; whether the
  coarse pyramid is kept; the bridge's conversion rate on a share; whether
  whole-stack projections need precomputing.

## Gates

**Phase 0**, on the microscope PC, before anything else is built: the
earlier design's ten-step trace over the existing Viewer and engine, with
time broken down into server work (the composer's own build and encode
timers), transfer, download-plus-decode as neuroglancer reports it, and
hand-off, upload and draw by subtraction, on a real run, cold and warm, local
disk and share, with a frozen fixture, a stated number of repetitions and a
declared tolerance. Its result names the layer that fails, if any.

**The data layer** is done when, under `neuroglancer-under`, on the stated
plate:

- opening a run reads the register and never lists the positions folder,
  counted in file operations on the Viewer's side;
- a relink of a grown run costs a fingerprint check, not a scan;
- if coarse levels are kept, a coarse tile is one read at the storage
  boundary, and the publication marker moves only after every dirty piece is
  current;
- no request is made for an output tile whose footprint holds no committed
  coverage;
- a new live position is visible within 500 ms at the ninety-fifth
  percentile over enough landings to compute one, with the start and finish
  events named; this cannot be attempted before the bridge writes the
  register, since today's relink is at most every thirty seconds.

**The engine** is done when, on the harness, over the same data layer, on
the same pixels, by the same definition of settled:

- first picture, by the earlier design's definition of a useful picture, is no
  slower than neuroglancer's within the declared tolerance, cold and warm
  reported separately;
- navigation latency at the ninety-fifth percentile is no worse, and a
  settled pan or zoom completes within 500 ms at that percentile;
- requests for the same navigation are fewer on the named sparse plate and no
  more on the named dense plate, and bytes no more on either;
- the earlier design's process-level memory gate holds (renderer and graphics
  process together at most 1 GiB over twenty repetitions of the trace, the
  last ten cycles growing by less than a tenth or 20 MiB), and the cache's
  own accounting stays within a budget fixed before the run;
- a landing during viewing dirties exactly its footprint and nothing else,
  byte for byte, and no stale tile reaches a measurement as current;
- every panel state (declared, provisional, settled, waiting, unreadable,
  absent) reaches the screen the same way as with neuroglancer, tested at the
  application level because the harness has no panel, and no absent window
  ever reaches the shader;
- it opens our own data as it is written today, unchanged, on complete
  fixtures: a full bridge-written multi-position run whose fields arrived as
  our flat OME-TIFFs, with channels, depth and time, and an OME-Zarr transfer
  of ours in 0.4 or 0.5;
- the stated visible-channel fixture draws within the latency and memory
  gates.

## Order of work

1. **The harness work phase 0 needs**, authorised here by name and not "the
   engine": the ten-step trace in the rig's external-run door; the adapter fix
   so a bridge-written five-axis store is drawn rather than placed beside the
   view; the breakdown instrumentation on both sides. Then phase 0 itself, on
   the microscope PC, with its result written down in one sentence.
2. **The data-layer design record**: the bridge writing the profile, layout,
   commits, observation and lifecycle records; the versioned extension and the
   collection index; the coordinate frame and z datum with half-open plane
   intervals; coverage; dirty boxes; the cost model and tile sizes; sharding
   of every level with more than one chunk in the bridge's writer; the
   single-file-levels decision; the terminal state; the re-scan rule; the
   (channel, kind) window key with `setChannel`'s kind and the never-measured
   label row. One review pass.
3. **The data layer built and measured under `neuroglancer-under`**: its
   gates, and the baseline the engine must beat. If it passes every gate of
   the earlier design, promise 3 applies and the engine's first brief shrinks.
4. **The engine design record** with the first brief: flat top view over the
   positions as the stores place them today, rectangles only, slices only,
   channels as an overlay, the three identities, the scheduler as specified,
   the worker, the per-format pools, the measurement handle with its
   counters. One review pass. Then the engine in stages: source and cache
   headless and testable without a browser; the renderer; the fourth option
   beside neuroglancer; the numbers. The operator page stays on neuroglancer
   until the gates pass.
5. **Later milestones**, each with a short record, a review pass and its own
   gates: labels; the maximum projection, then mean and sum; aligned
   placement with its stated meaning, then absolute with its default; turned
   positions; the side view with its own slider and contract changes; the
   navigation extras.
6. **Only after that**: the three-dimensional phase, choosing its own
   representation from measurements.
