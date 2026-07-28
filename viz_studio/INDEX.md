# Start here — ZMART visualization work (index)

**If you are an AI agent or a new maintainer picking this up, read this file
first.** It is the map: what exists, why, and which document to open for what.
Read the linked docs in the order below.

## What this is, in one paragraph

ZMART has two operator interfaces. The **target-acquisition webapp** (in
`workflows/target_acquisition/`) is the mature, full working UI — the whole
acquisition flow, driven in a browser or a native window, on a real or simulated
microscope. The **viz-studio viewer** (in `viz_studio/`) is a working viewer: a
React app that embeds the neuroglancer engine to view large, 3-D, multi-channel
images (OME-Zarr), intended to grow into the single image viewer for the whole
workflow. Both run with no microscope (demo mode).

## Read these, in this order

There are four, and they answer different questions. The list is deliberately
short; the older planning documents are still here and are listed further down as
history, but reading them first would leave you with a picture of the design that
is a few months out of date.

1. **`viz_studio/README.md`** — what the viewer is and how to run the demo (build
   the frontend, launch the window). Read this to *run* it.
2. **`viz_studio/DATA_LAYOUT.md`** — the design record: how a smart-microscopy run
   is written to disk and how the viewer presents it, with the reasoning for each
   decision and what was tried and rejected. One store per position, each carrying
   its own place on the stage; how much to open is the operator's choice; and the
   case to be good at is one image added to over time. Every claim about cost in it
   was measured rather than assumed. **Read this before changing how acquisitions
   are saved.**
3. **`viz_studio/NEXT_STEPS.md`** — what is known to be unfinished or wrong, and
   what to pick up next. Read this before starting work, so you are not solving
   something already understood.
4. **`viz_studio/TESTING.md`** — how to run the tests, and what each group of them
   is actually for.

If you want the reasoning behind the engine choice itself — why neuroglancer, and
how the first render bug was found — that is in
`docs/reviews/2026-07-23-visualization-engine-session.md`.

## Kept as history, not as description

These were written before or during the build and are left in place because the
reasoning in them is worth having. They are **not** descriptions of what exists
now, and each says so at the top. Read them if you want to know how a decision was
reached; do not read them to find out how the viewer works.

| | What it was for | What has since changed |
|---|---|---|
| `PLAN.md` | The plan to review before building the spike: the stack, the risks, the sequence. | The spike was built. The architecture it describes is right; the storage layout it assumes is superseded by `DATA_LAYOUT.md`. |
| `SPIKE_RESULTS.md` | What the spike established, honestly, including the worker-bundling bug. | Still accurate about the spike. The viewer has grown a great deal since. |
| `INTEGRATION_PLAN.md` | The plan for turning the prototype into the real viewer. | Carried out, with the stage-moving part deliberately dropped. |
| `INTEGRATION_ROADMAP.md` | The decision to make this the one image viewer for the whole workflow. | Still the intent. Not yet done. |
| `prototype/` | A single self-contained HTML page demonstrating the interface design. | The real viewer exists and keeps that design. |

## The two interfaces at a glance

| | Working UI (webapp) | Viewer (viz-studio) |
|---|---|---|
| Where | `workflows/target_acquisition/` | `viz_studio/` |
| What | full acquisition flow (steps, gates, gallery, report) | image/volume viewer (neuroglancer), 3-D capable |
| Maturity | mature, 42 tests, demo-complete | working viewer: renders, full control panel, annotations; not yet wired to the workflow |
| Run (demo, no scope) | `python workflows/target_acquisition/run_webapp.py --demo --window` | `python viz_studio/run_demo.py` (after building the frontend once) |
| Test | `pytest workflows/target_acquisition/tests/test_webapp*.py` | `python viz_studio/run_tests.py` — builds the page and runs everything; see `TESTING.md` |

Both open in a native desktop window via `pywebview` (`pip install pywebview` —
conda-forge does not package it), and both fall back to a browser if it is
missing.

## Current status

- Webapp: mature; next real milestone is hardware-in-the-loop Leica validation.
- Viz-studio: the control panel is **built**. The viewer renders the demo volume
  end to end (acceptance test PASS, 270/270 chunks) and offers per-channel
  visibility, colour and colour maps, contrast with a histogram and an auto
  button, opacity per channel and per acquisition type, synchronized Z and T
  controls, a 2-D/3-D toggle, segmentation masks, and a writable annotation layer
  with a targets list that saves beside the data. Acquisitions written while it is
  open are picked up on their own.

  The viewer deliberately does **not** talk to the microscope, and there is no
  `/api/goto`: targets are saved to a file and the control application acts on
  them. That separation is what lets the viewer be opened on any data, anywhere,
  including beside a running experiment. A test asserts that no
  stage-moving endpoint exists, so this cannot drift back.

  A run in progress is followed properly: the application driving the microscope
  says when a position is ready, the page is told over one connection it holds open,
  and only what actually changed is added to the picture rather than the scene being
  rebuilt. Closing an acquisition hands the memory back.

  What remains is moving the workflow's overview onto OME-Zarr/neuroglancer (see
  the roadmap), and writing the OME-Zarr ourselves rather than relying on what the
  mesoSPIM produces. Still demo and manual data only: not yet wired to the
  acquisition workflow. `NEXT_STEPS.md` has the honest list.
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
