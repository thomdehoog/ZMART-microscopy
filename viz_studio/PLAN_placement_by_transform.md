# Placement by transform, not by pixels

Each position carries its own offset in its own description, and the viewer draws
it where that says. Nothing is rewritten, nothing is padded, and an offset can be
revised later by editing a few bytes of JSON.

Measured today, on ten positions of the benchmark ladder: ten stores, each pulled
back 16.64 µm — **51.2 voxels, a fractional voxel** — placed correctly on screen
with no pixel altered. The pointer map cannot express that offset at all.

## Which numbers to trust

This document's tables disagree with each other, because the harness was wrong
underneath them and was fixed twice while they were being taken. **These are the
current ones. Anything elsewhere in this file or in the commit history that
contradicts them is superseded.**

Conditions matter more than the figures. A reading is only comparable to another
taken the same way, and there are four axes: which machine drew it, whether the
opening waited for the sources to *resolve* or merely be handed over, whether the
camera was pinned, and whether the engine was stock or carried the batched-bind
prototype.

**On the card (NVIDIA T400), stock engine, every source resolved, camera pinned.**
The only figures that describe the machine anyone uses:

```
400 positions        picture      sources
opening               0.31 s       4.95 s
drawing frame         0.6 ms       3.4 ms
a position costs         --        7.3 us
frames a second          116          105
```

**In software (headless SwiftShader), stock engine, same waits.** Useful for shape,
not for magnitude -- about two thirds of main-thread busy is the rasteriser reading
the canvas back, which inflates the slower arrangement more than the faster one:

```
positions    picture opening    sources opening    sources, a position costs
        5        0.21 s             0.25 s              --
       50        0.22 s             0.45 s             202 us
      100        0.24 s             0.72 s             393 us
      200        0.25 s             1.76 s             369 us
      400        0.24 s             6.32 s             371 us
```

**The picture as tiles climb**, overlapping, seams chunk-aligned, software:

```
    400 tiles   0.21 s    map 0.09 MB
  2,500 tiles   0.29 s    map 0.55 MB
 10,000 tiles   0.53 s    map 2.19 MB
```

**The batched-bind prototype**, software, four hundred overlapping sources:
2.36 s against 8.06 stock, and x3.9 for x4 positions rather than x10.3.

### Superseded, and why

- **"400 sources open in 3.64 s"** -- measured against `zmartSourcesWaiting()`, which
  returns with three hundred of the four hundred still unresolved. The page was three
  quarters loaded.
- **"The picture is flat at 0.22 s to ten thousand"** -- inherited from an older
  ladder on different geometry and never measured here. Measured, it is 0.53 s and it
  grows with the map.
- **"Declaring once is worth about a fifth"** -- measured against a software total
  that is half rasteriser artefact. Retracted; the experiment that settles it is a
  warm-cache run on the card, which has not been done.
- **Any ratio between the two arrangements taken in software** -- the readback scales
  with opening time, so it penalises the slower arrangement and the gap reads wider
  than it is.

## What this actually buys, which is narrower than it looks

**It is not precision, and it is not overlap. It is being able to change your mind
afterwards.**

The linked picture can already place a tile to the voxel. Overlap does not break
it: neighbours both cover a piece and the map gives that piece to one of them.
Sub-piece drift does not break it either — the tile is written with its low edge
padded by however far the stage overshot, so its grid of pieces lands on the run's
grid. That is `test_a_drifted_run_is_placed_truthfully.py`, and it is the real-stage
case: a microscope asked to step 1792 voxels stepping 1792 give or take seven. The
padding is never served and it costs nothing at draw time.

So an overlapping, drifted run of ten thousand positions still opens in well under a
second through the picture. The difference between the two arrangements is only
this:

```
picture + padding   any offset, flat cost, baked at write time
                    revising an offset means rewriting that tile's pixels

placed sources      any offset, ~5.1 ms a position at open, revisable by
                    editing a few bytes of JSON, no voxel touched
```

And the cost difference is a complexity class, not a constant:

```
tiles          picture      placed sources (with the bind batched)
      400       0.21 s          2.4 s
    2,500       0.29 s        ~13 s
   10,000       0.53 s        ~51 s      (sources extrapolated; the picture measured)
```

**The picture is not flat, which an earlier version of this document said three
times.** It grows -- 2.5x for 25x the tiles -- and the growth is entirely the map,
which goes from 0.09 MB to 2.19 as the tiles climb. That is sublinear and it is not
nothing. The 0.22 s repeated for every size was inherited from an older ladder and
had never been measured at ten thousand; when it was, it read 0.53.

What survives is the comparison, and it survives by two orders: the picture's cost
grows with the *description* of the run, the placed arrangement's with the number of
things in it. No tuning closes that.

**Therefore: placed sources are for tens of positions, a couple of hundred at the
outside — the ones under active examination. Surveys keep the picture, which is not
a fallback but the only thing here that works at the scale a run reaches.** Whether
paying five milliseconds a position is worth it depends entirely on how often
placements get revised: for a run stitched once and looked at afterwards the
padding is simply the right answer, and for targets re-registered as analysis
improves it is not.

### A measurement correction that belongs beside those numbers

Earlier rows in this document reported the sources arrangement opening four hundred
positions in 3.64 s. That was measured against `zmartSourcesWaiting() === 0`, which
returns with **300 of 400** sources still unresolved — a page three-quarters loaded.
Waiting for every source gives **8.96 s** on the stock engine and **2.36 s** with the
bind batched. The picture is unaffected either way, being a single source, and reads
0.22 s throughout.

## Ten thousand overlapping tiles open in half a second

Every claim in this document that the picture opens ten thousand positions in under
a second rested on a ladder whose tiles **abutted**. Overlap is what a real
acquisition produces and it had never been measured at that size, so the claim was
inherited rather than tested. Measured now, with the seams chunk-aligned and
ownership computed per tile:

```
| tiles  | map     | parse | opening |
|    400 | 0.09 MB |  1 ms |  0.21 s |
|  2,500 | 0.55 MB |  5 ms |  0.29 s |
| 10,000 | 2.19 MB | 14 ms |  0.53 s |

400 -> 10,000 is x2.5 for x25 the tiles
```

**Zero pieces with nothing behind them and zero owned twice, at ten thousand
hand-computed ownerships** -- checked against the geometry before the browser was
opened, because unsupplied ground draws as black rather than raising anything.

The growth is entirely the one term that was predicted to grow. Opening rose 0.32 s
while the map went from 0.09 to 2.19 MB; the parse is 14 ms of that and the rest is
fetching one larger document and indexing it. Nothing scans: `_tile_covering` indexes
by row, bisects across it, and stops walking back after one tile width, so overlap
makes it visit perhaps two tiles where it visited one.

This ran in the constrained regime rather than an easy one. Tiles of 64 with 32-voxel
pieces stepped 32 give `gcd(32, 64) / 32 = 1`, so exactly one pointable level -- the
same restriction a 2304 tile with 288 pieces imposes at 12.5% overlap.

**So overlapping runs at survey scale are not the problem.** What stands between this
and an acquisition is the writer computing ownership, which is the ten lines above
done automatically rather than by hand.

## What is already true, and needs no work

- OME-Zarr `scale` and `translation` are read per store; `identity` too. The parser
  table is at `datasource/zarr/ome.js:155` and anything else throws at `:169`, so
  **no rotation or shear** from metadata.
- **A position records its stage position in the multiscale-level
  `coordinateTransformations`, and a correction written into the dataset transforms
  composes with it.** An earlier version of this document said the *engine* places
  sources a tile-width apart by index and that a translation adds on top of that.
  That was wrong: the placement was in the data all along, which is why offsets
  looked additive. Deleting or replacing that block strips every tile of where it
  belongs — see `PLAN_many_sources_with_transforms.md`.
- Translation is any finite float — fractional and negative both fine. Scale must
  be finite and **positive**, so no flips.
- One layer already holds many sources: `dataSources` is an array
  (`layer/index.d.ts:112`), and `scene.js:260` already sends the list.
- A group is *not* walked. The driver reads `multiscales` on the group's own
  attributes and resolves one volume per source URL
  (`datasource/zarr/frontend.js:491`). Ten stores means ten sources.

## Phase 0 — the measurement that decides the rest (gate)

**Nothing below is worth building until this number exists.** The linked picture
exists because neuroglancer builds a drawing layer per image. At ten sources the
cost was small; the ladder was built because *thousands* of positions were the
problem.

Run both arrangements over the same pixels at rungs 10, 50, 100, 200, 400:

- one picture, pointers — `held = 1`
- one layer, N sources with transforms — `held = N`

A script doing this at one rung was written while measuring and is **not in the
repository** — it lives in the session's scratchpad and should be brought in as
`viz_studio/measure_two_arrangements.py`. It needs the rung loop and, importantly,
**`lit` matched between the two**: today's run had 0.51 against 0.83, so part of
7.9 → 13.7 ms was simply more specimen on screen, not the arrangement. Zoom each
to the same lit fraction before timing.

**Decision rule, written before the numbers arrive:** if the drawing frame at 400
sources stays within ~20% of the picture's, adopt sources as the placement
mechanism and keep the picture only for runs above that. If it bends, keep the
picture as the default and treat transforms as an overlay for small runs — and
Phase 4 becomes the real answer.

### Result, measured 7 August 2026

Same pixels, same places, both arrangements, one browser. Positions served straight
out of the picture's own folder — nothing copied, nothing edited.

Drawing in software (headless), where `lit` did agree between the two and the rows
are therefore comparable:

```
positions   picture          sources         held
        5    8.7 ms          10.4 ms         1 / 5
       10    8.6 ms          12.7 ms         1 / 10
       50    8.9 ms          25.5 ms         1 / 50
      100    9.1 ms          41.4 ms         1 / 100
      200    9.4 ms          69.4 ms         1 / 200
      400   10.0 ms         121.1 ms         1 / 400
```

**The picture is flat and the sources are linear**: about `8.5 ms + 0.28 ms × N`,
fitted at 0.278 from 10→400 and 0.266 from 100→400. The gate says no: **placement
by transform cannot be the default mechanism.**

The decision is made on the *shape* — flat against linear — and not on the "within
twenty per cent" rule this document set out with. That rule is retired: it is a
threshold in milliseconds, and these milliseconds are software-drawn ones the same
document says overstate the cost about fiftyfold. A threshold cannot be applied to
numbers already declared untransportable. The shape argument needs no threshold and
is sufficient on its own.

Two cautions on the table above, both found by review after it was published.
`lit` agreed between the arrangements at every rung except 10, and that is why they
are quoted as comparable — but `lit` covers only the **centre half** of the canvas
and is blind to which pyramid level drew, so it is a weaker warrant than it looks.
And **the camera was not pinned**: the view is centred once from whichever source
resolves first, so two rows of a rung need not have been looking at quite the same
thing. The curve is very unlikely to change shape, but these rows should be
re-measured with `position` and `zoomFactor` set explicitly.

Two costs that hold whatever is drawn, and match on both machines:

```
opening     400 positions   0.25 s  ->  3.50 s      14x
requests    400 positions   67      ->  1744        4.3 per position
```

**The same ladder on the card (NVIDIA T400) does not settle the drawing frame, and
must not be quoted.** It reported 0.7 ms against 2.4 ms at four hundred — but `lit`
disagreed between the arrangements at nearly every rung and read **0.201** for 400
sources, so that row timed a mostly black panel. With 1744 requests and 3.5 s to
open, the fixed 2.5 s settle in `how_it_drew` is not enough for the stores to
arrive before sampling starts. What it does show is that software drawing overstated
the absolute cost by roughly fifty times: the *shape* transfers, the milliseconds
do not.

**Before this is re-run:** `how_it_drew` needs to settle until `lit` stops climbing
rather than waiting a fixed interval. Until then no threshold in positions can be
quoted for real hardware.

### The limit is the opening, not the frame rate

Measured again with cold openings and a per-position cost, `lit` matched at
0.83–0.85 for the sources at every rung:

```
positions   fps            cold opening      one more        requests
            pic / src      pic / src         pic / src       pic / src
        5   90 /  88       0.21 / 0.21 s     --              65 /   58
       50   89 /  58       0.20 / 0.29 s     <10 / 311 us     60 /  238
      100   87 /  38       0.22 / 0.36 s     <10 / 317 us     62 /  438
      200   89 /  26       0.24 / 0.81 s     <10 / 310 us     70 /  848
      400   90 /  15       0.22 / 3.64 s     <10 / 283 us     67 / 1638
```

`one more` for the sources holds at 283–317 µs across an eightfold range, which is
what a real linear law looks like. For the picture it is *bounded rather than
measured* — the rise across the rungs is the same size as the column's own spread,
so all that can be said is "under about ten microseconds a position".

**Which column decides it changes on real hardware, and the earlier conclusion
named the wrong one.** At four hundred sources, against the same ladder on the
card:

```
                  software      card        recovers?
drawing frame     121.7 ms      2.4 ms      ~50x
fps                    15         115       yes
cold opening         3.64 s      3.50 s     no
requests               1638       1744      no
```

Drawing is GPU work and almost all of it comes back. Opening and fetching are
per-source setup and I/O and do not move at all. So the frame-rate ceiling is an
artefact of software drawing, and **the durable limit is the cold opening** — the
worst-behaved column of the four, growing roughly quadratically, with the
per-position cost of opening itself rising: 3.6 ms at a hundred, 4.1 at two
hundred, 9.1 at four hundred. Four hundred positions take three and a half seconds
to open on hardware that then draws them at 115 frames a second.

Sub-second opening holds to somewhere around one to two hundred sources. That is
the number to design against.

### What follows from it

- Transforms are an **overlay for a bounded number of positions** — a detail scan
  of a dozen gets free, revisable, fractional-voxel placement at a cost nobody can
  feel. Surveys keep the linked picture, which is flat to four hundred positions
  and was built for exactly this.
- **The bound has to be a number, and exceeding it has to be visible.** "Only the
  positions being examined" is not a limit: an operator picking three hundred
  targets is back in the bad regime with nothing on screen saying so. That is the
  fault the scale bar is held to account for — a picture that is quietly wrong is
  worse than one that is obviously broken. Whatever the measurements settle on,
  the overlay needs a documented ceiling and a stated behaviour when it is passed,
  shipped together and not afterwards.
- **Phase 4 is promoted** from optional to the only route that gets free placement
  *and* a flat curve.

## Phase 1 — placement written once, in the right slot

`parseOmeMultiscale` reads a `coordinateTransformations` at the **multiscale
level** and matrix-multiplies it with each dataset's. Tile placement belongs
there — one transform per image. Today's script wrote it into every resolution
level, which works and is the wrong slot.

- A writer in `zmart_storage` that records a placement on a store:
  `place(store, offset_um)`, writing the multiscale-level translation.
- It takes the offset a stitcher measured. It never touches pixels, and calling
  it twice replaces rather than accumulates.
- **The offset is a correction on top of nominal placement, not an absolute
  position** — measured today: a source lands a tile-width apart *plus* its own
  translation. Document that, because it is not what the name suggests.

Tests first, in the suite's style, driving the real page:

1. an offset written to a store reaches the engine and moves the picture;
2. a fractional offset survives — 51.2 voxels lands at 51.2, not 51;
3. offsets are independent — moving one position leaves the others where they were;
4. rewriting an offset replaces it, and no pixel changes (checksum the arrays).

## Phase 2 — the scale bar must notice sources that disagree

A per-tile **translation** is harmless. A per-tile **scale** is a claim about the
specimen: it says these voxels are a different size. Two sources at different
scales mean no single bar can describe the view — the fault fixed today, arriving
by a new route.

The guard added today (`LayerPanel.jsx`, `axesOnScreen` / `stretchedUnevenly`)
compares the *display stretch* only. It has no idea whether the sources disagree
with each other.

- Extend it to compare the scales the sources on screen declare.
- Same rule as today: warn when the axes on screen disagree, and stay quiet when
  they agree — an even difference is not a shear.
- Failing test first: two sources, different voxel size, warning appears; same
  voxel size, silent.

This phase is not optional if Phase 1 ships, and it should land in the same change.

## Phase 3 — affine, only if rotation is actually needed

OME-Zarr metadata cannot rotate. Neuroglancer's per-source
`LayerDataSource.transform` is a full matrix and can.

- `scene.js:260` would send `{url, transform}` instead of a bare URL string.
- Only worth doing if a real stitcher output carries rotation. Axis-aligned
  offsets cover drift, which is the case in hand.

Deferred until something asks for it.

## Phase 4 — ANSWERED BY MEASUREMENT: declaring once does not fix it

**The gate below was run and it refuses this phase.** A performance trace at N=100,
200 and 400 names the superlinear function, and it is not fetching.

`CoordinateSpaceCombiner.bind`, per position:

```
N     bind/position   fetch/position   requests/position
100      2.65 ms         0.382 ms          4.46
200      4.48 ms         0.394 ms          4.23
400      9.36 ms         0.367 ms          4.12
```

`bind` per position doubles as N doubles — O(N) of work per source, O(N²) overall.
Fetching per position is flat across all three sizes. At four hundred sources the
registration chain is **76% of all main-thread work**; the same run served as one
picture spends 3.6% and is indistinguishable from five sources.

The chain, read off the built bundle at the addresses the trace named: each
resolving source calls `addCoordinateSpace` three times — root, local and channel
combiners. Each `bind` ends in `update()`, which loops over every binding already
present; if the combined space changed it dispatches a signal whose handler list is
one per already-bound source; each handler rebuilds a chunk transform and re-posts
it to the chunk worker.

**So the cost is per-source registration inside the layer, not round trips.** One
document yielding N sources still binds N times and is still O(N²). Declaring once
would have removed 4 requests per position — a flat, already-cheap term — and left
the curve untouched.

Corrected numbers while here: the harness's settle condition
(`zmartSourcesWaiting() === 0`) returns with **30 of 100** sources resolved and
**300 of 400**, so the cold openings recorded earlier in this document were taken on
pages that had not finished loading. Waiting for every source to resolve gives
**1.0 s at 100, 2.6 s at 200, 10 s at 400**.

### The fix, prototyped and measured

Batching the binding works, and it was proved by intervention rather than argued.
`CoordinateSpaceCombiner.bind` ends with an eager `this.update()`
(`coordinate_transform.js:1318`). Replacing that with a batched update, measured on
identical stores with the camera pinned and a settle condition that waits for every
source to resolve:

```
                       100 pos   400 pos   growth
eager (stock)           0.87 s    8.96 s   x10.3
microtask coalesce      0.73 s    7.99 s   x11.0
50 ms batch             0.56 s    2.21 s   x3.9   <- linear
```

Four hundred positions open in 2.2 seconds instead of 9.0, and it is faster at a
hundred too. **The superlinear term is gone**: x3.9 for x4 positions is linear
within noise.

**The microtask attempt is worth recording because it failed and the reason is the
whole point.** Coalescing to a microtask changed nothing, because sources resolve
as separate network responses spread across the entire opening — no two binds land
in the same tick, so there is never anything to merge. The window has to be wide
enough to catch neighbours arriving from the network. Fifty milliseconds was the
first value tried and it was not tuned.

**What it trades, and why the prototype was reverted rather than kept.** `combined`
is no longer current the instant `bind()` returns, so anything reading it
synchronously afterwards sees the previous value. Nothing in this measurement
exercised that, and it is exactly the kind of correctness question that needs the
engine's own tests rather than an opening-time number. The patch lived in
`node_modules` and has been restored.

### Cutting requests buys almost nothing, measured

The obvious follow-ups were all about the four metadata files a position carries:
declare them in one document, write positions single-level, serve over HTTP/2 so
the six-connection cap stops mattering. **All three attack a term that is not
there.**

Opening the same four hundred sources twice against one server, so the second read
is a cache hit and metadata is effectively free:

```
engine                cold     warm    warm per source
stock (eager)         8.20 s   7.62 s     19.0 ms
microtask coalesce    8.58 s   7.97 s     19.9 ms
50 ms batch           2.53 s   2.05 s      5.1 ms
```

Free metadata saves about **0.5 s out of 8.2** — six per cent — and the warm batched
number is the same 2.05 s as the cold one. With the bind batched, fetching is not
the cost at all; the residue is per-source engine work: a render layer, a chunk
transform, an RPC to the chunk worker.

**And it corrects the story told above for why the microtask coalesce failed.** It
was not that sources arrive spread across the network: they still fail to batch when
every read is a cache hit, because each response resolves in its own task and
microtasks drain between them. No two binds share a tick however fast the data
comes. The fifty-millisecond window works because it spans *tasks*, not because it
outwaits the network.

So the list of remaining levers is shorter than it looked. Batching the bind is
worth 3.4x and is found. Bounding the number of sources is the only other one that
touches the real term.

**But "everything about requests is noise" -- which this section originally
concluded -- is wrong, and the warm-cache experiment could not have shown it.** It
held the request *count* fixed and made each one faster. That disproves bytes and
latency as the cost; it says nothing about the count, which drags a fixed amount of
scheduling behind it whether the answer comes from a socket or a cache.

A trace of the batched engine says where the residue really is:

```
bare RunTask               1318 ms across 18075 tasks   53% of main busy
microtask checkpoints       602 ms across 11865         24%
FunctionCall                318 ms across 504           13%
```

Per source that is 45 tasks, 30 microtask checkpoints and 4.2 requests at N=400 --
and 51, 33 and 4.7 at N=100, so it is flat per source. **About eleven scheduler turns
per request, four requests a source.** Cutting the four to one would cut the task
count with it, and the win would be in the scheduling rather than the bytes.

So declaring the positions once was back on the table, for a different reason than it
was first proposed and one that the earlier experiments could not see.

**RETRACTED — the fifth below was measured against a contaminated denominator and
is not a safe number.** Both experiments that bounded declaring-once ran in
software, where roughly two thirds of main-thread busy turned out to be the
rasteriser reading the canvas back (see below). The same half-second saving is six
per cent of a software 8.2 s and ten per cent of a hardware 4.95 s, and the two are
not the same claim.

Worse, the arithmetic points the other way. Net of the readback the engine's own
main-thread work is about 1.73 ms a source, so four hundred sources is **0.69 s of
engine work inside a 4.95 s opening on the card**. Some 4.25 s of a real opening is
not main-thread engine work at all -- about 10.7 ms a source, which at 4.2 requests
each is roughly **2.5 ms a request**, squarely a round trip plus queueing. If that is
what the opening is mostly made of, cutting 1,680 requests to 400 is a different
proposition from a fifth.

That is reasoning from a number, which has been wrong all day, so it is not a claim.
**The measurement that settles it is a warm-cache run on the card** -- the same
twenty-minute experiment, on the machine where the answer counts. Until then this
section records a bound that was measured, not a conclusion that holds.

The software measurement, for the record:

```
positions   files a store   requests a source   opening
      100        4                4.9            0.58 s
      100        2                2.5            0.44 s   -23%
      400        4                4.2            2.08 s
      400        2                2.3            1.84 s   -12%
```

That is roughly **0.3 ms saved per request removed** at four hundred sources. Going
the whole way to one request a source would take out about 1280 more of them, worth
some 0.4 s — an opening of about 1.7 s against 2.08, call it a fifth.

So the scheduling story is directionally right and quantitatively modest: the eleven
scheduler turns a request are real, and they are cheap. Requests account for roughly
1.3 ms of the 5.2 ms a source, and cutting them to one leaves about 4 ms. **Declaring
once is a fifth off, for a document format and a driver change.** It does not alter
the complexity class, and it does not move the scoping conclusion below.

(The stripped-levels build is a proxy and not a suggestion: with no coarse level the
engine fetches full resolution across a wide area when the operator zooms out, which
costs far more than the requests it saved. It is legitimate here only because the
opening is timed to every source resolving its *description*, which happens before
the chunks matter.)

### After the fix, there is no second thing to fix

A trace of the batched engine, on the same overlapped stores, confirms the fix
rather than merely the timings: `CoordinateSpaceCombiner.bind` goes from 3455 ms to
**3.4 ms**, and `addCoordinateSpace` below the noise floor. The fan-out is gone, not
displaced -- `update` is 103 ms, too small to be feeding the 282 ms of `Signal.dispatch`
that remains, which belongs to other signals. Main-thread busy falls 4.99 -> 1.85 s
and **GPU-thread busy 4.03 -> 1.19 s**, which was not expected: fewer transform
re-posts mean less redrawing too.

The residue is spread thin by construction. Stock needed six functions to reach half
of the attributed JS self-time; batched needs fifteen, the top five are 34%, and the
largest single entry is native `fetch` at 8.3% of main-thread busy. Attributed JS
self-time falls 4751 -> 961 ms across some 390 functions.

Two further quadratics do exist and are worth knowing about before they matter: a
generator that walks every `dataSource` and its subsources, called once per source,
and an explicit pairwise loop comparing each source's flattened state against every
earlier one. Together they are **about 50 ms, 1.6% of the open at four hundred
sources** -- the next quadratics, not present ones.

**So there is no second concentrated term to attack.** What is left is scheduling,
and the only lever on scheduling is issuing fewer requests per source.

### The unattributed time was the software rasteriser, not the engine

The profile above left about 890 ms of main-thread busy attributable to no JS
function, and both explanations offered for it were wrong. A second trace, with
categories chosen from the 301 the browser actually reports rather than guessed,
names it:

**`GpuChannel::WaitForGetOffsetInRange` — 1215 ms in 76 events, 64% of main-thread
busy at four hundred sources.** The cause is 25 `GLES2::ReadPixels` calls under
`LayerTreeHost::DoUpdateLayers <- ProxyMain::BeginMainFrame`: **Chromium's own
compositor reading the WebGL canvas back to the processor**, because SwiftShader has
no GPU to share a texture with. The GPU process corroborates it at 1215.5 ms through
`ImageHelper::readPixelsImpl - CPU Readback`.

Every candidate is refuted with a number:

```
V8 compile / parse         67 ms, and 1.2x for 4x N -- a constant, the bundle
garbage collection         40 ms
Blink style/layout/paint   47 ms
mojo / IPC dispatch        12 ms, flat
bare task, nothing named   12.8 ms  (0.5%)
```

The last line also refutes "the residue is scheduling spread over eighteen thousand
tasks", which is what the previous section concluded.

**Net of the readback the engine looks better than any number quoted above:**

```
non-GPU main-thread work   305 ms at N=100  ->  692 ms at N=400   2.27x for 4x N
per source                 3.05 ms          ->  1.73 ms           falls as N grows
```

Sublinear, and about **1.7 ms a source** rather than the 5.1 ms quoted elsewhere in
this document -- that figure was measured in software and carries the rasteriser's
readback inside it. So there is no second concentrated engine term, and the
conclusion is stronger than when it rested on "nothing shows above 5%".

**What this means for every software number here.** They are contaminated, in a way
that flatters the picture and penalises the sources: a longer opening means more
compositor frames means more readback. The shapes survive -- the picture is still
flat and the sources still linear -- but the *per-source constants measured in
software are too high*, and the headed figures are the ones to trust.

Still open: 333 ms of the batched opening remains genuinely unnamed, no trace was
taken on the real card, and there is a tension nobody has resolved -- 1.2 s of a
2.82 s open should be worth ~43% if it were all critical path, and the card
measured ~25%, so about half that block is slack the opening would have spent
waiting anyway.

### Where this leaves the arrangement

The ceiling was never inherent to placing tiles by transform. It is one eager call
in the engine, and with it batched the arrangement is linear in the number of
positions with a small constant. That changes the recommendation from "an overlay
for a bounded number of positions" to "worth pursuing upstream", and it makes the
bound a temporary consequence of an unfixed engine rather than a property of the
design.

### What would otherwise have been tried

Batch the binding. The quadratic exists because sources are bound one at a time and
each bind re-walks every binding already present and re-notifies every handler. Add
all N sources, then combine once. That is an upstream neuroglancer change, but it is
a far sharper request than "a driver that walks a group": it does not need discovery,
a file format, or consolidated metadata, and it would leave the arrangement's
placement freedom exactly as it is.

Failing that, the honest answer is a **bounded number of sources**, and the bound is
now measurable rather than guessed.

### The original argument, kept for the record

### Why this and not "a driver that walks a group"

An earlier version of this phase asked for a driver that, handed a group,
enumerates its children. That is the same cost by a longer road: enumerating still
means reading each child's description, and **the description is the whole cost**.

Measured: a position carries **four metadata files** — one for the group and one
per pyramid level — and the run asked **4.1 requests per position**, 1638 of them
at four hundred. The requests *are* the metadata; the pixels barely register. The
bundled driver has no consolidated-metadata support either (nothing matches
`consolidated` or `zmetadata` under `datasource/zarr/` or `kvstore/`), so every one
of those four is its own round trip.

So the thing to ask for is not discovery. It is **one document, read once, that
already says where all N tiles are** — which is what `zmart-links.json` is today,
minus a transform field.

A cheaper constant-factor cut is available first, and it has a failure mode worth
stating rather than a condition worth stating. Four files is one group and three
levels; a position written with a single level costs two, halving the requests.
That is right *while the sources are looked at close in*. **Zoom out on them and
there is no coarse level to draw from, so the engine fetches full-resolution chunks
across a wide area — which can cost far more than the requests it saved.**
Operators zoom. Either keep a coarse level, or make the overlay refuse to zoom out
past what it can serve.

### What it would and would not fix

```
                       declare N times      declare once
requests               4.1 per position     flat, one document
cold opening           ~quadratic           flat, if the quadratic is the fetching
drawing frame          0.28 ms per source   unchanged: still a render layer each
```

It does **not** fix the per-source frame cost. That is deliberate: at four hundred
sources the drawing frame falls from 121.7 ms in software to 2.4 ms on the card,
so that column is not what limits anything on real hardware. The columns this fixes
— opening and requests — are the ones that do not recover on a GPU and that set the
ceiling.

### The gate, and it is not optional

Requests are linear at 4.1 a position while the opening grows faster, so the
fetching does not explain the curve on its own. If the superlinear part is
per-source registration — each arriving source causing work across all the sources
already present — then declaring once removes N round trips and leaves the curve
untouched, because the reader still creates N sources internally. **That would make
this phase worth much less than it looks, and the honest answer a bounded number of
sources instead.** So the shape has to be established and located before the
document is designed.

In this order, because each step makes the next one mean something.

**A. Pin the camera and count honestly. A prerequisite, not a follow-up.**
Neuroglancer centres the view once from whichever source resolves first and never
recentres, and the zoom is reset the same way — so with per-store placements, where
the view lands varies run to run and the opening varies with it for reasons that
have nothing to do with N. Every measurement below would inherit that. Set
`position` and `zoomFactor` explicitly after opening, and replace `held` with
separate counts of loaded, failed and pending. It is cheap and everything else
rests on it.

**B. Profile. It needs no hypothesis, which is why it goes early.**
A performance trace at N=100 diffed against N=400 says which function's time grew
sixteenfold when N grew fourfold. It names the thing instead of inferring it. Five
mechanisms have now been argued from reading this engine and all five were wrong;
the step that requires no reasoning belongs at the front. It also gives the
fetch-versus-everything-else split directly, which is what C was really after.

**C. Establish that the shape is a shape.**
Net of the ~0.20 s baseline the measured excesses are 0.01, 0.03, 0.09, 0.16, 0.61
and 3.44 s — **one sample each**, and at a hundred positions the excess is smaller
than the baseline being subtracted from it. The curve is carried by two points.
Before anything is designed around the word quadratic: three repeats, medians, and
rungs above two hundred so the shape is not two points and a hope.

Note that a warm-cache run is **not** a clean isolation of fetching. A driver doing
1638 kvstore lookups that hit an HTTP cache has made fetching cheaper, not free: a
curve that softens proves nothing and one that does not could still be I/O. Serve
from a single in-memory store, or take the split from B.

### What would have to change

- **The document**: a per-tile transform beside the pointer, in the file that
  already lists the tiles.
- **The reader**: `datasource/zarr/frontend.js:491` resolves a group by reading
  `multiscales` on the group's *own* attributes and never enumerates children, so
  one source URL yields exactly one volume. It would need to yield N, each carrying
  its own transform, from a single fetch.

Everything else is already there: transforms are parsed per source
(`datasource/zarr/ome.js`), `dataSources` is an array (`layer/index.d.ts:112`), and
`scene.js:260` already sends a list.

## What not to do

- **Do not rewrite pixels to place a tile.** The padding trick works and is what
  the pointer map requires, but it makes placement permanent and un-revisable.
  It is the fallback, not the design.
- **Do not remove the linked picture.** It is measured, it works, and above some
  number of positions it is likely still the right answer. Phase 0 decides where
  that line is.
- **Do not report a frame time without `lit` beside it.** Today's comparison shows
  why: the two arrangements drew different amounts of specimen and the raw ratio
  flattered nothing.

## Order

Phase 0 → decision → Phase 1 + 2 together → Phase 3/4 only on evidence.

Review before implementing: hand this to Codex first.
