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
`viz_studio/options/contract.md`, and three implementations of it already exist.

The interface this serves: the viewer on the left, the workflow's own controls on
the right, and nothing else competing for attention.

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

Three implementations of the middle layer, behind one interface, each measured on the
same eight questions: `viz_studio/options/`, with the table in `RESULTS.md`. All
three hold the same two gestures, the same handedness, the same coordinate system,
and keep pace over hundreds of tiles arriving live.

What is **not** built is the bottom layer. Every option today draws the operator's
geometry above the engine, cutting holes where the picture shows through. That is
the arrangement the measurements describe.

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
