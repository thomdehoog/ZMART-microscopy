# Building the live writer and the two linked overviews

**Status:** implementation plan, revised after review and after running the
experiments it depends on. Nothing is built yet beyond the shared vocabulary in
`zmart_live/model.py`.

This is the plan for turning
[`live-position-timepoint-publication-decisions.md`](live-position-timepoint-publication-decisions.md)
into working code that can be tested against a real Neuroglancer.

The aim is the simplest arrangement that is genuinely powerful — something a
later piece of work can build on rather than unpick.

## What we are building, in one paragraph

A **writer** that is told what kind of acquisition is coming — frame size, how
much overlap is wanted, whether the tiles form a mosaic — and works out for
itself how to store it: chunk size, overlap in whole pixels, how many zoomed-out
levels, and how deep those levels can be *pointed at* rather than copied. It
writes each position as an ordinary OME-Zarr image. On top of those positions it
maintains **two overviews**, a **seamless** one and a **non-seamless** one, each
of which is a single image that points at the positions. A position or a
timepoint becomes visible in both at the same instant, through one atomic commit,
and never before it is complete. A viewer already open notices and redraws
without reopening anything.

Neuroglancer is a rendering engine here, not a user interface. ZMART supplies the
controls, and nothing in this plan depends on Neuroglancer's own panels.

## The rule everything else obeys

Positions are never handed to Neuroglancer one by one. Measured in this
repository: a thousand positions handed over separately drew **24 frames in five
seconds** where one image managed **255**. The cost is per *source*, not per
byte, and it is paid on every frame for ever after loading. One linked picture
per view, always — which is also how ten thousand positions come to open in
about half a second.

## The central finding, arrived at by experiment

The plan's first draft argued that changing seam ownership from a midpoint split
to a one-sided one relaxes the alignment rule enough to permit a chunk twice as
large. That is true, and running it against the real writer confirms it. But
review and experiment together turned up something better, and simpler.

The writer's rule for a *pointed* zoom level `L` is that **all three** of a
tile's placement numbers — where it lands, where it is taken from, and how much
is kept — must be whole multiples of `chunk × 2^(L−1)`.

The decision record gives the overlap to the upper/left tile, so every interior
tile is taken from an offset of `overlap` pixels into its own store. That offset
is the smallest number in the system, and it is what binds.

Describe exactly the same seams from the other side — **every tile gives up its
lower/right strip, so every tile contributes its first `step` pixels** — and the
offset becomes zero for every tile, uniformly. Measured on a 3×3 mosaic of 2304
pixel frames with 256 pixels of overlap, against the real refusals:

| chunk | upper/left owns | lower/right owns, every tile trimmed alike |
| ---: | ---: | ---: |
| 128 | 2 pointed levels | **5** |
| 256 | 1 pointed level | **4** |

This matters more than the chunk doubling did. A level that cannot be pointed at
has to be **written**, per view, by reading every tile's pixels back through
Python during the acquisition. At one pointed level the seamless view writes
about a third of the run's full-resolution volume — worse than the copying path
it was meant to replace. At four, it writes almost nothing.

And it is the simpler rule. Every tile is treated identically: taken from `(0,
0, 0)`, sized `step`, landing at its grid place. There is no first-tile special
case, no neighbour lookup, and no arrival-order question. Simpler and more
powerful at once, which is the rare case worth taking.

**Consequence for the decision record.** Decision 7 specifies top/left
predecessor wins. The two rules cover the mosaic identically — every output pixel
still has exactly one owner, and the seams merely sit one overlap-width away —
so this is a change of which tile supplies a pixel, not of what the operator
sees. The decision record should be amended to say lower/right, with this
measurement as the reason.

**The cost, stated plainly.** Trimming every tile alike leaves the mosaic's far
edge uncovered — the last column's right strip and the last row's bottom strip.
Those are written rather than pointed at. On a 10×10 mosaic that is a few tens of
megabytes against a run of hundreds of gigabytes.

### Two corrections carried over from review

The formula in the first draft was wrong in both directions. The honest one is

```text
deepest pointed level = 1 + v2( gcd(every lands_at, taken_from and size) / chunk )
```

where `v2` counts halvings, not a logarithm — a ratio of 3 buys no extra level.
And `overlap % chunk == 0` is necessary but **not sufficient**: a 2000-pixel
frame with 256 overlap and a 256 chunk satisfies it and is still refused, because
the frame itself does not divide. `plan_a_grid` must be tested against the real
refusal, not against the stated rule.

The "527 requests against 144, a 3.7× reduction" figure is **arithmetic, not a
measurement** — it reproduces exactly from `(⌊3840/chunk⌋+1) × ⌈2160/chunk⌉`. It
is the same table this plan elsewhere criticises for the HTTP/2 estimate. It is
no longer offered as evidence. What a bigger chunk is worth to a real viewer is
Phase 0's job to find out.

## On the server, and why it is not the lever

During a thousand-position cold open the server *"was never answering more than
seven requests at once … and was idle for two thirds of the wait"*. The time went
on the browser's main thread rebuilding coordinate spaces — a cost per *position*,
which one linked image removes by construction.

HTTP/2 is already recorded as rejected: *"It treats a symptom of the engine's
fan-out and costs a dependency."* The 440 ms → 26 ms figure attached to it is
arithmetic too, and it needs TLS on every microscope computer, which breaks the
run-it-and-it-works property. Nothing here adds it.

## Overlap: a band, with a default

Overlap is chosen from the frame, not fixed in advance, but it has a settled
band and a default:

```text
permitted   10% to 25%
preferred   10% to 20%
aim near    12%
```

At least ten per cent, comfortable up to twenty, twenty-five tolerated where the
arithmetic needs it, and aimed at the low end because overlap is microscope time.
Values like 11.1% or 12.5% are good answers and are not rejected for being
unround — a 2304 frame with 256 pixels of overlap is 11.1% and is exactly the
geometry that gives four pointed levels at a 256 chunk.

## The phases, in the order they should be done

The first draft put the unmeasured performance claim first and the commit record
third. That is backwards: the commit record depends on no claim at all, and it is
what makes the thing testable.

### Phase 0 — Settle the chunk question before building on it

`viz_studio/measure_the_chunk_size.py` already exists and **has never been run**.
Point it at a linked view rather than the copied canvas, use the frame the
argument is about, print the lit fraction as the first column, and register the
threshold in advance: *a bigger chunk must at least halve time-to-first-pixel at
five hundred tiles or more, with the lit fractions agreeing, or the chunk work
does not earn its place.*

Report pointed depth and written-pyramid bytes beside request counts. Treatments
are ownership **direction** and edge handling, not merely one-sided against
midpoint — the first draft's matrix would have compared two schemes that are
equal on written bytes and never found the one that is far better.

One browser and one server at a time; this box has four cores and parallel
measurement here has already been recorded as worthless.

### Phase 0b — Make `linkable` computed, never declared

`LevelGeometry.linkable` is a boolean that is currently trusted. A level wrongly
declared linkable produces a wrong picture with **no error anywhere**. Compute it
from the corrected formula, validate it against the real refusal, and refuse a
profile that claims more than it can deliver.

### Phase 1 — The commit record

An append-only run event file, a monotonic revision, one atomic rename per
published unit, written only after the data, its pyramid levels, its links and
the affected coarse chunks have been checked. `fsync` before the rename, because
this record's whole job is to mean "safely on disk".

Freshness today is inferred from a description file's modification time and the
byte length of an arriving-positions file. Both are guesses about a write that
may still be in progress, and neither moves at all when a moment is written into
room declared earlier.

Integration must be cheap: fold the event file's `(mtime, size)` into the
existing revision fingerprint so a commit moves it, parse only inside the config
rebuild that already runs when the fingerprint moves, and read only the tail
using the same cursor trick the pointer reader uses.

Publish the committed revision **per store**, beside the existing per-store frame
counts. Not in the chunk URL — a revision in the address makes the engine treat
each commit as a new data source and never drop the old one, which at a hundred
positions and a hundred commits is ten thousand sources.

### Phase 2 — Live refresh, and the test that proves it

Replace the scene-wide invalidation (22 requests per announcement, every source
dropped) with a per-store one driven by the per-store revision. Wire the refresh
into the operator page, which today never tells Neuroglancer that a tile landed.

Then the load-bearing test:

```text
commit tile A          -> A drawn, B not
write B, do not commit -> A STILL drawn and still bright, B still not
commit B               -> both drawn
```

The middle step is the point, and as first written it would pass over a black
screen. It must assert the positive arm in the same test — A's lit fraction
unchanged and non-zero — and a sabotage run must be shown to turn it red before
any of it is believed.

### Phase 3 — Timepoints into declared room

Nearly free once Phase 1 exists, and it closes the exact hole the commit record
was written for. Growing *beyond* declared room is not built; generous room is
declared instead, which this repository has measured as almost free.

### Phase 4 — `plan_a_grid` and the sealed profile

Now choosing against a measured objective rather than a guessed one. It settles
chunk, overlap in whole pixels, the resulting fraction, step, level count, and
pointed depth, and it is sealed before the first position is committed.

### Phase 5 — Lower/right uniform ownership and the seamless view

The crop passed through the existing placement fields, so the seamless overview
points instead of copying. Plus the grid contract: duplicate cells,
diagonal-only joins, wrong overlap and disconnected insertions refused.

### Phase 6 — The non-seamless view

Two things must be fixed for it, and neither is optional.

The growing view writes coarse levels without a tile index, which routes into a
check that **refuses a tile landing on already-imaged ground**. The second
overlapping whole frame therefore raises mid-run, on the microscope. A tile index
has to be passed through so a view that has deliberately chosen a winner is
allowed to.

And the two views would merge into one row: the viewer decides what belongs
together by comparing voxel size and channel names, which these two agree about
exactly. The operator would get one contrast control for both. The view's role
has to become part of its identity.

The winner rule for overlapping ground must be declared once and applied
identically to the pointers and to the written coarse levels — today the pointer
resolver picks the right-hand tile while the coarse writer picks whoever wrote
last, so a seam would show one tile zoomed in and another zoomed out.

### Phase 7 — What a commit actually costs

Measured the way an arrival must be measured: grow the run to N first, then time
**one** commit alone, at N = 10, 100, 1000, 5000. Timing a loop instead of an
arrival has already misled this project by a factor of two hundred. Strict
publication puts a coarse-chunk rebuild for two views on that path, and it is
currently unbudgeted.

### Phase 8 — Deferred, deliberately

Sharding every level and serving one chunk from inside a shard. Its benefit is
file count, not viewer speed; it makes the alignment rule harder, not easier
(the unit becomes the shard); and its performance gate is on a Windows microscope
computer nobody has measured. Level-0 sharding, as production already does,
keeps the existing rule true.

The analysis-ownership half of Decision 9 is also deferred. Stating that plainly
so the omission is a decision rather than an oversight.

## Also fix on the way past

`start_a_run` unconditionally discards an existing run, and a growing view starts
its tile list empty and deletes the arriving-positions file when it finishes. A
writer that restarts mid-run therefore loses every tile written before the
restart, permanently, at the moment the run ends. For a design whose premise is a
durable record, that comes first among the small things.

## Open questions the review did not settle

1. What a bigger chunk is actually worth to a real viewer, once one linked image
   has already removed the per-position cost. Phase 0.
2. Whether the far-edge strips are better written or better handled by letting
   the edge tiles keep their whole frame at a shallower pointed depth.
3. What the coarse-level rebuild costs per commit, and what the writer should do
   when it exceeds the interval between positions.
