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

## The two interfaces at a glance

| | Working UI (webapp) | Viewer (viz-studio) |
|---|---|---|
| Where | `workflows/target_acquisition/` | `viz_studio/` |
| What | full acquisition flow (steps, gates, gallery, report) | image/volume viewer (neuroglancer), 3-D capable |
| Maturity | mature, 42 tests, demo-complete | proven spike: renders, tested; no control panel yet |
| Run (demo, no scope) | `python workflows/target_acquisition/run_webapp.py --demo --window` | `python viz_studio/run_demo.py` (after building the frontend once) |
| Test | `pytest workflows/target_acquisition/tests/test_webapp*.py` | `python viz_studio/backend/browsercheck.py` |

Both open in a native desktop window via `pywebview` (`conda install -c
conda-forge pywebview`), and both fall back to a browser if it is missing.

## Current status

- Webapp: mature; next real milestone is hardware-in-the-loop Leica validation.
- Viz-studio: renders the demo volume end to end (acceptance test PASS, 270/270
  chunks), clean and tested; **not yet** a product — no control panel, demo data
  only, not wired to the workflow. Next step is the control panel, then moving
  the workflow's overview onto OME-Zarr/neuroglancer (see the roadmap).
- Not yet seen by anyone: the native windows physically opening on Windows.
  Everything they wrap is verified.

## Branches

- `claude/viz-studio-spike` — the complete, coherent branch: the webapp **and**
  the fixed viz-studio, both native windows, and all these docs. Point an agent
  here.
- `claude/workflow-safety-features` — the webapp's home branch.
- Nothing has been merged to `main` yet; consolidation is a deliberate later
  step.
