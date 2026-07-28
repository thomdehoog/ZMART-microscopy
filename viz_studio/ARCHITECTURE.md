# What the viewer is: a wrapper around an engine

**Status: a statement of the intended architecture, and a record of where the code
currently departs from it.** The departures are listed with what it would take to close
them. Nothing here has been built to this shape yet.

Read `DATA_LAYOUT.md` for how data is stored, `LIVE_MODE_PLAN.md` for the live-mode
proposal that sits on top of this, and `NEXT_STEPS.md` for the honest list of what is
unfinished — with the caveat, below, that several of its remaining items are ruled out by
the rule in section 2.

## 1. The shape

Neuroglancer is the engine and its own interface is switched off:
`NeuroglancerView.jsx:53-55` builds it with `makeMinimalViewer` and
`showUIControls: false`, and `engine-chrome.css` suppresses what remains. Everything an
operator sees is ours — the layer panel, the sliders, the targets list, the scale bar.

One trap comes with that and is worth repeating wherever this is described, because it
costs a day to rediscover: `makeMinimalViewer` builds the engine but installs **no input
bindings**. Without `setDefaultInputEventBindings` the volume renders perfectly and
nothing responds to the mouse. Rendering and navigation are independent, so render tests
cannot catch it; `tests/test_interaction.py` is what holds it.

## 2. The rule: defer everything the engine can do

**The wrapper does only what neuroglancer cannot do, and does not work around what
neuroglancer does badly.**

The second half matters as much as the first. Neuroglancer already handles data of this
size well, and it is the one component we chose not to rewrite; a wrapper that starts
compensating for it acquires the maintenance of both. The rule has a single exception,
and it is not a loophole: **inefficiency of our own making is ours to fix.** Handing the
engine forty thousand sources at once until the browser refuses them is our doing, not
its shortcoming.

Who owns what, as it stands:

| | owner |
|---|---|
| pyramid level selection, chunk fetch and decode | engine |
| the decoded-chunk cache | engine |
| placing tiles beside one another by their `translation` | engine |
| slice and volume rendering, navigation, input bindings | engine |
| which stores exist and which are open | wrapper |
| serving the bytes | wrapper |
| the panel, sliders, colours, annotations | wrapper |
| pacing how fast sources are offered | wrapper (our own inefficiency) |

Two places where the deferral is done well and should be copied rather than disturbed:

- **A channel is one layer with many sources.** The engine composites the tiles; we never
  stitch. Measured live on a real mesoSPIM transfer: seven stores become one group with
  `Ch488` holding five sources and `Ch647` two.
- **Contrast travels as control *values*, not as shader text.** `scene.js:52-60` declares
  the `invlerp` control with no particular value and `shaderControlsFor` sends the numbers
  separately, so dragging a contrast handle does not recompile a program on the graphics
  card.

### Where the rule is broken today: contrast is measured in Python

`contrast.py` reads pixels off the disk to compute a display window and a histogram.
Neuroglancer computes data histograms on the GPU already — it ships
`lib/webgl/empirical_cdf.js`, and `histogramSpecifications` / `dataHistogram` appear in
`sliceview/frontend.js`, `sliceview/volume/image_renderlayer.js` and
`volume_rendering/volume_render_layer.js`, existing precisely to drive the `invlerp`
controls we are already using. Switching off the engine's interface cost us the widget,
not the computation.

Nearly every contrast problem in this repository descends from that one deviation: the
cold open that took ninety minutes and then 126 seconds before being cut to 1.3; a row's
window coming from whichever of its positions sorts first by name; sampling that scales
with the *declared* extent of a store rather than what has been written; and the
degenerate `(0, 1)` window that is cached for the session when a store is met before its
pixels exist.

Deferring it deletes `contrast.py`, its server-side measurement cache and the invalidation
around it, and — because a GPU histogram measures what is actually loaded — it removes the
empty-canvas failure rather than working around it.

**Verify before committing to it:** the engine's histogram covers loaded chunks at the
current resolution, so an automatic window would shift as the operator navigates. That is
arguably the more honest behaviour, but it is a change, and it needs looking at on 16-bit
data where the interesting range is a narrow band well above zero.

### What the rule strikes from the roadmap

Applying section 2 honestly removes several items `NEXT_STEPS.md` still carries:

- **HTTP/2.** It treats a symptom of the engine's fan-out and costs a dependency.
- **The coordinate-space quadratic.** Already correctly declined — halving an 800-position
  open was measured as achievable and rejected because it needs replacing a method on an
  internal neuroglancer object at run time. It stays declined.
- **A parallel brightness pass.** Moot if contrast moves to the engine.
- **The remaining scale audits and the memory-per-folder measurement.** These characterise
  how the engine behaves with many stores. Under this rule that behaviour is the engine's,
  and we neither fix it nor chase it.

What survives is only the pacing, which is ours.

## 3. A dataset is what one load produces

**Loading through the wrapper produces exactly one dataset, however many stores it spans.**
A dataset is one acquisition type or one multitiled run: the stores in it must carry the
**same channels**, because they are the same acquisition. It appears in the panel as a
single named thing — `overview`, say — with one sub-layer per channel.

### Where the code departs

**The dataset boundary is currently inferred from filenames.** `stores.py:122-133` takes
the text before a store's first underscore as its acquisition type, and `group_by_type`
gathers stores by it. So the grouping is a property of a driver's naming convention rather
than of the load: point the viewer at a folder whose stores do not share a prefix and one
load silently becomes several datasets. The mesoSPIM transfer groups correctly only
because all seven stores happen to begin `Mag5_`.

**The same-channels requirement is not checked anywhere.** Stores with mismatched channels
produce extra rows and no complaint.

**A group has no identity.** It is a derived grouping over independent layers — no name of
its own, no channel list, no mode.

### What to build instead

A dataset as a first-class object, created by the load: a name, the channel list it
declares, the stores under it, and whether it is live. Then the panel renders datasets and
their channels rather than deriving both, `split_name`/`group_by_type` go, and the
same-channels rule becomes a validation at open with a reason given when it fails.

That one change satisfies this whole section, and it moves the viewer from *inferring*
what the operator loaded to *being told*.

## 4. Two modes, and they belong to the dataset

**Realtime.** The data is being written. The control application says when something is
ready, the viewer is told over a connection it holds open, and only what changed is added.

**Offline.** The data is finished. Any number of stores; open them, show them, stop asking.
Be efficient, but per section 2 — do not chase the engine's limits, and do not add viewer
machinery to make a large folder feel faster than the engine can draw it.

Mode is a property of a **dataset**, not of the server: an operator may watch a run in
progress while last week's finished run is open beside it for comparison. The per-folder
watch flag in `library.py` already works this way, so the code is closer to this than the
server-level `live=` argument suggests; what is missing is that the mode is not carried by
anything the operator can see or by anything the panel knows about.

## 5. What stays exactly as it is

The server: Python's own `http.server`, no framework, installable from conda with nothing
exotic. The traversal guard, which resolves each request target and refuses anything that
does not land inside an open folder. The separation from the microscope — no `/api/goto`,
targets written to a file for the control application to read, and a test asserting no
stage-moving endpoint exists. The pacing in `engine.js`. And the demonstrated
render-and-navigate tests, which are the only things that catch a viewer that draws
perfectly and ignores the mouse.

## 6. Consequences for the live-mode plan

`LIVE_MODE_PLAN.md` should be rebased on this document rather than read beside it. Two of
its items change character:

- Its first blocking item — auto-contrast poisoning a session on an unwritten canvas — is
  not a live-mode problem. It is a symptom of section 2's violation, and moving contrast to
  the engine removes it wherever it would have appeared.
- Its "one store per acquisition type" becomes a statement about **datasets**, which is
  what section 3 defines. One dataset may be one store or many; what the live case needs is
  that the number is fixed by the experiment, not that it is one.
