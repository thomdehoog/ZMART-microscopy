# Three ways to draw the flat view, measured side by side

The table below is the answer to `viz_studio/OPTIONS.md`. One column per option,
one row per question, every number taken from a photograph of the screen.

Measured 2026-07-30. **So far only option A has been built**, so the table has one
column; the other two fill in beside it as they are written, by running the same
program with a different word:

```
npm --prefix viz_studio/options/harness run build
python viz_studio/options/measure/run.py --option viv-under
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
| *measured* | 2026-07-30 23:32 | 2026-07-31 07:05 | 2026-07-31 07:09 |
| **0. Can a surface underneath the engine be seen?** | **no** | yes | yes |
| **1. Registration** — worst unevenness at rest (screen px) | 1.0 | 0.0 | 0.0 |
|   … while panning | 1.0 | 0.0 | 0.0 |
|   … while zooming | 2.0 | 0.0 | 0.0 |
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
|   … holders of decoded image it had to be asked to let go of | 3 | 3 | 3 |
| **5b. What the refresh costs** — pieces re-fetched | 4 | 3 | 4 |
| **5c. The picture survives the refresh** — seconds before it is back | 0.15 | 0.19 | 0.09 |
|   … what the window showed while it refreshed | [0.2726, 0.0, 0.1839] | [0.2734, 0.2734, 0.2734, 0.2734] | [0.2734, 0.2734, 0.2734] |
| **5d. The view stays put** — centre moved (µm) | 0.0 | 0 | 0.0 |
| **5e. How soon a tile shows** (seconds) | 0.35 | 0.37 | 0.36 |
| **5f. Does it keep up** — frames a second, first round → last | 5.2 → 6.0 | 5.2 → 5.6 | 5.2 → 5.2 |
|   … tiles written meanwhile | 460 | 449 | 478 |
| **6. Requests** — to redraw one view, unbounded | 117 | 845 | 432 |
|   … of those, for ground nobody imaged | 108 | 800 | 396 |
|   … bounded by the coverage record | 25 | 36 | 100 |
|   … of those, for ground nobody imaged | 16 | 0 | 64 |
| **7. Drawing rate** — frames a second at 20 positions | 18.9 | 13.0 | 19.3 |
|   … at 200 positions | 13.0 | 7.1 | 11.8 |

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
explained away by the two layers having been photographed a moment apart. One
pixel is the measurement's own floor, from the hole falling on fractional pixel
positions.

The last row of that group is the red evidence. Moving the hole two pixels reads
5, and eight pixels reads 17, on the same page with nothing else changed. A check
that has never been seen to fail is not evidence of anything.

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
  `tilesMayHaveLanded({coverage})`, which asks the engine to let go of the pieces
  of image it has decoded; three holders were asked, and the share went to 0.2726.
- *What the refresh costs.* Four pieces of image re-fetched, three of which held
  picture. That number follows the size of the window rather than the size of the
  specimen, because the engine asks for what it needs to draw and nothing else.
- *Does the picture survive it.* No, and it is honest to say so. Letting go of
  everything decoded is a complete redraw, so the window went to nothing and
  filled back in — the frames read 0.27, then 0.00, then 0.18. It was back to
  half of what it settled at in **0.15 seconds**. There was no patchwork of two
  generations: the readings are either the old picture, nothing, or the new one
  filling in, never a stable mixture of both.
- *Does the view stay put.* Yes, exactly: the centre moved 0.0 µm, the zoom did
  not change, and the edge of the picture on screen moved 0.0 photograph pixels.
- *How soon.* 0.35 seconds from the tile being safely on disk to the window being
  measurably brighter, which includes the time spent photographing and is
  therefore an upper bound rather than a best case.
- *Does it keep up.* 460 tiles written during the measurement while the view was
  panned and zoomed throughout, with a refresh in every round. The drawing rate
  went 5.2 → 6.0 → 5.2 → 6.0 → 6.0 → 6.0 frames a second: flat, not falling.

**6. Requests.** On the sparse canvas — a large declared room with a small imaged
patch, which is the shape a real run has — a complete redraw cost **117 requests,
108 of them for ground nobody had imaged**. Bounded to the coverage record, the
same redraw cost **25, of which 16 were wasted**. Almost the whole cost of a
redraw is asking about ground the microscope has never been to, and the record is
what stops it.

**7. Drawing rate.** 18.9 frames a second with twenty tile rectangles on the
operator's canvas and 13.0 with two hundred — a real cost, and one that will look
different on a machine with a graphics card. It is the number to compare against
the single-canvas option, because that is exactly where drawing in two surfaces
and drawing in one should differ.

---

## Two surprises worth passing on

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
