# What is broken, and how we know

Written 2026-07-29, at the end of a session that set out to check whether the tests were
testing what they claimed. They were not, and looking properly turned up fifteen real faults.
This document is the hand-over for that work.

**Read the evidence column before acting on anything here.** Everything marked *measured*
has a reproduction that was run and whose output is quoted. Everything marked *reasoned* is a
hypothesis and should be treated as unproven until somebody runs it — three claims that
looked certain this session dissolved the moment they were measured, including several of
mine.

A note on how these were found, because it decides where to look next. Not one of them was
found by the test suite. They were found by writing a test that had to *look at the picture*,
by attacking a fix on purpose to break it, and by an agent being told to behave like an
operator for an afternoon. The suite was green throughout.

---

## The two rules that came out of this

**A test that asks the engine whether it is happy is not a test.** The recurring fault in
this viewer is a picture that is silently absent: pieces fetched, layers built, the engine
reporting itself perfectly content, and nothing on screen. Waiting on engine state to know
*when* to photograph is right. Using it as the verdict is what let almost everything below
ship. `tests/pixels.py` says this already; the suite did not follow it.

**Prove a test can fail, in the test itself.** The strongest tests written this session hide
or blank the thing under test and assert the measurement falls — `assert blanked < lit / 4`.
That proof re-runs forever, unlike an assurance in a report that nobody reads twice.

---

## Fixed and pushed

On `claude/time-axis-storage-trso2u`, all with tests that fail without the fix.

| | fault | evidence |
| --- | --- | --- |
| 1 | Declaring a run over one already imaged destroyed it and reported success | measured: a tile of 4242 read back as 0 |
| 2 | Bundled pieces lost tiles written at the same moment | measured: `[0,0,0,44]` of `[11,22,33,44]` |
| 3 | A channel given no brightness range got a full 16-bit one, so real data opened almost black | measured: opens at (230,393) not (0,65535) |
| 4 | Re-running into the same folder kept the old, longer frame count | measured: 5 then 2, was 5 then 5 |
| 5 | A gap in the frames hid every frame past it — including an all-black frame, since zarr writes no piece for one | measured: `{0,7}` gave 1; 7 frames with the 4th black gave 3 |
| 6 | Frame counting could not read OME-Zarr 0.5 at all, on three of the four ways version 3 names its pieces | measured: 1000 declared / 3 imaged gave "I cannot say" |
| 7 | The axis-unit repair, which exists for foreign instruments, silently stopped working on version 3 | measured: `um` left unrepaired |
| 8 | The channel count fell back to trusting the description on version 3 | measured: 3 layers for a 2-channel array |
| 9 | The time axis was declared, then reversed to declare up front and fill in | see `DATA_LAYOUT.md` |

---

## Confirmed and unfixed

These are the work. Ordered by how badly each hurts an operator.

### A. An acquisition met before its image is on disk never draws, all session
*measured.* Severe. Realtime.

The library notices a store the instant its description lands, which is the earliest possible
moment and was deliberate. The engine then reads its pieces, finds nothing, and remembers
that with no time limit. When the image arrives, an ordinary `POST /api/announce` — the one
the README documents — does **not** clear that memory, because only `wrote_image_in_place`
does, and a run writing one store per position has no reason to send that flag.

    described, no image yet:            distinct 1, spread 0.0
    image written + plain announce:     distinct 1, spread 0.0     <- still blank
    after wrote_image_in_place:         distinct 2, spread 91.3
    a freshly opened page, same server: distinct 2, spread 91.3     <- the data is fine

Only the open viewer is stuck. The operator sees the acquisition listed, the eye open, and
black where the specimen should be, with nothing saying why.

### B. Brightness never reaches the picture for a single flat-colour layer
*measured, mechanism traced to the line.* Severe. **A regression introduced this session.**

Our flat-colour shader puts all the brightness into **alpha**:
`emitRGBA(vec4(1.0, 1.0, 1.0, normalized()))`. Neuroglancer disables GL blending for the
bottom-most cross-section image layer, so the framebuffer receives `RGB=(1,1,1)` verbatim and
alpha survives only as a binary "is this background?" test. The result is pure white wherever
the layer covers the view, at every setting.

    window (500, 4000)  -> distinct 2, dominant 0.6087, spread 124.4
    window (0, 60000)   -> distinct 2, dominant 0.6087, spread 124.4   identical

Corroborated arithmetically: a strictly two-colour 0/255 image with fraction *p* of one
colour has standard deviation `255·sqrt(p(1-p))`, which for p=0.6087 predicts **124.45**
against **124.45** observed. The picture is exactly {0,255} — no gradient at all.

Introduced by `eb7ffdb`, which moved intensity from RGB into alpha so that unimaged ground
would be transparent and rows could be seen together. That aim is right and must be kept. Its
stated justification — that the engine multiplies colour by alpha before drawing — is false
for the bottom layer. It is true for layers above it and true for the 3-D path, which is why
the volume view and the lookup-table shader are unaffected, and why nobody noticed.

**A fix is in progress**: intensity back into RGB, alpha as a coverage mask. An analysis
recommended `blend = "additive"` instead and I overruled it, because `DATA_LAYOUT.md` records
a measured decision that overlapping tiles are drawn one on top of another and not blended,
"so the picture looks exactly as it would have if a single image had been used". Additive
would sum overlaps into bright seams. Do not ship `vec4(rgb*v, v)` either: neuroglancer's
default blend is straight, not premultiplied, so that form darkens upper layers as `v²`.

### C. A window measured before the coarsest level is written sticks at (0, 1)
*measured.* Severe. Realtime. **Independent of B** — a second cause of the same symptom.

    coarsest level empty   -> window (0.0, 1.0)      histogram bins used 1
    coarsest level written -> window (328.0, 3196.0) histogram bins used 64

`measure()` reads the *coarsest* pyramid level, which is the **last** thing a pyramid writer
writes, so this hits ordinary live runs rather than only an empty store. The guard meant to
prevent it — "only remember the answer if the histogram is not null" — never fires, because
zarr returns missing pieces as the fill value and so produces a perfectly good histogram of
one bar. The answer is then cached for the session: the operator gets `BLACK 0`, `WHITE 1`, a
blank histogram, and an `Auto` button that restores the same nonsense.

### D. Keyboard shortcuts reach past our interface and trap the operator
*measured.* Severe.

`setDefaultInputEventBindings` installs neuroglancer's whole key map. **Space splits the
drawing area into four panels and there is no way back**, because clicking "2D" while already
in 2-D changes no state and so re-runs nothing. It needs no click first — the engine's element
holds focus on load.

    fresh load:      layout "yz",         1 panel
    press space:     layout "4panel-alt", 4 panels
    click 2D:        layout "4panel-alt", 4 panels    <- no way back
    click 3D then 2D: layout "yz",        1 panel     <- the only escape

Siblings: digits `1`–`9` hide a channel while the panel's eye still reads open, leaving the
eye one click out of phase so the operator's first click appears to do nothing; `b`, `a` and
`v` restore the engine's own scale bars, axis lines and bounds box; `s` switches slices off in
3-D; `o` adds an orthographic projection.

This is exactly the trap `engine-chrome.css` was written to prevent. **That stylesheet is
fine** — all three selectors still match in neuroglancer 2.41.2 and the elements are hidden.
The hole is the keyboard.

### E. The guard against overwriting a run is defeated by the acquisition's name
*measured.* Severe. **A hole in a fix committed this session** (`db13b1c`), so the fix must
land on top rather than amend it.

The guard globs on the name without escaping it, so square brackets are read as a character
class and match nothing:

    name 'overview'   second declaration refused        tile safe
    name 'well[A1]'   second declaration ALLOWED   ->   4242 became 0   DESTROYED
    name 'GFP[488]'   second declaration ALLOWED   ->   4242 became 0   DESTROYED

`name` is the acquisition type the caller supplies, so these are names somebody will type.
A name containing `*` is worse in a different way: the *first* declaration dies with a
pathlib error that says nothing about names. **A fix is in progress.**

### F. `fuse()` destroys the run it is about to read
*measured.* Severe. **A fix is in progress.**

`fuse(run, run/"overview.ome.zarr")` opens the target with `mode="w"`, wiping the source it
is reading, then dies with `KeyError: 'multiscales'`. The run is gone and the joined image was
never written. The docstring's "Replaced if it already exists" is thin cover for replacing the
run's own data.

### G. A second acquisition type arriving during a run is silently swallowed
*measured.* Severe. **A fix is in progress.**

Opening a folder holding two acquisition types is refused, deliberately and with a
well-written message. But stores discovered *later* are added with no such check, so:

    at start:                      ['run/Ch488 x1']
    after two more positions:      ['run/Ch488 x3']
    after a target scan lands:     ['run/Ch488 x4']   <- merged

Three overviews at 5×2×2 µm and a target scan at 1×0.3×0.3 µm become one row in one engine
layer. Worse than the documented shared-controls limitation: there is no heading, no row and
no eye for the target scan at all. The operator cannot tell it is open, cannot hide the
overview to look at it, and closing one closes both. Also, opening such a folder at startup
raises the refusal as an uncaught error, so a biologist gets a Python traceback instead of the
message written for them.

### H. Every channel of a multi-channel store shares one window, histogram and Auto
*measured.* High, for Stellaris data.

Brightness is measured per *store*, so a store with a channel axis gets one measurement
computed over all channels and handed to every channel's row. On a store where channel 0
peaks at 1200 and channel 1 at 39800, both rows get 800–33739. The faint channel's whole
useful range sits in the bottom 1.2 % of its window and about one pixel of its slider — the
precise state the slider's own docstring says was fixed. Its histogram is the mixture's, and
`Auto` restores the same wrong answer.

**This must land together with B.** Today both channels draw saturated, which masks it.
Fixing the shader alone will make the faint channel *invisible* rather than merely flat, and
that will look like a new fault caused by a fix.

### I. The scale bar states the wrong size in the 3-D view
*measured.* High — scientific consequence.

    what the bar claims (50 µm over 143 px):  3.50e-7 m per pixel
    what the volume is really drawn at:       1.99e-7 m per pixel

So it reads **50 µm where the truth is 28.5 µm**, over-stating by about 1.76×, by a factor
that also varies with window height. And it does not move: magnifying the volume 20× left the
label identical. `pixelSize()` reads the cross-section zoom; the volume panel is magnified by
a separate perspective zoom which the engine divides by the panel height, and the bar uses
neither. The single-plane view is correct and now tested.

A **strict** xfail asserts the right behaviour, so the suite will fail the moment this is
fixed and the marker must come off.

### J. Two nudges, and two full config rebuilds, per position
*measured.* Medium — cost.

Writing one store produces both the run's announcement and, within a second, the folder
watcher noticing the same write. With a page attached that is two `/api/config` answers per
position, on a question the code's own comment says takes over a second for five thousand
acquisitions. In-place writes into an open store do not double, because they do not move the
revision.

### K. An announcement arriving during a config fetch is dropped
*measured, consequence smaller than it looks.* Medium.

Three announcements during one slow fetch produced one fetch and no catch-up, because the
recovery flag is set *after* the early return. But in live mode the folder watcher re-nudges
within a second for anything that moves the revision, and the fetch in flight reads the disk
at request time, so the answer is current. The genuinely unrecoverable case is a change the
watcher cannot see. Separately, the recovery flag is left set indefinitely and is then
consumed by an unrelated change.

### L. The viewer cannot be started twice, and there is no `--port`
*measured.* Medium.

A port already in use raises an uncaught `OSError` with no advice, and `run_demo.py` exposes
no way to choose another — so on a lab PC where 8848 is taken the viewer cannot be started at
all. `launcher.open_window` also documents a `watch` parameter it does not have, and builds
its URL from the port *argument* rather than the server's real address, so `port=0` yields
`http://127.0.0.1:0`.

### M. Limitations in the frame counting that are not written down
*measured.* Low, but they will surprise somebody.

The answer is not bounded by the declared length: a stray folder `9999` in a store declaring
ten moments gives 10000. Safety comes entirely from the slider clamping in `AxisSlider.jsx`.
An empty leftover frame folder counts as reach. And freshness is equality on the folder's
modification time, so a folder replaced by a shorter one with an identical timestamp — `cp -a`
from an archive — keeps the old, longer answer.

### N. Writer limitations found by attacking the fixes
*measured.* Medium. **Fixes in progress.**

Two processes declaring the same folder before the first tile lands are both accepted and then
lose voxels, 10 times out of 10 — the simultaneous version of the case the guard was written
for. `discard_existing_run` leaves orphan images still holding the old run's pixels, which the
viewer shows mixed into the new run and which then block later declarations. The concurrency
grain is read from the first image only, so a hand-built run whose second image keeps a whole
plane in one file loses tiles. And the grain across resolutions is a maximum where it needs to
be a common multiple — *not* reachable through `create()` today, brute-forced across
everything it can produce, so the shipped writer is safe and only the comment's claimed
generality is wrong.

### O. Documentation describing a design that was replaced
*measured.* Low, actively misleading. **A fix is in progress.**

`README.md` and `stores.py` still describe grouping by filename, which was replaced by
one-load-one-dataset — and a folder shaped the way they describe is now refused.

---

## The test suite itself

Two tests **cannot fail at what they claim**, both verified:

- `test_open_and_close.py` `test_finished_data_opens_no_listening_connection` installs a
  request listener, collects every `/api/events` request into a list, and then never asserts
  on it. A viewer holding a connection open forever on finished data passes. Its live
  counterpart does assert, so this is a lost assertion rather than a choice.
- `test_gpu_realdata.py` `test_webgl_is_hardware_accelerated` skips when the renderer is
  falsy and then asserts the renderer is truthy. It can only skip or pass — while
  `TESTING.md` advertises it as the clearest single check that the GPU is in use.

Gaps that matter more than the weak tests:

- **Nothing asserted that a tile is drawn where its translation says.** The only assertion
  touching `translation` checks the transform exists *in the file*. If the viewer stacked
  every position at the origin, or swapped two axes, the suite passed. Placement was since
  measured to *work*; it was simply unguarded. A test is being written.
- **No test of drawing cost at all.** The regression `NEXT_STEPS.md` calls decisive — a
  thousand positions managing 24 frames in five seconds against 302 for a hundred — would go
  unnoticed. Every performance figure in that document comes from `measure_*.py` scripts that
  nothing runs.
- **The silent-position-loss threshold is ~680 and the test guarding it runs at 40**, with the
  production batch size overridden. Raising the real value back to something unsafe would not
  fail anything.
- **0.5 and on-the-fly are never tested together.** Every live test is version 2; the only
  version 3 browser test runs against finished data. They cannot meet until the writer can
  produce 0.5.
- **Nothing tests the desktop shell**, and nothing tests that the engine's own interface stays
  switched off (see D).
- **Without Chromium, 124 tests — a third of the suite, including every test that looks at a
  picture — skip, and the run still reports green.** CI now installs a browser and fails on an
  unbuilt page, but nothing fails when the pixel tests simply do not run.

---

## Do not chase these — they were suspected and cleared

Each cost real time to check, so the next session should not spend it again.

- **`engine-chrome.css` is not stale.** All three selectors still match in neuroglancer
  2.41.2 and the elements are hidden in both views. `.maximize-button` matches nothing only
  because a single-panel layout has no maximize button.
- **Opacity, colour and lookup tables all reach the engine and the picture.** An initial
  "opacity does nothing" was the test harness failing React's value tracker, not a defect.
- **`letGoOfDecodedPieces` firing unconditionally does not stop the picture filling in.**
  Eight tiles at 200 ms apart went 0.000 → 0.250 → 0.496 → 0.746 → 0.992, and still reached
  0.992 with no gap at all. Its docstring claims a narrower rule than the code implements,
  which is worth correcting, but the behaviour is sound.
- **The mesoSPIM shape is handled well**: six sibling per-tile-per-channel stores, no `omero`,
  no channel axis, two correct rows, and the translations honoured with tiles placed side by
  side.
- **The 2-D/3-D round trip loses nothing**, and odd folders — empty, non-zarr, a plain file, a
  missing path, a half-written store — are all answered plainly.
- **An invlerp with no range does not default to (0,1) on integer data.** It defaults to the
  type's full range. That hypothesis was mine and it was wrong; see B for what is actually
  happening.

---

## Judgements made this session, so they can be argued with

- **Frame counting reports how far the images reach, not how many moments were written.**
  Where a moment in the middle holds nothing, the empty ones between are offered and draw
  empty. Stopping at a count would put readable data out of reach silently, which is worse. In
  a live run, where moments arrive in order, the two are the same thing.
- **A timelapse declares its length up front and fills it in**, reversing an earlier decision
  in the same session. `DATA_LAYOUT.md` keeps both the original reasoning and the reversal.
- **Sharding stays out of the writer** until the exclusivity unit is right, because unsharded
  is verified correct and sharded silently loses tiles.
- **Intensity goes back into RGB rather than making layers additive** (see B).
- **The viewer's server is honestly not an installable package.** It is loose modules reached
  through the import path, and `pyproject.toml` says so rather than implying otherwise.
