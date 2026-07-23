# Viz Studio spike — results

This records what the spike actually established, honestly, so the next person
(or the next session) does not have to rediscover it. It follows the plan in
`PLAN.md`.

## Bottom line

The hard architectural question — *can we run neuroglancer as the engine inside
our own React app, reading our OME-Zarr, packaged for Windows?* — is answered
**yes, end to end**. The demo volume fetches, decodes, and renders (verified in
a headless browser here; screenshots in `backend/_check`). Everything the spike
set out to prove is proven.

An early version showed flat grey with no pixels; a code review traced it to a
real worker-bundling bug (not a headless quirk, as first suspected) and it is
now **fixed** — see "The render bug and its fix" below.

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

1. `build-workers.mjs` pre-compiles both worker entry points with esbuild into
   real, self-contained bundles (all `#src/...` resolved). Runs before every
   build. It asserts each compiled worker is large, so a silent regression to
   the stub fails the build loudly.
2. `postbuild.mjs` copies the compiled `async_computation.bundle.js` to the site
   root, where the chunk worker loads it from at runtime.
3. `vite.config.js` sets `build.assetsInlineLimit: 0` so the worker is emitted as
   a real file (a data:-URL worker has no origin and cannot fetch chunks).
4. `package.json` build script chains them:
   `node build-workers.mjs && vite build && node postbuild.mjs`.

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

## Acceptance check (guards against the bug returning)

After building, `frontend/dist/assets/` must contain a **large** (~1 MB)
`chunk_worker.bundle-*.js`, and `frontend/dist/async_computation.bundle.js` must
exist (~1.5 MB). If either is missing or tiny (~669 bytes), the worker fix did
not take and the viewer will grey out. `build-workers.mjs` already fails the
build if the compiled workers are too small.

## Notes / gotchas recorded for later

- The engine's embed API lives under `neuroglancer/unstable/*` with **no
  stability guarantee** — the version is pinned exactly (`2.41.2`).
- Reading a WebGL canvas with `drawImage`/`getImageData` returns black
  (`preserveDrawingBuffer` is off); trust screenshots, not canvas readback.
- Chunk fetches happen in the worker and do **not** appear in Playwright's
  `page.on("response")`; instrument the *server* to see them.
