# Building the live writer and the two linked overviews

**Status:** implementation plan with a tested reference implementation in
`zmart_live/`. The profile, ownership, manifest, coarse-chunk planner, shard-index
resolver and scene compiler exist. They are not yet one production pipeline: the
coordinator that earns readiness, the view stores, the shard resolver's backend
route and the live viewer refresh still have to be connected.

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

### Current implementation boundary

| phase | present in `zmart_live/` | still missing before production |
| --- | --- | --- |
| chunk/profile | chooser, sealed records, divisibility validation | Windows and real-viewer benchmark |
| publication | durable monotonic manifest, recovery, single-writer exclusion | coordinator that validates real artifacts before setting readiness |
| timepoints | event semantics inside already declared array room | growing beyond declared room and microscope integration |
| ownership | visual and analysis ROIs, exhaustive small-grid tests | persisted-layout validator against the sealed profile |
| coarse levels | exact affected-chunk and committed-contributor plans | actual raw/seamless coarse writers and timing budget |
| sharding | checked inner-chunk byte-range resolver | routing those ranges through the linked-view backend |
| scenes | internal scene model and bounded Neuroglancer adapter payload | actual raw selector store, 0.5 metadata adapter and frontend refresh |
| browser | real-Neuroglancer synthetic run and sabotage harness | production-path integration test and portable Chromium provisioning |

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

`LevelGeometry.linkable` remains serialized as a boolean, but the profile now
validates every true value against the grid-step, downsampling and inner-chunk
geometry and requires the linked levels to form one prefix. The remaining step is
to make it wholly derived at the serialization boundary and validate the result
against the backend route that will actually serve it.

### Phase 1 — The commit record

An append-only run event file, a monotonic revision, one atomic rename per
published unit, written only after the data, its pyramid levels, its links and
the affected coarse chunks have been checked. `fsync` before the rename, because
this record's whole job is to mean "safely on disk".

Freshness today is inferred from a description file's modification time and the
byte length of an arriving-positions file. Both are guesses about a write that
may still be in progress, and neither moves at all when a moment is written into
room declared earlier.

Integration must be cheap: use the atomic truth file's metadata fingerprint
(`mtime_ns`, `ctime_ns`, size and inode) so a commit moves it, parse only inside
the config rebuild that already runs when the fingerprint moves, and read only
the history tail using the same cursor trick the pointer reader uses.

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

### Phase 8 — Sharding, and the byte-range resolver that keeps it free

Sharding is not an optimisation to be deferred here. A run of four or five
hundred gigabytes written as loose chunks makes **over five million files**, and
simply moving that between Windows machines is a nightmare. Bundling is what
makes a run of that size handleable at all, so it is a first-class requirement.

The danger is that bundling takes away the freedom to choose a chunk. The view
hands Neuroglancer whole *files*, so once a file holds many chunks the placement
numbers must line up with the **bundle** rather than the chunk — and a bundle is
far larger, so the alignment rule becomes much harsher. At a 2048 step, any
bundle wider than the overlap makes the view unbuildable.

This was checked rather than assumed. Asking the linker what it measures
alignment against, for two arrays holding the same 256-pixel chunks:

| array | alignment unit the linker uses | piece inside the bundle |
| --- | ---: | ---: |
| unsharded | `(256, 256)` | — |
| sharded | **`(1024, 1024)`** — the bundle | `(256, 256)` |

The writer already reads the inner piece size out of the sharding codec, so the
information is there; what the view lines up with is the file. Neuroglancer
itself understands sharded Zarr v3 and asks for a piece inside a bundle by byte
offset, which is why the present design declares the view sharded exactly like
its tiles and hands over whole bundles. That works, and it pins alignment to the
shard.

With the uniform lower/right trim every placement number is a multiple of the
step, so a 1024 bundle does divide a 2048 step — but only two levels deep, where
the inner chunk would reach four. **Sharding therefore halves the pointed depth
unless the resolver exists.**

**That is escapable, and it has been demonstrated rather than assumed.** A shard
is not opaque: it is the encoded inner chunks laid end to end with a small index
at the back giving each one's offset and length. Reading that index and handing
back one chunk's byte range was tried against real Zarr v3 data — inner chunks of
256 bundled into shards of 1024, Zstd compressed, index at the end with a CRC32C
trailer. All sixteen inner chunks of a shard were lifted out by byte range and
decoded **identical** to what zarr itself returns for the same region. That is
required test 11 of the decision record, passing.

So the arrangement is:

- **canonical positions are sharded**, for the file count;
- **the linked views are logically unsharded** — they advertise inner chunks and
  resolve each one to a byte range inside a shard;
- **alignment therefore returns to the inner chunk**, and the shard shape stops
  constraining the chunk entirely.

This makes the resolver a prerequisite for sharding rather than a later
refinement: with it, sharding costs nothing in alignment; without it, sharding
and linking genuinely do fight.

#### What a shard should cover

| shard covers | files in a 500 GB run | file size |
| --- | ---: | ---: |
| nothing — loose chunks | 5,461,236 | tiny |
| one z plane | 67,423 | 10 MB |
| **8 z planes** | **8,428** | **81 MB** |
| **16 z planes** | **4,214** | **162 MB** |
| a whole position | 1,686 | 405 MB |
| four positions | 421 | 1,620 MB |

The rule is one sentence: **a shard may span anything inside a single commit, and
nothing across commits.**

That follows from what a commit already is. The publication unit is a complete
position, or a complete timepoint of one, and by definition that includes every
channel and every z plane. So bundling across those axes cannot expose anything
half-written — strict publication already requires them all to be finished before
anything becomes visible. Bundling across time or across positions is a different
matter entirely, because those *are* separate commits.

| axis | may a shard span it? | why |
| --- | --- | --- |
| z | **yes** | inside one commit; bound it to 8–16 planes for file size, not for correctness |
| channel | **yes** | inside one commit; every channel must be complete before publication anyway |
| time | **no** | appending timepoint 2 would rewrite the published file holding timepoint 1 |
| position | **no** | the earlier positions would wait for the later ones, and their published bytes would be rewritten |

Concretely: **one shard per timepoint, per channel, covering a z-slab sized to
land near a hundred megabytes, within a single position.**

Channels are kept separate rather than bundled simply because there can be up to
six or seven of them; bundling would multiply the file size by that count, and
sizing the slab per channel keeps files near the target whatever the channel
count turns out to be.

Sizing the slab to the file rather than to a fixed plane count is what makes this
stable across the whole envelope — frames anywhere from about a thousand to five
thousand pixels square, and stacks from a handful of planes to a few hundred:

| frame | one plane | z-slab | file size | files for a 500 GB run, 7 channels, all levels |
| ---: | ---: | ---: | ---: | ---: |
| 1024 | 2.0 MB | 50 | 100 MB | ~6,800 |
| 2048 | 8.0 MB | 12 | 96 MB | ~7,100 |
| 2304 | 10.1 MB | 10 | 101 MB | ~6,700 |
| 4096 | 32.0 MB | 3 | 96 MB | ~7,100 |
| 5120 | 50.0 MB | 2 | 100 MB | ~6,800 |

About seven thousand files for half a terabyte, whatever the frame size, against
five and a half million unsharded. That is the property worth having.

### What the profile builder chooses, across the envelope

Preference order, which encodes what actually costs what: enough pointed depth
that the written levels stay small; then staying inside the comfortable overlap
band, because overlap is microscope time; then the largest chunk, because that
is the fewest requests to fill a screen; then the least overlap as the tie-break.

| frame | chunk | overlap | fraction | step | pointed levels | chunks per plane |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1024 | 128 | 256 | 25.0% | 768 | 2 | 64 |
| 1280 | 256 | 256 | 20.0% | 1024 | 3 | 25 |
| 1536 | 128 | 256 | 16.7% | 1280 | 2 | 144 |
| 2048 | 128 | 512 | 25.0% | 1536 | 3 | 256 |
| 2160 | 144 | 432 | 20.0% | 1728 | 3 | 225 |
| **2304** | **256** | **256** | **11.1%** | 2048 | **4** | **81** |
| 2560 | 512 | 512 | 20.0% | 2048 | 3 | 25 |
| 3072 | 128 | 512 | 16.7% | 2560 | 3 | 576 |
| 4096 | 128 | 512 | 12.5% | 3584 | 3 | 1024 |
| 5120 | 512 | 1024 | 20.0% | 4096 | 4 | 100 |

### The convention: nine chunks across, one chunk of overlap

Running the chooser over both instruments this facility actually uses — confocal
at roughly a thousand to two thousand pixels square with five to ten channels and
up to a hundred planes, and mesoSPIM at around five thousand square with a few
channels and a few hundred planes — the same shape keeps winning, at every scale:

| | frame | chunk | overlap | step | pointed | chunks per plane |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| confocal, smaller | 1152 | 128 | 128 (11.1%) | 1024 = 2¹⁰ | 4 | 81 |
| confocal, larger | 2304 | 256 | 256 (11.1%) | 2048 = 2¹¹ | 4 | 81 |
| mesoSPIM | 4608 | 512 | 512 (11.1%) | 4096 = 2¹² | 4 | 81 |

So the convention is one sentence: **make the frame nine chunks across, give one
chunk of it to the overlap, and step by eight.**

The overlap, the pointing depth and the number of requests per plane come out
identical at every scale; only the chunk scales with the frame. The reason is the
uniform lower/right trim: every placement number is a multiple of the step, so a
step that is a pure power of two is exactly what buys pointing depth, and nine
chunks minus one chunk is eight chunks.

Some round numbers are a trap. A 1024 or 2048 frame is forced to 25% overlap for
shallower pointing than 1152 or 2304 achieves at 11.1%. A 4096 frame can reach
12.5% overlap, but only by choosing 128-pixel chunks, which means 1,024 chunks per
plane:

| frame | best overlap in band | pointed | verdict |
| ---: | ---: | ---: | --- |
| 1024 | 25.0% | 2 | poor, writes many levels |
| **1152** | **11.1%** | **4** | excellent |
| 2048 | 25.0% | 3 | workable |
| **2304** | **11.1%** | **4** | excellent |
| 4096 | 12.5% | 3 | workable, but many small chunks |
| **4608** | **11.1%** | **4** | excellent |
| 5120 | 20.0% | 4 | workable |

Where the scan format is a software setting, as it is on a confocal, the profile
builder should offer the better format and say what it saves. Where the camera's
frame is fixed — an sCMOS at 5120 — the same arithmetic simply reports the
honest cost, which at 20% overlap and four pointed levels is perfectly workable.

**A finding worth acting on.** A 2304 frame is markedly better than its
neighbours: it combines a 256-pixel chunk and four pointed levels at **11.1%**
overlap. Overlap is microscope time, so that is roughly a tenth of the run's
imaging saved, along with a quarter as many requests per plane as a 2048 frame.

Where ZMART controls an adjustable scan format, the profile builder should say so
and offer the better format rather than silently accepting a worse one. Where the
camera's frame is fixed, the same arithmetic simply reports the honest cost.

Not spanning positions matters more than the file count does. Positions arrive
one at a time and each has to become visible on its own; a shard covering four of
them cannot be closed until all four have landed, so the first three would sit
invisible waiting for the fourth. Adding a position later would also mean
rewriting a file that has already been published, which the whole design forbids.
The saving from four positions per shard is 421 files against 8,428, and 8,428 is
already comfortable. It is not worth breaking publication for.

Not spanning timepoints is the same argument in time: appending a second
timepoint must not rewrite the file holding the first, because the first is
already published and immutable. A new timepoint makes new shards.

Eight to sixteen planes gives 81–162 MB files and takes five and a half million
files down to four or eight thousand — about a 650-fold reduction, which is the
move-it-around problem solved. A whole position at 405 MB is too large for a live
write unit: that much would have to be buffered before anything became visible.
The final number is to be benchmarked on the actual Windows microscope computers,
as the decision record already asks.

### Deferred, deliberately

End-to-end concurrent analysis consumption. The layout records and ownership
ROIs now exist and are tested, but the production analysis runner does not yet
pin a committed layout revision and reject results outside that revision's core.

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
