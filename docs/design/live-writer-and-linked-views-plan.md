# Building the live writer and the two linked overviews

**Status:** implementation plan, drafted for review. Nothing here is built yet.

This is the plan for turning
[`live-position-timepoint-publication-decisions.md`](live-position-timepoint-publication-decisions.md)
into working code that can be tested against a real Neuroglancer.

It is deliberately not a restatement of that document. The decisions are
settled; what follows is the order of work, the shape of each piece, and — most
importantly — the places where measurement in this repository says the obvious
plan is the wrong one.

## What we are building, in one paragraph

A **writer** that is told what kind of acquisition is coming — frame size, how
much overlap is wanted, whether the tiles form a mosaic — and works out for
itself how to store it: chunk size, shard size, how many zoomed-out levels, and
how deep those levels can be pointed at rather than copied. It writes each
position as an ordinary OME-Zarr image. On top of those positions it maintains
**two overviews**, a **seamless** one and a **non-seamless** one, each of which
is a single image that points at the positions and copies almost nothing. A
position or a timepoint becomes visible in both overviews at the same instant,
through one atomic commit, and never before it is complete. A viewer that is
already open notices and redraws without reopening anything.

## The one finding that reorganises this plan

The obvious lever for making the viewer faster is the server, and it is the
wrong one.

This repository has already measured that during a thousand-position cold open
the server *"was never answering more than seven requests at once … and was idle
for two thirds of the wait"* (`NEXT_STEPS.md:72-78`). The ceiling is in the
browser, not in Python. That is why HTTP/2 is recorded as rejected —
`ARCHITECTURE.md:103`: *"It treats a symptom of the engine's fan-out and costs a
dependency."* The often-quoted improvement from 440 ms to 26 ms is arithmetic,
never a measurement, and the plan review says so plainly
(`ome-zarr-plan-third-opinion.md:223`). The recorded instruction is *"Take the
bigger chunk first, since it is free, then measure."*

So: **we make the viewer faster by asking fewer questions, not by answering them
faster.** And there is one change that halves the number of questions for free.

### One-sided ownership doubles the chunk size

To hand a tile's stored bytes straight to the viewer without copying them, the
seam between two tiles has to fall on a chunk boundary. Today's writer cuts each
overlap down the middle, so the *half*-overlap must be a whole number of chunks:

```text
(overlap / 2) % chunk == 0        midpoint seam, today's rule
overlap % chunk == 0              one-sided seam, the decision record's rule
```

For a 2304-pixel frame with a 256-pixel overlap, the midpoint rule forces a
128-pixel chunk. The one-sided rule allows 256. From this repository's own
table of what that costs to draw (`zmart-ome-zarr-recipe.md:836-841`):

| chunk | requests to fill a screen | round trips at six in flight |
| ---: | ---: | ---: |
| 128 | 527 | ~440 ms |
| 256 | 144 | ~120 ms |

That is a **3.7× reduction in requests**, from a change of ownership rule alone —
no new dependency, no TLS, no certificate on a microscope computer, and it moves
the *real* bottleneck, which is the number of things the browser is asked to
fetch. It is the same order of improvement HTTP/2 was supposed to deliver, and
unlike HTTP/2 it also reduces work for the server, the disk and the decoder.

This is the central bet of the plan, and it is falsifiable: if the measurement
harness in Phase 5 does not show it, the plan is wrong and we should say so.

### And the code is already shaped to receive it

This is not a hopeful argument. `zmart_storage/linked.py` already describes a
pointed-at tile as three things — where it lands in the picture, where it is
taken from inside its own store, and how big the kept part is — and it already
refuses any tile where those three are not whole numbers of chunks
(`linked.py:745-822`). Cropping a tile to the region it owns is therefore not a
new mechanism at all. It is the mechanism that exists, given non-zero arguments.

What has never been passed to it is the crop: `positions.Run.write` always emits
`taken_from=(0,0,0)` with no size (`positions.py:327`), so every tile is pointed
at whole. Overlapping runs are sent to `cropped.py` instead, which **copies the
whole run a second time** — the overlap ends up on disk twice, about 25% more
than the tiles alone.

So a seamless overview that copies nothing is a smaller change than it sounds:
pass the owned region through as `taken_from`/`size`. And the whole-chunk rule
that `linked.py` already enforces is precisely the rule that one-sided ownership
relaxes by a factor of two.

## What already exists, and what genuinely does not

Worth being exact, because several pieces look missing and are not.

**Already built and tested.** Positions written as separate OME-Zarr images; a
view that points at them instead of copying (`zmart_storage/linked.py`, served by
`viz_studio/backend/linking.py`); the half-and-half crop rule with its refusals
(`zmart_storage/cropped.py`); byte-range and HEAD serving so a browser can read a
shard index and then fetch one chunk out of it (`server.py:275-308`); a
server-sent-event announcement with a polling safety net
(`backend/announcements.py`); and a browser test harness that judges the picture
by photographing it rather than by asking the engine whether it is happy.

**Genuinely missing.** These are the plan.

1. **Nothing chooses the chunk size.** `positions.start_a_run` takes `piece=128`
   and hopes it suits the camera. The `plan_a_grid` function that the recipe
   proposes (`zmart-ome-zarr-recipe.md:1213`) has never been written.
2. **One-sided ownership does not exist.** Only the half-and-half rule is
   implemented.
3. **Sharding is written at level 0 only.** Bundling every level is what takes a
   2 TB run from 20.5 million files to about 1.19 million.
4. **A single chunk cannot be served from inside a shard.** The server hands over
   whole shard files and lets the browser index them. This is the keystone: it is
   what makes bundling every level compatible with chunk-aligned seams, and
   without it the two decisions cancel each other out.
5. **There is no seamless overview that points.** The pointing writer
   (`positions.py`) cannot express overlap at all; the only trimmed view is
   `cropped.py`, which copies the run a second time.
6. **No timepoint can be appended.** Room for moments is declared when the run
   starts and `_check_the_moment_fits` refuses anything beyond it
   (`canvas.py:1614-1635`); nothing in `zmart_storage` ever resizes an array.
   Writing *into* already-declared room works, and — this is the point —
   **changes nothing any reader is watching**, because the pointer list is only
   appended to once per place (`positions.py:326-328`). This is exactly the
   failure the commit record exists to fix.
7. **Nothing in production writes shards.** `start_a_run` has no `shard`
   argument. A live run today is Zarr v3 / OME-Zarr 0.5 with 128-pixel chunks
   and one file per chunk.
8. **Nothing tells an open Neuroglancer that a tile landed.** The method exists —
   `tilesMayHaveLanded` at `options/neuroglancer-under/viewer.js:2072` — and is
   never called from the operator page.
9. **There is no commit record.** Freshness is inferred from a description
   file's modification time and the byte length of the arriving-positions file
   (`linking.py:470-494`). Both are inferences about a write that may still be
   in progress, and neither moves when a moment is written into room that was
   declared earlier.

## The shape of the work

### Phase 1 — Decide the storage layout: `plan_a_grid`

One function, called once at run setup, never by a driver:

```python
plan_a_grid(frame_shape, overlap_intent, ownership="one_sided", ...) -> GridPlan
```

`overlap_intent` stays as this project already decided it: **none, modest, or
generous** — never a literal percentage, because a literal percentage cannot
always be satisfied at the same time as whole-pixel and whole-chunk arithmetic.
The returned plan states the chunk it chose, the overlap in pixels, the fraction
that works out to, the stage step, the shard shape, how many levels the pyramid
will have, and — the part nothing currently computes — **how deep the pointing
can go**:

```text
deepest linkable level = 1 + log2( gcd(step, frame) / chunk )
```

The search order is the decision record's, with one correction from this
repository's own measurements: prefer the **largest** chunk in the useful band
that satisfies the divisibility rules, not the chunk that hits the overlap target
most exactly. A chunk of 102 gives exactly 10% overlap and is, in the recipe's
words, *"the worst of both"* — 836 requests against 144.

The plan is sealed into an `AcquisitionProfile` before the first position is
written, and never changes underneath published data.

**Deliverable:** `zmart_live/profile.py`. Pure arithmetic, no I/O, fast to test
exhaustively across every frame width from 512 to 5000.

### Phase 2 — Ownership, and the two overviews

`zmart_live/ownership.py` computes, for every tile, the three regions the
decision record requires: what the seamless view shows, what a model is given to
look at, and which results count. One-sided and midpoint are both available; the
choice is per acquisition type and is recorded, not inferred.

The two overviews are then both `GrowingLinkedView`s over the *same* canonical
positions, differing only in the three numbers each tile is pointed at with:

| | lands at | taken from | size |
| --- | --- | --- | --- |
| **non-seamless** | the tile's nominal place | `(0, 0, 0)` | the whole frame |
| **seamless** | nominal place + the strip it gives up | the strip it gives up | the region it owns |

That is the whole difference. Neither copies a full-resolution voxel; both are
single images, so Neuroglancer is handed two sources for a run of any size rather
than two per position. The run costs one set of canonical positions plus two
descriptions.

Two honest limitations, stated rather than discovered later.

A single scalar image holds one value per voxel, so the **non-seamless** view
still has to pick a winner where two tiles cover the same place. It shows every
tile's full extent, which is what makes the tile edges and the stage's real
behaviour visible, and that is the point of it. It is not a way of seeing both
measurements at one coordinate at once — the canonical positions keep every
overlap pixel, and anything needing both values reads there.

The **seamless** view needs the strip a tile gives up to be a whole number of
chunks, because it is pointing at stored bytes rather than cutting pixels. With
one-sided ownership that strip is either nothing or the entire overlap, so
`overlap % chunk == 0` suffices. With a midpoint seam it is half the overlap, and
the requirement doubles. Where a tile's geometry cannot satisfy this at all, the
seamless view falls back to a written region for that tile and says so, rather
than silently pointing at the wrong bytes.

**Deliverable:** `zmart_live/ownership.py`, plus the crop passed through
`PlacedTile` and a second view maintained beside the first.

### Phase 2b — Timepoints that can actually be appended

Room for moments is declared when a run starts, and a moment written into that
room is invisible to every mechanism the viewer currently watches. Two things
follow.

Writing a later moment into declared room already works and needs only the commit
record from Phase 3 to become visible. That is the common case and it is cheap.

Growing *beyond* the declared room does not work, and the decision record is
explicit that if a workflow ever needs it, the resize and every new chunk must be
published as one transaction. This plan does **not** build that. It declares
generous room, measures what that costs — this repository has already found a
declared 4 TiB image occupying 59 MiB — and leaves growing to a later piece of
work with its own evidence.

### Phase 3 — The commit record

An append-only run event file, a monotonic revision, and one atomic rename per
published unit. Written only after the position or timepoint, its pyramid levels,
its links, and the affected coarse chunks have all been checked.

This replaces "the pointer file got longer" as the definition of truth, which is
the only way an appended timepoint can be noticed at all: appending a timepoint
does not change that file's length.

**Deliverable:** `zmart_live/manifest.py` and `zmart_live/layout.py`.

### Phase 4 — Serving one chunk from inside a shard

The keystone, and the reason it is the keystone is worth being exact about.

Bundling every pyramid level is what takes a 2 TB run from about 20.5 million
files to about 1.19 million, so it is not optional. But the moment a store is
sharded, the alignment rule gets *harder*, not easier: `linked.py` measures
placement against `chunk_grid.chunk_shape`, and for a sharded Zarr v3 array that
is the **shard**, not the chunk inside it (`linked.py:461-475`, `745-822`). A
whole tile plane per bundle would mean tiles could only sit on multiples of a
whole tile. Bundling every level and chunk-aligned seams therefore cancel each
other out — unless one chunk can be served from inside a shard.

The pointer format is already built to grow into this. Each entry carries a
`held_as` field, fixed at `"file"` today, and the resolver returns an offset and
a length that are always `0` and `None` (`linking.py:323`). The extension is a
version 4 record with `held_as: "range"` carrying the inner chunk shape, and a
resolver that fills those two numbers in. Readers already accept versions 1
through 3, so the tolerance pattern exists.

Two hazards are documented and must be handled rather than discovered. A shard
index is checksummed, so forwarding bytes from a capped shard fails if the inner
chunk count does not match — the same pixels measured 112 220 bytes capped
against 112 412 uncapped. And a seam aligned to an inner chunk may still cross an
outer shard boundary. The recorded instruction is to measure TensorStore's
overlay driver against a gate of 5 ms median before adopting it; warm figures on
Linux were 0.505 ms median at ten thousand positions, but the gate is meant to be
met on a Windows microscope computer.

**Deliverable:** `zmart_live/shardlink.py`, a version 4 pointer record, and the
server route that uses it.

### Phase 5 — Measure the assumptions, rather than assert them

This is what the plan is for. A harness that writes the *same* run under
different assumptions and reports what each costs:

- overlap intent: none, modest, generous;
- ownership: one-sided against midpoint;
- chunk: every legal choice in the band, not just the default;
- sharding: level 0 only, against every level;
- and for each, the number of requests to fill a screen, the time to first
  pixel, the drawing rate, the disk used, and how deep the pointing reached.

The one-sided-doubles-the-chunk claim above lives or dies here.

### Phase 6 — Telling an open viewer, and the tests that prove it

Wire `tilesMayHaveLanded` into the operator page, make the announcement name the
store that changed rather than invalidating the whole scene, and write the
end-to-end tests against a real Neuroglancer.

Naming the store matters more than it sounds. Today an announcement carrying
`wrote_image_in_place` invalidates **every** decoded piece in the scene, at a
measured cost of 22 requests per announcement — the existing plan document's own
verdict is *"the cost kept is greater than the cost removed."* With a commit
record we know exactly which store advanced and to which revision, so the blunt
instrument can be replaced by a precise one. This is the second place where the
commit record pays for itself.

Because ZMART supplies its own controls and Neuroglancer's native interface is
disabled, these tests drive ZMART's own controls and judge the picture by
photographing it. Neuroglancer is a rendering engine here, not a user interface,
which also means the tests must not depend on any of its panels being present.

The existing harness already works this way and its recipe is reused: a writer
that only writes when told to (`--interval 0`, then one POST per tile),
photographs taken repeatedly with the fullest kept — because a picture caught
mid-read can show less than has been written but never more — per-cell
brightness assertions over a fixed bounding box, and a sabotage switch that must
make the test go red before the test is believed.

Software rendering needs `--use-gl=angle --use-angle=swiftshader
--enable-unsafe-swiftshader`, and the drawing buffer must be preserved or the
screenshot comes back empty. Both are already established in the config.

The load-bearing sequence is:

```text
commit tile A          -> A is drawn, B is not
write B, do not commit -> A still drawn, B still not      <- the important one
commit B               -> both drawn
```

## What this plan deliberately does not do

- **It does not add HTTP/2**, for the reasons measured above. If Phase 5 shows
  request count is still the binding constraint after the chunk change, that is
  the moment to reconsider — with numbers.
- **It does not hand Neuroglancer one source per position.** Measured: a thousand
  positions handed over separately drew 24 frames in five seconds where one image
  managed 255. Everything here goes through one linked image per view.
- **It does not invoke or wait for a stitcher.** The seamless view is a
  quick-look at nominal grid places. Stitching stays a separate downstream job.
- **It does not change the writer's placement convention.** Positions are placed
  at the corner, every level carries the same translation, and the reader
  compensates. That was investigated and deliberately left alone.

## Open questions I want the review to attack

1. Is the one-sided-doubles-the-chunk argument actually right, or does the
   pyramid-phase rule claw the benefit back at level 1 and above?
2. Does bundling every level genuinely require the inner-chunk resolver first, or
   is there an ordering that gets some of the benefit sooner?
3. Is the non-seamless overview better served as one image with a declared
   winner, or as something else entirely?
4. What is the cheapest honest way to prove a half-written timepoint is invisible,
   given that the writer, the server and the browser all have to cooperate?
