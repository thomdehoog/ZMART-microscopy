# Viewer prototype (design demo)

A single self-contained HTML page that shows the ZMART viewer design working
end to end. Open `index.html` in any browser — no build, no server, no install.

It is a **prototype of the interface**, not the production viewer: it generates a
synthetic multi-channel, multi-timepoint lightsheet volume and draws it with a
small built-in renderer. The production viewer keeps this exact interface and
swaps the renderer for the neuroglancer engine reading real OME-Zarr, out of
core (see `../INTEGRATION_ROADMAP.md` and `../../docs/design/napari-feature-map.md`).

Nothing here is fixed to a channel count, volume size, or number of timepoints.
The `DATASET` object near the top of the page stands in for the metadata read
from an OME-Zarr store, and the whole interface is derived from it — add a
channel or change the dimensions and the panel, the layers, and the sliders
follow.

## What it demonstrates

- **Data-driven layers** — one layer per channel, read from the dataset (two
  here); add a third and the UI grows on its own.
- **Per-channel display** — visibility (the napari eye), contrast (with a
  histogram and an auto button), opacity, and colour from a small palette.
- **2-D and 3-D** — a scrollable plane and a rotatable volume, switched on the
  same data.
- **Z and T sliders** — depth and time. The time slider works in 3-D as well;
  the depth slider hides in 3-D, where z becomes a displayed axis.
- **Annotations in their own layer** — points and boxes live in a separate
  "Targets" layer you can hide or recolour, exactly like napari.
- **The microscope loop** — each target carries physical coordinates and a
  "send to microscope" action, the step that makes this a ZMART tool rather
  than only a viewer.
