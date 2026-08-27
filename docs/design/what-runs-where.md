# What runs where: the instrument, ZMART_analysis, and the page

Written 2026-08-27, on `claude/layered-view-operator-next-gcqxuu`. A rule for
deciding where a new piece of the operator page goes, the evidence that the code
already mostly follows it, the one control that already proves it, and the orders
that are still open.

**How to read this.** Statements are labelled.

- **Exists** — code on this branch, which you can open and read.
- **Proposal** — not built, offered here for a decision.

---

## The rule

> **Three parties, and each does one kind of thing.**
>
> - **The instrument** moves and captures. It produces pixels.
> - **ZMART_analysis** reads pixels and produces numbers. Focusing,
>   segmentation, feature extraction.
> - **The page** decides. Where to look, in what order, and what to keep.
>
> The first two are APIs — something outside the browser you hand work to and
> then ask about. The third is everything else.

Neither an instrument nor an image-analysis routine can run in a browser, and
that is the whole of why they are on the far side of a wire. Everything else is
a decision, and decisions belong where the operator makes them: geometry,
tiling, the plan, tuning, gating, drawing, and the state of the run as it is
being set up.

The rule is worth stating as a rule because the alternative — deciding case by
case whether a thing "feels like backend" — is what put a copy of the focus loop
in the bridge, where it drifted three ways at once and returned a column of zeros
to every operator who used the page.

---

## The distinction that does the work

Not "hard things are backend". The line is **what a party is looking at**.

The instrument is the only party that can move glass and expose a sensor. It is
asked for pixels and it does not know why.

ZMART_analysis is the only party holding the pixels afterwards. Everything it
does is the same sentence in three tenses: *given these planes, which is sharp;
given this tile, where are the objects; given this object, how big and how
bright.* Focusing is not a special case of instrument control — it is an
image-analysis routine that happens to be run before the picture rather than
after it.

The page is the only party that knows what the operator wants. It never looks at
a pixel to make a decision; it looks at numbers, which is why it can be a
browser at all.

---

## What ZMART_analysis owns

**Proposal**, except where marked.

| job | in | out |
|---|---|---|
| focus | a z-sweep at one place | the sharp height, and the curve it was chosen from |
| segmentation | one overview tile | labelled objects |
| feature extraction | the labelled objects | area, mean intensity, centroid, per object |

**Exists, in part.** Segmentation and feature extraction already go this way on
the notebook path: `discovery.py` submits each overview to the engine with a
`feature` key and drains `engine.results`. What does not go this way is
focusing — see the next section, which is the case for changing it.

All three have one shape, `submit` / `status` / `results`, and the bridge already
speaks that shape once (`POST /api/scan` starts work in a thread,
`GET /api/scan` polls it). So the analysis API is the same pattern a second
time, not a new one.

---

## The control that already proves focusing is analysis

**Exists, and it is a dead control.**

The operator page offers a choice of focus metric. `focus-map.js` charts two of
them against the same stack, labelled *Gradient-based* and *Entropy-based*, and
the chosen one decides the peak. The whole model sits in
`parts/microscope/pretend-sample/sweep.js`:

```js
export const METRICS = { brenner: {...}, dct: {...} };
export const SWEEP_N = 61;
export const SWEEP_HALF_UM = 34;
/** Tissue stays sharp over microns. Anything narrower than this is not tissue. */
export const MIN_TISSUE_WIDTH_UM = 4.5;
```

That is an image-analysis routine, written out in full — two sharpness metrics, a
61-plane sweep over ±34 µm, and a rule that rejects a peak too narrow to be
tissue, because a speck of debris is a hard edge in a single plane and will
out-score the sample. Its own docstring says why it exists: it models how an
autofocus ends up focused on dust.

**And it reaches nothing.** `live.js` sends the metric:

```js
async measureFocus(points, { metric } = {}) {
  return ask("/api/focus/measure", { points, metric });
}
```

`bridge.py` never reads `metric`. `focus_run.py` has no such parameter. It calls
the vendor's own `run_procedure({"name": "autofocus"})` and keeps whatever height
comes back. `live.js` admits the consequence in its own comment: live points come
back without sweeps and "the chart stays empty".

So on a real instrument the operator chooses a metric that does nothing, in front
of a chart that cannot draw, and the debris rule that is the entire point of the
step is not applied at all. The mock is not a rehearsal of the live path here —
it is a **specification the live path never implemented**.

**Proposal.** Focusing becomes: drive to the point, acquire a short stack, submit
it to ZMART_analysis, take the peak it returns. The vendor autofocus stops being
the mechanism. `sweep.js` stops being pretend and becomes the description of what
the analysis routine must do — including `MIN_TISSUE_WIDTH_UM`, which is the part
no vendor autofocus offers.

---

## What the front end already does

**Exists.** All of this is computed in the browser and never leaves it.

- `shared/carriers.js` — where the carrier's wells are.
- `shared/scanfields.js` — the shapes the operator drew, and the tiles that cover
  them. 830 lines, pure, micrometres from the carrier's own zero, no DOM and no
  app state.
- `shared/stage.js`, `stage-position.js` — where the stage is, in the page's terms.
- `steps/define_scan_area/` — the plan, and whether the stage can reach it.
- `steps/focus_strategy/` — where to measure height, and the surface fitted
  through what came back.
- `steps/refine_targets/gate.js` — the scatter the operator drags a rectangle over
  to choose targets.
- `parts/canvas/` — all the drawing.

And the picture itself: the canvas reads the acquisition straight out of the run's
zarr store over HTTP. `serve_a_run.py` exists only because a browser will not let
a page read files off a disk, so the run has to be handed out on a local address
instead.

---

## What the instrument API already does

**Exists.** Nine routes in `application/framework/bridge.py`, standard library
only — the microscope computer has no network to install packages from.

| route | what it does |
|---|---|
| `POST /api/connect` · `/api/disconnect` | open and close the session |
| `GET /api/setting` | read the instrument's state — **never moves anything** |
| `GET /api/acquisition_options` | what a capture can be set to |
| `GET /api/xyz` | where the stage is |
| `POST /api/xyz` | drive it there |
| `POST /api/state` | change settings on the instrument |
| `POST /api/acquire` | capture once, where it is standing |
| `POST /api/focus/measure` | drive to each point, focus, report the height |
| `POST /api/scan` · `GET /api/scan` | run the overview; poll the progress |

The readout/procedure split is load-bearing and should survive any change here.
`GET /api/setting` is the whole of recording a preset and nothing moves.
`POST /api/focus/measure` is the one preset-shaped request that *does* something,
which is exactly why it is its own verb rather than a flag on the readout.

Under this rule `/api/focus/measure` splits: the driving and the acquiring stay
here, the choosing of the peak moves to the analysis API.

---

## Where the line stops today

**Exists.** The seam ends at the overview scan. Steps 6, 7 and 8 — discover,
refine and acquire targets — are still rehearsed inside the window. Both `mock.js`
and `bridge.py` say so in their own docstrings.

`detection.js` is not calling cellpose. `detects()` is a nine-line stand-in
against invented cells:

```js
return diameter > settings.diameter * 0.70
    && diameter < settings.diameter * 1.55
    && cell.intensity > 0.36 + settings.cellprob * 0.05;
```

The Python for those steps does exist — `discovery.py` and
`steps/acquire_targets/widget.py` — but it is what the notebook runs, not what the
page reaches.

**Proposal.** Two routes, mirroring `/api/scan` because it is the same shape:

```
POST /api/detect    submit the overviews          (engine.submit)
GET  /api/detect    progress, and drained results (engine.status / .results)
```

What comes back is a table, not pixels: per object a centroid and its features.
Small JSON, and close to what `gate.js` already wants.

---

## Target curation is the gate, generalised

Curating targets in the operator window is not a new capability to build. It is
**manual feature curation**, and the page already does it — that is what step 7
is. Objects come back as a table of numbers, the operator looks at the numbers
and says which ones are worth imaging.

**Exists, and here is the one thing in the way.** `gate.js` hardcodes its two
axes. Area across, mean intensity up, in the maths and in the axis titles alike:

```js
c.area >= gate.aLo && c.area <= gate.aHi
&& c.intensity >= gate.iLo && c.intensity <= gate.iHi
```

```js
paint.fillText("cell area (µm²)", ...);
paint.fillText("mean intensity · ch2", ...);
```

Meanwhile the engine already returns more than two features per object.
`discovery.py` carries `area_px`, `eccentricity` and `mean_intensity` through on
every pick — and **`eccentricity` is extracted, returned, and thrown away**,
because the page has no axis to put it on.

That is the whole gap between "gating" and "curation": one is two fixed
features, the other is any of them.

**Proposal.** The features become data rather than identifiers. The analysis
result names what it measured; the page offers those names on the two axes; the
gate is expressed against whichever pair is chosen. Nothing else about the step
changes — the drag, the selection, the lighting-up on the canvas beside it all
work on a list of points regardless of what the axes mean.

Two things to settle when it is built:

- **Feature extraction is ZMART_analysis's job, and only its job.** The page must
  not compute a feature it was not given, or the same number will exist in two
  places and disagree. If an axis is wanted that analysis does not measure, the
  fix is in the routine, not in the page.
- **How many points.** `gate.js` is plain canvas, drawing every object one at a
  time. That is fine for one tile and not obviously fine for a whole carrier's
  worth. Whether it holds is a measurement, not a guess, and it is the same
  question the standalone target-picking app answered with a GPU scatter plot.

---

## The orders that are still open

Three separate decisions hide inside "in what order", and only the first is
settled.

**1. The plan comes before the points. Settled, and enforced by the code.**
`sharePoints` lays focus points over the positions the run will visit — a point
sits *on* a scan position, never beside one. So there must be a plan before there
can be points, which is why `define_scan_area` precedes `focus_strategy` in the
step order.

**2. Does the overview use the focus map? Undecided, and today the answer is no.**
`surfaceZ` is called only inside `focus-map.js`. The surface is measured, fitted,
drawn and never consumed: nothing in `scan_the_overview` reads it. The overview
does not currently scan at predicted heights.

There are two ways to close that, and they are genuinely different runs:

- **Two passes.** Measure focus at the shared points, fit the surface, then scan
  the overview one plane per tile at the height the surface predicts. Cheap, and
  it is what the current step order implies.
- **One pass.** Scan the overview as a short stack per tile and let
  ZMART_analysis return both the sharp plane (the picture) and the height (the
  surface) from the same pixels. The ordering question dissolves — there is only
  one drive — at a cost of *k* times the acquisition.

  This only becomes possible once focusing is analysis rather than a vendor
  procedure, which is the point of the section above. It is worth naming now
  because it is the reason to make that change beyond tidiness.

**3. In what order the points and tiles are visited. The page's to decide, and
today unoptimised.** `scanfields.js` emits tiles in plain raster order —
`for row … for col` — so every row ends with a full fly-back across the field.
Focus points are visited in the order they were laid. Neither is chosen for stage
travel, and on a large carrier that is the difference between a run and a long
run.

The rule settles *who* decides: the page hands the instrument a list, and the
order of that list is the plan. The instrument drives what it is given and has no
opinion. So visit order needs no new route and no backend change — it is a
change to how `scanfields.js` emits, and nothing downstream can tell.

Serpentine is the obvious first answer. Whether to go further should be measured,
not assumed.

---

## The one thing that straddles the line

**Exists, and is the reason to decide this now.** `discovery.py` does two jobs. It
calls the engine, *and* it converts each object's pixel centroid into a frame
`(x, y)` through `overview_pixel_to_frame`, parsing pixel size and image size out
of the OME-XML in order to do it.

Under this rule only the first job is analysis. The second is geometry, and the
browser already owns that mapping — it cannot draw the overview in the right place
without it.

**Proposal.** The analysis routes hand back **pixel** coordinates, and the page
converts them the way it converts everything else. Otherwise the same
image-to-frame mapping exists twice, once in Python and once in JavaScript, and
that is the focus-loop story again: a procedure written twice is a procedure that
will differ, and the difference will be silent.

---

## The consequence to accept, or refuse

The tiling maths lives only in the browser. `scanfields.js` has no Python
counterpart — `geom.py` is not it, that is crop-window maths for the notebook's
figures and the simulation hijack. So laying a plan is already a browser-only
capability, and every step that moves into the front end widens the gap.

That is fine if the page is the product and the notebook is a scripting escape
hatch. But it is the opposite of the arrangement built for focus, where
`focus_run.py` was deliberately pulled out into `parts/microscope/` so that the
page and the notebook could not drift.

**The codebase is currently doing both, and only one of them can be the plan.**
This note does not settle it. It records that the choice is open, and that
adopting the rule above means choosing the first: the page decides, the notebook
scripts what the page would have decided, and the two share only what crosses to
an API.

---

## What is not proposed here

- Moving cellpose, or any analysis routine, into the browser. They are
  ZMART_analysis; they are backend by the rule, and by torch.
- Moving anything that drives the stage. Also backend by the rule.
- Step 8. Acquiring targets moves an instrument, so its verbs join the instrument
  API when that work starts, exactly as `/api/scan` did.
- Deleting the vendor autofocus. It stays available; it stops being the thing the
  focus step is built on.
