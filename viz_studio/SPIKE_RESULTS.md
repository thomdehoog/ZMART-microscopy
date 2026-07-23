# Viz Studio spike — results

This records what the spike actually established, honestly, so the next person
(or the next session) does not have to rediscover it. It follows the plan in
`PLAN.md`.

## Bottom line

The hard architectural question — *can we run neuroglancer as the engine inside
our own React app, reading our OME-Zarr, packaged for Windows?* — is answered
**yes** for everything except the final step of getting image pixels onto the
screen, which did not rasterize in this headless Linux container and needs
validating on a real Windows machine with a GPU. The biggest risk is retired;
one rendering question remains open pending real hardware.

## What is proven (here, in a headless browser)

- **Bundling (was the #1 risk — now retired).** neuroglancer 2.41 bundles and
  boots in Vite + React 19, mounted chrome-hidden in our own component. Both
  `vite dev` and `vite build` work. The workers end up inlined into the bundle,
  so there are no worker-file 404s.
- **The integration recipe** (the real unknown, now known):
  - `optimizeDeps.exclude: ['neuroglancer']` in `vite.config.js`.
  - Import four registration modules before creating the viewer, or every data
    source fails with *"unsupported scheme"*:
    `neuroglancer/unstable/util/polyfills.js`, `.../layer/enabled_frontend_modules.js`,
    `.../datasource/enabled_frontend_modules.js`, `.../kvstore/enabled_frontend_modules.js`.
  - Mount into a `width/height:100%` div (not `inset:0`): neuroglancer sets
    `position:relative` on the element, which cancels inset-based sizing.
  - **Source URL format is `http://host/path/|zarr2:`** — the pipeline/kvstore
    form. The legacy `zarr://http://...` form is *dead* in 2.41 ("unsupported
    scheme"). This corrected a wrong assumption from the up-front research.
- **The OME-Zarr data pipeline works.** Python writes v0.4 / zarr v2; the engine
  reads the group, the multiscale pyramid levels, the array metadata, and the
  transform, and reports the layer ready with the correct coordinate space
  (`z, y, x`) and **correct physical scale** — the on-screen scale bar and the
  data bounding box are dimensionally right.
- **The supporting pieces work:** the 3-D multichannel demo generator
  (`backend/demo_data.py`), the stdlib server serving `dist/` + zarr on one
  origin (`backend/server.py`), and the headless-Chromium harness
  (`backend/browsercheck.py`).

## What is NOT yet proven (the open question)

- **Image pixels do not rasterize in this container.** The volume's *geometry*
  draws (bounding box, scale bar, 3-D outline), but the image itself shows as
  flat grey, and the server sees **zero pixel-chunk requests** (metadata is
  fetched; chunk data never is).
- **Where it was traced to:** the *frontend* correctly computes the visible
  resolution levels and wants to draw (verified by patching neuroglancer's
  `updateVisibleSources`: it runs in the **main** thread with the right sources
  and scale). But that computation **never runs in the worker thread**, and the
  worker is what decides which pixel chunks to fetch — so nothing is fetched.
- **Most likely cause:** in a headless, GPU-less browser the frontend throttles
  the viewport updates it sends to the worker (they are tied to animation
  frames / a presenting surface). It reproduced under both software GL
  (SwiftShader) and full Mesa llvmpipe, so it is not simply "no GPU". This is
  consistent with a headless-offscreen quirk that would not occur in a real
  windowed browser — which is exactly the Windows/WebView2 target. It is *not*
  yet ruled out as a subtle worker-sync bug in the embed.

## How to settle the open question (on Windows)

1. `conda env create -f environment.yml && conda activate zmart-viz`
2. `npm --prefix frontend install && npm --prefix frontend run build`
3. `python run_demo.py` → a native window opens on the demo volume.
4. Expected if the headless-quirk theory is right: the three blob-like
   "cells" channels render (white structure, green marker-a, magenta marker-b);
   scrolling changes the z-plane; the 3-D view shows a volume.
5. If it still shows grey with no pixels on real hardware, the worker
   viewport-sync is a genuine embed bug to fix (start from the trace above:
   `updateVisibleSources` not running in the worker context).

## Notes / gotchas recorded for later

- The engine's embed API lives under `neuroglancer/unstable/*` with **no
  stability guarantee** — the version is pinned exactly (`2.41.2`).
- Reading a WebGL canvas with `drawImage`/`getImageData` returns black
  (`preserveDrawingBuffer` is off); trust screenshots, not canvas readback.
- Chunk fetches happen in the worker and do **not** appear in Playwright's
  `page.on("response")`; instrument the *server* to see them.
