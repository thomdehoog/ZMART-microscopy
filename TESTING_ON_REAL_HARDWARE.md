# Testing the viewer in the operator window, on real data

Written 3 August 2026, for picking this up on the microscope computer. Everything
until now has been measured on a machine with no graphics card, drawing pretend
runs. This is the step where that stops.

The viewer is meant to be a **module of the operator window**, not a program of
its own, so it is tested there. That is what this branch is arranged for.

---

## Where to start

Check out **`claude/one-checkout`**. It holds the viewer, the writer and the
operator page in one tree, with one copy of each drawing engine.

### 1. Start the operator page

```bash
cd workflows/target_acquisition/webapp-ui
npm install
npm run dev          # http://127.0.0.1:5174
```

On the microscope computer, Node lives inside the project's conda environment
rather than on the system path, and everything has to stay under
`C:\ProgramData\MinicondaZMB\` because the machine refuses to run programs from
folders a user can write to. The exact paths are in that folder's `README.md`.

**Two environments, and they are not interchangeable.** `zmart-microscopy` has
Node and pywebview; `zmart-viz` has zarr and Playwright. Nothing has all four, so
`npm` comes from the first and every Python command below from the second. This
is not tidiness: the writer that produces a demo run needs zarr, and asked to run
from `zmart-microscopy` it fails with `No module named 'zarr'` — which, reached
through the browser suite, appears as every test timing out in `beforeAll` with
nothing said about zarr at all.

Three variables, for the same reason:

* `PYTHON` → `zmart-viz`'s interpreter. The browser suite spawns
  `process.env.PYTHON ?? "python"` to write its demo run, and plain `python` here
  is the wrong one.
* `PLAYWRIGHT_BROWSERS_PATH` → `C:\ProgramData\MinicondaZMB\home\t.de\ms-playwright`.
  Chromium downloaded anywhere a user can write to is refused at launch with
  `spawn UNKNOWN`. The webapp's config defaults this; `viz_studio`'s does not.
* `ZMART_REQUIRE_BROWSER=1`. Without it, a missing build makes the tests that
  photograph the screen **skip**, and a skip reads as a pass. This machine is
  supposed to be able to draw, so make it fail instead.

### 2. Serve one of your own acquisitions

```bash
python workflows/target_acquisition/serve_a_run.py /path/to/my_run.ome.zarr
```

It prints the whole page address with the run already filled in — copy that into
the browser.

A run cannot simply be opened from the disk, and it is worth knowing why so the
failure is not mistaken for something being broken: a page opened straight off
the disk is given no identity by the browser, and a browser will not let a page
without an identity read files. So the run is handed out over a local address
instead. Nothing leaves your machine.

### 3. Find the viewer

**Canvas demonstration** in the chooser at the top left, then **Viewer
comparison**. One step, holding a column per drawing engine — `viv-under` and
`neuroglancer-under` — both drawing the same run side by side, each with its own
view and its own buttons for the three layers: the drawing beneath the picture,
the picture itself, and the drawing above it.

They open looking at the same place. The engines do not agree about where to
open on their own — Viv fits the acquisition to its box, neuroglancer starts at
one voxel to the screen pixel, which on a 1.1 µm store is twenty times closer —
so the page puts them both on the first view either of them reports. After that
each is panned on its own; they are not locked together.

This was two steps, one per engine, and before that one step with a row of
buttons that swapped the engine in place. Both asked you to remember what the
last engine looked like. There was also a third engine here, `viv-inside`, which
drew the operator's layer inside the engine as a texture so that every change to
it cost an engine frame; it is out of the page and still in
`viz_studio/options/`.

---

## What to find out, in order

Write down what is actually seen rather than what was expected. Most of the
faults this project has met looked perfectly healthy from the inside.

### 1. Does it draw, and is it the right way round?

Point it at something whose orientation you already know — a corner of the
carrier, a marked well, anything asymmetric.

This matters more than it sounds. **A left-right mirror shipped undetected for
months.** The obvious test cannot find it: dragging the picture and watching
which way it moves gives the same answer either way round, because an engine
pans using the same axis mapping it draws with. Only something asymmetric inside
the specimen can say which way round the picture is.

### 2. Does a multi-colour run show all of its colours?

Each channel should arrive in the colour the run itself names, over the
brightness range the run names, without the page being told anything. A run of
several colours showing only its first colour is a fault that was live here
until recently.

### 3. Do two acquisitions land in the right place relative to each other?

Open a canvas holding two, and check the second against the stage coordinates you
know. Two of the three engines once placed a second acquisition **898 µm** from
where it belonged. That is fixed, but it has never been checked against a real
stage.

### 4. How fast is it on a real graphics card, and on a network drive?

**Every timing number in this repository came from a software renderer** and
should be re-measured rather than trusted. The one that decides the most:

> On a sparse canvas, three requests in four were spent fetching ground nobody
> had imaged — 250 requests to draw one view, 190 of them for empty room.

That number is what decides whether a store on a shared drive is comfortable to
work in. Measure it where the store really lives, not on a local disk.

---

## Known, expected, and not worth chasing

- **The layer beneath the picture is invisible under neuroglancer.** Neuroglancer
  forces the whole of its canvas opaque at the end of every frame, so nothing
  placed behind it is ever seen. The page says so on screen when you press the
  button. Anything that has to sit beneath the picture on that engine has to go
  inside it as a layer of its own, which means writing it to the store first.
- **Neuroglancer will not open a canvas with no acquisition at all.** It never
  finishes opening. The page gives up after twenty-five seconds and says what
  happened rather than waiting for ever.
- **Neuroglancer needs the page to be served**, not opened from the disk. Opened
  straight off the disk it is not on offer, so its column falls back to the engine
  that is, and says so in the corner. The heading names whichever engine is
  actually drawing, so two columns showing the same engine on a page opened off
  the disk is that, and not a fault.
- **The two columns are not looking at the same plane of the stack.** `viv-under`
  opens every acquisition at `plane: 0` (`viv-under/viewer.js:873`); neuroglancer
  opens in the middle of the volume. On a light-sheet stack the first plane is
  the edge, so the columns show different pictures of the same store and the left
  one looks empty and out of focus — confirmed by rendering both planes out of
  the file and matching them against the screen. **Do not read the two columns
  against each other for brightness or for sharpness until this is settled**;
  only an engine against itself is a fair comparison today.
- **A foreign store used to be drawn dim, and neuroglancer no longer is.** It
  reads the range out of the picture now — `viz_studio/options/brightness.js`,
  the middle plane of the sharpest copy, first to ninety-ninth percentile — and
  on the transfer below it draws a screen median of 48 where it drew 17 before,
  same engine and same view. `viv-under` does not use that file: it keeps its own
  copy, which reads the *smallest* copy of the image, its *first* plane, and takes
  the smallest and largest value it finds there. All three are wrong in the same
  direction, but what that costs on screen has not been measured on its own,
  because of the plane difference above.

### Found on 4 August, fixed, and worth knowing about

- **Reading the picture was worse than the guess it replaced, in two ways at
  once.** `brightness.js` took the *first* plane of a stack, which on a
  light-sheet tile is its edge — 203 to 503, where the middle plane holds 609 to
  23103 — and it took the smallest and largest value it found rather than
  percentiles, so one saturated pixel at 65535 against tissue at 1750 stretched
  the window elevenfold. The picture came out at a screen median of 12.9 against
  the 108.7 the fixed nought-to-4095 guess gave. Both are fixed and pinned by
  `webapp-ui/tests/unit/brightness.test.js`; measured on the transfer below, the
  neuroglancer column went from a screen median of 17 to 48.
- **The two Viv options still carry the old reading**, in a private copy called
  `theRangeItActuallyHolds`, and it has a third fault besides those two: it reads
  the *smallest* copy of the image, whose values describe the averaging rather
  than the picture. `brightness.js` says on its face that it is shared by every
  option the way `gestures.js` is. It is not yet — only neuroglancer uses it.

### Found on 3 August, fixed, and worth knowing about

- **`viv-under` drew nothing at all on a light-sheet transfer.** It asked for a
  time axis that such a store does not declare, so every piece of image was
  refused — quietly, one refusal at a time, with the page reporting itself
  perfectly content over an empty window.
- **Both Viv engines drew foreign stores at the stage's zero.** They read an
  image's position from the multiscales block only; OME-Zarr also allows it
  beside each resolution, which is where the transfers other instruments send
  put it. A run of many tiles therefore stacked every tile on every other.
- **Serving a run to more than one viewer starved the slowest engine.**
  `serve_a_run.py` answered one request at a time, so neuroglancer never finished
  opening and looked broken. It is threaded now.

Neither of the first two has a regression test. They were confirmed by hand, on
the transfer at `Z:\zmbstaff\10637\Raw_Data\mesoSPIM_transfer_20260626_1700\`,
by watching the refusals stop and the reported centre move to the position the
store states. Treat them as smoke-checked rather than proven.

---

## Still unknown

- **The pywebview desktop shell has never been run on Windows.** Not "probably
  fine" — never run. If it is quick to try, it is worth knowing.
- **How any of this behaves on a real graphics card.** Everything so far has been
  drawn in software.

---

## What was verified before this, and what was not

On the merged branch: the writer's **86 tests pass**, the operator page builds,
its **112 unit tests pass**, and its **38 browser tests pass** — the ones that
photograph the picture rather than asking the engine whether it is content.

The viewer's own suite was still running on the merged tree when this was
written. It reads **557 passed, 10 skipped, 2 xfailed** on the branch this was
merged from, and the merge changed nothing under `viz_studio/`, so it is expected
to hold — but expected is not measured. If it has not been confirmed in the
commit history by the time you read this, run it: `cd viz_studio && python
run_tests.py`, about twenty minutes.

One thing worth knowing about that operator-page browser suite: until 2 August it
had **never actually run in the development container**. It failed outright, all
37 of it, asking for a browser to be installed while a perfectly good one sat in
the same folder. It now finds whatever Chromium the machine has. Any statement
about that page from before then rested on its unit tests alone.

---

## The branches

| branch | what it is |
| --- | --- |
| **`claude/one-checkout`** | **Use this.** Viewer, writer and operator page together. |
| `claude/viewer-only` | What the viewer looked like before the merge. Kept as a fallback. |
| `claude/viewer-as-a-workflow` | The operator page before the merge. Kept as a fallback. |
| `claude/live-tiles-mvp` | Entirely contained in the above. Safe to close. |
| `claude/sandwich-probe` | Holds findings other documents cite. Fold in or close. |
| `claude/layer-stack-probe` | The same. |

The two fallback branches are untouched and can be gone back to. Once real data
has said the merge is sound, they should be retired — keeping them alive is how
the duplication started, and that duplication had already cost two faults fixed
on one branch and left live on the other.

## The decision this merge made

The hand-over said one question had to be answered before anything else was
comfortable: does the operator window come back into this repository, or does the
canvas become a package it depends on from outside?

This merge answers **the first**. The operator window is back in the repository,
and the canvas is a folder in the same tree rather than a copy across a branch.
If real-hardware testing suggests the other answer was better, this is much
cheaper to undo now than after a month of measurements.
