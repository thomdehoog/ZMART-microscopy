# Relative-Z operator: investigation and suggested fixes

Date: 9 September 2026

Status: root-cause mechanisms reproduced; no application fixes implemented

Scope: missing overview tiles, transient focus display, and a missing target acquisition layer

## 1. Purpose and outcome

The operator was tested on `codex/operator-relative-z-integration` with its required viewer dependency. The user reported three problems:

1. Only the first two overview tiles appeared, although more positions had been acquired.
2. During focus-map acquisition, scrolling through Z appeared to change the black or transparent area of the displayed image. The current focus capture was not yet visible. Once acquisition finished, the stacks looked correct and scrolling worked correctly.
3. **Major bug:** after targets were acquired, no target acquisition appeared in the main canvas's acquisition selector. See section 11.

Follow-up work reproduced all three failure mechanisms. The writer alternates between rounded job-reported XY sampling and higher-precision native OME sampling. The viewer rejects that disagreement. A failed publication batch also leaves the bridge's acquisition list stale, hiding valid target imagery. Separately, the renderer displays image and coverage sources before both are ready, producing temporary transparent holes, incorrect color blending, or black blocks. A gated test of the actual focus loop confirmed when captured stacks and inspector results become available. Section 12 records the experiments, assertions, and evidence artifacts.

The user clarified the intended rendering behavior: an acquired position should have an opaque XY footprint, including black or zero-intensity pixels. There should be no transparent holes inside a position simply because the image has no signal there.

This report distinguishes reproduced mechanisms from unrecorded historical timing. It is a handover for implementation, not a claim that the application has been fixed. The exact per-capture timeout logs and network timing of the user's original transient display were not recorded; controlled reproductions establish that the identified code paths produce these failures.

## 2. Test setup and preserved versions

### 2.1 Repositories and versions

| Component | Version or location |
| --- | --- |
| Operator repository | `https://github.com/thomdehoog/ZMART-microscopy` |
| Tested operator branch | `codex/operator-relative-z-integration` |
| Operator commit inspected | `10e6d212d2bf4e2878728047812c961a7ca313b0` |
| Separate local clone | `C:\ProgramData\MinicondaZMB\home\t.de\zmart-operator-relative-z` |
| Viewer repository | `https://github.com/thomdehoog/ZMART-viewer` |
| Required viewer branch | `codex/mixed-acquisition-depth` |
| Pinned viewer commit | `8604cb812949feb9bdcb5c8bf2739b559543fd44` |
| Installed viewer distribution | `zmart-viewer` 0.2.1 at that pinned commit |
| New development server | `http://127.0.0.1:5175/` |
| New Python environment | `C:\ProgramData\MinicondaZMB\envs\zmart-operator-relative-z` |

The new environment is a Python virtual environment created with `--system-site-packages` from the existing `zmart-microscopy` Conda environment. It has its own pinned viewer installation, while inheriting other packages from the base environment. It is therefore isolated for this viewer installation, but is not a fully independent Conda clone: subsequent changes to inherited packages can affect it.

Checks confirmed that the new environment imports viewer 0.2.1 from its own `Lib/site-packages`, that the installation records commit `8604cb8`, and that the operator's viewer capability check passes. This verifies the dependency boundary, not every possible runtime behavior.

The existing review checkout remains at:

```text
C:\ProgramData\MinicondaZMB\home\t.de\zmart-operator-review
branch: claude/smart-operator-workflow-review-ehw3c5
commit at handover: a0fafdc0
development port: 5174
Python environment: C:\ProgramData\MinicondaZMB\envs\zmart-microscopy
```

Its intentional changes to `application/framework/window/static/index.html` and untracked `application/setup-pictures/` were preserved. The older `zmart-operator` checkout is not the review version used for this work.

### 2.2 Documentation caveats

- The root README and dependency files on the integration branch pin viewer `8604cb8`.
- `docs/relative-z-integration.md` still names the earlier viewer commit `e759fec3`. Its architecture description is useful, but that version reference is stale.
- The earlier `application/NEXT_SESSION.md` handover predates several evening commits. Its suggestion to resume the old thin-tile problem is stale.
- The initial investigation note is in the integration clone at `docs/operator-observations-2026-09-09.md`. This report expands it and records the user's later clarification about opacity.

### 2.3 Runtime constraints and restarts

The local ProgramData checkout is used because the supplied machine history reports AppLocker and SMB restrictions on running the JavaScript tools from the network checkout. Node and npm are in the `zmart-microscopy` environment rather than the normal PATH.

Vite, esbuild, and Playwright are local application dependencies. `npm run dev` builds the Neuroglancer workers through `predev`; `npm run build` produces the built page. The native window without `--built` reads the development server. The built window and the workflow walk require a fresh build to see JavaScript changes.

The Python bridge lives inside the native window process. Restarting that window restarts its backend. A JavaScript reload alone does not restart Python.

During this session, the Codex tool rejected attempts to launch the window before the command ran, with `blocked by policy`. A separate session successfully launched the same checkout. The rejected commands already used detached `Start-Process -PassThru` with a visible window, so detachment was not an established explanation for the policy difference. Launching through another shell is not a demonstrated policy fix.

The agreed operational arrangement was to coordinate restarts with the user. Do not close a working window on the assumption that this session can reopen it. Process IDs and random bridge ports recorded during investigation are historical and must be rediscovered before use.

The virtual environment's launcher can have a child process whose executable is the base Python. This does not by itself show that the wrong packages are imported. `zmart-interface.py` did not contain the claimed explicit re-execution into another environment; verify package provenance rather than inferring it from the executable path alone.

## 3. Evidence collected

### 3.1 User screenshots

- [Only the first two tiles appear](<operator-evidence-2026-09-09/overview-only-two-tiles.png>)
- [Focus-map heights and stack preview](<operator-evidence-2026-09-09/focus-map-and-stack.png>)
- [Targets acquired but no target acquisition in the selector](<operator-evidence-2026-09-09/missing-target-acquisition.png>)

The first screenshot shows image data in the upper two positions of a four-position arrangement, with empty blue outlines below. The second shows different measured focus heights. Different physical focus heights are valid and do not, by themselves, explain missing flat images.

### 3.2 Run inspected

```text
E:\Experiments\ZMART-microscopy\target-acquisition_a56857
```

The investigation read original OME-Zarr metadata, publication records, and the running bridge's status. It did not change acquisition data or initiate microscope acquisitions.

Useful evidence locations:

```text
positions/overview/*.ome.zarr/zarr.json
positions/overview/.zmart-viewer/overview.ome.zarr/publication.json
positions/targets/*.ome.zarr/zarr.json
positions/targets/.zmart-viewer/overview.ome.zarr/publication.json
```

`GET /api/viewer` exposed a viewer publication error. `GET /api/scan` reported ten of ten targets acquired, with no acquisition error. Acquisition success and successful display publication are therefore separate states in this incident.

## 4. Problem 1: only the first two overview tiles appear

### 4.1 Original suspicion and earlier workaround

The user recognized the symptom from a previous branch and suspected that different relative heights again caused tiles to disappear.

Commit `fbe0de7a` explicitly describes an earlier eight-tile run in which only two tiles appeared. In that case, each flat position stood at its measured focus height, and interactions between source bounds, a thick display slab, and the shared Z coordinate system excluded some images.

The earlier fix places every single-plane capture at shared display Z = 0 and retains its actual acquisition height as provenance. It also centers the flat display slab on that shared depth. The fix is already in the integration branch.

### 4.2 What the current data shows

All eight overview original stores exist. Every one has Z translation 0 and Z scale 1. Their actual acquisition heights remain in provenance, approximately 85.85 down to 65.47 micrometres.

The publication boundary instead coincides with a change in XY sampling:

| Acquisition | Position indices in filenames | Recorded X and Y pixel size, �m/pixel | Publication evidence |
| --- | --- | --- | --- |
| Overview | 0-1 | 2.27 | Both included in published revision 2 |
| Overview | 2-6 | 2.27495107632 | Not included in that publication |
| Overview | 7 | 2.27 | Also not included after the earlier failure |
| Targets | 0-2 | 0.11375 | Included in target publication revision 3 |
| Targets | 3-5, 7-9 | 0.113747260274 | Not included in that publication |
| Targets | 6 | 0.11375 | Also absent after the earlier failure |

The fact that a later tile returns to the earlier pixel size does not necessarily recover publication: the requested snapshot still includes the incompatible earlier tile.

The live error named target positions 0 and 3 and their voxel sizes:

```text
(1.0, 0.11375, 0.11375)
(1.0, 0.113747260274, 0.113747260274)
```

The viewer classified these as incompatible magnifications. The first value in each tuple is Z spacing, which agrees; the disagreement is in X and Y.

The overview difference is approximately 0.218%, or approximately 2.535 �m over a 512-pixel field. The target difference is approximately 0.00241%, or 0.001403 �m over a 512-pixel field. These are calculated comparisons of recorded metadata, not measurements proving a physical magnification change. In particular, the overview discrepancy should not be dismissed as ordinary floating-point noise.

### 4.3 Relevant code

| Source | Behavior |
| --- | --- |
| `application/parts/storage/zarr_positions.py`, `_the_z_model`, around line 333 | Sets flat captures to shared Z and retains acquisition provenance |
| Same file, `_the_volume_of`, around line 241 | Reads XY sampling from the first plane's OME metadata |
| Same file, `_the_pixel_size_of` | Parses physical sizes and their units |
| Viewer `zmart_viewer/compose.py`, `_refuse_tiles_that_disagree`, around line 440 | Compares voxel-size tuples exactly and raises on disagreement |
| `application/parts/storage/viewer_service.py`, `_publish_once`, around line 254 | Preserves the last published picture and requeues a failed publication |

Viewer source references mean the pinned external viewer, installed under the new environment's `Lib/site-packages/zmart_viewer`. Fixes should be made in the viewer's source repository and pinned into the operator, not patched directly into installed packages.

### 4.4 Diagnosis and confidence

**Strongly supported:** inconsistent XY sampling prevents later positions from joining the displayed acquisition. The live target error confirms the rejection mechanism. The overview's sampling change at position 2 and its two-position publication support the same explanation for the screenshot.

**Reproduced on actual saved-store metadata:** passing all eight overview positions through the installed viewer's `_refuse_tiles_that_disagree` raises on positions 0 and 2, with exactly the recorded XY sampling values. Normalizing their sampling in memory makes that validation pass; original files were not changed. The historical error log was not recovered, but its failure mechanism is now directly reproduced.

**Traced to competing metadata sources:** saved job settings retain the same zoom, format, and formatted pixel size while output TIFF sampling changes. The saved native OME contains the higher-precision value. Exercising `metadata_with_job_physical_sizes` with a successful saved-settings response versus an unavailable response produces exactly the two values recorded in each acquisition. This does not establish the timing of each original timeout, but establishes the source inconsistency and reproduces its downstream failure.

### 4.5 Additional code lead: metadata-source fallback

In `zmart_drivers/leica/stellaris_y42h93/navigator_expert/acquisition/ome_canonical.py`, the physical-size correction around lines 125-163 prefers live job settings. If the bounded read does not return a dictionary, it logs a warning and retains vendor OME physical sizes. If individual geometry fields cannot be parsed, those fields also remain unchanged.

`_xy_pixel_sizes_from_job_settings`, around line 470, reads geometry through `readers/parsing.py::parse_tile_geometry`, which parses the job's reported pixel dimensions.

The follow-up checks confirmed the two sources numerically:

| Acquisition | Native OME / unavailable-settings path | Successful live-settings path |
| --- | --- | --- |
| Overview | 2.27495107632 �m/pixel | 2.27 �m/pixel, parsed from the formatted job string |
| Targets | 0.113747260274 �m/pixel | 0.11375 �m/pixel, parsed from `113.75 nm` |

All eight saved overview job settings agree on zoom 1, format 512 x 512, and the `2.27` pixel-size string. The original and later target captures also retain the same reported recipe geometry while written sampling alternates. A later target rerun changed some per-position values; the evidence report preserves capture history separately from the current position stores.

The physical-size override reads settings separately with a bounded timeout. If unavailable, it retains native metadata. The diagnostics substituted those two return conditions; they did not contact the Leica API. The original timeout logs are still unavailable.

### 4.6 Suggested fixes

#### A. Establish consistent, justified sampling at acquisition time

**Preferred direction after reproduction:** stop replacing valid native XY sampling with the rounded `pixelSize` presentation string on only some captures. Keep XY geometry from a consistent validated numeric source. Evaluate retaining native XY while preserving the separate job-based correction for native AutoSave Z spacing, which has a known different issue. Do not disable that Z correction indiscriminately. If a reliable unrounded job geometry API is available, validate it and use it consistently instead of parsing display text.

1. Compare overview positions 0, 1, and 2, then target positions 2 and 3. Identify the source and precision of each pixel-size value.
2. Record which source supplied canonical X/Y/Z sampling, its raw values, units, and why fallback occurred. Preserve this provenance with the capture.
3. For an unchanged acquisition recipe, use a validated geometry snapshot consistently. Its identity must include settings that affect sampling, such as objective, zoom, frame dimensions, binning, and relevant scan geometry.
4. Invalidate that snapshot when geometry changes. Do not reuse it merely because the job name is unchanged.
5. Keep metadata reads bounded. A consistent snapshot should not reintroduce indefinite waits on the microscope interface.

If fallback cannot be reconciled with the validated geometry, report the discrepancy explicitly. Do not silently invent sampling or take the first tile's value as truth for all subsequent tiles.

#### B. Choose an explicit viewer policy for genuine differences

For discrepancies proven to be representational rounding, a bounded compatibility rule may be appropriate. It should derive its limit from allowed spatial error, canonicalize accepted values consistently across pyramid levels and coverage, and retain the original metadata as provenance.

For genuinely different sampling, choose either separate acquisition groups or explicit resampling onto a common grid. Resampling changes geometry and potentially intensities; its interpolation and coverage behavior need a defined contract.

Do not replace the exact comparison with an arbitrary broad tolerance. The current common-grid compositor needs coherent geometry even when two inputs are accepted as compatible.

#### C. Make incomplete display publication visible

Present acquisition and publication progress separately, for example: "8 positions acquired; 2 displayed. Pixel-size mismatch prevents updating the picture." Keep useful imagery visible, but make the stale picture explicit.

Classify deterministic geometry failures separately from transient server or file-read failures. Repeating an identical invalid snapshot cannot fix its geometry. Retry when its inputs change or the operator requests a retry; avoid an endless undifferentiated retry loop.

Consider isolating errors by acquisition so a target publication failure does not unnecessarily prevent status updates for other valid acquisitions. This is a proposed improvement; the precise interaction should be tested before changing publication scheduling.

#### D. Recover existing runs through a separate derived output

Validate the correct sampling first. Then regenerate corrected derived stores and publication in a separate recovery location, preserving original TIFFs, metadata, and the current stores as evidence. Do not rewrite the microscope's recorded physical heights to address an XY problem.

### 4.7 Acceptance criteria

- All eight overview positions appear at the correct physical placement.
- All ten targets can be published, or a genuine geometry difference is explicitly represented and explained.
- Flat images remain visible across stack navigation regardless of their measured physical focus heights.
- Metadata source changes cannot silently produce an unexplained partial picture.
- Valid small representation differences and genuine magnification changes are tested separately.

## 5. Problem 2: unstable display during focus acquisition

### 5.1 User observation and important clarification

During creation of the focus map, scrolling through Z appears to change how much of the image footprint is black or transparent over the overview. The user also cannot yet see the data from the current focus capture.

The user repeatedly clarified that **once acquisition is done, the stacks look correct and scrolling through them works correctly**. This is not a report of permanently broken completed-stack geometry.

The changing footprint was described in relation to the overview, suggesting the large canvas. A question distinguishing that canvas from the small "Focus stack (XY)" preview was not answered explicitly. The two surfaces must be distinguished in reproduction because their update paths differ.

### 5.2 Confirmed behavior: no per-plane focus preview in this path

`application/parts/microscope/focus_run.py` calls `session.acquire` and waits for the capture record. Only after it returns does the loop call `keep(record)`. The focus loop has phase notifications, but no per-plane image callback.

The relevant sequence is:

```text
Drive to focus point
  -> acquire complete stack
  -> retain files and create the position store
  -> queue background viewer publication
  -> score the stack
  -> return the point measurement and generate small slice previews
  -> update the focus-map UI
```

The main viewer's publication can proceed while scoring occurs; it does not require the entire multi-point focus map to finish. The small previews depend on the completed point result.

In `application/framework/bridge.py`, `_focus_worker` passes `_keep_position_as_zarr` as the capture-retention callback. Its `landed` callback creates preview slices and adds the completed point to focus status.

This explains why the current stack does not appear plane by plane during its acquisition. It does not prove that every observed blank or changing area is caused by that limitation.

### 5.3 Confirmed UI behavior: selection follows the unfinished point

In `application/workflows/target_acquisition/steps/focus_strategy/focus-map.js`, the `onPoint` callback around line 1900 selects the next point when one exists. For the final point, it selects the point just completed.

`drawZSlice`, around line 1265, hides the small preview when the selected point has no slices. Consequently, the preview can follow the next unfinished point even though the previous point's stack is available. At the end of the run, selection remains on a completed point.

This explains the preview delay and final availability. The separate main-canvas readiness defect is established in the following subsection.

### 5.4 Rendering behavior relevant to the transient footprint

In `viz_studio/options/neuroglancer-under/viewer.js`, `installRows` creates an opaque-black coverage layer beneath acquisition signal layers. Coverage determines whether lower imagery is obscured even when the acquired intensity is zero.

The aggregate signal and coverage are separate image sources. `addSourcesToTheOpenRows` notices increasing publication revisions and calls `source-refresh.js::refreshSources`, which invalidates matching cached sources.

This provides a plausible transient mechanism: coverage and signal can be requested and become ready at different times. A new coverage mask with incomplete image pixels could show a black region; missing or stale coverage could expose lower imagery. Scrolling while new stacks arrive exercises both Z navigation and source refresh.

**Follow-up: reproduced under controlled loading delays.** With the real viewer server and the operator's real Neuroglancer adapter, withholding coverage responses allowed the red overview to show through a zero-intensity patch in a newly acquired focus position. Signal from the same position incorrectly added to the overview until coverage arrived. Withholding signal responses while scrolling to an uncached Z plane produced a black rectangle instead of the green focus image. Releasing each gate restored the correct display. The assertions passed with baking both off and on, with no browser errors. See section 12.

This confirms a renderer readiness/synchronization defect with exactly the relevant symptoms. It does not reconstruct the timing of the user's original run. Different acquired Z extents remain a valid separate reason for coverage to change outside a stack, but the recorded focus stacks all have the same shape and spacing, and the reproduction uses identical geometry and intensity patterns across Z.

Existing `aggregate-depth.spec.js` checks rendered colors, transparency, acquired black, and Z behavior after waiting for expected pixels. That is useful steady-state coverage, but does not establish that intermediate frames remain consistent during repeated live updates and scrolling.

## 6. Agreed opacity contract

The implementation should express the user's rule in terms of acquisition geometry, not image brightness:

| Location/state | Expected behavior |
| --- | --- |
| Inside an acquired position's XY rectangle at an acquired Z plane | Opaque, including zero-valued pixels and black background |
| A zero-filled chunk omitted by Zarr within that completed acquired rectangle | Still acquired; opaque black |
| Outside acquired position bounds or in a gap between positions | Transparent so underlying imagery can show through |
| Position or plane not yet acquired | No claim that it contains measured data; a plan marker may be shown separately |
| Data still loading for an already committed displayed position | Preserve a coherent prior display or show an explicit loading state; do not reinterpret loading as a hole in acquired coverage |

The core user requirement is **no brightness-derived transparency or sparse holes inside an acquired position**. Missing signal is not the same as missing acquisition coverage.

This does not mean flattening stacks, changing physical Z metadata, or making a stack obscure the scene at every possible Z. The working interpretation keeps transparency outside its acquired extent. A requirement to project a stack's XY footprint across all Z would be a different display policy and has not been requested.

A flat acquisition should retain its existing persistence through stack navigation. A stack remains a stack with its actual relative-Z domain. Whether a channel or acquisition is deliberately hidden remains a separate user control.

The existing complete-region publication payload and coverage layers already aim to implement much of this contract. Before adding another mask, determine whether the failure is in coverage generation, publication consistency, source loading, or UI selection.

## 7. Suggested fixes for the focusing experience

### 7.1 Separate the acquisition cursor from the inspection selection

Track "point currently being acquired" separately from "point being inspected." The progress indicator and stage marker can follow acquisition without forcing the inspector onto an unfinished point.

As a default, keep the latest completed stack available. If the user has explicitly selected an earlier point or is scrolling it, preserve that choice while further points arrive. An optional follow-latest-completed behavior can be added with an explicit state rather than silently changing selection.

Do not wait for the whole map to finish to expose completed stacks. The backend already reports completed points incrementally.

### 7.2 Make image and coverage publication coherent

The mismatch is now reproduced; select the implementation against the controlled-delay tests in section 12.

Bind signal and coverage to the same publication revision and manage their visible transition together. Revision identity alone is insufficient: the reproduction also fails while two sources from the same committed update have different readiness. Possible designs include immutable revision-specific resources with a controlled swap, or staging the current viewport's required signal and coverage before replacing the displayed revision.

Define behavior for newly visited Z planes while chunks load. Do not require loading an entire large stack before interaction. Retaining the last coherent viewport while indicating loading is preferable to presenting missing chunks as measured transparency; the final choice must also avoid showing old content as if it were the newly selected Z plane.

Check server publication consistency as well as browser timing. If image data and coverage can be read from different revisions under stable URLs, browser ordering alone will not solve the problem.

### 7.3 Preserve complete position coverage

Keep the operator's complete-position coverage independent of intensity, chunk allocation, and coarse-pyramid nonzero values. Generate it from acquired geometry and apply the same spatial placement to coverage and signal at each pyramid level.

If the external viewer supports explicit sparse regions for other producers, retain that capability where requested. The operator's complete-position mode should not inadvertently inherit a signal-derived sparse mask.

### 7.4 Treat true live per-plane preview as additional work

Keeping a completed stack visible is a smaller change than displaying a stack while it is being acquired.

True per-plane preview requires an explicit plane-ready interface, reliable completion detection for saved images, correctly stamped geometry, and safe treatment of partially written files. The current focus loop does not supply that interface.

If added, keep the live preview separate from committed complete-position publication, or extend the publication contract deliberately to describe partial acquisition coverage. Do not label an unacquired plane as acquired merely to obtain an opaque rectangle.

### 7.5 Acceptance criteria

- Completed focus stacks are inspectable while later points are acquiring.
- A user's inspection selection and Z position are not unexpectedly replaced by acquisition progress.
- Acquired zero-intensity regions remain opaque and do not reveal the overview as holes.
- Repeated Z scrolling during source updates does not mix incompatible signal and coverage states.
- Final completed-stack behavior remains correct.
- If live per-plane preview is not implemented, the interface clearly distinguishes "acquiring this stack" from available completed stacks.

## 8. Validation plan

### 8.1 Reproduce with saved data first

Use a separate diagnostic copy or derived output from the recorded run. Read metadata and compare the conflicting captures without changing the originals. Replay completed position arrivals into an isolated viewer instance, independently of the real microscope bridge.

For the focusing artifact, use deterministic synthetic or saved stacks with known geometry, including genuine zero-valued regions. Replay arrivals with controlled delays while scrolling Z. Capture intermediate frames, not just the final settled image.

Record selected inspection point, acquisition cursor, selected Z, publication revision, source revision/readiness, visible acquisition order, and coverage readiness. This will distinguish UI selection effects, legitimate Z extent changes, and rendering races.

### 8.2 Targeted tests

| Test area | Required cases |
| --- | --- |
| Metadata consistency | Live settings available/unavailable; field parse failures; recorded mismatch values; genuine recipe changes |
| Writer geometry | Correct XY units and transforms; flat Z = 0; preserved physical-height provenance; ascending stacks |
| Publication failures | Clear acquired/displayed counts; deterministic versus transient errors; valid recovery after corrected inputs |
| Coverage | Acquired all-black images; omitted zero chunks; gaps outside positions; mixed flats/stacks; fine and coarse levels |
| Focus inspection | Continue acquiring while selecting and scrolling an earlier completed point; no forced switch to missing slices |
| Live refresh | Delay coverage before signal and signal before coverage; repeated revisions during Z scrolling; both baking modes |
| Final regression | Completed stacks, channel visibility, overlap order, relative-Z limits, and idle request behavior remain correct |

Relevant existing tests include:

```text
application/parts/storage/test_zarr_positions.py
application/parts/storage/test_viewer_service.py
application/framework/test_operator_bridge.py
application/parts/canvas/flat-tiles.spec.js
application/parts/canvas/aggregate-depth.spec.js
application/parts/canvas/acquired-coverage.spec.js
application/parts/canvas/source-refresh.spec.js
application/parts/canvas/depth-range.spec.js
application/workflows/target_acquisition/walk.spec.js
```

The exact driver metadata tests should be selected alongside the eventual acquisition-layer change. Extend tests around real boundaries rather than writing assertions that merely repeat the implementation.

### 8.3 Suggested local verification commands

These commands are a plan; they were not executed as part of writing this report. Use a free test port and the isolated Python environment so the tests do not accidentally exercise the original review version on 5174.

```powershell
$operatorRoot = 'C:\ProgramData\MinicondaZMB\home\t.de\zmart-operator-relative-z'
$operatorPython = 'C:\ProgramData\MinicondaZMB\envs\zmart-operator-relative-z\Scripts\python.exe'
$toolEnv = 'C:\ProgramData\MinicondaZMB\envs\zmart-microscopy'
$env:PATH = "C:\ProgramData\MinicondaZMB\envs\zmart-operator-relative-z\Scripts;$toolEnv;$env:PATH"
$env:PYTHON = $operatorPython
$env:PLAYWRIGHT_CHROMIUM = 'C:\ProgramData\MinicondaZMB\home\t.de\ms-playwright\chromium-1234\chrome-win64\chrome.exe'
Set-Location $operatorRoot

& $operatorPython -c "from application.parts.storage.viewer_service import viewer_provenance; print(viewer_provenance())"
& $operatorPython -m pytest application/parts/storage/test_zarr_positions.py application/parts/storage/test_viewer_service.py application/framework/test_operator_bridge.py -q

Set-Location "$operatorRoot\application"
& "$toolEnv\npm.cmd" run test:unit
& "$toolEnv\npm.cmd" run build
$env:ZMART_TEST_PORT = '5176'
& "$toolEnv\npm.cmd" run test:ui -- parts/canvas/aggregate-depth.spec.js parts/canvas/acquired-coverage.spec.js parts/canvas/source-refresh.spec.js parts/canvas/flat-tiles.spec.js parts/canvas/depth-range.spec.js
```

The browser fixture helper `pythonForTheBridge()` defaults explicitly to the original `zmart-microscopy` interpreter, so `PYTHON` above is necessary; PATH alone is insufficient. The Chromium override supplies the observed `chrome-win64` path, which the config's older `chrome-win` search does not find. Run the built-page workflow walk after relevant focused checks pass. Coordinate any real microscope verification and window restart with the operator.

## 9. Recommended implementation order

1. Resolve the sampling-metadata provenance using the recorded mismatches. Reproduce the publication failure offline.
2. Implement justified canonical sampling or explicit grouping/resampling, with tests for genuinely different geometry.
3. Fix the missing target acquisition layer and publication error isolation described in section 11. Verify actual target imagery, not only an error message or a menu label.
4. Separate inspection selection from acquisition progress, retaining access to completed focus stacks.
5. Fix the now-reproduced independent signal/coverage readiness defect, using the controlled arrival and Z-scroll checks as regression cases.
6. Verify the opaque-position contract across Z navigation, new arrivals, omitted zero chunks, and both baking modes.
7. Consider live per-plane preview as a separate feature if it remains desired after the completed-stack inspector is usable during acquisition.

When a fix changes the viewer, make it in the external viewer repository, test it with the operator, and update the operator's viewer pin and documentation together. Preserve the original review environment and checkout.

## 10. Work completed and remaining uncertainty

Completed: separate operator checkout and viewer installation; dependency provenance checks; recorded metadata audit; actual-store rejection reproduction; real-server stale acquisition-list reproduction and recovery control; real-browser signal/coverage delay reproductions with baking off and on; real focus-loop callback-order verification using a fake capture; screenshots, scripts, JSON evidence, and proposed fixes saved.

Not completed: application fixes, corrected publication of the microscope run, or a full application regression suite. The purpose-built diagnostic assertions passed; those are not tests of a fix. Historical per-capture timeout logs and the original transient request timings were not available.

The mechanisms are now substantially diagnosed. Remaining implementation work is to keep sampling consistent, isolate publication failures and acquisition-list updates, coordinate rendered signal/coverage readiness, and decouple inspection selection from acquisition progress.

## 11. Major bug: target acquisition absent after targets are captured

### 11.1 Observation and recorded state

The additional screenshot shows the Acquire Targets step and an expanded acquisition selector containing only `overview` and `focussing`. Target names and a small comparison preview exist, but no target acquisition can be selected in the main canvas. The user classifies this as a major bug.

The earlier inspection recorded ten completed target captures and a target aggregate at revision 3 with three positions. The viewer's raw configuration included a `targets` group, while the bridge's cached acquisition list exposed only focusing and overview alongside a pixel-size mismatch error.

The screenshot's black squares alone do not prove which source owns them; a small target preview is also not proof that targets reached the main viewer.

### 11.2 Root cause and deterministic reproduction

`viewer_service.py::_publish_once` performs all pending opens and announcements before refreshing the cached source and acquisition lists. If any operation raises, it requeues work and returns with the old lists. `status()` serves those old lists. `live.js::viewerSources` returns a nonempty acquisition list directly without propagating its associated error in that return value.

The diagnostic uses the real viewer server and this actual publisher function:

1. Publish a valid overview and confirm the cached list contains overview.
2. Add a valid target acquisition plus an incompatible overview tile to the same pending update.
3. The target open succeeds, but the overview announcement fails.
4. The raw viewer configuration contains targets; the bridge's acquisition list still contains only overview.
5. Remove the invalid tile from the diagnostic's requested snapshot and retry; the bridge now exposes targets.

Assertions pass. No microscope data is edited. This reproduces how valid target imagery can exist while its entire acquisition layer remains absent in the operator.

The raw viewer configuration additionally exposed an automatically discovered `p1` group in the test. That matters for the fix: blindly forwarding every raw group after an error could expose an unwanted per-position acquisition. Refresh only valid committed acquisitions under the operator's aggregation contract.

### 11.3 Required fix

- Resolve the underlying sampling inconsistency so the complete run can publish.
- Track committed state and errors per acquisition; an invalid overview update must not hide a valid target acquisition.
- Preserve and surface valid committed target imagery when a later update fails, with explicit partial progress.
- Show acquisition lifecycle states such as preparing, partially available, ready, and blocked. Never imply that all captured positions are displayed when they are not.
- Preserve logical channel grouping; do not substitute one row per target or leak auto-discovered orphan groups.
- Make image availability and acquisition completion separate test assertions. A working thumbnail is insufficient.

Acceptance requires actual selectable target imagery, truthful partial/error states, and recovery after valid inputs are restored without restarting the entire application.

## 12. Follow-up experimental results and reproducible evidence

### 12.1 Diagnostic workspace

The report includes these compact evidence artifacts so its key results can be reviewed from the repository:

- [Metadata-path and publication reproduction results](operator-evidence-2026-09-09/publication-evidence.json)
- [Focus-loop delivery results](operator-evidence-2026-09-09/focus-delivery-evidence.json)
- [Browser assertions with baking enabled](operator-evidence-2026-09-09/focus-loading-evidence-baked.json)
- [Browser assertions with baking disabled](operator-evidence-2026-09-09/focus-loading-evidence-unbaked.json)
- [Coverage delayed: overview visible inside the acquired focus position](operator-evidence-2026-09-09/focus-coverage-delayed-unbaked.png)
- [Signal delayed on Z scrolling: temporary black block](operator-evidence-2026-09-09/focus-new-z-signal-delayed-unbaked.png)
- [Settled focus display](operator-evidence-2026-09-09/focus-settled-unbaked.png)

The complete metadata audit, reproduction scripts, and generated test stores remain in the local diagnostic workspace below. The full microscope run and those generated stores are not part of this documentation commit.

```text
C:\ProgramData\MinicondaZMB\home\t.de\operator-diagnostics
```

All test servers, generated images, and synthetic data were separate from the real microscope window. The recorded run was read only. Small synthetic capture files were generated and organized by the focus-loop test inside the diagnostic directory.

| Experiment | Result | Evidence |
| --- | --- | --- |
| Saved TIFF/state/store metadata audit | Constant reported recipe; alternating precise/rounded output sampling | `metadata-evidence.json` |
| Native OME versus successful/unavailable job read | Both branches reproduce the exact conflicting XY values | `publication-evidence.json`, `reproduce_publication.py` |
| Actual saved-store validation | Overview positions 0/2 rejected; target mismatch rejected; uniform in-memory control accepted | `publication-evidence.json` |
| Real server + bridge publisher | Target in raw configuration, absent in cached list after other publication fails; retry control restores it | `publication-evidence.json` |
| Real focus-loop gated capture/scoring | No display handoff during capture; viewer handoff before score; inspector point after score | `focus-delivery-evidence.json`, `reproduce_focus_delivery.py` |
| Real browser with coverage delayed | Acquired zero patch exposes overview; nonzero patch adds to overview until coverage arrives | `focus-loading-evidence-unbaked.json`, `focus-loading-evidence-baked.json` |
| Real browser with signal delayed on Z scroll | Opaque black occupies the patch until signal arrives | Same files; `focus-new-z-signal-delayed-*.png` |

The current saved target position stores were rerun after the earlier inspection. In the later metadata audit, a conflicting target store appears at position 4 rather than the original position 3. The historical mismatch and the current reproduction both reflect the same two sampling values; the report intentionally retains the earlier event and later capture history separately.

### 12.2 Pixel-level display proof

The diagnostic scene uses a red overview, green focus signal, and a known zero-intensity square inside each complete focus position. The image shape and intensity pattern are identical on every stack plane.

| State | Acquired zero patch RGB | Acquired signal patch RGB |
| --- | --- | --- |
| Before the new focus position arrives | `(180, 0, 0)` overview | `(180, 0, 0)` overview |
| New focus signal arrives, coverage held | `(180, 0, 0)` incorrectly showing overview | `(180, 120, 0)` incorrect addition to overview |
| Coverage released, image settled | `(0, 0, 0)` correct opaque black | `(0, 120, 0)` correct focus signal |
| Scroll to uncached Z, signal held | `(0, 0, 0)` | `(0, 0, 0)` temporary black block |
| Signal released at that Z | `(0, 0, 0)` | `(0, 120, 0)` restored focus signal |

These exact RGB assertions passed with `bake=false` and `bake=true`. Browser error lists were empty. Controlled response gates were used to make the timing deterministic; this establishes the defect without claiming that those exact delays were measured on the instrument.

The eight recorded focus originals also agree on shape `(1, 1, 84, 64, 64)`, XY sampling 4.1 �m, Z spacing approximately 2.4089156626506 �m, and lowest stored plane approximately -35.77 �m. A varying saved XY array size is not supported by those files.

### 12.3 Focus delivery proof

The real `measure_focus` loop was called with a fake capture that blocks on a test event, then with scoring blocked on another event. No instrument driver was connected.

```text
During capture: viewer keep callbacks = 0; inspector point callbacks = 0
During scoring: viewer keep callbacks = 1; inspector point callbacks = 0
After scoring: viewer keep callbacks = 1; inspector point callbacks = 1
```

The UI's automatic selection of the next unfinished point remains separately established by the `onPoint` callback in `focus-map.js`. The diagnostic does not claim to have replayed the entire native UI focus workflow.

### 12.4 Running the reproductions

Use the new environment's Python explicitly. For browser checks use the existing local Node and application Playwright dependency. The diagnostic runner locates Chromium at `chromium-1234/chrome-win64/chrome.exe`; that actual folder differs from the older `chrome-win` assumption.

```powershell
$diagnosticRoot = 'C:\ProgramData\MinicondaZMB\home\t.de\operator-diagnostics'
$diagnosticPython = 'C:\ProgramData\MinicondaZMB\envs\zmart-operator-relative-z\Scripts\python.exe'
$diagnosticNode = 'C:\ProgramData\MinicondaZMB\envs\zmart-microscopy\node.exe'
& $diagnosticPython "$diagnosticRoot\reproduce_publication.py"
& $diagnosticPython "$diagnosticRoot\reproduce_focus_delivery.py"
# In a separate terminal; serves only generated diagnostic data:
& $diagnosticPython "$diagnosticRoot\serve_focus_repro.py"
# While that server and the relative-Z Vite server on 5175 are running:
& $diagnosticNode "$diagnosticRoot\reproduce_focus_loading.mjs"
& $diagnosticNode "$diagnosticRoot\reproduce_focus_loading.mjs" --bake
```

These scripts reproduce existing failures and assert their signatures. Once the product is fixed, invert the display expectations so transient incorrect pixels fail regression tests. A passing reproduction today is evidence of the bug, not evidence of a correction.
