# The canvas

The canvas is not the framework's. A workflow declares it in `flow.js`; the
framework builds a box and knows only its name, that it stays once asked for,
and that it has a channel down its side. A workflow that shows no canvas
produces none — there is no canvas markup on the page for one to find.

It is not any one step's either. It appears at the step that first asks for it
— today the first step of all — and stays for the rest of the run, because every
step after that is looking at the same square millimetre of glass and the picture
of it is one picture.

And it is not target acquisition's. Nothing in it knows what a carrier is, or a
tileset, or a focus point — it knows layers, so any workflow could take it: one
drawing regions over an image, one drawing a plate map. It is a **part** a
workflow picks up. What is target acquisition's is the layers it hands in.

## What the canvas does

**It holds one view.** Pan and zoom act on the projection, not on a layer, so
every layer moves together. That is the whole reason the layers are stacked
rather than drawn side by side: they are statements about the same square
millimetre of glass, and they are only comparable if a pan can never take one of
them out of register with another.

**It holds the stack.** Layers are drawn bottom to top, in the order of the list
the workflow hands it, and each can be turned off on its own. Turning the tiles
out of the way is not a request to lose the focus points with them.

**It says how transparency is used.** One dial fades the whole stack, because
"let me see what is underneath" is one thought and should be one movement rather
than a visit to every layer in turn. A layer may declare itself solid and the
dial will not reach it: the crosshair where the stage is standing, the handles
of a shape being drawn, the scale bar. What those have in common is that a
half-visible one is worse than none — you cannot edit what you cannot see, and a
scale bar you can half see through is a scale bar you cannot trust.

The dial is not the only way through. A window can be opened over chosen ground
and it cuts through **every** layer at once, down to whatever is drawn beneath
the stack — which is how an operator watches a scan appear through their own
drawing rather than beside it. Given in the same coordinates the layers are, so
the window travels with the sample when the picture is panned.

**It offers the layers.** Each layer that has something to draw gets a chip on
the picture's own bar: what is drawn and how is the picture's business, so it is
asked on the picture.

## What a layer is

The vocabulary is `viewer.js`'s, because that is the canvas being converged on.
Inventing a second set of names for the same fields would be a third canvas.

    {
      key:        "plan",            // its name in the stack
      label:      "Plan",            // what the chip says
      explains:   "…",               // what the chip's tooltip says
      staysSolid: false,             // true = the fade dial does not reach it
      paint:      ({ context, project, zoom }) => …,
      reaches:    (at) => …,                    // is this point mine? optional
      claims:     { down, move, up, cursor },   // is this gesture mine? optional
    }

**Vertical order is the order of the list.** A step does not number its layer,
because a number is an opinion about layers it cannot see; the workflow hands
the canvas a list and the list is the answer. Bottom first, so the last one in
is the one on top.

**Whether a layer has anything to draw, and whether it reaches the screen, are
two questions and must not be run together.** The first is whether the run has
anything for it — no cells found, no targets imaged — and it decides whether
the layer gets a chip at all. The second is that answer and then whatever the
operator turned off. Conflating them was wrong in both directions: a layer the
operator hid lost its own chip, so there was no way to bring it back, and a
layer with nothing in it still offered a chip that did nothing.

## What a layer answers to

A layer is what it draws **and** what it answers to. Both are about the same
subject, so they arrive together.

    claims: {
      down(at, e) -> boolean,   // true = mine, and the picture must not pan
      move(at, e),
      up(at, e),
      cursor() -> string,
    }

`reaches` and `claims` answer two different questions and a layer may want
either or both. `reaches` is *is this point mine* — enough for a layer that only
wants to be told it was clicked. `claims` is *is this gesture mine* — what a
layer needs to hold a press through the moves and the release, which is what
drawing a shape or dragging a point actually is.

The canvas asks the claimants in stack order, **top layer first**, and pans with
whatever none of them wanted. That is the whole rule. It does not know that one
of them is drawing a rectangle and another is dragging a focus point.

Priority follows what is visually on top, which is what an operator expects: a
press on a shape moves the shape, a press on empty canvas moves the picture, and
neither owner knows the other exists.

Two things stay the canvas's own. **Alt+drag always pans**, so the picture can
still be moved while a drawing tool is armed and wants every press for itself.
And **the lock** stops picking without touching pan or zoom, because locking a
plan you have settled is about not disturbing it, not about not looking at it.

## What a step does

A step contributes layers and takes them away again. It never reaches into the
picture, never repositions it, and never asks what else is on it. Two steps
drawing the same ground draw two layers, and the operator decides which is on
top by turning one off — not by the steps negotiating.

Adding something new later is adding a layer. The canvas does not change.
