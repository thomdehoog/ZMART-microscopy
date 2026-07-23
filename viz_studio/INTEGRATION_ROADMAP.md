# Making the viewer the main viewer — integration roadmap

A record of the decision to grow the viz-studio (neuroglancer) viewer from a
spike into the single image/volume viewer for the whole ZMART workflow. Written
so the intent, the honest scope, and the path are not lost between sessions.

## The intent

Today the workflow's image surfaces (the overview map, the acquired-image
gallery) are separate viewers that stream flat PNGs. They work well for small
2-D tiles but cannot zoom to full resolution on large data, and cannot show 3-D
at all. The neuroglancer spike exists to become the **one image engine
underneath every place we look at pixels** — gaining zoom-to-pixel on gigapixel
overviews and, crucially, **true 3-D** (z-stacks, mesoSPIM volumes) that the
current viewers simply cannot do.

## The important distinction: what it replaces, and what it does not

"Main viewer for everything" means one engine for **image/volume display** — it
is *not* a wholesale replacement of the whole interface.

**neuroglancer becomes the engine for (the image surfaces):**

- the overview map — and it gains zoom-to-pixel and gigapixel scale;
- 3-D volumes (z-stacks, mesoSPIM) — the genuinely new capability;
- any large acquired image.

**These stay as our own React, unchanged (they are not image viewing):**

- the explorer's scatter plot + histogram + gates — that is feature-space
  plotting, a charting job, not something an image viewer does;
- the acquired-image gallery of same-scale pairs, and the focus position map —
  small and simple; neuroglancer would be overkill.

This is the "your UI, their engine" split we settled on: neuroglancer draws the
pixels; our React owns the plots, the gates, the controls, and the step flow,
and drives the engine.

## The honest catch: this is a consolidation project, not a drop-in

There are currently **two different front-end stacks**:

- the **webapp** (`workflows/target_acquisition/workflow/webapp`) — React written
  as Python strings (anywidget-style), vendored, served by a standard-library
  server, streaming PNG tiles over a live event stream;
- the **viz-studio** (`viz_studio/`) — a normal Vite/npm React build served as
  static files, reading images as OME-Zarr.

We chose the separate viz-studio stack deliberately, *because* embedding
neuroglancer into the anywidget widget model was the path we rejected. So making
neuroglancer the main viewer means the workflow's **image surfaces migrate onto
the viz-studio React stack** (or a shared one), and the data path shifts from
PNG-streaming to **OME-Zarr**: the workflow writes OME-Zarr, the viewer reads it.
That is the clean seam, and it is real work, not a switch to flip.

It also depends on viz-studio growing up. As of this writing it is still a
spike: it renders one hardcoded demo layer, has no control panel, uses demo data
only, and is not wired to the workflow's session or state.

## The incremental path (do this, not a big-bang rewrite)

1. **Grow the viz-studio control panel** — layers, per-channel brightness/
   contrast, z-scroll, 2-D/3-D toggle, the movable labeled box. (The next build
   step; the mount/state seam is already cut so App owns this.)
2. **Make the workflow write its overview as OME-Zarr**, then swap the overview
   widget for a neuroglancer view reading it. One surface, end to end — this
   proves the integration and the OME-Zarr seam on real workflow data.
3. **Leave the plots, gates, gallery, and step flow exactly as they are.** They
   are good, and they are separate concerns from image display.
4. **Expand to acquired volumes / 3-D** once that acquisition-to-OME-Zarr
   pipeline exists — this is where neuroglancer earns its place, because flat
   PNGs cannot go there.

## Recommendation

This is the right long-term direction, and it becomes necessary (not just nice)
the moment 3-D / mesoSPIM / whole-slide is a real requirement — the current
viewers cannot follow the data there. But the webapp works well today and does
not need replacing; the neuroglancer engine is what we reach for when we outgrow
flat PNGs, which 3-D guarantees we will. Do it incrementally, one surface at a
time, with OME-Zarr as the seam.

See `PLAN.md` for the viewer's design and `SPIKE_RESULTS.md` for what the spike
proved (and the worker-bundling bug it found and fixed).
