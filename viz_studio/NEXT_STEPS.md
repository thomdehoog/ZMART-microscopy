# What to do next

A hand-over list, in the order worth doing it. Each item says what the problem is, what
is already known about it, and how you would know it was finished.

The design decisions behind all of this are in `DATA_LAYOUT.md`, which has been brought
into line with the code and should be trusted.

---

## Done since the last hand-over

**The scale of the target, measured at last.** Two audits ran against synthetic folders of
up to forty thousand positions. The per-chunk path is flat — 0.21 ms median at forty
thousand, unchanged from a thousand — which is the part that belongs to Neuroglancer and
the part that is fine. Everything expensive is ours. Three costs grew with the square of
the number of positions open; two are fixed (see below), and the third is in `engine.js`
and is not. The worst single figure is the cold open: about ninety minutes at forty
thousand positions, spent reading pixels to judge brightness one store at a time.

**Two quadratics removed.** Looking again at a watched folder checked each image found
against a *list* of images already known, which walks the list — fifteen seconds a look at
forty thousand positions, and it runs whenever anything is announced. Asked of a set now:
four thousand positions take forty-one milliseconds. And the per-position frame counts were
rebuilt into a new list for every position added, the same fault as the addresses beside
them.

**A caution worth carrying.** Fixing the addresses that way first introduced a worse bug:
the row borrowed its list from the remembered measurement of a store rather than owning one,
so extending in place grew the remembered copy a little on every answer. Two pre-existing
tests caught it. The general shape: a shared structure is safe to copy from and unsafe to
extend, and swapping one for the other is exactly where that stops being true.

**The play button on the sliders threw and nobody noticed.** An earlier split moved the
slider into a file of its own and left the constant it needed behind in the shell, so
pressing play raised an error inside the handler and the view sat still. No test pressed it —
they all drive the slider directly. Worth fixing properly: nothing in the suite fails when
the page raises an uncaught error, and a listener for that in `tests/conftest.py` would have
caught this and will catch the next one.


Recorded here rather than deleted, because the *reasons* are worth keeping and because
two of these were long-standing bugs whose shape is easy to reintroduce.

**The slice view drawing only its own background** — solved, and it was none of the four
suspects. The magnification is chosen by the engine the first moment it believes it knows
what space the picture lives in, and it is careful afterwards to preserve the physical
scale when the voxel size changes. We hand it layers before the images have loaded, so
for a moment there are layers and no axes; the engine takes that as settled, has no voxel
size to work from, falls back to one voxel being one metre, and picks its usual default
of one voxel to a pixel — meaning one *metre* to a pixel. The real axes then arrive and it
faithfully keeps that scale. A specimen a tenth of a millimetre across ends up a
ten-thousandth of a pixel wide. The fix waits for the axes and lets the engine choose
again. `localPosition` was innocent.

**A new acquisition going unnoticed for a whole session** — this was still live, and it
happened about two times in five. A folder's modification time moves when something is
*created* inside it, not when a file already there is rewritten; writers (zarr included)
create the description file early and empty and fill it in later, so the folder looked
unchanged at exactly the moment it became readable. Now the description file is looked at
too.

**Tests that can see a blank screen** — `tests/pixels.py` photographs the middle of the
image and measures it, with a companion test that blanks the panel on purpose to prove
the check can fail.

**Caching follows whether the run is finished.** Nothing is kept while the instrument is
writing; finished data is kept for a year. Worth knowing, because it surprised us:
returning to somewhere you have been costs no fetch *either way* — what makes it free is
the engine's own memory of decoded pieces, not the browser's HTTP cache.

**A growing timelapse now reaches the engine.** This was item 1 of the last hand-over
and the only thing standing in the way of a run being watched properly. The cause was
not where the last session was looking. Handing a data source its own address back does
make the engine resolve the store again — that part was right — but the engine keeps its
own memory, inside the page, of everything it has ever worked out about a store, and the
resolving was answered out of that memory. Nothing reached the disk. That memory has no
time limit and no size limit, the engine never releases an entry once made, and no
instruction the server can send in a header can reach it. So the viewer now drops what is
remembered about that one store first, and only then asks. What is dropped is only what
was *read*; the decoded image is kept under a separate arrangement and is left strictly
alone.

Two things came out of it that are worth carrying forward. Dropping that memory makes the
next question genuinely reach the disk, so doing it on every announcement would mean four
small requests per position per announcement — thousands, on a row holding a store for
every place the microscope visited. It is therefore done only for a row whose frame count
has actually moved, and there is a test with a positive control on both halves. And there
is a real cost that Decision 2 in `DATA_LAYOUT.md` had not accounted for: the engine files
decoded image under a key that includes the array's shape, so when the shape genuinely
changes the frame on screen is fetched again. It is bounded and it is once per growth, but
it is not free. `DATA_LAYOUT.md` now says so.

**The channel from server to page** — built, as server-sent events. See below for what
was deliberately not done with it.

Also: the mesoSPIM tests are reachable through `ZMART_MESOSPIM_STORE` instead of naming
one PC's folder; the slice background is black; and `--dist loadfile` keeps whole test
files on one worker.

---

## Start here: six auditors, in parallel

The target is real and it is not met: **forty thousand positions, forty terabytes.** Two
audits at that scale have run and their findings are folded into the items below, but they
covered the backend and the frontend only broadly. Put **six agents** on it at once, each
with a narrow brief, because everything found so far was in a place nobody was looking.

Give each of them the figures already measured, tell them not to re-litigate the decisions
in `DATA_LAYOUT.md`, and require that every finding be **measured rather than reasoned** —
synthetic sparse stores cost almost nothing to fabricate, so an unmeasured claim has no
excuse. Ask for file:line, the growth law, the cost at 1 000 / 10 000 / 40 000 positions, a
concrete fix, and a plain statement of which findings are theoretical rather than reachable.

The briefs, chosen so they do not overlap:

1. **The cold open** — from pointing the viewer at a finished folder to the first pixel.
   This is the worst measured number in the system: roughly ninety minutes at forty thousand
   positions, nearly all of it reading pixels to judge brightness, one store at a time.
   Anything that removes, defers, bounds or parallelises that is the highest-value change
   available anywhere in the project.
2. **The live path** — from a position being written to it appearing. Every cost paid per
   announcement, and whether any of it scales with how much is already open rather than with
   what actually changed.
3. **The engine boundary** — `frontend/src/engine.js` and what it does to Neuroglancer. How
   many sources a layer holds before adding one more becomes slow, and how much of that is
   ours versus the engine's. An earlier audit measured the engine's own fan-out as the wall;
   confirm or refute it, because the answer decides whether item 1 below is optional or
   compulsory.
4. **Memory** — what the server holds after a long run and what the browser tab holds. Four
   caches never evict, and one keys on a folder number that never repeats, so opening and
   reopening leaks outright. Find the real ceiling and say when a machine gives up.
5. **The per-chunk path** — everything between a chunk request arriving and bytes leaving.
   It is the one path measured flat so far, which makes it the one worth defending: find what
   would make it not flat, and what the ceiling is in requests per second.
6. **The interface under load** — what a contrast drag, a group reorder and a mode switch
   cost with forty thousand positions open, and what the panel does per render. An earlier
   audit found sixty-one milliseconds of work per slider event at that scale, on the same
   thread the engine draws with.

A seventh, if there is room: **what a stitched image costs to make and to view**, measured
rather than assumed. Several of the items above are only worth doing if stitching turns out
not to be the better answer for finished data.

---

## 1. Hand the engine only the sources it needs

**Start here, and it is a measurement before it is a change.**

A row currently takes every position of its acquisition type at once. Each source is
resolved when it is added — roughly four small metadata requests — through a browser that
allows six connections at a time. At a few hundred positions that is fine. At several
thousand it is thousands of round trips before the first pixel.

The engine remembers each answer afterwards, and during a live run the positions arrive
one at a time, so the cost is spread and invisible. The case that hurts is opening a large
finished folder cold.

That remembering is the same memory described under the growing-timelapse work above, so
the two items meet here. Anything that makes a store be read again pays this cost afresh
for that store, which is why the re-read is confined to a row whose frame count has
actually moved. If you change how sources are added, keep that confinement — widening it
is the easiest way to turn a few hundred requests into a few thousand without noticing.

Two answers, and they are complementary: add sources for what is in view and extend as
the operator navigates; and prefer a stitched image for finished data, which is one
source instead of thousands.

**Measure before building either.** Time to first pixel with a few thousand sources on
one layer. Synthetic sparse stores cost almost nothing on disk, so this is cheap. Our own
code paths were measured to five thousand and made linear; the engine side at that scale
is still unmeasured, and it would be a shame to build the harder of the two answers and
find the easy one was enough.

Note that `tests/pixels.py` now gives you a way to time *first pixel* rather than first
chunk, which is the number that actually matters here.

### The same cost, arriving a second way: a timelapse across many positions

This has now been measured, and it is the thing standing between the viewer and a run of
the size it is meant for. **Read the numbers before deciding what to build.**

The frame count that decides whether a store is read again belongs to the *row*, and it
is the highest count across all the positions merged into that row (`server.py`, where
the rows are built). That is right for the time slider — it should reach as far as the
position furthest along — but it means one position gaining a frame moves the whole row's
count, and every store on the row is read again, not just the one that grew.

Measured on this machine, with two channels and two pyramid levels per position, on
stores small enough to be sparse. The cost being counted is round trips for the small
files describing each store, and that count follows the number of positions and channels,
not the size of the image — so these figures stand for a 400 GB run just as well as for
the few megabytes actually written.

| positions | opening the folder cold | one frame landing on one position |
| --------- | ----------------------- | --------------------------------- |
| 10        | 0.4 s, 40 requests      | 0.1 s, 60 requests                |
| 50        | 0.7 s, 224 requests     | 0.4 s, 300 requests               |
| 200       | 2.0 s, 572 requests     | 6.2 s, 1 200 requests             |
| 1 000     | 8.7 s, 2 936 requests   | 18.5 s, 6 000 requests            |

The frame-landing column is exact — six requests per position, every time. The cold-open
column wobbles by a few per cent between runs, since what the engine asks for while it is
still working out what it is looking at depends a little on what arrives first.

Read the last row twice. At a thousand positions, **one frame arriving at one position
costs more than opening the whole folder from cold** — and it does so every time any
position advances. A run writing a frame every few seconds would never finish catching up
with itself. This is on localhost, where a round trip is as cheap as it will ever be.

The shape is linear in the number of positions, so a run twice the size costs twice as
much; there is no cliff to be surprised by, and no threshold below which the problem
disappears. At a hundred positions it is barely noticeable, which is why it was not
noticed.

**This is now fixed, and the fix is worth understanding rather than just noting.** The
figures above are what it used to cost. Here is the same table afterwards:

| positions | one frame landing, before | after            |
| --------- | ------------------------- | ---------------- |
| 10        | 0.1 s, 60 requests        | 0.1 s, 6 requests |
| 50        | 0.4 s, 300 requests       | 0.1 s, 6 requests |
| 200       | 6.2 s, 1 200 requests     | 2.4 s, 6 requests |
| 1 000     | 18.5 s, 6 000 requests    | 6.6 s, 6 requests |

Six requests, whatever the size of the run. The cost of noticing a frame no longer has
anything to do with how many positions are open, which is the property that matters — a
run twice the size now costs the same rather than twice as much.

**How, and why it is not the change the previous note proposed.** That note suggested
having the announcement name the stores that had changed. That would have worked, but it
cuts against a decision made deliberately in `announcements.py`: the message says only
*something changed*, and the page then reads the disk, because the disk is what is true
and two descriptions of the world would have to be kept in step. That reasoning is sound
and was worth keeping.

It turned out not to be necessary. The count of frames written is worked out **per store**
already, in the course of building the answer to "what is open" — and was then thrown away,
collapsed into a single figure for the whole row. The row's figure is the highest across
its positions, which is exactly what the time slider needs and exactly no use for deciding
which position moved. So the per-store counts are now kept as well, alongside the list of
stores and in the same order, and the viewer compares each store against what it last saw.
Nothing was added to the announcement; the page still learns everything from the same
read of the disk it was already doing. The information had been there all along.

**One earlier step, kept because the reasoning still applies.** A store holding two
channels feeds two rows, and each row was forgetting and re-reading that store separately,
so the second threw away the files the first had just fetched. Forgetting is now shared
across the whole pass. On its own that took a thousand positions from 8 000 requests to
6 000 — real, and nowhere near enough, which is what sent us looking for the per-store
counts.

**What is left in that 6.6 s**, since it is no longer requests for descriptions: it is the
cost of building the answer to "what is open" for a thousand positions and handing the
resulting scene back through the panel. That is the same cost as opening the folder cold,
and it belongs to this item rather than to the timelapse — see the measurement above.

The measuring script is kept as `measure_many_positions.py`: it writes sparse timelapse
stores at a given number of positions, opens the viewer on them, grows one position by a
frame and counts what that sets off. Every figure in both tables comes from running it.

**Do not reach for a time limit or a size limit on what the engine remembers.** That is
the usual answer to a cache growing stale, and it is the wrong one here: a limit is what
you use when you cannot tell whether something has changed, and we can tell. It would make
the viewer slower and buy nothing. For the same reason there is nothing to tidy up when a
viewer closes — that memory lives in the page and goes when the page goes.

---

## 2. Move `build_config` out of `server.py`

About 120 lines of domain reasoning — how stores become rows, how positions merge, how
masks become their own kind — inside a closure in the HTTP module, reachable only over
HTTP. A `layers.py` taking a `Library` would make it testable without a server.

Two independent reviews raised it, and it has now cost us twice. A real bug once lived
there unseen (two runs silently drawn into one row). And when tracking down the missed
acquisition above, it was the first place suspected purely because nothing could examine
it directly — the fault was actually in `Library.revision()`, and getting there took a
server traced from the inside because neither piece could be questioned on its own.

---

## 3. The rest of the assertions that cannot fail

A review found roughly twenty. Three of the worst were fixed along the way; these remain:

- `test_masks_luts_and_refresh.py::test_it_can_be_put_back_to_a_flat_colour` — no
  assertion at all, and it waits for the *absence* of a colour map, which is the state it
  starts in.
- `test_open_and_close.py::test_the_selection_list_is_absent_unless_asked_for` — two
  `count() == 0` checks and no positive control; passes against a blank page.
- `test_under_stress.py::test_nothing_outside_an_open_folder_is_reachable` — eight cases
  that all pass if the path guard returns `None` unconditionally. Needs one assertion that
  a *legitimate* path resolves.

The pattern to apply: pair every "nothing happened" with proof the action landed. There
are now three worked examples of it in the suite (`test_a_blank_panel_would_be_noticed`,
the revision tests, and the cache tests) if you want the shape.

---

## 4. Smaller things worth doing

- **Consider revalidation instead of no-store for live data.** During a run the browser
  is told to keep nothing, which is simple and certainly correct. A middle course exists:
  let it keep a copy but require it to check, so an unchanged piece comes back as a short
  "still good" with no data. That needs the server to answer conditional requests, which
  it does not today. Only worth it if re-reading during a run ever shows up as a real
  cost — it has not been measured, and on localhost it may never matter.
- **Give the folder watcher a way to be switched off.** It exists as a safety net for
  writers that do not announce (see below). A workflow that *does* announce is paying for
  a directory scan a second for nothing.

---

## A deliberate deviation from the last hand-over

The previous list said to delete `Library.revision()` and the folder watching once the
push channel existed. The channel is built and the page no longer polls — but the
watching was **kept**, moved server-side.

The reasoning: a mesoSPIM writes its own OME-Zarr, and an operator may open the viewer on
a folder being filled by something that has never heard of us. In both cases nothing will
announce, and looking is the only way to notice. Deleting it would have removed the only
mechanism that works without the writer's cooperation — and it would have thrown away the
fix above, which was made in the same session.

What the objection was really about has been addressed: the *page* no longer asks several
times a second. The server looks once on its own behalf, however many windows are open,
and announces through the same channel. On finished data it does not run at all.
`Library.revision()` also still earns its keep as the fingerprint that lets the answer to
"what is open" be reused rather than rebuilt.

If you disagree, the thing to change is `FolderWatcher` in `announcements.py`; nothing
else depends on it.

---

## Where things stand

Branch `claude/napaly-neuroglancer-progress-jo0b8h`. The whole suite passes in about five
minutes with `-n 3` — 327 tests, 8 skipped where there is no GPU or no mesoSPIM data, and
no `xfail` left. Nothing uncommitted.

**How the viewer learns about new data, as it now stands.** There is no browser polling:
`/api/revision` is gone and answers 404, and a test asserts an idle viewer asks for
nothing at all. The page holds a connection open (`/api/events`) and the server speaks
down it when something changes. Two things make it speak: `POST /api/announce`, which is
the control application saying it has finished writing, and — only for live data — a
watcher that looks at the folder itself.

That watcher is the part still under discussion. The argument for keeping it is that the
mesoSPIM writes its own OME-Zarr and will never call our endpoint, so for the instrument
that exists today it is the only path. The argument against, which the operator has made
and which is sound, is that the loop belongs in the script running the acquisition: that
script knows what it wrote, whereas the watcher infers "finished" from modification
times — something a timestamp cannot actually say, and which has already given a wrong
answer twice. If you remove it, remove it *after* checking something announces, and
expect the mesoSPIM path to need the announcement wired into whatever drives it.

Two decisions are made but unbuilt, and both are in `DATA_LAYOUT.md`: **who writes the
OME-Zarr** (the mesoSPIM writes its own; our driver copies frame files and does not touch
zarr, so a writer is either a conversion step or a change to what the driver writes), and
**where a measurement belongs** — a table of intensities per object is neither pixels nor
geometry, and will come up the first time somebody classifies pixels.

One caution about the documentation, carried over from the last hand-over because it is
still the right caution. Twice in that session a conclusion was written into
`DATA_LAYOUT.md` before it was built, and both times it read as done. If you change
behaviour, check the document says so — and if it already says so, check the code agrees.
