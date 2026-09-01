# Viewer delivery after the JPEG-pyramid review

Date: 2026-09-01

Status: revised design and stop decision. Do not start a separate JPEG-pyramid
implementation. Begin only with the phase-0 contract and measurement work below.

Reviewed against:

- ZMART-microscopy commit `d8a67923`;
- the review on branch `claude/lazy-jpeg-pyramids-review-fhz6te`, commit
  `48f72d64`;
- ZMART Viewer 0.2.0 at commit `9ff10b0`.

## Decision

Do not build the proposed `jpeg-pyramid-under` engine.

Keep ZMART Viewer 0.2 as the one path that supplies pixels to the operator
canvas. It already composes only the requested pieces, uses the positions'
existing multiscale data, and has measured viewport work that stays nearly
flat over surveys from 64 to 16,384 positions. The old 8,400-request problem
belonged to the retired `jpeg-under` reference engine, not to the active
canvas.

The work should now proceed in this order:

1. Give every acquisition one declared display window per logical channel.
2. Measure Viewer 0.2 on real ZMART runs and the microscope PC, concentrating
   on cold opening, coarse warming, browser memory, and bytes actually moved.
3. Improve the existing composer's lazy serving only where those measurements
   show a problem.
4. Consider an 8-bit or JPEG response only if bytes or decode cost remain a
   measured bottleneck. Such a response must use the existing piece addresses,
   geometry, revision, source, and canvas. It must not create another viewer.

JPEG is therefore a conditional delivery encoding, not the architecture.

## What changed after review, and what did not

### Accepted

**The baseline was wrong.** The 8,400-field request queue was measured on the
old `jpeg-under` option. The workflow now opens `neuroglancer-under`, and
Viewer 0.2 already builds pieces on demand. The problem statement, phase order,
and default architecture have all been rewritten around the current path.

**A second production viewer is not justified.** The old plan's ownership
boundary decided who would maintain the duplication but did not remove it. The
revision forbids a second grid, manifest, source, invalidation loop, renderer
state, and canvas. It follows ZMART Viewer's own one-door/one-source direction.

**Decimation is the incumbent reducer.** Both repositories retain every second
pixel. The old plan incorrectly framed the choice as area versus maximum
reduction. The revision starts from the existing decimated levels and requires
an explicit coordinate translation plus a registration gate for any other
reducer.

**There is no acquisition-wide encoding window today.** The application
measures a window separately for every position. The old precedence referred
to preset and run-level values that are not yet recorded. The first work
package now creates that contract, and irreversible encoding refuses an
unresolved channel.

**Camera range is not a display fallback.** It remains valid as numeric
`min`/`max` provenance, but it may never supply display `start`/`end`. In an
8-bit derivative that mistake would be irreversible.

**The storage arithmetic and gates needed correction.** Ratios now use unique
compressed bytes actually on disk, storage categories are reported separately,
one absolute all-runs cap prevents a 500 GB run from receiving a 50 GB cache,
and the conditional encoding phase must beat Viewer 0.2 by a stated margin.

**The current Z evidence was overstated.** The separation of acquisition,
source, presentation, and navigation Z remains sound. However, the `z=0`
versus `z=0.5` observation came from a debugging report rather than a named
committed test or trace. The revision labels it reported evidence and requires
the repository to make it reproducible.

### Qualified rather than accepted literally

**Area averaging does not inevitably break registration.** It does break the
current scale-only, decimation-based convention if the corresponding half-block
translation is omitted. A different reducer can be registered with explicit
per-level transforms. The revision keeps that technical possibility while
making decimation the only default compatible by construction.

**JPEG may still have value, but not yet as a viewer.** Viewer 0.2's existing
measurements disprove the field-count motivation. They do not prove that
16-bit response bytes and browser decoding are optimal for every remote or
low-memory client. The revision retains one conditional encoding experiment,
but only behind a fivefold-byte and no-regression gate and only on the existing
piece route.

**The review suggested a persistent cache floor for small runs.** This revision
does not add one. A floor can violate the user's ten-per-cent limit. When a
small run's allowance cannot hold a screenful, transient RAM or no persistence
is safer than silently exceeding the rule.

**The suggested performance margins are starting values.** Two seconds,
500 ms, fivefold, and 5 GiB are explicit so the gates can fail. They remain
provisional until agreed before measurement on the microscope PC. They may not
be relaxed after seeing an unfavourable result merely to preserve a design.

### Retained from the original design

The review agreed with, and this revision keeps:

- TIFFs and canonical scientific data remain authoritative;
- JPEG or another 8-bit response is display-only;
- no silent fallback may conceal a broken scientific path;
- channels remain independent and colour/gamma stay in the browser;
- no per-tile or per-level stretch;
- no parent image is built from already lossy children;
- atomic publication and bounded failures;
- server-issued addresses and strict range validation;
- a stable live grid and source revision;
- acquired black remains distinguishable from unimaged ground;
- WebView2/WebGL2 is required for PyWebView;
- raw acquisition Z remains recoverable and does not silently become registered
  specimen Z.

## Why the decision changed

The first proposal used the wrong baseline. Its motivating observation came
from `viz_studio/backend/jpeg_tiles.py`: one 128-pixel JPEG and one request per
field. The workflow now selects `neuroglancer-under` in
`application/workflows/target_acquisition/shared/stage.js`.

ZMART Viewer 0.2's `zmart_viewer/compose.py` already indexes the positions per
level and composes only the piece being asked for. Its recorded measurements
show:

- landing-to-visible stays around a few hundred milliseconds through 16,384
  positions in its container ladder;
- one additional landing in a warm 10,000-position survey derives in 76 ms
  and rereads no tiles;
- a warm baked piece is served in about 0.15 ms;
- the remaining scale-dependent costs are chiefly the one-time bake and coarse
  warm, not one browser request per position.

Those figures are synthetic or machine-specific. They still disprove the
original architectural premise. Real-machine measurement remains necessary,
but a second image path is not justified before it.

## Product goal

The operator must be able to open and navigate ZMART microscopy data in a
browser or PyWebView with minimal waiting and no scientific ambiguity.

For a settled view:

- work should follow the number of visible pieces, not the number of fields;
- a whole acquisition should appear coarsely first and sharpen on demand;
- close zoom should show the source resolution in the visible region;
- channel controls should remain responsive;
- browser, RAM, and persistent duplicate storage must be bounded;
- the same picture, geometry, controls, and failure state must appear in the
  standalone Viewer and the embedded operator canvas.

Vendor TIFFs remain authoritative provenance. The OME-Zarr position stores are
the scientific representation used by the Viewer. Any display encoding is a
rebuildable derivative and must never be used for analysis.

## One path and one source

The target architecture is the one already described in ZMART Viewer's
`docs/open/PLAN_one_door_one_source.md` and
`docs/open/PLAN_two_viewers_one_contract.md`:

```text
acquisition record and OME-Zarr positions
        -> one Viewer dataset/source
        -> one piece-address and revision contract
        -> one embedded canvas
```

For a live run, the source URL stays stable and its revision advances. The
browser invalidates that source and asks again only for visible pieces.

The following are forbidden:

- a JPEG grid beside the Viewer's grid;
- a JPEG manifest beside the Viewer's source description;
- a second live invalidation mechanism;
- a second layer transform;
- a hidden fallback that draws JPEG when the scientific path failed;
- a second operator canvas underneath or above the first.

A later encoded response may have another media type or codec, but it remains
another representation of the same addressed piece and revision.

## Phase 0A: make the display-window contract explicit

This is useful whether or not a JPEG is ever written.

### The current gap

`application/parts/storage/zarr_positions.py` calls `_a_window_onto` for every
position and channel. A bright tissue field and an empty field can therefore
declare different starting brightness even though they belong to one logical
acquisition channel.

The current Viewer can still measure data when a store declares no useful
window. That is a reversible display choice because the original 16-bit values
remain. It is not a valid source for an irreversible 8-bit encoding unless the
chosen result is resolved once and recorded.

### Authority

One acquisition-level channel description owns the opening display window.
Each channel has a stable key rather than relying only on its array index.

The ordinary OME metadata remains:

```json
{
  "label": "488",
  "color": "00FF00",
  "window": {
    "min": 0,
    "max": 65535,
    "start": 300,
    "end": 4200
  }
}
```

`min` and `max` describe the number type or detector room. `start` and `end`
describe the initial display. Readers must never substitute the first pair for
the second.

ZMART provenance should additionally say how the display pair was obtained:

```json
{
  "zmart": {
    "displayWindows": [{
      "channelKey": "488",
      "start": 300,
      "end": 4200,
      "method": "preset",
      "algorithm": null,
      "sampleCount": 0,
      "resolvedAtRevision": 0
    }]
  }
}
```

The exact spelling belongs to the acquisition/view contract and should be
settled with the Viewer repository before code changes. The important facts
are channel identity, the two display bounds, the method, and when the choice
became fixed.

### Resolution policy

Use this order:

1. An explicit window in the acquisition preset or protocol.
2. An operator-approved window recorded for that run and channel.
3. A deterministic acquisition-wide measurement made by the existing Viewer
   and then recorded with its algorithm and revision.
4. No declared window.

Step 4 means the 16-bit Viewer may keep measuring a provisional display range.
It does not mean the camera range becomes the display range. It also means an
8-bit derivative must refuse to encode that channel.

Do not compute and stamp a permanent value from the first field. Do not update
a declared value whenever another field lands. A live automatic policy, if it
is later needed, must define a deterministic sampling set and a single freeze
event; until then, use presets or an explicit operator action.

### Writer and view behaviour

- The acquisition record carries the channel descriptions.
- `position_store_from_record` receives them rather than inventing a new
  window for each position.
- Every position in one acquisition mirrors the same channel window where one
  is declared.
- When no acquisition-wide window exists, position stores omit `start` and
  `end`; they still record honest `min` and `max`.
- The composed/linked Viewer's source description carries the acquisition
  window once and is the authority used by the embedded canvas.
- A legacy folder whose positions disagree does not silently choose the first
  store's value. The Viewer measures the composed acquisition or reports the
  disagreement, then records a resolved value only through an explicit
  migration or operator action.

### Tests and gate

Tests must prove:

- two fields with very different brightness receive the same declared window;
- channel identity, not arrival order, maps windows to channels;
- an absent display window remains absent and never becomes camera min/max;
- a Viewer-measured fallback can change the display without changing pixels;
- any recorded resolution is stable across reopen and names its provenance;
- no 8-bit encoder accepts an unresolved channel;
- existing foreign OME-Zarr without ZMART provenance still opens normally.

Phase 0A passes when one run-level channel description can be followed from
the acquisition record to every position and the one Viewer source. It fails
if two parts of the path remain independent authorities.

## Phase 0B: establish the real Viewer 0.2 baseline

Do not regenerate the synthetic measurements merely to obtain new numbers.
First read:

- `docs/measured/MEASURED_the_ladder_of_surveys.md`;
- `docs/open/MEASURED_the_four_ways_of_serving.md`;
- `docs/how_it_works/HOW_OURS_DIFFERS_FROM_OME_ZARR.md`;
- `docs/open/PLAN_one_door_one_source.md`.

Then repeat only the adoption measurements that have not been made on a real
ZMART run and the actual microscope PC.

### Fixtures

Use at least:

- a representative small run;
- a multi-channel overview large enough to exercise plate-scale zoom;
- the largest available real run;
- a live replay with positions arriving at the expected acquisition rate;
- a sparse fluorescence run containing dim puncta and bright outliers;
- a stack plus a one-plane overview for the Z contract.

Record the exact Viewer and ZMART-microscopy commits, browser/PyWebView engine,
WebView2 version, GPU renderer, CPU, RAM, disk type, and whether source data is
local or remote.

### One scripted trace

Run the same trace for `neuroglancer-under` and `viv-under` where both can open
the fixture:

1. cold open and fit the whole acquisition;
2. wait for the first scientifically recognisable coarse picture;
3. wait for the requested view to settle;
4. pan one viewport;
5. zoom to one well;
6. zoom to source-pixel scale;
7. enable four channels and change each display window;
8. revisit the first whole-acquisition and well views;
9. publish one new position during the session;
10. close and reopen.

### Measurements

Measure, rather than infer:

- time to first recognisable picture;
- time to settled sharp view at each zoom;
- p50, p95, and worst pan/zoom response;
- landing-to-visible latency;
- requests, response bytes, and codec for every step;
- source blocks read and pieces encoded;
- Python CPU and peak working set;
- browser JS heap, decoded image/array memory where exposed, and GPU memory or
  a defensible proxy;
- warm and bake duration;
- bytes persisted in every category described below;
- correctness: channel count, display windows, placement, live freshness, and
  absence of transient wrong pixels.

### Stop gate

Stop after phase 0 when the existing Viewer meets the following on the target
machine:

- a useful whole-acquisition picture appears within 2 seconds;
- a settled pan or zoom completes within 500 ms at p95;
- a new live position is visible within 500 ms at p95 after publication;
- memory reaches a stable bound during repeated navigation;
- automatic duplicate storage stays inside the agreed absolute cap;
- no position-count-proportional browser request pattern appears.

These initial usability thresholds should be adjusted only before running the
trace, with the reason recorded. A threshold may not be loosened after seeing a
bad result merely to keep an implementation idea alive.

If Viewer 0.2 passes, the JPEG work stops. Embedding the existing canvas is the
next product task.

## Storage accounting and the 500 GB case

Do not describe every non-TIFF byte as one cache. Report these categories
separately:

1. vendor TIFF source;
2. canonical OME-Zarr scientific position stores;
3. position-store pyramid overhead;
4. linked-view metadata and pointer maps;
5. baked Viewer pieces;
6. automatic persistent delivery cache;
7. browser HTTP cache;
8. transient server and browser memory.

Only categories explicitly documented as rebuildable may be deleted by cache
eviction. Calling scientific working data a cache does not make it disposable.

Every ratio uses the unique compressed source bytes actually present on disk,
not an uncompressed `width x height x dtype` estimate. Deduplicate hard links,
reflinks, and repeated references when counting.

The default policy proposed for automatic delivery derivatives is:

```text
per-acquisition hard ceiling = 10% of unique compressed source bytes
all-runs automatic-cache hard ceiling = 5 GiB
effective ceiling = the smaller applicable allowance
```

The 5 GiB value is a provisional operational default, not a scientific
constant. It answers the important requirement: a 500 GB source is not granted
50 GB merely because ten per cent sounds small. With the proposed default, all
automatically managed runs together cannot exceed 5 GiB.

Linked-view metadata should be the default because it copies no image pixels.
An explicit user-requested bake is not silently exempt from accounting: the UI
must show its estimated and final duplicate bytes. Whether user-requested bakes
share the automatic cache cap is an operational decision that must be made
before deployment.

Do not add a persistent per-run floor that violates the ten-per-cent rule. If a
small allowance cannot hold one screenful, serve it transiently in RAM or do
not persist it.

Eviction must be one process-wide service with one lock or database. Two Viewer
processes must not run independent eviction loops against the same root.

## Phase 1: improve the existing path only if phase 0 fails

Classify the measured failure before changing code.

### If cold open or coarse warm is the problem

Work inside ZMART Viewer's composer and one-source plan:

- let visible requests pre-empt background warming;
- make warming cancelable when the source revision changes;
- consider a sparse cache of already requested coarse pieces using the same
  existing piece address and codec;
- persist only where repeated-open measurements show a real benefit;
- keep live runs unbaked by default, consistent with the existing measurements;
- bake at run end only when the measured revisit benefit justifies its bytes.

Do not create a new grid or frontend source. The existing on-demand composer is
already the lazy generator.

### If bookkeeping is the problem

Profile the recorded O(number of positions) derive bookkeeping and remove only
the proven scan. Retain the tests that show a new landing rereads no old tiles
and that bursts coalesce.

### If browser memory is the problem

First bound the existing engine's cache and visible channel set. Measure Viv
before writing a deck.gl layer: it already supplies orthographic multiscale
drawing and per-channel colour/window controls. A new renderer is considered
only when the installed engines cannot meet the bound.

### Gate

Phase 1 must make the failing phase-0 metric pass without introducing a second
source or worsening any correctness gate. If it does, stop. Do not proceed to
8-bit delivery merely because phase 1 was completed.

## Phase 2: conditional 8-bit delivery experiment

Enter this phase only when phase 0 and the smallest phase-1 correction show
that transfer or decoding of the existing 16-bit pieces is still the dominant
cost.

### Candidates

Compare at least:

1. existing source dtype and codec;
2. 8-bit linear encoding with the existing chunk codec;
3. 8-bit grayscale JPEG, if the client can consume it without a parallel
   source contract.

The conversion is display-only:

```text
source uint16/float
    -> select the existing resolution
    -> apply the one resolved acquisition/channel display encoding window
    -> encode an 8-bit response
```

The scientific source keeps its dtype. Ordinary browser JPEG does not preserve
`uint16`; it preserves only an approximate mapping back through the recorded
window. Gamma, colour, opacity, and the operator's narrower display window stay
in the GPU and are not baked into the response.

### Geometry and reduction

Decimation is the incumbent. Both repositories keep every second pixel so a
coarse sample remains the low-corner sample of its fine block. The conditional
experiment starts with those existing levels; it does not build an
independently resampled pyramid.

Area and maximum reduction may still be useful for sparse fluorescence, but
they are separate visual experiments. Either one must declare its per-level
coordinate translation explicitly. Averaging is not inherently impossible to
register, but reusing a scale-only transform from the decimated pyramid would
shift the represented sample centre by `(2^k - 1) / 2` fine pixels at level
`k`. Any alternative must pass the cross-engine registration gate and must not
replace the incumbent silently.

Named visual risks:

- decimation can omit a punctum that falls between retained samples;
- area reduction can dim a small bright punctum;
- maximum reduction can enlarge hot pixels and make brightness jump with zoom.

### One route, not another pyramid

The server receives the ordinary Viewer piece address plus an explicitly
negotiated representation. It composes that ordinary piece from canonical
data, encodes it, and returns it with the same source identity and revision.

An encoded response cache, if measurements justify one, is keyed by:

```text
source identity
source revision
level, t, c, z, row, column
encoding profile and version
```

It obeys the shared absolute storage cap. A source or window revision makes
old encoded entries unreachable. It never rebuilds a JPEG from another JPEG.

The frontend may require a loader adapter, but it may not introduce another
layer list, navigation state, geometry transform, source manifest, or live
refresh path.

### Decision gate

Use the identical phase-0 trace. A new representation proceeds only if it:

- reduces transferred bytes by at least fivefold for the four-channel trace;
- does not make first-picture or p95 navigation time more than ten per cent
  worse;
- does not increase stable browser/GPU memory;
- remains inside the automatic cache ceiling;
- keeps every overlay and recognisable feature registered with Viewer 0.2 at
  every resolution;
- preserves dim structures judged important by the microscopy fixture;
- adds no second source, grid, scene, or invalidation contract.

If bytes improve but local PyWebView latency does not, do not ship it for the
operator canvas. A remote-viewing product may make a separate case later.

## Z remains a separate correctness track

The JPEG discussion does not own Z. Keep these facts distinct:

- source-local Z: plane centres, order, spacing, direction, and anchor;
- acquisition Z: stage/focus provenance from microscope movement;
- presentation Z: the transform that makes sources meet in a viewer scene;
- navigation Z: which plane an operator last selected.

For the flat two-dimensional overview:

```text
display_transform(source anchor-plane centre) = world z=0
```

Overlaying sources need not have equal raw acquisition Z. Their selected
anchor centres meet at one display plane. Channels, masks, and annotations
inherit the source transform; layers do not add another independent Z offset.

Single-plane sources anchor on their only plane. Stacks use an explicit
reference/focus plane. Until one convention is changed everywhere, legacy
stacks use the existing `theMiddlePlaneOf` rule:

```text
Math.floor(max(plane_count, 1) / 2)
```

Resolve and record the fallback when building the scene. Never choose it from
load order or recompute it adaptively.

The reported debugging trace says a one-plane source rendered at local `z=0`
and disappeared at `z=0.5`. That is plausible voxel-centre/boundary evidence,
but it is not yet named by a committed test, log, or screenshot. The current
fix should remain narrow, and the repository must record the evidence before
the plan calls the half-voxel convention proven.

Future 3-D placement is not simply raw stage Z. It requires validated Z scale,
axis direction, anchor, stage calibration, and a common specimen datum. Preserve
the raw acquisition Z now; do not claim physical registration yet.

Tests must prove:

- every flat overlay anchor maps to `z=0`;
- the single-plane voxel centre, not its boundary, is sampled;
- stack plane order and spacing remain unchanged;
- raw acquisition Z remains recoverable;
- the layer does not apply a second translation;
- 2-D/3-D switching changes presentation state, not source metadata;
- per-source remembered planes remain navigation state.

## HTTP and PyWebView

Use the existing server policy as the starting point. It already distinguishes
live descriptions and image data from immutable finished data. The browser
options currently request `cache: "no-store"`, so ETag or immutable-response
experiments must first name which fetches are allowed to use the browser cache.

PyWebView requires Edge Chromium/WebView2 and WebGL2. The Windows launcher
already checks for WebView2; phase 0 adds the WebGL2, renderer, and texture-size
report. MSHTML is not a supported fallback.

## Ownership

ZMART-microscopy owns:

- acquisition records and channel descriptors;
- authoritative TIFFs and canonical position stores;
- stage placement and raw acquisition Z provenance;
- the operator workflow and embedding boundary.

ZMART Viewer owns:

- the one source and piece-address contract;
- composition, optional bake, and response encoding;
- cache accounting and invalidation;
- the browser canvas and its channel controls;
- performance harnesses for serving and drawing.

Changes spanning those boundaries are planned together but implemented in the
repository that owns the behaviour. Do not copy Viewer production code back
under `viz_studio/backend`.

## Delivery order

1. **Adopt this stop decision.** No `jpeg-pyramid-under` implementation.
2. **Settle the window schema.** Review it with ZMART Viewer before code.
3. **Implement the run-wide window contract.** Keep legacy fallback reversible.
4. **Run the real phase-0 trace.** Publish raw results and environment.
5. **Stop if Viewer 0.2 passes.** Embed the one canvas.
6. **Fix only the measured existing-path bottleneck.** Repeat the trace.
7. **Stop if it passes.** Do not reward work with more work.
8. **Run the conditional encoding experiment only if bytes/decode still fail.**
9. **Adopt an encoding only if every decision gate passes.**
10. **Validate the unchanged one-source path in PyWebView on the microscope PC.**

Every step lands separately with its evidence. No phase is authorized merely
because the previous document described it.

## Stop conditions

Stop the JPEG/8-bit idea when any of these is true:

- Viewer 0.2 already meets the operator thresholds;
- the remaining delay is bake/warm work that can be made lazy in the composer;
- transfer bytes are not the dominant cost on local PyWebView;
- no truthful acquisition-wide channel window is available;
- the encoded route cannot reuse the existing grid, source, and revision;
- decoded memory is equal or worse;
- important dim structures do not survive the mapping;
- cross-resolution registration differs from the incumbent;
- the fivefold byte improvement is not reached;
- automatic duplicate storage cannot remain under both caps.

Stopping is a successful result: it prevents a second production viewer from
being built for a cost the current viewer already removed.

## Questions for the next review

1. Is the acquisition/view boundary the correct authority for a channel's
   declared display window?
2. Should an explicitly chosen window live first in the acquisition record,
   the composed view's OME metadata, or both with one named authority?
3. Does the current linked/baked Viewer persist any duplicate image category
   omitted from the storage accounting above?
4. Are the 2-second, 500-ms, fivefold, ten-per-cent, and 5-GiB gates appropriate
   for the microscope PC, before they are measured?
5. Which existing Viewer harness is the smallest extension for response bytes,
   browser memory, and the fixed navigation trace?
6. Can an 8-bit existing-codec response be consumed by the current engine with
   less work than JPEG, or would either require a second source in practice?
7. Where should the reported `z=0` versus `z=0.5` evidence be recorded and
   gated so the half-voxel correction becomes reproducible?
