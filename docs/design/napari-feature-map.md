# What to borrow from napari — the viewer's control surface

**Status:** design. A companion to `web-viewer.md`. That document explains why
the engine underneath the web viewer is neuroglancer; this one decides what the
viewer should let a person *do*, by working through what napari does and keeping
only the parts that earn their place. Written 2026-07-23.

## Who this is for

Most people driving ZMART are microscopists and biologists, not software
engineers. napari is the tool many of them already know for looking at image
stacks, so "napari, but in the browser and able to open a whole lightsheet
volume" is the promise the web viewer is making. The question this document
answers is a practical one: napari has a great many buttons, and we do not want
all of them. Which ones actually help someone decide *is this sample worth
imaging, which cells are the targets, where should the microscope go next* — and
which are just clutter we would be copying out of habit?

## The idea, in one paragraph

napari is really two things stacked together: a set of controls (a layer list, a
few sliders, some drawing tools) and a drawing engine underneath that puts pixels
on the screen. neuroglancer is the same two things. Our plan is to take
neuroglancer's engine — because, as `web-viewer.md` explains, it is the one that
can stream a volume too large to fit in memory — switch off every piece of
interface it draws for itself, and put a small, napari-shaped set of controls on
top instead. The engine draws the image; we supply the buttons. The reason to do
this rather than just hand people neuroglancer is that neuroglancer's own
interface is built for power users and shows everything at once. A biologist
should see four friendly controls, not forty.

## Why this is cheap — the two channels of communication

It helps to picture the viewer as two separate flows of information that never
mix.

The first is the image data itself. It lives on disk as OME-Zarr and flows **one
way only**, from disk into the engine, and only the small part currently on
screen — never the whole thing. Nothing we do sends data back the other way, and
nothing we do rewrites what is on disk. The acquisition stays exactly as it was
recorded, read but never altered.

The second flow is everything the controls do, and it is tiny. Changing the
brightness of a channel, giving it a colour, switching from a flat plane to a
rotating volume, dropping a marker on a cell — all of these are a handful of
numbers or a short instruction sent *to* the engine. None of them is an image.
So the entire control surface is small and fast no matter how large the
acquisition is, because it is made of instructions, not pixels. This is the
quiet reason the whole approach is affordable: the expensive thing (the data)
only ever moves in one direction and is never changed, and the thing we
manipulate (the view) is always cheap.

The one exception, noted here so it is not a surprise later, is painting a
segmentation mask by hand — colouring in regions voxel by voxel. That genuinely
does create a large new array, and so it sits outside this happy picture. It is
covered under "annotation" below, and the recommendation is to keep it optional
and separate.

## How napari handles very large data — and where it stops

This is the heart of why neuroglancer is underneath, so it is worth stating
plainly.

**In two dimensions, napari copes with enormous images very well.** It
understands multi-resolution data — an image saved at several zoom levels, coarse
to fine — and it is clever about only loading what it needs: the right level of
detail for how far you are zoomed in, and only the tiles currently in view.
There is also a structural reason two dimensions are easy. When you scroll
through a stack, each thing you look at is a single flat plane. One plane out of
a 200-gigabyte volume is just an ordinary image of a few megabytes. So "page
through a huge stack, one slice at a time" is comfortable almost by definition,
and napari does it smoothly.

**In three dimensions, napari hits a hard wall.** Drawing a volume is a different
task from drawing a plane. To render a volume you cannot use a single slice — you
need the whole block of data at once, because every pixel on screen is looking
*through* many layers of the sample. Two limitations of napari then combine.
First, its cleverness about picking the right level of detail is really a
two-dimensional trick; when you switch to a volume view it falls back to a single
resolution level for the entire block. Second, to draw that block it must load it
in full into the computer's memory and then hand it to the graphics card as one
piece, and the graphics card has a firm size limit. The result is that a
20-gigabyte or 200-gigabyte lightsheet volume simply cannot be shown at full
resolution in three dimensions. You are forced to shrink it to a coarse, blurry
copy small enough to fit, or it fails outright. There is no streaming: it is
load-the-whole-thing or nothing.

neuroglancer was built the other way around. It streams a volume the same way
napari streams a plane — fetching only the chunks, and only the level of detail,
that the current view actually needs. That is the capability the workflow's
present viewers cannot follow the data into, and it is exactly what a lightsheet
volume demands. So: we keep napari's *shape*, because people know it and it is
kind, and we take neuroglancer's *engine*, because it is the one that can go
where the data is going.

## The feature map — what napari offers, and what we should keep

The verdicts below use four labels:

- **v1** — build it now; this is the working viewer.
- **v2** — worth having, but after v1 has proven itself.
- **default** — napari exposes a control here, but the right answer is to pick a
  sensible fixed setting and *not* show the knob at all.
- **skip** — napari has it; we do not need it.

### Controlling how a channel looks

| napari control | verdict | reasoning |
|---|---|---|
| Contrast limits (the black/white points) | **v1** | The single most-used control. A raw 16-bit acquisition occupies a narrow band of the range and renders black without it. The spike already computes a sensible starting window on the server. |
| Auto-contrast, "once" | **v1** | One button that sets a good window and then leaves it alone. |
| Auto-contrast, "continuous" | skip | Re-fits on every move, so the picture flickers as you pan. The "once" button is calmer and enough. |
| Opacity | **v1** | Needed to see one channel through another. |
| Colour per channel | **v1**, changed | Keep it, but as a small fixed palette of solid colours, not napari's library of scientific colour maps. See "Two decisions to hold" below. |
| Gamma (a brightness curve) | v2 | Real, but secondary; the contrast limits cover most of what people reach for. |
| Blending mode | default | Just default to *additive*, the way real fluorescence channels sum, and hide the menu. |
| Projection mode | default | Default to *maximum intensity*, the usual choice for fluorescence, and hide it. |
| Interpolation (smoothing) | default | Choose smooth-when-zoomed and move on; nobody should have to think about this. |

### Changing the view

Every control in this group is free — it changes how you look, never the data —
so we can be generous here.

| napari control | verdict | reasoning |
|---|---|---|
| 2-D / 3-D toggle | **v1** | Already built. The one real choice a person makes: a working plane, or a rotatable volume for reading shape. |
| Scroll through the stack (z) | **v1** | The core gesture of the flat view. See "Dimensions" below for the slider. |
| Pan, zoom, and a "reset to frame everything" | **v1** | Table stakes. Reset matters because people get lost and need one button that brings them home. |
| Rotate and zoom the volume in 3-D | **v1** | Reading three-dimensional shape is the whole reason the volume view exists. |
| Scale bar with real units (µm) | **v1** | Already on, and always visible, so every view can be measured by eye. |
| Look from a different axis (down z, or along y) | v2 | Genuinely useful for reading anatomy. One clean "view from" control — not free axis-shuffling, which is a reliable way to end up staring at a view you cannot undo. |
| A cutting plane that slices into the volume | v2 | High value for thick samples, but more interface, so it can wait. |
| Saved or bookmarked viewpoints | v2 | "Take me back to that region." Pleasant, not essential. |
| Perspective vs. flat (orthographic) view | default | Pick the flat one, so sizes and distances stay honest, and hide the choice. |
| Roll / transpose the axes | skip | Axis gymnastics that confuse far more than they help. |
| Automatic playback through time | v2 | A movie-making nicety. A *manual* time slider is a v1 requirement — see "Dimensions" below. |
| napari's / neuroglancer's multi-panel grid of cross-sections | skip | This *is* the busy interface we are deliberately switching off. |

### Marking things on the image (annotation)

This is what turns a viewer into a ZMART tool: a mark on the image is a decision,
and a decision can be handed back to the microscope.

| napari capability | verdict | reasoning |
|---|---|---|
| Place, move, delete **points** | **v1** | Cell centres, seed positions, "image here." A point is just a coordinate. |
| Draw a **box** (or line, ellipse) | **v1** | A region to re-image at higher magnification — which is exactly the target-acquisition step the webapp performs today. |
| A **label** or score attached to each mark | **v1** | So detected or classified cells can be coloured by class or score. |
| Marks travel **back to Python** (and on to the stage) | **v1** | The point of it all. A box becomes a place to send the microscope. The existing "go here" path already proves the route. |
| Free-hand **polygons** | v2 | neuroglancer has no polygon shape, so this is real work rather than wiring; wait for a concrete need. |
| **Undo / redo** of edits | v2 | Something we would have to manage ourselves; add it when editing becomes heavy enough to warrant it. |
| Painting a **segmentation mask** by hand | separate, optional | The one thing here that creates large new data (see the note at the top). Keep it off the main path; reach for it only when a real task needs a hand-drawn mask. |

### Registration and coordinates (quiet, but important)

| napari capability | verdict | reasoning |
|---|---|---|
| Physical voxel size per layer | **v1** | Read straight from the OME-Zarr file, so the scale bar and every measurement are true. |
| Position / offset per layer | **v1** | Also read from the file, so tiles and channels line up where they belong. |
| Full affine registration (rotate, shear to align layers) | v2 | Partly supported by the engine; expose it only if misaligned layers become a real problem. |

### The parts of napari we do not need at all

napari is also a whole desktop application, and that scaffolding is exactly what
the web viewer replaces with its own small React app. So we **skip**: the
embedded Python console; the plugin system; the toolkit for building custom dock
widgets; vector-field, particle-track, and mesh layer types; and the
Python-array interface for pushing NumPy arrays in (our data arrives as
OME-Zarr files the engine opens directly, which is a different and simpler
shape). None of this is a loss — it is application plumbing the browser app
provides in its own way.

Two things that live elsewhere in ZMART also stay where they are, as noted in
`INTEGRATION_ROADMAP.md`: the explorer's scatter plot, histogram, and gates
(that is feature-space charting, not image viewing) and the acquired-image
gallery of matched pairs (small and simple, where this engine would be
overkill).

## One viewer for all of smart microscopy — the five axes

The ambition behind this viewer is a single one: **one strong, general-purpose
image viewer, in a web page, that opens everything smart microscopy produces** —
not a special tool for mesoSPIM and separate tools for everything else. The
reasoning holds up. mesoSPIM data is the hardest case on the axes that usually
defeat a viewer: it is large, it is three-dimensional, it has several channels,
and it arrives in many tiles. A viewer that streams *that* comfortably finds a
confocal stack, a widefield snapshot, or a plain two-dimensional image easy by
comparison, because each is a smaller, gentler version of the same problem.

What you end up with, said plainly, is a **five-dimensional viewer** — the five
axes a microscopist already lives in: **X, Y, Z, C, T** (width, height, depth,
channel, and time). These are the same five that Fiji and the OME/Bio-Formats
world are built on, so "cover all five well" is a concrete, finite target that
amounts to "open essentially any raster image microscopy produces." And it comes
with **strong three-dimensional rendering that respects the resolution pyramid**:
the volume is drawn from a coarse level when you frame the whole thing and from
full resolution only where you zoom in, so a huge volume renders at interactive
speed instead of forcing the blurry, shrunk-to-fit compromise napari must make in
three dimensions. That pyramid-aware volume rendering is the single capability
the workflow's current viewers cannot follow the data into, and it is the reason
the engine underneath is neuroglancer.

There is one honest gap in "solve mesoSPIM and the rest follows," and it is
**time**. mesoSPIM volumes are captured at a single moment, so they never
exercise a time axis — which means mesoSPIM alone cannot tell you whether the
time controls work. The remedy is small and worth stating: keep one genuine
time-lapse dataset on hand as a test, so the time path is *proven* on real data
rather than assumed, the same way every other part of this work is.

Here is how each of the non-picture axes should behave.

**Channel (C) — coloured layers, not a slider.** Channels belong in the layer
list, each drawn in its own solid colour and added together the way real light
adds. This is Fiji's "composite" view and the natural way to read fluorescence,
and it is reinforced by how the data is stored: a real acquisition keeps each
channel in its own file, so a channel is a layer by nature, not a position to
scroll through.

**Depth (Z) — a slider, and the wheel.** Moving through the stack is the core
gesture of the flat view and already works by scrolling the mouse wheel. A
visible slider along the bottom edge, where Fiji and napari have trained everyone
to look for it, is the friendly handle on top of that.

**Time (T) — a slider, and it must work in three dimensions too.** This is a firm
requirement, and neuroglancer supports it directly. Time is simply another named
axis alongside the three spatial ones. In the volume view the three spatial axes
are what gets ray-cast into a block, and time rides alongside as a position: you
can hold a rotated three-dimensional view, move the time slider, and the engine
fetches and redraws that moment's volume in place — still streaming only what the
screen needs, still choosing the right pyramid level. Two honest notes come with
it. First, stepping through time is heavier than scrolling through depth:
scrolling depth stays inside one volume whose pieces are largely already loaded,
while stepping time crosses to an entirely new volume that must be fetched, so
time will feel more like "step and settle" than the instant depth-wheel. That is
a property of the data, not a flaw to engineer away. Second, it depends on the
workflow writing its images *with* a time axis (the standard `t, c, z, y, x`
layout) — a task on the data-writing side, the same OME-Zarr seam the roadmap
already commits to, not something the viewer can conjure on its own.

One distinction keeps the time controls honest. A **manual time slider** — you
drag it, the volume follows — is the requirement and lives in the viewer.
**Automatic playback** — a button that animates through time on its own, useful
mainly for making a movie — is a separate, later nicety, not part of the working
viewer.

## Two decisions to hold

**Colour, not colour maps.** napari's colour menu is built around single-channel
scientific colour maps with names like *magma* and *viridis* — beautiful for one
channel of continuous data, but the wrong model for multi-channel fluorescence.
For our data the honest picture is each channel drawn in a solid colour and the
channels added together the way real light adds — 488 in green, 647 in magenta,
and so on. So we keep a colour control, but it offers a short, deliberately
limited palette of solid colours (green, magenta, cyan, amber, blue, grey),
which is both simpler to use and more truthful to what the microscope recorded.

**Defaults instead of dropdowns.** Look back at the "controlling how a channel
looks" table and count how many rows are marked *default* rather than *v1*:
blending, projection, interpolation. Each of those is a knob a biologist should
never have to touch, and every one we replace with a good fixed setting is the
whole reason we are wrapping neuroglancer rather than shipping it raw. Ship the
handful that matter, quietly default the rest, and a panel of ten intimidating
rows becomes four friendly ones.

## The v1 viewer, in one breath

Putting the *v1* marks together, the first real viewer is small and coherent:

- a layer list in napari's shape — one row per channel, an eye to hide it, a
  swatch to colour it;
- four display controls per channel — visibility, contrast, colour, opacity;
- a 2-D / 3-D toggle, a depth (z) slider alongside the scroll-wheel, pan/zoom,
  and a reset button — with a time (t) slider on the same footing, working in
  three dimensions too, as soon as time-lapse data is being written;
- point and box tools whose marks carry a label and travel back to Python;
- an always-on scale bar, with true physical units read from the file.

Almost all of the display side of that already exists in the spike. The new
work, and the part that makes it *ZMART's* viewer rather than a generic one, is
the annotation and the path that carries a marked box back to the microscope.

## The rule that keeps it honest

One sentence to settle any future "should we add this?" argument:

> If a control changes *how you look*, include it and keep it cheap. If a control
> changes *the data*, keep it out of the viewer — or make it an explicit,
> separate, optional mode.

View changes are free and never touch the acquisition, so we can afford to be
generous with them. Anything that writes is the rare and costly case, and it
should always look like the deliberate exception it is.

## Where to read more

- `web-viewer.md` — why the engine is neuroglancer, measured on real mesoSPIM
  data, and the overall shape of the interface.
- `../../viz_studio/INTEGRATION_ROADMAP.md` — how the viewer grows from a spike
  into the workflow's main image surface, one step at a time.
- `../../viz_studio/INDEX.md` — the map of the visualization work and what to
  read in what order.
