# The volume view: what works, what does not, and where to start

Written 4 August 2026, at the end of a long session, for picking up
three-dimensional navigation in the next one. Everything below was measured on
screen rather than reasoned about, and the numbers are here so a new attempt can
tell progress from noise.

Branch `viewer-plus-scanfields`, head `5ca162d`. Everything described is pushed.

---

## Start here

**The one thing to fix is rotation.** A plain drag in a volume measures *no change
at all* — 0.0 grey levels, 0.0 pixels of movement. Everything else on this page is
context for that.

The next thing to test is one hypothesis, stated so it can be proved or dropped in
an hour:

> `emptyTheEnginesOwnBindings` (in `options/neuroglancer-under/viewer.js`) does not
> detach the engine's default bindings — it **empties tables that are shared by the
> whole page**, including the module-level singletons neuroglancer keeps in
> `lib/ui/default_input_event_bindings.js`. That is why
> `setDefaultInputEventBindings` cannot put them back: it re-adds parents that are
> now empty. The suspicion is that emptying them also breaks the action dispatch
> those bindings feed, which would explain why bindings **set by name** on
> `viewer.inputEventBindings.perspectiveView` are demonstrably applied and still do
> nothing.
>
> **Test:** at open, detach the engine's defaults from this viewer's tables rather
> than emptying them, then bind by name for a volume and drag.

If that is wrong, the next suspect is that the perspective panel registers its
action listeners at construction, before the layout is switched to `3d`.

## A retraction, added 6 August 2026: the volume view refines perfectly well

Recorded here beside the rotation fault because the two look identical from the
operator's chair — a volume that will not respond — and one of them is not a fault
at all. This one is about `viz_studio`'s own viewer rather than the
`options/neuroglancer-under` one above, but the trap is the same in both and it
cost an afternoon and two reviews.

**What was claimed.** That the volume cannot choose a finer level of the pyramid,
because neuroglancer picks its level from the spacing along the viewing direction
and our pyramid never changes z. The proposed fix was to halve z when writing —
that is, to change how every run is written.

**All three parts of it were wrong.**

1. The selection is on **voxel volume, not z spacing**.
   `forEachVisibleVolumeRenderingChunk` in `volume_rendering/base.js` (lines 44-75
   of the installed 2.41.2) takes each level's `|chunkLayout.detTransform ×
   viewDet|` and keeps the coarsest one whose value still clears
   `(depthRange / depthSamples)³`. A determinant is direction-blind. Halving y and
   x alone still quarters that quantity from one level to the next — 4096× across
   a six-level ladder — so there was always plenty to choose between.
2. **The sweep varied the wrong zoom.** `crossSectionScale` and `projectionScale`
   are separate trackables. It set `navigationState.zoomFactor`, which is the flat
   view's and which the volume view does not read. Nothing moved, and "nothing
   changed" was duly reported. `frontend/src/ScaleBar.jsx:90` documents this exact
   trap in this repository.
3. **The readout was the wrong quantity too.** The volume renderer reports
   `cbrt(bestViewVolume × …)`; what was quoted was `medianOf3(effectiveVoxelSize)`,
   which is the *slice* view's figure.

**Re-measured against `perspectiveNavigationState.zoomFactor`, the volume walks
the whole pyramid:**

```
projection zoom   4096   1024    256     64     16      4      1
volume layer      20.8   20.8   20.8    2.6   0.33   0.33   0.33  um
                  (L6)                  (L3)  (L0, full resolution)
```

Confirmed again afterwards on the demo volume in `viz_studio`, from a different
quantity so as not to repeat the same reading twice. Sweeping
`perspectiveNavigationState.zoomFactor` and reading the volume render layer's own
`highestResolutionLoadedVoxelSize`:

```
projection zoom   0.03 … 10    30      100     512 (where it opens)
volume layer      0.35 µm    0.70 µm  1.40 µm  1.40 µm
                  (L0)       (L1)     (L2)     (L2, the coarsest the demo has)
```

Note where the last column sits. The view **opens** at a projection zoom of 512,
which on this data is already the coarsest level there is — so an operator whose
wheel does nothing in 3-D never sees anything else, and the picture they are shown
is exactly what a renderer stuck on the coarsest level would look like.

**What was actually broken was one line of binding.** The wheel had been rebound
to zoom on `bindings.sliceView` only, so the perspective panel kept the engine's
defaults — plain wheel steps z, zoom behind Control. On a run one plane deep the
wheel therefore did nothing at all in 3-D, and the operator was stuck at the
opening projection zoom, which is in the 20.8 µm regime. Both panels now get the
binding; see `CONTROLS.md` §1.

**Nothing is wrong with the writer, and no pyramid change is needed.** The lesson
to carry into the rotation work above is the check that would have caught all
three of these in a minute: *vary it, and confirm the input you varied is the one
the system reads.*

## How to get to it in one minute

Three commands, three environments — see `TESTING_ON_REAL_HARDWARE.md` for why:

```bash
# zmart-viz
python application/workflows/target_acquisition/serve_a_run.py <a stack>.ome.zarr --port 60810
# zmart-microscopy
npm --prefix application run dev
python application/dev_window.py \
  --url "http://127.0.0.1:5174/?workflow=canvas_layers&overview=http://127.0.0.1:60810/<name>.ome.zarr"
```

The address lands on the canvas step. Press **Volume**. The store this was all
measured on is `Z:\transfer\Nikita-ZMB-transfer\Regina-skin\fused.zarr` — 75 GB,
two colours, 833 planes, and out of spec in two ways the file server repairs on
the way out (`live_overview_demo.py`).

## What works, measured

| | evidence |
| --- | --- |
| the toggle exists, neuroglancer only | `viv` answers `canShowVolume: false`, so no button is drawn |
| the volume renders | 29.2% of the window lit, against 1.0% before the shader was fixed |
| **the wheel zooms the camera** | the specimen went 145.8 → 237.3 across while the flat reading correctly stayed at 6.45 µm/px |
| our gestures come off in volume mode | a plain drag used to pan the flat view by 900 µm; it no longer does |
| the view opens on the specimen | centre from the picture, not the declared canvas — see `where-the-specimen-is.js` |

## What does not work

| | evidence |
| --- | --- |
| **rotation** | plain drag and shift+drag both measure 0.0 change |
| the plane slider hides in volume | it does not, though the code path reads correctly and the handler runs |
| the volume looks good | it is a grey slab; see "transparency" below |
| any of it is tested | no browser test covers the volume at all |

## Three things that are easy to conflate

Getting these mixed up cost most of a session.

| | what it means | where it applies |
| --- | --- | --- |
| **zoom** | how large the projection is on screen | both |
| **the depth slider** | *which plane* of the stack is drawn | **flat only** — a volume draws all of them at once |
| **depth range** | how thick a slab the engine renders | the engine's own, `alt+wheel` |

The wheel felt broken because it moved the flat view's `µm per pixel` from 6.45 to
1.07 while nothing on screen changed size: a perspective camera does not draw with
that number. The slider should not be on screen in a volume at all; what belongs
there is the depth *range*.

## A volume asks the opposite of a slice

The shader is the part most likely to be got wrong again, so it is worth stating
plainly:

* **Flat** — the colour carries the brightness (`colour × v`) and the transparency
  says only whether a spot was imaged. Ground nobody has imaged stays clear so the
  layers under it show through.
* **A volume** — the colour is emitted at full strength and **the value goes in
  the alpha**. That is what makes a ray accumulate.

Emitting `colour × v` *with* alpha `v` attenuates twice: the volume lit 1.0% of
the window against 15.7% for the same data flat. It looks exactly like an engine
failing to render and it is arithmetic. `viz_studio/frontend/src/scene.js` has had
the correct volumetric shader all along — copy it rather than deriving it again.

## Transparency, which is the interesting problem

The volume is currently a grey slab, and the reason is worth understanding before
anybody reaches for the brightness.

Alpha **compounds along a ray**. A per-sample alpha of 0.05 over 100 samples is an
accumulated opacity of 1 − 0.95¹⁰⁰ ≈ **99.4%**. Background that reads as "faintly
dark" on a slice reads as "completely solid" in a volume, and the specimen's
interior hides its own structure.

So a volume wants:

1. **A much higher floor.** For a slice the 1st percentile is right — you want to
   see the background. For a volume, anything you can see you cannot see through,
   so the floor belongs nearer the 50th–90th percentile.
2. **A non-linear transfer**, so faint material contributes less than linearly.
3. **A sample count** (`volumeRenderingDepthSamples`), which costs graphics-card
   time linearly and was deliberately not touched.

Which means **`brightness.js` computes a window that is correct for the flat view
and wrong for a volume by construction** — same numbers, different job. The honest
fix is a window of its own for the volume, and it is a decision rather than a
tweak.

## What was tried and did not work

Kept because each looked right and will be proposed again.

* **`setDefaultInputEventBindings` to restore rotation.** Cannot work while the
  defaults are emptied rather than detached; see "Start here".
* **Proportional alpha as the cure for a faint volume.** It is the correct model
  and moved 1.0% to 1.3% — the faintness was the double attenuation above.
* **`volumeRenderingGain`.** Set to 3, changed nothing measurable. It is the right
  control for an operator to have, and it was not the fault.

## Where the pieces are

| | |
| --- | --- |
| the engines | `viz_studio/options/<name>/viewer.js` |
| the interface | `viz_studio/options/contract.md` — `canShowVolume`, `showVolume`, `theDepthItCanShow` |
| shared rules | `gestures.js`, `planes.js`, `brightness.js`, `opening-view.js`, `where-the-specimen-is.js` |
| the page | `application/src/canvas/panel.js` |
| what a real store said | `viz_studio/options/RESULTS.md`, top section |
