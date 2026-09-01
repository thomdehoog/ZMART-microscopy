# Smart Viewer in Smart Operator — cleanup and verification plan

**Date:** 2026-09-01

**Implementation branch:** `codex/smart-viewer-integration-cleanup`

**Smart Viewer authority:** `thomdehoog/ZMART-viewer`, version 0.2.0, commit
`9ff10b0`

**Review incorporated:**
`2026-09-01-review-of-the-smart-viewer-integration-plan.md` and
`2026-09-01-handover-smart-viewer-integration.md` from
`claude/viewer-port-remaining-steps-ofm5qp`

## Outcome

Step 5 of Smart Operator must show the mock microscope's kidney image through
the transparent tile plan. A 3 x 3 overview must fill exactly the nine planned
field positions, in the correct physical coordinate frame, while focussing can
be hidden independently.

The integration is finished only when rendered pixels, Smart Viewer state,
served OME-Zarr metadata, requested chunks, and the panel controls all agree.
An open eye, a completed scan counter, or a layer without a reported error is
not sufficient proof.

## Facts established before implementation

These facts were checked against Smart Viewer `9ff10b0` and the current
Microscopy branch rather than inferred from the older copied viewer.

1. `zmart_viewer.loading.load()` is the current front door for opening data.
   When it receives a folder containing two or more position stores and a
   `scenes` directory, `scene_behind_a_run()` declares one composed picture.
2. Smart Viewer's `POST /api/stores/open` always supplies a per-session scenes
   directory through `_scenes_of_this_session()`. It can therefore compose a
   run of positions without the operator calling `/api/stores/construct`.
3. `application/parts/storage/viewer_service.py` already calls
   `/api/stores/open`, closes and reopens a folder when its second store lands,
   and then calls `/api/announce` as later positions arrive.
4. The operator bridge currently reduces Smart Viewer's layer configuration to
   grouped `{url, name}` records in `_the_sources_in()`, and the page flattens
   those records in `viewerSources()`. Whether that reduction loses anything
   needed for Step 5 must be measured; it is not assumed to be the first fault.
5. `/api/measure` exists in Smart Viewer 0.2 and not in the copied server under
   `viz_studio/backend/`. A working histogram and Auto control are useful
   provenance checks as well as UI checks.
6. The cross-engine plane-selection failure predates Claude's seven commits. It
   is existing debt, not evidence that those commits introduced a regression.
7. The Microscopy and Viewer repositories both currently declare the Python
   distribution name `zmart-viewer` (versions 0.1.0 and 0.2.0 respectively).
   That packaging collision can make installation and provenance ambiguous and
   must be resolved or guarded before this is called reproducible.

## Source of truth and chosen boundary

The separate Smart Viewer repository is the authority for:

- classifying and opening OME-Zarr data;
- composing position stores into one acquisition picture;
- the served scene, source lifecycle, and live publication behavior;
- channel and acquisition configuration supplied by its API;
- measurements used for contrast and Auto;
- the Neuroglancer behavior already proven by Smart Viewer's own tests.

Smart Operator remains the authority for:

- the microscope workflow and Step 5 run state;
- planned stage positions and the carrier coordinate frame;
- the transparent plan, tiles, carrier, and stage overlays;
- the operator-specific panel and workflow actions;
- the single canvas adapter through which its overlays and pixels are drawn.

For this delivery, Smart Operator keeps its existing engine adapter behind
`viz_studio/options/contract.md`, and current Smart Viewer configuration drives
that adapter. Smart Viewer's whole page is not mounted as a second canvas, and
`app/page/src/engine.js`, `scene.js`, and `live-refresh.js` are not copied
into Microscopy. Copying those modules would create the second Neuroglancer
implementation this cleanup is intended to remove and would violate
`test_the_engine_stays_behind_its_adapter`.

If a presentation control from Smart Viewer is still needed after the baseline
works, its behavior is expressed through the operator's adapter contract. Its
engine internals are not forked.

## Things explicitly not assumed

- `/api/stores/construct` is not the first fix. It is considered only if a
  measured call through `/api/stores/open` fails to classify a valid positions
  folder as one scene.
- Dataset numbers such as `3` and `17` are not acquisition identity.
- The copied `viz_studio/backend/` and `viz_studio/frontend/src/` trees are not
  current Smart Viewer implementations.
- Claude's branch is not a merge target. Individual commits are candidates,
  each requiring a reproduced fault and focused review.
- The page's eye icon is not visibility truth. Engine state and rendered pixels
  must agree with it.
- The current branch is not declared working based on screenshots previously
  produced against a copied or stand-in viewer.

## Ordered work

### 0. Make the experiment reproducible and name the server

Before changing integration behavior:

1. Prepare the focus environment `ZMART--focus--main` and verify its existing
   diagnostics. Ensure the workflow dependencies used by the mock are present:
   `zarr`, `numpy`, `tifffile`, `imagecodecs`, `scikit-image`, and `pooch`.
2. Install Smart Viewer `9ff10b0` into the operator environment without its
   desktop-window dependency. The server requires `zarr>=3,<4` and
   `numpy>=1.24`; `pywebview` is not required for the bridge. A development
   install may therefore install those requirements explicitly and install the
   Viewer checkout with `--no-deps`.
3. Resolve the duplicate distribution name or add an explicit guard that fails
   when Microscopy's old 0.1.0 metadata shadows the real Viewer. The durable
   installation path must be documented and testable on a fresh checkout.
4. At the beginning of every browser acceptance run, record:
   - `Path(zmart_viewer.__file__).resolve()`;
   - installed distribution version;
   - expected Viewer Git commit;
   - whether `/api/measure` is present;
   - the operator and viewer server ports.
5. Fail before scanning if the import resolves inside Microscopy's copied
   `viz_studio` tree or reports anything other than the pinned Viewer.

The Smart Viewer page build (`app/page/dist`) is not required when the bridge
uses only its API and data routes. That claim must be covered by the headless
integration test; if any route unexpectedly depends on the built page, the
build becomes an explicit prerequisite rather than an accidental local state.

### 1. Run the decisive baseline before porting anything

With the real 0.2 server installed, run the existing operator walk through Step
5 unchanged. Do not first modify source grouping, layer synchronization, or the
Run action.

Capture and inspect:

- `GET /api/viewer` from the operator bridge after 0, 1, 2, and 9 overview
  positions;
- the direct Smart Viewer configuration returned when the positions folder is
  opened;
- the generated scene's shape, scales, translations, and source addresses;
- the bounds reported by the engine;
- all metadata and chunk requests needed to render the 3 x 3 overview;
- a screenshot of the Step 5 end state with focussing hidden.

The decisive question is not merely whether there is one URL. It is whether
there is one overview source whose measured bounds cover all nine planned
fields in the correct coordinate frame.

### 2. Follow the evidence branch and stop when it works

| Baseline result | Next action |
| --- | --- |
| Viewer is not running, import provenance is wrong, or `/api/viewer` reports an error | Fix only environment/package wiring, restart from a clean process, and repeat Step 1. |
| One overview source with correct nine-field bounds | Do not change composition or source grouping. Proceed directly to pixel, visibility, and view-state acceptance. |
| One overview source with single-field or otherwise wrong bounds | Inspect the input coordinate metadata and the scene emitted by `loading.scene_behind_a_run()`; fix the smallest incorrect producer or Viewer behavior. |
| Multiple overview sources | Call `loading.load()` directly on the exact folder and record why it did not compose. Correct the folder/metadata contract first. Consider `/api/stores/construct` only if `open` legitimately cannot represent this input. |
| Correct source and bounds, but absent/white pixels | Inspect the operator adapter's layer state, shader/window, visibility, selected z plane, and view fit. Do not rewrite the Viewer server. |
| Correct final picture, but live additions fail | Isolate close/reopen-on-second-position and `/api/announce` behavior with a two-then-nine-position server test before changing publication logic. |

If the defect is in Smart Viewer itself, fix it on a separate Smart Viewer
branch with its upstream tests, then pin Microscopy to the tested Viewer commit.
Do not hide an upstream defect with operator-specific source rewriting.

### 3. Keep the operator seam thin

Only if the baseline proves the current `{url, name}` reduction insufficient,
replace it with one typed adapter model derived from Smart Viewer's returned
configuration. Preserve only fields the operator demonstrably consumes:

- stable acquisition/group and channel identity;
- every source belonging to the channel;
- spatial position and dimensions needed by the adapter;
- display window, colour/LUT, opacity, and requested visibility;
- source revision identity when Smart Viewer supplies it.

Do not infer freshness from numeric URL components, collapse generations by a
decorated display heading, or make the page rediscover metadata the Viewer has
already classified. Add a contract fixture generated from real Smart Viewer
0.2 output so the two sides cannot silently drift.

### 4. Reuse Claude's fixes through a review ledger

The following work is inspected individually rather than re-derived or
cherry-picked wholesale:

| Candidate | What may be reused | Required decision |
| --- | --- | --- |
| `5376b7f` | Separating the operator's requested channel visibility from the engine's observed visibility | Reproduce hide/show with focussing and overview; adopt the minimal fix if it preserves prior channel choices. |
| `4ab5903` | A finite operator-owned view before any image exists, then following the engine once it is authoritative | Adversarially review gesture ownership, getter side effects, drift, and Fit preservation; retain only with the empty-canvas pan/zoom tests. |
| `908a201`, `b69013f`, `37613ed` | Engine-neutral contract additions for view changes, timepoints, and LUTs | Keep only the interfaces used by the current panel, with all drawing options answering the contract. |
| `ec2e5fa` | `counting-planes.js`, `the-window.js`, Reset, and the declared-window contrast fallback | Retain the arithmetic tests and verify the mock kidney histogram and Auto behavior against `/api/measure`. |
| `0184cb0` | Stable selection by channel name, acquisition fold, and opacity | Retain only behavior confirmed against Smart Viewer 0.2 groups/channels. |

The flat-z, stale-source, plate-scale pyramid, and single-view findings came
from earlier work and
`2026-09-01-why-the-acquired-overview-never-appeared.md`, not from these seven
commits. They remain regression gates but are attributed correctly.

### 5. Make view state and visibility truthful

Before any acquisition exists:

- the carrier, plan, and planned fields project to finite screen positions;
- panning and zooming work;
- a planned field has a deterministic, tested stage-to-screen position.

When the first image arrives:

- the existing whole-plate framing is preserved;
- the engine does not silently replace the operator's Fit with a single-field
  opening view;
- overlays and image pixels continue to use one authoritative projection.

For visibility:

1. the operator's action changes the managed layer state;
2. the engine reports the observed state without overwriting the operator's
   saved channel choice;
3. the panel redraws its eye from the observed state;
4. pixel checks prove the requested acquisition actually appeared/disappeared.

Hiding focussing must leave all overview channels visible. Showing focussing
again must restore the focussing channel choices held before the group was
hidden.

### 6. Preserve live publication and reruns

The existing sequence remains the default until a focused test disproves it:

1. open the first position;
2. close and reopen when the second store makes the folder composable;
3. announce later landed positions;
4. publish the stable composed overview only at the workflow's acquisition
   boundary.

A rerun must replace the correct acquisition using Smart Viewer's identity and
revision semantics without destroying focussing or another acquisition. No
polling clock may revoke a source that is still on screen. Expected Zarr format
probes, such as a Zarr-v3 reader checking for absent v2 metadata, are recorded
separately from failed required metadata/chunk requests.

### 7. Retire the misleading runtime paths

After the real Viewer-backed acceptance passes:

- make the copied `viz_studio/backend/` and `viz_studio/frontend/src/` trees
  explicitly reference-only or remove their runtime reachability;
- add a guard proving `viewer_service.py` imports the separate package;
- remove temporary stand-in modules, symlinks, and experiments;
- keep historical tests only where they still protect a supported contract;
- document a fresh-machine installation that selects the same Viewer commit.

## Acceptance gates

All gates are required.

### Server, data, and adapter gates

- Provenance records Smart Viewer 0.2 at the pinned source path/commit.
- Step 5 writes nine distinct overview position stores for the 3 x 3 plan.
- Smart Viewer returns separate `overview` and `focussing` acquisitions.
- The overview resolves to one composed source with bounds covering all nine
  planned positions.
- Every required overview metadata and chunk request succeeds. Any expected
  format probe failure is named and allow-listed rather than ignored broadly.
- Neuroglancer reports loaded bounds with no layer error or wedged open.
- Stage-plan and acquired-image projections agree to less than one screen pixel.
- Every expected tile ROI contains non-uniform kidney microscopy texture; no ROI
  may pass as white, black, or a flat placeholder/overlay colour.
- Hiding focussing makes its pixels absent while all nine overview ROIs remain
  filled.
- Histogram and Auto use the real Viewer's `/api/measure` response.
- No unhandled browser, bridge, or worker error occurs.

### View-state gates

- The empty canvas draws the plate and plan before acquisition.
- Empty-canvas pan and zoom both change the view correctly.
- Whole-plate framing survives the first and subsequent image arrivals unless
  the operator explicitly requests Fit.
- The same projection controls acquired pixels and workflow overlays after the
  image becomes authoritative.

### Screenshot protocol

Screenshots must come from the real Smart Operator Step 5 page, the real Smart
Viewer 0.2 server, and the mock microscope's kidney dataset. Each image is
paired with a small evidence record containing server provenance, landed
position count, source/bounds summary, visibility state, pixel-check result,
and unexpected network errors.

The Step 5 Run button completes all nine mock positions too quickly to provide
deterministic intermediate stops. Evidence is therefore split honestly:

1. `0-of-9`: Step 5 page before starting acquisition;
2. `3-of-9`: the Step 5 live bridge after `image(positions)` has published the
   first row through the same landed-position path;
3. `6-of-9`: the same deterministic live bridge after two rows;
4. `9-of-9-harness`: the same bridge after all nine positions;
5. `9-of-9-run`: a separate end-to-end use of Step 5's actual Run button;
6. `overview-only`: focussing visibly disabled in the panel, overview enabled,
   and all nine overview positions still textured;
7. `whole-plate`: the complete carrier remains in frame with the overview at
   the correct physical position after the image arrived;
8. `kidney-close-up`: cells are visibly microscopy data rather than white or a
   flat placeholder.

The 3- and 6-position screenshots are labelled as deterministic live-bridge
evidence, not falsely described as a paused Run-button scan. The final
Run-button screenshot proves the end-to-end workflow.

After the 3 x 3 proof passes, run `every-tile-is-filled.spec.js` with focussing
hidden and the existing larger six-well/per-field acceptance. Every planned
field is measured independently so a partially drawn overview cannot pass from
a zoomed-out impression.

## Test order

1. Current Smart Viewer focused server/loading/composition tests, unchanged.
2. A direct two-position `loading.load()` and `/api/stores/open` composition
   contract using the same data layout Step 5 writes.
3. Microscopy's engine-boundary and cross-option contract tests, carrying the
   known plane-selection debt explicitly until fixed.
4. Focused bridge tests for import provenance, first/second/later position
   publication, source bounds, and rerun identity.
5. Panel visibility, measurement, contrast, and empty-canvas view tests.
6. Deterministic 0/3/6/9 browser evidence.
7. Actual Step 5 Run-button walk and overview-only screenshots.
8. Larger per-field acceptance with focussing hidden.

## Delivery and safety

- Work only on `codex/smart-viewer-integration-cleanup`; never commit or push
  the user's original branch.
- If Smart Viewer needs a change, use a separate branch in its repository and
  pin the tested commit from the Microscopy cleanup branch.
- Make small checkpoint commits with the associated tests/evidence named in
  each commit message.
- Refresh the verified Git bundle after substantive checkpoints until GitHub
  authentication permits normal pushes.
- Push the cleanup branch and use a draft PR for review; do not merge it as part
  of this work.
- Commit the final screenshot evidence and its manifest so the visual proof is
  reviewable rather than transient.

## Current status

- Claude's review and handover have been read and checked against both codebases.
- The original plan's large engine-module port has been removed.
- The corrected first action is the real-Viewer baseline measurement.
- No implementation from the copied viewer has been adopted on this branch.
- The integration is not yet claimed to work; it must pass the gates above on a
  clean process using the pinned separate Smart Viewer.
