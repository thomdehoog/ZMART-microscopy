# A lightweight JPEG pyramid for the ZMART browser viewer

Date: 2026-09-01

Status: detailed proposal for review. No implementation has been started and
none of the performance claims below should be treated as measured yet.

## The decision this plan proposes

Build a display-only, tiled JPEG pyramid for flat ZMART acquisitions, but do
not replace the TIFFs, analysis data, or the existing volume viewer with it.
The JPEG path should be an explicitly selected two-dimensional display engine,
not a silent fallback that can hide a broken scientific-data path.

The goal is practical:

- a browser or PyWebView should fetch work in proportion to the screen, not in
  proportion to the number of microscope fields;
- a whole plate should begin with a few coarse tiles and sharpen as the
  operator zooms;
- close zoom should reach one source pixel per screen pixel for only the area
  being viewed;
- ordinary JPEG and a small JSON manifest should be enough to consume the
  display data;
- the persistent display cache must have both a relative and an absolute size
  ceiling, so a 500 GB run can never create a 50 GB “lightweight” cache;
- deleting the entire display cache must lose no scientific data and must be a
  supported way to recover space.

This is promising, but it earns a production place only if a measured spike
beats the current Smart Viewer 0.2 path on real ZMART runs. The first phase is
therefore a comparison, not a port.

## The problem it is meant to solve

The existing small-picture path in `viz_studio/backend/jpeg_tiles.py` and
`viz_studio/options/jpeg-under/viewer.js` makes one 128-pixel JPEG per field.
It proved that ordinary display copies can make ten thousand TIFF fields
viewable. It also exposed the remaining scaling problem. At roughly 8,400
fields, every field asks for its own picture and the queue resolves in scan
order. The work still grows with the field count, even though the screen has a
fixed number of pixels.

A global pyramid changes that relationship. A whole-plate view asks for the
few coarse tiles covering the screen. A well-sized view asks for a few tiles at
an intermediate level. A cell-sized view asks for a few full-resolution tiles.
The number of source fields may grow from 840 to 8,400 without multiplying the
number of requests needed for one settled view.

The current OME-Zarr/Smart Viewer path may already be close enough after the
0.2 upgrade. `docs/reviews/2026-09-01-review-of-the-smart-viewer-integration-plan.md`
correctly requires that this be measured before another viewer path is built.
JPEG wins only if it is materially faster, smaller, or easier to deploy for
ZMART's ordinary flat view.

## Scope

### In scope

- Full-resolution XY slice viewing for acquisitions described as
  `T x C x Z x Y x X`.
- Independent channel visibility, colour, window, gamma, colour map, and
  opacity in the browser.
- Timepoint and z-plane selection.
- Live positions arriving while a view is open.
- Several acquisition types, such as overview and targets, placed together in
  stage micrometres while retaining separate controls.
- Browser and PyWebView delivery through the same local HTTP interface.

### Not in scope

- Scientific measurement from JPEGs.
- Replacing the vendor TIFFs or the canonical analysis representation.
- Arbitrary XZ/YZ slicing or out-of-core volume rendering.
- Stitching, illumination correction, registration, or blending overlaps into
  a new scientific image.
- Supporting an image orientation the run has not recorded.
- A silent JPEG fallback when the selected scientific-data viewer fails.

Neuroglancer or another volume-capable engine remains the path for volume
rendering. The JPEG view is a fast flat view.

## Facts the implementation must preserve

1. **The TIFFs are authoritative.** JPEGs are lossy, rebuildable display
   derivatives and nothing may read them for analysis.
2. **A TIFF does not reliably say where the stage stood.** Placement comes
   from the acquisition record's `x_um`, `y_um`, pixel size, and recorded image
   orientation. Filenames must not be parsed to recover facts the run already
   knows.
3. **Channels stay separate.** One pyramid belongs to one logical channel.
   Colour and compositing happen in the browser.
4. **Time and z select pixels; they do not move a flat image in x/y.** A focus
   height remains measurement metadata rather than a stage translation for an
   overview map.
5. **Unimaged ground and acquired black pixels are different facts.** The JPEG
   may draw both as black, but the run's coverage record remains available to
   overlays and tests so the application can tell them apart.
6. **The grid origin cannot move during a live run.** Otherwise every tile URL
   would change its physical meaning when a new position arrived.

## The dtype question

The coarse levels can keep the same *intensity meaning* as the finest level,
but ordinary browser JPEG cannot keep a `uint16` or floating-point dtype. It is
effectively an 8-bit display format in the browsers this project targets.

The conversion must therefore be:

```text
source uint16/float
    -> downsample in source precision or float
    -> apply one fixed channel-wide encoding window
    -> 8-bit grayscale JPEG
```

For a channel encoding window `[encoded_low, encoded_high]`:

```text
jpeg_sample = round(255 * clamp(
    (source_sample - encoded_low) / (encoded_high - encoded_low), 0, 1
))
```

Every tile and every level of that channel uses the same window. The manifest
records it. A decoded JPEG value therefore has the same approximate source
meaning at every zoom. The browser can express an operator window in source
units by first translating it into this encoded range.

The encoder must not bake in display gamma, a colour, or a per-tile stretch.
Those choices would make fields incomparable and would make later contrast
controls dishonest. The existing small-picture `_stretch` path deliberately
bakes in gamma for a fixed preview; it must not be reused unchanged for this
purpose.

Values clipped outside the encoding window cannot be recovered. A JPEG view
must say which range it retained, and the UI must not imply that a slider can
recover values it cannot. If the operator needs the full 12/16-bit range, the
scientific-data viewer remains available. A later version may create a second
cache generation with a wider encoding profile, but it must never mix profiles
within one channel view.

### How the encoding window is chosen

The first field must not decide it. A run beginning over empty sample would
then set a completely different scale from one beginning over bright tissue.

The first spike should use this precedence:

1. an acquisition-wide window declared by the recorded acquisition preset;
2. a window declared by a run-wide channel description;
3. a configured camera range only when neither of the first two exists.

A per-position measurement is not an acquisition-wide window. If the run has
no stable answer, the spike should report that and compare two explicit
policies on real data rather than silently inventing one. A robust sampled
window may become a second cache profile, but switching to it during a live run
must be deliberate and versioned.

## Size budget

The budget has a per-acquisition relative cap and a cache-root absolute cap. A
percentage alone is not a safe policy for large microscopy runs, and an
absolute cap applied once per run would still let a collection of runs fill the
machine.

Provisional defaults for the spike:

```text
per-acquisition soft target = 5% of authoritative source bytes
per-acquisition hard ceiling = 10% of authoritative source bytes
all-runs cache-root soft target = 5 GiB
all-runs cache-root hard ceiling = 10 GiB
```

The effective allowance is the smaller applicable limit. Thus a 500 GB
acquisition targets no more than 5 GB and can never retain a 50 GB display
cache. Several runs share the same 10 GiB root ceiling rather than each
receiving 10 GiB. The exact 5/10 GiB values are review and measurement inputs;
combining relative per-acquisition limits with one absolute all-runs limit is
not optional.

The source size is the authoritative acquisition's unique source-image bytes
on disk, counted once, not an uncompressed array estimate and not enlarged by
counting another derived representation. Cache size includes manifests,
sidecars, and every persistent display derivative beneath the cache root.

- The soft target starts background/low-priority eviction.
- The hard ceiling is enforced before atomic publication. A cache write that
  would cross it triggers eviction or is declined; it never quietly exceeds
  the limit.
- Eviction order is incomplete temporary files first, then least-recently-used
  fine tiles. Coarse tiles and recently visible tiles have greater value
  because they make the next open fast.
- A tile that was evicted is regenerated if it is requested again.
- The cache is deliberately partial. The hard ceiling is more important than
  retaining every full-resolution tile ever visited.

For intuition, a complete two-dimensional power-of-two pyramid has at most
`4/3` as many samples as its finest level. Against an uncompressed 16-bit
source, if a grayscale JPEG averages `b` bits per sample, the approximate
ratio is `b / 12`. One bit per sample is about 8.3%; two bits per sample is
about 16.7%. Real TIFFs may already be compressed, so only measurements against
the files on disk can decide how much of a pyramid fits.

Transient state has separate bounds:

- lossless working pixels used while a live tile is changing are kept in RAM,
  not as a second persistent pyramid;
- decoded browser/GPU tiles start with a conservative 128 MiB combined budget;
- browser accounting assumes up to eight bytes per pixel for a decoded image
  plus its GPU texture until measurement shows a tighter safe number.

## The spatial grid

One acquisition has one fixed level-0 pixel grid. The run should declare its
planned extent before the first field is served, because the scan plan already
knows where it intends to go.

Pixel coordinates refer to pixel edges. A six-number affine transform maps a
level-0 pixel edge `(px, py)` into stage micrometres:

```text
stage_x = a * px + b * py + tx
stage_y = c * px + d * py + ty
```

This records scale, orientation, handedness, and origin without relying on an
implicit “top-left” convention. The first implementation may accept only the
axis-aligned orientation actually validated on the target instrument, but it
must reject unsupported rotation or shear rather than draw it approximately.

Each source position also has a source-pixel-to-stage transform derived from
its acquisition record. Rasterising that source into the global grid is a
normal resampling operation. A position that cannot be reconciled within a
declared tolerance is reported and omitted from the JPEG view; it is not
snapped silently.

If a live position falls outside the declared extent, the origin still does
not move. The safe first-version response is to publish a new pyramid
generation with a larger extent or refuse that position from this display
path. Extending only right/down may be supported later, but it must not change
existing tile coordinates.

Separate acquisition types keep separate grids and manifests. Their affine
transforms place them together in stage micrometres in the viewer.

## Z has three jobs and must not be one number

The reported failure is consistent with distinct roles for Z being combined:

- **acquisition Z** is where the microscope drove/focused while capturing a
  position;
- **source-local Z** says which plane within that captured source is being
  sampled;
- **presentation Z** says how that source is placed for the current view.

The acquisition value must be preserved, but it must not lift every field of a
flat overview to a different display height. A focus surface controls imaging;
it is not automatically the geometry of a two-dimensional plate map.

### The present correction stays narrow

The current trace proves one boundary correction: the flat source renders when
its sole voxel centre is sampled at local `z=0`, while `z=0.5` samples the upper
boundary of that voxel. The current work should correct that sampling and the
2-D presentation transform only.

It should not attempt physical 3-D registration. It preserves the information a
future calibrated scene would need, but it neither uses raw stage/focus Z as a
specimen coordinate nor claims that a translation built from it is correct.

The scene/link builder resolves the source anchor once and records the answer.
Opening order, asynchronous source arrival, and current navigation can never
recalculate it. Tests for the present correction must prove:

- every 2-D overlay anchor centre meets display `z=0`;
- the single-plane source is sampled at its voxel centre;
- a stack's internal plane order and spacing are unchanged;
- the original acquisition/focus Z remains recoverable as provenance;
- no layer adds a second presentation Z offset.

Each source needs one explicit anchor plane. Coordinates refer to plane
centres, not the boundary above a voxel. If plane `i` has local centre
`local_z(i)` and the anchor has centre `local_z(anchor)`, the flat presentation
uses:

```text
relative_z(i) = local_z(i) - local_z(anchor)
```

The anchor plane is therefore exactly at display `z=0`. A one-plane source is
sampled at that plane's centre, not at `+0.5` of a voxel where the image ends.

The anchor rule is deterministic:

1. a single-plane source anchors on its only plane;
2. a stack anchors on its recorded focus/reference plane;
3. a legacy stack with no reference uses the middle *plane index* as a warned
   fallback, not the maximum plane and not a runtime choice;
4. load order, current visibility, and which source answered first never choose
   an anchor.

For an even number of legacy planes, “middle” must still name a real plane. The
proposed fallback is `floor((count - 1) / 2)`, recorded in the manifest so a
different program reaches the same answer.

### Two-dimensional presentation

All source anchor-plane centres map to the common flat display plane. Channels,
masks, labels, and annotations that describe the same pixels inherit the same
source transform. A layer may show/hide or style a source; it does not add a
second Z translation.

For a global JPEG overview, the manifest's z coordinate is relative to the
anchor. Fields captured at different focus-surface heights still contribute to
the same logical `z=0` plane. A real stack retains its relative plane spacing.

This does not require every source to have the same raw acquisition Z. It
requires the selected anchor centres to agree after the two-dimensional
presentation transform.

Plane selection is navigation, not placement. A flat one-plane overview should
not disappear merely because the operator moves through a separate stack. The
first product spike should test the simplest explicit behaviour: a source with
one plane remains on its anchor, while a stack selects its requested relative
plane. If operators switch among several stacks, remembering the last relative
plane per source may be useful, but that state belongs in the session/view state
and never changes the source transform.

### Future three-dimensional presentation

A future physical scene may use:

```text
world_z_3d(i) = calibrated_acquisition_z - specimen_datum + relative_z(i)
```

That is reversible because acquisition Z, the anchor, and local spacing were
not overwritten by the flat view. It is safe to describe this as “changing the
Z translation” only after the following have been validated: units, Z scale,
axis direction, anchor plane, stage-Z calibration, and a shared specimen datum.
The objective's focus position is not assumed to be a registered specimen
coordinate merely because it has micrometre units.

Two lightweight scene descriptions may therefore reference the same source
pixels:

- a 2-D scene using anchor-relative flat placement;
- a 3-D scene using calibrated physical placement.

They do not require two copies of the scientific chunks. The JPEG pyramid in
this proposal remains the display derivative for the 2-D scene; the volume
engine reads the volume-capable source for 3-D.

The authority chain is:

```text
local plane centre
    -> source anchor transform
    -> mode-specific presentation transform
    -> layer styling and visibility
```

Applying acquisition Z once in the source and again in a layer is forbidden.
The manifest or scene should give channels and derived layers a shared geometry
identity so this can be checked rather than inferred from nearly equal numbers.

## Levels, tiles, and downsampling

- Level 0 is the finest level.
- Level `L` has `2^L` level-0 pixels per displayed pixel on each XY axis.
- Levels continue until the declared acquisition fits in one or a few tiles.
- Tiles are square and power-of-two sized.
- The first spike compares 512 and 1024 pixels. It should begin at 512 because
  decoded memory and four-channel views are the more dangerous failure mode;
  1024 wins only if real measurements show that fewer requests outweigh the
  larger decoded textures.
- Edge tiles carry their valid width and height and must never be stretched to
  fill a nominal square.
- Missing tiles answer as missing; they are not enormous all-black files.

Downsampling happens before the 8-bit encoding, in source precision or float,
and never by decoding a JPEG parent. Repeated JPEG-to-JPEG pyramid building
would accumulate ringing and quantisation at every level.

Area/box averaging is the reference resampler because it gives a stable,
anti-aliased view. Fluorescence is sparse, so a max-preserving alternative
must be compared on real images: averaging may hide tiny bright objects at
plate scale, while max pooling may exaggerate isolated hot pixels and make
brightness jump between levels. This is one of the few decisions the design
cannot settle honestly without photographs and measurements.

JPEG quality is also selected by measurement under the size budget. The spike
should compare at least quality 85, 90, and 95 per level. “95 at level 0” is a
candidate, not a promise.

## Overlaps and retakes

Overlap semantics are display semantics, not stitching.

The first implementation should support the arrangement ZMART currently uses:
grid-aligned positions without ambiguous within-acquisition overlap. It may
also support exact retakes by giving the highest committed capture sequence
ownership of the repeated ground.

Any broader overlap has to choose one deterministic rule. The proposed rule is
latest committed position wins, resolved from the run's sequence number rather
than a file modification time. No feathering, brightest-wins, or averaging is
allowed to appear under the name of placement. If the alignment needed to make
that rule consistent at every pyramid level is absent, the JPEG path refuses
that acquisition until a proper rasteriser has been measured.

## Manifest and HTTP interface

The browser receives one small manifest per acquisition. A first schema could
look like this:

```json
{
  "schema": "zmart-jpeg-pyramid/0.1",
  "datasetId": "overview-abc123",
  "revision": 37,
  "complete": false,
  "axes": {"t": 1, "c": 3, "z": 1},
  "zModel": {
    "coordinate": "relative-to-anchor-plane-centre",
    "planeCentresUm": [0.0],
    "anchor": {"kind": "only-plane", "index": 0},
    "acquisitionZ": "preserved-in-capture-record"
  },
  "grid": {
    "width": 32768,
    "height": 24576,
    "pixelEdgesToStageUm": [0.65, 0, 1200, 0, 0.65, 3400]
  },
  "tile": {
    "width": 512,
    "height": 512,
    "levelZero": "finest",
    "levels": [
      {"level": 0, "width": 32768, "height": 24576},
      {"level": 1, "width": 16384, "height": 12288},
      {"level": 2, "width": 8192, "height": 6144},
      {"level": 3, "width": 4096, "height": 3072},
      {"level": 4, "width": 2048, "height": 1536},
      {"level": 5, "width": 1024, "height": 768},
      {"level": 6, "width": 512, "height": 384}
    ]
  },
  "channels": [
    {
      "id": "c0",
      "label": "DAPI",
      "sourceDtype": "uint16",
      "encoding": {"transfer": "linear", "low": 80, "high": 3400},
      "defaultWindow": {"low": 140, "high": 2100}
    }
  ],
  "tileUrl": "planes/{t}/{c}/{z}/{level}/{y}/{x}.jpg",
  "emptyTile": "204",
  "defaultBlend": "additive"
}
```

The complete schema also needs a format-generation identifier, JPEG quality,
resampler, source fingerprint, and cache-budget report. Unknown schema versions
are refused with a useful message.

Suggested routes:

```text
GET /view/<acquisition>/pyramid.json
GET /view/<acquisition>/planes/<t>/<c>/<z>/<level>/<y>/<x>.jpg
GET /view/<acquisition>/cache-status.json
```

Every integer is range-checked before it becomes a path. A dataset identifier
is server-issued. The route must not accept arbitrary filesystem paths.

### Publication and browser caching

- Manifests and mutable live tiles use stable URLs, `ETag`, and
  `Cache-Control: no-cache`. “No-cache” permits storage but requires validation;
  it is different from the current `no-store` response, which throws away a
  useful JPEG after every request.
- A completed, content-addressed cache generation may use long-lived immutable
  responses.
- Files are written to a temporary sibling and replaced whole. A browser sees
  the old complete JPEG or the new complete JPEG, never half of either.
- Concurrent requests for the same missing tile share one bounded generation
  job.
- A failed generation leaves no final file. The response names the source and
  reason in server logs; the browser receives a bounded failure and may retry.

When `tilesMayHaveLanded()` is called, the viewer revalidates the manifest. If
its revision changed, it drops only its visible tile-layer memory and
revalidates those visible URLs. The request count therefore follows the
viewport even if the manifest revision changes after every position. Server
ETags avoid retransmitting unchanged tiles.

## Lazy generation and a live scan

“Lazy” means an unviewed run need not acquire a second permanent dataset. It
does not mean a first-ever open of 10,000 completed fields can be instant
without reading any summary of those fields. That trade-off must be stated.

### Source index

The generator consumes the run's canonical capture records. Each entry names:

- dataset/acquisition identity;
- committed capture sequence and replacement identity;
- time, channel, and z indices;
- source file and source region;
- source-pixel-to-stage transform;
- source dtype and pixel size.

This index is derived and rebuildable. It must not become a third scientific
ledger beside the run records and the image metadata. A small spatial index in
memory maps a requested tile footprint to intersecting captures.

### First request for a tile

1. Validate the plane, level, and tile coordinates.
2. Find committed source positions intersecting the tile footprint.
3. If none intersect, answer 204.
4. Compute a dependency fingerprint from those source identities, their
   revisions, the encoding profile, resampler, and format version.
5. Return a cached JPEG whose sidecar has that fingerprint, if one exists.
6. Otherwise read the intersecting source data, rasterise it in committed
   ownership order, downsample in source precision, encode to the channel's
   fixed 8-bit range, and write the JPEG atomically. A tiled TIFF may permit a
   rectangular read; a stripped or single-plane export may require decoding a
   larger strip or the whole intersecting plane. The measurement must record
   which happened rather than assuming cheap random access.
7. Record its byte size and enforce both cache ceilings before publication.

The source fingerprint is local to the tile. A position landing elsewhere does
not make this tile stale merely because the acquisition revision increased.

### A position arriving while the view is open

The acquisition thread commits the scientific files and record first. Display
work happens afterwards in a bounded viewer worker; a slow JPEG must never hold
the stage or make a successful capture fail.

For every already materialised tile intersecting the new position, the viewer
has two safe choices:

1. rebuild it from its authoritative sources; or
2. while the viewer process remains alive, patch a lossless 8-bit working tile
   held under a strict RAM LRU, then derive a fresh JPEG from that complete
   working tile.

The second is the proposed live optimisation. It prevents a visible coarse
tile from rereading every earlier field on every landing, and it also prevents
repeated JPEG-to-JPEG encoding. It is transient: there is no persistent raw
pyramid that could defeat the disk goal. If the process restarts, the tile is
rebuilt from sources once and becomes hot again.

Tiles that have never been requested are not generated when a position lands.
Their source fingerprints will cause the right result if they are requested
later.

At the end of a live run the current visible/coarse JPEGs are already warm. An
unviewed completed run pays for its first coarse view on first open. A later
optional “warm display cache” command may prebuild coarse levels, but it is not
part of acquisition and obeys the same caps.

## Browser renderer

Use a new `jpeg-pyramid-under` option rather than changing `jpeg-under` in
place. The old option is a useful small, fixed-preview reference and its tests
should keep meaning what they mean today.

The first renderer spike should use the deck.gl packages already present in
`application/package.json`:

- `OrthographicView` gives a non-geographic top-down XY view;
- `TileLayer` selects visible non-geographic tiles, limits requests, passes an
  `AbortSignal`, and supports a byte-budgeted cache;
- `BitmapLayer` can place each decoded image over explicit bounds;
- a small BitmapLayer shader extension applies the source window, gamma,
  colour map, channel colour, and opacity.

These are reasons to spike deck.gl, not permission to assume it works. The
spike must prove the exact installed versions, the target browser, and the
target PyWebView engine. PyWebView on Windows must use Edge Chromium/WebView2;
an IE/MSHTML fallback is not an acceptable renderer for this viewer and should
fail at startup with a clear compatibility message.

One TileLayer is used per visible channel and selected `(t, z)`. The shader
turns decoded grayscale into display intensity. Version 1 supports additive
fluorescence compositing and the flat colour maps already offered by the panel.
Other blend modes wait until one is requested and tested.

The renderer keeps the existing `viz_studio/options/contract.md`:

- centres and zoom are stage micrometres;
- `setPlane`, `setMoment`, and `setChannel` retain their meanings;
- the application's overlay remains above the picture;
- `whenTheViewMoves`, `tilesMayHaveLanded`, and bounded `destroy` remain true;
- an empty acquisition list opens immediately so a plate can be planned before
  the microscope has captured anything.

The viewer may show a coverage/mean-grey placeholder while a first-ever coarse
tile is being generated, but it must label the state as loading. It must never
present a placeholder as the finished scientific image.

## Browser and PyWebView delivery

The same HTTP routes serve both. No JPEG bytes cross a Python-to-JavaScript
bridge method and no base64 copy is made. PyWebView opens the same local URL as
an ordinary browser, which keeps testing and caching behaviour identical.

Minimal friction means:

- no browser extension;
- no custom image codec or service worker in version 1;
- no `file://` mode for the product path;
- one local server already owned by the application/viewer;
- a startup capability check for WebGL2 and the required PyWebView engine;
- ordinary JPEG responses that can be inspected with browser tools or `curl`.

## Ownership boundary

The recommended production boundary is:

- ZMART-microscopy owns capture records, authoritative files, scan plans, and
  stage placement facts;
- ZMART Viewer owns display-cache generation, manifests, tile HTTP responses,
  and the browser drawing adapter;
- the operator page owns controls and overlays and speaks only through the
  viewer contract.

This repository may host the measurement spike under `viz_studio/`, because
the old JPEG reference and the common engine tests already live there. The
production code should not be copied independently into both repositories.
Before phase 3, the current ZMART Viewer repository must be open beside this
one and the API ownership settled file by file.

## Implementation plan

Each phase ends at a gate. Do not continue merely because code has been
written.

### Phase 0 — measure the current paths

No product code.

1. Install/run the real Smart Viewer 0.2 server, not the vendored historical
   backend.
2. Use the same completed and live acquisitions for:
   - Smart Viewer/OME-Zarr;
   - current one-JPEG-per-field viewer;
   - the later pyramid spike.
3. Record cold and warm time to first meaningful picture, time to settled
   whole-plate view, requests, transferred bytes, decoded/GPU memory, frame
   times while panning, and disk bytes.
4. Repeat at approximately 100, 1,000, and 10,000 fields, and with one and four
   visible channels.
5. Name the browser, PyWebView renderer, server commit, and dataset in every
   result.

Gate: continue only if the present path still has a material viewport or
deployment cost that JPEG can plausibly remove.

### Phase 1 — static single-plane pyramid generator

Prototype under `viz_studio/`; do not wire it into the workflow.

1. Build the fixed grid and manifest from explicit synthetic capture records.
2. Generate requested tiles directly from TIFF source regions.
3. Prove level dimensions, edge tiles, physical placement, stable encoding,
   and atomic publication.
4. Compare 512/1024 tiles, JPEG 85/90/95, and area/max downsampling on at least
   two real ZMART fields: sparse fluorescence and dense tissue.
5. Enforce both cache ceilings in the generator from the start.

Gate: a static pyramid stays below the target caps or demonstrates useful
partial-cache eviction, and its rendered view is acceptably faithful to a TIFF
reference under the same display transform.

### Phase 2 — browser adapter

1. Add a separate `jpeg-pyramid-under` option.
2. Fetch only tiles intersecting the viewport at the appropriate level.
3. Apply channel window/colour/gamma/opacity on the GPU.
4. Enforce request cancellation and a conservative decoded-memory budget.
5. Meet the whole existing option contract and its placement tests.

Gate: increasing the source from 1,000 to 10,000 fields at the same settled
whole-plate view does not increase the request count or decoded memory in
proportion to the field count.

### Phase 3 — time, z, and channels

1. Keep one pyramid per `(t, c, z)`.
2. Switch planes and moments without changing XY placement.
3. Make all current panel channel controls truthful against the 8-bit encoding
   range.
4. Test at least two channels, three z-planes, and two moments; current one-
   plane fixtures are not enough.

Gate: the panel, engine read-back, and photographed pixels agree after every
control change.

### Phase 4 — live publication

1. Append new source records only after the scientific capture is committed.
2. Revalidate the manifest revision through the existing
   `tilesMayHaveLanded()` path.
3. Add the bounded transient working-tile RAM cache.
4. Prove that a source landing outside the viewport does not regenerate or
   refetch the visible view.
5. Prove that a source landing inside it changes only the intersecting tile
   chain and never exposes a partial JPEG.
6. Finalise or restart the viewer and prove the same tiles rebuild from source.

Gate: live display work cannot delay or fail acquisition, and the cost of one
landing is bounded by affected/visible tiles rather than total fields.

### Phase 5 — operator integration

1. Have the real viewer server advertise the JPEG-pyramid manifest as an
   explicit two-dimensional display source.
2. Let the workflow choose it deliberately for the flat view. Do not catch an
   OME-Zarr failure and quietly substitute JPEG.
3. Keep the volume action on the volume-capable source.
4. Preserve the canvas view and overlays while a first acquisition arrives.
5. Show the operator whether they are looking at a display derivative and
   provide a direct route to the scientific-data view.

Gate: all existing 54-field and 864-field operator walks pass, the plate stays
on screen, every field is checked separately, and a deliberately broken JPEG
path produces a visible failure rather than a substitute picture.

### Phase 6 — target-machine proof

Run on the microscope PC in both its supported external browser and PyWebView.
Measure a completed cold run, a warm run, and a live run. Inspect the pictures,
not only the assertions.

Gate: both cache ceilings hold, the target view is responsive, WebView2 needs
no manual intervention beyond installation checks already needed by the app,
and no scientific workflow reads the derivative.

## Proposed files for the spike

Names are proposed so review can challenge the boundary before code exists.

```text
viz_studio/backend/jpeg_pyramid.py
    grid, manifest, source index, tile rendering, cache accounting

viz_studio/options/jpeg-pyramid-under/viewer.js
    option contract and deck.gl TileLayers

viz_studio/options/jpeg-pyramid-under/intensity-bitmap-layer.js
    the small grayscale/window/colour shader extension

viz_studio/tests/test_jpeg_pyramid.py
    backend format, geometry, intensity, cache, concurrency

viz_studio/tests/test_the_jpeg_pyramid_viewer.py
    real-browser fetching, placement, controls, memory/request behaviour

viz_studio/measure_jpeg_pyramid.py
    the non-asserted scale/quality/size measurements
```

Only after the spike passes should production routes be assigned between the
actual ZMART Viewer server and the thin bridge integration. `application/framework/bridge.py`
should not absorb a second full viewer backend simply because it already serves
the old previews.

## Required tests

### Backend contracts

- All levels have the declared dimensions and exact physical extent.
- A source pixel and a tile corner land at the expected stage micrometres.
- One source value maps to the same approximate JPEG value at every level.
- Different tiles and fields never choose independent intensity ranges.
- Edge tiles are cropped or clipped without stretching.
- Unsupported orientation, extent growth, overlap, and dtype fail visibly.
- A retake has deterministic ownership.
- Two concurrent requests produce one valid final tile.
- Killing generation leaves no published partial file.
- An unrelated new position leaves a tile fingerprint and ETag unchanged.
- Cache eviction never crosses either ceiling and never removes source data.
- Deleting the cache and rebuilding produces equivalent display pixels within
  the JPEG tolerance.

### Browser contracts

- Whole-plate requests use coarse global tiles, not one request per field.
- Zoom selects the next level without a blank flash or a misplaced image.
- A stale/off-screen request is aborted and is not cached as a success.
- The byte-budgeted cache remains bounded with four channels.
- Black/white, gamma, colour, LUT, opacity, and visibility alter only the
  intended channel.
- Z and T controls select pixels without translating XY.
- Every source's anchor-plane centre maps to display z=0 in 2-D, while its
  original acquisition Z remains recoverable.
- A one-plane source is sampled at its voxel centre and stays visible while a
  separate stack changes its local plane.
- Channels and derived layers share one geometry identity and cannot add a
  second Z placement.
- Acquisition types at different pixel sizes align in micrometres.
- A live visible tile changes after publication; an unrelated one does not.
- Empty, loading, failed, and genuinely black are distinguishable states.
- `destroy()` releases requests, ImageBitmaps/textures, listeners, and WebGL
  resources.

### Visual comparisons

Render the TIFF reference and JPEG path through the same display window and
compare the final screen pixels. Include sparse puncta, smooth gradients,
dense tissue, a hot pixel, a tile seam, dark acquired ground, and a field
retake. Numeric image metrics may support the decision, but photographed
features and seams are the acceptance evidence.

### Performance gates

Exact numbers are provisional until phase 0 establishes the target machine.
The relationships are not provisional:

- requests and decoded memory for one settled view follow viewport area and
  visible channel count, not source field count;
- warm panning does no source reads and no JPEG encoding;
- a position landing outside the view does no visible-tile transfer;
- persistent cache remains below both ceilings at every point, not only after
  a cleanup pass;
- acquisition timing is unchanged within measurement noise when the viewer is
  closed and when it is open.

## Failure behaviour

- Missing source: the tile fails and names the source; no black success tile.
- Unsupported geometry: the acquisition is unavailable in the JPEG engine and
  the reason is shown.
- Cache full: evict by policy; if nothing may be evicted, serve an uncached
  result or decline the tile rather than exceed the ceiling.
- Bad manifest: refuse the source; do not guess a schema.
- Renderer unavailable: external browser may still be offered; PyWebView names
  the missing WebView2/WebGL capability.
- Generator timeout: bounded failure and later retry; never an endless loading
  promise.
- Source changes during a read: discard the result when its fingerprint no
  longer matches and retry against the committed revision.

## Rejected shortcuts

- **One enormous JPEG per plane.** Small transfer does not prevent enormous
  decoded memory, and the browser cannot range-decode arbitrary JPEG regions.
- **Only one thumbnail per field.** Already measured: far-zoom convergence and
  requests still follow field count.
- **Build parent JPEGs from child JPEGs.** Loss accumulates at each generation.
- **Patch and re-encode an old JPEG after every landing.** Unchanged pixels
  degrade repeatedly. A transient lossless hot tile avoids this without a
  second persistent dataset.
- **A per-tile or per-level stretch.** It makes neighbouring fields and zoom
  levels incomparable.
- **12/16-bit JPEG for the browser.** It gives up the compatibility and minimal
  friction that motivate the design.
- **A persistent uncompressed working pyramid.** It defeats the lightweight
  disk goal.
- **Generate every level during acquisition.** It spends microscope time on a
  view nobody may open.
- **Automatic JPEG fallback.** It previously made a broken image pipeline look
  healthy and is deliberately not returning.
- **Treat z as an XY placement correction.** A flat overview is flat display
  geometry even when its focus height varies across the sample.

## Stop conditions

Do not continue to production if any of these holds after the spike:

- Smart Viewer 0.2 already meets the same request, latency, memory, and
  deployment goals on the target run.
- Useful fluorescence detail cannot survive a stable 8-bit mapping within the
  disk caps.
- A truthful live path needs a persistent lossless pyramid large enough to
  defeat the size goal.
- Browser/PyWebView decoded or GPU memory remains excessive at the tile size
  needed for acceptable request counts.
- Correct physical placement requires unrecorded orientation or silent stage
  snapping.
- Maintaining the JPEG path would create two independent production viewer
  backends with the same responsibilities.

## Questions for review

1. Are the relative and absolute cache caps defined against the right source
   byte set, especially when the TIFFs are already compressed?
2. Are 5 GiB soft and 10 GiB hard reasonable defaults on the microscope PC, or
   should both be lower?
3. Is the fixed linear 8-bit channel encoding sufficient for the real cameras,
   or should a versioned nonlinear transfer be tested?
4. Is transient lossless RAM for hot live tiles enough to avoid repeated
   coarse-tile rebuilds, including after a viewer restart?
5. Should the first version refuse all within-acquisition overlap, rather than
   include latest-committed ownership?
6. Does deck.gl's TileLayer plus a BitmapLayer shader remain the smallest
   renderer under the existing option contract?
7. Which exact responsibilities belong in ZMART Viewer rather than this
   repository's bridge?
8. What real datasets and target-machine thresholds should make the stop/go
   decision?
9. Is there a cheaper way to make Smart Viewer/OME-Zarr satisfy the same goals
   without a second display format?
10. Is the proposed source-anchor model compatible with the actual Smart Viewer
    scene/link representation, and where should per-source 2-D versus 3-D
    presentation transforms be stored?
11. Should a one-plane source remain pinned to its anchor while another stack
    is navigated, or should the 2-D panel expose per-source plane selection from
    the start?
