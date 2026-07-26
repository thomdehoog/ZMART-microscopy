# What to do next

A hand-over list, in the order worth doing it. Each item says what the problem is, what
is already known about it, and how you would know it was finished.

The design decisions behind all of this are in `DATA_LAYOUT.md`, which was brought into
line with the code and should be trusted. Everything described below is *not* done.

---

## 1. Find out why the slice view draws only its own background

**This is first, and it is not a storage question.** Everything else assumes the viewer
puts pixels on screen, and right now there is evidence it does not.

What is known:

- The image panel reads a uniform mid-grey — a single value, no variation at all.
- That value is `128`, and Neuroglancer's default cross-section background is
  `0.5, 0.5, 0.5`. So the engine is drawing *its own background* and nothing on top of it.
- The 3-D view reads uniform `0`, which is likewise its own background.
- Image data does reach the graphics card: the acceptance test waits for
  `numVisibleChunksAvailable` to rise and it does. So this is not a loading failure.
- The same result appears on the code as it was before this session's changes, so it is
  not a regression introduced by the layer-sync rewrite.

Suspects, in the order I would check them:

1. **`localPosition`.** Each panel row pins itself to one channel by setting the layer's
   local position. If that lands wrongly, a layer loads its data and draws nothing —
   which is exactly the symptom. This is the one thing we do that could cause it.
2. **The contrast window.** If it maps every value to zero, the picture is black — but
   the background is grey, so this fits less well.
3. **The slice plane sitting outside the data** in z.
4. **Layer visibility** — cheap to rule out, so rule it out first.

Useful to know: the canvas *can* be read in a headless browser here. I wrongly concluded
for a while that it could not, and lost time to it. Take a screenshot, or read pixels
inside `viewer.display.updateFinished`; both work. A uniform reading is a real finding,
not a capture failure.

Finished when: the panel shows structure, and a test asserts the canvas is not uniformly
one colour (see item 2).

---

## 2. Make the test suite able to see a blank screen

Nothing in 300 tests checks that a pixel was ever drawn. This is why item 1 is an open
question rather than something the suite caught.

- `test_render_acceptance.py` asserts `numVisibleChunksAvailable > 0` — but its own
  fixture already waited for that condition, so the assertion cannot fail.
- `backend/browsercheck.py` writes `render.png` and never looks at it. A screenshot of
  flat grey passes with `RESULT: PASS`.

Do: screenshot the image area and assert the pixel values are not all one value. Two
lines in each place.

While there, a review found roughly twenty other assertions that cannot fail. The three
worst, each of which passes with its feature deleted:

- `test_masks_luts_and_refresh.py::test_it_can_be_put_back_to_a_flat_colour` — no
  assertion at all, and it waits for the *absence* of a colour map, which is the state
  it starts in.
- `test_open_and_close.py::test_the_selection_list_is_absent_unless_asked_for` — two
  `count() == 0` checks and no positive control; passes against a blank page.
- `test_under_stress.py::test_nothing_outside_an_open_folder_is_reachable` — eight cases
  that all pass if the path guard returns `None` unconditionally. Needs one assertion
  that a *legitimate* path resolves.

The pattern to apply: pair every "nothing happened" with proof the action landed.

---

## 3. Add a channel from the server to the page, then delete the polling

The viewer currently learns about new data by reading modification times several times a
second. That is the wrong mechanism — a timestamp cannot say "finished writing", and
inferring it has already given a wrong answer twice, once badly enough that a new
acquisition would have stayed invisible for a whole session.

The control application knows: it called for the acquisition and waited for the write.
It should say so, with two messages:

- **"this position is ready"** → the viewer hands the engine one more address.
  `POST /api/stores/open` already accepts this and is tested.
- **"this position now has *n* frames"** → the viewer re-reads that store's description
  so the time slider reaches the new frame.

What is missing is the path *back* to an already-open page. Server-sent events fit: the
page holds one connection, the server writes a line, the page acts on it.

**Order matters.** Build the channel first. Removing the polling first was tried in this
session and reverted: the announcement reaches the server and stops there, so the viewer
hears nothing. The tests showed it immediately.

Announcements arrive at the rate acquisitions finish — a handful a minute at most — so
this is small and quiet, and does no work when nothing is happening.

Finished when: an acquisition script can announce a position and a new frame, an open page
reflects both, and `/api/revision` together with `Library.revision()` and the folder
watching are deleted.

---

## 4. Hand the engine only the sources it needs

A row currently takes every position of its acquisition type at once. Each source is
resolved when it is added — roughly four small metadata requests — through a browser that
allows six connections at a time. At a few hundred positions that is fine. At several
thousand it is thousands of round trips before the first pixel.

It is cached afterwards, and during a live run the positions arrive one at a time, so the
cost is spread and invisible. The case that hurts is opening a large finished folder cold.

Two answers, and they are complementary: add sources for what is in view and extend as the
operator navigates; and prefer a stitched image for finished data, which is one source
instead of thousands.

Worth measuring before building either: time to first pixel with a few thousand sources on
one layer. Synthetic sparse stores cost almost nothing on disk, so this is a cheap
experiment. I measured our own code paths to five thousand and made them linear; the
engine side at that scale is unmeasured.

---

## 5. Smaller things worth doing

- **Set the cross-section background to black.** One line
  (`viewer.crossSectionBackgroundColor`). Do it *after* item 1 — the grey is currently the
  only signal that nothing is being drawn, and black would hide it.
- **Move `build_config` out of `server.py`.** It is about 120 lines of domain reasoning —
  how stores become rows, how positions merge, how masks become their own kind — inside a
  closure in the HTTP module, reachable only over HTTP. A `layers.py` taking a `Library`
  would make it testable without a server. Two independent reviews raised it; a real bug
  (two runs silently drawn into one row) lived there unseen.
- **Delete `test_real_mesospim_data.py`, or make it reachable.** It is gated on one
  absolute path on one acquisition PC, including a transfer timestamp, so it skips
  everywhere and always will.
- **`--dist loadfile`** in `run_tests.py`. With `-n 3` the default splits per test, so
  module-scoped fixtures are rebuilt on every worker. One line, tens of seconds.

---

## Where things stand

Branch `claude/napaly-neuroglancer-progress-jo0b8h`. 300 tests pass, 8 skip, about five
minutes with `-n 3`. Nothing uncommitted.

Two things are decided but unbuilt, and both are noted in `DATA_LAYOUT.md`: **who writes
the OME-Zarr** (the mesoSPIM writes its own; our driver copies frame files and does not
touch zarr, so a writer is either a conversion step or a change to what the driver
writes), and **where a measurement belongs** — a table of intensities per object is
neither pixels nor geometry, and will come up the first time somebody classifies pixels.

One caution about the documentation. Twice in this session I wrote a conclusion into
`DATA_LAYOUT.md` before it was built, and both times it read as done: option B was in the
writer contract while Decision 2 still said the opposite, and the polling was described as
removed after the removal had been reverted. Both are fixed and the document now matches
the code. If you change behaviour, check the document says so — and if it already says so,
check the code agrees.
