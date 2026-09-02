# Smart Operator workflow review — Steps 1 to 8 on the real bridge and Smart Viewer 0.2

**Date of review:** 2026-09-02
**Reviewed:** `thomdehoog/ZMART-microscopy`, branch `codex/smart-viewer-integration-cleanup`,
remote head `6e360a490c09db77426949e182949af7e7e8617c` (draft PR #24; confirmed equal to the
expected head, worktree clean before the review began).
**Smart Viewer authority:** `thomdehoog/ZMART-viewer` 0.2.0 at
`9ff10b04e803fbe2a71a1735a8065a845ea803dd`, cloned and installed with `pip install --no-deps -e`,
import path `/home/user/thomdehoog/zmart-viewer/zmart_viewer/__init__.py`; `/api/measure` present.
**Review branch (fixes and evidence):** `claude/smart-operator-workflow-review-ehw3c5`. Nothing was
pushed to the codex branch and PR #24 stays in draft.
**Second pass (2026-09-02, later):** every finding that needed no product decision was fixed on the
review branch and re-verified; section 10 lists the changes and the runs that hold them. The
per-finding status lines below say what was done for each.
**Third pass (2026-09-02, on the operator's PC):** with Cellpose available, Steps 6 to 8 were run on
real pixels through the operator page. That reached two defects no earlier pass could (HIGH-3, the
detection lost after Cellpose finished; MEDIUM-9, the cell map starving the picture server) and one
more on the page (MEDIUM-10); all three are fixed and re-proven. Interruption and partial
acquisition accounting were then proven the same way and exposed a fourth (MEDIUM-11, the gallery
empty after a stopped run), fixed likewise. Section 11 has the pass.

The document `docs/reviews/2026-09-01-why-the-acquired-overview-never-appeared.md` named in the
review brief does not exist on this branch or on any fetched branch; the plan cites it as the
origin of the flat-z and stale-source gates. The other three named documents and both evidence
directories were read in full.

## 1. Executive verdict

**PR head: conditional pass. Review branch: pass.** The verdict below describes the PR head as
reviewed; section 10 records that conditions 1, 2 and 4 are fixed and re-proven on the review
branch, and section 11 that condition 3 fell on the operator's PC -- where the first real
detection exposed HIGH-3 and MEDIUM-9, which the PR head also carries and the review branch fixes.

Steps 1 to 5 work end to end on the production build served by the real
bridge, with the mock kidney and the separate Smart Viewer 0.2, and the live Step 8 source model
holds: a target scan arrives as its own Viewer acquisition (observed name `targets`), every
acquired position is one spatial source behind each of its three channel rows, requested
visibility and the whole-plate Fit survive its arrival, and the three groups switch on and off
independently without touching a source matrix. The conditions are:

1. The Neuroglancer adapter moved only the **first** source of each channel row back to the
   corner of its voxel. Every later tile of an acquisition stood half a voxel (2 µm on the mock)
   away from the first and from the plan. The accepted 0/3/6/9 records show exactly this
   (0 µm on field 0, 2.83 µm on fields 1–8) inside a 4 µm tolerance that hid it. This review fixes
   the adapter and re-proves Step 5 at 0 µm on all nine fields and the live target group at 0 µm
   on all three target sources (section 9). The PR head itself still carries the defect.
2. The accepted Step 5 evidence spec cannot run on the PR head: the panel rewrite renamed the
   Auto button's accessible name, so the spec waits forever for a button called "Auto" and both
   tests time out after 15 minutes. The accepted records were captured five commits earlier
   (`77cb291e`), before that rewrite.
3. Steps 6 and 7 could not be exercised live here: the Cellpose weights download from
   `huggingface.co` is denied by this container's egress policy (HTTP 403). Their canvas
   behaviour is proven only with the pretend backend. Step 8's canvas rings, gallery and
   verdicts are likewise pretend-only; the Step 8 **source** path is proven live.
4. Several smaller defects listed below (a position store is visible to the Viewer before its
   coarser levels are written, stale target sources after a shorter rerun, a TypeError shown
   instead of the analysis's reason when a tile test fails, a shipped default password, target
   frames hidden under the plan's ground outside overview fields).

Nothing in the coordinate audit shows an arbitrary offset, a duplicated origin, raw stage Z used
as specimen Z, or navigation state leaking into a transform.

## 2. Findings, by severity

### HIGH-1 — Half-voxel correction reached one source per row; every later tile misplaced by 2 µm

**Status: fixed on the review branch and re-proven (0 µm on nine overview and three target sources, both passes).**

- **File:** `viz_studio/options/neuroglancer-under/viewer.js`, function
  `countFromTheCornerOfTheVoxelRatherThanItsMiddle` (head: line 1280 reads
  `layer.dataSources?.[0]?.loadState?.transform` only, gated on the engine's
  `voxelCenterAtIntegerCoordinates` flag).
- **Observed:** In the accepted `9-of-9-run.json` the registration table reads field 0 → 0 µm,
  fields 1–8 → 2.828 µm (−2 µm in x and in y, half of the 4 µm voxel). The same numbers came back
  on head in this review's 3-of-9 and 6-of-9 records, and the bridge-published target group had
  all three of its sources 2.828 µm off.
- **Root cause, measured:** the writer puts the *corner* of the first voxel in the OME-Zarr
  translation (`zarr_positions.py` docstring; `_the_corner_of`). Neuroglancer places the first
  voxel *centre* on the translation, so every source lands half a voxel early. The adapter
  compensated only where the engine's flag said "centre convention", and only for the first
  source of a row. With diagnostics on, the flag read `[t, c, z, y, x] = [T, T, T, T, T]` for
  overview and focussing stores (voxel-aligned translations) but `[T, T, T, F, F]` for the target
  stores (translations that are not whole voxels), while the engine placed both kinds the same
  way: lower bound = translation − 2 µm. The flag describes axis labelling, not placement.
  After the first correction the layer's shared output-space flag flips, so later sources of the
  same row were never corrected either.
- **Expected:** every position store of an acquisition is placed with its first-voxel corner on
  the translation the writer meant, so all centres equal the plan's absolute stage points.
- **Effect:** invisible at 12 µm per pixel (0.07 px) and hidden by the 4 µm tolerance in the
  evidence spec, but a real half-voxel seam between tiles at full resolution and a wrong answer to
  "is this pixel inside the field I laid out".
- **Reproduction:** run `step-five-kidney-evidence.spec.js` on head (after the HIGH-2 locator
  patch) and read `registration.positions[*].errorUm`; or the new
  `review-live-target-arrival.spec.js` bridge test and read `registration[*].errorUm`.
- **Boundary:** engine adapter. Writer translations and Viewer config are consistent with each
  other; the durable cure the plan itself names — the writer declaring the NGFF centre
  convention by adding half a voxel per level — would remove the adapter compensation entirely
  and is recommended as follow-up (it changes every store's metadata, the `zarrTrace`
  expectations, and the interop tests).
- **Fix made on the review branch:** the loop visits every `dataSources` entry, moves each loaded
  source back by half a voxel on the two drawn axes exactly once (a `WeakSet` of load states;
  a reloaded source gets a new load state and is moved again), and no longer reads the flag.
  `layersForMeasurement` now reports the flag per source so a record can show it.
  Verified: 0/3/6/9 deterministic and Run-button records on the fixed code report
  `maximumErrorUm = 0` on all nine fields with nine textured ROIs; the bridge-published target
  group reports 0 µm on all three target sources; view preservation still holds on one Viewer
  instance. Side effect: when a new source's placement is settled the engine cancels and refetches
  its first chunk requests (reported by the browser as `net::ERR_ABORTED`); pixels still arrive,
  and the two evidence specs now record those cancellations apart from failed requests.

### HIGH-2 — The accepted Step 5 evidence spec is broken on the PR head

**Status: fixed; the spec passed both tests in the second pass (72 s) and its records replace the accepted Step 5 evidence.**

- **File:** `application/step-five-kidney-evidence.spec.js:811` (head) uses
  `getByRole("button", { name: "Auto", exact: true })`; `application/parts/canvas/viewer-panel.js:575`
  (commit `cd88f5b`) sets the button's accessible name to `auto contrast <channel>`.
- **Observed:** both tests wait for the click for the whole 900 s budget and fail. A traced rerun
  (`DEBUG=pw:api`) shows the last call as `waiting for getByRole('button', { name: 'Auto' })` after
  all nine sources loaded and the histogram measured. The accepted records carry provenance commit
  `77cb291e`; five later commits changed `viewer-panel.js` and `watching-the-run.js`.
- **Expected:** the branch's Step 5 acceptance gate runs green on the commit that is up for
  review.
- **Fix made:** the spec now clicks `.viewer-panel button[aria-label^="auto contrast"]`, and the
  grid-framing gestures are wrapped as an operator navigation so engine chunk cancellations during
  the zoom are recorded rather than counted as failures. Both tests pass on the fixed branch.

### MEDIUM-1 — Cellpose discovery unavailable here; Steps 6–7 live remain unproven

**Status: was this container's egress policy, not a code defect. Closed in the third pass (section 11): on the operator's PC, with the weights on disk, Cellpose ran through the real bridge -- and exposed HIGH-3 and MEDIUM-9 behind it, both fixed there.**

- The tile test through the real bridge failed with
  `Could not initialize CellposeModel on any device: cpu: <urlopen error Tunnel connection failed:
  403 Forbidden>` (weights from `huggingface.co`, blocked by egress policy). Evidence:
  `step6-discovery-blocked.json/png`. Everything about candidate placement, gating and acquisition
  rings on the canvas is therefore proven only by `framework/operator-page.spec.js` with
  `?backend=pretend`, which passed here (32 of 33; see LOW-3).

### MEDIUM-2 — A tile test that fails shows a page TypeError instead of the analysis's reason

**Status: fixed; the operator-path test skips at Step 6 with the analysis's own sentence in the readout (both passes).**

- **File:** `application/framework/window/main.js:1124` (head).
- **Observed:** the panel readout said `Cannot read properties of undefined (reading 'cells')`;
  the bridge had reported the field under `failed` with the pipeline's sentence.
- **Fix made:** `tryOn` now throws the bridge's `why` when no field came back; the new spec asserts
  the readout contains it.

### MEDIUM-2b — A position store is published before its coarser pyramid levels are written

**Status: fixed on the review branch.** `zarr_positions.py` now builds each store under `positions/.writing-<type>/` and renames it into `positions/<type>/` after the last level is filled; a rerun of the same position moves the old store aside and the new one in (two renames). Held by three new tests in `test_zarr_positions.py` (levels filled before publication, nothing left beside the store, replacement under the same name) and by the deterministic 0/3/6/9 run, which no longer sees any level-1 404 (`after-fixes` Step 5 records: 0 unexpected failures at every checkpoint).

- **Files:** `application/parts/storage/zarr_positions.py:93` (levels are filled "from the finest
  down" after `zarr.json` is declared), `application/parts/storage/viewer_service.py:200`
  (`a_position_landed` announces after the write; the Viewer's generic folder watcher publishes a
  store as soon as its description exists).
- **Observed:** in the final deterministic 0/3/6/9 run, three level-1 chunk requests for
  `overview_…_P000003` (one per channel) answered **404**; the engine had asked for the 2× copy the
  12 µm/px view draws before the writer had filled it. The next "may have landed" re-read fetched
  them and the field ended textured, so the picture healed; the accepted-evidence rule "no
  unexpected request failed" is right to flag it. Two of three earlier runs did not hit the race.
- **Expected:** a store becomes visible only when it is complete.
- **Recommendation:** write each position store under a temporary name and rename it into
  `positions/<type>/` after the last level is filled, or use the Viewer's atomic publication marker
  (`zmart_viewer/live.py` watches one directly) instead of the generic folder watcher.

### MEDIUM-3 — A shorter rerun of a target scan leaves stale target sources in the Viewer group

**Status: fixed on the review branch.** `_start_scan` now names the stores the new plan will write again and removes every other store of that kind before the first drive; the viewer service is told and leaves any source whose store is gone off disk out of what the page is handed (`_still_on_disk`); the display copies are rebuilt from the new records. A first attempt asked the Viewer to close the acquisition and reopen the folder: that is not a usable route with Viewer 0.2, which treats a reopened folder as a new linked picture and remembers closed store names, so it was replaced by the retire-and-filter rule. Held by three bridge tests and four service tests, by a live probe (3 → 2 → 2 replaced in place → 3 → 4 sources through a shrink and regrowth) and by the review spec's rerun check, now hard: `viewerSourcesPerChannel [2, 2, 2]`, `engineSourcesPerRow [2, 2, 2]`, 2 stores on disk, 6 misses on the retired store recorded apart from failures, 0 unexpected failures (`after-fixes/live-target-arrival/bridge-step8-rerun-with-fewer-targets.json`). Growth by cumulative reruns (the Step 5 harness) still keeps one Viewer instance (view-preservation: 3 → 24 → 27).

- **Files:** `application/framework/bridge.py:836` (`_start_scan` resets `_records` only),
  `application/parts/storage/output.py:75` (`prepare_acquisition` never clears
  `positions/<type>`), `application/parts/storage/viewer_service.py:200` (folder opened once,
  never pruned).
- **Observed live:** after three targets were acquired, a rerun of two positions left
  `viewerSourcesPerChannel = [3, 3, 3]`, `engineSourcesPerRow = [3, 3, 3]`, three stores on disk,
  two records. Evidence: `bridge-step8-rerun-with-fewer-targets.json`.
- **Expected:** a rerun accounts for exactly what it captured. The plan's rerun rule ("replace the
  correct acquisition using Smart Viewer's identity and revision semantics") is not implemented for
  a shrinking scan.
- **Recommendation:** on `_start_scan`, remove (or move aside) stores of the same acquisition type
  whose position index is beyond the new plan, and tell the Viewer; or name reruns as a new
  acquisition revision. Not fixed here: it needs a decision on rerun semantics.

### MEDIUM-4 — Acquired target frames outside overview fields are hidden under the plan's ground

**Status: fixed on the review branch.** `openTheGroundThatHasBeenScanned` opens a window over each acquired target frame (centred on its cell, as wide as the recording's frame) and is called as each target lands; the canvas exposes its windows (`groundWindows`). Held by the pretend whole-run walk in `operator-page.spec.js`, which checks one window per acquired target at the frame size (passed, 1.2 m).

- **File:** `application/workflows/target_acquisition/shared/stage.js:734`
  (`openTheGroundThatHasBeenScanned` opens see-through windows for `run.plan` fields only).
- **Observed:** in `bridge-step8-complete-overview-and-targets.png` the part of a target frame
  that lies outside its overview field is covered by the pale ground at the default fade; the
  target-only capture with fade 0 shows the same frame textured. A target acquired at the edge of
  the plan is only visible after the operator fades the layers.
- **Recommendation:** open a see-through window for each acquired target frame as well (the run
  knows `targetFrameUm` and the acquired positions).

### MEDIUM-5 — The live target group is `targets`; every panel test and the panel-UX evidence use `target`

**Status: fixed on the review branch.** The page now names the acquisition `target` (backend calls, picture addresses), which is the name the notebook flow, the storage tests, the panel tests and the panel-UX evidence already used; the canvas layer and step mode keep their own key `targets`. Observed live in the second pass: Viewer group `target`, folder `positions/target`. `zmart_live/profiles.py` (a separate package the operator page does not use) still calls its profile `targets` and was left alone.

- `application/framework/window/main.js:749` sends `acquisition_type: "targets"`; the bridge writes
  `positions/targets`; Smart Viewer reports the group `targets`; the canvas mode and layer key are
  `targets`. `application/viewer-panel-state.spec.js:14`, `viewer-panel-ux-evidence.spec.js:114` and
  `parts/storage/test_zarr_positions.py:151` parameterize `target`, and the accepted panel-UX
  screenshots show a `target` group that never occurs live.
- No acquisition-name-specific coordinate logic exists (only `focussing` is special-cased, for draw
  order, in `watching-the-run.js:544`), so there is no configuration or coordinate effect; the
  inconsistency is that no committed test or evidence exercises the real name. Recommendation:
  pick one name (`target` is the conceptual one) and use it in `main.js`, the bridge folder and the
  tests together.

### MEDIUM-6 — The bridge still imports the reference-only copied backend at runtime

**Status: fixed on the review branch.** `viz_studio/backend/jpeg_tiles.py` moved to `application/parts/storage/jpeg_tiles.py`; the bridge, `mock_picture.py` and the bridge tests import it there; a shim under `viz_studio/backend/` keeps the 22 historical JPEG tests running (all pass). Nothing in the runtime imports `viz_studio` any more.

- `application/framework/bridge.py:772` and `:795` import `viz_studio.backend.jpeg_tiles` for the
  focus slice previews and the JPEG view tiles; `viz_studio/backend/REFERENCE_ONLY.md` says the tree
  must not be imported. The Viewer-provenance guard covers only `viewer_service.py`. Package G's
  "reference-only" claim is overstated for the JPEG fallback and the Step 4 preview.

### MEDIUM-7 — Panel-UX "coordinate safety" evidence is an identity-matrix fixture

**Status: fixed on the review branch.** Both panel fixtures place every source with a voxel size on the diagonal and a stage corner in the last row; the UX spec asserts no matrix is the identity and that all stay byte-equal through the visibility actions. Passed against the live Viewer 0.2 reference (2 of 2); new captures under `after-fixes/panel-ux/` with `record.json`.

- `application/viewer-panel-ux-evidence.spec.js:135` mounts the panel on a fake viewer whose five
  sources carry identity matrices; the JSON claim "all five immutable identity matrices" cannot
  show that real transforms are untouched. (The Step 5 records and this review's Step 8 records
  compare real per-source matrices before and after visibility actions: equal.)

### MEDIUM-8 — The production build ships a default password

**Status: fixed on the review branch.** `DEFAULT_SESSION.password` is empty. Connect first stayed disabled until one was typed; in the third pass the operator decided otherwise (section 11): the field starts empty and stays optional, the page says nothing about a password being needed, and whether one is wanted is the instrument's business when the session is opened. The password test now expects an empty field and an enabled Connect; every browser spec still types its own.

- `application/parts/microscope/instruments.js:63` sets `password: "demo"` with a comment that a
  real build must ship it empty. Connect is enabled without typing anything; the gate is only
  proved once the field is emptied (this review's Step 1 record notes
  `passwordPrefilledByThePage: true`).

### LOW-1 — Step 5 evidence records carry no PNG dimensions or SHA-256

**Status: fixed.** Every Step 5 record carries `artifact.{png,width,height,sha256}`; the replaced accepted records all verify (0 mismatches over 48 records).
The eight `2026-09-01-smart-viewer-step-five/*.json` records omit the artifact block the panel-UX
records carry; the review brief requires it.

### LOW-2 — Failing Python tests on the branch

**Status: fixed.** The webapp tests import their own package and match the demo CLI's arguments (35 pass); the detection test builds its paths for the running machine (all pass).
`application/workflows/target_acquisition/webapp/test_webapp.py` (10 tests) import the stale path
`workflow.webapp`; `application/parts/microscope/test_detection.py::test_a_capture_with_a_position_store_is_read_from_it`
builds Windows paths and fails on Linux. 301 of 312 focused tests pass. Not production defects.

### LOW-3 — Timing-fragile browser tests

**Status: fixed.** The canvas walk and the two-run plan test are marked slow; the operator walk reads the slice preview once the map has finished (the preview follows the point under measurement by design). The operator walk passed in 59 s and both slow tests passed alone.
`framework/operator-page.spec.js:447` ("the canvas is always on the stage") keeps the 30 s default
test timeout around a 60 s wait and timed out twice here; `the-operator-walk.spec.js:179` expects
the focus slice preview while the run is still measuring, but the preview follows the selected
point, which the run advances, so it fails deterministically here (three runs). The preview does
appear once the run ends (diagnostic walk recorded 61 slices per point).

### LOW-4 — Committed bundle differs from a fresh build

**Status: resolved in the first pass.** The review commit rebuilt the page; a fresh `npm run build` now reproduces the committed bundle exactly (no diff).
`framework/window/static/chunk_worker.bundle-CycDtxtB.js` is committed; a fresh `npm run build`
produces `…-VL1EZiOw.js`. `the-built-page.spec.js` passed against the rebuilt bundle.

### LOW-5 — After Disconnect the page reopens a picture on the JPEG fallback address

**Status: fixed.** The page hands out no picture address and no Viewer sources once the session is closed; the review spec now requires no open picture after Disconnect (`bridge-step1-reconnected.json`: `pictureOpen: false`).
`watching-the-run.js:706` keeps polling; with the bridge session closed `viewerSources` is null
and `pictures("overview")` is still an address, so a JPEG engine opens on an empty view. No
acquisition source survives (checked), so no stale pixels; but the picture object is not null.

## 3. Gate table, Steps 1–8

| Step | Gate | Result | Proven with |
| --- | --- | --- | --- |
| 1 Connect | instruments and APIs from backend; password gate; checks settle; failures visible; travel and position from driver; disconnect resets; reconnect | **passed** (head: password gate only after emptying the prefilled field, MEDIUM-8; review branch: field ships empty) | production build + real bridge (`step1-connected`, `step1-reconnected`) |
| 2 Carrier | slide and plate presets; carrier-local geometry; origin centred in travel; no origin compensation on sources; edits invalidate plan | **passed** | production build (`step2-carrier`), operator-page pretend suite (carrier tests), source review of `stage.js` |
| 3 Scan area | optics recorded from the microscope; grid; counts match carrier and frame; every position on screen; plan locked after scan | **passed** (grid/fields/regions/polygon/clear behaviours proven with pretend backend) | `step3-plan`, operator-page pretend suite |
| 4 Focus | focussing configuration recorded; points measured through the analysis; traces and stack; fixed/mapped behaviour; focus Z provenance only | **passed** (slice-preview timing test LOW-3, fixed) | `step4-focus-map`, `the-map-fills-in`, `a-moved-point-has-no-curve`, bridge probe |
| 5 Overview | 0/3/6/9; Run button; nine ROIs examined and textured; three rows × nine sources; growth without remount; Fit preserved; overview-only; close-up; projection < 1 px; real `/api/measure`; no unexpected failures | **failed on head** (HIGH-1 misplacement, HIGH-2 broken spec) → **passed on the fixed review branch** | real bridge + Viewer 0.2 + mock kidney (`step-five-fixed/*`, `view-preservation.json`, `step5-overview-complete`) |
| 6 Discover | preview is the selected field; settings; test vs all; ids and positions; candidates on canvas; layer changes canvas; hoverable; failures honest; a test and a run can be stopped by hand | **blocked live** in the container (MEDIUM-1) → **failed on real pixels** on the operator's PC (HIGH-3) → **passed on real pixels** on the review branch (section 11); failure reporting fixed (MEDIUM-2); the tile test had no brake (MEDIUM-12), the brake did not stop the field (MEDIUM-13) detection fell back to the CPU without a word (MEDIUM-14) and a run written beside the page lost its stores to a denied rename (MEDIUM-15), the test after a stopped one could get the analysis on its way out (MEDIUM-16), all fixed and re-proven live | operator-page pretend walk; `step6-discovery-blocked`; `on-the-operators-pc/step6-discovered-over-overview` |
| 7 Refine | candidates before gate; no implicit gate; polygon gate; intersection; feedback; counts agree; gate survives navigation; coordinates unchanged | **passed on real pixels** (section 11) after MEDIUM-10 (the ceiling now survives navigation with the gate); **passed with pretend backend** | operator-page pretend walk; `on-the-operators-pc/step7-*` |
| 8 Acquire | configuration before acquisition; button gating; one conversion; focus Z provenance; positions equal; rings/frames; gallery; verdicts; partial runs | button path with real discovered targets **passed live** (section 11; three gated cells acquired at their positions, registration 0 µm, rings, gallery, verdicts, one-at-a-time growth); source model **passed live**; interruption **failed** (the gallery stayed empty after a stopped run, MEDIUM-11) → **passed live** on the review branch: stopped by hand after 5 of 12, every account says 5, Run again says 12 | `bridge-step8-*` records; `on-the-operators-pc/step8-*`; `on-the-operators-pc/interruption/` |

## 4. Test ledger

Environment: Linux container, Python 3.11.15, Node 22.22.2, Chromium 141 (Playwright's own
build 1194) with SwiftShader software GL, four cores. A `conda` stand-in on PATH runs the analysis
engine's per-step workers with the one interpreter (documented in the evidence manifests); torch
2.13 (CPU) and cellpose 4.2.1 were installed but the model weights cannot be fetched.

| Command (cwd) | Result | Time | Notes |
| --- | --- | --- | --- |
| `pytest tests/test_server.py tests/test_stores.py tests/test_datasets.py tests/test_acquisition_groups.py tests/test_announcements.py tests/test_many_positions_arrive.py tests/test_live_publication_gateway.py tests/test_an_acquisition_folder_offers_one_image.py tests/test_positions_land_wherever_they_are_put.py tests/test_brightness_is_measured_honestly.py tests/test_auto_reads_what_is_on_screen.py tests/test_a_run_arriving.py tests/test_a_second_acquisition_type_arriving.py` (Viewer 9ff10b0) | 159 passed, 9 skipped | 53 s | 6 skips: page not yet built; 1: `ZMART_FIND_THE_LIMIT` unset; 1: writer cannot add to a running run; 1: `run_demo.py` needs the built page |
| `pytest application/framework application/parts/storage application/parts/microscope application/workflows/target_acquisition/steps … test_steps.py test_pixel_to_frame.py test_v4_flow.py webapp/test_webapp.py` | 301 passed, 11 failed | 118 s | LOW-2 |
| `npx vitest run` (head) | 365 passed, 15 skipped | 8 s | skips are the suite's intentional ones |
| `npm run build` (head) | ok | 9 s | bundle differs from committed (LOW-4) |
| `playwright test parts/canvas/canvas-layers.spec.js` | 14 passed | 15 s | |
| `playwright test viewer-panel-look.spec.js` | 1 passed | 10 s | |
| `playwright test viewer-panel-histogram.spec.js` | 4 passed | 8 s | edge drag, pan, wheel, dblclick, typed values, Log, stale/failed Auto |
| `playwright test viewer-panel-state.spec.js` | 3 passed | 7 s | group eyes, persistence, engine mismatch reconciliation (group named `target`) |
| `playwright test framework/operator-page.spec.js` | 32 passed, 1 failed | 5.9 min | pretend backend; failure LOW-3; "one walk of the whole run" (Steps 6–8 canvas) passed |
| `playwright test …/focus_strategy/the-map-fills-in.spec.js`, `a-moved-point-has-no-curve.spec.js` | 1 + 1 passed | 23 s each | real bridge, real analysis workers |
| `playwright test …/shared/drive-to.spec.js` | 1 passed | 7 s | |
| `playwright test …/the-scan-the-page-takes.spec.js`, `the-scan-under-the-plan.spec.js`, `live-overview.spec.js`, `live-overview-layers.spec.js`, `live-overview-sparse.spec.js` | 2 + 3 + 1 + 1 + 2 passed | 35 s, 50 s, 38 s, 28 s, 90 s | |
| `playwright test framework/the-built-page.spec.js` | 1 passed | 11 s | built vs development ink equal |
| `playwright test …/the-operator-walk.spec.js` | 1 failed (×3 runs) | 15 s | LOW-3 (`#zpreview` timing) |
| `playwright test step-five-view-preservation.spec.js` (head) | 1 passed | 35 s | 3 → 24 → 27 sources on one Viewer instance, drift < 0.25 px |
| `playwright test step-five-kidney-evidence.spec.js` (head) | 2 failed (timeouts, 900 s each) | 30 min | HIGH-2 |
| `playwright test every-tile-is-filled.spec.js` (head) | 1 passed | 3.2 min | 54 of 54 six-well fields drawn |
| `ZMART_VIEWER_REFERENCE_URL=… playwright test viewer-panel-real-measure.spec.js` | 1 passed | 5 s | real `/api/measure`, window equals the Viewer's answer |
| `… viewer-panel-ux-evidence.spec.js` | 2 passed (first run 1 failed: reference served with `live=False` aborted `/api/events`) | 12 s | fixture panel + real measurements |
| `playwright test review-live-target-arrival.spec.js` (new, head adapter) | 1 skipped at Step 6 (blocked), 1 failed on soft checks | 75 s | soft failures: target registration 2.83 µm (HIGH-1), stale rerun (MEDIUM-3) |
| `pytest tests/test_many_positions_arrive.py tests/test_positions_land_wherever_they_are_put.py tests/test_auto_reads_what_is_on_screen.py tests/test_a_run_arriving.py tests/test_a_second_acquisition_type_arriving.py` (Viewer, page built) | 58 passed, 2 skipped | 57 s | skips: `ZMART_FIND_THE_LIMIT` unset; writer cannot add to a running run |
| `npx vitest run` (fixed branch) | 365 passed, 15 skipped | 8 s | |
| `npm run build` (fixed branch) | ok | 9 s | committed on the review branch |
| `playwright test step-five-kidney-evidence.spec.js` (fixed branch, final) | Run button passed; deterministic failed only on MEDIUM-2b (three 404 level-1 chunks); both report 9/9 examined and textured, `maximumErrorUm = 0` | 64 s | an earlier fixed run passed 2 of 2 |
| `playwright test step-five-view-preservation.spec.js` (fixed branch) | 1 passed | 36 s | drift 0 px, one instance, no failed request |
| `playwright test review-live-target-arrival.spec.js` (fixed branch) | Steps 1–5 passed; Step 6 skipped (MEDIUM-1); bridge-path Step 8 passed every check except the soft MEDIUM-3 rerun check | 79 s | target registration 0 µm, projections 0.07 px |
| `playwright test every-tile-is-filled.spec.js` (fixed branch) | 1 passed, 54 of 54 fields | 3.2 min | |
| `playwright test framework/the-built-page.spec.js`, `parts/canvas/canvas-layers.spec.js`, `viewer-panel-state.spec.js` (fixed branch) | 1 + 14 + 3 passed | 12 s, 12 s, 7 s | |
| `playwright test …/the-operator-walk.spec.js` (fixed branch) | 1 failed | 23 s | LOW-3, unchanged |

Skips that are not passes: the Steps 6–7 live walk is skipped by the new spec with the Cellpose
reason recorded; the two remaining Viewer skips are opt-in stress tests.

## 5. Screenshot and evidence manifest

Every PNG below has a JSON record beside it with repository, branch and commit, Viewer version and
commit, backend and page provenance, workflow step and state, plan count, per-group source counts,
acquisition and channel structure, requested and engine-observed visibility, selected channel,
per-source bounds and matrix hashes, carrier-local, absolute-stage and projected coordinates,
Z anchor and provenance (target stores), pixel checks, projection error, allow-listed probes,
unexpected failures, browser and worker errors, and PNG width, height and SHA-256.

Accepted (fixed review branch, production build served by the bridge, real bridge, real Viewer
0.2, mock kidney) — `docs/reviews/evidence/2026-09-02-smart-operator-review/`:

| File | Step | What it shows |
| --- | --- | --- |
| `step1-connected` | 1 | five driver checks answered; instruments from the backend |
| `step2-carrier` | 2 | 75 × 25 mm slide centred in the 120 × 80 mm travel |
| `step3-plan` | 3 | 3 × 3 grid from the driver's 1024 µm frame, all nine positions on screen |
| `step4-focus-map` | 4 | measured point, XY slice, ZX reslice, focus plot |
| `step5-overview-complete` | 5 | Run button, 9/9 sources per channel, nine textured ROIs, focussing hidden |
| `step6-discovery-blocked` | 6 | real field preview; the analysis's 403 reason in the readout |
| `bridge-step8-ready-to-acquire` … `bridge-step8-rerun-with-fewer-targets` | 8 | target group `targets` arriving, complete, target-only, overview-only, rerun |
| `step1-reconnected` | 1 | run-owned state reset and reconnect |
| `step-five-fixed/0-of-9 … kidney-close-up` | 5 | the branch's own deterministic and Run-button records on the fixed adapter |
| `panel-ux/smart-viewer-0.2-reference`, `smart-operator-comparable-panel`, `…-focussing-overlay`, `…-overview-only` | 5–8 | Viewer 0.2 reference and the Operator panel states (fixture engine, real measurements) |

Third pass (operator's PC, real Cellpose; section 11) — `on-the-operators-pc/live-target-arrival/`:

| File | Step | What it shows |
| --- | --- | --- |
| `step6-discovered-over-overview` | 6 | 4010 real Cellpose candidates over the nine fields; the field preview with its masks |
| `step7-candidates-before-gate`, `step7-gated-selection` | 7 | every candidate as context; a polygon gate on area x intensity keeping 3 under a ceiling of 3 |
| `step8-ready-to-acquire` … `step8-gallery-with-verdict` | 8 | the button path: three gated cells acquired, frames and rings on the overview, close-up ring, gallery with a verdict |
| `bridge-step8-*`, `step1-reconnected` | 8, 1 | the source model and the disconnect, re-proven on this machine |

Kept separate as failed or partial runs (not accepted): `head-branch/` holds the head-branch
Step 5 and Step 8 records showing the 2.83 µm registration and the run summaries of every batch
(including the batch-5 runs contaminated by orphaned bridge processes).

Inspected screenshots from the accepted set: every one listed above was opened and looked at.
The 3/6/9 pictures show tissue only where the ROI ledger says so; the target-only picture shows
three separate kidney frames at their off-centre target positions and nothing elsewhere; the
overview-only picture shows the nine-field mosaic with the target frames gone.

## 6. Coordinate and Z audit

| Boundary | What was read | Result |
| --- | --- | --- |
| Plan | `__theStageCanvas.plan()`, carrier-local, 1024 µm frames | nine centres 35476…37524 / 10476…12524 |
| Carrier origin | `carrierOriginUm()` | (23500, 28500): slide centred in the driver's travel; applied once by `toStage` in `main.js:610` and `:747` |
| Bridge | `requested_position_um` per record | plan + origin exactly; focus z from the fitted map |
| Position store | level-0 `translation` (y, x) | absolute-stage top-left corner = centre − 512; z = 0 for flat stores; stacks anchored on the requested plane (index 30 of 61 for the focussing stack, spacing +1.133 µm) |
| Store Z record | `zmart_microscopy.z_coordinate` | `only-voxel-center` / `requested-stage-focus-z`, `registered_specimen_z: false`, raw plane centres and requested focus z kept |
| Engine | per-source bounds from `layersForMeasurement` | head: first source exact, others −2 µm (HIGH-1); fixed: all overview sources exact (0 µm) and all target sources exact (≤ 1e-11 µm, second pass) |
| Navigation | `2d-overlay` sets nav z = 0 (`openOnThePlaneWhereTheSpecimenIs`) | never rewrites a transform |
| Stage canvas ↔ engine projection | plan centres through both | 0.070 px at every zoom used |
| Visibility, order, panel actions | per-source matrices before/after | byte-equal in every record |

No acquisition-name-specific coordinate logic exists. Draw order (overview, then other groups in
Viewer order, focussing last) is chosen in `watching-the-run.js:544` and does not touch a source.

## 7. Viewer source-lifecycle audit

- **Focussing:** opened at the first focus stack (`a_position_landed` → `/api/stores/open`),
  one channel row, one source. Hidden through the panel before the overview scan in every run;
  stayed hidden across every later arrival.
- **Overview:** the first field opens `positions/overview`; a new acquisition beside focussing is a
  new scene, so the page reopens once. Fields 2–9 grow the three rows through `addSources` on the
  same Viewer instance (view-preservation: 3 → 24 → 27 sources, one instance, drift < 0.25 px).
- **Targets:** the first target position opens `positions/target` (`positions/targets` on the PR head, MEDIUM-5); Smart Viewer lists a third
  acquisition `target` with three channel rows; the page reopens once (a genuinely new
  acquisition shape) and then holds the instance. All three target sources landed within one page
  poll of each other, so growth 1 → 2 → 3 on the target group was not observed separately;
  the arrival log records the sequence. A shorter rerun left stale sources on the head (MEDIUM-3); on the
  review branch it is accounted exactly (2 sources per row, 2 stores on disk) after one reopen.
- **Disconnect:** the viewer service stops, `/api/viewer` reports not running, no acquisition
  source survives on the page; on the review branch no picture is open at all (LOW-5 fixed).

## 8. What was proven with what

- **Pretend backend only:** Steps 6–8 canvas behaviour (candidates inside their fields, no
  implicit gate, polygon gating, selected/acquired marks, hoverable targets, gallery verdicts),
  the panel-UX screenshots' engine state.
- **Real bridge, real analysis workers, mock kidney (no Viewer needed):** focus map measurement,
  slice previews, six-well per-field texture (54/54), the JPEG view path.
- **Real bridge + real Smart Viewer 0.2 + mock kidney:** Steps 1–5 end to end on the production
  build; 0/3/6/9 deterministic and Run-button evidence (on the fixed adapter); Fit preservation;
  overview-only; kidney close-up; histogram and Auto through `/api/measure`; the Step 8 source
  model with bridge-published target positions (separate `target` group, per-position sources,
  visibility survival, Fit preservation, independent group eyes, matrices unchanged, Z anchors);
  on the review branch also the shorter rerun accounted exactly and no picture after Disconnect.
- **Proven in the third pass (section 11), real bridge + real Smart Viewer 0.2 + mock kidney +
  real Cellpose on the operator's PC:** Steps 6 and 7 on real pixels (4010 candidates from nine
  fields, a polygon gate, the ceiling), the Step 8 button path with real discovered targets
  (three gated cells acquired, rings, gallery, verdicts), and target source growth one position
  at a time (the Viewer reported 1, 2, 3 sources per row at 180, 325 and 422 ms).
- **Proven in the third pass as well:** interruption and partial acquisition accounting -- an
  acquisition stopped by the page's own Interrupt after 4 of 12 pairs is accounted as 4 by the
  bridge, the Viewer, the disk, the canvas, the gallery (after MEDIUM-11) and the sentence beside
  the button, and Run again completes and re-accounts all 12.

## 9. Changes made on the review branch and their verification

See the commit on `claude/smart-operator-workflow-review-ehw3c5`. Production code:
`viz_studio/options/neuroglancer-under/viewer.js` (HIGH-1 fix; `layersForMeasurement` also reports
the per-axis convention flag) and `application/framework/window/main.js` (MEDIUM-2 fix). Tests:
`step-five-kidney-evidence.spec.js` (HIGH-2 locator; framing wrapped as navigation),
`step-five-view-preservation.spec.js` (engine cancellations recorded apart from failures), and the
new `review-live-target-arrival.spec.js`. Verification results are in the table at the end of this
section.

| Verification (fixed branch, final batch) | Result |
| --- | --- |
| `npx vitest run` | 365 passed, 15 skipped |
| `npm run build` | ok; `the-built-page.spec.js` passed |
| `step-five-kidney-evidence.spec.js` | Run button: passed, `maximumErrorUm = 0`, 9/9 textured, real `/api/measure` (66 bars); deterministic: same numbers at 3/6/9, failed only on three 404 level-1 chunks (MEDIUM-2b) |
| `step-five-view-preservation.spec.js` | passed; 3 → 24 → 27 sources on one instance; drift 0 px; no failed request |
| `review-live-target-arrival.spec.js` bridge path | `targets` group, 3 rows × 3 sources, registration 0 µm, projections 0.070 px, Fit preserved, focussing hidden throughout, target-only and overview-only pixel checks passed, matrices unchanged, Z anchors 0 with focus provenance 15.94 µm; soft check on the shorter rerun fails (MEDIUM-3) |
| `review-live-target-arrival.spec.js` operator path | Steps 1–5 passed on the production build; Step 6 skipped with the Cellpose reason shown in the panel (MEDIUM-2 fix verified) |
| `every-tile-is-filled.spec.js` | 54 of 54 six-well fields drawn |
| `canvas-layers.spec.js`, `viewer-panel-state.spec.js` | 14 + 3 passed |
| Viewer 0.2 browser tests | 58 passed, 2 opt-in skips |

## 10. Second pass: every remaining finding fixed and re-verified

All changes are on `claude/smart-operator-workflow-review-ehw3c5` (commits after `7919ea0`); PR #24
and the codex branch are untouched. MEDIUM-1 is the one finding left open, because it is this
container's egress policy and not the code.

**Production code changed:** `application/parts/storage/zarr_positions.py` (whole-store
publication), `application/framework/bridge.py` (stale stores retired on a rerun; JPEG helpers
imported from the application), `application/parts/storage/viewer_service.py` (retired stores
announced and filtered out), `application/parts/storage/jpeg_tiles.py` (moved from
`viz_studio/backend/`, shim left behind), `application/framework/window/main.js` (acquisition named
`target`; ground opened over acquired frames; no picture address after Disconnect; run state
exposes the target frame size), `application/workflows/target_acquisition/shared/stage.js` and
`application/parts/canvas/viewer.js` (windows over acquired targets, `groundWindows` reader),
`application/parts/microscope/instruments.js` (empty password), and the rebuilt
`framework/window/static/index.html`.

**Tests changed or added:** `test_zarr_positions.py` (+3), `test_viewer_service.py` (+4),
`test_operator_bridge.py` (+3, stubs repointed), `test_detection.py`, `test_webapp.py`,
`operator-page.spec.js` (password test, Step 8 windows, two slow budgets),
`the-operator-walk.spec.js` (preview after the map), `viewer-panel-state.spec.js` and
`viewer-panel-ux-evidence.spec.js` (real matrices), `step-five-kidney-evidence.spec.js` (artifact
block), `review-live-target-arrival.spec.js` (`target` name, hard rerun check, no picture after
Disconnect, retired-store misses recorded apart from failures).

**Evidence added:** `evidence/2026-09-02-smart-operator-review/after-fixes/` — the second-pass
review-spec records (`live-target-arrival/`, 18 screenshots with paired records and the manifest),
`view-preservation.json`, the panel-UX captures with `record.json`, and `browser-batches.txt` with
every suite's exit code and duration. The accepted Step 5 directory
`evidence/2026-09-01-smart-viewer-step-five/` is **replaced** by the second-pass run because the
full replacement run passed (both tests, 0 µm at 0/3/6/9, 0 unexpected failures); the head-branch
records that show the 2.83 µm defect stay under `head-branch/`.

| Verification (final code) | Result |
| --- | --- |
| Python: `test_zarr_positions`, `test_viewer_service`, `test_operator_bridge`, `test_detection`, `test_webapp` | 126 passed; the earlier LOW-2 failures are gone |
| Python: `viz_studio/tests/test_small_pictures_from_exported_tiffs.py` through the shim | 22 passed |
| `npx vitest run` / `npm run build` | 365 passed, 15 skipped / bundle identical to the committed one |
| Live probe of the viewer service against Smart Viewer 0.2 | 3 → 2 → 2 (in place) → 3 → 4 sources through shrink and regrowth, no viewer error |
| Browser batch 1 (18 pretend/bridge suites, then panel suites with the live reference, then the review spec) | 14 suites passed; `operator-page` 31/33, `focus-moved-point` 0/1 and `step-five-view-preservation` 0/1 failed while page modules were being edited (the dev server reloads every open page) and under the first, close-based rerun rule; `step-five-kidney-evidence` 1/2 under that same rule; the review spec failed only on chunk 404s of the deliberately retired store |
| Browser batch 2 (the disturbed suites alone, final code) | `step-five-view-preservation` passed (34.6 s); `step-five-kidney-evidence` 2/2 (72 s); `focus-moved-point` passed (25.7 s); `operator-page` 32/33 with the plan-editability test 0.3 s over its 30 s budget, then passed alone with the slow budget (30.4 s); `review-live-target-arrival` bridge path passed (86 s), operator path skipped at Step 6 with the Cellpose reason |
| Review spec, bridge path, second pass | group `target`; 3 rows × 3 sources; registration ≤ 1e-11 µm; projections 0.070 px; remount once at the first target arrival; Fit and visibility preserved; matrices unchanged; rerun with 2 positions → `[2, 2, 2]` in the Viewer and in the engine, 2 stores on disk; Disconnect leaves no picture open |
| Evidence hashes | 51 records carry `artifact.sha256`; 50 verify against their PNG; the one head-branch record kept without its picture (`step5-overview-complete.head.json`, numbers only) has none to verify |

What the second pass does not change: Steps 6–7 on real pixels, the Step 8 button path with real
discovered targets, one-at-a-time target growth and interruption accounting remain unproven here.

## 11. Third pass, on the operator's PC: Steps 6 to 8 on real pixels

**Where:** the review branch cloned on the development PC that runs the real instruments
(Windows 11, an AppLocker-whitelisted checkout), env `zmart-microscopy` (Python 3.11.15, node 26.5,
Playwright 1.62 with its Chromium 1234 and SwiftShader), the analysis step envs this machine
already had (`ZMART--object_analysis--vision`: cellpose 4.1.1, torch 2.11 with CUDA, the 1.2 GB
`cpsam` weights on disk), Smart Viewer 0.2.0 at `9ff10b04` installed from the sibling checkout with
`pip install --no-deps -e`. The page under test is the committed production build served by the
bridge, as in the second pass. Nothing was pushed to the codex branch and PR #24 stays in draft.

**What it settles:** MEDIUM-1 was that container's egress policy and nothing else -- with the
weights on disk, Cellpose runs through the real bridge. But the first real run past the weights
failed anyway, on a code defect no pass could have reached before (HIGH-3 below), and the first run
past *that* failed on a second one (MEDIUM-9). Both are fixed and re-proven; Steps 6, 7 and 8 are
now proven on real pixels through the operator page, the Step 8 button path with real discovered
targets included, and the Viewer was seen growing the target group one position at a time.

### HIGH-3 -- Detection lost after Cellpose finished: the position store hashed as one file

**Status: fixed and re-proven on the review branch.**

- **File:** `zmart_analysis/workflows/object_analysis/steps/detect_objects.py`, `file_sha256`
  (`Path(path).open("rb")`), called from `_write_detection_checkpoint` on `inp["image_path"]`.
- **Observed:** the tile test ran 56 s (model load and segmentation), then every field failed with
  `PermissionError: [Errno 13] Permission denied: '...\positions\overview\overview_K00_..._P000000_V00.ome.zarr'`.
  The bridge hands the step the capture's OME-Zarr position (`detection.py`, `record["zarr"]`),
  which is a directory; opening a directory as a file is "permission denied" on Windows and
  "is a directory" on Linux, so the defect is on every platform, and the container never reached it
  only because the weights download failed first.
- **Effect:** no field of a real run could ever be detected on; Step 6 was unreachable live.
- **Fix:** `file_sha256` digests a directory as every file in it in path order, each relative
  name then its bytes, so a changed chunk and a moved chunk are both a different position; a
  single file digests as before. Five tests in `test_output.py` (a store digests, repeats, changes
  with one chunk, changes with a moved chunk, and files its checkpoint under the store's name with
  that digest), all red before the fix with the same permission error. The test module also gained
  its own path setup: alone, it could not import the step before.

### MEDIUM-9 -- The cell map, drawn in the bridge's process, starved the picture server

**Status: fixed and re-proven on the review branch.**

- **File:** `application/framework/bridge.py`, `_embedding_worker` (a thread of the bridge process
  calling `embedding.umap_embedding`); the Viewer serves from a thread of the same process
  (`viewer_service.start`).
- **Observed:** with detection working, the operator path failed at `step8-ready-to-acquire`
  because `/api/viewer` reported `the viewer's current picture could not be read: timed out` --
  the service's one-second read of the Viewer's config, 13 s after Refine opened, which is when the
  page asks for the UMAP map of all 4010 cells.
- **Measured** (nine real overview stores, 4010 synthetic cells, one process): the Viewer's config
  answered in 3 ms at rest, a median of 365 ms and up to 699 ms while the warm map ran (12.2 s),
  up to 639 ms during the first map (24.9 s with umap's compile); under a real run's extra load
  the answer crossed the budget. A page that polls the Viewer during the map sees the picture
  as failing.
- **Fix:** the map is drawn in a process of its own (`embedding.in_another_process`, a spawned
  worker; `embedding.apart` is the seam) and only the points come back; a failure comes back as the
  same sentence. Each map pays umap's import and compile again, which is what "lands quietly"
  costs. Tests: four in `test_embedding.py` (another pid, the result returned, the same sentence on
  failure, the map drawn apart equals the map drawn here) and one in `test_operator_bridge.py`
  (the bridge draws through the seam and never in its own process). Re-proven: the operator path's
  Step 6, 7 and 8 records all carry `viewerError: null` after discovery.

### MEDIUM-10 -- The per-tileset ceiling belonged to the panel, not to the run

**Status: fixed and re-proven on the review branch.**

- **File:** `application/workflows/target_acquisition/steps/refine_targets/gate.js`
  (`maxN.value = "50"` on every mount); `application/framework/window/main.js` (the run state
  held the gates and the gated ids, never the ceiling they were drawn under).
- **Observed** in `step7-gated-selection.png`: after the spec stood on another step and came back,
  the box read 50 while the readout said "3 kept of 699 in gates" -- the selection on the canvas
  was drawn under a ceiling of 3, and the page showed a different rule over it. The next edit of
  any gate would have silently redrawn the selection under 50.
- **Fix:** the ceiling is run state (`gateCap`), handed to the panel with the gates
  (`ctx.cap()`, `setGates(gates, ids, cap)`), and the box shows it. The disconnect reset, which
  carried a dead `gate: null` key and left the gates standing, now clears the gates and the ceiling.
  The pretend whole-run walk lays a gate, types a ceiling of 1, leaves for the overview step and
  returns: the box must still say 1 and the selection must be the one drawn under it. Red on the
  unfixed page (`Expected "1", Received "50"`), green on the fixed one.

### Spec corrections (test code only)

- The disconnect check waited a fixed 1.5 s and read `/api/viewer`; the page fires the disconnect
  without awaiting it, and once here the viewer was still up when asked (bridge path, first run).
  It now polls the bridge until the viewer is down.
- Acquisition records were paired with gated targets by list position; the page acquires in the
  order the ceiling drew them. A record is now matched to the one gated target at its requested
  stage position, and every gated target must be taken exactly once.
- The green-ring check searched a fixed 24 px around the target; the acquired layer draws the ring
  at a radius it sizes by zoom (9 px scaled by the square root of the pixels per micrometre over
  0.03, at least 7 px), which at the close-up zoom is 36 px out (measured on the screenshot: 457
  ring pixels in the 32-40 px band, 11 sample-green pixels inside 24 px). The window now follows
  the layer's own rule plus 8 px, and the record carries the ring radius it searched.

### Environment trap, recorded so nobody pays for it twice

The analysis engine spawns each step as `conda run -n ZMART--<workflow>--<step> python ...`. Started
from a shell that merely prepends the operator env's folder to PATH, `conda run` activates the step
env by name but `python` still resolves to the operator env's interpreter (the worker reported
`CONDA_DEFAULT_ENV=ZMART--object_analysis--vision` and `sys.executable=...\zmart-microscopy\python.exe`),
and every detection fails with `No module named 'cellpose'`. conda only strips PATH entries it made
itself: a real activation (`CONDA_PREFIX`, `CONDA_DEFAULT_ENV`, `CONDA_SHLVL` set) makes the worker
run its own interpreter. This is how the first run here failed; it is not a code defect.

### Observed, not changed

- Step 6's panel at 1440 x 900: the "Run again" button wraps onto two lines and the note
  "4010 targets · Cellpose ..." runs past the panel's edge (`step6-discovered-over-overview.png`).
- Discovery of nine 1024 x 1024 fields took 7 min 14 s with Cellpose on the GPU (about 48 s per
  field including the checkpoint), the same across three runs: 449, 525, 402, 480, 512, 391,
  366, 463, 422 cells, 4010 in all, none failed.

### Test ledger, third pass

Environment: Windows 11 Pro, development PC with a CUDA GPU, the `zmart-microscopy` env
(Python 3.11.15, node 26.5.0, npm 11.17), Playwright 1.62.0 with Chromium 1234 under SwiftShader,
the step envs `ZMART--focus--main` and `ZMART--object_analysis--vision` (cellpose 4.1.1, torch
2.11.0+cu128), Smart Viewer 0.2.0 at `9ff10b04`. The bridge was started under a real conda
activation (see the environment trap above). Every run below is on the final code of the review
branch unless marked as a first run.

| Command (cwd `application` unless noted) | Result | Time | Notes |
| --- | --- | --- | --- |
| `playwright test review-live-target-arrival.spec.js` (first run, env folder on PATH only) | operator path skipped at Step 6 (`No module named 'cellpose'`); bridge path failed on the disconnect check | 3.5 min | the environment trap; the disconnect check's fixed wait |
| same, under a real activation (first run past the weights) | operator path skipped at Step 6: `PermissionError ... .ome.zarr` after 56 s in the worker; bridge path passed | 1.9 min | HIGH-3 |
| `pytest zmart_analysis/workflows/object_analysis/tests` (repo root) | 93 passed, 3 skipped; the five new tests red before the fix, green after | 3 s | |
| operator path with HIGH-3 fixed | Steps 6 and 7 passed on real pixels; failed at `step8-ready-to-acquire` on `viewerError: the viewer's current picture could not be read: timed out` | 7.9 min | MEDIUM-9 |
| starvation probe (nine real overview stores, 4010 synthetic cells, one process) | config answers: 3 ms at rest; median 365 ms, max 699 ms during the warm map (12.2 s); max 639 ms during the first map (24.9 s) | 60 s | measured, not inferred |
| `pytest application/parts/analysis/test_embedding.py application/framework/test_operator_bridge.py -k "Apart or cell_map"` (repo root) | 4 + 1 new tests red before the fix (no `apart`, map drawn in-process), green after | 30 s | |
| `playwright test framework/operator-page.spec.js -g "one walk of the whole run"` (dev server on 5175) | passed with the ceiling check; on the unfixed page: `Expected "1", Received "50"` | 1.2 min each | MEDIUM-10 |
| `npx vitest run` | 365 passed, 15 skipped | 5.6 s | |
| `npm run build` | ok; `the-built-page.spec.js` passed (built and development ink equal) | 0.7 s, 9.6 s | the committed bundle is this build |
| `pytest` on `test_zarr_positions`, `test_viewer_service`, `test_operator_bridge`, `test_detection`, `test_webapp`, `test_embedding` and `object_analysis/tests` (repo root) | 238 passed, 3 skipped | 56 s | |
| `playwright test review-live-target-arrival.spec.js` (final, both paths) | 2 passed | 8.8 min | the evidence below; two earlier full runs failed only on spec assumptions (record pairing by index, the 24 px ring window) |
| `playwright test review-live-target-arrival.spec.js -g interruption` (first run) | failed: stopped after 2 of 12, every account 2, gallery 0 | 10 min | MEDIUM-11 |
| `playwright test framework/operator-page.spec.js -g "one walk of the whole run"` (dev server on 5175) | interruption check red on the unfixed page (9 acquired, 0 pairs), green fixed | 1.4 min each | |
| `npx vitest run`, `npm run build` | 365 passed, 15 skipped; ok | 5.6 s, 0.8 s | the committed bundle is this build |
| `playwright test review-live-target-arrival.spec.js -g interruption` (final) | 1 passed: stopped after 5 of 12, every account 5; Run again, every account 12 | 25 min | discovery took about 22 of them, see below |

### What the final run holds

Operator path, production build served by the bridge, real bridge, real Smart Viewer 0.2, mock
kidney, real Cellpose on the GPU:

- Step 6: the tile test examined one field; Run discovered 449, 525, 402, 480, 512, 391, 366, 463
  and 422 cells over the nine fields (4010), none failed; every candidate inside the field that
  produced it; every id unique; canvas positions equal the bridge's stage positions minus the
  carrier origin to 1e-6; the candidate layer changes 48 584 canvas pixels; the first candidate is
  hoverable at its projection. Discovery ran from 11:22:31 to 11:29:44 UTC (7 min 13 s).
- Step 7: all 4010 drawn, none selected before a gate; a polygon gate on area x intensity keeps
  3 of 699 in gates under a ceiling of 3; a second gate on another feature cannot widen it; the
  gate and the ceiling survive a visit to the overview step; coordinates untouched.
- Step 8: the Acquire button stays disabled until the target configuration is recorded; the run
  acquires exactly the three gated cells at their stage positions (each record matched to one
  gated target, every gated target taken once); the Viewer group `target` grows one source per
  row at 139, 276 and 387 ms; the page remounts once at the first arrival and holds the instance;
  registration on the three target stores 0, 1e-11 and 0 µm; projection 0.070 px; the acquired
  ring 36.7 px out at the close-up zoom with 469 ring pixels; the acquired layer changes 193 914
  pixels; three gallery pairs served (target frames 13.7-14.9 kB, overview crops 13.4-14.8 kB),
  captions carry the ids, verdicts mark and unmark; no unexpected request failure, no browser
  error, no viewer error on any record after discovery.
- Disconnect: no targets, no plan, no picture, no acquisition row, viewer down; reconnect works.

Bridge path, same run: registration 7e-12, 7e-12 and 1e-11 µm on the three target sources;
sources per row 1, 2, 3 at 119, 253 and 340 ms; the shorter rerun leaves 2 sources per row and 2
stores on disk.

**Evidence:** `evidence/2026-09-02-smart-operator-review/on-the-operators-pc/live-target-arrival/`
holds the final run's 28 records with their screenshots and the manifest (all 28 SHA-256 values
verify). Each record lists the projections of the targets the run acts on and the count of all
candidates, since 4010 projections per record was 2.4 MB of numbers nobody reads; the
per-candidate projection check still runs on every one (`projectionError.targetsMaxPx`).
`on-the-operators-pc/first-runs/` keeps the three failing records and pictures that named the
defects: `step6-permission-denied-on-the-store`, `step8-viewer-timed-out-during-the-map` and
`step7-ceiling-box-reads-50-over-3-kept` (their candidate lists cut the same way when filed).


### Interruption and partial acquisition accounting

**How it was proven:** a third test in `review-live-target-arrival.spec.js`, on the same
production build, real bridge, real Smart Viewer 0.2, mock kidney and real Cellpose: Steps 1 to 5,
then discovery of the whole population, one gate under a ceiling of 12, the target configuration,
and the Acquire press. Once the bridge reported the first pair, the same button -- now reading
Interrupt -- was pressed. The test then reads every account at once (`targetAccounting`): the
bridge's scan (`running`, `stopped`, `done`, `of`, `error`, records), the Viewer group's sources
per channel row, the engine's sources per row, the stores under `positions/target`, the canvas's
acquired marks, the gallery's pairs and captions, the button, the sentence beside it, and the run
state (`done`, `ran`, the note). Then Run again, and the same reading.

**What it found -- MEDIUM-11, the gallery empty after a stopped run. Status: fixed and re-proven.**

- **File:** `application/framework/window/main.js`, the target scan's completion: the gallery
  was rebuilt in `finish()` only, and a run stopped by hand ends in `stoppedShort()` instead.
- **Observed** (first live run, `interruption-run1`): stopped after 2 of 12; the bridge said
  stopped with 2 records, the Viewer 2 sources per row, 2 stores on disk, the canvas 2 acquired
  cells with rings, the sentence "stopped by hand -- 2 of 12 pairs acquired" -- and the gallery
  showed 0 pairs. An operator who stops a run to look at what it took has nothing to look at.
- **Fix:** the gallery is rebuilt where the acquired set is settled, stopped or not; the rebuild
  in `finish()` went, since that was its only caller. The pretend whole-run walk now interrupts
  its own acquisition after the first pair and expects one gallery pair per acquired target: red
  on the unfixed page (9 acquired, 0 pairs), green on the fixed one.

**What the final run holds** (`on-the-operators-pc/interruption/`, 7.0 min on the final code; an
earlier run of 25 min, with discovery on the CPU -- see MEDIUM-14 -- held the same accounts at
5 of 12): the Interrupt was pressed while the bridge reported 3 done; the field in hand
completed and the run stopped at 4 of 12 -- between two fields, as the rule says. Every account
then read 4: `scan = {running: false, stopped: true, done: 4, of: 12, error: null, records: 4}`,
Viewer `[4, 4, 4]`, engine `[4, 4, 4]`, 4 stores on disk, 4 acquired cells on the canvas (each
record taken at exactly one gated target, and those four are the acquired ones), 4 gallery pairs
with their ids in the captions, the button "Run again", the note and the hint both
"stopped by hand -- 4 of 12 pairs acquired", the step in `ran` and not in `done`. Run again then
read 12 everywhere: `scan = {running: false, stopped: false, done: 12, of: 12, error: null,
records: 12}`, Viewer `[12, 12, 12]`, engine `[12, 12, 12]`, 12 stores on disk (the four of the
interrupted run replaced under their own names), 12 acquired cells -- every gated target taken
once -- 12 gallery pairs, "12 pairs acquired", the step done. No unexpected request failure, no
browser error and no viewer error on either record; Disconnect and reconnect as before.

Two things about the pretend walk's version of the same press: the pretend run redraws the action
bar every animation frame, so a Playwright click that waits for the button to hold still waits
until the run is over and then presses Run again -- the walk dispatches the press on the button
as it stands. With the real bridge the page redraws once per 300 ms poll and the ordinary click
landed. And the discovery in this run took three times longer than the earlier three (about
22 min against 7); the card reported no thermal or power slowdown, P0 at 1830 MHz and 58 C, and
the cause was not established.

**Still unproven after the third pass:** everything above stands on the mock kidney, not on a
real sample.

### The operator's own test of the mock: three more findings

The operator opened the page in its window on this PC (`zmart-interface.py --built`) and tested
the mock by hand. Two asks came out of it -- a tile test and the whole-population run must both be
interruptable, and no password should be needed -- and proving the first exposed that the brake
the page already had did not stop anything.

#### MEDIUM-12 -- The tile test had no brake

**Status: fixed and re-proven on the review branch.**

- **Files:** `application/workflows/target_acquisition/steps/discover_targets/detection.js` (the
  press ran the test and waited); `application/framework/window/main.js` (the panel was handed
  `tryOn` and no brake, and a test the backend reported stopped was read as "not examined", a
  failure sentence).
- **Observed:** the step's Run over all fields has had Interrupt since the review began, but
  "Test this tile" went through the same bridge route with no press on the page to reach it: a
  field takes about a minute on this machine, the first one more, and a test once pressed could
  only be waited out.
- **Fix:** while a field is being tested the same press reads Interrupt, then "stopping…" once
  pressed, and calls the brake the Run uses (`stopTargets`); when the backend answers stopped, the
  readout says "stopped by hand -- position N not examined" and the press is itself again. The
  pretend backend's tile test now takes 1.2 s and honours the brake meanwhile, so the walk can
  reach it: the whole-run walk stops one tile test by hand before taking one, red before the fix
  (`Expected "Interrupt", Received "Test this tile"`), green after.

#### MEDIUM-13 -- The brake waited for the field and left the worker running

**Status: fixed and re-proven on the review branch, in the analysis engine.**

- **Files:** `zmart_analysis/engine/_pipeline.py` (`Engine.shutdown` joined its threads before it
  touched the workers), `zmart_analysis/engine/_worker.py` (`Worker.shutdown` sent a sentinel the
  busy worker never reads, waited five seconds, then terminated the `conda run` wrapper -- whose
  Python child kept segmenting -- and a worker put down before its spawn forgot it and spawned),
  `application/parts/analysis/warm.py` (`Analysis.shutdown` asked for the waiting kind).
- **Observed, on the real bridge:** the first interrupted tile test came back with the field's
  449 objects. Measured outside the browser on a real overview store: a stop pressed one second
  into a test blocked for 19 s and then handed back 447 objects; and the ten idle Python pairs
  found on this machine were exactly such wrappers and workers, left by earlier sessions. A stop
  that landed while `conda run` was still activating left the whole chain standing --
  `conda.exe`, its interpreter, the activation shell and the worker -- under the bridge's pid.
- **Fix:** `Engine.shutdown(wait=False)` puts the workers down first, busy ones included, and
  cancels what was queued; `Worker.shutdown(now=True)` kills the process tree at once
  (`taskkill /T` on Windows, the wrapper's own session on POSIX) without the sentinel or the
  wait, and a worker put down stays down: a spawn under way is refused before, right after, and
  once the worker is on the line. The warm door's shutdown asks for that kind. A `run` in flight
  raises, which is what the hand wanted; nothing is left behind. Measured after the fix: a press
  one second in stops in 2.2 s, a press nine seconds in stops in 1.8 s, the run raises, and the
  Python process count is back where it was ten seconds later, both times.
- **Tests:** five in `test_engine.py` (`TestTheBrake`): a busy worker put down at once and its
  caller released with `WorkerCrashedError`; the whole tree under a wrapper; an engine shut down
  without waiting stops its running step in under 3 s; a stop mid-activation leaves nothing; a
  stop before the spawn leaves nothing (red without the put-down check: the job ran and the
  caller was never released). The polite shutdown keeps its respawn contract. The warm door's
  stub records that it was asked not to wait.
- **A trap for the next reader:** an interrupted tile test on the real bridge is the same thing
  as a stopped field: the worker dies, and the next test pays the worker's spawn and the model
  load again -- about a minute.

#### MEDIUM-14 -- Detection fell back to the CPU without a word, and stayed there

**Status: fixed and re-proven on the review branch.** Found while proving MEDIUM-13 on the real
bridge: the run after the fixed brake segmented at ten minutes a field instead of fifty seconds.

- **Files:** `zmart_analysis/workflows/object_analysis/steps/detect_objects.py`
  (`_get_cellpose_model` kept whatever model it got first, for the worker's whole life);
  `application/parts/microscope/detection.py` and `application/framework/bridge.py` (the device the
  step reported never left the pipeline result); the page (nothing to say it with).
- **Measured:** the card reported 2.5 GB free and 2 % memory activity while the vision worker had
  burnt 40 minutes of CPU on its third field; `torch.cuda.is_available()` was true from the same
  environment. The step tries the devices in order and caches the first model that loads: a tile
  test stopped by hand puts its worker down, the next test starts a second later while the card
  still holds the dead worker's memory, the CUDA model fails to load, the CPU one loads and is
  cached, and every field of the session after that runs on the CPU. Nothing on the page said so;
  the run looked like a slow run. The 22-minute discovery in the interruption pass (section 11)
  was most likely the same thing.
- **Fix, in three places:** a cached CPU model is offered the accelerator again on the next call
  and replaced when it loads, and once on the card it stays there (`test_segmentation.py`: cuda
  refused once, then taken, then kept -- three model loads for three fields, not four); each
  field's answer carries the device it was segmented on, from the step's own record through
  `detection.through` and the bridge's field entries (`test_detection.py`,
  `test_operator_bridge.py`); the tile readout says "N objects at position i · on the GPU" or
  "· on the CPU", the discovery note says "· on the CPU" when any field had to be, and the pretend
  backend's fields say "on pretend". The fallback itself stays: a machine without a card must
  still discover, slowly and saying so.

#### No password needed (operator's decision)

MEDIUM-8 stands as recorded -- the page ships no password -- and the gate that came with it is
gone: Connect is ready as soon as an instrument is chosen, the sentence "a password is needed to
open the session" is removed, and the field stays empty and optional. Whether an instrument wants
one is its own business when the session is opened. `session-card.js`; the pretend test now
expects an enabled Connect and no such sentence (5 connect tests pass).

#### The display settings as a tab, and the column that folds away (operator's asks)

Two more asks from the window, built the same afternoon.

- **Display settings a tab away from the step.** The picture's own controls -- its acquisitions,
  channel rows, windows and Auto -- used to stand as a strip between the canvas and the step's
  channel. They now stand *in* the channel's column, and the row over that column carries two
  real tabs: the step's name and "Display settings". Pressing one shows it there; the other is a
  press away. One column, one width, so the canvas does not move by a pixel when the choice
  changes -- the review spec measures the canvas's box before and after both presses at Step 6
  and requires equality (`step6-display-settings-tab`). The tab is offered exactly while there is
  something to show under it: the settings become a thing with the first picture, the focus stack
  of Step 4, and go with the picture at Disconnect (the operator's decision, after seeing a tab
  that stood empty over three steps); a JPEG copy has no display settings, and the pretend
  backend therefore shows the step's name alone, as before. Walking to a step brings that step's
  channel back, so display settings left showing on one step do not follow the operator to the
  next; a spec that pressed the panel presses the step's tab again before the step's own button
  (`showDisplaySettings` / `showTheChannel` in `live-bridge.js`). `parts/canvas/panel.js` (the second column),
  `parts/canvas/viewer-panel.js` (`into`: fills the column, no fold of its own),
  `watching-the-run.js` (mounts there and says when the settings came or went),
  `main.js` (`sideView`, the two tabs, the switch).
- **The column folds away to the right.** A 14px strip on the column's edge -- the same strip the
  viewer's panel folded with -- puts the whole column away with one press and gives the canvas the
  room; the strip stays as the way back, and the column returns the width it had, the canvas
  with it. Folded, the column has no heading. The pretend suite presses it on the Connect step:
  the column and its divider go, the canvas grows by more than 100 px, the heading goes; pressed
  again, everything is back and the canvas is the width it was
  (`the channel folds away to the right and comes back`). `main.js` (`sideFolded`, the fold on
  the same edge as the divider), `panel.js`, `style.css`.

#### MEDIUM-15 -- A run written beside the page lost its stores to a denied rename

**Status: fixed and re-proven on the review branch.** Found by the operator in the window: the
overview was on the canvas, the Display settings tab said no picture had come, and the Viewer
behind the window held no acquisition at all.

- **Files:** `application/parts/storage/zarr_positions.py` (one attempt at each store, and a
  refused rename was the store's end); `application/vite.config.js` (the development server
  watched everything under the page, run output included); the mock driver's default output
  root, `mock-output` under the working directory, which the interface's own bridge (started in
  `application/`) resolves to `application/mock-output`.
- **Observed:** every record of the window's run carried
  `zarr_error: [WinError 5] Access is denied: '...\.writing-overview\...\zarr.<uuid>.partial' ->
  '...\zarr.json'` instead of a store; `/api/viewer` answered `acquisitions: []`; the page fell
  back to the JPEG copies, which bring no display settings. Reproduced with a bridge run from a
  script: written under `application/mock-output` with the development server up, one position
  in three and the focus stack lost; written under the temp folder, nothing lost. Windows denies
  a rename while another process holds the file, and the watcher opened each store's files as
  they appeared. A scanner on a microscope PC does the same (Kaspersky has suspended a run on
  this machine before).
- **Fix:** the store is written up to three times, each in a fresh staging folder, with a short
  wait between; a rename denied for good raises as itself. Two tests in `test_zarr_positions.py`
  (denied once: the store is published and nothing else stands in the folder; denied every time:
  the same error). And the development server no longer watches `mock-output`, so it never holds
  a run's files at all. Re-proven with the same script: the run under `application/mock-output`
  with the server up lost nothing, and the Viewer listed both acquisitions.

#### MEDIUM-16 -- The test after a stopped one could be handed the analysis on its way out

**Status: fixed and re-proven on the review branch.** Found by the review spec once the tile
test could be stopped: the test pressed right after a stopped one answered
"Engine has been shut down" instead of examining its field.

- **File:** `application/parts/analysis/warm.py`, `close()`: it put the analysis down first and
  emptied the door after. The brake puts the worker down at once, the stopped run reports
  itself done at once, the page starts the next test at once -- and `the_analysis()` in that
  test could still be handed the analysis whose engine was being shut down. A script that
  waited a moment between the two never saw it; the page does not wait.
- **Fix:** the door is emptied first, the old analysis put down after, so whoever asks during
  the shutdown gets a fresh one. `test_warm.py` holds it with an engine whose shutdown blocks
  until released: the analysis asked for meanwhile is a different object with a different
  engine (red before: the same one).

Two more spec matters from the same afternoon: `step-five-kidney-evidence.spec.js` looked for
the Viewer's `/api/measure` route with `rg`, which this machine does not carry, and could not
load at all -- it reads the file now. And running any bridge of one's own beside a spec's bridge
is not a thing to do on this machine: two processes spawning `conda run` at once trip the
activation-file race the engine documents, and the interruption test lost its whole discovery
to a probe of mine running alongside. Verification runs alone.

#### Ledger and evidence for MEDIUM-12 to MEDIUM-14 and the password

| Command (cwd `application` unless noted) | Result | Time | Notes |
| --- | --- | --- | --- |
| `playwright test framework/operator-page.spec.js -g "one walk of the whole run"` (dev server on 5175) | tile-test Interrupt check: `Expected "Interrupt", Received "Test this tile"` before the fix; passed after | 1.3 min each | MEDIUM-12 |
| operator path, first live run with the brake | the interrupted tile test came back with 449 objects | 2.9 min (contaminated: a probe on the same card and a hand-killed tree) | MEDIUM-13 found |
| brake probe on a real overview store (repo root, `probe_stop.py`) before the fix | stop at +1 s: `close()` 19.0 s, run returned 447 objects after 18.8 s | 60 s | measured |
| `pytest zmart_analysis/engine/test_engine.py -k TheBrake` (repo root) | 3 red (5.0 s shutdown, wrapper alive, tree alive), then green; the two spawn-window tests red without the put-down check (the caller never released), green with it | 8 s | MEDIUM-13 |
| brake probe after the fix | stop at +1 s: `close()` 2.2 s, run raised after 3.4 s; stop at +9 s: `close()` 1.8 s, raised after 10.8 s; Python process count unchanged ten seconds later, both times | 60 s | |
| worker spawned right after a tree kill (repo root) | connects in 2.1 s and answers | 10 s | no conda temp-file trap |
| `pytest zmart_analysis/engine application/parts/analysis/test_warm.py application/framework/test_operator_bridge.py` (repo root, real activation) | 169 passed | 83 s | the polite shutdown keeps its respawn contract |
| operator path with the fixed brake, first clean attempt | Steps 1-5 passed, the interrupted tile test came back stopped with nothing examined, then discovery at ten minutes a field on the CPU -- killed after 3 of 9 | 35 min | MEDIUM-14 found: 2.5 GB free on the card, 2 % memory activity, 40 min of CPU in the worker |
| `pytest zmart_analysis/workflows/object_analysis/tests/test_segmentation.py -k offered_the_gpu_again` (repo root) | red, then green | 0.3 s | MEDIUM-14 |
| `pytest` on `test_detection`, `test_operator_bridge`, `object_analysis/tests`, `zmart_analysis/engine`, `parts/analysis` (repo root, real activation) | 291 passed, 3 skipped | 123 s | |
| `playwright test framework/operator-page.spec.js -g "password|session|check|connecting"` (5175) | 5 passed | 22 s | no password needed |
| `npx vitest run`, `npm run build` | 365 passed, 15 skipped; ok | 5.6 s, 0.8 s | |
| `playwright test review-live-target-arrival.spec.js` (all three, final code before the device lookup fix) | 3 passed | 16.2 min | discovery on the card again: the operator path in 8.6 min |

**What the final runs hold** (`on-the-operators-pc/live-target-arrival/`, the two paths, 8.8 min;
`on-the-operators-pc/interruption/`, the interruption test, 7.0 min: stopped by hand after 4 of 12,
every account 4, Run again every account 12; all records with verified hashes):

- Connect opened with the password field empty and nothing on the page saying one was needed.
- The tile test stopped by hand: the press read Interrupt, the bridge answered
  `{running: false, stopped: true, error: null, fields: [], failed: []}` and logged
  "was put down", the readout said the field was not examined, and the press was ready again.
  The real tile test that followed examined its field (449 objects, on the GPU), and Run
  discovered 449, 525, 402, 480, 512, 391, 366, 463 and 422 cells over the nine fields with
  none failed, every field on the card (`device: cuda`), from 14:27:59 to 14:35:12 UTC --
  7 min 13 s, the pace of the first passes, with the readout saying "· on the GPU".
- Step 7 and Step 8 as before: 3 of 699 kept under a ceiling of 3; three targets acquired at
  their positions with registration 7e-12, 0 and 7e-12 µm, the Viewer growing 1, 2, 3 sources
  per row at 170, 306 and 464 ms, 556 ring pixels at 36.7 px, three gallery pairs, a verdict;
  the bridge path with registration 7e-12, 7e-12 and 1e-11 µm and the shorter rerun at 2 sources
  per row and 2 stores; Disconnect leaves nothing open. No unexpected request failure, browser
  error or viewer error on any record.

## 12. The operator's list after testing the mock -- queued, not done

Raised by the operator on 2026-09-02 while testing the mock in the window on this PC, with two
screenshots (Step 8 with 22 pairs acquired, Step 6 mid tile test). Recorded here as asked; none of
it is built yet, and the order below is the order it was said in.

**Step 8, Acquire Targets**

1. **The mock's target frame is far too large.** An acquired target should be a smaller field of
   view than the overview field, with a smaller pixel size in it, so that it reads as the
   high-resolution frame it stands for. Today the mock cuts a frame as wide as the overview's.
2. **The target pictures should wear the overview's image settings**: the same channel windows
   and colours, so a target frame over the overview looks like the same sample seen closer,
   not a differently coloured picture.
3. **The eye on the target group did not work.** Hiding the overview group hid it; hiding the
   target group did not. (The review's panel checks toggled groups through the panel's own
   handle and passed; the press on the group row in the built page is what the operator used.)
   Also: the operator wants the group named `targets`, not `target` -- MEDIUM-5 chose `target`
   to match the notebook flow and the tests; to be decided with the operator.
4. **Not every pair listed under Acquire Targets.** Instead, a list of targets like the list of
   focus points on Step 4: pressing a target on the canvas highlights and selects it in the list,
   and only that one's low-resolution crop and high-resolution frame appear below -- one pair on
   show, never all of them.

**Step 6, Discover Targets**

5. **The example field in the panel should wear the canvas's image settings and colours** --
   today the tile in the Discover panel is coloured and windowed on its own, unlike the same
   field on the canvas beside it.
