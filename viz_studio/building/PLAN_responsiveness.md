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

### 4. Build ahead of the operator

**What.** A prefetcher that watches the request stream and fills idle time.
Three rules make it help rather than hurt. It predicts from motion: the last
few requests give a direction, and it builds two or three columns ahead of a
pan, nothing behind it; after a pause on coarse ground it builds the finer
pieces underneath, because a pause is where a zoom begins. It is a priority
queue re-sorted by the current viewport, and work queued for ground the
operator has left is dropped, not built. And it runs only when no real request
is waiting — the operator's own click is always the fastest thing here.

**Why.** Together with the disk cache this is what makes fresh ground stop
being felt: by the time the operator arrives, the ground is no longer fresh.

**Check.** Replay a recorded pan across cold ground with and without the
prefetcher: the with-run should serve almost every piece from cache, and a
deliberately mis-predicting prefetcher (build behind the pan) should measure
no better than none — proving the predictions, not just the extra work, are
what helps.

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

What order to build in, then, is unchanged by the live requirement: the slab
finish and the disk cache first, because they are small and pay immediately;
parallel building third; the prefetcher once there is a cache for it to fill;
the priorities and the piece-size measurement last, on the lab machine, where
the numbers mean something.
