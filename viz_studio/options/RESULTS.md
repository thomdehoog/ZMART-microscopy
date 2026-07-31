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

**And the drawing rate wanders a great deal between one run and the next**, which
is worth knowing before anybody reads a change in it as a change in the code. Row
7 fell for all three options between the run of the morning and the run that
added the bottom layer — option A from 24.8 to 18.0 frames a second, option B from
26.1 to 16.0. That looked like a cost of the change, so it was checked properly
rather than assumed either way: the page was built twice, once with the bottom
layer and once without, and measurement 7 was taken from the two builds
alternately, five times each, so that a machine having a slow few minutes could
not favour one. The medians came out **14.7 against 16.0 at twenty positions and
12.0 against 11.6 at two hundred** — the two builds swapping places, with single
readings ranging from 10.2 to 16.4 within one build. So the fall is the machine
and not the change, and a difference of this size in row 7 means nothing at all
unless it is taken this way.

The same caution belongs on row 6 for option B, which went from 826 requests to
723 between the two runs while the bounded figure held at exactly 36. The
unbounded reading waits for the requests to go quiet and then stops, so it counts
however many the engine had got round to asking for; the bounded one is settled by
the coverage record and is steady. Read the bounded numbers as the measurement and
the unbounded ones as the order of magnitude.

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

### The canvas now has a bottom layer, and one of the three cannot honour it

`viz_studio/THE_CANVAS.md` describes the front end's main surface as three layers
sharing one coordinate system: the application's own drawing beneath the picture,
the picture in the middle, and the operator's marks above. Until recently the
interface had only the top of those, so every option drew all of the operator's
geometry on one sheet above the engine and cut holes in it. That is still what
rows 1 to 7 describe, deliberately, because it is what an engine with an opaque
canvas obliges an application into and because all three options drawing the same
thing is what makes them comparable.

The interface now has the bottom slot as well — `drawUnder(paint)` beside
`drawOver(paint)`, taking the same kind of function, called at the same moment
with the same view — and rows **0b** and **1b** report what each option does with
it. Two questions are asked and they are separate promises:

- **Is a drawing put there really beneath the picture?** Measured by drawing one
  flat colour in the bottom slot and photographing the window. Both Viv options
  show it across 96.95% of the window; neuroglancer shows none of it and shows
  its own background across 97% instead.
- **Does it stay locked to the picture while the view moves?** Being underneath
  and staying put are different things, and a bottom layer that drifts as the
  operator pans is worse than none at all, because it looks right standing still
  and wrong the moment it is used. Measured with the same instrument as row 1,
  with the shape moved to the layer beneath: both Viv options read **0 screen
  pixels of unevenness at rest, panning, zooming and thrown about**, the same as
  their top layer. So on an engine that allows a bottom layer at all, being
  underneath costs nothing in registration.

**The option that cannot honour the slot says so rather than faking it.** Every
option publishes `viewer.drawsUnder`, and a page can ask it without knowing which
engine it is talking to. It would have been easy to have neuroglancer draw the
bottom layer *above* the picture instead, with holes cut wherever the run has
imaged, so that the page looked the same under all three — and that was
deliberately not done. Two options that looked identical while doing entirely
different things underneath would make this whole table a lie, which is precisely
the kind of silent difference the table exists to prevent. Option A paints the
drawing where it belongs, the engine covers it, and the row reads **no**.

Row 1b reads "not applicable" for option A rather than a number, for the same
reason: there was nothing of the bottom layer on screen to measure, and a nought
would read as "perfectly lined up".

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
| *measured* | 2026-07-31 11:27 | 2026-07-31 11:14 | 2026-07-31 11:16 |
| **0. Can a surface underneath the engine be seen?** | **no** | yes | yes |
| **0b. Is the bottom layer genuinely beneath the picture?** | **no** | yes | yes |
|   … a colour drawn there fills this share of the window | 0.0 | 0.9695 | 0.9695 |
|   … the same colour drawn in the top slot instead (must be large) | 1.0 | 1.0 | 1.0 |
| **1. Registration** — worst unevenness at rest (screen px) | 1.0 | 0.0 | 0.0 |
|   … while panning | 1.0 | 0.0 | 0.0 |
|   … while zooming | 1.0 | 0.0 | 0.0 |
|   … thrown about | 1.0 | 0.0 | 0.0 |
|   … with the hole moved 8 px on purpose (must be large) | 17.0 | 16.0 | 16.0 |
| **1b. Registration of the bottom layer** — worst unevenness at rest (screen px) | not applicable | 0.0 | 0.0 |
|   … while panning | not applicable | 0.0 | 0.0 |
|   … while zooming | not applicable | 0.0 | 0.0 |
|   … thrown about | not applicable | 0.0 | 0.0 |
|   … with the ring moved 8 px on purpose (must be large) | not applicable | 16.0 | 16.0 |
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
| **5c. The picture survives the refresh** — seconds before it is back | 0.12 | 0.25 | 0.18 |
|   … what the window showed while it refreshed | [0.2726, 0.2726] | [0.2734, 0.2734, 0.2734, 0.2734] | [0.2734, 0.2734, 0.2734, 0.2734] |
| **5d. The view stays put** — centre moved (µm) | 0.0 | 0 | 0.0 |
| **5e. How soon a tile shows** (seconds) | 0.37 | 0.36 | 0.22 |
| **5f. Does it keep up** — frames a second, first round → last | 5.2 → 5.6 | 5.6 → 4.8 | 5.2 → 5.6 |
|   … tiles written meanwhile | 438 | 426 | 441 |
| **6. Requests** — to redraw one view, unbounded | 117 | 723 | 432 |
|   … of those, for ground nobody imaged | 108 | 678 | 396 |
|   … bounded by the coverage record | 25 | 36 | 100 |
|   … of those, for ground nobody imaged | 16 | 0 | 64 |
| **7. Drawing rate** — frames a second at 20 positions | 18.0 | 8.2 | 16.0 |
|   … at 200 positions | 11.2 | 6.9 | 12.1 |

<!-- end of the generated table -->

---

## What the rows mean

**0. Showing through.** Described above. The check was shown able to give the
other answer: with the option's own surfaces hidden, the colour behind filled
100% of the window.

Note that rows 0 and 0b are asking the same physics of two different things, and
the pair is more useful than either alone — see 0b below.

**0b. Is the bottom layer genuinely beneath the picture?** The same physics as row
0, asked of the slot an application actually writes against. Row 0 paints a colour
on the *box* the viewer was opened inside and asks whether it shows through; this
one hands a colour to `drawUnder(paint)`, which is what an application would do,
and asks the same question of the result. They can come apart, because an option
could implement the slot and then not honour it, and that is why both are here.

The check was shown able to give the other answer, and the way it was shown is the
part worth reading. **The same flat colour, painted by the same drawing function
on the same page, was handed to the top slot instead.** Every option then showed
it filling 100% of the window — including the one that had shown none of it a
moment before. So the reading means "which slot", not "which colour", and it
cannot be explained by a drawing that never ran or by a counting program that can
only answer nought.

The measurement is taken with the drawn region *unbounded*, and that matters more
here than anywhere else. Bounded to the coverage record, the engine's surface
covers only the part of the window holding imaged ground, so a colour drawn
beneath would be seen all around it — which is a fact about the size of a box
rather than about whether a surface lets light through, and it would read as a yes
on an engine that is really a no.

**1b. Registration of the bottom layer.** Row 1 asked whether the layer *above*
the picture stays lined up with it. This asks the same of the layer *below*, and
it is the second half of what a shared coordinate system promises: all three
layers pan and zoom together, or the canvas is not one canvas.

The instrument is the same and `viz_studio/tests/margins.py` reads it unchanged.
Only the shape moves: a rectangle of colour is drawn beneath the picture a little
way outside the imaged square, so a cut across the photograph meets the ring, a
band of background, the picture, a band of background and the ring again — the
same four things row 1 reads, in the same order. The ring is drawn narrow enough
to stay inside the rectangle the engine is given, which is what makes "there is
none of it on screen" a truthful answer for an engine that covers what is behind
it, rather than a reading taken off the edge of the engine's own box.

The last row of the group is the red evidence, and it is the same breakage row 1
uses applied to the other slot: the ring moved two pixels reads 4, and eight
pixels reads 16, on the same page with nothing else changed.

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

## Surprises worth passing on

**The two Viv options cannot live in one page at the same time.** The harness can
now change engine without losing the view — press `o`, and the centre, the
magnification, the plane, the moment and the channel settings all carry over, so
the same view can be looked at through two engines seconds apart. That works
between neuroglancer and either Viv option, in both directions, with the centre
measured as moving 0 µm and the zoom unchanged.

It does not work between the two Viv options, and the reason is not about drawing
at all. They are installed from two different lists of packages — one borrows the
viewer's own, the other keeps a list beside itself — and the versions of deck.gl
underneath them differ. deck.gl refuses outright to have two versions of itself
alive in one page and says so: "multiple versions detected: 9.3.3 vs 9.3.7". The
harness catches that, puts the engine that was working back on the same view, and
writes the reason in the corner rather than going blank; pressing `o` again steps
over the one that will not open and reaches the third.

It is recorded here rather than fixed, because fixing it means choosing one
version of deck.gl for both options — which would change which version of the
engine half of this table describes. That is a real decision and not one to take
by accident while adding a keystroke.

## Four surprises from building the options

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
