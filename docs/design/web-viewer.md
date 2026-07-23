# The ZMART web viewer — napari in the browser, neuroglancer underneath

**Status:** design. The engine layer is built and measured; the interface
described here is not. Written 2026-07-23, after a session spent establishing
what the engine can actually do on real mesoSPIM data.

## What this is for

Every ZMART workflow ends in someone looking at an image and deciding
something: is this sample worth imaging, which cells are targets, did the
acquisition work, where should the microscope go next. Today that is spread
across notebook figures, the target-acquisition webapp's gallery, napari on the
analysis machine, and Fiji. Each shows a different subset, none of them shows a
whole lightsheet volume, and none of them can hand a decision back to the
microscope.

This viewer is meant to be the one place that work happens — the backbone the
other tools plug into, on any machine with a browser, over data too large to
open any other way.

The shape of it: **napari's interface, vizarr's everyday simplicity,
neuroglancer's engine.**

## Why neuroglancer, established rather than assumed

Measured on `multitile_NF_Mag5x_Ch488_Ch647.ome.zarr` (20 GB, 7 tiles) and on a
2.5 GB tile within it:

- **Out-of-core.** A zoomed 3-D view fetched **8 of 32** full-resolution chunks.
  Cost tracks screen area, not dataset size — a 20 GB group and a 200 GB one
  open the same way.
- **Multiresolution in 3-D as well as 2-D.** The volume is drawn from the
  coarsest level when framed whole and from full resolution when you zoom:
  voxel size `40 × 35.2 × 35.2 µm` → `10 × 1.1 × 1.1 µm`, read from the engine.
- **Reads real acquisitions unconverted.** NGFF 0.4, zarr v2, blosc/zstd,
  `dimension_separator: "/"`, scale **and** translation transforms, no channel
  axis, one store per tile and channel.
- **It is an engine, not an application.** Its own furniture — bounding box,
  axis lines, panel grid, section planes — is plain state and is switched off.

The alternative considered was vizarr/Viv, which is the better tool for 2-D
plates and slides but uploads a whole resolution level to the GPU for 3-D. Level
0 of a single tile here is 6.1 GB uncompressed, so that path can only ever show
a downsampled volume.

## What exists today

- 2-D plane view, scrolling z, as the default — no panel grid, no chrome
- a `2D | 3D` toggle that re-renders the same data as a ray-cast volume
- multi-store loading: one layer per tile and channel, placed by their own
  translations, coloured by excitation wavelength when overlaid
- contrast measured per store: the `omero` block when declared, otherwise the
  1st/99.9th percentile of the coarsest pyramid level (99th/99.99th in 3-D,
  where a background-level window is fog)
- 99 tests, including gesture tests that fail if navigation regresses

## The interface

Three regions. Nothing else at the top level.

```
┌──────────────┬────────────────────────────────────────────┐
│ LAYERS       │                                            │
│  ▸ 488  ●    │                                            │
│  ▸ 647  ●    │            the image                       │
│  ▸ targets   │                                            │
│  ▸ regions   │                                            │
│              │                                            │
│ [+ annotate] │  [2D|3D]                          [z ────] │
└──────────────┴────────────────────────────────────────────┘
```

### Layer list

One row per layer, napari's model: name, visibility, colour swatch, and a
disclosure that opens that layer's controls. Two kinds:

- **image layers** — one per store. A tiled two-channel acquisition arrives as
  four; they are grouped by tile so the list stays readable.
- **annotation layers** — points, boxes, and regions the operator draws.

Drag to reorder, which sets draw order. Solo/mute on the visibility dot
(click = toggle, alt-click = solo), because comparing two channels is the
commonest thing anyone does and it should not take four clicks.

### Channel controls

Per image layer, opened from its row:

- **Colour** — swatch opening a small palette (the wavelength default already
  applied, overridable). Green/magenta rather than red/green by default:
  colour-blind safe and higher contrast on dark backgrounds.
- **Histogram with a draggable window.** The one control that matters most.
  Real acquisitions occupy a sliver of the 16-bit range — 198–1388 out of
  65535 in the tile measured — so an image that renders black is the normal
  first experience, and a number entry is no way to fix it. The histogram is
  computed from the coarsest pyramid level (a megabyte, not the volume), drawn
  log-y, with the current window as a draggable band. Auto button restores the
  measured default.
- **Opacity**, and in 3-D a **gamma/alpha ramp**, since intensity drives opacity
  when ray casting.

The 2-D and 3-D windows are separate values on the same layer and both travel
with the config, so the toggle never has to recompute or round-trip.

### Annotations

napari's point and shape layers, in the browser. neuroglancer has annotation
layers natively — points, lines, axis-aligned boxes, ellipsoids — with
per-annotation properties, so this is wiring rather than invention.

What it must support, driven by what ZMART already does:

- **points** — cell centres, seed positions, "image here"
- **boxes** — regions to re-image at higher magnification, which is exactly the
  target-acquisition flow the webapp performs today
- **properties per annotation** — a class label, a score, free text

And crucially, annotations travel back to Python. The existing `POST /api/goto`
already proves the path (browser → Python → eventually hardware). Generalised:

```
GET  /api/annotations            what has been drawn
POST /api/annotations            replace/persist a layer
POST /api/goto      {box}        move the stage there
```

Persisted as JSON beside the acquisition, in the `smart/` layout the lab already
uses, so a selection made in the viewer is an input to the next acquisition
rather than a screenshot.

### Analysis output is just another layer

The reason this becomes the backbone rather than a viewer: what the analysis
produces goes back on screen next to what produced it. A Cellpose run over the
488 channel writes a label volume; that appears as a **labels layer** beside the
image, not as a PNG in a report.

neuroglancer has a segmentation layer type natively — integer labels, a colour
per object, hover to identify, click to select — so this is again wiring rather
than invention. The kinds ZMART already generates:

| output | layer | what it buys |
|---|---|---|
| Cellpose / segmentation masks | labels | see the mask over the image, at full resolution, in 3-D |
| probability or distance maps | image | judge a threshold by eye instead of by histogram |
| detected objects, classified cells | annotation points with properties | colour by class or score |
| selected targets | annotation boxes | the acquisition's actual input |

Two consequences for the design:

- **Analysis writes OME-Zarr beside the image**, in the same `smart/` layout,
  so a result is openable by the same code path as an acquisition. No special
  case for "analysis data".
- **Selection is bidirectional.** Clicking an object in the labels layer selects
  it in whatever plot or table sits alongside, and vice versa. That is the
  linked-view behaviour the discovery tools want and napari makes awkward.

## The engine must be invisible

A hard requirement, not a preference: an operator should never be able to tell
what is underneath. Practically that means:

- **No neuroglancer UI, ever.** Its top bar, layer panel, location box, settings
  dialog, panel grid, bounding box, axis lines and section planes are all off.
  The parts still leaking through — the small per-panel maximise icons and axis
  letters — are DOM and go too.
- **No neuroglancer vocabulary.** No "cross-section", no "data source", no
  `|zarr2:` URLs on screen. Layers have the names the microscope gave them.
- **No neuroglancer keybindings we did not choose.** Its defaults bring up its
  own dialogs; the bindings we want (pan, zoom, z, rotate) are kept and the rest
  unbound.
- **Ours is the only interface.** Every control is a React component we own,
  writing to `viewer.state`. Nothing is configured by reaching into the engine's
  own widgets.

There is also a size argument. The bundle is currently ~1.7 MB because
neuroglancer registers every data source and format it supports. We read
OME-Zarr over HTTP and nothing else, so trimming the registration imports to
what we use should cut a large fraction of that — worth doing once the interface
settles, and worth measuring rather than assuming.

## Architecture

The split that already exists, extended rather than changed:

```
Python                                   browser
──────                                   ───────
zarr on disk  ──HTTP chunks──────────▶   neuroglancer engine
/api/config   ──what to open─────────▶   React app  (layers, controls)
/api/annotations  ◀──what was drawn───   annotation layers
/api/goto     ◀──where to image───────   box → stage
```

**One owner of viewer state.** The React app is the only writer of
`viewer.state`; the engine is never configured from two places. That is what
makes adding controls safe — each new control is another value pushed the same
way.

**The server decides what to open, the client decides how to show it.** Pointing
at an acquisition is a server-side argument; colour, window, and mode are
client-side and instant.

## Decisions taken

1. **neuroglancer, embedded chrome-hidden** rather than forked or reimplemented.
   Its UI is state we switch off, so there is nothing to fork.
2. **The 2-D plane is the default view.** 3-D is a click away and not the
   everyday tool; opening in 3-D on a lightsheet volume is slower and reads
   worse.
3. **Contrast is measured, never assumed.** An image that renders black looks
   like a broken viewer, and the fix must not require the operator to know the
   data's dynamic range.
4. **Per-tile-and-channel layers, not a merged volume.** Real stores have no
   channel axis; merging would mean rewriting the data.
5. **Annotations are the product, not a decoration.** They are how a decision
   leaves the viewer and reaches the microscope.

## Open questions

- **Chunk size.** Level 0 chunks in the current export are **191 MB** (typical
  guidance is 1–32 MB). This is the single biggest lever on responsiveness and
  it belongs upstream, in whatever writes the OME-Zarr. Worth measuring before
  optimising anything in the viewer.
- **Where annotations live.** Beside the acquisition, or in the experiment's
  `smart/` folder, or a small database once there are many?
- **Multi-tile as one image.** Tiles are placed by their translations and
  overlap; do we blend them, or is showing them as separate layers correct?
- **Who runs the server.** Per-operator on the microscope PC (today), or one
  instance serving the facility?
- **napari parity.** How far to go — labels layers, a shapes editor, plugins?
  Each is real work and only some of it earns its place.

## Milestones

1. **Layer list + visibility + colour.** Makes multi-channel usable at all.
2. **Histogram with draggable window.** The control that stops real data
   looking broken.
3. **Labels layers for analysis output.** A Cellpose mask over its own image,
   at full resolution, in 2-D and 3-D.
4. **Annotation layers, points and boxes, persisted through the API.** The point
   at which the viewer stops being a viewer and starts being a tool.
5. **Round trip to the microscope** — a box drawn here becomes a target
   acquisition, closing the loop the target-acquisition webapp opens.
6. **Strip the bundle** to the data sources we actually use, and remove the last
   DOM leakage from the engine.
7. **Then, and only then:** measurements, linked plots, plugins.

Milestones 1–4 are what make this the backbone. Everything after is polish on a
tool that already works.
