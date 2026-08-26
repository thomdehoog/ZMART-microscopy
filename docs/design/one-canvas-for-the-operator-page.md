# One canvas for the operator page

**Status: DONE.** All five steps landed 2026-08-26. What changed on the way is
recorded under *What it turned out to be* at the end; step 4 in particular was
not the merge planned here.

## What was asked

> the canvas should be step agnostic, it just provides the option show layers.
> And it should take care the panning and zooming it is done at the same time.
> In layers that are linked. And also it should give you a way to define the
> vertical order of the layer, and how transparancy is used.

> its step agnostic, but belongs to a workflow, not to the framework.

The second half is done: the canvas is declared by the workflow in `flow.js`,
builds its own markup, and the framework knows only that it is a panel that
stays. `index.html` has no canvas in it, and a workflow may have none.

This document is about the first half.

## The finding

**The canvas being described already exists, and is already tested.**
`workflows/target_acquisition/shared/canvas/viewer.js` exports
`putTheCanvasIn`, which takes

    layersAbove: [{ key, label, explains, staysSolid,
                    paint({ context, project, zoom }), reaches(at) }]

and gives back a handle with `setLayersAbove`, `seeThrough`, `lock`, `lookAt`
and `destroy`. It draws the stack bottom-first, gives every layer a chip, fades
the whole stack with one dial, exempts a layer that says `staysSolid`, cuts
see-through windows through every layer at once, and attaches pan and drag to
the picture so all the layers move together. Its own file says, in as many
words, that it is never told which step it is in or which workflow it belongs
to. Eight browser tests in `tests/canvas-layers.spec.js` drive it on a page
built for the purpose and read the pixels back.

The operator page does not use it. `shared/stage.js` is a second, bespoke
implementation of the same idea — its own view, its own stack, its own chip bar
— fused with the target-acquisition run's own drawing. That is the actual
problem: not that the canvas lacks a layer contract, but that there are two
canvases and the operator page is on the one that knows what a carrier is.

## The proposal

The canvas panel opens `putTheCanvasIn`. What the run draws becomes
`layersAbove`, handed in with `setLayersAbove` and changed as steps come and
go. `stage.js` stops being a viewer and becomes the run's layers.

That deletes the duplicate view, the duplicate stack, the duplicate chip bar
and the duplicate fade dial — and it turns on the layer controls, which on the
operator page have never once appeared: `renderStageLayerControls` wrote into
`#stage-layers`, an element no markup ever created, and now takes a `layerBar`
nothing supplies. Dead either way, and dead code that looks alive — the whole
of the chip bar, the fade dial and the lock are written and unreachable.

It also puts the acquired overview where it belongs. `putTheCanvasIn` draws a
picture *beneath* the layers from a real run, which is exactly what
`watching-the-run.js` does by hand today with the same `jpeg-under` engine.

## The one real gap, and how small it turned out to be

`viewer.js` routes **touches**, not **drags**. `reaches(at)` asks a layer
whether a point is inside it and `onTouched` reports the click; there is no way
for a layer to hold a press through the moves and the release. Drawing a region,
dragging a position from well to well, marqueeing focus points and dragging one
of them all need that, and `stage.js` serves them today by asking the editor
first, then the focus map, then panning with whatever neither wanted.

**But the lending mechanism already exists, one level down.** Panning and
zooming are not `viewer.js`'s — they belong to `viz_studio/options/gestures.js`,
shared by all three engines, and the engine contract has carried this since it
was written:

    viewer.handDragsTo(handler)   // hand over a function: dragging stops panning
    viewer.handDragsTo(null)      // hand over nothing: dragging pans again

    handler({ phase, at, screen })   // "started" | "moved" | "finished"

`contract.md` puts it exactly the right way round — *the canvas owns the
mechanics of a gesture, and the application owns what a drag currently means* —
and settles that meaning once, when the drag begins, so one movement of the hand
is never split between two meanings. That is the same rule a claim needs: a
layer takes the whole gesture or none of it.

So two things are missing, not a contract:

1. **A lent drag cannot be declined.** With a handler installed, panning never
   happens, so there is no way to say *nobody wanted this one, pan instead*.
   Letting the handler return `false` at `"started"` fixes it — one change in
   `gestures.js`, which all three engines share, and a line in `contract.md`.
2. **Nothing routes a drag to a layer.** `viewer.js` installs one handler that
   asks the stack top-first and forwards the rest of the drag to whoever took it.

Alt+drag stops being a special case: it is the layers declining while alt is
held. The canvas keeps no rule about it.

## Where the canvas lives

The canvas is a **shared asset**; the layers are **workflow-owned**. `viewer.js`
knows nothing about microscopes — an analysis flow drawing regions over an
image, or a QC flow drawing a plate map, could take it unchanged. The carrier,
the plan, the focus map and the stage mark are target acquisition's and stay in
it.

The tree does not say that yet. Both sit under
`workflows/target_acquisition/shared/canvas/`, where *shared* means shared
between that workflow's steps. A second workflow reaching across into a sibling
workflow's folder would be exactly the wrong dependency — it would quietly make
target acquisition a library.

So a third top-level folder beside `framework/` and `workflows/`, holding the
canvas and anything else a workflow can pick up:

    framework/   the engine. Runs any workflow, knows none.
    parts/       what a workflow is built from. Know nothing about any workflow.
    workflows/   the plug-ins. Pick parts, supply meaning.

The name `parts/` is a proposal, not settled. It has to say what the things are
for; `widget` did not, which is why the step folders stopped using the word.

Moved as part of the convergence, not before: that work already redraws the line
between the viewer and the layers, so the files move once instead of twice.

## What is yours to decide

**Splitting the focus map from the focus points.** Making claim order follow
stack order forces it, and it is the one change here an operator would notice.

The stack is drawn in two passes — the faded layers in list order, then the solid
ones on top. So `staysSolid` and *drawn early* are mutually exclusive: a layer
exempt from the dial floats to the top of the picture.

The focus map wants both. It is drawn early today, below the plan, deliberately —
so the scan fields draw over it rather than the map covering the very fields the
operator is placing points among. And the points on it want to be solid, because
fading the plan to see the picture underneath is not a request to lose the marks
you are placing. It cannot have both, and `stage.js` says so in a comment ending
"splitting the map from the points would buy back both".

Claim order makes it sharper still: a focus point must take a press before the
picture pans, which puts it near the top, while the surface belongs near the
bottom.

So the split stops being optional: the fitted surface goes low and accepts the
dial, the points go high and stay solid. The visible consequence is what happens
when you turn the fade down — the surface fades, the points do not. That is the
right shape, and it is a thing to look at on screen rather than argue here.

## Order of work

1. **DONE.** A lent drag can be declined (`gestures.js`, so all three engines
   have it), alt+drag is never offered, and `viewer.js` routes a drag to the
   stack top-first via `whoClaims` in `layers-above.js`. Three tests in
   `canvas-layers.spec.js`; 11 of 11 there pass. One correction along the way:
   alt+drag is the *canvas's* rule, not a layer declining — an escape hatch each
   layer has to remember to implement is not an escape hatch.
2. **DONE.** Every layer's `paint` works from the frame it is handed rather
   than closing over this file's `place` and `view.scale`, which is what lets
   another canvas draw them. `drawnIn(frame)` names the two coordinate frames
   apart — `place` for the carrier's micrometres, `onTheStage` for the travel's
   — because confusing them draws everything up and to the left, which has
   happened once already.

   `claims` is NOT added here. Nothing consults it until the canvas routes
   gestures, so adding it now would be a contract written and unenforced. It
   lands with step 3, where it is read. `claims` does not replace `reaches`
   either — they answer different questions, and the tests depend on `reaches`.
3. The canvas panel opens `putTheCanvasIn` and hands the layers in. Fit, the
   readout and the scale bar move to the viewer, which is where a statement
   about the projection belongs.
4. Delete the duplicate: `stage.js` keeps the run's layers and nothing else.
5. The layers move out to the steps that own them — the carrier to step 2, the
   plan to step 3, the focus map to step 4 — which is what makes a step's
   layers arrive and leave with the step.

Steps 1–4 are the convergence. Step 5 is the payoff and can follow separately.

**Nothing an operator can do today may stop working.** Drawing a region, closing
a polygon on a double-click, dragging a grid position from well to well and
having it slide into the nearest one, marqueeing focus points, dragging a point,
hovering the stage mark for a readout. These are covered by the browser suite,
which is the check on every step above: 48 of 49 today, the one failure being the
tileset stopwatch flake.

## Risks

Neither of the first two is a decision; they are work to be done carefully.

- **The engine baggage.** `putTheCanvasIn` carries the engine chooser and the
  neuroglancer/viv/jpeg machinery. The operator page wants one engine and no
  chooser. Handing `chooser` an element nothing shows is the cheap answer and
  probably the wrong one; a flag saying the canvas is not offering a choice is
  the honest one. Decided with the code in front of us.
- **Fit, the readout and the scale bar** are the operator page's, not the
  demonstration page's. They belong in the viewer — all three are statements
  about the projection — but they have to move without the demonstration page
  growing furniture it never asked for.
- **`whereTheStageIs` prefers the plan's last tile over the reading from
  `get_xyz`** once tiles have been taken. A known step-1 gap that travels with
  the stage-mark layer. Fix it where the reader is, not in the layer, and not
  in this work.


## What it turned out to be

**Step 1 was already built.** The drag-lending mechanism was in the engine
contract — `handDragsTo`, shared by all three engines, settling what a drag
means once when it begins. Two things were missing, not a contract: a lent drag
could not be *declined*, and nothing routed one to a layer. Alt+drag turned out
to be the canvas's own rule rather than a layer declining, because an escape
hatch each layer must remember to implement is not an escape hatch.

**Step 3 cost more than the plan said**, and every extra was the same shape:
something reaching across the boundary the convergence moved. The readout said
where the view was rather than what was under the pointer; the editor stopped
hearing the pointer move, so a position could not be picked up; the scan beneath
was driven from a pan offset that no longer existed; the canvas painted an
opaque ground over the scan; and a test hid the plan with `canvas.stagecv`,
which stopped matching when the plan stopped being a canvas.

**Step 4 was not the merge described here.** The plan said the acquired overview
should become the canvas's picture. It should not: `overview.js` is a
purpose-built renderer for a live acquisition — gaps drawn as gaps, see-through,
channel mixing — and the generic engine does not replace it. What step 4 came to
was deleting the duplicate viewer, which the convergence had already done.

**Step 5 gave the layers to their steps**, and made `claims` per-layer cheap
enough to finish: the order the editor and the focus map are asked in now falls
out of where they sit in the stack rather than being written in one function.

Two faults found by using it, both breaking rules written here: a canvas with no
run offered buttons for a picture that did not exist, and hiding a layer left
its chrome on screen. A layer may now say what it `follows`.
