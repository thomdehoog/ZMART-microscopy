# Three ways to draw the flat view, measured side by side

The table below is the answer to `viz_studio/OPTIONS.md`. One column per option,
one row per question, every number taken from a photograph of the screen.

All three options have now been built and measured, so the table has three
columns. Each column is rewritten by running the same program with a different
word, and the date at the top of each says when it was last taken:

```
npm --prefix viz_studio/options/harness run build
python viz_studio/options/measure/run.py --option all
```

The photographs behind every number are in `measurements/<option>/`, and the full
readings — including everything the table has no room for — are in
`measurements/<option>.json`.

---

## Read this before the table

### It was measured on a machine with no graphics card

Software rendering means frames arrive far less often than they would on real
hardware — around fifteen to twenty a second here — so every gesture was made in
fewer, larger steps than a real hand would make, and the engine was never the
fast thing waiting on a slow disk.

What that does and does not affect is worth being precise about. **The
registration readings are not affected**, because a band that is uneven within a
single photograph is uneven whenever the photograph was taken, and slowness
cannot invent one. **The drawing-rate readings describe this machine** and should
be read as "does the cost grow", not as "is it fast enough". **The measurement of
whether the arrangement keeps up with a run is the one to repeat first** on the
machine with the graphics card, because that is where the engine stops being the
slowest thing.

### One finding changes the shape of the arrangement, and it applies to option B too

**Nothing behind neuroglancer's canvas ever shows through it.** With one colour
painted behind the engine's surface and another set as the engine's own
background, over ground nobody had imaged an operator saw the engine's background
across 97% of the window and none of the colour behind. The engine forces the
whole canvas opaque at the end of every frame.

That was measured before anything was built on it, which was the right order,
because it settles which way up a sandwich has to be assembled. A sandwich is two
separate drawing surfaces in the page, one in front of the other: the engine's
canvas and the operator's own. In that arrangement the operator's carrier and
planned tiles cannot sit on a surface *underneath* the engine, because such a
surface is never seen at all. The sandwich has to be built the other way up:
**the operator draws the carrier and the tiles on the surface above the engine,
and cuts holes in it wherever the coverage record says there is picture.** That
is what the harness does, it works, and it is what the sparseness row measures.

**Please do not read this as saying that the stack in `LAYERS.md` cannot be
built.** It is a different arrangement and it was measured separately the same
night, and the two results sit happily side by side once you see which is which.
This measurement is about two *canvases* in the page, one behind the other. The
layer-stack probe written up in `viz_studio/LAYER_STACK.md` — which at the time of
writing lives on the branch `claude/layer-stack-probe`, commit `4960d17` — asked
the neighbouring question: what happens when the plate and the plan are put
*inside* neuroglancer as ordinary image layers, beneath the acquisition. There the
lower layer does show through the upper one — read as exactly `0, 255, 0`
wherever the upper layer had never been written, turning to the background colour
when the lower layer was taken away, and to `255, 0, 0` when the upper layer's
shader was made opaque on purpose. So the honest statement of both findings
together is this: **a surface behind the engine's canvas can never be seen, while
a layer inside the engine, beneath another layer, can.** The stack in `LAYERS.md` is buildable — as layers
within the engine rather than as canvases stacked on top of one another.

The finding here has a consequence for the sandwich worth stating plainly. In
this arrangement the coverage record is no longer an optimisation — it is the
thing that makes the layer order possible at all. With no record there is nowhere
the picture may show, and the harness says so rather than guessing. Whether a
deck.gl canvas behaves the same way is unmeasured, and the agent building option
B should measure it the same way before building on it:
`measure/showing_through.py` does it by name and needs no changes.

### The seam is meant to be invisible; the measurements make it visible on purpose

The engine's background is meant to match the page exactly, so that an operator
can never tell there are two surfaces. During the registration measurement it is
saturated blue and the operator's sheet is saturated red, because a band you
cannot see is a band you cannot measure. Please do not tidy them into agreement:
the check would go on passing while measuring nothing. It is said again at the
top of `harness/src/drawings.js` and of `tests/margins.py`.

---

<!-- the table below is written by measure/results.py; edit above or below it -->

| | neuroglancer-under | viv-inside | viv-under |
| --- | --- | --- | --- |
| *measured* | 2026-07-31 08:46 | 2026-07-31 07:56 | 2026-07-31 07:57 |
| **0. Can a surface underneath the engine be seen?** | **no** | yes | yes |
| **1. Registration** — worst unevenness at rest (screen px) | 1.0 | 0.0 | 0.0 |
|   … while panning | 1.0 | 0.0 | 0.0 |
|   … while zooming | 1.0 | 0.0 | 0.0 |
|   … thrown about | 1.0 | 0.0 | 0.0 |
|   … with the hole moved 8 px on purpose (must be large) | 17.0 | 16.0 | 16.0 |
| **2. Handedness** — brightness across the picture (levels per 100 px) | 91.5 | 91.5 | 91.5 |
|   … the bright edge is on the right | yes | yes | yes |
|   … dragging carries the picture with the hand (slope) | 1.0 | 1.0 | 1.0 |
| **3. Two gestures** — removed gestures that moved the view | none | none | none |
|   … gestures the page refused | 1 shiftDrag, 1 rightButton, 3 ctrlWheel, 22 keys | 1 shiftDrag, 1 rightButton, 3 ctrlWheel, 22 keys | 1 shiftDrag, 1 rightButton, 3 ctrlWheel, 22 keys |
| **4. Sparseness** — share of the window showing picture | 0.0152 | 0.0153 | 0.0153 |
|   … the operator's plan shows through the gaps | yes | yes | yes |
| **5a. New data appears at all** | yes | yes | yes |
|   … readers the option had to send back to the store | 3 | 3 | 3 |
| **5b. What the refresh costs** — pieces re-fetched | 4 | 3 | 4 |
| **5c. The picture survives the refresh** — seconds before it is back | 0.08 | 0.11 | 0.1 |
|   … what the window showed while it refreshed | [0.2726, 0.2726, 0.2726] | [0.2734, 0.2734, 0.2734] | [0.2734, 0.2734, 0.2734, 0.2734] |
| **5d. The view stays put** — centre moved (µm) | 0.0 | 0 | 0.0 |
| **5e. How soon a tile shows** (seconds) | 0.3 | 0.38 | 0.13 |
| **5f. Does it keep up** — frames a second, first round → last | 5.2 → 5.6 | 5.2 → 4.8 | 5.2 → 5.2 |
|   … tiles written meanwhile | 465 | 470 | 484 |
| **6. Requests** — to redraw one view, unbounded | 117 | 826 | 432 |
|   … of those, for ground nobody imaged | 108 | 781 | 396 |
|   … bounded by the coverage record | 25 | 36 | 100 |
|   … of those, for ground nobody imaged | 16 | 0 | 64 |
| **7. Drawing rate** — frames a second at 20 positions | 24.8 | 12.7 | 26.1 |
|   … at 200 positions | 19.2 | 10.9 | 18.1 |

<!-- end of the generated table -->

---

## What the rows mean

**0. Showing through.** Described above. The check was shown able to give the
other answer: with the option's own surfaces hidden, the colour behind filled
100% of the window.

**1. Registration.** A square of image with a hole cut forty screen pixels larger
around it; the band between them is read on all four sides, along three cuts, in
every frame of a live recording. The right answer is "unchanged", so the number
is the worst unevenness within any *single* photograph — which cannot be
explained away by the two layers having been photographed a moment apart.

The last row of that group is the red evidence. Moving the hole two pixels reads
5, and eight pixels reads 17, on the same page with nothing else changed. A check
that has never been seen to fail is not evidence of anything.

**The one pixel option A reads at rest is this measurement's own floor against
this engine, and nothing in the viewer can drive it to nought.** It was chased
down properly rather than assumed, and the cause is worth knowing, because it
says what the number can and cannot tell you.

Neuroglancer's picture has a hard edge. A screen pixel either shows picture or it
does not, with nothing in between, so the block of picture on the screen always
begins and ends on a whole pixel. The two Viv options fade their edge across the
last pixel instead, and the reading — which counts only pixels that are
definitely one thing or definitely the other — skips that half-lit pixel on
*both* sides, which is the whole reason they come out even. At the magnification
this measurement uses, the edge of the imaged square falls exactly half way
across a pixel, and there a block of whole pixels simply cannot sit centred in
the hole: whichever way the engine rounds, one margin comes out a pixel wider
than the one opposite.

That is measured, not argued. The hole can be moved by a fraction of a pixel, so
it was: nudged half a pixel to the left — deliberately put in the wrong place —
the two margins across the window came out **even, 40 and 40**, where they read
40 and 41 with the hole where it belongs; nudged half a pixel to the right they
read 39 and 41. A number that improves when you break the thing it is measuring
has reached the end of what it can resolve. So option A's 1 should be read as
"the two agree to within half a screen pixel", which is also all that the two
zeros mean.

**2. Handedness.** The picture runs uphill to the right at 91 grey levels per
hundred pixels, which is the specimen the way round it really is. The separate
dragging check reads +1.0, meaning the picture goes with the hand. Both are
needed and neither replaces the other: dragging reads +1.0 whichever way round
the picture is drawn, because an engine pans using the same axis mapping it draws
with. Only something asymmetric inside the specimen can say which way round it is.

**3. Two gestures.** Nine gestures that used to move the view were each made in
earnest and each left the picture byte-identical. The page also reports what it
turned away — one shift-drag, one right-button click, three ctrl-wheels and
twenty-two key presses — which is what stops this passing on a page that had
quietly stopped listening altogether.

**4. Sparseness.** Five patches imaged on a canvas mostly never visited, seen from
far enough out to have the whole carrier in the window. Picture where picture was
written, the operator's plan everywhere else.

**5. New data arriving.** The one that matters most, and it has six parts.

- *Does it appear at all.* Eight tiles were written into ground the viewer had
  already looked at and found empty. **Nothing appeared** — the share of the
  window showing picture did not move at all, from 0.0953 to 0.0953. Not slow: no
  request was made, ever. What made it appear was one call,
  `tilesMayHaveLanded({coverage})`, which sends the option back to the store to
  read what is there now; three readers were sent back, and the share went to
  0.2726. How an option goes back differs and the page never knows: the two Viv
  options open a fresh reader on the store, and option A tells neuroglancer's
  background worker to read its three resolution levels again.
- *What the refresh costs.* Four pieces of image re-fetched, three of which held
  picture. That number follows the size of the window rather than the size of the
  specimen, because the engine asks for what it needs to draw and nothing else.
- *Does the picture survive it.* Yes, in all three, and the readings are flat:
  option A held 0.2726 in every frame of the refresh and the other two held
  0.2734. That is what it should look like — the picture already on screen is
  kept and exchanged piece by piece only once each replacement is ready to draw,
  so there is neither a gap nor a patchwork of two generations on screen at once.

  It is worth recording that **option A did not start out this way**, because the
  fault it had is the one to watch for in any engine. Left to itself neuroglancer
  answers "go and look again" by throwing away every piece of picture it has
  already decoded, so the window read 0.2726, then **0.0000**, then 0.1839 across
  a single refresh: on a run in progress, a flash of empty screen every few
  seconds at exactly the moment the operator is watching most closely. The
  adapter now keeps the browser's own copy of each piece on the screen and swaps
  it for its replacement at the moment that replacement lands; the engine offers
  nothing narrower than "read this whole resolution level again", so the fetching
  is unchanged and only the picture on screen is held.
  `tests/test_the_options_hold_together.py` has the check that stops it coming
  back, and that check was shown going red against the fault.
- *Does the view stay put.* Yes, exactly: the centre moved 0.0 µm, the zoom did
  not change, and the edge of the picture on screen moved 0.0 photograph pixels.
- *How soon.* 0.30 seconds from the tile being safely on disk to the window being
  measurably brighter, which includes the time spent photographing and is
  therefore an upper bound rather than a best case.
- *Does it keep up.* 476 tiles written during the measurement while the view was
  panned and zoomed throughout, with a refresh in every round. The drawing rate
  went 5.2 → 5.6 → 5.2 → 5.2 → 5.2 → 5.2 frames a second: flat, not falling.

**6. Requests.** On the sparse canvas — a large declared room with a small imaged
patch, which is the shape a real run has — a complete redraw cost **117 requests,
108 of them for ground nobody had imaged**. Bounded to the coverage record, the
same redraw cost **25, of which 16 were wasted**. Almost the whole cost of a
redraw is asking about ground the microscope has never been to, and the record is
what stops it.

**7. Drawing rate.** 25.1 frames a second with twenty tile rectangles on the
operator's canvas and 19.5 with two hundred — a real cost, and one that will look
different on a machine with a graphics card. It is the number to compare against
the single-canvas option, because that is exactly where drawing in two surfaces
and drawing in one should differ.

---

## Four surprises worth passing on

**Following the pointer did not come apart, on this machine.** `SANDWICH.md`
records that repainting the operator's drawing on every mouse move rather than
from the engine's end-of-frame announcement let the two layers drift by up to 25
screen pixels. That was reproduced here as a deliberate breakage — the
end-of-frame repaint removed and a pointer repaint put in its place — and the
margins stayed at 1, 2 and 1. The engine in this arrangement simply never fell
behind by a whole frame.

The discipline is kept anyway, and it should be: it costs nothing, it is the only
arrangement that *cannot* come apart, and this machine is the slowest possible
place to look for a fault that needs the engine to be slower than the hand. It
should be looked for again on real hardware with a large dataset, where the engine
is genuinely working. But it is recorded here as not reproduced, because reporting
it as confirmed would be untrue.

**Resizing the engine's canvas costs registration unless the engine is told at
once.** Bounding the drawn region to the imaged ground means resizing the engine's
box as the view moves, and the engine only re-reads its own size when the
browser's resize watcher reports — which is *after* it has drawn another frame at
the old size. A frame drawn at one size and stretched to another is the wrong
scale in the wrong place. Measured, that read **69 screen pixels while panning and
71 while thrown about**, with the band closed altogether in 99 of 123 photographs.
Nudging the engine's own count of resizes so that it re-reads its size before it
draws brings the same measurement back to **1**.

That had not been seen before because the earlier probe never bounded the drawn
region while measuring registration. It is worth knowing for option B: if it
resizes its drawing surface for any reason, the same fault is waiting.

**The picture was sitting half a voxel from where the store says it is, and the
margin measurement could not see it.** This came out of chasing the pixel above,
and it is the more useful of the two things that chase turned up.

An image has to say where in the specimen its first voxel sits, and there are two
ways of saying it: the **corner** of that voxel, which is what our writer means
and what the coverage record counts in, or its **middle**, which is what the
OME-Zarr text says and therefore what neuroglancer assumes. Nothing in the store
says which of the two it means, so both are being reasonable — and the engine
placed every acquisition half a voxel before where the operator's drawing put it.

Half a voxel comes to about half a screen pixel at the magnification an engine
chooses for itself, because it picks whichever stored resolution puts roughly one
voxel in one pixel. That is exactly the size of the floor described above, which
is why the margin measurement, taken at one magnification, could never have found
it. Zoom in past the finest stored resolution, though, and half a voxel keeps its
size in the specimen while a screen pixel shrinks: measured at eight times full
resolution, the edge of the picture sat **four screen pixels** from where the
drawing put it, and it would be eight at sixteen times. That is precisely the
moment an operator is asking whether a tile's picture really landed inside the
square they laid out.

`neuroglancer-under/viewer.js` now moves the layer back by half a voxel — half a
voxel *of the image*, not a number of pixels tuned on one screen, and only where
the engine has said it is counting from the middle of a voxel. Measured after:
the edge of the picture lands exactly where the drawing puts it at full
resolution (0.000 µm, from 0.500 µm), and the margin reading **while zooming came
down from 2 to 1**, stable across three runs each way. The reading at rest did
not move, for the reason given above, and nothing else in the table moved either.

**It is only half cured, and the rest belongs to the writer.** The engine takes
its half a voxel off each stored resolution separately, so a four-micrometre
level is placed two micrometres early where the one-micrometre level is placed
half a micrometre early — which also means the resolutions within one pyramid do
not line up with each other. Only the finest can be put right from the viewer,
because the coarser ones are placed once, while the store's description is being
read, and are out of reach afterwards. The complete cure is for
`zmart_storage/canvas.py` to say which convention it means, by giving each
resolution a translation of half its own voxel. Nothing in Viv's packages
mentions `coordinateTransformations` at all, so options B and C — which already
place the picture from the corner — should not notice the change.

**A dense screen costs sharpness and a little registration, but not scale.**
Neuroglancer sizes its canvas in browser pixels and lets the browser scale it up,
which `SANDWICH.md` §7 records as a loss of sharpness. Measured here at a screen
density of 1.5 and of 2, the margins came out 60 / 61 and 79 / 81 real pixels
against a band cut at 60 and 80. Opposite sides therefore add up to within a
single real pixel of twice the band at every density — and a picture drawn at the
wrong *size* could not do that, because the square is 245 browser pixels across
and an error in scale would grow with it. So **the picture is the right size, and
only the grid its edge can land on is coarser**: the finest step at which the
engine can place it is one browser pixel rather than one real pixel. Options B
and C, which do size their canvas in real pixels, read 0 at every density.

What that means for an operator on a dense laptop screen is a seam between the
picture and their own drawing that can sit up to one real pixel out at a density
of 2 — a hairline, and not the much larger error a genuine disagreement about
the size of the window would have caused.
