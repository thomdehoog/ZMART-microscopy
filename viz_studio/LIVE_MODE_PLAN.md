# Live mode: one store per acquisition type, declared once

**Status: a proposal, revised after review.** Nothing here is implemented. The first
version of this document was reviewed three times independently; two reviewers ran probes
rather than reasoning, and between them they disproved its central safety argument, found
that one of its load-bearing claims described a mechanism that does not exist, and showed
that the change as first written would make every live run open on a blown-out picture.
What follows is what survived, what replaced it, and what is now known to be blocking.

The disproved parts are kept at the end rather than deleted. A plan that quietly drops its
own rejected arguments invites someone to propose them again.

## What it changes

While a run is being watched, the viewer is given **one OME-Zarr store per acquisition
type**, and each store's canvas is declared in full before the run begins. Tiles and
timepoints are written into places that already exist, so no store changes shape while it
is open.

Opening a finished folder of many stores is untouched, including the pacing in
`engine.js`, which is a correctness fix and not a speed one.

**The `t` half of this is not a change at all.** The docstring of `written_timepoints`,
in `stores.py`, already says: *"A store is given its full length in time when it is
created, long before the run has produced that many frames — that is what keeps an
unpredictable timelapse cheap."* The whole function exists to bound the slider because the
store declares more than it holds, and
`test_masks_luts_and_refresh.py::test_the_time_slider_stops_at_frames_that_exist` pins it.
`DATA_LAYOUT.md` Decision 2, which describes a timelapse growing its own array, is the
stale artefact. Reconciling it is bookkeeping, and this plan should not dress it up as
design.

What is genuinely new is therefore only the **spatial** canvas: declaring `y` and `x` up
front so tiles land in a store that already has room for them.

## Why

The cost is the number of stores, not the amount of data. One store describing about
137 GB reaches the screen in 1.4 seconds on 38 requests; three hundred separate positions
covering a far smaller specimen take 2.4 seconds on 1 125 requests and then draw at a
quarter of the rate. A run that scales with arbitrary tiles is a run whose store count
would otherwise climb without limit.

Note what that evidence does *not* cover: those measurements were taken on stores with
axes `c, z, y, x`. **No measurement in this repository involves a `t` axis at all.** Any
claim about what declaring `t` costs or saves is unmeasured, which is one reason the `t`
half is bookkeeping here rather than a proposal.

## Blocking, and in this order

Neither of these is optional and neither is a detail. The first version of this plan filed
both under "open questions"; they decide whether the design is usable.

### 1. Auto-contrast poisons the session on a canvas that is not yet written

`contrast.measure` crops the last two axes to a square **about the middle** of the
declared canvas, and takes the middle index of every leading axis. Early in a run that is
empty ground. Measured by review on this repository's own 400 GB fixture, the window comes
back `(0.0, 1.0)`, so every voxel above one count draws fully saturated.

It does not recover. `server.py` remembers the measurement for the session, and its guard
against exactly this case tests whether the histogram is `None` — but a histogram of zeros
is not `None`, because `contrast.py` raises the upper bound to at least `low + 1.0`. So
the guard never fires, and every tile that lands afterwards is drawn blown out.

**This is caused by the change, not merely revealed by it.** Under the current layout a
store's description is written *last*, after its pixels, and `library.py` is built around
that ordering — the viewer meets a store that already has something in it. Declaring a
canvas inverts that: the description exists first and the pixels arrive later. The
pathological path the guard was written for stops being unlikely and becomes the normal
first second of every run.

Fix before anything else: sample only where data has actually been written, and make the
cache guard fire on a **degenerate window** rather than on a missing histogram. Then add a
test that looks at the picture. This repository has already paid for that lesson once —
`DATA_LAYOUT.md` records the viewer opening on an empty grey rectangle for weeks with
three hundred tests passing.

### 2. The chunk-key separator cannot satisfy both mechanisms

OME-Zarr allows chunk keys to be laid out in nested folders (`"/"`) or flat with dots
(`"."`), and the two halves of this design want opposite answers.

- **Nested.** `written_timepoints` reads the frame count in one glance, which is what keeps
  the slider honest. But `library.revision()` watches only each store's own modification
  time, its `.zattrs`, and the top of its first level. Under this design `.zattrs` never
  changes — that is the point — so **a tile landing into an existing timepoint moves
  nothing the watcher looks at.** The folder-watch safety net, which exists for writers
  that do not announce, goes blind for precisely the operation this design is built around.
- **Flat.** The watcher sees every chunk, but the frame count falls back to a capped
  directory scan that gives up past `_SCAN_LIMIT = 20_000` and returns `None`. Three
  hundred tiles across two channels, five z planes and seven timepoints is already
  21 000 files. The slider then runs out to the declared length, the operator scrubs into
  frames that do not exist, and the engine's memory of "nothing here" poisons them for the
  session — the exact failure Decision 2 rejected a declared ceiling for.

No choice gives both. This has to be decided, and whichever is chosen, the mechanism that
loses has to be repaired rather than left to fail quietly. Both scripts the first version
of this plan offered as fixture models use the flat layout, which `DATA_LAYOUT.md`
forbids.

## The work this actually needs: invalidation that names a store

`letGoOfDecodedPieces` in `engine.js` walks every shared object the engine holds and
invalidates every one of them. It is triggered by a bare boolean on the announcement, with
no other condition — see the `heard` handler inside `App.jsx`. So a run writing tiles into
one store sets that flag on essentially every announcement, and each one throws away
**every decoded chunk of every source in the viewer** and refetches the whole visible
scene.

Measured in `NEXT_STEPS.md`, a tile landing costs 22 requests, paid on every announcement.
The shape-key refetch that declaring `t` avoids is at most the same visible set and happens
once per *growth*, which is a subset of announcements. **The cost kept is greater than the
cost removed.**

The fix is small and is the one genuine piece of engineering here: have the announcement
name *which store* was written, and invalidate only that store's sources. A store name is
the address of the change, not a second description of the world, so it does not violate
Decision 4's rule that announcements stay detail-free.

This document used to add that `engine.js` documented a gate — the invalidation firing
"only when the scene turned out to be completely unchanged" — that `App.jsx` did not
implement, and that one of the two was therefore a lie. **That has since been put right and
the note is kept only so nobody goes looking for it.** `letGoOfDecodedPieces` now names the
exactly two occasions on which it is called, both of them in `App.jsx`, and `App.jsx`
implements both and no others: a run saying outright that it wrote image into a store
already open, and an acquisition already on screen gaining its first picture. The wider
rule the old docstring described is recorded there as an attempt that was tried and
rejected, with the measurement that rejected it.

## What the writer has to do, and what that is worth

The viewer never writes, so all of this is a requirement handed to whoever does. It is not
work for us, but the design does not hold without it.

**One writer per store, updating the levels above each tile as it lands, announcing after.**

The reason is the copies of the image. The size of a piece is held constant across them
here (see how `chunks` is chosen in `demo_data.py`), so a tile that is exactly one piece of
the full-size copy is a quarter of a
chunk at the level above, a sixteenth two levels up. Several tiles therefore share one
coarse chunk file, and updating it means reading it, adding a contribution and writing it
back. **That is entirely safe when one process does it in order** — read-modify-write is
only dangerous under concurrency, and measured loss of three tiles in four came from two
writers in the same file at once. A single writer handling tiles one at a time, which is
the natural shape when a microscope visits one position at a time, has no race to lose to.

Announcing *after* the coarse levels are updated matters: it means the viewer never sees a
state where level 0 holds a tile that the levels above it do not.

Be honest that this contention is **created by this change**. Today each tile is its own
store with its own pyramid, so no two tiles ever share a coarse chunk and the question does
not arise. We would be asking for the layout that introduces it.

Two further requirements on the writer:

- **Set `write_empty_chunks=True`, or accept that data is deleted.** It defaults to
  `False`, and it does not merely skip writing an all-empty chunk — it deletes one that is
  already there. A retake that comes back black, because a shutter stayed shut or the
  focus was lost, erases the good tile that was in its place. Nothing in this repository
  sets it.
- **Tiles must begin and end on chunk boundaries in `y` and `x`,** stated in chunk indices
  rather than micrometres. A tile straddling a boundary forces read-modify-write at
  level 0 as well, and loses up to 75% of a tile's voxels silently. The writer holds
  micrometres, so the index arithmetic — voxel size, stage step, canvas origin — is where
  this will actually go wrong.

**The viewer's half of this is to check, not to fix.** On open, read each level's `.zarray`
and say so when the tile step is not a chunk multiple at that level, or when a non-`y`/`x`
axis is chunked above 1. That is reading, which is the viewer's job, and it turns silent
corruption into a visible complaint. The lab's own mesoSPIM stores would fail that check
today: they chunk `z` at 128.

## Canvas size

Sized to the ground the experiment means to cover. Where the experiment does not say,
`DATA_LAYOUT.md` offers the stage's travel limits — **but that default was justified for an
overview and does not carry to every acquisition type.** The justification was that a
stage's range is a few centimetres, nowhere near the hundred-fold over-declaration that
spoils the brightness measurement. Against a target scan's field of a couple of hundred
micrometres, stage travel is roughly five hundred times too big per axis, which is two to
three orders past that stated bound.

So the bound stands and has to be applied per acquisition type. The first version of this
plan wrote that the canvas "can be generously over-estimated", which deleted a limit the
design record had put there deliberately.

Origin at the low corner, growth only ever outward. And `z` needs an answer: it is declared
by the acquisition, and unlike `t` it has **no written-count guard anywhere** — the slider
takes its range from the declared shape. Either do not declare `z` beyond what is acquired,
or build the counter that `t` already has.

## What is not in scope

The production writer. Writing happens **only inside the test suite**, and should stay one
small fixture helper — if it grows a pyramid updater, it has become the writer and the
scope line has moved without anyone deciding to move it.

Also out of scope: fusing finished folders, and making folders of many stores faster.

## The tests

Rewritten. The first version proposed eight; three already existed, one could not pass, one
had no assertion, and one tested the wrong pyramid level.

1. **A store opened at the moment its canvas is declared, before a single pixel exists** —
   and the picture is not blown out, then or after tiles land. This is the normal first
   second of every run under this design, no existing test covers it, and the fixture that
   would have caught it passes today because it only asserts a 200 and an elapsed time.
   This is the most important test in the list.
2. **Tiles and timepoints landing into one declared store together**, every tile appearing
   at the timepoint it was written to, with the two announcement orders run both ways. No
   existing test does both: every spatial-tile fixture has no `t` axis, and every `t`
   fixture writes whole frames. Attach a fetch count, or a whole-page invalidation makes it
   pass for the wrong reason.
3. **A place looked at before it was written appears once written**, for a tile position
   and for a timepoint, with the negative control that it stays blank when invalidation is
   not asked for. The control currently exists only as a script.
4. **No store's shape changes in live mode**, and a landing timepoint triggers no
   whole-page invalidation. This replaces the first version's "regression test", which
   already exists and already passes and therefore could not have said anything about the
   change.
5. **The cost of one landing does not grow with the declared canvas** — asserted as
   independence across two very different canvas sizes, not as a fixed request count. The
   number quoted in the first version was prose in a script, not a measurement, and the
   same quantity measured elsewhere is 22.
6. **The viewer's chunking check fires** on a store whose tile step is not a chunk multiple,
   and on one chunked above 1 in a non-spatial axis.

Scale at realistic tile and timepoint counts belongs in a `measure_*.py`, where every other
measurement in this repository lives — an unasserted benchmark in the suite has no failure
mode and the suite is already nine minutes. Demonstrating chunk-straddling loss belongs in a
`check_*.py` for the same reason: it asserts a property of zarr and of concurrent writers,
with the viewer never started.

## How you would know it was finished

- A canvas declared before any pixel exists opens on a sane picture, and stays sane as
  tiles land.
- A store declared once and written into as a run proceeds shows every tile at every
  timepoint, with no shape change, and an announcement invalidates one store rather than
  the scene.
- The measured cost of one landing is independent of the declared canvas size.
- The viewer says so when a store's chunking cannot support tiles landing safely.
- `DATA_LAYOUT.md` Decision 2 matches what `stores.py` already does, and the separator
  question has an answer written down.

## Disproved by review, kept so it is not proposed again

- **"Every write creates a chunk file that did not exist, so nothing can be erased."** True
  at level 0 with aligned tiles; false above it, where several tiles share a coarse chunk.
  Safe under a single serial writer, which is why that is now a stated requirement rather
  than a property of the layout.
- **"The announcement channel already carries per-store frame counts."** It does not. The
  announcement payload is empty by design; the count is scanned off the disk.
- **"Live mode refuses to grow the set of stores during a run."** Contradicts Decision 4,
  which lists a new acquisition type appearing as one of the only two things that happen
  during a run; contradicts Decision 5; contradicts the stated purpose of `library.py`; and
  breaks a passing test written so that a new acquisition type needs no code change. It
  also buys nothing — the store count is held down by the writer, not by the viewer
  refusing.
- **"Chunk size, canvas defaults and tile step belong in the profile."** The viewer never
  writes, so none of these are its parameters.
- **"Declaring `t` up front is the change being proposed."** It is what the code already
  does.
