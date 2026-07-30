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

## Three decisions to make, and what I would choose

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

**Recommendation: bind the plain wheel to zoom, and keep Ctrl + wheel bound to
zoom as well** so that anybody who learned the old way is not punished. Stepping
through z stays available on the slider, on `,` and `.`, and on Shift + wheel if
we want to keep a mouse gesture for it.

Whatever is decided, decide it deliberately, because the wheel is the gesture an
operator makes most often and without thinking.

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

**Recommendation: unbind rotation in the flat view.** If a rotated view is wanted
later it can come back as a deliberate control with the overlay rotated to match,
which is a much larger piece of work than a binding.

If it is kept, then `z` — snap back to the axes — becomes an important control
rather than a curiosity, and it needs to be visible in the interface rather than
hidden on a key.

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
