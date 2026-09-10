# Microscope operator issues observed on 2026-09-10

The installed named-views operator had missing previews, incomplete-looking target rendering, and slow store preparation and viewer updates. The original observations and diagnostic findings are preserved below. The confirmed preview dependency was repaired on 2026-09-11; see the repair status at the end. The publication, responsiveness and remaining rendering investigations are still open. Diagnosis did not acquire images or change microscope settings.

## Installation under observation

- Operator branch: `codex/operator-named-views-simulator`.
- Operator revision: `53667bbecfa1c87160e19fcbce736e0225b8f470`.
- Viewer: `0.5.0.dev0`, built from `90e0350777a2852ee19dee7b5fe48846aa5bcf14` in `thomdehoog/ZMART-viewer`.
- Conda environment: `C:\ProgramData\MinicondaZMB\envs\zmart-operator-named-views`.
- Launch command: `python application/zmart-interface.py --built`, without simulator pixels.
- Installation instructions: [microscope installation handover](MICROSCOPE_INSTALL_HANDOVER_2026-09-10.md).

Both frontend builds and dependency checks passed. Preflight results were 525 unit tests passed, 15 skipped, and all four named-view browser tests passed with generated image fixtures. These checks did not establish correct preview behavior or performance during microscope use.

## Open issues

### 1. Focusing image previews are black

In step 4, Focus strategy, four black image squares appear at the focus points. Focus coordinates, Z results, and the focus plot are visible. The screenshot shows the focussing acquisition in Top view at Plane 1 of 201.

Expected: focusing images should be inspectable at the selected plane, with empty/out-of-range states clearly distinguished from a failed preview.

### 2. Object detection sidebar preview is black

In step 6, Detect objects, the Configure object detection preview on the right is black, although the main overview displays image data. Fast detection is selected, with tile 4 of 4 outlined on the canvas and Grey preview mode shown.

Expected: the sidebar displays the selected tile for configuring and testing detection.

### 3. Overview / Target scan sidebar comparison is black

In step 9, Acquire Targets, both halves of the sidebar comparison are black while image data is visible on the main canvas. The screenshot shows MIP mode, targets selected, and acquisition progress at 9 of 20.

Expected: the comparison displays the corresponding overview and available target image, or clearly reports pending data.

### 4. Large dark blocks cover the target image area

A later screenshot shows Top view at Plane 10 of 21 with target 9 selected (`overview_r001_c000_obj02101`, 21.43, 21.09 mm). Large dark rectangles cover the target area while surrounding image data remains visible. The sidebar comparison is also black.

The viewer reports `targets: 9/20 stores available (preparing)`. Rerun current, Rerun all, and Make it look good controls are visible. This records the display state; it does not establish whether acquisition/publication has finished or whether the dark blocks represent missing, stale, out-of-range, or genuinely dark pixels.

### 5. Store generation and delivery to the viewer are slow

The user reports that generating stores and pushing them to the viewer is generally slow. No timings or confirmed bottlenecks have been collected.

### 6. Possible cache update or loading problem

The user suspects that cache updating or loading is also faulty. The exact mechanism and its relationship to slow publication, black previews, and dark target blocks remain unconfirmed.

## Hypotheses and investigation work

The user suspects the right-side previews may read different data from the main canvas, explaining why those previews remain black. Treat this as a hypothesis to test, not an established cause.

- Compare sidebar and main-canvas source paths, acquisition/target selection, channels, planes/projections, and data revisions across focusing, detection, and target acquisition.
- Inspect failed or empty preview requests and distinguish pending data from valid dark pixels or an out-of-range plane.
- Trace store publication and viewer availability, including cache refresh/invalidation and subsequent reads.
- Measure store creation, publication, viewer loading, preview generation, and time to visible pixels separately.

The general requirement is to improve overall performance and responsiveness across store generation, viewer delivery, caching, previews, and rendering. Establish timings and verify improvements with the same recorded dataset. Schedule investigation separately from ongoing acquisition.

## Screenshot evidence

Screenshots were supplied in the session and remain on the microscope workstation under `C:\Users\t.de\Desktop`. They are not embedded in this Markdown report.

| Observation | Local screenshot filename |
| --- | --- |
| Focusing previews | `{4AF82A90-C0B0-4210-9AD4-30888A623A35}.png` |
| Detection preview | `{624F7086-BA8D-41E5-9B60-D37FB931BF71}.png` |
| Acquisition sidebar comparison | `{015E93D6-81F1-4FE2-BF74-92FA9C5476C3}.png` |
| Dark target blocks / preparing stores | `{37A273BD-1480-476A-A0F6-EA5D31CC55E1}.png` |

## Follow-up diagnosis on the running installation

Data inspected: `E:\Experiments\ZMART-microscopy\target-acquisition_80d754`. Evidence came from read-only status/preview HTTP requests, existing OME-Zarr pixel reads, source inspection, two external thread snapshots, and a ten-second sampling profile of the running operator. A separate existing analysis environment was used to verify preview generation without installing anything into the running operator environment.

### Confirmed: the operator environment lacks the preview reader dependency

Both tested displayed-preview routes returned HTTP 500 with `{"error": "No module named 'ngio'"}`: an overview tile and a captured target tile. The log also contains `no slice copies for a focus point: No module named 'ngio'` for all four focus points.

The call paths are:

- Detection and target comparison: `application/framework/bridge.py::_a_picture_as_displayed` -> `application/parts/storage/jpeg_tiles.py::picture_as_displayed` -> `zmart_analysis/workflows/object_analysis/steps/detect_objects.py::load_plane` -> `_open_position` -> `import ngio`.
- Focus slice previews: `bridge.py::_the_slice_copies_of` -> `jpeg_tiles.py::make_slice_copies` -> the same canonical reader. The exception is caught and an empty preview list is returned.

These paths run inside the **operator process**. Having ngio in the focus/detection worker environments does not satisfy that dependency. The installed operator's environment specification/requirements do not declare this new runtime requirement, so pip check passed despite the missing module. The installation preflight checked the analysis workers but did not exercise these live preview routes in the operator environment.

The main viewer uses its own Zarr rendering path and therefore can display pixels while the sidebar reader fails. Both paths refer to the canonical position stores; a different underlying image dataset is not required to explain these failures.

Control check: the same `picture_as_displayed` code successfully generated nonblack overview and target JPEGs using the existing focus worker environment with ngio 1.1.0. The overview JPEG was 666,618 bytes and the target JPEG 605,266 bytes; both contained nonzero pixels. This confirms a dependency/environment failure for the tested previews, rather than absent source pixels.

**Fix direction:** declare and install the canonical reader's dependencies in the operator environment, validate real preview endpoints there, regenerate missing focus previews from existing stores, and show preview request failures in the UI instead of leaving an unexplained black panel. Resolve dependencies as a complete compatible set; do not assume ngio alone is the only transitive requirement.

### Focusing screenshot: valid dark planes and missing previews are separate

All four recorded focus stores have shape `(1, 1, 201, 64, 64)`. Their first and last planes are genuinely zero. Plane index 100 has signal: maxima of 10-15 counts and 2,092-2,683 nonzero pixels depending on the point.

The original screenshot shows Top, Plane 1 of 201. Black focus squares at that particular plane therefore do **not** by themselves establish a canvas rendering fault. The missing generated focus previews are independently confirmed by the ngio errors. Plane selection/focus-result navigation should be checked after restoring the preview path; this investigation did not establish that the UI automatically selected the intended focal plane.

### Confirmed: acquisition finishes while publication continues for minutes

The scan API reports `running=false`, `done=20`, `of=20`, `error=null`, and the capture log includes site 20/20. During diagnosis, publication remained at 9/20 and later advanced to 16/20 without a restart. The servers continued answering requests. This is a long publication backlog, not evidence of a deadlock or a capture stuck on target 9.

At 23:51:21 local time, all 20 captures were complete; 16 were fully published and the Top view had a pending update containing 20 stores.

Actual publication timestamps for the 16-store update:

| View | Revision | Commit time, local |
| --- | --- | --- |
| Top | 6 | 23:43:53 |
| Slice | 6 | 23:48:43 |
| MIP | 6 | 23:48:49 |

Top-to-Slice completion alone took approximately 4 minutes 49 seconds. This is directly measured publication latency, not an estimate of network transfer speed.

Thread snapshots located the background publisher in `viewer_service.py::_ask`, waiting for `/api/announce`. The viewer request was inside `views.py::_publish` -> `published.py::commit` -> `building.py::_replace_one_piece` -> recursive `compose.py::_reduce_composed_slab` / `_read_from` -> Zarr reads. Later profiling also observed `_rehalve_one_level`. CPU time increased and publication eventually advanced, establishing continued work.

This run has baking enabled. Its target aggregate has 14 pyramid levels and a sparse full-stage shape of `(1, 2, 21, 1386172, 2157228)` for Top; Slice had 26 absolute-Z planes. This is a logical sparse extent, **not** a fully allocated array of that size. Publication performs substantial pyramid composition/reduction before acknowledging each update; the observed `_built_wherever` path builds slabs in the current process. The expensive work is inside the viewer's publication computation, not merely copying finished stores to a remote viewer.

Capture-side timing logs average 22.705 seconds per target, including 18.248 seconds capturing and 2.662 seconds saving. Their total is 454.093 seconds across 20 targets. Those measurements do not include every subsequent store-conversion/publication stage, so they must not be used as complete end-to-end timings. Separate instrumentation of canonical-store generation is still needed to quantify its contribution.

**Fix direction:** keep usable committed images available while preparing updates; separate interactive availability from coarse pyramid baking; reduce repeated composition/read work and measure cache reuse; report actual publication phase/progress and timings. Coalescing already exists, so adding more retries or repeated announcements is not a solution. The publication request deliberately has no timeout because abandoning an HTTP wait does not cancel its server-side write.

### Confirmed: revision propagation lags behind individual view commits

At one sampled point:

- The viewer's own `/api/config` reported Top revision 6, and its committed manifest contained 16 stores.
- The operator's `/api/viewer` still advertised Top revision 5 and 9 published stores.
- Slice was preparing the 16-store update, its `pending.json` existed, and its metadata endpoint returned HTTP 503.
- MIP still held revision 5 with 9 stores.

`views.py::_publish` commits Top, Slice and MIP sequentially. The operator only replaces its cached acquisitions and revisions after the whole announcement completes. Its canvas receives acquisitions through `live.js::viewerSources`; `viz_studio/options/neuroglancer-under/viewer.js::refreshPublishedRows` refreshes cached data only when a newer source revision arrives. Consequently, a committed Top update can wait minutes before the operator propagates the revision needed to refresh existing canvas caches.

The viewer also refuses reads from an aggregate with `pending.json` (`server.py::_serve_from_data` returns HTTP 503). When the next batch starts, even a previously usable named view can temporarily become unavailable. This is a publication/availability and revision-notification problem; clearing the browser cache alone will not finish the rebuild or make a pending view readable.

**Fix direction:** publish revision notifications as individual views commit, refresh operator metadata independently of the slow announcement worker, and retain access to the previous committed generation during rebuild. Validate recovery from transient 503 responses and invalidation of previously cached empty chunks with the actual browser engine.

### Dark target blocks: confirmed stale/incomplete inputs, limited historical attribution

Sampled target source pixels were valid. A full-resolution target plane contained values up to 65,326; another sampled mid-stack plane at a smaller pyramid level contained values up to 57,904. Baked Top crops from an already committed target also contained signal at levels 4-7. At a target included in the 16-store Top generation but not yet in the 9-store MIP generation, the MIP crop was still all zero.

Thus the live viewer had a demonstrable mix of stale revisions, unequal view coverage, and temporarily unavailable data. These conditions can account for missing or stale target display and coarse blocks. The exact pixels/cache contents behind the earlier screenshot were not captured at that moment, so this diagnosis does not claim every dark rectangle has been individually traced. It also does not establish raw-data corruption or a separate GPU defect. Recheck the same target and plane after all 20 stores are published and the client has received the current revisions; any remaining blocks then need a bounded rendering/cache reproduction.

## Recommended repair order

1. Repair the operator reader dependency specification and add preview endpoint coverage, including visible error reporting.
2. Decouple routine target selection from persistent aggregate rebuilding so inspection remains responsive.
3. Repair publication availability and per-view revision propagation so ready images update promptly and remain readable; include pending reorder work in status.
4. Validate these repairs in the operator, including focus navigation, target selection and image refinement during publication.
5. Then investigate any remaining native-window rendering/cache defect and measure the complete performance breakdown to guide further composition/baking optimization.

No fixes have been applied as part of this diagnosis. Local diagnostic scripts, summaries and profiles are stored under `C:\ProgramData\MinicondaZMB\home\t.de\operator-diagnostics`, including `named-views-diagnosis-summary.json`, `named-views-stall-threads.json`, `named-views-stall-threads-2.json`, and `named-views-stall-profile.json`.

## Completion and additional checks

The final batch completed without intervention. At 23:57:26 local time, the operator reported 20/20 target stores ready, all three target views were revision 7, and the publisher thread was idle. The user then confirmed that the display looked correct. This substantially narrows the reported dark-block problem to the period of incomplete publication/revision propagation; no persistent rendering defect was demonstrated after completion.

| Final batch milestone | Local time |
| --- | --- |
| Previous 16-store MIP commit | 23:48:49 |
| Top reaches 20 stores | 23:53:45 |
| Slice reaches 20 stores | 23:56:12 |
| MIP reaches 20 stores | 23:56:18 |

The interval between completion of the 16-store batch and completion of the 20-store batch was approximately 7 minutes 29 seconds. Top finished before the displayed count could advance, and Slice then took a further 2 minutes 27 seconds before MIP completed.

### Served pixels match committed sources after completion

Read-only HTTP checks sampled the final target's full-resolution chunks for Top, Slice, and MIP, in both channels. All six 32-by-32 patches matched their respective committed source pixels exactly (zero differing pixels). Top plane index 9 and Slice plane index 14 both correctly selected native plane index 9 for this target. MIP was checked against its committed projection source. These are bounded samples, not exhaustive image validation.

Those chunk requests took approximately 0.067-0.190 seconds and returned `Cache-Control: no-store`. The operator also advertised revision 7 for every target view. Thus usable pixel delivery after publication is much faster than preparing the publication, and the observed revision lag clears when the batch finishes.

### Existing source pyramids often cannot be reused

A geometry-only check of the actual committed mosaic evaluated `Composer._can_read_native` without building pixels or changing stores:

| Source pyramid level | Occupied aggregate pieces | Pieces allowed to reuse native pyramid data |
| --- | --- | --- |
| 1 | 80 | 16 |
| 2 | 46 | 5 |
| 3 | 28 | 0 |

The counts were the same for Top, Slice and MIP. Reuse requires compatible reduction arithmetic and aligned acquired-region boundaries on the aggregate grid. When those conditions fail, `_build_slab` recursively composes finer pixels before reducing them. In this dataset, no occupied piece at level 3 qualifies for direct native-pyramid reuse. This identifies a concrete source of extra work behind the sampled recursive composition stacks; it does not quantify every contributor to elapsed time.

Optimization should preserve correct gap/overlap ownership and reduction arithmetic. Simply bypassing the alignment checks or snapping physical tile positions to a coarser grid would change the image semantics. A bounded benchmark should instead measure repeated reads/composition and evaluate reuse of correctly composed intermediate results, incremental updates and deferred baking.

Additional local evidence: `served-target-pixel-checks.json`, `pyramid-reuse-check.json`, and their diagnostic scripts in the diagnostics folder. The missing ngio dependency and preview failures remain unfixed.

## New finding on 2026-09-11: selecting targets restarts publication

After the user confirmed the completed image looked correct, a further screenshot showed a coarse target in Top view, Plane 12 of 21, with target list row 18 selected. Local screenshot: `C:\Users\t.de\Desktop\{66777486-7248-4DF6-8A5A-F138EBE4FEBB}.png`. Completion of the original acquisition batch therefore did not end the display problem: subsequent interaction can start another publication.

### Confirmed interaction-to-rebuild path

`application/framework/window/main.js::selectTarget` calls `backend.raiseTarget(label)` for an explicit selection of an acquired target. This sends `POST /api/targets/raise`. The bridge calls `viewer_service.raise_position`, which removes that store from the composition order, appends it to the end, and queues publication. Thus selecting a target is coupled to rewriting its overlap order in the persisted aggregate, rather than being only a selection/highlight operation.

The implementation deliberately excludes quiet automatic selection, but ordinary user selection still takes this path. During the new screenshot investigation:

- The operator reported all 20 targets published and `state=ready`.
- The Top aggregate nevertheless had `pending.json`, timestamped 00:00:16 on 2026-09-11.
- Its pending and committed source-version dictionaries were identical: this update did not require a new capture or new source pixel revision.
- Top metadata and coverage requests returned HTTP 503. An isolated fresh Neuroglancer reader also encountered those failures, so the native window alone is not required to reproduce this data-availability problem.
- The pending update marked 135 level-0 XY pieces, 60 level-1 pieces, 37 level-2 pieces and 23 level-3 pieces dirty, with further work through level 13. A thread snapshot caught the commit building level 4, plane 5.

No selection/reorder POST was issued by the diagnostic reader; it read the existing viewer and data endpoints. Its attempted resolution comparison was stopped when the pending-store responses prevented a fair comparison.

### Why the ready count misses it

`viewer_service.status` compares published source revisions against acquired source revisions. `raise_position` changes composition order without changing those revisions. Therefore the status can remain **20/20 ready while an interaction-triggered aggregate rebuild is in progress**. Status needs to track composition/publication generations and pending work, not just source versions.

### Why a selection can invalidate substantial work

In `published.py::prepare`, the reorder logic compares old and new order lists by ordinal position and marks names at differing positions as affected. Moving one item to the end shifts other items too. Their occupied aggregate pieces then enter the dirty set, without first limiting changes to areas where the relative overlap actually changes. This is an identifiable source of unnecessary invalidation to benchmark and tighten.

### Revised repair priority

Decouple routine target inspection from expensive persistent aggregate rebuilding. Preserve the selected target's intended visual prominence through a transient viewer presentation, or make any necessary reorder work bounded to actual affected overlap while keeping the last committed image readable. Also make pending reorder work visible in publication status. Together with per-view revision propagation, this directly addresses the user's hypothesis that the operator integration is imposing avoidable work on Neuroglancer.

The snapshot does not establish a separate browser resolution-selection defect: the backend was again refusing the data needed for refinement. Test the native client's finer-level loading once the selected view is readable and no selection-triggered rebuild is active. No runtime fixes or restart were performed.

## Agreed direction: prioritize responsiveness

The user explicitly prioritizes responsiveness. Let Neuroglancer independently manage chunk fetching, caching, zooming and resolution selection; the operator should manage the acquisition workflow and send lightweight state/revision updates. Routine target inspection should update selection and presentation immediately without waiting for persistent aggregate recomposition. Keep a complete readable generation available, expose ready views promptly, and perform expensive pyramid preparation in the background. The backend must still provide correct readable chunks; this direction does not assume Neuroglancer itself generates the source stores or their pyramids.

## Diagnostic coverage and remaining limits

Every reported symptom has been investigated, but not every possible contributing cause has been proved or excluded.

Confirmed by runtime evidence and source tracing: missing ngio on the operator preview paths; genuine zero-valued first/last focus planes; completed acquisition with prolonged publication; sequential view commits and delayed operator revisions; pending views returning HTTP 503; selection-triggered order changes and rebuilds hidden by the ready count; and restrictive native-pyramid reuse on this recorded geometry. Sampled served pixels matched their committed sources after publication, and the user confirmed the display recovered before further target interaction.

Still outstanding:

- Direct inspection of the existing native WebView's request/cache state during a coarse-frame incident. The isolated reader hit the same unavailable backend, so it could not establish whether an additional native-client resolution/cache defect exists.
- Exhaustive pixel validation and exact historical screenshot-to-chunk attribution. Six matching patches do not prove every target, plane or pyramid level is correct.
- A complete performance breakdown separating ingestion/store creation, composition, compression, filesystem I/O, cache reuse, preview generation and frontend rendering. Current evidence identifies expensive publication paths and elapsed commit intervals, not an optimized implementation or a speedup guarantee.
- Focus-result navigation behavior after restoring preview generation, and end-to-end validation of preview dependencies in the actual operator environment after repair.

This report is sufficient to prioritize targeted repairs, but those repairs and their regression/performance validation have not yet been performed.

## Explicit outstanding tasks

The user confirmed on 2026-09-11 that the following work still has to be done:

Priority clarification: repair the confirmed preview and interaction/publication problems first, following the repair order above. The two investigations below remain required follow-up work, but are not prerequisites for starting those repairs. Use focused measurements and regression checks while repairing each confirmed issue; the complete performance breakdown can follow.

- [ ] Investigate whether an additional native-window rendering, resolution-selection or cache defect remains. Inspect the actual WebView's requests and cache state with publication complete, current revisions delivered and no aggregate rebuild active. Record the result even if no additional defect is found.
- [ ] Measure the complete performance breakdown: ingestion/store creation, composition and pyramid building, compression, filesystem I/O, cache reuse, preview generation, viewer loading and frontend rendering. Identify the dominant costs with measured timings rather than attributing all delays to the already-confirmed publication bottleneck.

## Repair 1: canonical preview reader restored on 2026-09-11

The operator now declares `ngio==1.1.0` in both dependency manifests. The Python minimum is 3.11, matching this reader's requirement. The installation handover includes an operator-process reader check and HTTP preview regression tests; an analysis worker import check alone is insufficient.

Installed ngio and its missing dependencies in the current operator environment, preserving the installed NumPy, Zarr, Pydantic and viewer versions. Pydantic 2.13.4 was explicitly retained during installation; the resolver selected compatible ome-zarr-models 1.6. The live operator was not restarted and no acquisition was triggered.

Validated:

- The running operator's overview and target displayed-preview endpoints now return HTTP 200 JPEGs, both 1024 by 1024 with nonzero signal (666,618 and 605,266 bytes in the sampled requests).
- All four recorded focus stores generate 201 JPEG slices each in a separate diagnostic folder. Central-slice maxima are 145, 125, 116 and 120. No source stores or acquisition records were modified.
- Three new canonical-store HTTP tests cover overview/target MIPs, channel display changes, and focus slices with physical Z heights and genuinely blank end planes. These tests use the actual reader and do not skip when ngio is missing. Together with existing preview/canonical/simulator checks: 22 passed. Two additional bridge preview tests passed.
- Two browser tests verify visible preview failure messages and recovery to a valid black image. All 525 JavaScript unit tests passed (15 skipped); the production page rebuilt successfully; `pip check` passed.

The rebuilt interface displays `Preview unavailable` for failed detection/gallery image requests and a focus preview status message for missing/failed slices. Failed focus image callbacks are cleared; incomplete gallery images are not passed to canvas drawing. Browser tests covered detection and gallery; direct native-window focus navigation remains to be checked.

At the time of repair 1, the four previously measured focus points still contained empty in-memory slice lists from the original failure. Installing the reader did not backfill those lists. Regeneration was verified separately under `operator-diagnostics/preview-repair-evidence`; that check did not replace the window's state. Newly generated focus results can now create their slice copies. The user subsequently reran a focus point and then closed the window during repair 2. This repair does not claim to resolve any remaining native-window rendering or publication issue.

## Repair 2: target inspection no longer requests aggregate rebuilding

Ordinary target selection in `main.js::selectTarget` now updates only the local selection, gallery comparison, frame outline and current-target action. It no longer calls `backend.raiseTarget`, so list/canvas clicks do not change persisted composition order or start publication. Neuroglancer continues reading the existing published images. The mosaic retains acquisition overlap order; the sidebar comparison shows the selected frame independently of overlap in the mosaic. Actual acquisition/rerun publication and the explicit backend reorder API are unchanged.

Two selection details were corrected alongside this change: explicitly choosing the quietly followed frame activates its manual outline, and rebuilding the action bar makes `Rerun current` capture the current selection rather than the selection held by an older button callback.

Validation:

- A browser regression using the operator's pretend acquisition workflow reproduced the old defect: the first explicit list selection called the instrumented reorder method. The test failed before the fix and passed afterward.
- The same test covers quiet following during acquisition, list selection, choosing the quietly followed frame, canvas selection, gallery synchronization, and rerunning the newly selected physical frame. The reorder request stub remains uncalled throughout; if called, it records the invocation and leaves its promise pending to represent slow publication.
- All 525 JavaScript unit tests passed (15 skipped); the production interface rebuilt successfully.
- The broader existing `one walk of the whole run` test failed before reaching selection because Detect objects opened at tile `864 / 864` while the test expects `1 / 864`. This is a separate existing issue recorded for follow-up, not fixed in this repair. The focused selection regression does not depend on that initial tile choice.

The user closed the native operator after the focus rerun; the rebuilt interface was then relaunched. Previous session logs were preserved in `operator-diagnostics/before-selection-fix.stdout.log` and `.stderr.log`. No microscope acquisition was triggered by the repair or its tests. Publication availability, per-view revision propagation, truthful pending status and further performance work remain outstanding; preventing selection-triggered rebuilding does not repair those acquisition-time paths.

## Repair 3: readable publication and prompt view revisions

Implemented in viewer commit `643a721f8dd68f61abc8c2ecf40a4bf8d6fb2136`, branch `codex/operator-publication-responsiveness`, and the operator commit containing this report. Both operator dependency manifests and the installation handover now pin that viewer revision.

The viewer serves a complete immutable HTTP generation while the working named view is rebuilt. Metadata, coverage and fine on-demand chunks read the same committed generation; changed original stores cannot silently alter its fine-level pixels. Each completed view is discoverable immediately, including Top during the first opening while Slice still builds. The operator refreshes view metadata independently every 0.5 seconds instead of waiting for the whole publication POST. Metadata reads are serialized outside the acquisition/status lock so delayed responses cannot overwrite newer results. A queued or active publication reports preparing even if its source revision counts already match, as happens for an explicit reorder.

Generation snapshots hard-link atomically replaced aggregate chunks. New source revisions are copied once because original stores may be overwritten in place; unchanged frozen source folders are shared directly across generations and compatible views. Copying large sets of small files uses at most eight workers. Old generations and their caches are released after the last HTTP/configuration reader; frozen sources remain until no registered generation uses them.

Validation:

- 108 viewer tests passed, including the named-view, HTTP server, published acquisition/depth and real Chromium rendering checks. Browser tests used the allowed Chromium executable under MinicondaZMB and NVIDIA ANGLE rendering.
- Eight focused HTTP regressions cover same-depth and changed-depth updates, pixels/metadata/coverage remaining readable, Top advancing while Slice remains old, first-view discovery, source sharing, final-reader cleanup, and recovery from injected bake, snapshot-copy and publication-ledger failures. These eight passed again after the final cleanup hardening.
- All 40 operator service tests passed against the changed companion viewer, including the 100-position notification/status responsiveness checks with and without baking. New checks cover pending reorders, intermediate view revisions, rejecting obsolete-session metadata, and excluding uncommitted raw rows during first publication.
- Ruff and whitespace checks passed. A matching viewer wheel was built in `operator-diagnostics/repair-3-wheel`.

Bounded storage measurement on this workstation: one recorded target store contained 83,959,082 bytes in 3,575 files. The initial serial snapshot copy from E: to C: took 17.76 seconds and recreating its hard links took 4.62 seconds. The final bounded copy took 2.00 seconds; subsequent views/updates reuse an existing source folder without relinking those files. These are individual warm/cold-cache-uncontrolled measurements, not a full acquisition benchmark or a promised overall speedup. Results are saved in `operator-diagnostics/readable-copy-benchmark`.

Limits and deployment checks:

- Extra disk space is required for the current frozen source revisions and temporarily for replaced revisions held by readers. Copy fallback on filesystems without hard links costs more. Pyramid composition itself remains expensive; the full performance breakdown remains outstanding.
- The immutable HTTP guarantee begins with the first successful publication using the new viewer. Existing views without a readable pointer keep their legacy serving behavior until republished. Direct filesystem readers of the working aggregate do not receive the HTTP snapshot guarantee.
- Reader leases are local to one server process. Do not run multiple independent viewer servers against the same output folders. Abrupt termination can leave orphan private source folders; automatic crash-orphan scavenging remains follow-up work.
- The actual native-window resolution/cache investigation, real-microscope validation and full performance profiling are still required. Automated browser success does not prove that every previously reported native rendering symptom is fixed.
- Deployment completed after the user closed the operator on 2026-09-11. Installed the prepared wheel with `--no-deps --force-reinstall`; verified its installed Python sources match the tested viewer checkout and `pip check` reports no broken requirements. Relaunched the existing named-views launcher. The native ZMART window opened and the operator's `/api/viewer` reports running with no error. This startup check does not trigger or validate a new microscope acquisition. Previous session logs are preserved in `operator-diagnostics/before-repair-3.stdout.log` and `.stderr.log`.
