# Native XY and publication isolation: offline verification

Base: operator integration `e8691829`, including the microscope observations and
investigation plan. These are the first two fixes, not a claim that every reported
display problem is resolved. Neither the rig worktree nor recorded run data was
modified.

## Changes

1. Native AutoSave XY calibration is authoritative. A live job's rounded
   `pixelSize` string no longer replaces it when a settings read succeeds.
   The separate job-based Z spacing correction and its existing bounded read
   remain. Native XY must be finite and positive; missing calibration now fails
   explicitly before canonical export/cleanup, preserving native originals.
   This avoids accidentally displaying an uncalibrated image as 1 micrometre
   per pixel. Both Leica driver copies have the same implementation and tests.
2. The background publisher submits independent acquisition snapshots. A bad
   overview open or update no longer prevents targets from reaching the page.
   Last committed images remain usable. Automatically discovered, uncommitted
   position groups are excluded. Input rejection waits for a changed snapshot;
   temporary failures retain pending work and retry without another capture.
3. `/api/viewer` exposes per-acquisition acquired/currently-published store counts
   and errors. The page reads images and status in the same existing poll, keeping
   available images even when another acquisition failed. The canvas note says
   **available**, not displayed: server publication does not prove GPU rendering.
   Shorter reruns prune current membership without resetting revision history.
4. Viewer commit `b33a21cb8ff9c3edb6a49c75e46ee5e72790818b` distinguishes a temporary
   open I/O failure (HTTP 503) from invalid input (HTTP 400), matching announce.
   Requirements and environment pins include it. The built operator page is rebuilt.

No geometry tolerance, first-tile calibration cache, new polling loop, source
proxy, or second invalidation path was added. Baking remains optional and original
position stores remain separate. Acquisition/status callbacks still do no viewer I/O.

## Offline evidence

| Check | Result |
| --- | --- |
| Acquisition, native AutoSave, OME patcher tests | 91 passed per Leica driver |
| Viewer service | 35 passed, including both 100-position bake modes |
| Position writer, output, JPEG regressions | 36 passed |
| Viewer acquired publication, depth, announcements | 67 passed |
| Operator JavaScript unit suite | 518 passed, 15 skipped |
| Browser publication isolation and mixed-depth regressions | 6 passed in 1.3 minutes |
| Production page build | Passed |

The XY regression uses the recorded precise values `2.27495107632` and
`0.113747260274` micrometres against rounded job strings `2.27 um` and
`113.75 nm`, alternating successful/unavailable/degraded settings reads. It failed
before the fix. Tests also preserve a genuine sampling change, reject missing or
invalid native axes, and round-trip unequal XY with nanometre units through
canonical XML. AutoSave test images now declare their calibration explicitly.

The real HTTP publication test deliberately introduces incompatible overview
sampling while a valid target lands. It checks both submission orders and both
first-open/update rejection, then fixes the input and checks recovery. Separate
tests cover HTTP 503 retry without another capture and retirement/reuse of names.

The browser uses the real publication service, live backend, run watcher and
Neuroglancer. With baking off and on it measures these RGB samples:

| Region | Rejected overview update | After input correction |
| --- | --- | --- |
| Previously published overview | (120,120,120) | (120,120,120) |
| Rejected/new overview region | (255,0,255), underlay visible | (180,180,180) |
| Independent target | (240,240,240) | (240,240,240) |

The blocked note is asserted alongside valid target pixels and disappears after
recovery. Each mode records zero image-chunk requests during a 3.2-second idle
window while blocked and another after recovery (at least two normal polls).
The baked partial screenshot was also decoded independently with Pillow:
16,384 overview pixels at RGB 120, 16,384 target pixels at RGB 240, and 172,032
magenta background pixels, matching the expected two 128-by-128 rendered regions.
The four mixed-depth cases each recorded 28 image requests and zero idle image
requests; they also check black coverage, gaps, Z and coarse transitions.

Screenshots are generated evidence, not committed assets. This run's output is at
`C:/ProgramData/MinicondaZMB/home/t.de/publication-isolation-results-20260909/`.
The `publication-failure` subfolders contain `partial-publication.png` and
`recovered-publication.png`; the other subfolders contain mixed-depth proofs.

Two independent reviews found the missing-calibration and retired-count gaps;
both were addressed and independently rechecked. No remaining finding in their
scoped final reviews. Changed production Python passes Ruff. The broader existing
native-AutoSave test file has an unrelated UP037 annotation warning; not changed.

## Limits and tonight's short acceptance check

An initial bake-off browser attempt rendered black at the first sample for its
five-second assertion window. An unchanged targeted rerun passed, then the final
six-case run passed without retry or relaxed assertions. This does **not** close
the separately reported signal/coverage readiness issue. Focus inspector selection
is also outside this increment. No long benchmark ladder or hardware test was run.

Before deployment, push the viewer branch first, then the operator integration
branch; update the rig's installed pinned viewer dependency as well as its code.
Use a new run: existing canonical TIFF/Zarr metadata is not repaired by this fix.

Tonight, acquire a small overview and a few targets with the usual focus setup:

- For an unchanged XY recipe, check precise canonical/store XY values agree
  across captures. Confirm Z stacks still have the intended spacing and order.
- Confirm every acquired overview field and target becomes visible, including
  the final acquisition after scanning stops. `available` counts should catch up;
  then visually check rendered pixels independently of those counts.
- If publication fails, record the visible message and `/api/viewer` response;
  unrelated valid acquisitions must remain visible. Do not deliberately alter
  rig data to induce failure; that case is covered by the offline fixture.
- If an available image stays black, record zoom/Z, status and a screenshot:
  that separates the remaining readiness problem from publication rejection.

The quick browser reproduction is
`npm run test:ui -- parts/canvas/publication-failure.spec.js` in `application/`;
the small backend regression is
`python -m pytest application/parts/storage/test_viewer_service.py -k "invalid_overview or retirement or http_503" -q`.
Use the pinned viewer environment. All generated fixtures are local and separate
from recorded microscope runs.
