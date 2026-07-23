# Session report — the visualization engine, and how we reasoned about it

Date: 2026-07-23. Branches touched: `claude/workflow-safety-features` (the
target-acquisition webapp) and `claude/viz-studio-spike` (a new
neuroglancer-based viewer, which also carries the webapp).

This is written to be *instructive*, not just a log: the decisions matter less
than the reasoning that produced them, because that reasoning is what you reuse
next time.

## What actually happened (the short version)

1. Finished the webapp's discovery UX: folded two Acquire buttons into one that
   mirrors the preview strip, so the button and the preview can never disagree.
2. Held a long design conversation about a new visualization engine — big data,
   3-D, customizable — and converged on a concrete stack.
3. Built that as a spike (`viz_studio/`): a React app embedding neuroglancer,
   reading OME-Zarr from a small Python server, opened in a native window.
4. Hit a "renders grey, no pixels" bug, chased it deep, and — with help from a
   code review — found it was a real, deterministic worker-bundling bug (not the
   "headless quirk" first hypothesised) and fixed it.
5. Made the acceptance test actually assert rendering, did two simplicity
   review passes, added a native-window option to the webapp too, and recorded
   an integration roadmap.

The durable artifacts: `viz_studio/` (working spike + tests), its `PLAN.md`,
`SPIKE_RESULTS.md`, and `INTEGRATION_ROADMAP.md`, plus the webapp's `--window`
launcher.

## Thought processes worth reusing

### 1. Drive every decision from a concrete requirement, not a preference

The engine choice (neuroglancer over viv over napari over neuroglancer-with-
custom-UI) was not made by taste. Each layer was *forced* by a stated need:

- "customizable, my own UI" → rules out configuring a finished app; wants a
  library you build on.
- "active linked plots" → hard in napari's Qt, native in the browser.
- "works from Stellaris to mesoSPIM" → mesoSPIM means large out-of-core 3-D.
- "lightweight, conda, Windows" → prebuilt frontend + pywebview, not Electron.

When a decision has many axes, list the requirements first and let them
eliminate options. The choice falls out; you are not arguing aesthetics.

### 2. Collapse a many-way decision to its single crux

viv vs neuroglancer looked like a broad comparison. It was not. Almost every
axis (UI control, React fit, offline packaging, 2-D scale, OME-Zarr) favoured
viv or tied. Exactly one axis was decisive: **can it rotate a full-resolution
volume larger than GPU memory?** viv cannot; neuroglancer can; mesoSPIM needs
it. The whole decision reduced to that one yes/no. Find the crux and the rest
stops mattering — and say so, so the reader isn't drowned in a balanced-looking
table that hides the one row that decides everything.

### 3. Separate "the thing" from "how it's delivered"

Repeated worry ("will pywebview limit the power?", "is conda a constraint?")
kept conflating the *app* with its *wrapper*. The power lives in the web app;
pywebview/conda/the native window are packaging and change nothing about what
the app can do. Naming that split defused a series of false trade-offs. When
someone fears a packaging choice costs capability, check whether the capability
actually lives in the layer they're worried about.

### 4. Honesty over cheerleading — and let review correct you

When the volume rendered grey, the first hypothesis was "a headless/GPU
quirk that won't happen on real Windows." That was stated *as a hypothesis, not
a fact*, and the honest uncertainty was written into `SPIKE_RESULTS.md`. A code
review then proved it wrong from the built artifact alone: the worker was
neuroglancer's raw source stub, unrunnable on every platform. The lesson is
double-edged:

- Do not dress a hopeful guess as a verified result. The uncertainty label is
  what made the correction cheap.
- A fresh reviewer sees what the author cannot. Two independent reviews in this
  session each found the one thing that mattered (the worker bug; then the test
  that didn't test). Author-blindness is real; budget for review.

### 5. Chase a bug to a *mechanism*, not a plausible story

"Headless quirk" was a plausible story that fit the symptom. It was also wrong.
What settled it was reducing the problem until a mechanism was visible:
metadata loaded but zero pixel chunks were fetched → the frontend computed
visible sources but the worker never did → the worker was a 669-byte stub of
`#src/...` imports a browser can't resolve → it threw on load, never signalled
ready, and the main thread's "wait until ready" queue swallowed everything
silently. A plausible story is not a diagnosis. Keep going until you can point
at the line.

### 6. A test with no teeth is worse than no test

The render acceptance check computed whether the volume loaded and then never
gated on it — it could print PASS on the exact grey-screen bug it existed to
catch. We fixed it to assert pixels actually arrived (chunks available ≥
needed), then *proved it fails* by reproducing the bug (removing the async
worker → FAIL, exit 1). Always verify a test fails when the thing it guards is
broken; a green check that cannot go red is a false sense of safety.

### 7. Simplicity is a maintained property, not a one-time state

Two explicit "no fossils, no wrapper-in-helper-in-wrapper, flat and readable"
passes found real cruft each time: a dead `viewerRef`, a phantom "header"
comment, an `onReady`-only-to-set-a-global prop chain, a scattered dynamic
import, a docstring claiming a fallback the code didn't implement. None were
there when written "carefully"; they accumulate. The higher-leverage fix was
architectural: re-cutting the seam so the viewer component only *mounts* the
engine and the parent owns *what is shown* — which made the fossils fall out and
made the future control panel slot in without a fight. Prefer the structural fix
that prevents the mess over polishing the mess.

## Where this leaves us, and how to move forward

- The webapp (the full working interface) is mature and demo-complete; its next
  real milestone is hardware-in-the-loop validation of the Leica driver.
- The viz-studio viewer is a proven spike: it renders, it's clean, it's tested,
  it opens in a native window. It is *not* a product yet — no control panel,
  demo data only, not wired to the workflow.
- The plan to make it the main viewer is recorded in
  `viz_studio/INTEGRATION_ROADMAP.md`: grow the control panel, move the overview
  to OME-Zarr/neuroglancer first, leave the plots/gates/flow alone, expand to
  3-D once acquisition writes volumes. It is a consolidation project (two
  front-end stacks today), done incrementally, with OME-Zarr as the seam.
- Branch state: both interfaces live on `claude/viz-studio-spike` (one checkout
  runs both). `claude/workflow-safety-features` carries the webapp plus an older
  copy of the viz-studio spike; when we consolidate to `main`, keep only the
  fixed viz-studio and decide the merge target deliberately (nothing has been
  merged to `main` in this session).

The one thing no one has yet seen: the native windows physically opening on
Windows. Everything they wrap is verified; the window itself is the first-look
item on real hardware.
