# Operator observations, 2026-09-09

## Follow-up: root-cause mechanisms reproduced

This initial note is preserved as the investigation history. Its tentative
diagnosis below is superseded by the experiments and expanded report:
[Investigation, root causes, and fix plan](operator-relative-z-investigation-and-fix-plan-2026-09-09.md).

The follow-up established:

- The conflicting XY sampling values come from precise native OME versus the
  rounded live-job pixel-size string. The successful-read and unavailable-read
  paths reproduce the recorded values. The actual stored overview tiles fail
  viewer validation at position 2; a uniform in-memory geometry control passes.
- A real isolated viewer/publisher reproduction confirms that one failed
  acquisition update can leave the bridge's acquisition list stale, hiding an
  independently published target acquisition. This is the third, major bug
  reported after the first version of this note.
- Real-browser tests reproduce transparent holes and incorrect addition to the
  overview when coverage lags signal, and black rectangles when signal lags
  coverage during Z scrolling. Controlled-delay assertions pass in both baking
  modes, and the display settles correctly after the gates are released.
- A gated fake capture exercising the real focus loop confirms that viewer data
  is handed off only after capture completes and inspector results only after
  scoring. No microscope driver was connected for the reproduction.

Scripts, JSON results, and screenshots are retained under
`C:/ProgramData/MinicondaZMB/home/t.de/operator-diagnostics`.
No application fixes or changes to the recorded run were made. Original timeout
logs and the exact network timing of the user's initial transient were not
captured; the experiments prove the mechanisms without reconstructing those
historical timings.

Branch: `codex/operator-relative-z-integration`, operator `10e6d212`, installed
viewer `8604cb812949feb9bdcb5c8bf2739b559543fd44` (0.2.1).
Investigation only; no application, viewer or acquisition data changed.

## 1. Only the first two overview tiles appear

Reported screenshots:
- `C:/Users/t.de/Desktop/Bugs/4 focusing/one the first 2 tiles show up.png`
- `C:/Users/t.de/Desktop/Bugs/4 focusing/{3FD8D443-B732-42A6-ACCB-91C17D26ABB9}.png`

The user suspected different focus heights, recalling the earlier branch's
workaround. Commit `fbe0de7a` documents exactly that earlier symptom: only two
tiles of an eight-tile run appeared when flat captures stood at their measured
focus heights. Its shared-display-Z fix is already present in this branch.

Read-only inspection of the active run
`E:/Experiments/ZMART-microscopy/target-acquisition_a56857` shows:

- All eight overview original stores exist under `positions/overview`.
- Every original has Z translation 0 and Z scale 1. Measured heights remain
  separately recorded as provenance (approximately 85.85 to 65.47 micrometres).
- Overview positions 0 and 1 have XY sampling 2.27 micrometres/pixel;
  position 2 has 2.27495107632, as do positions 3 through 6. Position 7 has 2.27.
- `positions/overview/.zmart-viewer/overview.ome.zarr/publication.json` is at
  revision 2 and contains only positions 0 and 1.
- The target publication is at revision 3 and contains only positions 0 to 2.
  Target position 3 changes XY sampling from 0.11375 to 0.113747260274.
- The active bridge's `GET /api/viewer` reports a publication error for those
  two target sampling values, treating them as different magnifications.
- `GET /api/scan` reports all 10 targets acquired, with no acquisition error.

Code supporting the diagnosis:

- `application/parts/storage/zarr_positions.py`, `_the_z_model`: single-plane
  captures use `A_FLAT_CAPTURES_SHARED_Z_UM = 0.0`, retaining acquisition height.
- The same file reads physical XY sampling from OME metadata.
- Installed viewer `zmart_viewer/compose.py`, around line 460: exact comparison
  `ours.voxel_um != other.voxel_um` raises the magnification mismatch error.
- `application/parts/storage/viewer_service.py`, `_publish_once`: a publication
  exception preserves the previously published picture and requeues the update.

Conclusion: evidence strongly supports publication stopping at inconsistent XY
sampling, rather than flat tiles disappearing at different display Z heights.
The live error is for targets; the overview's stored sampling and publication
boundary support the same mechanism there. The original overview error has not
been recovered separately.

Still to determine: why nominally matching captures acquire different sampling
metadata (rounding, metadata sources, or actual acquisition changes). Do not
simply relax the viewer check until the source geometry is understood.

## 2. Focus display changes during acquisition; completed stacks scroll correctly

User observations:
- While the focus job is running and the focus map is being built, scrolling
  through Z appears to change the image-data footprint: more or less black is
  seen over the overview acquisition.
- The current focus job's data is not visible yet while it is acquiring.
- Once acquisition finishes, the result looks good and scrolling through the
  stacks works correctly. This is a transient display observation, not a
  report that the completed stack geometry is wrong.

Code evidence for the delayed focus preview:
- `application/parts/microscope/focus_run.py:265` waits for `session.acquire`
  to return a capture record before calling `keep(record)` at line 282.
  There is no per-plane display callback in this focus loop.
- The bridge's `keep` callback converts and queues a completed stack for the
  main viewer. The point result and its small slice previews are supplied
  separately, after scoring (`bridge.py`, `_focus_worker` / `landed`).
- `focus-map.js:1900` automatically selects the next, unmeasured point each
  time a point completes. At the final point, it selects the completed point
  instead. This can leave the preview following the in-progress point rather
  than showing the stack just completed.
- `focus-map.js:1265`, `drawZSlice`, hides the preview when the selected point
  has no slices. These paths support the reported absence of a preview during
  capture and its availability when the run finishes.

The changing black footprint is not yet reproduced or attributed conclusively.
Relevant main-canvas paths, if that is where the user sees it:
- `neuroglancer-under/viewer.js:677` creates a separate opaque-black coverage
  layer beneath each acquisition's signal. Coverage, rather than pixel
  brightness, decides which parts cover underlying imagery.
- `addSourcesToTheOpenRows` refreshes changed aggregate sources as completed
  focus stacks arrive; `source-refresh.js` invalidates their cached chunks.
  Signal and coverage are separate sources, so their display while updates
  load is a candidate to inspect, not a confirmed synchronization bug.
- Existing `aggregate-depth.spec.js` checks Z navigation after pixel values
  settle. It does not establish that the image footprint stays stable while
  repeatedly scrolling during an active focus acquisition and source refresh.

Next diagnostic: capture the transient main-canvas/preview state during a
user-run focus acquisition, including selected point, Z, source revision,
signal and coverage readiness. Do not reacquire, restart, or modify the real
instrument as part of this note-taking investigation.
