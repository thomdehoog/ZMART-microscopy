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

The document `docs/reviews/2026-09-01-why-the-acquired-overview-never-appeared.md` named in the
review brief does not exist on this branch or on any fetched branch; the plan cites it as the
origin of the flat-z and stale-source gates. The other three named documents and both evidence
directories were read in full.

## 1. Executive verdict

**Conditional pass.** Steps 1 to 5 work end to end on the production build served by the real
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

- The tile test through the real bridge failed with
  `Could not initialize CellposeModel on any device: cpu: <urlopen error Tunnel connection failed:
  403 Forbidden>` (weights from `huggingface.co`, blocked by egress policy). Evidence:
  `step6-discovery-blocked.json/png`. Everything about candidate placement, gating and acquisition
  rings on the canvas is therefore proven only by `framework/operator-page.spec.js` with
  `?backend=pretend`, which passed here (32 of 33; see LOW-3).

### MEDIUM-2 — A tile test that fails shows a page TypeError instead of the analysis's reason

- **File:** `application/framework/window/main.js:1124` (head).
- **Observed:** the panel readout said `Cannot read properties of undefined (reading 'cells')`;
  the bridge had reported the field under `failed` with the pipeline's sentence.
- **Fix made:** `tryOn` now throws the bridge's `why` when no field came back; the new spec asserts
  the readout contains it.

### MEDIUM-2b — A position store is published before its coarser pyramid levels are written

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

- **File:** `application/workflows/target_acquisition/shared/stage.js:734`
  (`openTheGroundThatHasBeenScanned` opens see-through windows for `run.plan` fields only).
- **Observed:** in `bridge-step8-complete-overview-and-targets.png` the part of a target frame
  that lies outside its overview field is covered by the pale ground at the default fade; the
  target-only capture with fade 0 shows the same frame textured. A target acquired at the edge of
  the plan is only visible after the operator fades the layers.
- **Recommendation:** open a see-through window for each acquired target frame as well (the run
  knows `targetFrameUm` and the acquired positions).

### MEDIUM-5 — The live target group is `targets`; every panel test and the panel-UX evidence use `target`

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

- `application/framework/bridge.py:772` and `:795` import `viz_studio.backend.jpeg_tiles` for the
  focus slice previews and the JPEG view tiles; `viz_studio/backend/REFERENCE_ONLY.md` says the tree
  must not be imported. The Viewer-provenance guard covers only `viewer_service.py`. Package G's
  "reference-only" claim is overstated for the JPEG fallback and the Step 4 preview.

### MEDIUM-7 — Panel-UX "coordinate safety" evidence is an identity-matrix fixture

- `application/viewer-panel-ux-evidence.spec.js:135` mounts the panel on a fake viewer whose five
  sources carry identity matrices; the JSON claim "all five immutable identity matrices" cannot
  show that real transforms are untouched. (The Step 5 records and this review's Step 8 records
  compare real per-source matrices before and after visibility actions: equal.)

### MEDIUM-8 — The production build ships a default password

- `application/parts/microscope/instruments.js:63` sets `password: "demo"` with a comment that a
  real build must ship it empty. Connect is enabled without typing anything; the gate is only
  proved once the field is emptied (this review's Step 1 record notes
  `passwordPrefilledByThePage: true`).

### LOW-1 — Step 5 evidence records carry no PNG dimensions or SHA-256
The eight `2026-09-01-smart-viewer-step-five/*.json` records omit the artifact block the panel-UX
records carry; the review brief requires it.

### LOW-2 — Failing Python tests on the branch
`application/workflows/target_acquisition/webapp/test_webapp.py` (10 tests) import the stale path
`workflow.webapp`; `application/parts/microscope/test_detection.py::test_a_capture_with_a_position_store_is_read_from_it`
builds Windows paths and fails on Linux. 301 of 312 focused tests pass. Not production defects.

### LOW-3 — Timing-fragile browser tests
`framework/operator-page.spec.js:447` ("the canvas is always on the stage") keeps the 30 s default
test timeout around a 60 s wait and timed out twice here; `the-operator-walk.spec.js:179` expects
the focus slice preview while the run is still measuring, but the preview follows the selected
point, which the run advances, so it fails deterministically here (three runs). The preview does
appear once the run ends (diagnostic walk recorded 61 slices per point).

### LOW-4 — Committed bundle differs from a fresh build
`framework/window/static/chunk_worker.bundle-CycDtxtB.js` is committed; a fresh `npm run build`
produces `…-VL1EZiOw.js`. `the-built-page.spec.js` passed against the rebuilt bundle.

### LOW-5 — After Disconnect the page reopens a picture on the JPEG fallback address
`watching-the-run.js:706` keeps polling; with the bridge session closed `viewerSources` is null
and `pictures("overview")` is still an address, so a JPEG engine opens on an empty view. No
acquisition source survives (checked), so no stale pixels; but the picture object is not null.

## 3. Gate table, Steps 1–8

| Step | Gate | Result | Proven with |
| --- | --- | --- | --- |
| 1 Connect | instruments and APIs from backend; password gate; checks settle; failures visible; travel and position from driver; disconnect resets; reconnect | **passed** (password gate only after emptying the prefilled field: MEDIUM-8) | production build + real bridge (`step1-connected`, `step1-reconnected`) |
| 2 Carrier | slide and plate presets; carrier-local geometry; origin centred in travel; no origin compensation on sources; edits invalidate plan | **passed** | production build (`step2-carrier`), operator-page pretend suite (carrier tests), source review of `stage.js` |
| 3 Scan area | optics recorded from the microscope; grid; counts match carrier and frame; every position on screen; plan locked after scan | **passed** (grid/fields/regions/polygon/clear behaviours proven with pretend backend) | `step3-plan`, operator-page pretend suite |
| 4 Focus | focussing configuration recorded; points measured through the analysis; traces and stack; fixed/mapped behaviour; focus Z provenance only | **passed** (slice-preview timing test LOW-3) | `step4-focus-map`, `the-map-fills-in`, `a-moved-point-has-no-curve`, bridge probe |
| 5 Overview | 0/3/6/9; Run button; nine ROIs examined and textured; three rows × nine sources; growth without remount; Fit preserved; overview-only; close-up; projection < 1 px; real `/api/measure`; no unexpected failures | **failed on head** (HIGH-1 misplacement, HIGH-2 broken spec) → **passed on the fixed review branch** | real bridge + Viewer 0.2 + mock kidney (`step-five-fixed/*`, `view-preservation.json`, `step5-overview-complete`) |
| 6 Discover | preview is the selected field; settings; test vs all; ids and positions; candidates on canvas; layer changes canvas; hoverable; failures honest | **blocked live** (MEDIUM-1); canvas behaviour **passed with pretend backend**; failure reporting **failed** then fixed (MEDIUM-2) | operator-page pretend walk; `step6-discovery-blocked` |
| 7 Refine | candidates before gate; no implicit gate; polygon gate; intersection; feedback; counts agree; gate survives navigation; coordinates unchanged | **unproven live**; **passed with pretend backend** | operator-page pretend walk; source review of `gating.js` (no gates → empty set) |
| 8 Acquire | configuration before acquisition; button gating; one conversion; focus Z provenance; positions equal; rings/frames; gallery; verdicts; partial runs | canvas/gallery **passed with pretend backend**; interruption **unproven**; source model **passed live** (remount at first arrival is by design; stale rerun sources MEDIUM-3) | `bridge-step8-*` records |

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
| Engine | per-source bounds from `layersForMeasurement` | head: first source exact, others −2 µm (HIGH-1); fixed: all overview sources exact |
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
- **Targets:** the first target position opens `positions/targets`; Smart Viewer lists a third
  acquisition `targets` with three channel rows; the page reopens once (a genuinely new
  acquisition shape) and then holds the instance. All three target sources landed within one page
  poll of each other, so growth 1 → 2 → 3 on the target group was not observed separately;
  the arrival log records the sequence. A shorter rerun leaves stale sources (MEDIUM-3).
- **Disconnect:** the viewer service stops, `/api/viewer` reports not running, no acquisition
  source survives on the page (LOW-5 for the JPEG fallback picture).

## 8. What was proven with what

- **Pretend backend only:** Steps 6–8 canvas behaviour (candidates inside their fields, no
  implicit gate, polygon gating, selected/acquired marks, hoverable targets, gallery verdicts),
  the panel-UX screenshots' engine state.
- **Real bridge, real analysis workers, mock kidney (no Viewer needed):** focus map measurement,
  slice previews, six-well per-field texture (54/54), the JPEG view path.
- **Real bridge + real Smart Viewer 0.2 + mock kidney:** Steps 1–5 end to end on the production
  build; 0/3/6/9 deterministic and Run-button evidence (on the fixed adapter); Fit preservation;
  overview-only; kidney close-up; histogram and Auto through `/api/measure`; the Step 8 source
  model with bridge-published target positions (separate `targets` group, per-position sources,
  visibility survival, Fit preservation, independent group eyes, matrices unchanged, Z anchors).
- **Unproven:** Steps 6–7 on real pixels; the Step 8 button path with real discovered targets;
  target source growth one position at a time (all three landed within one page poll);
  interruption and partial acquisition accounting.

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
