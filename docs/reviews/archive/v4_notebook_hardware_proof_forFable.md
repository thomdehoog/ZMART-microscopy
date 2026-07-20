# Fable review request: v4 target-acquisition hardware proof of principle

Review the branch `claude/leica-config-loading-review-ammwaz` in the
`thomdehoog/ZMART-microscopy` repository. Review the complete branch against
`origin/main`, then inspect the latest commit separately so regressions introduced by
the final hardening pass are easy to identify.

This is a safety-adjacent proof of principle for a real Leica Stellaris 5 microscope.
The primary artifact is:

```
workflows/target_acquisition/zmart_microscopy_v4.ipynb
```

The notebook must run from top to bottom on the microscope workstation and perform the
existing workflow without hidden setup steps:

```
connect -> set origin -> capture overview/target jobs -> read scan positions
-> measure focus -> acquire overviews -> inspect mosaic -> segment cells
-> gate targets -> acquire targets -> inspect pairs -> write report -> disconnect
```

Do an adversarial code review. Do not implement fixes. Prioritize incorrect stage
coordinates, unsafe or surprising hardware actions, broken cross-package contracts,
silent failures, misleading UI state, and missing integration coverage over style.

The intended scope is deliberately narrow. This branch should make the existing proof
of principle complete and reliable. It should not add new acquisition modes, deep
features, a new analysis framework, or broad abstractions.

## Repositories and revisions

Primary repository and branch:

```
https://github.com/thomdehoog/ZMART-microscopy
branch: claude/leica-config-loading-review-ammwaz
review range: origin/main...HEAD
```

External analysis contract:

```
https://github.com/thomdehoog/smart-analysis/tree/v4-engine
```

Read the external repository at the `v4-engine` branch. In particular, inspect:

```
engine/_pipeline.py
engine/_run.py
workflows/target_acquisition/pipelines/overview.yaml
workflows/target_acquisition/steps/segment_tile.py
workflows/target_acquisition/steps/pick_targets.py
workflows/target_acquisition/README.md
workflows/_features.py
```

The notebook uses only Cellpose segmentation and the classical values already emitted
by the target-acquisition pipeline: area, eccentricity, and mean intensity. Deep
features are explicitly out of scope.

## Intended design

### Driver to controller

Importing the Leica `zmart_adapter` registers a connection and a table of controller
operations. `zmart_controller` resolves the connection, opens one `Session`, forwards
calls without interpreting driver-owned dictionaries, and propagates exceptions. The
Leica adapter owns:

- connection to LAS X and machine-config loading;
- frame origin and objective-aware frame math;
- stage-limit enforcement and movement;
- selected-job state capture/reapplication;
- scan-field, focus-point, root, and autofocus procedures;
- acquisition, native AutoSave collection, stage-aligned OME-TIFF persistence;
- a structured `planes` manifest plus the compatibility `images` list.

The controller should remain vendor-agnostic. The workflow and visible notebook should
not import or call Navigator Expert directly.

### Controller to workflow and notebook

The notebook keeps the explicit controller `Session` returned by `workflow.connect`.
Workflow functions may call only the controller surface: `get_state`, `set_state`,
`get_xyz`, `set_xyz`, `run_procedure`, and `acquire`.

The notebook activates the interactive matplotlib backend before importing plotting
code. The canonical environment installs `ipympl`. The analysis engine and its
`overview` pipeline are loaded before any hardware action, so a missing or wrong
smart-analysis checkout fails before the microscope run starts.

The notebook refuses to continue when machine-specific stage limits are not active,
or when the operator captured the same LAS X job as both overview and target.

### Image and coordinate contract

The Leica adapter saves one canonical 2-D OME-TIFF per `(t, z, c)` plane. Its acquisition
record includes:

```
{
    "images": ["..."],
    "planes": [
        {"t": 0, "z": 0, "c": 0, "path": "..."},
        ...
    ],
}
```

The target workflow supports one timepoint and one z plane, with one or more channels.
It must reject z stacks/time series rather than guessing from filename order. Channel
planes should remain available to the overview viewer; segmentation uses the primary
channel.

The driver applies the measured camera-to-stage orientation while saving. Therefore
the saved image is already stage-aligned and the smart-analysis `image_to_stage` matrix
must be identity. Pixel size is supplied separately as `(width_um, height_um)`.
ZMART stores image shapes as `(height, width)`; smart-analysis expects
`source_image_size_px=(width, height)`. Treat any swap, double scaling, sign error, or
half-hidden alternate transform as a major finding.

### Analysis engine contract

`load_analysis_engine` must:

1. resolve and validate the configured smart-analysis repository;
2. require the v4 target-acquisition pipeline YAML;
3. instantiate `engine.Engine`;
4. register it under the exact queue name `overview`;
5. shut the engine down if registration fails.

`discover_targets` must submit a valid v4 payload for every overview, consume each
result exactly once, propagate `status["failed"]` details, detect missing/duplicate
results, and map returned centroids into the controller frame. It must not turn worker
failure into an empty target list.

The notebook must shut down an old engine before rerunning setup and must shut down the
engine during final cleanup. Controller disconnect must still happen if engine shutdown
raises.

### Widget behavior

The four widgets are existing workflow functionality, not decorative plots:

1. `FocusPicker`
   - LAS X focus points are optional, but operational read failures must not be hidden.
   - Point add/remove and toolbar pan/zoom must not conflict.
   - Measuring calls controller motion and autofocus only.
   - Editing points invalidates the measured surface.
   - Remeasuring unchanged points updates the existing heatmap in place.
   - Callback failures must be visible in the figure.

2. `OverviewViewer`
   - Tiles use their real frame centers, dimensions, and pixel size.
   - Separate canonical channel files form one channel stack.
   - Per-channel visibility, color, and display range must update all tiles.
   - Large runs auto-downsample for display without changing physical extents.
   - The original acquisition files must remain untouched.

3. `TargetExplorer`
   - Only complete, finite numeric features appear as axes.
   - Slider and lasso gates combine with AND semantics.
   - Changing axes clears the old-coordinate lasso and installs a working new selector.
   - Hover finds targets in screen pixels and shows the correct source crop.
   - `explorer.gated` at acquisition time reflects current controls.

4. `AcquisitionGallery`
   - A positive whole-number count is required; invalid text must never acquire one
     target by coercion.
   - Sampling occurs from the current gate.
   - Hardware/state/focus/options calls follow the same target-capture path as scripts.
   - Failed acquisition must not commit `picked` or `records` that a summary could report
     as successful.
   - Overview/target panels use the same physical field of view.
   - More rows increase figure height while width stays fixed, producing vertical-only
     notebook scrolling and readable image pairs.
   - Callback failures are visible on the figure.

## Files to inspect in ZMART-microscopy

Notebook and bootstrap:

```
workflows/target_acquisition/zmart_microscopy_v4.ipynb
workflows/target_acquisition/_bootstrap.py
workflows/target_acquisition/README.md
environment.yml
requirements.txt
```

Controller boundary:

```
zmart_controller/__init__.py
zmart_controller/layer.py
zmart_controller/registry.py
zmart_controller/tests/
```

Workflow and widgets:

```
workflows/target_acquisition/workflow/steps.py
workflows/target_acquisition/workflow/discovery.py
workflows/target_acquisition/workflow/_records.py
workflows/target_acquisition/workflow/_capture_run.py
workflows/target_acquisition/workflow/_focus_run.py
workflows/target_acquisition/workflow/_focus_surface.py
workflows/target_acquisition/workflow/_focus_widget.py
workflows/target_acquisition/workflow/_overview_widget.py
workflows/target_acquisition/workflow/_discovery_widget.py
workflows/target_acquisition/workflow/_acquisition_widget.py
workflows/target_acquisition/workflow/_geom.py
workflows/target_acquisition/workflow/viz.py
workflows/target_acquisition/tests/
```

Leica adapter and concrete driver boundary:

```
zmart_drivers/leica/stellaris5_y42h93/navigator_expert/zmart_adapter/
zmart_drivers/leica/stellaris5_y42h93/navigator_expert/connection/
zmart_drivers/leica/stellaris5_y42h93/navigator_expert/commands/gate.py
zmart_drivers/leica/stellaris5_y42h93/navigator_expert/motion/
zmart_drivers/leica/stellaris5_y42h93/navigator_expert/acquisition/
zmart_drivers/leica/stellaris5_y42h93/navigator_expert/scanfields.py
zmart_drivers/leica/stellaris5_y42h93/navigator_expert/tests/unit/test_zmart_adapter.py
zmart_drivers/leica/stellaris5_y42h93/navigator_expert/tests/hardware/validate_zmart_adapter.py
```

CI:

```
.github/workflows/target-acquisition.yml
```

## Required review questions

### A. Notebook execution and lifecycle

1. Does the setup cell work both when the kernel starts at repository root and when it
   starts in the notebook directory?
2. Is `%matplotlib widget` activated before any `pyplot` import? Does the declared
   environment actually install every runtime dependency?
3. Does setup fail before hardware movement if smart-analysis is absent, on the wrong
   branch, or cannot register its pipeline?
4. On setup-cell rerun, failed connection, analysis failure, interrupted acquisition,
   summary failure, and final-cell rerun, which resources remain live?
5. Can the notebook write a successful-looking summary without a successful target
   acquisition?
6. Are operator instructions consistent with what cells actually do?

### B. Hardware safety and frame integrity

1. Trace one target from Cellpose centroid to `Session.set_xyz` and prove units, axis
   order, orientation, signs, origin, objective translation, and z choice are correct.
2. Confirm every move reaches both the adapter whole-move preflight and the lower command
   gate. Look for any workflow or widget bypass.
3. Determine what happens when limits, orientation, or calibration are missing, corrupt,
   fallback, or stale. Is the notebook's preflight strong enough for a hardware proof?
4. Verify overview and target state are selected at the correct time and that autofocus
   restores state safely.
5. Check scan-field stripping order. Can positions/focus points be destroyed before the
   notebook reads them, or can a stored scan pattern execute unexpectedly?
6. Check partial multi-position failures. Can saved images and in-memory records disagree
   in a way that causes wrong reporting or repeated acquisition?

### C. Driver/controller contract

1. Compare every controller method signature to the adapter ops table and every workflow
   call site.
2. Verify returned state/procedure/acquisition dictionaries have the exact shapes consumed
   by the notebook and widgets.
3. Check module-active session behavior versus the explicit `Session` held by the notebook,
   including reconnect and disconnect after exceptions.
4. Verify the plane manifest is complete, deterministic, JSON-safe, and backward
   compatible. Check multi-channel, multi-z, and multi-timepoint cases.
5. Confirm controller tests select the mock explicitly and cannot accidentally connect to
   Leica because collection imported the adapter.

### D. smart-analysis v4 contract

1. Compare registration, queue names, payload keys, tuple conventions, and result keys
   directly to `smart-analysis@v4-engine`; do not infer from ZMART's fake engine.
2. Verify `tile_id` has the required `(region, row, col)` shape.
3. Verify pixel size is not applied twice and `(H, W)` is not passed where `(W, H)` is
   required.
4. Verify all worker failures become actionable notebook exceptions, including the case
   where some tiles succeeded first.
5. Inspect the Cellpose worker environment named in `segment_tile.METADATA`. Will that
   environment exist on the stated microscope setup, and does it contain compatible
   Cellpose/Torch/tifffile dependencies? Flag any undocumented deployment prerequisite.
6. Confirm only classical features are surfaced and that missing/NaN values cannot break
   widget construction.

### E. Widgets and professional operator behavior

For each widget, inspect both programmatic methods and real callback wiring. Agg tests that
call private handlers are not proof that ipympl mouse events still work after axes are
cleared or rebuilt.

Check layout at typical notebook widths and at 1, 5, 10, and 25 acquired targets. Look for
horizontal overflow, tiny rows, overlapping axes, unreadable labels, and controls that are
off-canvas. Scrolling should be vertical only.

Check long-running callbacks. Does the operator see that focus/acquisition is in progress?
Can a double click queue duplicate hardware work? Is stale success state retained after a
failed retry? Are callback errors visible and sufficiently specific?

Check memory behavior with many 2048x2048 multi-channel overview tiles. Confirm display
downsampling prevents avoidable retained arrays without changing stage extents or analysis
inputs.

### F. Tests and CI

1. Identify every important assertion that uses a permissive stub instead of the real
   Leica adapter or the real smart-analysis v4 contract.
2. Check whether collection order can change registry contents or backend state.
3. Verify notebook code cells parse and the setup cell is actually executed in tests.
4. Verify CI runs controller, workflow, and Leica-adapter boundary tests together on both
   Linux and Windows.
5. Note all hardware-only assumptions that no offline test can prove and map each one to an
   existing hardware validator step or a missing manual check.

## Commands to run

From the ZMART-microscopy repository root:

```bash
git status --short --branch
git diff --check origin/main...HEAD
git diff --stat origin/main...HEAD
python -m json.tool workflows/target_acquisition/zmart_microscopy_v4.ipynb > /dev/null
python -m pytest -q \
  zmart_controller/tests \
  workflows/target_acquisition/tests \
  zmart_drivers/leica/stellaris5_y42h93/navigator_expert/tests/unit/test_zmart_adapter.py \
  --tb=short
```

Also run the relevant linter on changed Python files. If smart-analysis can be checked out,
perform a registration-only smoke test against its actual `v4-engine` `Engine` and pipeline.
Do not claim a real hardware pass unless one was actually performed on Windows with LAS X.

## Deliverable

Lead with findings, ordered by severity: blocker, major, minor, nit. For every finding give:

- exact `file:line`;
- concrete initial state/input and action;
- observed or logically inevitable wrong outcome;
- why existing tests do not catch it;
- smallest appropriate fix.

Explicitly state whether you found any path that can:

- move to an incorrectly transformed target;
- perform an unbounded or fallback-bounded move without stopping the notebook;
- acquire the wrong LAS X job;
- confuse channels with z/time planes;
- hide Cellpose/engine failure as zero targets;
- retain a stale focus surface or stale successful gallery state;
- create duplicate acquisition from widget interaction;
- report targets as acquired when hardware acquisition failed;
- leave the engine or controller session live after cleanup.

After findings, include a short section for verified-correct areas and a short residual-risk
list containing only claims that require real hardware. Avoid style-only commentary unless
it directly affects an operator's ability to run the notebook correctly.
