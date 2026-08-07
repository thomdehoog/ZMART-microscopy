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

*Measured 2026-07-30. The write-up is `SANDWICH.md`, which is not on this branch —
it lives on `claude/sandwich-probe`, commit `1277e30`.* Registration holds to **1 screen pixel**
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
 *   acquisitions  [{ url, name, channels? }]  drawn in order, first at the bottom
 *                 channels is optional; left out, the option reads the run's own
 *                 description of its colours — see options/contract.md §6
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

   **That number alone is not enough, and knowing why is half the measurement.**
   Unevenness catches the two layers sitting in different *places*. It is deaf to
   them agreeing about where the centre is and disagreeing about how *large*
   everything should be, because that grows all four margins together and leaves
   them equal. So the same photograph is also read for how much wider the band
   came out all round than the width it was cut at, which is deaf to displacement
   in return. Both are reported. `RESULTS.md` row 1c shows the second one catching
   an operator's drawing made two per cent too large while the first sits at
   nought throughout.
2. **Handedness** — open an acquisition written dim at one edge and bright at the
   other, and check the bright edge is drawn on the right. A mirrored view was
   shipped for months because nothing asked this; see `CONTROLS.md` §1a and
   `tests/test_the_picture_is_not_mirrored.py`, which measures it.

   Do not settle for dragging the picture and watching which way it goes. That
   was the obvious check and it cannot find this fault: an engine pans using the
   same axis mapping it draws with, so the picture follows the hand pixel for
   pixel whichever way round it is drawn — measured at a slope of +1.0 both
   before the mirror was fixed and after. It is still worth checking, because a
   view that slides against the hand is unusable, but it is a separate question.
   Only something asymmetric *inside* the specimen can say which way round the
   picture is.
3. **Two gestures and no more** — drag pans, the wheel zooms, and every other
   gesture leaves the picture byte-identical. See `CONTROLS.md`.
4. **Sparseness** — a canvas imaged in a few scattered places shows the operator's
   drawing through the gaps, and shows picture only where picture was written.
5. **New data arriving while somebody is watching** — the measurement that matters
   most, because watching a run fill in is what this viewer is *for*. A run that
   has to be reopened to show what it just acquired is not a smart-microscopy
   viewer, it is a file browser.

   It is not enough that a tile eventually appears. Every option must be measured
   on all six of these, with a run genuinely writing throughout:

   - **Does it appear at all**, and what call was needed to make it — nothing on
     disk announces a new tile, because the images are declared at full size before
     any tile exists and their description is identical before and after. Both
     engines are known to need telling: neuroglancer through the cache-invalidation
     path `frontend/src/engine.js` already uses, and Viv by being handed a fresh
     loader. Record exactly what each needed.
   - **What the refresh costs.** How many pieces of image are re-fetched to show
     one new tile? An option that re-reads the whole view every time a tile lands
     will not survive a long run, however well it draws.
   - **Does the picture survive the refresh** — does it flicker, blank, or show a
     patchwork of two generations? The live-tiles work already met the patchwork
     case, where a second read started too early left parts of two different planes
     on screen at once.
   - **Does the view stay where the operator put it?** A refresh that resets the
     centre or the zoom is unusable, and it is an easy mistake to make when the
     way to refresh is to hand the engine a new source.
   - **How soon after the tile lands does it show**, in seconds.
   - **Does it keep up?** Not one tile — a long run at a realistic rate, several
     hundred tiles arriving steadily, with the operator panning and zooming
     throughout. Report whether the picture keeps pace or falls progressively
     further behind, and what the drawing rate does over the run.

   Neuroglancer's behaviour here is partly known and Viv's is only known for a
   short run in a small canvas. Treat both as unmeasured and measure both.
6. **Requests** — how many pieces of image are asked for to draw one view, and how
   many of those are for ground nobody imaged. Measured with and without the
   coverage record bounding the drawn region.
7. **Drawing rate with many positions** — the existing fault where cost grows with
   the number of positions. Frames in three seconds at twenty positions and at two
   hundred.
8. **Two acquisitions at once** — a wide survey and a detailed scan over part of
   it, opened together. This is the ordinary arrangement a run has, and it is the
   only case where a viewer has no help at all: two images written at different
   voxel sizes share nothing but the position each of them states in micrometres,
   so if that position is ignored one run is drawn at the other's corner. On a
   single acquisition written from the stage's zero the fault is invisible, which
   is exactly why it has to be measured on two.

   Measure that both are drawn and that the finer one lands inside a known
   feature of the coarser, in micrometres, read from the photograph — and show
   the check failing by moving one run's stated position a known distance. Two of
   the three options were found drawing the finer run 898 µm out of place the
   first time this was asked.

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

---

## Telling "imaged and dark" from "never visited"

Decided in conversation on 2026-07-30, **not yet built**. Recorded here because it
is the last thing standing between the layer stack above and doing what an operator
would expect.

The problem. Making unimaged room see-through works by looking at how bright a
voxel is: nothing there, so let the layer beneath show through. But a place that
genuinely *was* imaged and came back black looks exactly the same to that test, so
it disappears too — and a viewer that hides a dark specimen is worse than one that
never hid anything.

The fix is one line in the writer, just before a tile is written:

```python
image = np.maximum(image, 1)
```

Zarr fills room that was never written with zero. The ambiguity exists only because
acquired data is *also* allowed to be zero. Take that away and nought means "nobody
has been here" — exactly, always — while anything at all means "somebody looked,
and this is what they saw". The test the shader already makes, `v > 0.0`, stops
being a guess about brightness and becomes a true statement about coverage.

What it costs is the single value zero as a real intensity: one level out of the
65,536 a camera can record, and the one meaning "darker than nothing". A camera
sits at an offset of a hundred counts or so, so nothing an instrument produces is
lost. Only an image that has already had its background taken off could contain a
true zero, and there the zero was noise rather than signal.

Why not something cleverer. A sentinel such as 65535 fails because saturated
pixels genuinely reach it. A wider or signed type works and doubles the storage.
The engine does know which pieces of image were never written — a missing piece is
fetched, not found, and filled in — but that knowledge never reaches the shader, so
it is present and unreachable. And a shader cannot read a second layer, so the
record of where tiles were imaged cannot be consulted while drawing.

The one genuinely different approach is to stop asking the pixels at all: use that
record to give the engine one bounded layer per imaged region, so unimaged ground
has no layer over it and is see-through because nothing is drawn there. That is
exact and needs no convention — but it trades one layer for many, and this viewer
already has a measured fault where cost grows with the number of positions.

**Two things to know before doing it.** It applies only to tiles written afterwards;
anything already acquired keeps the ambiguity. And it needs a test that writes a
genuinely dark tile beside unwritten room and proves the first stays visible while
the second does not — otherwise the guarantee quietly rots the next time somebody
tidies the writer.

---

## Nothing is drawn until something is there

Arrived at in conversation on 2026-07-30, **not yet built or measured**. Recorded
because it is the tidiest answer to three separate problems, and because it inverts
an assumption the current arrangement makes without ever having chosen it.

Today one layer covers the whole of a run's declared canvas. A run declares
generously — that is the point, since room nobody writes into costs nothing — so
that single layer stretches across ground the microscope will never visit, and
paints it black. Everything else follows from patching over that: the shader that
turns dark into see-through, the layer stacked underneath so the transparency
survives, the reserved intensity that separates a dark specimen from empty ground.

The other way round is to draw nothing at all until there is something to draw. Each
part of the canvas that has been imaged gets its own bounded layer; ground nobody
has visited has no layer over it, and is therefore see-through because nothing was
ever painted there. As a run proceeds, regions appear.

**One mechanism settles three things.**

Transparency stops being computed and becomes structural. There is no shader trick
and nothing to switch off by accident.

Pieces of image are no longer asked for over empty ground. A sparse canvas was
measured making 250 requests to draw one view, 190 of them for room never imaged —
roughly three in four wasted. That is the number that decides whether a store on a
network drive is comfortable or painful.

And "imaged but dark" is no longer ambiguous. A region that was visited has a layer
over it whether or not its voxels are bright, so a dark specimen stays visible while
untouched ground stays clear — with no reserved intensity and no convention to
enforce in the writer.

**What makes it affordable is the coverage record**, which is why this was not
practical before tonight. The obvious objection is one layer per tile and hundreds
of tiles, against a viewer that already slows measurably as positions are added.
But `zmart_storage/coverage.py` joins tiles that touch into regions, so an ordinary
raster scan is one rectangle that grows rather than two hundred separate ones, and a
scattered scan is a handful. The number of layers follows the shape of the
acquisition, not the number of tiles.

**What is unmeasured**, and what this would live or die on: the cost of changing
layers while somebody is watching. Regions appear and grow throughout a run, and
every change asks the engine to take on a new bounded source or alter an existing
one. Neuroglancer will do it; how much it costs each time is unknown, and a long run
makes that change often. It is close enough to the live-acquisition measurement
already in this document that the two should be answered together.
