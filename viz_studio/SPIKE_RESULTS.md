# Viz Studio spike — results

This records what the spike actually established, honestly, so the next person
(or the next session) does not have to rediscover it. It follows the plan in
`PLAN.md`.

## Bottom line

The hard architectural question — *can we run neuroglancer as the engine inside
our own React app, reading our OME-Zarr, packaged for Windows?* — is answered
**yes, end to end**. The demo volume fetches, decodes, and renders — verified by
an automated headless-browser acceptance test (`backend/browsercheck.py`, which
strictly asserts pixels arrived and writes a screenshot to
`backend/_check/render.png` when you run it). Everything the spike set out to
prove is proven.

An early version showed flat grey with no pixels; a code review traced it to a
real worker-bundling bug (not a headless quirk, as first suspected) and it is
now **fixed** — see "The render bug and its fix" below.

## What is proven (here, in a headless browser)

- **Bundling (was the #1 risk — now retired).** neuroglancer 2.41 bundles and
  boots in Vite + React 19, mounted chrome-hidden in our own component. The
  production build (`npm run build`, served by Python) is the verified path; its
  two background workers are compiled ahead of time and emitted as real asset
  files (not inlined — that is what lets them fetch chunks; see the fix below).
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
  - **Call `setDefaultInputEventBindings(viewer.inputEventBindings)` after
    creating the viewer**, or nothing responds to the mouse. `makeMinimalViewer`
    builds the engine but installs no navigation bindings; neuroglancer's own
    entry points (`default_viewer_setup.js`, `main_python.js`) call this
    separately. Without it the panels still receive every DOM event and the
    volume still renders — it simply never moves. See "The interaction bug"
    below.
- **The OME-Zarr data pipeline works.** Python writes v0.4 / zarr v2; the engine
  reads the group, the multiscale pyramid levels, the array metadata, and the
  transform, and reports the layer ready with the correct coordinate space
  (`z, y, x`) and **correct physical scale** — the on-screen scale bar and the
  data bounding box are dimensionally right.
- **The supporting pieces work:** the 3-D multichannel demo generator
  (`backend/demo_data.py`), the stdlib server serving `dist/` + zarr on one
  origin (`backend/server.py`), and the headless-Chromium harness
  (`backend/browsercheck.py`).

## The render bug and its fix

The early "flat grey, no pixels" symptom was **not** a headless quirk (the first
theory). It was a real, deterministic bundling bug that would have failed on
Windows too — a code review caught it from the built artifact alone.

**Root cause.** neuroglancer ships its two background workers
(`chunk_worker.bundle.js`, `async_computation.bundle.js`) as tiny *source*
stubs — lists of `#src/...` imports that only a bundler can resolve. Vite, meeting
`new Worker(new URL(...))` inside a dependency, did **not** run those stubs
through its worker compiler; it copied the raw stub. A browser cannot resolve
`#src/...`, so the worker threw on load, never signalled "ready", and — because
the main thread queues all messages until the worker is ready — the entire
data-loading half of the viewer silently did nothing. Metadata (fetched on the
main thread) loaded; pixel chunks (fetched in the worker) never did.

**Fix** (in `frontend/`):

1. `precompile-workers.mjs` pre-compiles both worker entry points with esbuild into
   real, self-contained bundles (all `#src/...` resolved). Runs before every
   build. It asserts each compiled worker is large, so a silent regression to
   the stub fails the build loudly.
2. `copy-async-worker.mjs` copies the compiled `async_computation.bundle.js` to the site
   root, where the chunk worker loads it from at runtime.
3. `vite.config.js` sets `build.assetsInlineLimit: 0` so the worker is emitted as
   a real file (a data:-URL worker has no origin and cannot fetch chunks).
4. `package.json` build script chains them:
   `node precompile-workers.mjs && vite build && node copy-async-worker.mjs`.

**Verified here:** with the fix, the demo volume reaches `270/270` visible chunks
available and the blob "cells" render in all cross-sections and the 3-D view, in
the same headless container that previously showed grey. On your Windows/WebView2
machine (a real GPU) it will render at least as well.

## Try it on Windows

1. `conda env create -f environment.yml && conda activate zmart-viz`
2. `npm --prefix frontend install && npm --prefix frontend run build`
   (the build compiles the workers automatically — watch for the
   "compiled worker ..." lines).
3. `python run_demo.py` → a native window opens on the demo volume; the three
   blob channels render, scrolling changes the z-plane, and the 3-D view shows a
   volume.

## The interaction bug and its fix

Found on the first run of the native window on Windows (2026-07-23): the volume
rendered correctly and **nothing responded to the mouse** — no pan, no zoom, no
z-scroll, no 3-D rotation.

**Root cause.** `makeMinimalViewer` constructs the engine but does not install
neuroglancer's default input bindings; `setDefaultInputEventBindings` is called
separately by its own entry points, which we did not use. The panels received
every DOM event (verified: `mousedown`/`wheel` land on
`.neuroglancer-rendered-data-panel`) but no action was mapped to them, so the
navigation state never changed. `showUIControls: false` was *not* the cause —
that flag only ANDs into UI *visibility*, never into input bindings.

**Fix.** One call in `NeuroglancerView.jsx`, immediately after creating the
viewer. Verified: dragging a slice panel pans, plain wheel steps z, `control`
+wheel zooms, dragging the 3-D panel rotates.

**Why the render test missed it.** Rendering and navigation are independent —
with the bindings absent, every render assertion still passes. Confirmed by
removing the fix and re-running: the four interaction tests fail, the render
tests stay green.

## Acceptance check (guards against the bug returning)

`viz_studio/tests/` is the gate; run it with `pytest viz_studio/tests`. It
covers the demo volume's OME-Zarr contract, the server's HTTP contract, the
build artifacts, the render, and the four navigation gestures. The
browser-driven tests skip (with a reason) where the page is not built or no
Chromium is available.

After building, `frontend/dist/assets/` must contain a **large** (~1 MB)
`chunk_worker.bundle-*.js`, and `frontend/dist/async_computation.bundle.js` must
exist (~1.5 MB). If either is missing or tiny (~669 bytes), the worker fix did
not take and the viewer will grey out. `precompile-workers.mjs` already fails the
build if the compiled workers are too small, and
`tests/test_build_artifacts.py` asserts it from the emitted files.

## Notes / gotchas recorded for later

- The engine's embed API lives under `neuroglancer/unstable/*` with **no
  stability guarantee** — the version is pinned exactly (`2.41.2`).
- Reading a WebGL canvas with `drawImage`/`getImageData` returns black
  (`preserveDrawingBuffer` is off); trust screenshots, not canvas readback.
- Chunk fetches happen in the worker and do **not** appear in Playwright's
  `page.on("response")`; instrument the *server* to see them.
