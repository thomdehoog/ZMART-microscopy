# Viewer prototype (design demo)

A single self-contained HTML page that shows the ZMART viewer design working
end to end. Open `index.html` in any browser — no build, no server, no install.

To show it in its own desktop window instead of a browser tab (nicer on the
microscope PC), run `python run.py`. That opens the page in a native window via
pywebview (`pip install pywebview`), and simply falls back to your browser if
pywebview is not installed. Because the page is self-contained, no server is
needed either way.

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

## Showing a different sample

You do not have to edit the file to try a different shape. The page reads the
sample it should build from the URL, so you can show, say, a three-colour
timelapse just by adding parameters after `index.html`:

- `?channels=488,561,647` — one channel per laser line, coloured by wavelength
- `?channels=4` — four channels from the default palette
- `?nt=12` — twelve timepoints; `?nz=100`, `?nx=256&ny=256`, `?vox=0.9`
- `?dataset=<url-encoded JSON>` — a full descriptor, for complete control

For example, `index.html?channels=405,488,561,647&nt=10` opens a four-channel,
ten-timepoint sample. Values that are out of sensible bounds are clamped, and a
request for a volume too large to hold is trimmed down, so a URL can never wedge
the viewer. This is still **synthetic** data — it is for showing the interface
with different shapes. Opening a *real* acquisition is the production step:
writing it as OME-Zarr and letting the neuroglancer engine stream it (see the
integration roadmap).

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
