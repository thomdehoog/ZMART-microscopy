# The layered view: what is here, and how to take it

> **This lifting has since happened.** The operator window and the layered view
> now live together on this branch, and the source tree has been reorganised —
> the canvas files named below now sit in
> `application/src/application/parts/canvas/` (with `panel.js`
> renamed `viewer.js`), and `application/src/workflows/README.md` maps the whole
> arrangement. The rest of this document is kept as the record of what was
> built and why; read the paths in it as the paths of that time.

This branch holds one thing: **a picture that scales to ten thousand fields, and
a stack of layers above it that a workflow decides.** It is meant to be lifted
into whichever operator window you are actually working in, rather than merged
wholesale — the operator window on this branch is not the one you have been
editing, and that is exactly why this is separate.

Everything here is tested and photographed. Nothing here touches the driver, the
controller, `index.html`, `main.js`, or the step catalogue.

---

## What to copy, exactly

Two halves. **They are independent** — the JPEG viewer works under any canvas,
and the layer stack works over any engine — so you can take one without the
other, and neither one needs anything else on this branch.

### Half one — the JPEG viewer (5 files, no dependencies outside `viz_studio/`)

```
viz_studio/backend/jpeg_tiles.py                 make the pictures        NEW
viz_studio/backend/mock_scan.py                  a microscope to test on  NEW
viz_studio/options/jpeg-under/viewer.js          draw them                NEW
viz_studio/tests/test_small_pictures_from_exported_tiffs.py               NEW
viz_studio/tests/test_the_jpeg_viewer_holds_ten_thousand.py               NEW
```

Needs, and none of these were changed: `viz_studio/options/gestures.js` (which
the engine imports for panning and zooming), `viz_studio/options/contract.md`
(the interface it keeps), and `numpy`, `tifffile`, `Pillow` for the making.

To offer it in a page, one line per list in that page's engine registry — on
this branch that is `application/src/canvas/engines.js`, where `jpeg-under` was
added to `HOW_TO_OPEN` and `WHAT_IT_IS`. **Nothing else in that file changed
except a paragraph of comment.**

### Half two — the layered view (2 files new, 2 edited)

```
application/src/canvas/layers-above.js             the whole idea, ~140 lines   NEW
application/tests/unit/layers-above.test.js        16 tests, no browser          NEW
application/tests/canvas-layers.spec.js            8 tests, real browser         NEW

application/src/canvas/panel.js                    the controls and the wiring  EDITED
application/src/style.css                          the fade and lock strip      EDITED
```

**`layers-above.js` is the part that matters and it depends on nothing.** No
DOM, no imports, no framework. It takes a list of layers and returns the one
paint function an engine's top slot takes. If you are integrating into a
different operator window, this file moves across untouched and you write your
own controls around it.

`panel.js` is where the buttons, the fade slider, the lock and the click routing
live. Its changes are worth reading rather than copying if your canvas panel is
a different file — the parts to look for are `buildTheLayerButtons`,
`showTheLayer`, `fadeTo`, `seeThrough`, `setLayersAbove`, and the pointer
listeners near `A_PRESS_THAT_DID_NOT_TRAVEL`.

One change in `panel.js` is not about layers at all and is worth keeping either
way: **the canvas now opens with no run instead of refusing.** The first steps
of a workflow have nothing scanned yet and still need the canvas, because the
carrier and the positions are layers and none of them needs a picture
underneath.

### What was edited only to keep the tests honest

```
application/tests/unit/engines.test.js             the engine list is pinned on purpose
```

---

## The two halves

### 1. The picture: small JPEGs, one per field

A microscope hands us one TIFF per plane and nothing else — no pyramid, no
positions. A scan of ten thousand of those is tens of gigabytes, which is the
difference between a picture that opens and one that does not. So the small
copies are made once, before anything is drawn.

| file | what it is |
|---|---|
| `viz_studio/backend/jpeg_tiles.py` | Turns a folder of exported OME-TIFFs into one small JPEG per field, plus a `tiles.json` saying where each belongs. |
| `viz_studio/backend/mock_scan.py` | A pretend microscope export, in the driver's exact naming, so all of this can be built and measured without a machine. |
| `viz_studio/options/jpeg-under/viewer.js` | The engine that draws them. Keeps the engine interface in `viz_studio/options/contract.md` and nothing else. |
| `viz_studio/tests/test_small_pictures_from_exported_tiffs.py` | 9 tests on the making. |
| `viz_studio/tests/test_the_jpeg_viewer_holds_ten_thousand.py` | 7 tests on the drawing, in a real browser. |

**The thing that is easy to get wrong:** a TIFF does not say where it was taken.
The position has to be handed in from the run's own record. A single scan taken
from the stage's zero lands correctly whether or not anybody read a position, so
the mistake is invisible until there are two scans — at which point the second
appears at the first one's corner.

**Measured, on fields of 2048 × 2048, which is what a real microscope writes:**

| tile | 10,000 fields on disk | making | opens | panning |
|---|---|---|---|---|
| 32 px | 9 MB | 40 s | 30 ms | 60 fps |
| 64 px | 27 MB | 40 s | 20 ms | 60 fps |
| **128 px** (chosen) | **100 MB** | 40 s | 35 ms | 60 fps |
| 256 px | 389 MB | 70 s | 30 ms | 60 fps |

Tile size makes no difference to how the viewer feels. What costs is the *number*
of fields, not their pixels — so the choice is only about what the folder weighs
and how far you can zoom before it goes soft. At a hundred thousand fields,
panning the whole scan drops to about 10 frames a second whatever the tile size;
that is the honest ceiling, and the fix when you reach it is a coarser grid to
draw from when zoomed right out, not smaller JPEGs.

### 2. The layers above it

| file | what it is |
|---|---|
| `application/src/canvas/layers-above.js` | Turns a stack of layers into the single drawing the engine's top slot takes. ~140 lines, no DOM. |
| `application/src/canvas/panel.js` | The canvas panel: builds a button per layer, the shared fade, the lock, and routes clicks. |
| `application/src/canvas/engines.js` | `jpeg-under` registered alongside the other two engines. |
| `application/src/style.css` | The fade and lock strip. |
| `application/tests/unit/layers-above.test.js` | 16 unit tests. |
| `application/tests/canvas-layers.spec.js` | 8 browser tests. |

The arrangement, which is settled in `viz_studio/LAYERS.md`:

**The picture is always the bottom layer and always solid.** It is never faded
and no window is cut through it. That is not a preference — neuroglancer draws
with the graphics card into a surface of its own and cannot be made see-through,
and it is where this is heading. Since nothing is beneath the bottom layer,
transparency there would buy nothing anyway.

So everything see-through lives above it:

- **Each layer has its own fade.** A carrier outline you want faintly present and
  a set of positions you want solid are two different numbers.
- **One dial fades them all together.** "Let me see the picture" is one thought
  and should be one movement. It only ever makes things fainter.
- **A window over chosen ground**, in micrometres, opens the drawing so the
  picture shows through. This is what the fields landing during a run use: as
  each one arrives, the plan over it is opened up.
- **A window takes away every layer below it**, because what is meant to show
  through is the picture and not the next drawing down.
- **A layer marked `staysSolid` survives all of that** — drawn after the window
  is cut, untouched by the dial. Focus points are what that is for: fading the
  plan to see the picture is not a request to lose them.
- **Layers can be worked with.** Each may say what of it is at a place on the
  sample; the canvas asks from the top down, so what you can see is what your
  click reaches. A press that travelled was a pan and is not also a click.
- **The whole lot can be locked** — panning and zooming carry on, only picking
  stops. For the long stretches where an operator is reading a plan rather than
  changing one.

Inside the viewer, at the bottom, there may be **more than one picture** — the
survey of the whole slide, and the detail scans taken from places found in it.
Those are drawn or not drawn, with nothing in between. Deliberately plainer,
because that is all an engine that cannot be made see-through can promise.

---

## How a workflow uses it

```js
canvas.setLayersAbove([
  { key: "carrier",  label: "Carrier",       paint, reaches },
  { key: "tiles",    label: "Scan fields",   paint, reaches },
  { key: "heatmap",  label: "Heatmap",       paint, opacity: 0.55 },
  { key: "focus",    label: "Focus points",  paint, staysSolid: true },
  // targets appear when discovery finishes, refined targets after that
]);

canvas.seeThrough(fieldsThatHaveLanded);   // micrometres
canvas.fadeTo(0.3);                        // the shared dial
canvas.lock(true);                         // reading, not editing
```

`paint(frame)` is exactly what every canvas drawing already takes — one frame
holding the view, the box, a drawing context and a way of turning micrometres
into screen pixels. See `viz_studio/options/contract.md`.

A step hands in the whole list again rather than adding one layer at a time, and
a layer that was already there keeps whether it was being shown. The canvas is
never told which step it is in; it is told what to draw. That is what keeps it
movable from one workflow into the next.

---

## The ideas behind it, as they were settled

These were worked out in conversation and are written down because the reasoning
matters more than the code: anybody wiring this into a different window will meet
the same questions, and the answers are not obvious.

### Why the picture is solid, and everything see-through sits above it

The engine has to be at the bottom. Neuroglancer draws with the graphics card
into a surface of its own and cannot be made see-through, and it is where this is
heading. Anything that has to work with neuroglancer has to work with an opaque
bottom layer — so the JPEG viewer, which could easily have been transparent, is
deliberately built the same way rather than being allowed to depend on something
its successor cannot do.

And since nothing is beneath the bottom layer, transparency there buys nothing.
There is no picture underneath for it to reveal. A see-through engine would only
ever reveal the page's background, and in exchange the picture would become
ambiguous — half-transparent images, and no clear answer to where the engine is
see-through and where it is not. Two things would then decide what an operator
sees and neither would be readable on its own.

So: **a solid picture at the bottom, and layers above it that say exactly where
it shows through.** One place makes the decision, and it is a place that can be
stated in micrometres on the sample.

The practical prize is that none of this costs anything per engine. Per-layer
opacity, a shared fade and a window over chosen ground all belong to the
application's own drawing, and they behave identically whichever engine is
drawing underneath.

### The three kinds of transparency, and why there are three

They answer three different questions and none of them replaces another.

**A layer's own opacity** answers "how present should *this* thing be?" A carrier
outline you want faintly there and a set of positions you want solid are two
different numbers, and neither should have to move when the other does. Set once,
per layer, usually by whoever declared the layer.

**The shared dial** answers "let me see the picture." That is one thought and it
should be one movement, not a visit to every layer in turn. It multiplies what is
already there rather than replacing it, so a layer set faint stays relatively
fainter — and it only ever reduces. Turning the dial up does not make a
deliberately faint layer solid.

**A window over chosen ground** answers "let me see *these* fields." It is a list
of rectangles in micrometres, so it describes a piece of specimen rather than a
piece of screen: it travels with the sample when the view is panned and grows
when the view is magnified. This is the one the run itself drives — as each field
lands, the plan drawn over it is opened up, so the picture that just appeared can
actually be seen.

### A window cuts through everything below it

If one layer is made see-through, should the ones below go too? Here they do, and
it is not a detail. A window that only removed the top layer would reveal the
*next drawing down* rather than the picture — and revealing the picture is the
entire purpose. So a window takes away everything drawn before it.

A layer that should survive says `staysSolid: true`. It is drawn after the
windows are cut and the dial does not reach it. **Focus points are what this is
for**: they mark where the microscope will focus, they have to stay readable
whatever else is going on, and an operator fading the plan to see the picture
underneath has not asked to lose them.

That is also why the heatmap and the focus points are separate layers rather than
one drawing. Turning the heatmap off is not a request to lose the focus points
with it, and the only way to keep that promise is to make them two things.

### Inside the viewer, transparency is deliberately absent

The bottom layer can hold more than one picture — the survey of the whole slide,
and later the detail scans taken from places found in it. An operator wants
either on its own or both together, so they are kept apart and offered by name.

But they are drawn or not drawn, with nothing in between. That is not laziness;
it is the same constraint as above. An engine that cannot be made see-through
cannot promise anything else, and building a fade there would be building
something the next engine cannot honour.

### Layers are things an operator works with, not decoration

A layer may say what of it is at a given place on the sample, and the canvas asks
the layers **from the top down** — so what an operator can see is what their
click reaches. A target drawn over a position belongs to the target when you
click it, because the target is what is under the pointer. A layer that is
switched off is never asked; something invisible that still catches clicks is
among the more baffling things a page can do.

A press that *travelled* was a pan, and must not also count as a click: an
operator who drags the picture across the screen and lands on a position has not
chosen that position. A few pixels of slack, because a hand on a trackpad is
never quite still.

### The lock, and what it is really for

Interactivity can be switched off as a whole. Locked, the canvas is something to
look at: it still pans and zooms, every button still works, but a click reaches
nothing and nothing can be picked or moved by accident.

An operator spends a long time looking at a plan they have already settled —
checking it, showing it to somebody, panning around it while the run goes — and
in all that time a stray click can only do harm. It is the same idea as the lock
on any drawing tool: not a restriction, a way of putting the tools down without
putting the picture away. It starts unlocked, because a canvas that quietly
ignores clicks is a canvas an operator will decide is broken.

### The stack is not fixed, and the workflow owns it

An arbitrary number of layers, added and hidden as a run goes: where the
microscope is now, the carrier, the scan fields, the focus points, the heatmap,
the targets once discovery has found them, the refined targets after refinement,
and the acquired images after that. Each with a button, each fadeable, each
touchable.

The canvas is **never told which step it is in**. It is told what to draw, and
the step decides that. That one rule is what keeps the canvas movable from one
workflow to the next, and it is why the layer list is handed in rather than
written inside the canvas. A picture that has learned the shape of one workflow
cannot be moved into the next one without being taken apart again.

A step hands in the whole list rather than adding one layer at a time, and a
layer that was already there keeps whether it was being shown — an operator who
turned the carrier off should not find it back on because a target was discovered
somewhere else entirely.

### Which files each idea lives in

| idea | where it lives |
|---|---|
| per-layer opacity, the shared dial, windows, `staysSolid` | `layers-above.js` → `theDrawingAbove` |
| clicks find the top layer that claims them | `layers-above.js` → `whoIsAt` |
| the buttons, the fade slider, the lock, click routing | `panel.js` |
| the look of the fade and lock | `style.css` |
| the picture is solid and at the bottom | `jpeg-under/viewer.js`, and `viz_studio/LAYERS.md` for the reasoning |
| more than one picture inside the viewer | `jpeg-under/viewer.js` → `picturesInside`, `showPictureInside` |

---

## Wired into the target-acquisition window

Both halves are now in the operator window itself, not only in the comparison
panel.

**The canvas draws a stack of thirteen layers.** Everything that used to be a
run of statements with an `if` in front of it is now a layer with a name, a
control, its own fade and a click path: Background, Stage, Carrier, Tiles,
Heatmap, Plan, Cells, Targets, Focus, Test field, Editing, Where the stage is,
Scale bar. The three checkboxes that used to sit in the canvas foot are gone.

The last five stay solid — they survive the shared fade and any window, because
a reading you can half see through is a reading you cannot trust and where the
microscope actually is should never be the thing that went faint.

**The scan is drawn beneath the plan**, by `jpeg-under`, on its own surface.
Point the page at a folder of small pictures with `?picture=<folder>`.

Two things had to be true for that to work, and neither was:

- **The picture surface was on top of the plan, not beneath it**, which is why
  the two were swapped by hiding one. A picture on top can never show *through*
  the plan whatever the layers do.
- **The page's own background was painted outside the stack**, so a window cut
  through the layers left the grey sitting exactly where the picture would be.
  It is the bottom layer now, cut by the same window in the same pass.

The two surfaces are drawn by different code and agree about where things are
to within **0.0000 px**, measured at every zoom and after panning — the plan
owns the gestures and hands the view down, so they cannot argue.

### Rehearsing it without a microscope

    # 1. drive the page to a plan, and ask it where it means to send the stage
    #    (window.__theStageCanvas.plan())
    # 2. build a scan at exactly those places
    python application/workflows/target_acquisition/mock_picture.py plan.json \
        --into application/public/mock-scan --um-per-pixel 5.2
    # 3. point the page at it
    #    http://localhost:5174/?picture=/mock-scan

`mock_picture.py` writes the same filenames the Leica driver writes, one plane
per file, with the same OME description carrying the pixel size and saying
nothing about position. Only the source of the pixels is invented — so wiring a
microscope in means replacing where the pixels come from and changing nothing
else.

The positions are handed in rather than read from the files, which is the
arrangement being rehearsed as much as anything else: **a microscope's files do
not say where they were taken**, so the run's own record is the only answer.

## What is **not** done, and is the next thing

- **Where the layer controls live, and what they look like.** What is in the
  canvas foot is the machinery in the place the old checkboxes were, not a
  settled design.
- **When the ground gets opened during a run.** The mechanism works and the
  tests drive it, but nothing decides the policy for an operator yet.
- **The carrier is the one layer that is not sparse** — it fills its wells, so
  it hides the picture where no window is cut. Whether it should thin out once
  there is a picture is a design call; the window already does it.

Two smaller things also left:

- **Making the JPEGs during a run.** The helper works on a finished folder.
  Nothing calls it as fields land, and the shared brightening currently needs all
  the fields before it can be settled — that wants a decision, most likely fixing
  the two points from the first few hundred fields.
- **The microscope itself.** Everything here is against the mock, on purpose:
  wiring a microscope in means replacing `mock_scan.py` with the real export and
  changing nothing else.

---

## Running it

```
# the picture
python -m pytest viz_studio/tests/test_small_pictures_from_exported_tiffs.py \
                 viz_studio/tests/test_the_jpeg_viewer_holds_ten_thousand.py

# the layers
cd application
npx vitest run
npx playwright test tests/canvas-layers.spec.js
```

Each test was checked by putting the old behaviour back and confirming it failed.
