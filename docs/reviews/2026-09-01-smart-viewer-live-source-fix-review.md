# Review and fix: every live field reaches the Smart Operator canvas

**Date:** 2026-09-01  
**Microscopy branch:** `codex/smart-viewer-integration-cleanup`  
**Smart Viewer checked:** `thomdehoog/ZMART-viewer` 0.2.0, commit `9ff10b0`  
**Claude candidate reviewed:** `claude/every-field-reaches-the-canvas`, commit
`d84c6848`

## Verdict

Claude found a real reduction bug: when Smart Viewer returned several position
stores in one acquisition row, Microscopy kept only one. The candidate fix for
that narrow fault is correct and its regression tests are meaningful.

It was not, by itself, the Step 5 fix. The bridge also cached the configuration
returned when the first field opened and then tried to make a growing picture
current by closing and reopening it. That behavior came from the older server
contract. Smart Viewer 0.2 already watches a folder opened on its first field,
adds later stores to the same stable dataset, and reports the growing source
list through `GET /api/config`.

The cleanup therefore uses the Viewer behavior that already exists:

1. open each acquisition folder once, when its first position lands;
2. announce later landings;
3. read the Viewer's current config on the operator's existing 1.5-second poll;
4. keep every field belonging to the newest Viewer dataset under each
   acquisition heading;
5. never close and reopen a folder merely because it grew.

This is deliberately an integration fix, not another Viewer implementation.

## What was actually broken

### 1. The bridge froze the first answer

`a_position_landed()` stored the layer configuration returned by the first
`POST /api/stores/open`. `status()`, which serves Microscopy's `/api/viewer`,
returned that stored value forever. The browser polls `/api/viewer` every 1.5
seconds, but every poll received the same first-field URL.

Smart Viewer itself was already current. In a direct 0.2 server check:

| Moment | Viewer acquisition | Source URLs | Dataset numbers |
| --- | --- | ---: | --- |
| Folder first opened | `overview` | 1 | `0` |
| Three more stores landed | `overview` | 4 | `0` |

The four URLs were four placed OME-Zarr position stores in one watched
acquisition. They did not represent four acquisitions or four generations.

### 2. The relink workaround contradicted Viewer 0.2

The microscopy service closed and reopened a folder when the second store
landed. A later Claude branch expanded this into a 30-second relink throttle.
Both forms solve an obsolete assumption: that a folder opened on one store
cannot grow.

In Viewer 0.2 it can grow. Reopening has three avoidable costs:

- it changes the dataset number and revokes URLs the page may still be opening;
- it delays a short scan or makes live evidence depend on a timer;
- once the folder is composed into a session scene, a later reopen can reuse
  the old scene declaration instead of rebuilding it.

The last point was reproduced directly. A positions folder was composed with
two stores, a third store was added, and the same folder was opened again.
Both `zarr.json` and `tiles.json` still declared two tiles. The scene path was
reused, but its tile ledger did not grow. Relinking is therefore not a safe
publication mechanism for this live plain-folder case.

### 3. Microscopy and Viewer had the same distribution name

Both repositories declared the pip distribution `zmart-viewer`:

- Microscopy: 0.1.0;
- separate Smart Viewer: 0.2.0.

Installing Microscopy could uninstall the working Viewer and replace its
metadata without producing an error near the black canvas. Microscopy now
declares itself as `zmart-microscopy`; its Python packages and imports are
unchanged. The separate `zmart_viewer` package remains the sole owner of the
Viewer name.

## Review of Claude's candidate

### What is accepted

`d84c6848` changed the source reduction from "keep one URL" to "keep every URL
whose `/data/N/` number equals the newest dataset number." That matches the
real Viewer contract:

- fields of one watched acquisition share one dataset number;
- an obsolete opening, if one is still present, has an older dataset number.

The candidate's six focused tests pass. Running those same tests against the
parent implementation produces exactly three failures, including the two
important cases: retaining all fields and retaining all fields of the newest
generation. The tests are therefore not vacuous.

A direct integration check also generated four real Viewer source URLs and fed
the returned config through the candidate reducer. All four survived.

### What is not accepted

The 30-second close/reopen machinery surrounding the candidate is not carried
onto the cleanup branch. It is unnecessary with the current Viewer's watched
folder and can turn a growing acquisition into a stale composed scene.

The candidate test wording calls several position-store URLs a "composed
acquisition." That is misleading. A current composed session scene is normally
one virtual `*.zmartview.zarr` URL; the several same-dataset URLs in this fault
are a watched multi-store acquisition. The source-selection behavior is still
right.

## Implemented change

`application/parts/storage/viewer_service.py` now:

- records an opened folder as membership rather than a store count;
- opens that folder only once;
- reads Smart Viewer's `GET /api/config` whenever the page polls status;
- publishes a refreshed acquisition/source list only if the Viewer port is
  still the same after the request;
- keeps every source in the newest Viewer dataset number;
- strips Viewer session/copy decorations from operator acquisition headings;
- preserves the last usable source list and reports a sentence if a config
  refresh fails, so a Viewer hiccup cannot abort the scan.

`pyproject.toml` now names this distribution `zmart-microscopy`, eliminating
the installation collision with Smart Viewer.

## Verification performed

| Check | Result |
| --- | --- |
| Focused Microscopy source/service tests | 6 passed |
| All Microscopy storage tests | 20 passed |
| Ruff on changed Python files | passed |
| Offline wheel metadata | `Name: zmart-microscopy`; Viewer name no longer claimed |
| Candidate tests against `d84c6848` | 6 passed |
| Candidate tests forced against its parent | 3 passed, 3 failed as expected |
| Smart Viewer multi-store layer contract | passed |
| Real Viewer + cleanup service, one field then four | 1 -> 4 URLs, all dataset `0`, one opened folder, no error |
| Reopen a grown composed session scene | reproduced stale 2-tile declaration with 3 stores on disk |

The older `the-scan-under-the-plan.spec.js` still times out before its alignment
assertion because `window.__thePicture` never becomes truthy. The same failure
is present before Claude's integration branch, so it is not caused by this
change, but it prevents that test from proving registration.

## Screenshot review

An existing 0/3/6/9 screenshot set was inspected. It does show nine synthetic
fields filling the planned 3 x 3 grid, and its overview-only image shows the
focussing heading crossed out while overview pixels remain. It is useful
structural evidence, but it is not the user's requested proof: the pixels are
the mock's smooth synthetic texture, not visibly identifiable kidney
microscopy data. The whole-plate image also makes the acquisition too small to
judge registration by eye.

Those images are therefore not accepted as the final gate and are not added to
this branch as proof.

## Review points still open

1. **Real Step 5 pixels:** capture 0/3/6/9 with the mock kidney dataset and
   verify every planned ROI is textured rather than white, black, or flat.
2. **Visibility truth:** hide focussing, photograph overview still filling all
   nine positions, and verify engine state rather than trusting the eye icon.
3. **Registration:** repair the harness that waits for `window.__thePicture`,
   then compare all nine image bounds with the transparent plan to less than
   one screen pixel.
4. **View preservation:** prove the whole-plate Fit survives the first and
   later field arrivals.
5. **Fresh installation:** install Microscopy and Viewer into a clean
   environment in both orders and confirm Viewer remains 0.2.0 and
   `/api/measure` is available.
6. **Other Claude fixes:** review the requested-vs-observed eye-state fix and
   the empty-canvas projection fix separately; neither is silently bundled
   into this source-lifecycle change.

## Merge condition

This commit is suitable for review as the source-lifecycle and packaging fix.
The pull request must remain draft until the kidney 0/3/6/9 evidence,
overview-only visibility, registration, and clean-install checks above pass.
