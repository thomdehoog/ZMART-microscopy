# The layered view: what is here, and how to take it

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
this branch that is `webapp-ui/src/canvas/engines.js`, where `jpeg-under` was
added to `HOW_TO_OPEN` and `WHAT_IT_IS`. **Nothing else in that file changed
except a paragraph of comment.**

### Half two — the layered view (2 files new, 2 edited)

```
webapp-ui/src/canvas/layers-above.js             the whole idea, ~140 lines   NEW
webapp-ui/tests/unit/layers-above.test.js        16 tests, no browser          NEW
webapp-ui/tests/canvas-layers.spec.js            8 tests, real browser         NEW

webapp-ui/src/canvas/panel.js                    the controls and the wiring  EDITED
webapp-ui/src/style.css                          the fade and lock strip      EDITED
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
webapp-ui/tests/unit/engines.test.js             the engine list is pinned on purpose
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
| `webapp-ui/src/canvas/layers-above.js` | Turns a stack of layers into the single drawing the engine's top slot takes. ~140 lines, no DOM. |
| `webapp-ui/src/canvas/panel.js` | The canvas panel: builds a button per layer, the shared fade, the lock, and routes clicks. |
| `webapp-ui/src/canvas/engines.js` | `jpeg-under` registered alongside the other two engines. |
| `webapp-ui/src/style.css` | The fade and lock strip. |
| `webapp-ui/tests/unit/layers-above.test.js` | 16 unit tests. |
| `webapp-ui/tests/canvas-layers.spec.js` | 8 browser tests. |

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

## What is **not** done, and is the next thing

`jpeg-under` and the layer stack are wired into `src/canvas/panel.js`, which is
the engine **comparison** panel. The operator window has its own canvas —
`#stage-canvas` with `#overview-canvas` (deck.gl + Viv) underneath — and its own
layer bar. Putting the picture under *that* canvas, and moving its layers onto
this stack, is the remaining work, and it belongs in whichever operator window
you are actually using.

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
cd workflows/target_acquisition/webapp-ui
npx vitest run
npx playwright test tests/canvas-layers.spec.js
```

Each test was checked by putting the old behaviour back and confirming it failed.
