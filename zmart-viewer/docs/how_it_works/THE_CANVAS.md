# The canvas: three layers, one coordinate system

Written 2026-07-31, recording the shape the smart-microscopy front end is meant to
take, and the one measured fact that decides whether it can be built as described.

---

## What it is

A single canvas that is the centrepiece of the smart-microscopy interface — the
window into the microscope and into the data at the same time. Not a viewer bolted
into a page, but the page's main surface, with the workflow's controls beside it.

Three layers, from the bottom up:

| | What lives there | Who owns it |
| --- | --- | --- |
| **bottom** | anything the application wants beneath the picture — the carrier, a patterned background, whatever a workflow needs | the application |
| **middle** | the acquired image | a drawing engine |
| **top** | scribbles, markers, selection, and the tiles the operator drags around | the application |

**All three share one coordinate system and move together.** Pan or zoom, and the
picture, the things beneath it and the things above it stay locked to one another
and to the specimen. That is the whole point: the canvas coordinate system *is* the
store's coordinate system, in micrometres, so nothing has to be lined up by hand and
nothing can drift.

**The middle layer is swappable.** Neuroglancer or Viv sits there behind one
interface, so choosing differently later means replacing one module rather than
unpicking an engine from the whole front end. That interface is
`zmart-viewer/parked/contract.md`, and three implementations of it already exist.

The interface this serves: the viewer on the left, the workflow's own controls on
the right, and nothing else competing for attention.

**The framework now has all three slots**, and it is the same shape whichever
engine is plugged in. An application hands over one drawing function for the
bottom layer and one for the top — `drawUnder(paint)` and `drawOver(paint)`,
written identically — and both are painted from the same view in the same frame
as the picture. An engine that cannot honour the bottom slot says so, as
`viewer.drawsUnder`, rather than faking it; the next section is about which
engine that is and why.

---

## The one thing that stands in the way, and it is measured

**Neuroglancer's canvas is opaque, so nothing can be drawn beneath it.**

This is not a guess. Painting a colour on a surface behind the engine's canvas and
photographing what an operator sees gave **0% of that colour and 97% of the engine's
own background**. Neuroglancer forces the whole canvas's alpha to 1 at the end of
every frame. Viv, measured the same way on the same page, gave **96.95% of the
colour behind it and 0% of its own background** — a deck.gl canvas lets what is
behind it through.

So the bottom layer as described above — the application's own drawing, interactive,
changing while somebody watches — **works with Viv and does not work with
neuroglancer**.

That has since been measured again, from the other end. The framework now has a
bottom slot that an application actually writes against, and a colour drawn *in
that slot* was photographed: 96.95% of the window under both Viv options, 0% under
neuroglancer. Implementing a slot and honouring it are two different things, and
this is the reading that tells them apart. It is `parked/RESULTS.md` measurement 0b.

**This is fine, and it is not something to work around.** The framework is the
same shape whichever engine is plugged in; an engine that cannot honour the bottom
layer says so and the page shows nothing there. What must never be done is to draw
the bottom layer *above* the picture instead, with holes cut in it, so that the two
pages look alike. They would then look identical while doing something entirely
different underneath, and the comparison would stop meaning anything.

### What neuroglancer offers instead, and what it costs

Anything meant to sit beneath the picture has to go *inside* the engine, as an image
or label layer. That does work: two layers inside neuroglancer, the upper one
see-through where nothing was written, showed the lower one through exactly as
intended. It is measured, and the check was shown able to fail.

But a layer inside the engine is read from a store, which means:

- **it has to be written to disk before it can be seen**, and rewritten to change;
- **it cannot change while somebody is watching** — a tile rectangle turning from
  planned to acquiring to done changes every few seconds and must not touch the disk;
- **it cannot be clicked or dragged**, because this viewer switches the engine's own
  interface off on purpose.

A plate outline fixed for a carrier type is perfectly happy under those rules — write
it once, reuse it for every run. A tile the operator is dragging is not.

### So the choice is genuinely between two things

**If the bottom layer must be the application's own — interactive, changing, drawn in
JavaScript — that is an argument for Viv**, and a stronger one than anything in the
comparison table. It is the only measured difference that decides what can be built
rather than how well it performs.

**If the bottom layer only ever holds things that are fixed for the run** — a carrier
outline, a background pattern, a plan saved before the run starts — neuroglancer can
hold them as layers, and everything interactive lives on top where it belongs
anyway.

Worth noting that the layer order already moved for an unrelated reason: the plan was
photographed being covered by the acquisition exactly when an operator most wants to
see it, so the plan now belongs *above* the picture regardless. That takes the most
obviously interactive thing off the bottom layer and weakens the case for needing one.

What is left underneath is the carrier and the background — and those are fixed for
the run.

---

## What is already built

Three implementations of the middle layer, behind one interface, each measured on
the same questions: `zmart-viewer/parked/`, with the table in `parked/RESULTS.md`. All
three hold the same two gestures, the same handedness, the same coordinate system,
and keep pace over hundreds of tiles arriving live.

**The bottom layer is now part of the framework**, and each option honours it as
far as its engine allows and reports what it did. Three things were added, and
they are the whole of it:

1. **A slot in the interface.** `drawUnder(paint)` sits beside `drawOver(paint)`
   and takes the same kind of function, called at the same moment with the same
   view. An application's drawing code for the two layers is identical, and it is
   identical across all three options.
2. **A plain fact the page can ask for.** `viewer.drawsUnder` is `true` where the
   drawing really ends up beneath the picture and `false` where the engine cannot
   allow it, with `viewer.drawsUnderBecause` giving the reason in a sentence. A
   page finds this out without knowing which engine it is talking to.
3. **A measurement.** `parked/RESULTS.md` rows 0b and 1b report, per option and from a
   photograph, whether a colour drawn in the bottom slot is seen at all and
   whether it stays locked to the picture while the view is panned, zoomed and
   thrown about.

The answers, measured: **Viv can, in both arrangements, and neuroglancer cannot.**
A colour drawn in the bottom slot fills 96.95% of the window under either Viv
option and 0% under neuroglancer, where the engine's own background fills 97%
instead. The same colour drawn in the *top* slot fills the window under all three,
which is how we know the difference is the slot and not the drawing.

And the bottom layer holds its place as well as the top one does. The band between
a shape drawn beneath the picture and the edge of the picture reads **0 screen
pixels of unevenness at rest, panning, zooming and thrown about** on both Viv
options — the same as their top layer — with the same reading going to 4 and 16
when the shape is deliberately moved 2 and 8 pixels. So on an engine that allows a
bottom layer at all, being underneath costs nothing in registration.

Every option still draws the operator's geometry as one sheet *above* the engine
with holes cut in it by default, and that is deliberate: it is what the older
measurements describe, it is what an engine with an opaque canvas obliges an
application into, and keeping all three drawing the same thing is what makes them
comparable. The harness's `?draw=threeLayers` view takes the same scene apart into
the three layers proper — carrier and background pattern beneath, picture in the
middle, tiles above — and switching engine with the **o** key shows the difference
plainly: the ground is there under Viv and simply absent under neuroglancer,
blotted out exactly within the rectangle the engine is drawing in.

### Things that are not drawings

The two slots hand an application a flat drawing context, which is right for
shapes that must stay locked to the picture. **It cannot hold an HTML element**,
so a label pinned to a tile, a menu, or a handle with its own event listeners has
to be an ordinary element positioned over or under the canvas.

Every option therefore publishes the transform: `viewer.whereThingsAreDrawn()`
gives the centre and the magnification in micrometres, the size of the box, and
`project`/`unproject` between micrometres and browser pixels; the same record is
handed to `onViewChanged` every frame the view settles, so an element moves in the
same instant the picture does. That is all that was added — no layer of HTML
elements exists yet and none should until its shape is settled.

Which side such an element may go on follows from the finding above rather than
needing its own measurement. **Above the canvas works for every option.** Below it
works only where the engine's canvas lets what is behind it through, which is
exactly what `drawsUnder` and measurement 0b already answer: yes for both Viv
options, no for neuroglancer.

---

## What would have to be decided next

1. **Whether the bottom layer must be the application's own.** Everything above turns
   on it, and it is a question about what the workflows need rather than about the
   engines.
2. **If yes, and neuroglancer is still wanted**, whether the things that go there can
   be written as store-backed layers — which is possible and cheap for a plate, and
   impossible for anything that moves.
3. **Whether both engines stay.** They already sit behind one interface, so keeping
   both is not expensive, and a workflow that needs a live bottom layer could choose
   Viv while one that needs the volume view chooses neuroglancer.
4. **Whether the two Viv options should share one installation of deck.gl.** They
   do not today: one borrows the viewer's own packages and the other keeps a list
   beside itself, and the two versions differ. deck.gl refuses to have two versions
   of itself alive in one page, so the harness can change engine without losing the
   view between *any* pair except those two — where it puts the working engine back
   and says why in the corner. Making all three swappable in one page means choosing
   one version, which changes which version of the engine the measurements describe.
   That is a real decision and not one to take by accident.

---

## The shape of the framework, in one place

For somebody arriving here from the code, this is the whole of what the three
layers come to. The details are in `zmart-viewer/parked/contract.md`.

```js
viewer.drawUnder(paint)   // the bottom layer: the application's own ground
                          // (hand over null when there is nothing to put there)
                          //   … the engine draws the picture in the middle …
viewer.drawOver(paint)    // the top layer: the operator's marks, selection, tiles

viewer.drawsUnder         // true or false — is the bottom layer really beneath?
viewer.drawsUnderBecause  // one sentence saying why it is what it is

viewer.whereThingsAreDrawn()   // the same transform, for placing ordinary HTML
```

Both drawing functions receive the same frame — the centre and zoom in
micrometres, the size of the box, a 2-D context, and `project`/`unproject` — and
are called in the same frame as the picture. That is what makes all three layers
pan and zoom together: they are not kept in step, they are placed from the same
numbers.
