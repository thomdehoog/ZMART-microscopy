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

**And the drawing rate wanders a great deal between one reading and the next**,
which is worth knowing before anybody reads a change in it as a change in the
code. It wandered enough that row 7 used to be misleading, so the row has been
changed, and the story is worth telling because it is the reason for the
brackets in it.

Row 7 fell for all three options between the run of one morning and the run that
added the bottom layer — option A from 24.8 to 18.0 frames a second, option B
from 26.1 to 16.0. That looked like a cost of the change, so it was checked
rather than assumed: the page was built twice, once with the bottom layer and
once without, and measurement 7 was taken from the two builds alternately, five
times each, so that a machine having a slow few minutes could not favour one. The
medians came out 14.7 against 16.0 at twenty positions and 12.0 against 11.6 at
two hundred — the two builds swapping places, with single readings ranging from
10.2 to 16.4 within one build. The fall was the machine and not the change.

That was written down but the table went on reporting a single reading, which
invited exactly the comparison it could not support. Taken five times over on one
unchanged build, single readings have ranged from 4.8 to 10.3 on the same option
at the same number of positions — a factor of two — while two options a reader
would want to compare sat within a few tenths of each other. **So row 7 now
reports the middle of five readings with the lowest and highest beside it**, and
two columns whose ranges overlap have not been shown to differ, however far apart
their middle values fall.

Two runs of the new row a quarter of an hour apart show why that had to be said
out loud. In the first, options A and B overlapped at twenty positions and were
almost apart at two hundred; in the second, taken with no change to any of the
three, they were apart at twenty and lay exactly on top of each other at two
hundred. **Option C is the only column that is plainly and repeatedly slower
than the others**, at both counts, in both runs. Everything else about row 7 is
this machine having a good minute or a bad one.

The same caution belongs on row 6 for option B, which has read 826, 723 and 688
requests on different runs while the bounded figure held at exactly 36 every
time. The unbounded reading waits for the requests to go quiet and then stops, so
it counts however many the engine had got round to asking for; the bounded one is
settled by the coverage record and is steady. Read the bounded numbers as the
measurement and the unbounded ones as the order of magnitude.

### Every row was broken on purpose to see whether it would notice

A table of numbers reads as evidence whether or not it is, so each measurement
here has been made to fail deliberately, by breaking the thing it claims to
watch, and the breakages are listed under each row below. Three of them were not
noticed at first, and all three have been fixed:

- **Row 0b** said yes to an option that drew the bottom layer *above* the
  picture. It asked only whether the colour appeared, and a colour on top appears
  just as well as a colour underneath. It now also asks whether the acquired
  picture is still showing, which a colour on top hides completely.
- **Row 4** said "the picture shows" on a page with no acquired picture on screen
  at all. It counts near-white pixels, and the operator's own pale carrier
  outline is near-white enough to pass the test on its own. The same window is
  now photographed twice, once with every channel switched off, and the reported
  share is the difference.
- **Row 7** reported a single reading of a number that varies by a factor of two
  on an unchanged build. It now reports the middle of five with the spread beside
  it.

One thing the table still cannot see is recorded under the row it belongs to: row
3 cannot tell an engine whose gestures were taken away from an engine that never
receives them.

**A second one used to be recorded there and now has a row of its own.** The
registration rows were blind to the two layers agreeing about where the centre of
the picture is and disagreeing about how *large* everything around it should be,
because that leaves all four margins equal and the reading is the unevenness of
the four. Row 1c is the number that catches it, it is reported beside row 1
rather than instead of it, and the two are not interchangeable: one sees the
layers sliding apart and is deaf to a wrong size, the other sees a wrong size and
is deaf to sliding apart. Row 1c below sets out how it is worked out and shows it
catching a drawing made two per cent too large while the unevenness sits at
nought throughout.

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
when the lower layer was taken away, and to `255, 0, 0` when the little program
the engine runs on the graphics card to decide each spot's colour — a shader, in
the engines' own word — was made to paint the upper layer opaque on purpose. So the honest statement of both findings
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

### A run's own colours are read from the store, and this is not a row

`viz_studio/options/contract.md` §6 now makes `channels` optional: a page that
says nothing about an acquisition's colours gets the run's own description read
out of the store instead of a single white channel. The fault behind that change
was plain — a run recorded in two colours showed only its first one, in white —
and it is checked against a photograph in
`viz_studio/tests/test_the_options_hold_together.py`, on a two-channel
acquisition written for the purpose.

**It is deliberately not a row in the table**, and the reason is worth saying so
that nobody adds one later without thinking. The table compares three engines, and
a row of three identical yeses compares nothing. Every option reads the same
description in the same way — the four functions that do it are word for word the
same in all three — so on this question there is nothing between them to report.
What differs is how hard each of them had to work to get there, and that is
prose rather than a number; it is under "Five surprises" below.

The readings, taken the same day as this note, on the two-colour square with the
picture framed the way every measurement here frames it: with the page saying
nothing, **4.78% of the window came out green and 4.74% red for option A, and
4.80% and 4.79% for options B and C** — the two halves of the square, each in
the colour the run names. With the page describing the acquisition itself, as one
white channel, all three showed **no green and no red at all** and about 4.7% of
the window near white. Reading the store is what happens when the page says
nothing; it never overrules a page that speaks.

### Nothing had ever opened two acquisitions, and two of the three were wrong

Every row above 8 is measured on a single run. The arrangement this project is
actually built around is two — a wide survey of the whole specimen and a detailed
scan of the part worth looking at closely — and until row 8 was written, no
measurement and no test anywhere had ever asked an option to open two at once.

Asked for the first time, **two of the three drew the detailed scan 898
micrometres from where its store says it is**: the whole run, at exactly the right
size and perfectly sharp, over the wrong part of the slide. The reason it had
gone unnoticed for so long is the reason it is worth writing down. Two images
written at different voxel sizes have nothing in common but the position each of
them states in micrometres, and on a single acquisition written from the stage's
zero that position is nought — so a viewer that never reads it looks perfectly
correct on every other row in this table.

Both were put right, both now read **0.0 µm**, and the measurement was shown able
to fail by moving one run's stated position 64 µm and watching all three notice it
at the right size. Row 8 below has the arrangement, the numbers and what the row
deliberately does not ask.

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
| *measured* | 2026-07-31 12:46 | 2026-07-31 12:48 | 2026-07-31 12:51 |
| **0. Can a surface underneath the engine be seen?** | **no** | yes | yes |
| **0b. Is the bottom layer genuinely beneath the picture?** | **no** | yes | yes |
|   … a colour drawn there fills this share of the window | 0.0 | 0.9695 | 0.9695 |
|   … and the acquired picture is still showing on top of it | yes | yes | yes |
|   … the same colour drawn in the top slot instead (must be large) | 1.0 | 1.0 | 1.0 |
|   … which must hide the picture, and does (share left showing) | 0.0 | 0.0 | 0.0 |
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
| **4. Sparseness** — share of the window showing picture | 0.0111 | 0.0112 | 0.0112 |
|   … the same count with every channel switched off (must be small) | 0.0041 | 0.0041 | 0.0041 |
|   … the operator's plan shows through the gaps | yes | yes | yes |
| **5a. New data appears at all** | yes | yes | yes |
|   … the option's own count of what it sent back (a different thing in each) | 3 | 3 | 3 |
| **5b. What the refresh costs** — pieces re-fetched | 4 | 3 | 4 |
| **5c. The picture survives the refresh** — seconds before it is back | 0.12 | 0.4 | 0.2 |
|   … what the window showed while it refreshed | [0.2726, 0.2726, 0.2726] | [0.2734, 0.2734, 0.2734, 0.2734] | [0.2734, 0.2734, 0.2734] |
| **5d. The view stays put** — centre moved (µm) | 0.0 | 0 | 0.0 |
| **5e. How soon a tile shows** (seconds) | 0.43 | 0.62 | 0.46 |
| **5f. Does it keep up** — frames a second, first round → last | 5.2 → 5.2 | 3.5 → 4.5 | 5.2 → 5.2 |
|   … tiles written meanwhile | 426 | 512 | 414 |
| **6. Requests** — to redraw one view, unbounded | 117 | 688 | 432 |
|   … of those, for ground nobody imaged | 108 | 643 | 396 |
|   … bounded by the coverage record | 25 | 36 | 100 |
|   … of those, for ground nobody imaged | 16 | 0 | 64 |
| **7. Drawing rate** — frames a second at 20 positions, middle of five | 13.5 (12.3–14.0) | 5.6 (4.9–6.2) | 10.9 (10.0–11.6) |
|   … at 200 positions, middle of five | 9.1 (8.4–10.5) | 4.5 (4.2–5.0) | 9.2 (8.4–9.9) |

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

**That was not enough on its own, and finding out why is the most useful thing in
this row.** Option C was deliberately changed to put its bottom layer at the end
of its list of layers instead of the beginning — that is, to draw the thing
handed to `drawUnder` *over* the picture rather than under it, which is exactly
the fake `contract.md` §4a forbids. The row went on reading **yes**, and its
prose went on saying "the application's own drawing really does sit beneath the
picture", because a colour on top fills the window just as well as a colour
underneath. The only sign in the whole table was the share moving from 0.9695 to
1.0, which nobody would read as a fault.

So the row now asks a second question of the same photograph: **is the acquired
picture still showing on top of the colour?** Underneath, it is — 2.95% of the
window, exactly what it is with nothing drawn at all. On top, it is not — the
colour has covered it and the picture reads nought. Both readings are in the
table, and against the deliberately faked option the row now reads no, with a
sentence saying which half it failed. The same second question is what makes the
top-slot check mean something: a colour in the top slot must both fill the window
and hide the picture.

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
that has never been seen to fail is not evidence of anything, and this one has
been shown to fail against a real fault as well as against a nudged hole: with
option B changed to paint the operator's drawing from the frame *before* the one
being shown — the classic follower fault — the row went from 0 to 10 while
panning and 24 while thrown about.

**What this number cannot see**, and it is worth knowing before leaning on a
nought. Unevenness is the difference between the widest side and the narrowest,
so it catches the two layers sitting in different *places*. If instead they agree
about position and disagree about *magnification*, all four sides grow or shrink
together and the difference between them stays at nought. That is not a small
blind spot. An outline drawn a couple of per cent too large around a tile is
plainly wrong to look at, and this number would have gone on reading nought while
an operator looked at it.

Displacement is still the fault this arrangement is actually prone to, so it is
still the headline. The other question now has a reading of its own beside it,
and it is row 1c.

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

**1c. A disagreement about size.** The other half of the question row 1 asks, and
a separate number because no single number can do both jobs.

The band around the picture is cut a fixed forty browser pixels wider than the
imaged square on every side. Row 1 reads how *uneven* the four sides are, which
goes wrong the moment the two layers sit in different places. This row reads what
the unevenness is deaf to: how much wider the band came out **all round** than
the forty it was cut at. It is worked out by averaging each pair of opposite
sides and comparing that average with forty — and averaging a pair is exactly
what makes it deaf to displacement in return, because sliding the drawing
sideways takes from one margin what it gives the one opposite and leaves their
average where it was. So the two readings are independent by construction, and a
reader needs both.

**The information was already being recorded; the number was not**, and it is
worth being precise about that, because "we were already measuring it" and "we
were already reporting it" are different claims. Every side of the band has
always been written into `measurements/<option>.json`, at rest and as a worst
departure from the width it was cut at, so this was largely a matter of reporting
rather than of measuring — the cheaper of the two answers. But not purely. The
per-side departures that were already there **conflate the two faults**: a side
three pixels wide of forty is three pixels wide either because the drawing has
moved or because it is the wrong size, and that number cannot say which. Taking
the two opposite sides together is what separates them, and that arithmetic is
new.

**The red evidence, which is the point of the row.** The page was made to draw
everything of its own at 1.01 and then 1.02 times its proper size, about the
middle of the window, leaving the picture exactly where it is. That is not an
invented fault: an option whose conversion from micrometres to screen pixels was
slightly wrong would look precisely like this. Nothing else on the page changed,
and both readings were taken from each photograph. **On every option the
unevenness stayed at 0.0 at both scales**, exactly as the paragraph under row 1
says it would, **while this reading rose from 1 to 2 and then to 3 screen
pixels.** The contrast is the finding: the headline number cannot see this fault
at all, and the new one sees it at one per cent.

The *size* of the rise is checked as well as its direction, because a number that
merely moves is not evidence — a check that reported something wrong whenever
anything changed could not tell a hairline from a disaster. The imaged square is
about 243 photograph pixels across, so drawing it two per cent too large pushes
each of its edges out by one per cent of that, which is 2.4 pixels; the reading
rose by 2. At one per cent the arithmetic says 1.2 and the reading rose by 1.
Both numbers are in the table beside each other.

**One is this reading's own floor rather than a disagreement**, and all three
options read 1 with nothing broken at all. Every edge here is found as the gap
between the last pixel that is definitely one thing and the first that is
definitely the next, so the softly lit pixel between them is left out on both
sides and the band comes out about a pixel wider than it was cut. That floor is
what sets the smallest disagreement this can resolve — around half a per cent on
a square this size, and less on a larger one, because the error grows with the
square while the floor does not.

**What it cannot tell apart**, and this matters on a slow disk. A picture whose
pieces have not all arrived is genuinely smaller than the ground it was written
on, so the band around it is genuinely wider — and that looks here exactly like a
disagreement about size. It is nothing of the kind; it is an operator waiting for
their data. So the reading taken during a gesture is the **least** the band was
ever wider over the frames of that gesture, which is the opposite of every other
number in this table and is deliberate: a real disagreement about size is in
every frame, while a frame of half-arrived picture can only inflate a single
reading and cannot lower the least of them.

**2. Handedness.** The picture runs uphill to the right at 91 grey levels per
hundred pixels, which is the specimen the way round it really is. The separate
dragging check reads +1.0, meaning the picture goes with the hand. Both are
needed and neither replaces the other: dragging reads +1.0 whichever way round
the picture is drawn, because an engine pans using the same axis mapping it draws
with. Only something asymmetric inside the specimen can say which way round it is.

The row was shown able to give the other answer. With option B's picture mirrored
left to right on purpose, the brightness slope went from +91.5 to **−91.5** and
"the bright edge is on the right" read no — while the dragging check went on
reading +1.0, exactly as the paragraph above says it would. That is as clear a
demonstration as one could want that the dragging check cannot do this job.

**3. Two gestures.** Nine gestures that used to move the view were each made in
earnest and each left the picture byte-identical. The page also reports what it
turned away — one shift-drag, one right-button click, three ctrl-wheels and
twenty-two key presses — which is what stops this passing on a page that had
quietly stopped listening altogether.

The row was shown able to give the other answer: with shift-and-drag allowed to
pan again in `harness/src/gestures.js`, it read **1: shift and drag (used to
rotate)** on the next run.

**What it cannot tell apart, which matters for one line of option A.** Option A
also empties neuroglancer's own table of gestures, and its comment calls that
belt as well as braces. That is exactly right, and this row cannot say which of
the two is doing the work: with the emptying taken out altogether, every one of
the nine gestures still left the picture byte-identical. The engine never
receives them in the first place — its box is transparent to the mouse, and it
listens for keys on an element that never has the keyboard's attention. So the
emptying is insurance against a future stylesheet edit rather than something this
table can show working, and it should be kept for that reason rather than because
a number here would notice if it went.

**4. Sparseness.** Five patches imaged on a canvas mostly never visited, seen from
far enough out to have the whole carrier in the window. Picture where picture was
written, the operator's plan everywhere else.

**The number in this row used to be a little too large, and the check behind it
could not fail.** The counting finds near-white pixels, on the reasoning that the
acquired picture is near-white and the operator's drawing is dark. The operator's
carrier outline is a pale line, and pale enough to be counted as picture: on its
own it fills 0.41% of the window, which was more than the 0.2% the check asked
for. So with the holes in the operator's sheet deliberately not cut at all — no
acquired picture reaching the screen anywhere — the row still read "the picture
shows".

The same window is now photographed twice, once with every channel switched off
through the interface, and the share reported is the difference between the two.
That does two jobs at once. The headline number is now the picture alone, which
is why this row reads 0.0111 where it used to read 0.0152. And the second reading
is the red evidence, reported in the table beside it: with the picture switched
off the share falls to 0.0041, and against the uncut-holes breakage the row now
reads 0.0000 and "the picture shows" reads no.

**5. New data arriving.** The one that matters most, and it has six parts.

- *Does it appear at all.* Eight tiles were written into ground the viewer had
  already looked at and found empty. **Nothing appeared** — the share of the
  window showing picture did not move at all, from 0.0953 to 0.0953. Not slow: no
  request was made, ever. What made it appear was one call,
  `tilesMayHaveLanded({coverage})`, which sends the option back to the store to
  read what is there now, and the share went to 0.2726. How an option goes back
  differs and the page never knows: the two Viv options open a fresh reader on
  the store, and option A tells neuroglancer's background worker to read its
  three resolution levels again.

  The row beneath it — *the option's own count of what it sent back* — reads 3 in
  every column and **must not be read across them**, which is why the row now
  says so in its own name. It is the only number in this table that is the
  option's own account of its own work rather than something read off a
  photograph or counted by the server. For the two Viv options it is how many
  copies of the image the freshly opened reader has, which is three because the
  writer makes a pyramid of three; for option A it is how many of the engine's
  own stores of decoded picture were told to let go, which is also three and for
  an unrelated reason. It is kept for one narrow job: telling "the option was
  asked and nothing happened" apart from "the option was never asked", which look
  identical on screen. It cannot do more than that, and it was shown not to:
  with option B's refresh deliberately made to hand the fresh readers nowhere,
  this row went on reading 3 while the window never changed, "new data appears at
  all" read no, and the pieces re-fetched fell to nought. **Row 5b is the number
  to compare**, because the server counted it.
- *What the refresh costs.* Four pieces of image re-fetched for option A, three
  of which held picture. That number follows the size of the window rather than the size of the
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
- *How soon.* Between a fifth and two thirds of a second from the tile being
  safely on disk to the window being measurably brighter — see row 5e for the
  reading each option last gave. It includes the time spent photographing, so it
  is an upper bound rather than a best case.
- *Does it keep up.* Four hundred-odd tiles written during the measurement while
  the view was panned and zoomed throughout, with a refresh in every round. The
  drawing rate over the six rounds is flat rather than falling for every option,
  which is the answer this asks for: a viewer that fell progressively further
  behind a run would show it here. Row 5f carries the first round and the last
  for each option, and the whole series is in `measurements/<option>.json`.
  Read it the way row 7 asks to be read — these are single readings of a number
  that wanders, so what matters is the shape of the six and not any one of them.

  Two parts of this were shown able to fail. With option A's picture-keeping
  taken out, "does the picture survive the refresh" read
  `[0.2726, 0.0000, 0.0000]` — the blink, back. With option C's refresh made to
  drag the view sideways on purpose, "the view stays put" read 50.155 µm and the
  edge of the picture on screen moved 12 photograph pixels, so the reading from
  the numbers and the reading from the photograph agreed.

**6. Requests.** On the sparse canvas — a large declared room with a small imaged
patch, which is the shape a real run has — a complete redraw cost **117 requests,
108 of them for ground nobody had imaged**. Bounded to the coverage record, the
same redraw cost **25, of which 16 were wasted**. Almost the whole cost of a
redraw is asking about ground the microscope has never been to, and the record is
what stops it.

Shown able to fail: with option A's bounding switched off in the adapter, the
bounded reading came out at 117 — exactly the unbounded one, which is what it
should be when the record is doing nothing.

**7. Drawing rate.** The cost of the operator's drawing growing with the number
of tile rectangles on it, which is exactly where drawing in two surfaces and
drawing in one should differ.

**Read the brackets before the number.** Each reading is the middle of five
three-second pans taken on the same page, and the pair beside it is the lowest
and the highest of those five. That is not decoration: a single reading of this
has been seen to vary by a factor of two on an unchanged build, so a difference
smaller than the spread means nothing whatever.

Only two things in this row have held across repeated runs. **Option C is slower
than the other two**, at both counts, by more than the spread. And **every option
draws more slowly with two hundred rectangles than with twenty**, which is the
cost the row exists to show. Whether options A and B differ from one another has
come out both ways on runs a quarter of an hour apart, which is the honest answer:
not shown either way on this machine.

And the whole row describes this machine, which has no graphics card. It says
"does the cost grow", not "is it fast enough".

**8. Two acquisitions at once.** A wide survey and a detailed scan over part of
it, opened together. This is the ordinary arrangement smart microscopy is built
around, and until this row existed **nothing in this suite had ever asked an
option to open two acquisitions at all** — no measurement and no test. Every
number above it was taken on a single run.

That gap matters more than "one measurement missing" suggests, and the reason is
worth reading before the numbers. Two runs written at different voxel sizes have
nothing whatever in common except the position each of them states in
micrometres. Nothing about the pixels themselves lines them up. And on a single
acquisition the question never arises: a run written from the stage's zero is
drawn in the right place whether its stated position was read or not, so a viewer
that ignores the position entirely looks perfectly correct on every other row in
this table.

**The arrangement.** The survey is imaged edge to edge at four micrometres to the
voxel over two millimetres of specimen, and it names its colour green. In the
middle of it is one square of ground 512 µm across that it deliberately never
visits — a plain window in the picture, and the known feature everything else is
measured against. The detail scan is written at half a micrometre to the voxel,
eight times finer, it names its colour red, and it states a position that puts it
centred in that window with 128 µm of empty ground between it and the survey on
every side. A viewer that places the two by physical coordinates alone shows a red
square in the middle of the green window with an even band all round it, and the
band is the reading.

**Everything comes from the photograph, including the scale.** The survey is a
known number of micrometres across, so how many pixels of green there are says
what one photograph pixel is worth; the unimaged window is a known 512 µm across
and says the same at the closer magnification. Nothing here is taken from what an
engine reports about its own view, which matters especially in this row, because
an engine that has placed a run wrongly will report its own view perfectly
confidently.

**Two of the three drew the detail scan 898 micrometres from where its store says
it is, and that is the most useful thing in this row.** Both Viv options placed
it at the survey's own corner — the whole detail scan, drawn at exactly the right
size and perfectly sharp, over the wrong part of the specimen. The cause was one
omission in each of them. Both had a function whose job is to put a second
acquisition into the world the first one defines, and both **stretched** the
second onto the first's voxel size and never **moved** it: the position each run
states in its own description was read by nobody. Neuroglancer reads that
description itself and was right from the first reading — 1.0 µm departure from
the expected 128 µm band, which is well inside half of the survey's own
four-micrometre voxel.

It has been put right rather than only reported, because the fix is small and of
a piece with what those functions already did. Each Viv option now reads the
position out of the store's own description exactly as it already read the size
of a voxel, and places every acquisition in a world whose unit is the first run's
voxel and whose zero is the stage's zero. The functions say so at length —
`placementOf` in `viv-under/viewer.js` and `stretchOntoTheSameWorld` in
`viv-inside/viewer.js`. Measured after the change, both read a worst departure of
**0.0 µm** from the 128 µm band, and the table carries the readings for all three.

For a run written from the stage's zero, which is every other acquisition in this
suite, the placement is the identity and nothing at all changed — which is why no
other number in the table moved.

**The red evidence.** The detail scan's *stated* position was moved 64
micrometres along, in its own description on disk, with not a voxel of its
picture touched and the survey left alone. That is exactly the fault a run with a
mistaken stage position would have. All three options then drew it 63 to 64.4 µm
out of place, and the band that should have been even all round came out about
191 µm on one side and about 64 on the other — the move noticed, and noticed at
the right *size*, which is the part that matters. A check that reported something
wrong whenever anything changed would pass this without being able to tell a
hair's breadth from half a specimen.

**Two things this row deliberately does not ask**, so that nobody reads more into
it than it says.

- **It does not bound the drawn region to the coverage record.** The interface
  takes one coverage record for the whole viewer, and a record counts in voxels
  of one particular image — so as things stand it cannot describe two runs whose
  voxels are different sizes. That is a real limitation of the interface rather
  than of any engine, it is the next thing to settle for anyone building on this,
  and measuring around it was better than measuring something that would have
  meant three different things in three columns.
- **It does not say the two are sharp to better than a photograph pixel.** The
  detail scan measures 251 to 252 µm across where it should be 256, on all three
  options, and that is the reading rather than the picture: the bounding box is
  taken from pixels that are *definitely* red, so the softly lit pixel at each
  edge is left out on both sides, which at three micrometres to the pixel comes
  to the few micrometres missing. The band measurement is taken at one micrometre
  to the pixel for exactly that reason.

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

## Five surprises from building the options

**Reading the run's own colours was free for the two Viv options and awkward for
neuroglancer, and it turned up two further faults in the neuroglancer adapter on
the way.** This is the one genuine difference between the engines behind the note
above, and it is worth knowing before somebody adds a fourth option.

Viv hands a store's whole description back alongside the picture, so options B
and C already had it in their hands: reading the channels out of it is a few
lines and costs no extra request at all. Neuroglancer reads the same description
— it has to, in order to build a layer — but keeps it to itself, giving back a
layer rather than the text the layer was built from. So option A has to go and
fetch the description itself, which is one small extra request per acquisition
when the viewer opens. That is the whole of the cost, and it is worth paying, but
it is a real difference in how much an engine will tell you about what it just
read.

The two further faults were both invisible until something with more than one
channel was actually drawn, because until now every acquisition in the suite had
exactly one white channel and every page said so.

- **Both of a two-channel run's layers drew the same channel.** Which channel a
  layer reads was being written onto the layer just after it was made, and a
  layer made a moment ago does not yet know what dimensions its data has, so the
  position was written into a space with no room in it and simply lost. Said
  instead in the description the layer is built from, it takes. Measured before
  the fix: one colour missing altogether and the other drawn twice.
- **The second channel reached the screen at half strength.** Neuroglancer's own
  default for an image layer is to be half see-through, which is right for
  looking through one layer at another and wrong for the channels of one
  acquisition. Measured: the second channel came out at 118 of a possible 255
  where the first came out at 237 — the colour the run names, watered down for no
  reason an operator could see.

Options B and C needed neither fix; they name the channel they read and draw each
at full strength already.

**Following the pointer did not come apart, on this machine.** The sandwich
probe's write-up — `viz_studio/SANDWICH.md`, which is not on this branch but on
`claude/sandwich-probe`, commit `1277e30` —
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
which `viz_studio/SANDWICH.md` §7 records as a loss of sharpness — again on
`claude/sandwich-probe`, commit `1277e30`. Measured here at a screen
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
