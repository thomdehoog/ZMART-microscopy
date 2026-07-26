# Start here — ZMART visualization work (index)

**If you are an AI agent or a new maintainer picking this up, read this file
first.** It is the map: what exists, why, and which document to open for what.
Read the linked docs in the order below.

## What this is, in one paragraph

ZMART has two operator interfaces. The **target-acquisition webapp** (in
`workflows/target_acquisition/`) is the mature, full working UI — the whole
acquisition flow, driven in a browser or a native window, on a real or simulated
microscope. The **viz-studio viewer** (in `viz_studio/`) is a newer spike: a
React app that embeds the neuroglancer engine to view large, 3-D, multi-channel
images (OME-Zarr), intended to grow into the single image viewer for the whole
workflow. Both run with no microscope (demo mode).

## Read these, in this order

1. **This index** — orientation.
2. **`docs/reviews/2026-07-23-visualization-engine-session.md`** — *what we
   learned and decided, and the reasoning behind it.* The most useful starting
   read: it explains why the engine choice was made, how the render bug was
   found and fixed, and the thought patterns worth reusing. Read this to
   understand the "why".
3. **`viz_studio/README.md`** — what the viewer is and how to run the demo
   (build the frontend, launch the window). Read this to *run* it.
4. **`viz_studio/PLAN.md`** — the viewer's design and the decisions behind every
   part of the stack (neuroglancer, React, OME-Zarr, pywebview, conda). Read
   this to understand the architecture.
5. **`viz_studio/SPIKE_RESULTS.md`** — exactly what the spike proved, the
   worker-bundling bug it found and fixed, and the acceptance check that guards
   against regression. Read this to know what is and isn't verified.
6. **`viz_studio/INTEGRATION_ROADMAP.md`** — the plan to make the viewer the main
   image viewer for the whole workflow: what it replaces, what stays, and the
   incremental path via OME-Zarr. Read this to know where it's going.
7. **`viz_studio/DATA_LAYOUT.md`** — how a smart-microscopy run should be written
   to disk, and why: one OME-Zarr per acquisition type, positions sharing one
   canvas, time declared generously up front. Every cost claim in it was measured,
   and `viz_studio/measure_canvas.py` reproduces those measurements. Read this
   **before changing how acquisitions are saved**, and before adding live
   updating — the decisions there are what make both cheap.

## The two interfaces at a glance

| | Working UI (webapp) | Viewer (viz-studio) |
|---|---|---|
| Where | `workflows/target_acquisition/` | `viz_studio/` |
| What | full acquisition flow (steps, gates, gallery, report) | image/volume viewer (neuroglancer), 3-D capable |
| Maturity | mature, 42 tests, demo-complete | working viewer: renders, full control panel, annotations; not yet wired to the workflow |
| Run (demo, no scope) | `python workflows/target_acquisition/run_webapp.py --demo --window` | `python viz_studio/run_demo.py` (after building the frontend once) |
| Test | `pytest workflows/target_acquisition/tests/test_webapp*.py` | `pytest viz_studio/tests` (166 tests; the browser ones skip unless the frontend is built) |

Both open in a native desktop window via `pywebview` (`pip install pywebview` —
conda-forge does not package it), and both fall back to a browser if it is
missing.

## Current status

- Webapp: mature; next real milestone is hardware-in-the-loop Leica validation.
- Viz-studio: the control panel is **built**. The viewer renders the demo volume
  end to end (acceptance test PASS, 270/270 chunks) and now offers per-channel
  visibility and colour, contrast with a histogram and an auto button, opacity, a
  synchronized Z control, a 2-D/3-D toggle, and a writable annotation layer with
  a targets list that saves beside the data. What remains is the T slider (it
  needs a genuine timelapse OME-Zarr to prove), connecting `/api/goto` to the
  microscope control layer, and then moving the workflow's overview onto
  OME-Zarr/neuroglancer (see the roadmap). Still demo/manual data only: not yet
  wired to the acquisition workflow.
- The native window has now been opened on Windows (2026-07-23) and works. That
  first run found the interaction bug described in `SPIKE_RESULTS.md`: the
  volume rendered but nothing responded to the mouse, because the default input
  bindings were never installed. Fixed, and now covered by
  `viz_studio/tests/test_interaction.py`.

## Branches

There is **one** branch to work from:

- **`claude/napaly-neuroglancer-progress-jo0b8h`** — everything: the webapp, the
  viewer with its full control panel and annotations, all these docs, and `main`
  merged in. Point an agent here.

Several earlier branch names still exist on the remote
(`claude/viz-studio-spike`, `claude/neuroglancer-napari-version-e2707l`, and the
five `codex/zmart-viewer-*` branches). They are not separate pieces of work —
the viewer was built as one straight line of commits, and each of those names is
just a bookmark left at an intermediate step along it. The branch above contains
all of them, so nothing is lost by ignoring or deleting them.

Nothing has been merged to `main` yet; consolidation is a deliberate later step.
