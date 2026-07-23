# ZMART Viz Studio — spike plan

A standalone, Windows-native, conda-installable, lightweight visualization
studio: **your own React UI + neuroglancer engine**, driven by a **Python
backend**, with a **demo mode** that fully simulates being at the microscope
on small synthesized data (no hardware, no conversion).

This document is the plan to review *before* building. It records the locked
decisions, the architecture, exactly what the spike proves, the real risks,
and the sequence.

## Why this exists (the decision, recapped)

A long design conversation converged on one internally-consistent stack. Each
choice was forced by a concrete requirement:

| Layer | Choice | Forced by |
|---|---|---|
| Engine | **neuroglancer** | out-of-core terabyte 3D — mesoSPIM lightsheet volumes viv can't rotate at full res |
| UI | **your own React** (napari-style) | total UI control + active linked plots (hard in napari's Qt) |
| Window | **pywebview** (WebView2 = Chromium on Windows) | native, lightweight, full WebGL2; no Electron/node for the user |
| Backend | **Python** | analysis + microscope control stay Python (the brain/hands) |
| Data | **multiscale OME-Zarr** | streams to neuroglancer over HTTP; demo synthesizes it directly |
| Delivery | **conda** + prebuilt frontend as package data | one environment file, no node on the user's machine |

The delivery row says conda, but it cannot be conda *only*: pywebview is not on
conda-forge, so the environment file carries a small pip section. That is a
constraint on the packaging milestone (M6), not on the design.

Windows-only is confirmed, which is what makes pywebview a no-compromise
choice: on Windows its webview *is* Chromium, so neuroglancer runs on the
exact engine it is tuned for.

## Architecture

```
viz_studio/
  frontend/         Vite + React + neuroglancer  ->  built to static assets
  backend/          Python: stdlib HTTP server + zarr serving + demo generator + launcher
  environment.yml   conda env (Python + pywebview + serving; no node for the user)
```

Two processes on the user's machine, talking over **one loopback origin**:

- **Python backend** — a stdlib `ThreadingHTTPServer` (reusing ZMART's existing
  `webapp/_server.py` pattern, *not* FastAPI — the job is "serve a folder of
  small zarr files + two JSON routes", which needs no framework and keeps the
  conda-forge/offline promise). It serves the built frontend `dist/` **and** the
  OME-Zarr store from the same port, exposes a couple of JSON endpoints
  (annotations, one control intent), and generates the demo volume. This is
  where analysis and (later) real microscope control live.
- **React frontend** — mounts a neuroglancer `Viewer` (`makeMinimalViewer`,
  built-in chrome hidden via `showUIControls:false`), wraps it in your own
  control panel, reads OME-Zarr for pixels via a `zarr://` source, and talks to
  the Python endpoints for everything else.

**Single origin matters:** in the shipped app, the frontend and the zarr are
served from the *same* `http://127.0.0.1:PORT` (never `file://`), so ES modules
and web workers load with no CORS friction. For local dev (Vite on 5173), a
Vite dev proxy forwards `/data` and `/api` to the Python server. OME-Zarr is
many small chunk files, each a plain full-file `GET` — **no HTTP range support
needed.**

The seam is exactly the client/server split ZMART's existing webapp already
uses (Python `RunFlow`/`Session` backend, JS frontend over HTTP/SSE) — this
extends a proven pattern rather than inventing one.

### The state bridge (the heart of "my UI, their engine")

neuroglancer's viewer state is an observable object. The bridge is two-way:

- **Outbound** (your UI → engine): a control changes → we mutate neuroglancer
  state (add/remove layers, `shaderControls` for contrast, layout for
  2D/3D, position for z-scrub, annotations for boxes/labels).
- **Inbound** (engine → your UI): the user drags a box in-canvas → we
  subscribe to the state change → your React model updates to match.

Your app stays the source of truth; neuroglancer is the render + interaction
surface.

## What the spike proves (scope)

Small synthesized data only. **M1–M4 are pure browser-side and need no
backend** — they run against a Vite dev server pointed at a statically-generated
zarr, so the risky work is proven before any Python is written. In dependency
order:

1. **Build smoke test (the gate)** — neuroglancer mounts and bundles in Vite.
   Concretely: (a) `optimizeDeps.exclude:['neuroglancer']`; (b) import the API
   from `neuroglancer/unstable/...`; (c) verify **both** `vite dev` **and**
   `vite build` (they fail differently — the worker/`import.meta.url` issue is
   build-time); (d) confirm `dist/` emits the hashed worker chunks and they load
   with no 404s.
2. **Render** — the synthesized multi-channel 3D OME-Zarr (v0.4/zarr v2)
   displays in a mounted, chrome-hidden neuroglancer, **at correct physical
   scale** (verifies the NGFF data contract, not just that pixels appear).
3. **Control panel drives the engine** — add/remove a channel layer,
   brightness/contrast per channel (`shaderControls`), 2D↔3D + MIP/volume toggle
   (`layout`), z-scrub through the stack (`position`). All from your React UI,
   via the viewer state object.
4. **Movable labeled 3D box, round-trip** — place + move a box from a React
   button (outbound, `AXIS_ALIGNED_BOUNDING_BOX`); drag it in-canvas and watch
   React state update (inbound, the annotation source's `childUpdated` signal).
   This is the true test of the bridge and the reason the embed (not iframe) is
   mandatory.
5. **Python seam** — the stdlib backend generates the demo zarr, serves it +
   `dist/` on one origin, and accepts one control **intent** (a stub "move stage
   to this box" endpoint that echoes the box coords) so the command path is
   exercised end-to-end.
6. **Demo mode** — a full "at the microscope" experience: **one excellent**
   multi-channel 3D volume (one volume exercises every control path), on small
   data, launchable with no hardware.
7. **Packaging** — a pywebview (WebView2) launcher for Windows and a conda
   `environment.yml`; the prebuilt `dist/` shipped as package data so the user
   needs no node. Cannot be validated on Linux — shipped marked "untested on
   Windows", with a WebView2-runtime check in the launcher.

Because this container is Linux, the pywebview *window* can't run here — but
**headless Chromium here is the same engine as WebView2**, so neuroglancer
rendering and the box round-trip are proven in Chromium via Playwright as a
valid proxy, with screenshots.

## Risks and mitigations

Both a feasibility review (which inspected the installed neuroglancer 2.41.2
package directly) and an architecture review informed this list. Net: R1 is
**smaller** than first feared; R5 and a new R6 are the durable risks.

- **R1 — embedding neuroglancer in Vite.** *Lower than it looks.* neuroglancer
  2.41 ships pre-compiled ESM with **pre-bundled workers** using
  `new Worker(new URL("./chunk_worker.bundle.js", import.meta.url), {type:"module"})`
  — the exact idiom Vite supports natively. The one real gotcha is Vite's
  dev-mode dep pre-bundling mangling that `new URL`; fix is
  `optimizeDeps.exclude:['neuroglancer']`. Prove at M1. *There is no turnkey
  Vite example, so M1 is genuine (≈1-day) integration work, not copy-paste.*
- **R1-fallback — iframe is NOT a true fallback for this app.** An iframe can
  only render + take coarse serialized state; it **cannot deliver M4's live
  box-drag round-trip** (that needs the in-process `childUpdated` signal). So if
  M1 fails, the fix is the Vite worker/optimizeDeps config — *not* switching to
  iframe. iframe is a render-only degraded mode, nothing more.
- **R2 — neuroglancer WebGL2 under WebView2.** Low: WebView2 is Chromium.
  Proxy-tested in headless Chromium here.
- **R3 — smoothness of two-way annotation sync when dragging.** *Mitigation:*
  mounted `Viewer` + the annotation source's first-class `childAdded/
  childUpdated/childDeleted` signals (not polling, not URL state).
- **R4 — lightweight vs. neuroglancer's bundle heft.** A few MB of JS;
  acceptable as prebuilt static served locally. Node stays a build-time-only
  dependency, never the user's — *this holds only if the built `dist/` is
  committed/packaged as package data*, which the packaging step must do
  explicitly.
- **R5 — OME-Zarr flavor (co-top risk).** neuroglancer reads **v0.4/zarr v2**
  reliably; **v0.5/zarr v3 is historically flaky** (google/neuroglancer #651:
  chunks silently not loading). *Decision, not "verify later":* the demo writer
  targets **OME-Zarr v0.4 / zarr v2**; v3 is out of scope for the spike. Verify
  correct physical scale at M2.
- **R6 — reliance on the `unstable/` API (new, and the most durable).** The
  embed API lives under `neuroglancer/unstable/*` with no stability guarantee.
  *Mitigation:* pin the exact version (`2.41.2`, not `^2.41.2`) and budget
  review time on every upgrade. Bundling is a one-time fight; this recurs.

## Milestones (sequence)

M1–M4 run against a Vite dev server + static zarr — **no backend yet.**

- **M1** build smoke test — neuroglancer bundles and boots in `vite dev` *and*
  `vite build` (R1 gate; `optimizeDeps.exclude`, `unstable/` imports, worker
  chunks load).
- **M2** render the synthesized demo OME-Zarr (v0.4/zarr v2) at correct scale.
- **M3** wire the React control panel (layers, contrast, 2D/3D, z-scrub, MIP).
- **M4** movable labeled box, two-way round-trip (`childUpdated`).
- **M5** Python backend: stdlib `ThreadingHTTPServer` serving `dist/` + zarr on
  one origin + demo generator + one echo control-intent endpoint.
- **M6** pywebview launcher (with WebView2-runtime check) + conda
  `environment.yml` + prebuilt-assets-as-package-data path.
- **M7** headless-Chromium proof + screenshots of the full demo experience.

## Deliverables

- `viz_studio/` runnable app with a one-command **demo** launch.
- pywebview Windows launcher + conda `environment.yml`.
- README written for the biologist/microscopist audience (per repo CLAUDE.md).
- Screenshots proving render, controls, 3D, and the box round-trip.

## Non-goals (explicitly out of scope for the spike)

- Real Stellaris/mesoSPIM → OME-Zarr conversion (deferred; live acquisition
  writes zarr directly, so a converter is only for pre-existing legacy files).
- Full integration with ZMART's acquisition `Session` / workflow.
- napari-parity polish. The spike proves the path; it is not the product.

## Open questions — resolved by review

1. **Embed vs iframe** → **Mounted `Viewer` embed**, decisively. The in-process
   `childUpdated` signal is what makes the box round-trip (M4) work; iframe
   would forfeit the one thing the architecture exists to prove. Keep iframe
   only as a render-only degraded mode if M1 somehow fails.
2. **Backend framework** → **Reuse ZMART's stdlib `ThreadingHTTPServer`**, not
   FastAPI. The workload is static-chunk serving + two JSON routes; the repo's
   own pattern already does this and keeps the conda-forge/offline/lightweight
   promise. Serve `dist/` + zarr from one loopback server; Vite proxy for dev;
   inherit the loopback bind + `Host`-header check.
3. **Where it lives** → **In-repo `viz_studio/`** for the spike. One clone, one
   conda env, easy borrowing of the sim's channel conventions and the server
   pattern; node toolchain quarantined inside `frontend/`. Split to its own repo
   only if it graduates into an independently-released product.
4. **napari-parity in the spike** → **Minimal, chosen to cover distinct state
   paths, not feature count**: layer add/remove, per-channel contrast
   (`shaderControls`), 2D↔3D + MIP (`layout`), z-scrub (`position`), labeled box
   (`annotations`). That set already touches every category of outbound mutation
   plus the one inbound path. Colormaps, linked plots, ROI stats are repetition
   of proven paths — they belong to the product, not the spike.

## Demo data (built first, decoupled from the embed risk)

`backend/demo_data.py` synthesizes the "at the microscope" volume: a
(channels, z, y, x) = (3, 48, 320, 320) `uint16` volume, three channels
(`structure` + `marker-a` + `marker-b`) following ZMART's `*20000+800`
convention, with soft 3-D gaussian "cells" and a deliberate marker overlap
(single- and double-positive cells). Written as **OME-Zarr v0.4 / zarr v2** with
a 4-level resolution pyramid and an `omero` block for default channel colours
and brightness windows. Anisotropic voxels (z=2.0, y=x=0.35 µm) so the physical
scale check at M2 is meaningful. No microscope, no converter.
