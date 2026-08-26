# One canvas for the operator page

**Status:** proposed, not started. 2026-08-26.

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
operator page have never appeared at all: `renderStageLayerControls` writes
into `#stage-layers`, and no markup has ever created that element.

It also puts the acquired overview where it belongs. `putTheCanvasIn` draws a
picture *beneath* the layers from a real run, which is exactly what
`watching-the-run.js` does by hand today with the same `jpeg-under` engine.

## The one real gap

The viewer routes **touches**, not **drags**. `reaches(at)` asks a layer
whether a point is inside it and `onTouched` reports the click; there is no
way for a layer to claim a press and then receive the moves and the release.

The operator page needs that. Drawing a region, dragging a position from well
to well, marqueeing focus points and dragging one of them are all press-move-
release, and today `stage.js` serves them by asking the editor first, then the
focus map, then panning with whatever neither wanted.

So the contract has to grow one step, from *who is under this point* to *who
wants this gesture*:

    claims: {
      down(at, e) -> boolean,   // true = mine, the picture must not pan
      move(at, e),
      up(at, e),
      cursor() -> string,
    }

asked in stack order, top layer first, and the picture pans only with what none
of them claimed. That is what `stage.js` already does; the change is that the
viewer runs the chain instead, so any workflow's layers get it.

## Order of work

1. Grow the viewer's gesture contract to claims, with tests in
   `canvas-layers.spec.js` — a layer that claims a drag, and a press it turns
   down that pans instead.
2. Turn `theStageLayers` into `layersAbove` entries: `paint({context, project,
   zoom})` instead of closing over `place` and `view.scale`, `reaches`/`claims`
   instead of the hand-rolled chain.
3. The canvas panel opens `putTheCanvasIn` and hands the layers in. Fit, the
   readout and the scale bar move to the viewer, which is where a statement
   about the projection belongs.
4. Delete the duplicate: `stage.js` keeps the run's layers and nothing else.
5. The layers move out to the steps that own them — the carrier to step 2, the
   plan to step 3, the focus map to step 4 — which is what makes a step's
   layers arrive and leave with the step.

Steps 1–4 are the convergence. Step 5 is the payoff and can follow separately.

## Risks

- **The engines.** `putTheCanvasIn` carries the engine chooser and the
  neuroglancer/viv/jpeg machinery. The operator page wants one engine and no
  chooser. Passing `chooser` an element nothing shows is the cheap answer; the
  honest one is a flag, decided when the code is in front of us.
- **The scale bar and the readout** are the operator page's, not the
  demonstration page's. They have to survive the move without the
  demonstration page growing furniture it does not want.
- **`whereTheStageIs` prefers the plan's last tile over the reading from
  `get_xyz`** once tiles have been taken. That is a known step-1 gap and it
  travels with the stage-mark layer; it should be fixed where the reader is,
  not in the layer.
