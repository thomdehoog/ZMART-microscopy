# From prototype to the real viewer — the integration plan

A step-by-step plan for putting the prototype's control surface
(`prototype/index.html`) onto the spike's neuroglancer engine reading real
OME-Zarr. It is the detailed, file-level companion to
`INTEGRATION_ROADMAP.md`: the roadmap says *why* and *in what order at the
product level*; this says *which control maps to which engine feature, in which
file*.

## The good news: both halves already exist

This is a wiring job, not a rewrite. Two pieces are already built and working;
the task is to join them.

**The engine half is done** (`frontend/src/`, `backend/`):

- `NeuroglancerView.jsx` mounts a headless neuroglancer with all of its own UI
  switched off and hands back the live `viewer`.
- `App.jsx` already drives everything through `viewer.state.restoreState({...})`:
  `shaderFor()` builds the per-channel contrast window (an `invlerp` range),
  colour, and — in 3-D — an opacity uniform; `layout` switches the plane and the
  volume; layers come from `/api/config`.
- `backend/server.py` already serves the image as OME-Zarr under `/data`,
  answers `/api/config` with one layer per channel (window, colour), and has a
  `POST /api/goto` endpoint stubbed (it receives a box's corners and, on real
  hardware, would move the stage).
- `run_demo.py --data <store.ome.zarr>` already opens a **real** OME-Zarr store,
  not just the demo. So real data can be viewed *today*, with the spike's
  current (simpler) panel.

**The interface half is the prototype**: a fuller, friendlier control surface —
interactive contrast with a histogram and an auto button, an opacity slider,
Z and T sliders, an annotations layer with point/box tools, a targets list with
"send to microscope", and URL-chosen samples. It is drawn with a stand-in
renderer today; production points these same controls at the engine above.

## Control-by-control map

For each control the prototype offers, this is the neuroglancer mechanism that
implements it and how much work it is. "Exists" means the spike already does it;
"wire" means the engine supports it and the panel needs connecting; "build"
means real new work.

| Prototype control | neuroglancer mechanism | Status | Confidence |
|---|---|---|---|
| Layer per channel | `/api/config` → one image layer each | **exists** | high |
| Visibility (eye) | `layer.visible` in the restored state | **exists** | high |
| Colour per channel | `shaderFor()` colour term | **exists** | high |
| Contrast (black/white + histogram + auto) | `shaderFor()` `invlerp` range, set live from the sliders | wire | high |
| Opacity per channel | shader opacity uniform (3-D) / `layer.opacity` (2-D) | wire | med-high |
| 2-D / 3-D toggle | `layout` = slice vs `3d` | **exists** | high |
| Z slider | cross-section position on `viewer.state` (the wheel already scrolls it) | wire | medium |
| T slider | position along a `t` dimension in the store's coordinate space | build | medium |
| Annotations layer (points, boxes) | a neuroglancer annotation layer + an input tool to place them | build | medium |
| Targets list + recolour + hide | read back the annotation layer's annotations; layer colour/visibility | build | medium |
| Send target → microscope | box corners → existing `POST /api/goto` | wire | high |
| Choose sample (channels/dims/time) | already answered by `/api/config` from the store's metadata | **exists** | high |

The histogram deserves a note: the prototype computes it in the browser from the
synthetic volume. Against real data, either the server computes a coarse
histogram from the store's coarsest pyramid level and sends it with
`/api/config` (cheap, recommended), or it is read from the store's `omero`
metadata if present.

## The data path, and what "time" needs

Real data flows exactly as it does in the spike today:

```
acquisition ──write──▶ OME-Zarr on disk ──HTTP chunks──▶ neuroglancer engine
                       /api/config ──what to open───────▶ React app (panel)
                       /api/goto  ◀──a box to image──────  annotations
```

Nothing is copied into the viewer; the engine streams the chunks the current
view needs. The one axis that needs care is **time**: the T slider works only if
the store is written with a time axis (the standard `t, c, z, y, x` layout) and
neuroglancer is given a position along that axis. mesoSPIM data is a single
timepoint, so it will not exercise this — keep one genuine timelapse store as a
test, as the roadmap notes.

## File-by-file changes

Everything lands in the spike's stack (`viz_studio/frontend`, `viz_studio/backend`);
the prototype stays as the design reference.

- **`frontend/src/LayerPanel.jsx`** — grow from the eye + colour swatch it has
  today into the prototype's panel: add the opacity slider, the contrast
  black/white sliders with the histogram and the auto button, and keep the
  napari-style layer rows. Each control updates React state.
- **`frontend/src/App.jsx`** — extend `shaderFor()`/`layersFor()` so the live
  contrast range and opacity come from that state, and keep applying them with
  `restoreState`. Add the Z and T sliders here (they set positions on
  `viewer.state`). Own the annotation-layer state alongside the image layers.
- **New `frontend/src/annotations.js` (or a component)** — create the neuroglancer
  annotation layer, bind a "place point / drag box" tool, read annotations back
  out for the targets list, and post a box to `/api/goto`.
- **`backend/server.py`** — add `GET/POST /api/annotations` to persist what was
  drawn beside the store, and have `/api/config` include a coarse per-channel
  histogram and (when present) the time axis length.
- **`backend/stores.py`** — report the store's dimensions including `t`, so the
  panel knows whether to show a T slider (exactly the prototype's rule: show a
  slider only for an axis that exists).

## Suggested order

Do the cheap, high-confidence wins first, each verifiable on real data with the
existing engine, before the genuinely new pieces:

1. **Contrast + opacity sliders** on the existing engine — pure `shaderFor`
   wiring, immediately visible on a real store via `run_demo.py --data`.
2. **Z slider** — connect a slider to the cross-section position the wheel
   already moves.
3. **Histogram in `/api/config`** — so contrast has a real distribution to show.
4. **Annotation points + the `/api/goto` box** — the step that makes it a ZMART
   tool; the endpoint already exists.
5. **T slider** — once a timelapse OME-Zarr is available to prove it.

## Honest testing note

Unlike the prototype, this cannot be fully built or run in the headless Linux
container used here: neuroglancer needs an `npm` build, a real browser with a
GPU to render, and an OME-Zarr store to read. So this integration should be
built and checked where it can actually run — the microscope PC (the spike's
native window was validated on Windows on 2026-07-23) — rather than assumed
working from code that never executed. Treat each step above as "done" only once
it has rendered real data on that machine.

**To see real data today**, before any of this is wired: build the spike's
frontend once and point it at a store —

```
npm --prefix frontend install && npm --prefix frontend run build
python run_demo.py --data /path/to/acquisition.ome.zarr
```

— which already opens real OME-Zarr through neuroglancer, with the spike's
current panel. This plan is about giving that same engine the prototype's fuller
controls.
