# Making the built viewer feel instant, beside a live view it must not touch

> Planned 2026-08-11, from measurements taken on a 4-core Linux sandbox and the
> lab figures already recorded in this folder's commits. Nothing below is built
> yet. The changes are listed in the order worth building them, and each one
> says how to check it did what it promised.

The built viewer shows a transfer from another microscope by building each
piece of the picture on request — decoding the tiles that cover it, laying
them in, encoding the result. It is correct (zero wrong voxels against the
real Thy1 set, checked through the bytes on the wire) and it scales (a piece
costs the same at four thousand tiles as at sixty-four). What it is not yet is
*instant*, and the slowness is confined to one situation: the first look at
fresh ground at fine resolution.

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
server stops, so the same work is paid again tomorrow. Second, the transfer a
piece is built from never changes — it arrived finished — so anything built
from it is true forever. Cheap to keep, safe to keep, and today kept nowhere.

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
piece ever built, keyed by transfer identity, resolution and piece coordinate.
A request checks the folder before building; a build writes what it made.
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

## The same viewer must also show a live run — and must leave it alone

The viewer's front door serves two kinds of picture through one ladder: a
piece is either *pointed at* (a governed live run, answered by the gateway out
of the positions' own bytes), *built* (a finished transfer, everything above),
or *absent*. The operator never needs to know which answered. A live smart-
microscopy run makes the built path's tricks look tempting in the one place
they must not go, so the boundary is worth writing down as rules rather than
taste:

- **Live ground is asked about fresh, every request.** The gateway's decision
  — published or withheld — is the live contract, it changes on every commit,
  and it costs about half a millisecond. There is nothing worth caching and
  everything to lose: a remembered "allowed" can show a tile whose commit was
  rolled back; a remembered "withheld" can hold blank what has just been
  published. The piece cache (change 2) and the builder never see a live path.

- **Prefetch may look ahead on a live view, but through the gate.** Reading
  ahead of a pan is as useful live as it is on a transfer, and as cheap as any
  other pointer answer — but the prefetcher asks the gateway at fire time like
  any other request, and keeps nothing. If any read-ahead is ever held even
  briefly, the view's own change counter is the key that says it is stale.

- **The slowness these changes attack does not exist on the live path.** That
  is the quiet conclusion of the measurements above: pointing is already
  faster than every optimisation here can make building. The live view needs
  none of this, and the complication the live view brings is contained
  entirely in the two rules above — everything else in this plan runs on
  ground that holds still.

What order to build in, then: the slab finish and the disk cache first,
because they are small and pay immediately; the coarse warmer next, because
it is the fix for the one slowness a person at the microscope has actually
reported, and the coarse levels it pins are the cache's ideal tenants —
smallest in bytes, dearest to build, wanted by every session, immutable
forever, and therefore never evicted; parallel building after that, which
also makes the warmer itself finish sooner; the priorities, the piece-size
measurement and any predicting prefetcher last, on the lab machine, and only
if a person there still feels a wait.

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
   chunks are refetched, a pointer answer costs about half a millisecond, so
   a commit that flushes a viewport of a hundred chunks costs ~50 ms of
   server work. The gateway's parallel-fire tests hammer exactly this storm.
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
