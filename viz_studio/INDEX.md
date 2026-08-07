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
short. There are a dozen more documents beside this one, and they are listed
further down under "the rest of the documents"; the older planning documents are
listed after that as history, and reading those first would leave you with a
picture of the design that is a few months out of date.

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
`docs/reviews/2026-07-23-visualization-engine-session.md`, which is **not on this
branch**. It lives on `claude/workflow-safety-features`, commit `209408c`.
`DRAWING_ENGINES.md` beside this file covers the same ground more recently, and
`OPTIONS.md` records the three arrangements that were built and measured since.

## Showing many positions as one picture

This is the largest single piece of work on this branch and it has its own small
shelf of documents. The problem it solves: a plate of thousands of positions is
thousands of separate stores, and a drawing engine that builds layers per store
cannot open that. The answer is to leave the positions exactly where the microscope
wrote them and add a **view** beside them — a complete OME-Zarr image whose pixels
are the positions' own files, so nothing is copied at any zoom.

Read the first one; open the others when you have the question they answer.

| | The question it answers |
|---|---|
| `HANDOVER_a_view_that_writes_nothing.md` | **Start here.** What was built, every measurement out to ten thousand positions, and the two things that still block real data. |
| `PLAN_showing_many_stores_as_one.md` | **The next piece of work**, written out step by step: making a real acquisition open, when a drifting stage puts every position slightly off the grid. |
| `HOW_OURS_DIFFERS_FROM_OME_ZARR.md` | Whether a colleague can open our runs in napari or Fiji. One real divergence, four that only look like one. |
| `LESSONS_ome_zarr_and_neuroglancer.md` | The things that cost us time — each one a mistake actually made here rather than a general warning. Worth reading before writing any OME-Zarr of your own. |
| `PLAN_nothing_copied_at_all.md` | Why a view need not write even the zoomed-out copies, and what the acquisition has to do for that to hold. |
| `OPEN_a_run_that_changes_while_you_watch.md` | An open question: a new position works, but re-imaging one is not noticed by a viewer watching the run. |
| `INTEROP.md` | What happens when other software reads what we write, measured against a real mesoSPIM transfer. |
| `LINKING_INSTEAD_OF_COPYING.md` | How the idea was arrived at, including the claim that was wrong and what it cost. Reasoning rather than description. |
| `HANDOVER_overlapping_runs.md` | The older arrangement that copies, and the measurements behind the decision not to. |
| `WHAT_CAN_BE_SIMPLIFIED.md` | Where the code can get smaller, what was found broken while looking, and — the useful half — what looks like waste and is load-bearing. **Read section 4 before deleting anything.** |
| `TILES_IN_ONE_STORE.md` | The bench measurements of three ways to give the viewer one source without discarding the overlap. |

## The rest of the documents beside this one

The four above are enough to run the viewer and to work on it. These others were
written since, each answering one question in depth, and they are listed here so
that a newcomer can find the right one rather than opening all of them. Read one
when you have the question it answers.

| | The question it answers |
|---|---|
| `WHERE_THINGS_STAND.md` | What was done, measured and decided in the last long session, written for somebody arriving the next morning. **The best single thing to read after the four above.** |
| `FAULTS.md` | What is broken and how we know. Every entry says whether it was measured or only reasoned about, and the measured ones carry the reproduction that was run. |
| `ARCHITECTURE.md` | The shape the viewer is meant to have — a thin wrapper around a drawing engine — and where the code still departs from it. |
| `DRAWING_ENGINES.md` | Which engine draws the picture, and why there may end up being two. |
| `OPTIONS.md` | Three ways of putting acquired image underneath the operator's own drawing, built so they could be compared rather than argued about. |
| `LAYERS.md` | What is drawn on top of what, and where the line falls between the engine's work and ours. |
| `THE_CANVAS.md` | The shape the smart-microscopy front end is meant to take: three layers in one coordinate system. |
| `CONTROLS.md` | How the viewer is driven — every mouse gesture and key, and why each is what it is. Flat view only. |
| `LIVE_MODE_PLAN.md` | A proposal, not yet built, for one store per acquisition type declared at the start. Worth reading for what its reviewers disproved. |
| `HANDOVER_3D.md` | Where three-dimensional navigation got to, and the three commands for getting the volume view up. |
| `PLAN_three_unfinished.md` | Three pieces of work on the `viewer-plus-scanfields` branch, revised through four rounds of review. |

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
| `PLAN_keeping_the_overlap.md` | Two ways of keeping the overlap, weighed against each other after two reviews. | Neither was built. Superseded by the view described above, which keeps the overlap by not showing it. |
| `PLAN_the_pluggable_viewer.md` | A plan for making the drawing engine replaceable, rewritten against two critiques. | The reasoning stands; `ARCHITECTURE.md` and `DRAWING_ENGINES.md` describe where it actually got to. |

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

- **`claude/viewer-only`** — the viewer with its full control panel and
  annotations, the writer in `zmart_storage`, and all these documents. Point an
  agent here for anything to do with looking at images or writing them.

This used to name `claude/napaly-neuroglancer-progress-jo0b8h`, which was the
right answer when it was written and is no longer: `claude/viewer-only` holds
some sixty commits of work on top of it, including the whole of the writer.

The name is meant literally, and it is worth knowing before you go looking for
something. This branch was narrowed to the viewer and the writer on purpose, so
the parts of ZMART that drive the instrument are **not** here:
`zmart_drivers`, `zmart_controller`, `getting_started`, and most of the `docs/`
tree and the `workflows/` folder are all on the older branch and were left
there. The two trees were compared file by file on 2026-07-31, so nothing has
been lost: everything absent here is still on that branch and none of it is the
viewer or the writer. But if a document beside this one points at a path under
`docs/` and you cannot find it, that is why, and
`claude/napaly-neuroglancer-progress-jo0b8h` (commit `810da03`) is where it
still lives.

Several earlier branch names still exist on the remote
(`claude/viz-studio-spike`, `claude/neuroglancer-napari-version-e2707l`, and the
five `codex/zmart-viewer-*` branches). They are not separate pieces of work —
the viewer was built as one straight line of commits, and each of those names is
just a bookmark left at an intermediate step along it. The branch above contains
all of them, so nothing is lost by ignoring or deleting them.

Three branches hold measurements that are referred to from these documents and
that were deliberately not merged, because each is a probe rather than something
to keep: `claude/sandwich-probe` (`SANDWICH.md`),
`claude/layer-stack-probe` (`LAYER_STACK.md`), and
`claude/workflow-safety-features` (the older `docs/` tree, including the
engine-choice session written up on 2026-07-23).

Nothing has been merged to `main` yet; consolidation is a deliberate later step.
