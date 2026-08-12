# Making the built viewer feel instant, for transfers and the live run alike

> Planned 2026-08-11, from measurements taken on a 4-core Linux sandbox and the
> lab figures already recorded in this folder's commits. Nothing below is built
> yet. The changes are listed in the order worth building them, and each one
> says how to check it did what it promised.
>
> **Updated 2026-08-12, the same night, for the superseding decision in
> `docs/design/pointing-and-building.md` on the live branch.** Building is no
> longer only the import path: the governed live view is served by building
> too, behind the manifest gate, because dense arbitrary placement — the
> point of smart microscopy — is exactly what pointing's alignment
> conditions compound against. This promotes the plan from "make the import
> viewer pleasant" to "make the main serving path pleasant", adds change
> zero (the composer learns the gate), and rewrites the live-view rules:
> live ground is now cacheable, with the view's change counter in the key.

The built viewer shows many positions as one picture by building each piece
on request — decoding the positions that cover it, laying them in, encoding
the result. It is correct (zero wrong voxels against the real Thy1 set,
checked through the bytes on the wire), it scales (a piece costs the same at
four thousand tiles as at sixty-four), and it is placement-blind: fractional
offsets, dense clusters and overlap cost it nothing, which is why it now
serves the live run as well as the transfers that arrive finished. What it
is not yet is *instant*, and the slowness is confined to one situation: the
first look at fresh ground at fine resolution.

## What is slow today, measured

On the lab machine against the real Thy1 transfer:

    a screenful of fresh full-resolution ground     1.2 - 1.8 s
    the same screenful, already built                 64 - 86 ms
    the first plane of a slab                        300 - 436 ms
    each further plane of that slab                          6 ms
    a coarse piece, from the tiles' own copies              57 ms
    the same ground built down from full resolution       1494 ms
    empty ground                                           0.2 ms

On the sandbox, with synthetic tiles at fractional offsets: a fresh piece
costs 26 - 42 ms, flat from 64 to 1024 tiles. For comparison, the pointing
path that serves our own governed runs answers in about 0.5 ms a chunk on the
same machine — so building is the one place a wait can be felt at all.

Two facts shape everything below. First, a built piece is thrown away when the
server stops, so the same work is paid again tomorrow. Second, a built piece
stays true for as long as its sources do not change — which for a finished
transfer is forever, and for a live run is until a commit touches its ground.
The view's change counter names that moment exactly, so "safe to keep" has a
precise meaning in both cases: keep it under the counter value it was built
at. Cheap to keep, safe to keep, and today kept nowhere.

## Where it is actually felt: zooming out

Reported from the microscope, 2026-08-11, and it relocates the problem: the
gesture that is really slow is not panning or zooming in — it is **zooming
out**. The benchmarks above measured pieces; the operator measured gestures,
and the gesture measurement is the one that matters. The mechanism, once
said, is obvious in hindsight.

Which levels count as "coarse" is decided by size, not by picking numbers:
**pin every pyramid level smaller than one percent of the transfer.** With
halving in y and x, each level is a quarter of the one above — level 3 is
1.6 percent, level 4 is 0.4 — so the rule pins level 4 and coarser, about
half a percent of the transfer all together (4 GB against 800). Halving z as
well, it pins level 3 and coarser at a fifth of a percent. The rule scales
itself to any transfer, and the geometric sum bounds what it can ever pin.
Levels finer than the cut are still cached when visited; they are simply
evictable, where the pinned levels never are.

**Coarse pieces aggregate positions.** The scaling argument — a piece is
covered by a handful of tiles however large the run — is true at full
resolution and stops being true one level at a time above it. Each level up,
a piece of the same 512-pixel size covers four times the ground, so it meets
about four times the tiles. Three levels up, hundreds. The coarsest piece of
all — the whole survey in one look — meets **every position in the
transfer**. The cost of a piece follows the tiles that reach it, so zoom-out
systematically requests the most expensive pieces in the pyramid.

**Each position costs its full entry price for a sliver.** A coarse piece
takes a thin sliver from each of those many positions, but the price per
position is nearly constant however little is taken: open the file, read a
block of its coarse copy, decompress the whole block, keep the sliver, throw
the rest away. This is the same disease this folder has cured twice already —
the unit asked for smaller than the unit stored — but multiplied across
hundreds of sources at once, as hundreds of small scattered reads over
hundreds of files. It is the read-side twin of the many-little-files problem
that sharding solves on the write side, and it is at its worst exactly where
transfers live: Windows machines and network shares, where per-file overhead
dominates small reads.

**And the deferred opening bill lands here.** Opening a tile is postponed
until the first piece that touches it, which is right for zoomed-in work
where a piece touches nine. The first zoom-out touches all of them, so the
entire postponed opening cost of the transfer — seconds, at thousands of
tiles — arrives on a single request. The laziness did not shrink the bill;
it moved it to the one gesture that collects it whole.

Every other gesture moves toward fewer tiles per piece and bigger slivers per
tile, which is why nothing else is felt. The consequence for this plan is
written into change 4 below: the answer to zoom-out is not predicting, it is
**warming the coarse levels exhaustively**, because they are the one part of
the pyramid small enough to build completely and expensive enough to build
only once.

## The six changes, in building order

### 1. Finish the slab that is already decoded

**What.** Answering for one plane already decodes the whole 32-plane slab of
blocks — that is simply what a compressed block is. Today the other 31 planes'
pieces are encoded only when asked for, one request at a time. Instead, when a
piece of plane 12 is built, encode the same piece of the neighbouring planes
while the decoded blocks are still in hand.

**Why.** A microscopist inspects a stack by scrolling through focus, and this
makes that the smoothest movement in the viewer: 6 ms a plane instead of a
fresh request each time. It is also the smallest change on this list — the
expensive work is already done; only the cheap tail is being kept.

**Check.** Scroll through 32 planes of one screenful, cold. Today that is 32
round trips into the slab; afterwards the first plane pays and the remaining
31 arrive at cache speed. Byte-compare a sample of the pre-built pieces
against freshly built ones.

### 2. Keep built pieces on disk

**What.** A cache folder beside the viewer's own bookkeeping, holding every
piece ever built, keyed by picture identity, resolution, piece coordinate —
and, for a live run, the view's change counter at the moment of building.
A request checks the folder before building; a build writes what it made.
For a finished transfer the counter never moves and the key is effectively
the old three-part one; for a live run, a commit moves the counter for the
ground it touched, which makes the stale entries unreachable by key — they
are never *found* again, and the eviction sweep reclaims them at leisure.
One rule, both kinds of picture, no special cases in the lookup.
Bound it by bytes, oldest out, like the in-memory caches — but measured in
gigabytes, because disk is cheap and the pieces compress well.

**Why.** This turns the one-time cost into a genuinely one-time cost. It is
lazy conversion: the transfer converts itself exactly in proportion to what
people look at, with no up-front rewriting, and the cache survives restarts so
tomorrow's first look at yesterday's ground is instant. The transfer is
immutable, so a kept piece can never go stale — the only cache in this system
with nothing to invalidate.

**Check.** Build a screenful, restart the server, ask again: file-read speed,
byte-identical to the first answer. Corrupt one cached piece by hand and
confirm the checksum check rebuilds it rather than serving it.

**Large transfers.** The worry that this cache grows without limit has an
arithmetic answer. Its ceiling is the fully built picture — the transfer's own
size plus a third for the pyramid — and reaching that ceiling just means the
lazy conversion completed. For a transfer too large to ever hold whole, say
800 GB, the pyramid does the work: each level is a quarter of the one above,
so levels two and coarser for the *entire* picture come to well under a tenth
of the transfer — pin those, and all navigation everywhere is permanently
instant. The two finest levels are where operators visit only regions of
interest, a few gigabytes each, and the byte-bounded oldest-out rule keeps
exactly the regions that were visited. Ten to twenty percent of the
transfer's size is a comfortable budget; an evicted piece is not an error but
30 ms of rebuilding, so the budget is a dial, never a cliff. One cache folder
per transfer with a last-touched date, so cleaning up after a finished
project is one visible delete rather than a surprise found later.

**The browser's own layers stack on top.** Built pieces are immutable, so the
server should say `Cache-Control: immutable` on them and let the operator's
own browser be the front line — revisits then never even reach the network.
The live path is the opposite and must be marked `no-store`: a
browser-remembered "withheld" would hold published ground blank, and a
remembered chunk could outlive a rollback. Nothing between the gateway and
the operator's eyes may remember a live answer.

### 3. Build the pieces of a screenful in parallel

**What.** A screenful is 8 - 16 independent pieces, and the expensive step —
decompressing blocks — releases Python's lock, so pieces can genuinely build
on separate cores. Give the composer a small worker pool and let a burst of
requests use the whole machine.

**Why.** The 1.2 s fresh screenful is mostly pieces waiting their turn. Four
cores take it toward a quarter of that before any other trick is applied.

**Check.** The parallel-fire test in `check.py` already asks for a dozen
pieces at once and compares each against a lone polite build — extend its
timing side: the wall-clock for a cold screenful should fall roughly with the
core count, and the bytes must not change at all. The shared-encoder mistake
this folder once shipped is exactly what that comparison is there to catch.

### 4. Warm the coarse levels exhaustively — prediction only if ever needed

**What.** On opening a transfer whose cache is cold, build **every piece of
the coarse levels** in the background, and keep them on disk. No prediction,
no motion model: the coarse pyramid is the one part of the picture small
enough to enumerate — all of level 2 and coarser is a few percent of the
transfer — and, as the zoom-out section above says, the most expensive part
per piece. Speculate on all of it, because all of it is affordable and every
piece of it will eventually be wanted.

Build it bottom-up and chain the pyramid: only the finest warmed level reads
the positions themselves (paying the many-files scatter exactly once), and
each coarser level is averaged from the four built pieces below it, never
touching the positions again. The warmer runs at idle priority — a real
request always preempts — and coarsest-first within a level ordering, so the
whole-survey look becomes instant earliest.

**Why.** This is the fix for the one slowness an operator actually reported.
After the warmer has run once, zoom-out reads a handful of contiguous cached
pieces from one local folder instead of slivers from hundreds of files, and
it stays that way forever, for everyone, because coarse ground built from an
immutable transfer never goes stale.

**What it costs, so nobody is surprised.** The warmer's floor is one visit
to every position — that is what building the finest pinned level means, and
no cleverness lowers it. At today's 24-tile transfers that is a couple of
seconds, and the operator's own first zoom-out was already paying most of it.
At survey scale it is minutes: ten thousand positions cost about three
seconds of opening (0.28 ms a tile, measured) plus one coarse block read and
decode each at a few milliseconds — one to a few minutes for an 800 GB
transfer, dominated by the per-file scatter and worse on a network share.
The design absorbs those minutes rather than showing them to anybody: paid
once ever, run in the background behind real requests, coarsest level first
so the whole-survey look works within seconds of opening, and pieces the
operator's own browsing has already built are skipped, not rebuilt.

The motion-predicting prefetcher this change once was is demoted to a
someday: after changes 1-3 and the warmer, the remaining cold case is a
first-ever pan across fine fresh ground, and nobody has reported feeling it.
Build a predictor when a person at the microscope says otherwise, not
before.

**Check.** Open a large transfer cold, zoom straight out: today that is the
worst request in the system, collecting the whole deferred opening bill;
after the warmer has finished it is file-read speed. Byte-compare warmed
pieces against freshly built ones, including a chained coarse piece against
the same piece built directly from the positions — the chaining must change
where the bytes come from, not what they are.

### 5. Serve the coarse copy before the fine one

**What.** When requests queue, answer coarse-level pieces first. They cost
57 ms against 1494 and they are the layer the engine stretches over everything
while fine pieces arrive.

**Why.** The operator then always sees a complete, merely soft picture at
once, sharpening underneath — instead of a patchwork of sharp and missing.

**Check.** Time-to-first-complete-picture on a cold open, which should fall to
roughly the cost of the coarse pieces alone.

### 6. Measure the piece size instead of reasoning about it

**What.** `PIECE = 512` says in its own comment that it is reasoning rather
than measurement. Run the existing measurements at 256 and 512 on real
specimen and let the numbers pick.

**Why.** Smaller pieces mean less work before the first pixel appears, at the
price of more requests — exactly the trade this plan is about, and the one
number here nobody has measured.

**Check.** The measurement scripts in this folder, plus time-to-first-pixel on
a cold screenful at each size, on the lab machine and named as such.

## Change zero: the composer learns the gate

The superseding decision makes one piece of genuinely new work, and it comes
before everything numbered above can touch a live run.

**What.** Today the gateway decides *what may be shown* and the composer
assumes *everything on disk is showable*. Serving the live view by building
means joining them: before laying tiles into a piece, the composer asks the
manifest which positions and moments are published, lays **only those**, in
**commit order** with the later commit on top — never arrival order, never
layout order — and stamps the result with the view's change counter for the
cache key. Withheld ground is left as fill, exactly as if it had never been
written, so a position that is on disk but uncommitted neither appears early
nor blanks the published ground beneath it.

**Why first.** Every numbered change below is an accelerator; this is the
correctness on which they may accelerate. A disk cache over an ungated
composer would happily preserve a leaked uncommitted tile forever.

**Check.** The full harness the gateway already has, aimed at the built
path: the sabotage campaigns gain composer faults (lay in arrival order;
ignore the manifest; keep serving a cached piece across a commit that
touched it), each watched failing first; the parallel-fire tests run against
built answers — a commit landing mid-storm must never surface withheld
pixels, blank published ground, or hand back a torn mixture; and the browser
production test photographs the same three promises through a genuine
Neuroglancer, as it does today.

## The live run, under the same roof

With the gate inside the composer, the live rules simplify to three, and
none of them says "the builder never sees a live path" any more:

- **The manifest is consulted fresh at build time, and its answer travels in
  the cache key.** A cached piece is not a cached *decision* — it is a
  cached *result of a decision*, valid exactly as long as the change counter
  that names it. A rolled-back commit moves the counter; the stale piece
  becomes unreachable by key. Nothing anywhere remembers "allowed" or
  "withheld" as such.

- **The browser must stay forgetful on live ground.** Server-side caching is
  safe because the server sees every commit; the operator's browser does
  not. Live view pieces are served `no-store`; only finished transfers get
  `immutable`. Nothing between the server and the operator's eyes may
  remember a live answer.

- **The warmer runs on live ground too, incrementally.** Coarse pieces of
  published ground are warmed like any transfer's; when a commit lands, the
  handful of coarse pieces above the touched ground are re-queued at idle
  priority. A 12x12 half-second-commit run re-warms a few pieces per commit
  — pennies — and the whole-survey look stays permanently current.

What order to build in, then: **change zero when the live run is the
target** — it is the correctness everything else accelerates — with the slab
finish and the disk cache beside it, because they are small, pay immediately
and serve both kinds of picture; the coarse warmer next, because it is the
fix for the one slowness a person at the microscope has actually reported,
and the coarse levels it pins are the cache's ideal tenants — smallest in
bytes, dearest to build, wanted by every session, stable under the counter
rule; parallel building after that, which also makes the warmer itself
finish sooner; the priorities, the piece-size measurement and any
predicting prefetcher last, on the lab machine, and only if a person there
still feels a wait.

## Benchmark the crux itself: many sources against one picture

The root requirement — many tiles must reach the viewer as one image —
rests on a claim nobody has measured as a curve: that Neuroglancer
collapses when handed one source per tile. The claim is surely true at ten
thousand; where it *starts* being true is unknown, and the answer has
consequences — if a few hundred sources are actually fine, small runs may
not need the server at all, and the crossover count is a fact worth owning
rather than assuming.

**The measurement.** Two arms over identical synthetic runs, at rungs of
1, 5, 10, 50, 100, 200, 400, 800 and 1600 positions:

- *As sources*: every position handed to Neuroglancer directly, one layer
  source per store, no server cleverness.
- *As one picture*: the same positions behind the built seamless view.

**Every metric, both arms, per rung** — following the house measuring
rules (several sizes read as a shape, counts beside timings, the machine
named):

- time until the viewer is open and interactive;
- time until the first complete picture (coarse everywhere, however soft);
- a fresh full-resolution screenful, and the same screenful revisited;
- one pan and one zoom-out, as the operator feels them (time until the
  screen settles);
- HTTP requests issued for each of the above;
- browser memory and, where the arm has one, server memory and processor
  time;
- dropped frames or a stuttering interaction, noted honestly even if only
  as an observation;
- and whether the arm survives the rung at all — refusal to open, a tab
  out of memory, or a minute-long hang are results, not failures of the
  benchmark.

**What the curve buys.** The rung where the as-sources arm bends is the
measured crossover: below it, a small run may be shown the simple way;
above it, the one-image requirement binds, now with a number attached.
Plotted beside it, the one-picture arm's flat line is the crux made
visible — the strongest single figure this project can show anyone who
asks why the server exists.

## What the new architecture opens up, beyond speed

Two consequences of serving by building, noted the night of the decision so
they are designed on purpose rather than discovered:

**Views become cheap declarations.** The composer lays pixels at pixel
granularity into whatever frame a view declares, so "what the view shows"
stops being a storage question. A cropped region of interest around one
target, a single slab of depth, a view that lays only the sharp centre of
each position and drops the vignetted rim, a seam-resolved overlap instead
of later-wins — each is just another hollow declared store, a few kilobytes
naming a shape and an origin over the same positions. Many views can stand
over one run at once; the positions stay the single system of record under
all of them; every view of a live run passes the same gate and shows only
published ground. The trimming idea the pointing design had to abandon
(trims had to land on chunk boundaries) returns here for free, at pixel
precision, per view, reversible.

**The stored grid and the served grid are decoupled, on purpose.** Chunks
keep every advantage on both sides — chunked position stores are what make
building affordable (a piece reads only the blocks that cover it), and the
built picture is itself served, cached and prefetched in chunk-shaped
pieces. What is given up is only the *identity* between the two, which was
pointing's zero-copy trick — and with it goes the entire alignment
constraint stack, because that stack was exactly the price of forcing one
grid to serve both the writer and the viewer. Now the storage chunk is
tuned for the acquisition (frame shape, compression, commit latency) and
the serving piece for the screen, independently.

## Neuroglancer and the live view: what was looked up, for someday

The live page makes Neuroglancer notice a grown run by calling
`invalidateCache()` on its chunk sources — see `goBackToTheStore` in
`zmart_live/tests/browser/page/viewer.js`. That call is wholesale: the public
API (`src/chunk_manager/frontend.ts` in google/neuroglancer) offers only
"drop everything this source holds", no per-chunk form, and the Python side's
`LocalVolume.invalidate()` is the same. So today one committed position makes
Neuroglancer refetch every chunk it is displaying.

Checked against the upstream source on 2026-08-11: this is a limit of the
public API, not of the machinery. The backend keeps its cache as a map keyed
by chunk key and already has `removeChunk` for exactly one chunk; the
wholesale call is a thin RPC over granular internals, and no upstream issue
or pull request exposes the granular form. Three routes, in order:

1. *Live with it, measured* — which is what this plan assumes. Only visible
   chunks are refetched, and under the new architecture almost all of them
   come straight from the piece cache at file-read speed — only the pieces
   the commit actually touched rebuild. The parallel-fire tests hammer
   exactly this storm.
2. *Patch our own bundle* — the page already builds Neuroglancer from source
   and already reaches past the public API to find the sources it
   invalidates, so adding an `invalidateChunks(keys)` RPC to our bundled
   copy is the same kind of move, and a day's prototype.
3. *Offer it upstream* — the patch rides entirely on existing primitives,
   and live-updating microscopy is a use case upstream has no story for.
   The prototype from route 2 is the evidence for the pull request.

A commit touches a handful of chunks; per-chunk invalidation turns ~100
refetches per commit into ~10. Worth doing when commit rates rise, not
before.
