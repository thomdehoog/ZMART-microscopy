# What is drawn where: the layer stack, and the line between the engine and us

Written 2026-07-30, while the flat two-dimensional front end is being designed.

This describes **what belongs to the drawing engine and what belongs to the
application's own canvas**, and why the line falls where it does. It is worth
writing down separately from the question of *which* engine draws, because the
answer is the same either way — and that question is still open, being measured
in task #23.

---

## The stack, from the bottom up

| | What it is | Who draws it |
| --- | --- | --- |
| 1 | The carrier: the plate or slide outline, the wells | the application |
| 2 | The tiles the operator laid out, coloured by how they are getting on | the application |
| 3 | The acquired image — one layer per acquisition type | the engine |
| 4 | A segmentation mask, when there is one | the engine |
| 5 | Scribbles, markers, selection, drag handles | the application |

Later layers are drawn over earlier ones. So the operator's plan sits underneath
the picture and shows through wherever nothing has been imaged yet, and anything
they are actively working with sits on top of everything.

An acquisition type is one image. A run that takes a wide survey and then a
detailed scan of chosen places has two of them, and they become two layers in the
stack — the survey below, the detailed scan above, each with its own brightness
range and its own switch. They share one coordinate system, so they simply land
where they belong without anything being lined up by hand.

---

## The line, and the two reasons it falls there

**Raster pictures read out of the store belong to the engine. Objects the
operator makes, moves or changes belong to the application.**

That sounds like a rule of thumb. It holds up because two quite different
questions point at the same place, and a boundary that two independent arguments
agree on is usually a real one rather than a convenience.

### The first reason: what each is good at

A drawing engine of this kind exists to show one enormous picture that does not
fit in memory. It keeps smaller copies to show when you are zoomed out, it fetches
only the pieces you are looking at, it remembers what it has already decoded, and
it copes with the great majority of a declared canvas never having been imaged.
That is difficult, and it is the whole reason for using one.

An application's own canvas is good at the opposite: a handful of shapes that it
can test against the mouse, drag, restyle and redraw sixty times a second. Asking
the engine to do that is awkward, and asking the canvas to hold a hundred
gigabytes is impossible.

Images and segmentation masks are the first kind. Carrier outlines, tile
rectangles, scribbles, markers and selection are the second.

### The second reason: how often it changes

Anything held by the engine lives in the store, and changing it means *writing* —
which is slow, permanent, and not something to do while somebody is looking. Anything
held by the application changes for free, as often as you like, and is gone when
the page closes unless you decide to keep it.

So the question "does this change while an operator is watching?" sorts almost
everything by itself, and it sorts it the same way the first question does. A tile
rectangle turning from *planned* to *acquiring* to *done* changes every few
seconds and must not touch the disk. A plane of acquired image is written once and
never changes again.

---

## What the engine can and cannot hold

It takes images, and it takes label images — a picture where each number is an
object rather than a brightness. Label images are a genuine gain rather than a
compromise: the engine gives each object its own colour and lets one be picked out
from the rest, which the application would otherwise have to build. This project
already writes and reads them, under `labels/` inside the store.

Neuroglancer also offers an annotation layer holding points, lines, boxes and
ellipsoids, so simple markers *could* be handed over. In practice they should not
be, for a reason that has nothing to do with what it can store: this viewer
switches the engine's own interface off on purpose, so anything living over there
cannot be clicked, dragged or restyled by the operator. Something you cannot touch
is not much use as a marker.

Freehand scribbles have no home there at all. They are long paths with styling and
hit-testing, which is exactly the work the application's canvas is for.

---

## One consequence worth knowing about: picking

Because the acquired image is drawn *above* the tile rectangles, a click landing
on the image would be caught by it before ever reaching the tile underneath.

The fix is one line — mark the image layer as not pickable. You almost never want
to pick a pixel; you want to pick the tile it belongs to. With the image standing
aside, clicks fall through to the rectangles and the interaction the operator
expects simply works.

---

## The one thing that crosses the line

A scribble that becomes a mask.

It begins as the application's own path — drawn, adjusted, undone, redrawn — and
at some point the operator decides it is right and saves it. At that moment it is
written into the store as a label image, and from then on it belongs to the
engine.

This is worth planning for rather than discovering. It is a deliberate save and
not a live thing, so it does not undermine the rule; but it does mean the
application needs a way to turn its own drawing into voxels, and the store needs
somewhere to put it. Both halves already exist in this project — the writer can
produce a label image, and the viewer already finds one.

---

## The rule underneath all of it

**The application's coordinate system and the store's coordinate system are the
same.** The carrier is drawn in stage coordinates, the tiles are placed in stage
coordinates, and the image is expected to sit underneath in exactly that frame,
with no conversion at drawing time.

Everything above depends on that. It is also why rotating the flat view is
switched off — see `CONTROLS.md` — because a rotated picture stops matching the
drawing over it and nothing reports that it has.

---

## What is still open

None of the above depends on which engine draws the image, which is the point of
writing it down now. What was still being decided when this was written is
whether the engine draws *inside* the application's canvas as another layer, or
*underneath* it as a second canvas with holes cut in the layers above.

**That has now been measured, and the answer is in `SANDWICH.md`.** The short
version: drawing the image underneath does hold registration, provided the
application's own drawing is repainted from the frame the engine has just
finished rather than the moment the mouse moves. Repainted from the mouse, the
picture really does slide out from under the outlines, by up to seventy screen
pixels. Repainted from the engine's last frame, the two are indistinguishable
from being drawn in a single canvas.

Two things found while measuring it belong here as well as there, because they
are about this stack rather than about which engine draws it:

- **Unimaged ground must be drawn as nothing rather than as black.** A run
  declares far more room than it fills, and a piece nobody has imaged reads back
  as nought — exactly like a piece of genuinely dark specimen. Drawn plainly it
  becomes a solid black rectangle sitting over the operator's plan, hiding the
  tiles they laid out for a place the microscope has not been to yet. Drawn with
  nothing there, the plan shows through, which is what the table above says
  should happen. It is two lines in the shader.
- **The flat view as this project configures it draws the specimen mirrored left
  to right**, and nothing reports it. That breaks the rule at the bottom of this
  file just as thoroughly as a rotation would. See `SANDWICH.md`, section 2.
