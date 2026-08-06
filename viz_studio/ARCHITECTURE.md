# What the viewer is: a wrapper around an engine

**Status: a statement of the intended architecture, and a record of where the code
currently departs from it.** The departures are listed with what it would take to close
them.

When this was written, none of it had been built to this shape. **Section 3 is now the
exception: it has been built, and that section describes the code rather than an
intention.** Everything else still stands as intent.

Read `DATA_LAYOUT.md` for how data is stored, `LIVE_MODE_PLAN.md` for the live-mode
proposal that sits on top of this, and `NEXT_STEPS.md` for the honest list of what is
unfinished — with the caveat, below, that several of its remaining items are ruled out by
the rule in section 2.

Sections 1 to 6 describe the viewer itself. **Section 7 stands back further** and
describes the three layers the whole tool is made of — what the operator sees, what
is on disk, and what sits between them. It is the widest frame and a good place to
start if you are new here.

## 1. The shape

Neuroglancer is the engine and its own interface is switched off: `NeuroglancerView.jsx`
builds it with `makeMinimalViewer` and `showUIControls: false`, and `engine-chrome.css`
suppresses what remains. Everything an operator sees is ours — the layer panel, the
sliders, the targets list, the scale bar.

(Pointers in this document name functions rather than line numbers. Two of them used to
give a line and both had drifted a few lines out of date, which is enough to send a
reader to the wrong place and no way to notice.)

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
- **Contrast travels as control *values*, not as shader text.** `shaderFor` in `scene.js`
  declares the `invlerp` control with no particular value and `shaderControlsFor` sends the
  numbers separately, so dragging a contrast handle does not recompile a program on the
  graphics card.

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

### This is how the code works now

This section used to record three departures, and all three have since been closed. They
are worth stating, because what replaced them is the more interesting half.

**The dataset boundary was inferred from filenames, and no longer is.** The viewer used to
take the text before a store's first underscore as its acquisition type and gather stores
by it, so what appeared on screen came from a driver's naming convention: point the viewer
at a folder whose stores did not share a prefix and one load silently became several
datasets. Both `split_name` and `group_by_type` are gone.

What decides whether two stores belong together is now read from *inside* them: the size of
one voxel, and — where a store names its channels internally — the channel names. See
`_acquisition_of` and `_same_acquisition` in `library.py`. The voxel size is the
magnification the microscope actually used and cannot be anything else, whereas a folder
can be renamed by anybody. So a run may invent a kind of scan nobody has heard of and call
it anything at all, and it is still shown correctly.

**The same-channels requirement is checked, at the door.** `_one_acquisition_only` refuses
a load spanning more than one acquisition and names what it found, listing the stores in
each, so the answer is to open one of them rather than to wonder what happened. That is the
one place the viewer declines to show something it was pointed at, and it is deliberate: a
folder holding two acquisitions is usually a folder chosen one level too high.

**A dataset is a first-class object.** `Dataset` in `library.py` is created by the load and
carries its own number, folder, name, list of stores, channel list, whether it is live, and
what kind of acquisition it is. The panel is given datasets and their channels rather than
deriving both.

One consequence is worth knowing, because it is not obvious from the above. A store that
appears in a watched folder *during* a run is placed by the same comparison, and one that
turns out to be a different acquisition — a target scan landing in the folder an overview is
being written to — is opened as a dataset of its own rather than merged into the row beside
it. Refusing there would be no use: the request that would have carried the refusal finished
long ago, and the target scan is usually the very thing the run was done for. So the two
moments agree on what matters, that two acquisitions are never drawn as one row, and differ
only in whether there is anybody left to tell. `_look_again` and `_place` in `library.py`
set this out in full.

Together these moved the viewer from *inferring* what the operator loaded to *being told*,
which is what this section asked for.

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

## 7. The three layers: the operator, the disk, and what sits between

Sections 1 to 6 are about the viewer. This section is about the whole tool, and it
is the frame the rest of it hangs on.

There are three layers, and it is worth being able to name them:

```
        FRONT                     MIDDLE                      BACK
   Neuroglancer and          backend/server.py           OME-Zarr on disk
   our interface

  +------------------+      +-------------------+      +-------------------+
  |  draws 2D and 3D |      | answers questions |      | tiles, however the|
  |  chooses the     |      | about a picture   |      | microscope wrote  |
  |  zoom level      |      | that need not     |      | them: one image,  |
  |  softens the     |      | exist on disk in  |      | four images, one  |
  |  seams           |      | that shape        |      | per well, nested  |
  +------------------+      +-------------------+      +-------------------+
           |                          |                          |
           |   "the piece at          |   "the part of tile 42   |
           |    z=3, y=7, x=2"        |    that falls in it"     |
           |------------------------->|------------------------->|
           |                          |                          |
           |<-------------------------|<-------------------------|
           |   one piece of picture   |   the bytes on disk      |
           |                          |                          |

   speaks: one ordinary       speaks: both, and           speaks: whatever
   OME-Zarr, one source,      translates between          suits the run
   with a pyramid             them
```

Reading one request end to end: the operator drags the view, so the engine works
out which pieces of picture it is missing and asks for them by position. The
server takes each of those positions, works out which tiles cover that piece of
the specimen and where those tiles are kept, reads them, and hands back one piece.
The engine never learns that tiles were involved.

The whole of this section follows from one thing: the question the front asks and
the question the back answers are allowed to be different questions, because the
middle translates between them.

**The front is the engine and our interface around it.** It draws, it navigates,
and it does the whole of the three-dimensional work. What matters here is that it
is only ever handed **one ordinary OME-Zarr** — one source, with a pyramid.
Everything the viewer's speed depends on follows from that, and section 2's rule
says why we do not try to do its job for it.

**The back is whatever suits the microscope and the experiment.** One large image,
one image per well, one per position, or images nested inside a parent — the choice
belongs to how the run is acquired and how the data will be analysed afterwards,
not to what the viewer would prefer.

**The middle is the server, and its job is to let those two disagree.** It answers
the front's questions about a picture that need not exist on disk in that shape. It
is not a new component: `backend/server.py` is already this layer. Today it passes
files straight through, which is the simplest thing it can do and the right thing
when the store on disk is already the picture the operator wants to see.

### What this buys, and it is the reason to think in these terms

**Where a tile sits on disk and where it belongs on the stage become separate
questions.** That is the whole benefit, and everything else is a consequence:

- The back can change without the front noticing, so a storage layout chosen for
  the microscope does not have to be a layout chosen for drawing.
- A tile's position can be corrected *after* acquisition — once a stitcher has
  worked out where the stage really went — without a byte being rewritten.
- The number of images on disk stops setting the viewer's frame rate, which is
  what `NEXT_STEPS.md` spends its scale audits establishing.

There is one arrangement this makes possible that is otherwise a straight
contradiction: **keeping the overlap between tiles while still showing one
picture**. An image holds a single value per point, so tiles written into one
image overwrite each other where they meet — `DATA_LAYOUT.md` Decision 1b measures
that at a fifth of everything the camera recorded. With a middle layer the tiles
can be kept apart on disk, whole and unspoiled, and put together only on the way
out. `TILES_IN_ONE_STORE.md` measures what that costs.

### Two rules about what belongs where

**The middle places tiles; the front blends them.** Putting a tile in its proper
place is moving whole voxels about, and it is cheap — measured at about six
milliseconds for one piece of picture, and it stays there whether the run holds
sixteen tiles or ten thousand. *Smoothing* the join between two tiles is a
different kind of work: `measure_live_fusion_cost.py` measures a stitching library
doing it live at six hundred to three thousand milliseconds a piece, a hundred times
dearer. So the seam is softened in the shader, where the picture is already being
drawn — `INTEROP.md` §3 sets out the fifteen lines it takes — and never in the
middle.

**The middle only earns its place when the back and the front disagree.** If the
store on disk is already the picture the operator wants — one image, tiles butted
up against each other, no overlap to preserve — the front reads it directly and
the middle has nothing to do. Building a placing layer for a run that does not need
one is work with no reader.

### What this costs, stated plainly

A store whose tiles are laid out for the microscope rather than for looking at is
**only a picture while our software is running**. Handed to a colleague, opened in
napari, or restored from a backup, it is a grid of tiles with no indication that it
was ever anything else.

That is a real price and it should be paid deliberately. `DATA_LAYOUT.md` records a
way of keeping the overlap that does *not* pay it — dealing tiles across four
ordinary images so that neighbours never share one, measured at nothing lost and
sixty draws a second — where the only cost is that a reader opens four images
instead of one. Which of those is right depends on how much the data has to travel,
and it is a decision for the experiment rather than for the viewer.

### Watching a run that is still going

The three layers hold up while data is arriving, which is what a smart-microscopy
run needs. Tiles kept apart on disk never share a piece of a file, so two of them
written at the same moment cannot destroy each other — the hazard `DATA_LAYOUT.md`
measures at up to three quarters of a tile lost. The front already knows how to
notice new data: an announcement carrying `wrote_image_in_place` makes the engine
let go of what it has decoded, and it refetches only what is on screen.

The one job that is genuinely new is keeping the **zoomed-out copies** current as
tiles land. Those copies have to be made once from all the tiles together — made
separately from separate images, every tile edge would be averaged against the
empty ground beside it and the specimen would wear a faint grid. That is design
work rather than a detail, and it is not done.

### Status

The three layers are real; the placing behaviour in the middle is not. The server
passes files through today, and everything above about tiles being kept apart and
assembled on the way out is measured but unbuilt. `TILES_IN_ONE_STORE.md` has the
measurements, and `PLAN_keeping_the_overlap.md` weighs it against the simpler
arrangement this repository had already measured -- dealing tiles across four
ordinary images -- and recommends that instead, for reasons that are about what the
data is worth to somebody else rather than about speed.

---

## 8. Where each file sits, and what it is for

Section 1 gives the shape and section 7 gives the three layers. This is the same
picture at the level of files, for somebody who has just cloned the repository and
wants to know which one to open.

```
                              ┌─────────────────────────────────────┐
   WHAT YOU RUN               │  viz_studio/run_demo.py             │
                              │  launcher.py  — opens a window, or  │
                              │                 prints an address   │
                              └────────────────┬────────────────────┘
                                               │ starts
 ══════════════════════════════════════════════▼══════════════════════════════
   THE FRONT — what you see            viz_studio/frontend/src/
 ══════════════════════════════════════════════════════════════════════════════

     App.jsx ─────────────── holds the whole panel's state
       ├── NeuroglancerView.jsx ── builds the engine (makeMinimalViewer);
       │                            Neuroglancer's own interface is OFF
       ├── LayerPanel.jsx ─────── acquisitions, channels, colour, contrast
       ├── AxisSlider.jsx ─────── depth up the side, time along the bottom
       ├── ScaleBar.jsx ───────── how large the specimen really is
       └── TargetsPanel.jsx ───── places you mark, saved to a file

     scene.js ── panel state  →  plain layer descriptions
                 (no React and no browser in it — the easy part to check)
     engine.js ─ applies those to the engine WITHOUT rebuilding the scene

 ══════════════════════════════════════════════▲══════════════════════════════
                                  HTTP         │  pieces, descriptions, events
 ══════════════════════════════════════════════▼══════════════════════════════
   THE MIDDLE — what answers            viz_studio/backend/
 ══════════════════════════════════════════════════════════════════════════════

     server.py ────── answers every request; guards the opened folder
       ├── stores.py ────── which stores are one acquisition, read from
       │                    inside them rather than from their names
       ├── linking.py ───── "no file here?" → which position's file holds
       │                    those exact bytes.  The view is served here.
       ├── contrast.py ──── without this, real acquisitions draw black
       ├── library.py ───── add last week's run beside today's
       ├── announcements.py ─ tells an open viewer that a position arrived
       └── demo_data.py ─── a pretend specimen, so it runs with no microscope

     browsercheck.py ─ the safety net: serves the page, opens it, reads the
                       pixels that came out

 ══════════════════════════════════════════════▼══════════════════════════════
   THE BACK — what is written            zmart_storage/
 ══════════════════════════════════════════════════════════════════════════════

     positions.py ── writes a run, one position at a time          ┐
     canvas.py ───── the image writer; line 1562 is the shrink     ├ writers
     cropped.py ──── tiles plus a trimmed canvas (the older way)   │
     linked.py ───── builds a view: pointers, and no pixels        ┘
     coverage.py ─── where the run has actually imaged

              writes ↓                          ↑ read by linking.py

     experiment/
       overview.ome.zarr/     the view — a real OME-Zarr image holding no picture
       positions/
         overview_pos00000.ome.zarr    ← all of the data is here
         overview_pos00001.ome.zarr
       zmart-links/           ours, kept outside the images
       zmart-coverage/        ours
```

Three things the drawing is meant to make obvious, each of which is a decision
rather than an accident.

**At the bottom the arrow only goes one way.** `linking.py` reads the positions and
nothing in the viewer writes them. That is what lets the viewer be opened on a run
that is still being acquired, on the machine next to the instrument, without any
possibility of disturbing it.

**There is no line from anything here to the microscope.** Places an operator marks
are saved to a file beside the data, and the control application reads them from
there. A test asserts that no stage-moving endpoint exists, so this cannot drift
back in by accident.

**`scene.js` and `engine.js` are separate on purpose.** One is pure translation —
give it the panel's state and it hands back descriptions of layers, with no React
and no browser involved — and the other holds the fiddly business of applying those
to a live engine without rebuilding the scene. Splitting them is what made the
engine's behaviour something a test can check rather than something you have to
watch.
