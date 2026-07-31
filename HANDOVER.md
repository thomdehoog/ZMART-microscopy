# Where this stands, and what to do next

Written 2026-07-31, at the end of a long session, for whoever picks this up next —
which will probably be the same person, a day later, with none of it in mind.

It says what exists, where it lives, what was decided, what was tried and rejected,
and what to do first. The last part matters most: **the exploring is finished and the
integrating has not started**, and that is the shape of the work ahead.

---

## The honest summary in five lines

A great deal was settled this session, almost all of it by measurement rather than
argument. What was *not* done is put the pieces together. There are now five
branches, three working implementations of the same viewer, an operator window that
lives apart from the canvas it is meant to hold, and several documents that have to
say "see another branch" to be truthful. None of that is broken. All of it is
unfinished in the same way.

---

## What exists, and where

### The writer — `zmart_storage/`, branch `claude/viewer-only`

Turns a microscope's tiles into OME-Zarr. This is the most thoroughly tested thing
in the project: two quality passes, seventy-nine deliberate mutations of the
implementation between them, and every fault they exposed closed.

- **One image per acquisition type.** Tiles butt up against each other and land
  straight into their places. Overlapping runs are refused rather than mangled.
- **A record of where every tile was imaged** (`coverage.py`), written one line per
  tile, appended whole so that two tiles landing at once cannot splice each other.
  Sixteen threads writing together put sixteen whole lines on disk.
- **The pyramid follows the canvas size.** A stage-sized canvas went from three
  smaller copies to eight, and from roughly nineteen thousand requests to open a
  view down to about thirty.

### The existing viewer — `viz_studio/frontend` and `backend`, same branch

The React application with neuroglancer inside it. It works, and this session found
and fixed real faults in it — including one that had been shipping for months.

**Its current commit is not verified.** `483417f` holds a quality pass that was
stopped one step before it ran the suite. An agent is checking it now.

### The canvas — `viz_studio/options/`, same branch

The new thing, and most of this session. **Three implementations of one interface**,
so they can be compared rather than argued about:

| | what it is |
| --- | --- |
| `neuroglancer-under` | neuroglancer in its own canvas, the operator's drawing above it |
| `viv-under` | the same arrangement, Viv and deck.gl below instead |
| `viv-inside` | no sandwich — Viv's layers and ours in one canvas, one pass |

All three take the same drawing functions, honour the same two gestures, speak
micrometres, and are measured by the same suite. The table is in `RESULTS.md`.

### The operator window — branch `claude/live-tiles-mvp`

The step rail, the workflow chooser, the right-hand panel. Built before this session.
**It is not on the viewer branch**, because that branch was deliberately narrowed to
the viewer and the writer, and the workflow code went out with the rest.

### Two measurement rigs — `claude/sandwich-probe`, `claude/layer-stack-probe`

Not products. They answered whether stacked canvases stay locked together, and
whether one layer inside the engine can show through another. Their findings are
written up on those branches.

---

## What was decided, so it is not re-argued

**Neuroglancer**, for what it lets you build rather than what it can hold. Most of
the objections to embedding it dissolved when they were actually tested: the
background colour is a setting, the input bindings are a table you write to, the
keyboard traps were already removed, position and zoom drive from outside, and the
2-D/3-D toggle already exists. Three dimensions comes almost free. Viv stays built
and available, which costs nothing.

**Two gestures in the flat view.** Drag pans, the wheel zooms, nothing else moves the
view. Rotation is removed, because a rotated picture silently stops matching the
drawing over it.

**The layer stack.** Carrier at the bottom, the acquired picture, then a mask, then
the operator's planned tiles, then scribbles. The plan sits *above* the picture,
because photographing it the other way round showed the acquisition covering the tile
outlines exactly when an operator most wants them.

**No overlap, for now.** Overlap is a debt that must be settled by a checkerboard
acquisition or a real stitcher, and neither is here. Tiles step by a whole tile.
**The cost, accepted knowingly:** there is no recorded data with which to correct a
stage that is slightly off, so a seam from stage error is permanent. Overlap comes
back later if the viewer work settles and it turns out to be needed.

---

## What was tried and rejected, with the reason

These are written down because each looks attractive on its own and will be proposed
again otherwise.

**A floor of one in every tile**, so that nought would mean "nobody has been here".
Rejected: on a photon-counting detector zero is a real measurement, and clamping it
fabricates a count that was never recorded — in exactly the low-light work photon
counting exists for. The coverage record answers the same question as a fact, for any
detector, without touching a voxel.

**One bounded layer per imaged region**, so unvisited ground would have nothing drawn
over it. Rejected because a layer cannot be cropped: a bound written onto the output
axes is *accepted and silently ignored*, so it would need one store per region, which
breaks the single sparse canvas everything rests on.

**Shifting the writer's translations by half a voxel** so the picture lands where
neuroglancer expects. Rejected: that is changing the data to suit one reader. The
standard decides; a reader that disagrees compensates in its own adapter, which is
where the compensation already lives. **An investigation into what the standard
actually says is in flight** — see below.

---

## What is in flight as this is written

Three agents, each in its own territory:

1. **Verifying `483417f`** — running the viewer suite that was never run, fixing what
   is red, and re-breaking each of seven fixes to prove their new tests catch them.
2. **Removing stitching** — `fuse.py` and the overlap machinery, keeping the refusal
   of overlapping runs and rewriting its advice. Also writing
   `zmart_storage/VOXEL_PLACEMENT.md`, the investigation above.
3. **A Viewer workflow** — on `claude/viewer-as-a-workflow`, off the operator-window
   branch: one workflow, one step, the canvas and nothing else, so it can be
   exercised inside the real window on its own.

Their results are not in this document. Read their commits.

---

## What to do next, in order

### 1. Settle where things live. This is the one that is costing us.

The repository was narrowed to the viewer and the writer on purpose. The integration
work needs the operator window and the canvas together. **Those two facts
contradict each other**, and the contradiction is already visible in the documents,
which keep having to point at other branches to stay truthful.

Two honest options. Either the operator window comes back into this repository and
the narrowing is partly undone, deliberately; or the canvas becomes something the
operator window depends on from outside — a package, with a version — and the
branches stay apart on purpose. Both are defensible. Drifting between them is not.

Nothing else on this list is comfortable until that is answered.

### 2. Fold the probe branches in or close them.

`claude/sandwich-probe` and `claude/layer-stack-probe` hold findings that other
documents cite. A citation to a branch is a citation with a short life. Bring the
write-ups across, or accept that they are historical and stop citing them.

### 3. Write the runbook.

From a fresh clone to three viewers on your own data: install, build, point it at a
store, which parameter picks which engine, how to make a test acquisition, what to
look at first. About twenty minutes of work, and it is the difference between "it can
be run" and "you can run it".

### 4. Then take it to real data on a real machine.

This is the highest-information action available and nothing substitutes for it.

---

## What has never been done, and will produce the next batch of faults

Everything found this session was found by reading code, breaking it on purpose, and
photographing pixels from stores written for the purpose. That method found about
twenty-five real faults — **none of which any suite had caught** — and it is close to
exhausted. What remains is what the method cannot reach:

- **No real data.** Every measurement used stores a few thousand voxels across.
- **No real graphics card.** Two rows of the comparison table are noise for this
  reason, and one option's cost is probably overstated.
- **No real operator.** Nobody has sat down and used it. The mirrored view survived
  months precisely because it looked fine.
- **No real microscope.** The operator window's mock pretends at the level of whole
  experiments rather than the instrument, so none of the code that will meet hardware
  has ever run. See `docs/design/controller_boundary.md`.
- **Windows.** The desktop shell has never been started.
- **Two acquisitions at once.** All three canvas implementations have code for
  placing one image against another, and nothing anywhere opens two.

---

## Smaller things worth not losing

- **`viz_studio/INDEX.md`** still describes the design as "one store per position",
  which is no longer true and is the file that tells a new maintainer what to read.
- **Registration is measured as unevenness**, which is blind to the two layers
  agreeing about position while disagreeing about magnification.
- **`SLACK_AROUND_THE_IMAGED_GROUND`** is defined in two adapters and the harness
  sizes a measurement against it in prose. Change one and a row silently starts
  measuring something else.
- **The canvas should own its gestures**, with the right-hand panel selecting the
  tool — so a drag draws instead of panning when the operator has chosen a pen. Not
  built; the reasoning is in the session's notes.
