# What to do next

A hand-over list, in the order worth doing it. Each item says what the problem is, what
is already known about it, and how you would know it was finished.

The design decisions behind all of this are in `DATA_LAYOUT.md`, which has been brought
into line with the code and should be trusted.

---

## Done since the last hand-over

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

**The channel from server to page** — built, as server-sent events. See below for what
was deliberately not done with it.

Also: the mesoSPIM tests are reachable through `ZMART_MESOSPIM_STORE` instead of naming
one PC's folder; the slice background is black; and `--dist loadfile` keeps whole test
files on one worker.

---

## 1. Make a growing timelapse reach the engine

**Start here.** It is the only thing in the way of a run being watched properly, and it
is half built — there is a test waiting for it that will turn green when it works.

### What the problem is

A timelapse grows: the array's length in time is raised by one and the new frame is
written into it (`DATA_LAYOUT.md`, Decision 2). Nothing about the *scene* changes when
that happens — same store, same channels, same everything the panel can show — so the
only way the viewer can find out is to read the store's description again.

The engine will not do that on its own. It read the description when it first resolved
the store, learnt "this image has twelve timepoints", and is holding that answer. Until
something makes it look again, the time slider cannot reach frame thirteen even though
the frame is on disk.

### What is already done

- **The server side is right.** The files describing a store are served `no-cache`
  precisely so a re-read returns the truth, while the image itself is kept for a year
  and marked immutable. A test pins both halves so they cannot drift together.
- **`syncLayers` takes a `reread` option** (`frontend/src/engine.js`). When set, it hands
  every open data source its own address back — `source.spec = { ...source.spec }` —
  which, confirmed by reading `layer_data_source.js`, makes Neuroglancer dispose what it
  worked out and resolve the store again.
- **`App.jsx` sets it** on the pass that follows an announcement, and only then.
- **The pieces of image are not disturbed.** A chunk keeps its own address when an array
  grows, so everything already fetched stays put. That is asserted.

### What is missing

Re-resolving happens, but the coordinate space the time slider reads from still reports
the old length afterwards. So the store is correctly *not* opened a second time, the
layers are correctly left alone — and the new frame is still out of reach.

`tests/test_a_run_arriving.py::test_a_timelapse_that_grows_is_noticed_without_being_added_twice`
is marked `xfail(strict=True)` with that reason. Remove the marker when it passes; strict
means it will fail loudly if it starts passing by accident, which is what you want.

### Where to look

The question is what makes a layer adopt a new extent after its source is re-resolved.
Worth checking, roughly in this order: whether `layer.dataSourcesChanged` needs
dispatching after the spec assignment; whether the layer's own coordinate space is
derived once and cached; and whether `viewer.navigationState.position.coordinateSpace`
recombines only when the *set* of layers changes rather than when one of them changes
shape. `CoordinateSpaceCombiner` is the thing doing the combining.

### One trap, already fallen into

The re-read must happen **as well as** adding new sources, not instead of. An earlier
version treated them as alternatives, and new positions silently stopped appearing —
because one announcement can mean both things at once (a position finished *and* another
gained a frame). `tests/test_a_run_arriving.py::test_a_run_arrives_one_position_at_a_time`
catches that; it failed exactly this way and now passes.

---

## 2. Hand the engine only the sources it needs

**This is now the first item, and it is a measurement before it is a change.**

A row currently takes every position of its acquisition type at once. Each source is
resolved when it is added — roughly four small metadata requests — through a browser that
allows six connections at a time. At a few hundred positions that is fine. At several
thousand it is thousands of round trips before the first pixel.

It is cached afterwards, and during a live run the positions arrive one at a time, so the
cost is spread and invisible. The case that hurts is opening a large finished folder cold.

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

---

## 3. Move `build_config` out of `server.py`

About 120 lines of domain reasoning — how stores become rows, how positions merge, how
masks become their own kind — inside a closure in the HTTP module, reachable only over
HTTP. A `layers.py` taking a `Library` would make it testable without a server.

Two independent reviews raised it, and it has now cost us twice. A real bug once lived
there unseen (two runs silently drawn into one row). And when tracking down the missed
acquisition above, it was the first place suspected purely because nothing could examine
it directly — the fault was actually in `Library.revision()`, and getting there took a
server traced from the inside because neither piece could be questioned on its own.

---

## 4. The rest of the assertions that cannot fail

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

## 5. Smaller things worth doing

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

Branch `claude/napaly-neuroglancer-progress-jo0b8h`. The suite passes in about five
minutes with `-n 3`, with one deliberate `xfail` — item 1 above. Nothing uncommitted.

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
