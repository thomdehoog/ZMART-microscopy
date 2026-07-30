# Three ways to draw the flat view, built so they can be compared

Written 2026-07-30, to be tried side by side on a machine with a real graphics card
and a large acquisition.

There are three credible ways to put acquired image data underneath the operator's
own drawing. Each has now been measured far enough to know it is not hopeless, and
no further amount of reasoning will separate them — what separates them is how they
feel with a hundred gigabytes on screen, which is a question only a real machine
with a real dataset can answer.

So all three are being built, behind **one interface**, validated by **one
measurement suite**. That is the whole point of this document. Three viewers with
three different interfaces cannot be compared: any difference you feel might be the
engine or might be the way somebody happened to wire it up. Three viewers behind an
identical interface, driven by the same page and measured by the same tests, differ
only in the thing being compared.

---

## The three

### A. Neuroglancer underneath

Neuroglancer draws into its own canvas. The operator's canvas sits exactly on top,
with holes cut wherever the image should show through. Neuroglancer never sees the
mouse; the page owns every gesture and tells the engine where to look.

*Measured 2026-07-30 (`SANDWICH.md`).* Registration holds to **1 screen pixel**
while the view is thrown about, provided the operator's canvas is repainted only
from inside neuroglancer's end-of-frame announcement. Following the pointer instead
gives 25. No interface freeze was found even with the server delayed 200 ms.

*Why it is attractive.* It is the engine already proven here on real data, it
handles one enormous sparse volume as its core job, and the volume view comes
almost free because it is the same engine with a different layout.

### B. Viv underneath

The same arrangement, with Viv and deck.gl drawing into the lower canvas instead of
neuroglancer. Everything above the engine is identical to option A.

*Why it is worth building.* It isolates the engine from the arrangement. If A and B
feel different, the difference is the engine. If they feel the same, the sandwich
arrangement is neutral and the choice is about everything else — which is a much
easier decision to make.

### C. Viv inside one canvas

No sandwich. Viv's image layers and the operator's geometry are layers in a single
deck.gl canvas, drawn in one pass from one view state. Where nothing was imaged,
the image would otherwise be painted opaque black, so a small shader addition makes
it see-through.

*Measured 2026-07-30 (`DRAWING_ENGINES.md`, and the live-tiles work).* Registration
is exact by construction — the control run in the sandwich measurements read **0**
on every gesture. The see-through addition turns 0 of 19 unimaged squares into 19 of
19.

*Why it is attractive.* Nothing to keep in step, ever. The registration question
simply does not arise.

*Its known cost.* The see-through addition keys on brightness, so somewhere that was
imaged and came back black looks the same as somewhere never visited. And the 3-D
view needs a second engine.

---

## The interface all three implement

One module per option, each exporting the same function. Nothing else is public.

```js
/**
 * Open a viewer inside `element` and return the handle used to drive it.
 *
 * @param {HTMLElement} element  where the viewer draws; it fills this box
 * @param {object} options
 *   acquisitions  [{ url, name, channels }]  drawn in order, first at the bottom
 *   coverage      the imaged regions, as `zmart_storage/coverage.py` records them,
 *                 or null when the run keeps no record
 *   background    the page colour, so the seam never shows
 *   onViewChanged called with { centre, zoom } whenever the view settles
 * @returns {Viewer}
 */
export function openViewer(element, options): Viewer
```

and the handle:

```js
viewer.setView({ centre, zoom })   // centre in micrometres, zoom in µm per screen pixel
viewer.getView()                   // → { centre, zoom }, the view now on screen
viewer.setPlane(z)                 // which plane of the stack
viewer.setMoment(t)                // which moment of a timelapse
viewer.setChannel(index, { visible, colour, window })
viewer.drawOver(paint)             // the operator's own drawing; see below
viewer.tilesMayHaveLanded()        // "go and look, a tile may have arrived"
viewer.destroy()
```

**`drawOver(paint)`** is the part that decides whether the comparison is fair. The
page hands over one function, and every option calls it at the moment that option
considers correct — for the sandwich options that is inside the engine's end-of-frame
announcement, for the single-canvas option it is inside deck.gl's own draw. The page
never knows which. It receives the view state to draw against and draws the same
shapes in every option.

```js
viewer.drawOver(({ centre, zoom, width, height, project }) => {
  // `project` turns micrometres into screen pixels for this frame.
  // Draw the carrier, the tiles, the scribbles. Same code in all three.
})
```

**Units are micrometres everywhere**, because that is what the operator's stage and
the store's own description both speak. No option may expose an engine's private
notion of zoom.

---

## What every option must be measured on

The same suite runs against all three, and an option that will not pass it is not
ready to be compared.

1. **Registration** — `viz_studio/tests/margins.py`. A square of image with a
   slightly larger hole cut over it; the four margins stay even while the view is
   panned, zoomed and thrown about. Reported as worst unevenness in any one frame,
   in screen pixels.
2. **Handedness** — drag the picture and check it moves the way the drag went. The
   slope must be **+1.0**. A mirrored view was shipped for months because nothing
   asked this.
3. **Two gestures and no more** — drag pans, the wheel zooms, and every other
   gesture leaves the picture byte-identical. See `CONTROLS.md`.
4. **Sparseness** — a canvas imaged in a few scattered places shows the operator's
   drawing through the gaps, and shows picture only where picture was written.
5. **New data** — tiles written into ground the viewer has already looked at appear
   once `tilesMayHaveLanded()` is called.
6. **Requests** — how many pieces of image are asked for to draw one view, and how
   many of those are for ground nobody imaged. Measured with and without the
   coverage record bounding the drawn region.
7. **Drawing rate with many positions** — the existing fault where cost grows with
   the number of positions. Frames in three seconds at twenty positions and at two
   hundred.

Every measurement must be taken **from the picture**, never from what an engine
reports about itself, and every check must be shown failing when it should. That
rule was learned the hard way in this repository and it is not negotiable.

---

## Where things live

```
viz_studio/options/
  contract.md        this interface, restated beside the code
  harness/           the page that drives any option, and the shapes it draws over
  neuroglancer-under/
  viv-under/
  viv-inside/
  measure/           the shared suite, run against each in turn
  RESULTS.md         the table, filled in as each is measured
```

The harness must be able to switch options **without a rebuild** — a query
parameter is enough. Somebody comparing three viewers should be able to flip
between them on the same data in the same second, because a difference you can only
see by rebuilding is a difference you will not see at all.

---

## What this is not

It is not three finished products. Each needs to be good enough that the comparison
is about the approach rather than about unfinished wiring, and no better. Anything
one option has that the others do not is a reason to distrust the result.
