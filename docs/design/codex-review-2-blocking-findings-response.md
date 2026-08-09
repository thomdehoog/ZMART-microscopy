# Response to the second Codex review: the seven blocking findings

**Reviewed head:** `23661841`. **This response covers the work done after it.**

Every finding in that review was accepted. None was argued with, and two were
confirmed by direct inspection before any work started, so that whoever fixed
them was working from established fact rather than from a claim:

- `coordinator.py:459` hardcoded `z=1` in the seamless store's shape;
- `ownership.the_far_edges()` appeared nowhere outside its own tests, so the
  21% of every edge tile it computes really was being written as black.

Two constraints from the review are being honoured. **PR #8 stays a draft**, and
**nothing here is connected to the microscope.**

## How this work was done

Each finding was given to a separate worker owning a disjoint set of files, and
every one was told the same two things: **reproduce the defect with a failing
test before changing any production code**, and record the observed wrong
behaviour in that test's docstring. A fix without a test that failed first was
not accepted.

That discipline earned its place. Several defects turned out to be worse than
described once someone actually watched them happen, and two seeded faults were
found to be uncatchable and had to be rewritten rather than quietly counted.

## The blocking findings

### 1–5. The coordinator

*Status: in progress at the time of writing. This section will state what was
fixed, what was reproduced first, and what was not fixed, once that work has
landed and I have verified it myself rather than relayed a report.*

The five defects are: a completely unwritten timepoint could be committed;
readiness was still false in four independent ways; the seamless image silently
lost every tile's far edge; Z stacks were truncated to one plane and channels
were copied rather than written; and committed canonical pixels remained
mutable, so two readers could see different data under one revision.

### 6. The browser harness gated by position, not by moment

**Fixed, and it was worse than reported.** Both halves were reproduced on a real
screen first.

In the three-tile case — A and B published, C written but not published —
C was **fully drawn**, and the server's own counters showed why: `A: served 225`,
`C: served 0, refused 0`. Every one of C's chunks was served *under A's name*.
The server never knew it had been asked for C at all. The two-tile fixture could
not see this, because sharing a stop only becomes possible with three.

The later-moment case was equally plain: with A's second moment written but not
published, `A moment 1: served 64, refused 0`, fully drawn.

The fix keys availability on the `(position, moment)` pair read from the piece's
own address, and attributes raw-view pieces by **stop plus spatial region**
rather than by stop alone — stops are deliberately reused by tiles that cannot
overlap, which is exactly what made the old rule wrong. A start-up check now
refuses to serve any run in which a raw piece could hold two same-stop tiles.

Afterwards: `C: served 0, refused 81`, `A moment 1: served 0, refused 64`.

The sabotage script grew to six faults, all caught, and gained a guard that
lists the runner's real test titles first — because "no test matched" and "a test
failed" look identical from outside, so a reworded title would otherwise be
silently recorded as a fault caught.

### 7. The positions were not conforming OME-Zarr images

**Fixed.** `zarr.open_group()` now succeeds. The group carries `ome.version`,
`multiscales`, axes with UDUNITS-2-checked units, per-dataset scale and
translation, and `dimension_names` on every level. Levels are described first and
the group declared second, so an interruption never leaves a folder announcing
itself as an image it is not.

Fifteen seeded faults, all caught on the first run.

Two details worth recording because they are the kind of thing that makes a test
prove nothing. The headline test opens the group with `mode="r"`, because the
default `mode="a"` **creates** the missing group — written the obvious way, that
test would have passed against the unfixed code. And the multiscale `type` is
`"mean"` rather than `"nearest"`, because the coordinator genuinely averages
two-by-two blocks; describing it otherwise would have been a false statement
about the data in a file other people's software reads.

## Identity and persistence

All five fixed, each reproduced first.

- **Profiles are persisted**, atomically, and re-fingerprinted on load so a
  hand-edited file is caught rather than believed.
- **Profile identity is content-addressed** over the whole profile. The
  reviewer's two colliding `confocal-1152-128` profiles now get different names.
  `channels` had to be added to `AcquisitionProfile` for this: without it the
  fingerprint could not cover the colours, and a profile whose identity does not
  cover its contents is not sealed at all.
- **Names are path-safe**, checked when the record is built, before any pixels
  are written. `../../escaped` is refused, as are Windows device names such as
  `CON` and `CON.txt`, since this runs on Windows microscope computers.
- **Layout revisions are numbered and immutable.** A changed arrangement mints
  the next snapshot; an arrangement that says the same thing reuses the existing
  one, which is what the decision record asks for.
- **Rectangular frames** are supported per axis. The square-only shorthands now
  refuse to answer for a rectangle rather than handing back one of two sides.

One seeded fault — *measure the width's overlap against the height* — was **not**
caught at first, because a 2:1 rectangle still gives the right answer. The tests
were widened to four shapes in both orientations until it was.

## Scaling: the shard resolver

**Reproduced, diagnosed and fixed — and the diagnosis was not what anyone
expected.**

The reviewer measured about 71 ms per chunk request; 90 ms was reproduced here on
a 96-plane bundle. But measuring rather than assuming showed that **95% of it was
the CRC32C checksum**, computed one bit at a time over a 124 KB table. That
matters independently of any cache, because during a live run the bundle being
written keeps changing and every request legitimately misses.

| planes per bundle | as it was | reading afresh now | remembered |
| ---: | ---: | ---: | ---: |
| 12 | 12.0 ms | 1.7 ms | 33.8 µs |
| 24 | 24.0 ms | 3.4 ms | 40.5 µs |
| 48 | 49.4 ms | 6.9 ms | 29.8 µs |
| 96 | **90.2 ms** | 15.7 ms | **29.3 µs** |

The shape is the finding. The old cost **doubled every time the bundle doubled**
— it was proportional to the whole table, not to the one chunk being asked for.
Remembered is flat. Expressed as a count, which survives a busy machine where a
timing does not: one screenful of 48 requests now reads **one** table off the
disk instead of forty-eight.

The cache is keyed on the file's full identity — path, device, inode, size and
both timestamps, plus the geometry the table was parsed with — so a rewritten
bundle misses rather than serving a stale index. It is bounded twice, by
remembered positions and by remembered bundles, so neither a few huge bundles nor
many tiny ones can grow it without limit.

`viewroute` was also re-reading each position's description on every request,
about two thirds of what remained after the checksum fix.

Three things that worker declined to claim: the re-stat guard is untestable and
is recorded as a claim the tests do not make; one seeded fault was uncatchable
and was rewritten into two that are; and the miss path is still 15.7 ms on the
largest bundle, with the next step identified but deliberately not taken.

## A flaw found in our own evidence

Two workers independently hit the same trap, and it undermines every fault
campaign in this repository, so it is reported here rather than buried.

Python decides whether its compiled copy of a module is still valid from the
source's **size** and the **second** it last changed. A seeded fault that swaps
one word for another of the same length, and is reverted within the same second,
leaves both unchanged — so the compiled copy holding the **faulty** version stays
in use. The campaign restores every file correctly, reports every fault caught,
and the next ordinary test run silently executes the broken code. One worker
watched exactly that: a green campaign followed by eight failures from a file
that had already been put back.

The shared harness now discards the compiled copy after every rewrite.

**What is honestly established about that fix:** the guard removes the compiled
copies it says it removes, and that is demonstrated. Staging the trap
deliberately on this machine did *not* reproduce it — the restored answer came
back every time — so something here hides it. The guard is kept because it is
cheap and certainly correct, not because a test here demonstrates the failure it
prevents.

## Still open, and not claimed as fixed

- **The O(N²) view copying.** Every commit still recopies every committed
  position into both full-resolution stores. This is not a defect to patch; it is
  the zero-copy design that was agreed and never built — virtual routing for
  linkable levels, and incremental materialization of only the affected coarse
  chunks. It is the next substantial piece of work.
- **The view stores are not OME-Zarr images either.** Finding 7 was fixed for
  positions; `views/overview-seamless.ome.zarr` and `overview-raw.ome.zarr` are
  still bare arrays, and the view is what an operator actually opens.
- **The browser harness is still not the application path.** It uses a server in
  the test directory rather than `viz_studio/backend`, with no `ViewRoute`, no
  scene discovery and no production refresh, and it calls Neuroglancer's internal
  cache invalidation by hand. The README now says so at the top.
- **No mosaic several rows deep has been watched on a screen.** Stop attribution
  does not assume a single row, but every browser run so far has been one.
- **Nothing has been measured on Windows or SMB**, which is where the file-count
  argument that justified sharding actually bites.
- **`zmart_storage/canvas.py` does not parse on Python 3.10** while
  `pyproject.toml` declares `>=3.10`. Pre-existing, and now inherited by
  `zmart_live.omezarr`, which imports it.
