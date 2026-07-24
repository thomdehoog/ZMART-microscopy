# ZMART Viewer Handoff — 2026-07-24

## Resume point

- Repository: `thomdehoog/ZMART-microscopy`
- Working branch: `codex/zmart-viewer-annotations`
- Implementation checkpoint: `891f79b`
- Parent viewer branch: `codex/zmart-viewer-histogram-auto`
- Local checkout:
  `C:\ProgramData\MinicondaZMB\envs\ZMART-viewer\src\ZMART-microscopy`
- Conda environment: `ZMART-viewer`
- Playwright browser location:
  `C:\ProgramData\MinicondaZMB\envs\ZMART-viewer\ms-playwright`

The implementation checkpoint is pushed to
`origin/codex/zmart-viewer-annotations`. No pull request has been opened.

## What works

The viewer currently provides:

- OME-Zarr streaming and rendering through Neuroglancer.
- A 2-D working view and 3-D volume view.
- Multi-channel layer visibility and recolouring.
- Per-layer contrast, histogram-based automatic contrast, and opacity.
- A synchronized Z control.
- Synthetic OME-Zarr demo data.
- Native desktop display through pywebview.
- A Neuroglancer-native writable annotation layer named `Targets`.
- React buttons that install Neuroglancer's own point and bounding-box tools.
- A target list with selection and deletion.
- Annotation-layer visibility and colour controls.
- A `Go to` action for boxes that sends named physical coordinates and units to
  `POST /api/goto`.
- Annotation persistence through `GET/POST /api/annotations`.
- Atomic JSON sidecar storage at
  `<OME-Zarr parent>/zmart-annotations.json`.
- Backend validation for annotation type, ID, coordinate rank, finite values,
  descriptions, duplicates, and document size.

## Architecture boundary

Keep the current separation:

- Neuroglancer owns image rendering, navigation, coordinate transforms,
  annotation geometry, selection, and drawing tools.
- React owns the operator-facing controls and reflects Neuroglancer state.
- Python owns persistence and microscope-facing endpoints.

Do not draw a second annotation canvas, infer coordinates from DOM pixels, or
implement separate point/box geometry in React. The current controls use
`LocalAnnotationSource`, `PlacePointTool`, `PlaceBoundingBoxTool`, and
`selectAnnotation` from the installed Neuroglancer API.

## Validation completed

The following checks passed before the checkpoint was pushed:

- Frontend production build with Vite.
- 120 backend, data-generation, store-discovery, contrast, and build-artifact
  tests.
- 27 focused annotation, server, and layer-integration tests.
- 9 navigation tests, including wheel/Z-slider synchronization and 2-D/3-D
  position preservation.
- The five new annotation browser tests individually.

The combined full-suite command was not recorded as passing. It exceeded the
command timeout because existing browser tests wait on assumptions that became
stale when the `Targets` layer was added. One confirmed example expected the
Neuroglancer layer count to be exactly two for a two-channel image; it is now
correctly three including `Targets`. That expectation was updated to count
image layers separately, and its focused test passes.

Treat the full-suite status as incomplete, not failed and not passed.

## What to do next

1. Audit remaining browser tests for assumptions that every managed
   Neuroglancer layer is an image layer. Filter by layer name/type rather than
   using the total `managedLayers.length`.
2. Run each remaining browser test file independently to expose failures
   quickly:

   ```powershell
   $env:PLAYWRIGHT_BROWSERS_PATH='C:\ProgramData\MinicondaZMB\envs\ZMART-viewer\ms-playwright'
   conda run -n ZMART-viewer python -m pytest tests/test_layer_panel.py -q
   conda run -n ZMART-viewer python -m pytest tests/test_volume_rendering.py -q
   conda run -n ZMART-viewer python -m pytest tests/test_render_acceptance.py -q
   ```

3. Fix only stale test assumptions or genuine regressions; do not remove the
   native annotation layer to satisfy an old count.
4. Run the full suite after the browser files pass independently. The two
   real-store checks may remain skipped when `ZMART_TEST_STORE` is unset.
5. Launch the viewer in pywebview and manually verify:
   - point drawing;
   - two-click box drawing;
   - select/delete;
   - recolour/hide;
   - persistence after closing and reopening;
   - `Go to` box payload.
6. Inspect the saved sidecar beside the selected OME-Zarr data and confirm that
   reopening the same acquisition restores only its own targets.
7. After that validation, decide whether to:
   - polish annotation labels and selected-row state;
   - connect `/api/goto` to the microscope safety/control layer; or
   - open a draft pull request for the complete viewer sequence.

## Known limitations

- `/api/goto` is still a demo acknowledgement; it does not move hardware.
- Annotation descriptions are preserved by the data contract but are not yet
  editable in the React panel.
- Persistence errors are returned by the server, but the UI does not yet show
  save/error status.
- The Z control observes Neuroglancer's live navigation object each animation
  frame because coordinate-space reconciliation can replace the underlying
  `Position` object. This uses the public navigation state and avoids stale
  subscriptions, but deserves review if Neuroglancer exposes a stable
  replacement signal in a future version.
- The full combined suite still needs the audit described above.

## Useful commands

Build:

```powershell
cd C:\ProgramData\MinicondaZMB\envs\ZMART-viewer\src\ZMART-microscopy\viz_studio
conda run -n ZMART-viewer npm.cmd --prefix frontend run build
```

Focused annotation validation:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH='C:\ProgramData\MinicondaZMB\envs\ZMART-viewer\ms-playwright'
conda run -n ZMART-viewer python -m pytest tests/test_annotations.py tests/test_server.py -q
```

Inspect the checkpoint:

```powershell
git switch codex/zmart-viewer-annotations
git show --stat 891f79b
```
