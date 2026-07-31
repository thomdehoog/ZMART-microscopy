# What is drawn where: the layer stack, and the line between the engine and us

Written 2026-07-30, while the flat two-dimensional front end is being designed.

This describes **what belongs to the drawing engine and what belongs to the
application's own canvas**, and why the line falls where it does. It is worth
writing down separately from the question of *which* engine draws, because the
answer is the same either way. That question has since been settled — the engine
is neuroglancer, and the reasoning is recorded in `WHERE_THINGS_STAND.md` — but
nothing below depends on it.

---

## The stack, from the bottom up

| | What it is | Who draws it |
| --- | --- | --- |
| 1 | The carrier: the plate or slide outline, the wells | the application |
| 2 | The acquired image — one layer per acquisition type | the engine |
| 3 | A segmentation mask, when there is one | the engine |
| 4 | The tiles the operator laid out, coloured by how they are getting on | the application |
| 5 | Scribbles, markers, selection, drag handles | the application |

Later layers are drawn over earlier ones. So the acquired picture covers the
carrier wherever there is picture, the operator's plan stays visible on top of
the picture, and anything they are actively working with sits above everything
else.

**Why the plan sits above the picture rather than below it.** This was the other
way round until the layer stack was photographed being built on 2026-07-30, and
the photographs settled it (`LAYER_STACK.md` §3, which at the time of writing
lives on the branch `claude/layer-stack-probe`, commit `4960d17`). With the plan
underneath, the acquisition covered the tile outlines exactly where the two
overlapped — so a tile lost its outline at the very moment it was imaged. That is
the worst possible moment to lose it, because it is precisely when the operator is
checking whether the tile they got is the tile they planned. The carrier
underneath is a different sort of thing: it is a backdrop, drawn so the operator
can see where on the plate they are, and it is *meant* to be covered as picture
arrives. The plan is not a backdrop. It is something the operator drew on purpose
and needs to keep seeing, so it belongs above the picture. It should be drawn
lightly enough to sit there comfortably — a thin outline and at most a faint
wash — so that it marks the picture out without hiding what is in it.

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

With the plan drawn above the picture, a click that lands inside a planned tile
reaches that tile first, which is the behaviour an operator expects. The picture
is still there underneath, though, and a click on imaged ground where no tile was
planned lands on it.

So it is still worth marking the image layer as not pickable, which is one line.
You almost never want to pick a pixel; you want to pick the tile it belongs to,
or nothing at all. With the image standing aside, a click either finds one of the
operator's own shapes or finds nothing, and never comes back holding a voxel
nobody asked about.

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

**Which engine draws is no longer one of these questions.** It is neuroglancer,
chosen on the strength of what it lets you build around it rather than on what it
can hold; `WHERE_THINGS_STAND.md` sets out the reasoning, along with the one
drawback that does not go away, which is that every import comes through a path
the package itself calls unpromised. None of the stack above depended on that
answer, which is why it was worth writing down before the choice was made.

What is still being decided is the **arrangement**: whether the engine draws
*inside* the application's own canvas as one more layer, or *underneath* it as a
second canvas with holes cut in the surface above. Three viewers are being built
side by side for that comparison — two sandwiches, one with each engine, and one
single canvas — behind one interface and measured with one suite, so that any
difference you feel is the approach rather than the way somebody happened to wire
it up. Viv is still among them on purpose, so that the choice of engine is checked
against a real machine and a real dataset instead of being argued about. See
`OPTIONS.md` for the three and `options/RESULTS.md` for the readings so far.

One measured fact belongs here because it decides how each arrangement can be
assembled, and because the two halves of it are easy to run together by mistake.
**Nothing painted on a surface behind the engine's canvas is ever seen**, since
the engine forces its whole canvas opaque at the end of every frame — so in a
sandwich of two canvases the carrier and the plan cannot go underneath, and are
instead drawn on the surface above with holes cut wherever there is picture.
**A layer placed inside the engine, beneath another layer, is a different matter
and does show through**, measured exactly. So the stack above can also be built
entirely as layers within the engine, which is how the layer-stack probe built
it — the plate and the plan each written into the store as an image layer of
their own. Both measurements are written up: the first in `options/RESULTS.md`,
the second in `LAYER_STACK.md`.

That second route does cut across the line drawn earlier in this document, and it
is worth seeing the cost before choosing it. Anything written as a layer lives in
the store, so it cannot change while somebody is watching without writing to disk
again. A plan fixed at the moment the operator presses save is comfortable there.
Tile rectangles that turn from *planned* to *acquiring* to *done* every few
seconds are not, and belong to the application whichever route is taken. The order
in the table above holds either way.
