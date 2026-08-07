# How the viewer is driven: the controls, and why they are what they are

Written 2026-07-30. This describes the **flat, two-dimensional view** only. The
volume view is deliberately out of scope for now.

This document exists because the viewer is about to have two different pieces of
code deciding what a mouse gesture means, and they must agree. Today the drawing
engine interprets the mouse itself. In the arrangement being designed, the
operator's own canvas sits on top and receives every gesture, and the engine only
moves because it was told to. Either way, "what does dragging do" stops being
something a library decides for us and becomes something we decide once, on
purpose, and write down.

The rule this document serves is a short one:

> **A gesture means the same thing wherever it is made, and it means what a
> microscopist would expect.**

That sounds obvious. It stops being obvious the moment two pieces of code each
inherit a sensible default from a different library, and the two sensible
defaults disagree.

---

## What "a binding" means

The engine keeps a table that maps a gesture — a mouse button, a wheel turn, a
key — to an action. Neuroglancer calls this an `EventActionMap`, and it is a
plain table we are allowed to write to. Nothing here requires modifying the
engine or working around it.

This viewer already builds that table by hand rather than accepting whatever the
engine installs by default. The code is in
`viz_studio/frontend/src/NeuroglancerView.jsx`, around line 99, and the comment
above it explains what was left out and why.

---

## What is bound today

Read out of the installed engine, not from memory. Gestures marked **at:** are
handled inside an image panel; the rest are keys.

### The mouse

| Gesture | What it does today |
| --- | --- |
| Drag, left button | Pan — move the image under the pointer |
| **Shift + drag, left button** | **Rotate the plane** (see the warning below) |
| Wheel | **Step through z**, one plane per notch |
| Shift + wheel | Step through z, ten planes per notch |
| Ctrl + wheel | Zoom |
| Alt + wheel | Change how thick a slab is drawn |
| Right button | Centre the view on the point clicked |
| Double click | Select what is under the pointer |
| Ctrl + drag | Start an annotation |

### The keys

| Key | What it does today |
| --- | --- |
| Arrow keys | Move a step in x or y |
| `,` and `.` | Back and forward one plane in z |
| `[` and `]` | Back and forward one moment in time |
| Ctrl + `=` / Ctrl + `-` | Zoom in and out |
| Alt + `=` / Alt + `-` | Make the drawn slab thinner or thicker |
| `z` | Snap the view back to the axes |
| **`r` and `e`** | **Rotate the plane** (see the warning below) |
| **Shift + arrow keys** | **Rotate out of the plane** (see the warning below) |
| Enter, Backspace | Finish an annotation, undo a step of one |

### What is deliberately **not** bound

The engine also offers a page-wide keyboard table, and this viewer does not
install it. That is not tidiness — it was removed because it trapped an operator.
The space bar split the image into four panels with no way back, the digits 1 to
9 hid channels while the interface still showed them as visible, and several
letters restored scale bars and axis lines that this viewer draws for itself.
None of it was reachable through our own interface, so leaving it out costs
nothing and removes a set of traps. The reasoning is written out in full in
`NeuroglancerView.jsx`.

---

## The decision that has been made

**In the flat view there are exactly two ways to move around, and nothing else.**

| Gesture | What it does |
| --- | --- |
| Drag with the mouse | Pan the view |
| Turn the scroll wheel | Zoom in and out |

Everything else that could change where you are or which way you are facing is
removed: rotating by Shift and drag, rotating with `r` and `e`, tilting with
Shift and the arrow keys, stepping through z on the plain wheel, zooming with
Ctrl and the wheel, recentring with the right button, and the arrow, comma, full
stop and bracket keys.

Moving through the stack and through time is not taken away — it moves to the
sliders the interface already draws, where it is visible and labelled, rather than
living on a gesture an operator has to know about.

Two gestures is a deliberate choice rather than a minimal one. An operator at a
microscope should be able to sit down and move around without being taught, and
every extra gesture is one more thing that can be triggered by accident. The
sections below explain what each removal is protecting.

**Where this now lives.** For the three viewers in `viz_studio/options/`, the two
gestures are in one shared file, `options/gestures.js`, which each of them
imports; the viewer puts the listeners on when it opens and takes them off when it
closes. A page that shows one of those viewers therefore inherits this decision
rather than making it again, which is the point of writing it down here at all.

**And one thing a page may change.** An operator who has chosen a pen needs a drag
to draw rather than pan, and it cannot do both. So a page may tell the viewer that
a drag means something other than panning — `handDragsTo`, set out in
`options/contract.md` §2a — and the viewer hands the drag over instead of moving
the view. What the two gestures *are* does not change; what a drag means is the
application's to decide, exactly as it is in every drawing program an operator has
already used.

## The three questions this settles, and why it settles them that way

These are the places where the defaults are defensible for the engine's original
audience and wrong for ours. None of them is difficult to change; all of them are
unpleasant to discover late.

### 1. The wheel currently steps through z, and does not zoom

This is the sharpest one. Everybody who has used a map in a browser expects the
wheel to zoom. In this viewer it moves through the stack instead, and zooming
needs Ctrl held down.

It is not a silly default — for someone reading through a volume, a plane per
notch is exactly right. But this viewer already has a z slider down the right-hand
side, so stepping through the stack has a home of its own, whereas zooming has
nowhere else to live.

**Decided: the plain wheel zooms.** The wheel is the gesture an operator makes
most often and without thinking, and a browser has taught everyone what it does.
Stepping through the stack keeps the slider it already has, which is better than a
gesture anyway because it shows you where in the stack you are.

### 1a. And something nobody had noticed: the flat view was mirrored

Not a binding, but it belongs beside them because it is the same kind of fault
and it was found while testing them. **It has since been put right**, and the
rest of this section is kept so that nobody undoes it by accident.

The engine draws three chosen axes: one across the window, one down it, one into
the screen. Which is which follows from the *order* the axes are handed over in
together with which of the engine's named panel layouts is asked for — and the
two interact. The viewer used to hand them over in the order an OME-Zarr image
declares them, depth then height then width, and ask for the layout called `yz`.
That did put width across the window and height down it, and it looked entirely
right.

**It also ran width to the left.** Every picture the flat view drew was a mirror
image of the specimen. Nothing errored, and on a round embryo or a symmetrical
plate there was nothing whatever to notice — but an operator who picked out the
well on the left of the screen and sent the stage there sent it to the well on
the other side of the plate. It is the rotation hazard below in a quieter form,
and it is the reason that hazard is worth taking as seriously as this document
does.

**What was changed.** The axes are now handed over the other way round — width,
then height, then depth — and the layout asked for is the one the engine calls
`xy`. That puts width across the window running to the right, height down it, and
depth into the screen, which is the plane an operator scrolls through. Those
two go together and **must be changed together**: either on its own gives a view
that is edge-on, with the stack collapsed to a line, or mirrored again. The pair
of them live in `frontend/src/engine.js`, in
`pinTheAxesThatMeasureDistance`, and in `frontend/src/App.jsx`, at
`SLICE_LAYOUT`, and each says so at the other.

**How it is held in place.** `tests/test_the_picture_is_not_mirrored.py` opens a
small acquisition written dim at one edge and bright at the other, photographs
the picture, and fails unless the bright edge is drawn on the right. Measured
across the picture, the brightness ran downhill at 65 grey levels per hundred
pixels before the change and uphill by the same 65 after it. The same file
checks separately that dragging carries the picture with the hand, so that the
mirror can never be "fixed" by reversing the pan gesture instead — that would
make the viewer feel normal while leaving the picture just as reflected.

One thing that measurement taught, and it is worth knowing before writing
another: **dragging cannot find this fault.** The engine pans using the same
axis mapping it draws with, so the picture followed the hand pixel for pixel,
slope +1.0, both before and after. What tells you which way round a picture is
must come from something inside the specimen that could not have been reflected
along with it — here, the order the voxels sit in the file. The original
measurement in `SANDWICH.md`, section 2 — which is not on this branch; it lives on
`claude/sandwich-probe`, commit `1277e30` — saw the mirror as a slope of −1 only
because it compared the picture with the operator's own drawing laid over it,
and that drawing was placed from the store's coordinates directly.

Which handedness a microscopist *should* see remains a decision about the
instrument rather than about drawing: which way the stage moves relative to the
camera is a property of the microscope. What is settled here is narrower and
more important — the viewer no longer flips it silently. If an instrument
records that its stage runs the other way, that belongs in the acquisition's own
description, and the viewer should read it from there rather than assume.

### 2. Rotation is bound four different ways, and probably should not be

Shift + drag, `r`, `e`, and Shift + arrow keys all rotate the view. That is a
sensible thing to offer for a volume that was acquired at an angle to the axes.

**It is a hazard for what is being built now.** The whole premise of the new front
end is that the canvas coordinate system *is* the store's coordinate system — the
operator's carrier outline and their tile positions are drawn in stage
coordinates, straight, and the image is expected to sit underneath in exactly the
same frame. A rotated view breaks that correspondence completely, and the failure
is silent: nothing errors, the picture simply stops lining up with the drawing
over it. Shift + drag is an easy gesture to make by accident.

**Decided: rotation is removed from the flat view.** If a rotated view is wanted
later it comes back as a deliberate control, with the drawing over it rotated to
match — which is real work rather than a binding, and worth doing properly when
somebody actually needs it.

Because rotation is gone, a test has to prove it is gone. An unbound gesture looks
exactly like a gesture nobody tried, so without a check that Shift and drag leaves
the view untouched, this quietly comes back the next time the bindings are
edited.

### 3. Zoom should anchor on the pointer

The point under the pointer should stay under the pointer as the view zooms. This
is what everyone expects and its absence is felt immediately even by people who
cannot say what is wrong.

This matters more than usual in the arrangement being designed, because if the
operator's canvas implements zoom itself and hands a zoom level to the engine, any
small mismatch between the two shows up as the image creeping out from under the
outlines drawn on top of it — a little on every notch, accumulating. It is worth
testing by zooming ten notches in and ten back out and checking that you end
exactly where you started.

---

## What has to be written by hand if input moves to our own canvas

In the arrangement where the operator's canvas sits on top, the engine never
receives a mouse event at all, and the binding table above stops being consulted.
Everything an operator can do then has to be implemented in our own code, and
pushed down to the engine as a position and a zoom level.

The engine exposes what is needed for that, and this viewer already uses all of
it: `navigationState.position` for where the view is centred,
`navigationState.zoomFactor` for how close it is, and
`navigationState.pose.displayDimensions` for which axes are on screen. Each of
them also carries a `changed` signal, so our own controls can follow the view as
well as set it — the z slider and the scale bar already work that way, in
`AxisSlider.jsx` and `ScaleBar.jsx`.

What must be written: pan, zoom anchored on the pointer, and the conversion
between the millimetres the operator's drawing uses and the physical units the
engine works in. That conversion belongs in exactly one place, because getting it
wrong shifts the whole picture rather than a corner of it.

---

## Changing a binding

The table takes readable gesture names, so a change is small and legible:

```js
// The wheel zooms, which is what a browser has taught everyone to expect.
// Stepping through the stack keeps its slider, its comma and full stop keys,
// and shift+wheel, so nothing is lost by moving it off the plain wheel.
bindings.sliceView.set("at:wheel", "zoom-via-wheel");

// Rotation is removed rather than rebound: a rotated view no longer lines up
// with the carrier outline and tile positions drawn over it, and nothing warns
// you that it has stopped lining up.
bindings.sliceView.set("at:shift+mousedown0", null);
```

Anything changed here should be changed in one place and reflected in the table
above, so that this document keeps describing the viewer that actually exists.
