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

It is its own workflow, with **two independent steps** — one opens with Viv, one
with neuroglancer, and neither disturbs the other, so you can look at the same
scene in both. Each has buttons for the three layers: the drawing beneath the
picture, the picture itself, and the drawing above it.

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
  straight off the disk the chooser offers the other two engines and says why.

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
