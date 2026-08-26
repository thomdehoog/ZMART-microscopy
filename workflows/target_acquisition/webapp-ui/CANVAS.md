# The canvas

The canvas belongs to a workflow, not to the framework and not to any one step.
A workflow declares it in `flow.js`; the framework builds a box and knows only
its name, that it stays once asked for, and that it has a channel down its side.
A workflow that shows no canvas produces none — there is no canvas markup on the
page for one to find.

Within a workflow it is **step-agnostic**. It does not know what a carrier is,
or a tileset, or a focus point. It knows layers.

## What the canvas does

**It holds one view.** Pan and zoom act on the projection, not on a layer, so
every layer moves together. That is the whole reason the layers are stacked
rather than drawn side by side: they are statements about the same square
millimetre of glass, and they are only comparable if a pan can never take one of
them out of register with another.

**It holds the stack.** Layers are drawn bottom to top in the order they declare
— an explicit number, so a step can place its layer among the others without
knowing what the others are.

**It says how transparency is used.** One dial fades the whole stack, because
"let me see what is underneath" is one thought and should be one movement rather
than a visit to every layer in turn. A layer may declare itself solid and the
dial will not reach it: the crosshair where the stage is standing, the handles
of a shape being drawn, the scale bar. What those have in common is that a
half-visible one is worse than none — you cannot edit what you cannot see, and a
scale bar you can half see through is a scale bar you cannot trust.

**It offers the layers.** Each layer that has something to draw gets a chip on
the picture's own bar: what is drawn and how is the picture's business, so it is
asked on the picture.

## What a layer is

    {
      key:      "plan",              // its name in the stack
      label:    "Plan",              // what the chip says
      explains: "…",                 // what the chip's tooltip says
      order:    50,                  // bottom to top; ties keep declaration order
      solid:    false,               // true = the fade dial does not reach it
      has:      () => run.fields.length > 0,   // is there anything to draw?
      draw:     (ctx, projection) => …,        // draw it, in that projection
    }

`has` and what reaches the screen are two different questions and must not be
run together. `has` is whether the run has anything for this layer — no cells
found, no targets imaged — and it decides whether the layer gets a chip at all.
What is shown is that answer and then whatever the operator turned off.
Conflating them was wrong in both directions: a layer the operator hid lost its
own chip, so there was no way to bring it back, and a layer with nothing in it
still offered a chip that did nothing.

## What a step does

A step contributes layers and takes them away again. It never reaches into the
picture, never repositions it, and never asks what else is on it. Two steps
drawing the same ground draw two layers, and the operator decides which is on
top by turning one off — not by the steps negotiating.

Gestures work the same way: the picture asks whoever has claimed presses, in
order, and pans only with what none of them wanted. So a press on a shape drags
the shape and a press on empty canvas moves the picture, without either owner
knowing the other exists.
