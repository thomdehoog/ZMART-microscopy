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

### 1a. And something nobody had noticed: the flat view is mirrored

Not a binding, but it belongs beside them because it is the same kind of fault
and it was found while testing them.

The engine draws three chosen axes: one across the window, one down it, one into
the screen. Which is which follows from the *order* the axes are handed over in
together with which of the engine's named layouts is asked for — and the two
interact. This viewer hands them over as depth, height, width and asks for the
layout called `yz`, which does put width across the window and height down it and
looks entirely right.

**It also runs width to the left.** Measured by dragging and watching where the
picture went: the drawing over the image moved 168 pixels one way and the picture
moved 168 pixels the other. Handing the axes over width-first and asking for the
layout called `xy` instead makes them move together. The figures are in
`SANDWICH.md`, section 2.

This has not been changed here, because which handedness a microscopist should
see is a decision about the instrument rather than about drawing, and it wants
somebody who knows the stage to make it. But it must be made. A mirrored plate
view is still a perfectly good picture — nothing errors, and on a round specimen
there is nothing to notice — and the operator who clicks the left-hand well and
drives the stage there is driving it to the wrong one. It is the rotation hazard
below, in a quieter form.

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
edited. There is now such a check —
`viz_studio/tests/test_the_margins_stay_even.py` — and it turns the view on
purpose to prove it would notice.

One thing that check taught, worth knowing before writing another: **a rotation of
a couple of degrees is nearly invisible to the obvious measurement.** A square
turned two degrees is almost exactly as wide across its middle as it was, so
anything reading a single line through the centre reports nothing wrong at all.
What catches it is reading the same edge along several lines and comparing them
with each other. See `SANDWICH.md`, section 9.

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
