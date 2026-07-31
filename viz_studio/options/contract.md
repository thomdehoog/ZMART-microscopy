# The interface all three options implement

This restates `viz_studio/OPTIONS.md` beside the code, and records the few things
that had to be settled while the first option was built. It is the document to
read before writing the second or third.

The rule underneath everything here is short. **Three viewers with three
different interfaces cannot be compared**: any difference you feel might be the
engine, or might be the way somebody happened to wire it up. Three viewers behind
an identical interface, driven by the same page and measured by the same tests,
differ only in the thing being compared. Every awkwardness below is in service of
that.

---

## What an option is

One folder, `viz_studio/options/<name>/`, holding a `viewer.js` that exports
exactly one thing:

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
 *   onViewChanged called whenever the view settles, with the same record
 *                 `whereThingsAreDrawn()` gives back
 * @returns {Promise<Viewer>}
 */
export function openViewer(element, options): Promise<Viewer>
```

and the handle:

```js
viewer.setView({ centre, zoom })   // centre in micrometres, zoom in µm per screen pixel
viewer.getView()                   // → { centre, zoom }, the view now on screen
viewer.setPlane(z)                 // which plane of the stack, in micrometres
viewer.setMoment(t)                // which moment of a timelapse, counted from the first
viewer.setChannel(index, { visible, colour, window })
viewer.drawUnder(paint)            // the application's drawing beneath the picture
viewer.drawOver(paint)             // the application's drawing above it
viewer.drawsUnder                  // true or false: is `drawUnder` really beneath?
viewer.drawsUnderBecause           // one sentence saying why it is what it is
viewer.whereThingsAreDrawn()       // the transform, for placing ordinary HTML
viewer.tilesMayHaveLanded({ coverage })   // "go and look, a tile may have arrived"
viewer.destroy()
```

Nothing else is public. Add your option's name to
`harness/src/options.js` — one line — and the page, the gestures, the drawing,
the measurements and the results table all work for it without another change.

---

## The five things that are not negotiable

### 1. Units are micrometres, everywhere

`centre` is a pair of micrometres on the stage. `zoom` is micrometres per screen
pixel. `setPlane` takes micrometres. **No option may expose an engine's private
notion of zoom**, because the moment one does, a comparison between two options
stops being a comparison of anything.

This is easy to get almost right. Neuroglancer counts in "canonical voxels per
screen pixel", where a canonical voxel is the smallest voxel among the axes on
screen — a number whose meaning changes when a different acquisition is opened.
Deck.gl counts in powers of two from a tile scheme. Both conversions belong
inside your module, in one place, and neither may reach the page.

The trap worth naming: **a wrong unit round-trips perfectly.** If `setView` and
`getView` are wrong in the same way, everything you can ask the viewer agrees
with itself and only the picture is wrong. So the check for this
(`tests/test_the_options_hold_together.py`) measures how wide the imaged ground
is *on screen* and compares it with the zoom, on a store written at a third of a
micrometre to the voxel — where counting in voxels lands three times out. It was
shown to fail on an option deliberately broken that way.

### 2. Two gestures, and the page owns them

Dragging pans; the plain wheel zooms; nothing else moves the view. The gesture
handling lives in `harness/src/gestures.js` and is attached to **the box the
viewer was opened inside**, not to anything the option created. Events from
whatever surfaces the option put in there bubble up to it, so this works the same
for one canvas or two.

What your option has to do is make sure they arrive. Concretely: whatever surface
is on top must receive pointer events, and the engine's own gesture table must be
empty. Neuroglancer builds a small tree of elements with a stacking order of
their own, and left alone those escape into the page's order and end up *above*
anything placed after them — so the operator's drawing looks perfectly correct
while every click is quietly caught by the engine underneath. Two lines of
styling fix it and both are in `neuroglancer-under/viewer.js`.

### 3. Addresses are passed in, never worked out

`acquisitions[i].url` is a whole address including the scheme and host. An option
may not put `window.location.origin` in front of anything. There is a check for
it.

That is not fussiness. Neuroglancer given an address beginning with a slash
builds the layer, raises no error, makes no request, and waits for ever — so the
failure mode of getting this wrong is a blank page that looks like a slow one.

### 4. The application's drawings are repainted at the moment the option
considers correct

There are two slots, and they are the outer two layers of
`viz_studio/THE_CANVAS.md`: the application's own drawing beneath the picture,
and its own drawing above it. `drawUnder(paint)` and `drawOver(paint)` each take
one function and the option calls it. For the sandwich options that is from
inside the engine's end-of-frame announcement, using the view read at that
instant; for a single-canvas option it is inside the engine's own draw. **The
page never knows which.**

Both are called with the same kind of frame, in the same frame of the picture:

```js
paint({ centre, zoom, width, height, density, context, project, unproject, coverage })
```

- `centre`, `zoom` — the view this frame is being drawn from, in micrometres
- `width`, `height` — the box, in browser pixels
- `density` — how many real pixels the screen packs into one browser pixel
- `context` — a 2-D drawing context, already cleared and already scaled for the
  screen's pixel density, so everything is drawn in browser-pixel units
- `project(x, y)` — micrometres to screen pixels for this frame
- `unproject(x, y)` — screen pixels back to micrometres, for a click or a drag
- `coverage` — the run's coverage record, or null

Hand `null` to either slot to say the application has nothing for it. An option
may then skip laying a surface down at all, so a page that never draws beneath
the picture pays nothing for the slot.

**A note for the single-canvas option.** A deck.gl canvas has no 2-D context to
offer. The honest way to keep the page's drawing code identical is to draw into
an offscreen 2-D canvas and composite it inside your own single pass — the
registration stays exact by construction, which is the property that option is
being built to demonstrate, and the page goes on drawing the same shapes. If you
find a better way, take it; what must not change is the page's drawing code.

### 4a. An option that cannot honour the bottom slot must say so

This is the one place where the three options genuinely differ in what they can
do, so the interface makes the difference askable rather than hiding it.

```js
viewer.drawsUnder          // true: genuinely beneath the picture. false: this engine cannot.
viewer.drawsUnderBecause   // one plain sentence, which a page may show to whoever is looking
```

**A page must be able to find this out without knowing which engine it is talking
to**, which is why it is a fact on the handle rather than something a page works
out from an option's name.

Neuroglancer forces the whole of its canvas opaque at the end of every frame, so
a surface behind it is never seen: measured, 0% of a colour painted behind it
against 97% of the engine's own background. A deck.gl canvas is cleared to
nothing, so 96.95% of the same colour comes through. Those are the two answers,
and `viz_studio/options/RESULTS.md` measurement 0b reports them per option from a
photograph.

**Do not invent a fallback**, and this matters more than it may look. It would be
easy for an option that cannot draw beneath the picture to draw the same thing
*above* it instead, with holes cut wherever the run has imaged, so that the page
looks the same. It must not. Two options that looked identical while doing
entirely different things underneath would make the comparison a lie, and a
silent difference of exactly that kind is what this whole exercise exists to
avoid. An option that cannot honour the slot paints the drawing where it belongs,
lets the engine cover it, and answers `false`.

### 4b. The transform is published every frame, for things that are not drawings

A drawing function is right for shapes that must stay locked to the picture, and
it is why they stay locked as well as they do. But **you cannot put an HTML
element inside a drawing context.** A label pinned to a tile, a menu, a styled
handle, anything with its own event listeners, has to be an ordinary element
positioned over or under the canvas — and to land in the right place it needs the
same conversion from micrometres to screen pixels that the drawing uses.

So every option publishes it:

```js
viewer.whereThingsAreDrawn()   // { centre, zoom, width, height, density, project, unproject }
```

and hands the same record to `onViewChanged` every time the view settles, so an
element can be moved in the same instant the picture moved rather than a frame
later. `project(x, y)` gives browser pixels from the top-left of the box the
viewer was opened inside, which is exactly what `left` and `top` want.

This is the whole of it. **No option builds a layer of HTML elements**, and none
should until the shape of that is settled; publishing the transform is what makes
it possible for an application to. Which side of the canvas such an element may
go on is the same question `drawsUnder` answers: above works everywhere, below
only where the engine's canvas lets what is behind it through.

### 5. Nothing in a module variable

Everything belongs to the viewer, so that a page can hold two. There is a check
that opens a second viewer, moves it, closes it, and fails if the first one
noticed.

---

## The one thing that was added while the first option was built

`tilesMayHaveLanded()` takes an optional `{ coverage }`.

It is not optional in practice, and the reason is worth reading before you write
your own. The coverage record says where the run has imaged. While a run is
going, that answer changes — which is the entire point of it. Two things are
worked out from it: where the operator's drawing cuts its holes, and (for the
sandwich options) how much of the window the engine is given to draw in. Both are
settled when the viewer opens.

So without a way to hand over a newer record, **a tile written outside the ground
the run had reached when the page opened is drawn nowhere and shows through
nothing** — and on screen that looks exactly like an engine failing to notice new
data. It was measured that way before this was added: tiles landing inside the
old bounds appeared at once, tiles landing outside them never appeared at all.

---

## Things measured while building the first option that the next two should know

**Nothing behind a WebGL canvas shows through it, at least not neuroglancer's.**
Measured, with one colour painted behind the engine's canvas and another set as
the engine's own background: over ground nobody imaged, 97% of the window was the
engine's background and 0% was the colour behind. The engine forces the whole
canvas opaque at the end of every frame.

The consequence applies to any sandwich built on *that* engine, and it is worth
being careful about which part carries over. In a sandwich — two drawing surfaces
in the page, one in front of the other — the operator's plan cannot be put on a
surface underneath **neuroglancer**, because that surface is never seen. It has to
be built the other way up: the operator draws the carrier and the tiles on the
surface *above*, and cuts holes in it wherever the coverage record says there is
picture. That works, and it is what the harness does by default, for all three
options, so that the three are drawing the same thing when they are compared.

It turned out **not** to carry over to a deck.gl canvas, which is cleared to
nothing rather than to a colour: measured the same way, 96.95% of the colour
behind it comes through. That is why the bottom slot in §4a exists at all, and why
it is asked about rather than assumed. Both Viv options honour it; neuroglancer
says plainly that it cannot.

It also promotes the coverage record from an optimisation to a requirement for
these options. With no record there is nowhere the picture is allowed to show,
and the harness says so plainly rather than guessing.

**This does not mean the stack in `LAYERS.md` is impossible**, and it would be
easy to draw that conclusion by mistake, so it is worth separating the two
carefully. What was measured here is one *canvas* placed behind another. Putting
the plate and the plan *inside* neuroglancer as image layers, underneath the
acquisition, is a different arrangement, and it was measured on the same night in
`viz_studio/LAYER_STACK.md` — on the branch `claude/layer-stack-probe`, commit
`4960d17`, at the time of writing. There a lower layer does show through the layer
above it, read as exactly `0, 255, 0` wherever the upper layer had never been
written. So a surface behind the engine's canvas can never be seen, while a layer
inside the engine, beneath another layer, can. Option C, which draws everything in
one canvas, is not touched by this finding either.

**Resizing the engine's canvas mid-gesture costs registration unless the engine is
told at once.** Neuroglancer only re-reads its own size when the browser's resize
watcher reports, which is after it has already drawn another frame at the old
size — and a frame drawn at one size and stretched to another is the wrong scale
in the wrong place. Measured: the two layers came apart by 69 screen pixels while
panning. Nudging the engine's own count of resizes brings it back to 1. If your
option resizes its drawing surface for any reason, look for the same thing.

**Registration and bounding the drawn region are in tension**, and the first is
worth more. The sandwich measurements on the earlier probe branch never bounded
the region while measuring registration, so this had not been seen before.
