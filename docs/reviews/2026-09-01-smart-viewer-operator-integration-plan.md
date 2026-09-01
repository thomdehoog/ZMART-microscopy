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
3. A folder opened when it contains one store is watched by Smart Viewer 0.2.
   As later stores land, `GET /api/config` adds them to the same dataset number
   and the same acquisition row. A measured synthetic run grew from one to four
   `/data/0/...` sources without closing or reopening the folder.
4. The operator bridge froze the config returned by the first
   `/api/stores/open` call. It therefore kept handing the page one source even
   after Smart Viewer correctly reported four. Its close/reopen-on-the-second-
   store workaround fights Viewer 0.2's watch contract and is removed.
5. Claude's `d84c6848` change correctly distinguishes several stores in one
   Viewer dataset from older dataset generations. Its six focused checks pass,
   three fail against the old one-address rule, and real Viewer output confirms
   all stores in one watched acquisition share `/data/N/`. That reduction fix
   is necessary but is not sufficient unless the bridge reads the live config.
6. Opening an already multi-store folder creates one session scene. Reopening a
   grown folder currently reuses that scene without redeclaring it: in a direct
   Viewer 0.2 check the disk grew from two stores to three while `zarr.json` and
   `tiles.json` remained at two. Relinking is therefore not a valid live-growth
   mechanism for a plain positions folder.
7. `/api/measure` exists in Smart Viewer 0.2 and not in the copied server under
   `viz_studio/backend/`. A working histogram and Auto control are useful
   provenance checks as well as UI checks.
8. The cross-engine plane-selection failure predates Claude's seven commits. It
   is existing debt, not evidence that those commits introduced a regression.
9. At baseline the Microscopy and Viewer repositories both declared the Python
   distribution name `zmart-viewer` (versions 0.1.0 and 0.2.0 respectively).
   The cleanup branch now names Microscopy `zmart-microscopy`; a fresh-install
   provenance gate still has to prove that the real Viewer remains selected.
10. The first kidney screenshot claim was false. The browser check silently
    skipped every planned field whose projected box was outside the screenshot,
    so zero examined fields satisfied an "every field" assertion. Its
    `overview-only` shot was zoomed inside the image and could not establish
    registration. Neither image is accepted as evidence.
11. The whole-plate screenshot from Claude's evidence branch measures a picture
    of approximately the right 3 x 3 physical extent, but translated about
    `+23.3 mm` in x and `+29.4 mm` in y from the plan. The slide scale itself is
    correct. This narrows the remaining registration fault to a translation,
    not a scale or composition failure.
12. That translation is close to, but not equal to, the mock's centred-carrier
    origin (`22.5 mm`, `27.5 mm` for a 75 x 25 mm slide on a 120 x 80 mm
    stage). This is a diagnostic lead, not a fix. No origin is added, removed,
    or hard-coded until the live plan point, carrier origin, stored OME-Zarr
    translation, engine image bounds, and both screen projections are recorded
    in one coordinate trace.
13. The engine's opening view replaced the workflow's whole-plate Fit in the
    failed run. That hid the translation and made all planned boxes off-screen.
    View preservation and registration are therefore separate assertions even
    if one code path ultimately caused both.
14. The current cleanup checkpoint preserves Smart Viewer 0.2's data shape:
    three logical channel rows, each retaining all of its spatial position
    sources. Focused Python tests, panel tests, a production build, and a
    visually inspected panel screenshot pass. This fixes the measured 27-row
    flattening fault; it does not yet prove kidney registration.

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

### Canonical reversible Z-coordinate model

Step 5 is a two-dimensional presentation. Its shared display `z=0` is an
overlay anchor, not the microscope stage's zero and not a registered specimen
datum. This model applies uniformly to every acquisition type, including
`overview`, `focussing`, and `target`; no acquisition name selects different Z
arithmetic.

- Every source declares one source-local anchor-plane voxel centre. Its stored
  transform maps that centre to shared display `z=0`; sources that overlap in
  2-D do not need equal raw acquisition Z.
- A single-plane source anchors on its only voxel centre. A stack names an
  explicit reference/focus plane. If a legacy stack lacks that declaration,
  its fallback is resolved and recorded once while the source/scene is built;
  source load order must never choose it adaptively.
- Re-anchoring preserves source-local plane order, signed spacing, units, axis
  direction, and the selected anchor. In index notation, a source with signed
  spacing `s` and anchor index `a` uses `z_display(i) = (i - a) * s`.
- Raw stage/focus Z remains recoverable provenance. It is not treated as
  registered specimen Z, and no 2-D display transform may erase or relabel it
  as such.
- Z placement has one authority: the source transform produced when the store
  or scene is declared. The Viewer selects navigation plane `z=0` for the 2-D
  presentation but does not independently offset a layer transform.
- Navigation state and source transforms remain separate. Moving the depth
  control selects a source-local plane; it does not rewrite placement.
- Acquisition draw order and visibility remain independent presentation state.
  Putting a target above an overview, or hiding focussing, does not alter any
  source's anchor or Z transform.

Future physical 3-D placement is deliberately outside this delivery. It
requires validated Z scale and direction, an explicit anchor, calibrated stage
Z, and a specimen datum. Until those exist, neither this plan nor its evidence
claims that raw acquisition Z places sources in registered specimen 3-D.

For the present failure, the captured trace proves only the voxel-centre
boundary: the flat source renders at `z=0`, while `z=0.5` samples its boundary.
The current work package corrects that boundary and records the reversible
model; it does not introduce a broader 3-D placement scheme.

Focused gates for this model are:

1. every 2-D source anchor evaluates to display `z=0`, including sources with
   different raw acquisition Z, parameterized across `overview`, `focussing`,
   and `target`;
2. a stack's internal signed spacing, plane order, units, and direction remain
   unchanged by anchoring, parameterized across the same acquisition types;
3. original plane-centre Z and requested focus Z are recoverable from
   provenance, explicitly marked as not registered specimen Z;
4. a legacy fallback, when needed, is present in source/scene metadata before
   Viewer loading begins.

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

### Immediate execution sequence (no speculative patches)

The next implementation work follows this sequence exactly. A failed gate
stops the sequence; it does not trigger a nearby-looking coordinate patch.

1. **Make the evidence test capable of failing.** Require exactly nine planned
   fields to be examined. An off-screen or unprojectable field is a failure,
   never `continue`. Record the source count, bounds, view, and visibility in
   the evidence manifest. Keep the previously copied evidence spec uncommitted
   until these assertions are repaired.
2. **Reproduce on the cleanup branch.** Run the real Smart Viewer 0.2 server and
   actual Step 5 kidney workflow from a clean process. Capture a whole-plate
   before image arrival and after 1 and 9 positions. Do not infer cleanup-branch
   behavior from Claude's branch, because its canvas/view commits differ.
3. **Take one coordinate trace at the failure.** For the first and last planned
   fields, record in micrometres:
   - carrier-local plan centre;
   - `carrierOriginUm()` and the corresponding absolute stage centre;
   - the OME-Zarr level-0 scale and translation written for that position;
   - Smart Viewer/Neuroglancer source bounds;
   - the plan's stage-canvas screen projection;
   - the same physical point's image-engine screen projection.
4. **Name the single owner of the translation.** Use the trace to identify the
   first boundary where equal physical points diverge. Fix only that boundary:
   writer metadata, Viewer source transform, adapter transform, or overlay
   projection. Do not compensate in a later layer for an earlier error.
5. **Protect the whole-plate view independently.** Prove that first and later
   source openings do not replace an operator-selected Fit. If the registration
   trace is correct while the camera moves, fix view ownership separately.
6. **Run non-vacuous visual acceptance.** Produce 0/3/6/9, whole-plate,
   overview-only, and kidney-close-up screenshots. The test must report nine of
   nine examined ROIs, nine of nine textured ROIs, registration error below the
   declared tolerance, three overview channel rows, and a source/tile ledger
   accounting for all nine positions per channel at completion. This may be
   nine placed sources or one composed scene whose ledger contains nine tiles.
7. **Only then review the remaining Claude candidates.** Adopt an individual
   change only when a current failing test demonstrates its need. Never merge
   `claude/viewer-port-remaining-steps-ofm5qp` as a unit.

The completion claim is deliberately binary: until steps 1 through 6 pass on
the cleanup branch, the PR remains draft and its description says that Step 5
registration is unresolved.

### Work packages and stop conditions

| Package | Permitted work | Required proof before continuing | Stop condition |
| --- | --- | --- | --- |
| A. Preserve Viewer data shape | The already-reviewed bridge, poll, channel-row, and multi-source adapter changes | Focused Python and JS checks; production build; panel screenshot with `overview 3` and one row each for channels 0, 1, and 2 | Any field URL is discarded, any position becomes its own channel row, or the poll can block longer than its interval |
| B. Repair the evidence harness | Assertions, diagnostics, screenshot timing, and evidence manifest only; no production transform change | Deliberately reintroducing the known translated/off-screen state fails because fewer than nine ROIs are examined or registration exceeds tolerance | The test can pass with zero ROIs, a full-frame tissue crop, a blank whole-plate shot, or an unverified eye icon |
| C. Record the coordinate trace | Read-only browser/bridge instrumentation and metadata parsing | One table traces two planned fields through carrier, stage, Zarr, Viewer, engine, and screen coordinates | Any coordinate is inferred from a label, screenshot scale, or dataset number rather than read from the running system |
| D. Correct registration | The smallest boundary identified by package C, plus a regression test | All nine plan/image centres and bounds agree in physical and screen space; kidney pixels occupy those same ROIs | The proposed change applies a compensating offset after the first divergence, hard-codes the current slide origin, or changes scale to hide translation |
| E. Preserve view ownership | Opening-view and Fit behavior only, independently tested from registration | Whole-plate projections before and after 1/9 and 9/9 arrivals remain equal unless the operator requested a new view; pan and zoom still work before acquisition | Image arrival silently zooms away from the carrier or two components both write the view |
| F. Prove Step 5 | Real Viewer 0.2, actual kidney mock, deterministic partial bridge, and actual Run button | Complete screenshot set plus machine-readable manifest; overview-only and three-row panel state agree with rendered pixels | Any screenshot was taken against the copied Viewer, any intermediate count was guessed, or any unexpected request/error is ignored |
| G. Cleanup and delivery | Remove unreachable stand-ins, document install, and update the draft PR | Fresh environment selects Viewer 0.2, `/api/measure` works, focused and browser suites pass, branch is clean | A copied Viewer becomes runtime-reachable, PR wording overstates evidence, or an unrelated Claude commit enters the diff |
| H. Smart Viewer-inspired histogram and layer UX | Operator-native requested state, abortable real measurements, Viewer-like histogram interactions, acquisition/channel presentation, and observed-state reconciliation | Focused interaction/state tests, production build, real Viewer reference screenshots, corresponding Operator screenshots, and unchanged source-transform records | A full Viewer page/component is copied, stable source growth remounts the Viewer, a stale/failing measurement moves the window, engine state silently disagrees, or any UI action changes a source transform |

Packages are sequential. In particular, production coordinate code cannot
change during B or C. That separation ensures the failing test and coordinate
trace describe the original fault rather than a partially corrected version.

### Required coordinate trace

The trace is a checked-in machine-readable record and a human-readable table.
For plan positions 0 and 8 it contains these values, with units and coordinate
frame named for every pair:

| Boundary | Required value | Expected relationship |
| --- | --- | --- |
| Workflow plan | carrier-local centre `(x, y)` and `frameUm` | Comes directly from `__theStageCanvas.plan()` |
| Carrier placement | absolute-stage carrier origin `(ox, oy)` | Comes directly from `carrierOriginUm()` |
| Acquisition request | absolute-stage centre | `plan + carrier origin`, exactly once |
| Position store | level-0 OME-Zarr `(y, x)` scale and translation | Translation is the absolute-stage top-left of the written frame |
| Smart Viewer config | acquisition, channel, all source URLs, dataset generation | Three logical channels; all nine physical positions accounted for |
| Engine | per-source physical bounds and aggregate acquisition bounds | Bounds contain the same absolute-stage centres as the stores |
| Stage canvas | screen projection of carrier-local plan centre | Uses the carrier-owned view |
| Picture engine | screen projection of the matching absolute-stage centre | Equals the plan projection within the declared tolerance |

The first row where the expected relationship fails owns the correction. A
later layer is not allowed to compensate for it.

### Evidence manifest requirements

Every accepted screenshot has a neighbouring JSON record with:

- Microscopy branch and commit;
- Smart Viewer import path, version, and commit;
- screenshot name and UTC timestamp;
- planned, landed, examined, and textured ROI counts;
- plan bounds, image aggregate bounds, and maximum registration error in
  micrometres and screen pixels;
- acquisition headings, logical channel rows, and position/tile count per
  channel;
- requested and engine-observed visibility for focussing and overview;
- current view centre and zoom before and after the relevant arrival/action;
- required metadata/chunk request totals, unexpected failures, browser errors,
  bridge errors, and worker errors.

The screenshot and record are one artifact: neither is accepted alone.

### Commit boundaries

| Commit | Contents | Must not contain |
| --- | --- | --- |
| 1. Viewer data shape checkpoint | Verified bridge refresh, bounded timeout, three logical channel rows, all spatial sources, focused tests, and rebuilt bundle | Registration claims or the flawed kidney evidence spec |
| 2. Canonical plan correction | This plan and the corrected review statement rejecting the false-positive screenshots | Production code |
| 3. Failing evidence and coordinate trace | Non-vacuous test, diagnostic hooks, and a captured failing trace | A coordinate fix |
| 4. Measured registration fix | One boundary correction and focused regression tests | Panel rewrites, copied Viewer internals, or unrelated Claude changes |
| 5. View preservation | Only if independently failing after registration; Fit/opening-view fix and tests | Registration compensation |
| 6. Acceptance evidence | Passing manifest, 0/3/6/9, whole-plate, overview-only, close-up, and test output | Unreviewed implementation changes |
| 7. Runtime cleanup | Provenance/install guards and removal or quarantine of obsolete runtime paths | New viewer behavior |
| 8. Histogram/layer UX plan | Reference inspection, visual/behavior inventory, and package-H gates | Production code or revised Step 5 evidence |
| 9. Operator panel state and hierarchy | Stable requested state, group/channel/selection/colour/opacity persistence, observed-state reconciliation, and focused tests | Histogram interaction rewrite or coordinate changes |
| 10. Histogram interaction and measurement lifecycle | Axis/window controls, click/drag/pan/wheel/reset, Auto/Log, abort/stale/failure behavior, and focused tests | Source composition, navigation, or coordinate changes |
| 11. Panel UX evidence and production bundle | Real Viewer reference, comparable Operator states, overview-only/focussing-overlay screenshots, JSON records, browser gates, and rebuilt bundle | New behavior not covered by the preceding commits |

Each commit is reviewable and revertible on its own. If a package produces no
failure, its implementation commit is omitted rather than manufactured.

### Explicit prohibitions

- Do not merge either Claude integration branch wholesale.
- Do not copy Smart Viewer 0.2's `engine.js`, `scene.js`, `live-refresh.js`, or
  `LayerPanel.jsx` into Microscopy.
- Do not use dataset numbers as acquisition identity.
- Do not restore the 30-second close/reopen timer.
- Do not hard-code `22.5 mm`, `27.5 mm`, the measured `23.3 mm`, or `29.4 mm`.
- Do not trust panel eyes, scan completion, HTTP 200, or a non-white crop as
  pixel/visibility/registration proof by themselves.
- Do not skip off-screen fields in an acceptance assertion.
- Do not let image arrival replace an operator-selected Fit silently.
- Do not call the PR ready while any required evidence record is absent.

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

The decisive question is not whether there is one URL. During a live plain-
folder acquisition, Smart Viewer deliberately exposes one stable dataset with
one placed source per landed position. The decisive question is whether the
overview acquisition's combined measured bounds cover all nine planned fields
in the correct coordinate frame and every source contributes rendered pixels.

### 2. Follow the evidence branch and stop when it works

| Baseline result | Next action |
| --- | --- |
| Viewer is not running, import provenance is wrong, or `/api/viewer` reports an error | Fix only environment/package wiring, restart from a clean process, and repeat Step 1. |
| One overview acquisition with nine same-dataset sources and correct combined bounds | This is Smart Viewer 0.2's expected live-folder result. Proceed directly to pixel, visibility, and view-state acceptance. |
| One composed overview source with correct nine-field bounds | Valid for a folder first opened after several positions already exist. Proceed directly to acceptance; do not force it during live growth. |
| One overview source with single-field or otherwise wrong bounds | Check whether the bridge froze its first config. If not, inspect input coordinate metadata and the emitted source/scene. |
| Multiple dataset generations under one overview heading | Keep every source in the newest dataset number and remove the integration behavior that keeps reopening the folder. |
| Correct source and bounds, but absent/white pixels | Inspect the operator adapter's layer state, shader/window, visibility, selected z plane, and view fit. Do not rewrite the Viewer server. |
| Correct final picture, but live additions fail | Isolate close/reopen-on-second-position and `/api/announce` behavior with a two-then-nine-position server test before changing publication logic. |

If the defect is in Smart Viewer itself, fix it on a separate Smart Viewer
branch with its upstream tests, then pin Microscopy to the tested Viewer commit.
Do not hide an upstream defect with operator-specific source rewriting.

### 3. Keep the operator seam thin

The baseline proved that the current `{url, name}` reduction discarded fields
and that the bridge never refreshed it. For the present adapter, keep the seam
minimal: read Smart Viewer's current config on the existing operator poll,
group every image source by acquisition, and retain every URL belonging to the
newest Viewer dataset number. Preserve only fields the operator demonstrably
consumes:

- stable acquisition/group and channel identity;
- every source belonging to the channel;
- spatial position and dimensions needed by the adapter;
- display window, colour/LUT, opacity, and requested visibility;
- source revision identity when Smart Viewer supplies it.

Dataset numbers are used only to separate an obsolete opening from the several
stores of one current opening; they are not acquisition identity. Do not make
the page rediscover metadata the Viewer has already classified. Keep a contract
fixture shaped like real Smart Viewer 0.2 output so the two sides cannot
silently drift.

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
| `d84c684` | Keeping every field in the newest Viewer dataset instead of one URL | Adopt the narrow source reduction and its regression checks; do not adopt the 30-second relink machinery surrounding it. |

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

The focused real-server test establishes the Viewer 0.2 sequence:

1. open the positions folder once when its first store lands;
2. announce every later landing;
3. read `GET /api/config` on the operator's existing 1.5-second poll;
4. keep the stable dataset open while Smart Viewer adds the new position
   sources to it;
5. never close/reopen merely because the folder grew.

This is Smart Viewer's own watched-folder implementation. A 30-second relink
timer is neither required nor safe: it delays short scans, revokes source URLs,
and can replace a growing dataset with a session scene whose tile ledger no
longer grows.

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

### 8. Smart Viewer-inspired histogram and layer UX

This is a separate, reversible work package after the coordinate, source-
lifecycle, and Step 5 proof. Its inspection record is
`2026-09-01-smart-viewer-panel-ux-inventory.md`. It does not replace or weaken
any earlier evidence.

Smart Operator owns requested panel state by stable acquisition/channel key:
visibility, colour, opacity, window, histogram axis, Log state, selection, and
collapsed groups. Engine-observed visibility/window/weight are read through the
adapter and retained separately for inspection. A mismatch is visible and the
requested state is deterministically reapplied; observed state never silently
becomes a second UI authority.

Stable acquisition growth continues through `viewer.addSources` and does not
remount the Viewer or panel. If the acquisition/channel shape genuinely changes
and the existing scene must be replaced, the new panel receives the same
operator-owned state object and restores every surviving channel by key.

Histogram interaction follows the proven Viewer 0.2 contract:

- a six-pixel edge hit zone drags one window edge;
- a background drag pans only the brightness axis;
- the wheel zooms the brightness axis toward the pointer;
- double-click resets the axis frame without measuring or changing the window;
- Auto is a one-shot real `/api/measure` request and Log changes count heights,
  never brightness positions;
- superseded measurements are aborted or ignored by generation and operator-
  action revision;
- a failed or empty measurement is shown and leaves the current window intact.

The layer panel uses the same acquisition/channel visual vocabulary as Viewer
0.2 while retaining Operator-native wiring. Acquisition eyes gate a complete
group without erasing per-channel requests. Overview, focussing, and target are
independent. Overview remains the base map and focussing the diagnostic overlay;
panel ordering is not source placement.

Package H is coordinate-inert. Its tests snapshot source matrices and canonical
Z anchors before and after visibility, selection, collapse, and order actions.
Every 2-D reference voxel centre remains at display `z=0`; stack geometry and
raw acquisition/stage Z provenance remain untouched. No physical 3-D placement
is implemented or claimed.

## Acceptance gates

All gates are required.

### Server, data, and adapter gates

- Provenance records Smart Viewer 0.2 at the pinned source path/commit.
- Step 5 writes nine distinct overview position stores for the 3 x 3 plan.
- Smart Viewer returns separate `overview` and `focussing` acquisitions.
- The overview resolves to one acquisition whose combined bounds cover all
  nine planned positions. During live acquisition this is normally nine
  placed sources under one stable Viewer dataset number; a completed folder
  opened later may instead be one composed scene source.
- Every required overview metadata and chunk request succeeds. Any expected
  format probe failure is named and allow-listed rather than ignored broadly.
- Neuroglancer reports loaded bounds with no layer error or wedged open.
- Stage-plan and acquired-image projections agree to less than one screen pixel.
- Every 2-D source's declared anchor maps to display `z=0`; stacks retain their
  signed source-local spacing and raw acquisition Z provenance.
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

### Histogram and layer-panel UX gates

- Histogram edge drag, background pan, wheel zoom, double-click reset, typed
  axis/window values, and sliders are exercised as browser interactions.
- Auto and Log use real Viewer `/api/measure` data; Log changes bar heights but
  not x positions. A superseded or failed measurement cannot move the window.
- The selected acquisition/channel, eye, colour, opacity, window, axis, and Log
  state survive stable source growth and any necessary panel rebuild.
- Acquisition eyes hide/show complete groups while preserving every channel's
  requested choice. Overview, focussing, and target are parameterized in the
  same tests.
- Requested and engine-observed state are separately inspectable and converge
  without remounting the Viewer.
- Visibility, selection, collapse, panel order, and drawing order leave every
  source matrix and display-Z anchor unchanged.
- The production browser evidence includes the real Viewer 0.2 reference,
  comparable Operator histogram/selection/group states, overview-only,
  focussing-overlay, and the rebuilt production page.

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
2. A direct watched-folder contract proving `/api/stores/open` at one position,
   later landings, `/api/announce`, and `GET /api/config` grow one stable Viewer
   dataset from one source to nine.
3. Microscopy's engine-boundary and cross-option contract tests, carrying the
   known plane-selection debt explicitly until fixed.
4. Focused bridge tests for import provenance, first/second/later position
   publication, source bounds, and rerun identity.
5. Panel visibility, measurement, contrast, and empty-canvas view tests.
6. Deterministic 0/3/6/9 browser evidence.
7. Actual Step 5 Run-button walk and overview-only screenshots.
8. Larger per-field acceptance with focussing hidden.
9. Panel requested/observed state tests parameterized across overview,
   focussing, and target.
10. Histogram pointer, value, Auto/Log, stale-response, and failure browser
    tests against the real Viewer server.
11. Coordinate-invariance snapshots, production build, and the separate panel
    UX screenshot manifest.

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

- Claude's review, handover, and fault reports were read as context and checked
  against both codebases. Neither Claude integration branch was merged; only
  independently reproduced, narrowly bounded behavior was carried across.
- The coordinate trace found the first divergence at flat-source Z sampling:
  the only voxel centre is `z=0`, while `z=0.5` is its boundary. The production
  correction is limited to that boundary. No carrier-origin subtraction or
  other XY compensation was added.
- The reversible 2-D display-anchor model now applies without acquisition-name
  special cases to `overview`, `focussing`, and `target`. Every declared anchor
  maps to display `z=0`; stacks retain signed spacing, plane order, direction,
  and raw acquisition/focus Z provenance. No physical 3-D registration is
  implemented or claimed.
- Smart Viewer 0.2 keeps three overview channel rows with all nine spatial
  sources behind each row. The bridge opens each positions folder once,
  announces later landings, refreshes `/api/config`, and grows stable engine
  sources without replacing the Viewer or the operator's view and visibility.
- Acquisition order is presentation state, not geometry. The accepted evidence
  uses overview as the base and focussing as the diagnostic overlay; reversing
  that order is valid but can obscure overview pixels and therefore needs its
  own visibility/blending proof. Hiding focussing through the operator panel
  leaves every overview field visible and does not change either source's Z.
- The repaired evidence requires exactly nine projected ROIs; an off-screen or
  unprojectable ROI fails. The accepted 0/3/6/9, actual Run-button,
  overview-only, whole-plate, and kidney-close-up records are under
  `docs/reviews/evidence/2026-09-01-smart-viewer-step-five/`. The complete runs
  examine and texture all nine ROIs, keep maximum projection error below
  `0.071 px` (below `2.83 µm`), and report no unexpected request, browser,
  worker, or bridge error.
- Histogram and Auto now have direct evidence: selecting overview channel 0 and
  pressing Auto both receive successful responses from the separate Viewer's
  `/api/measure`; the evidence records a new request on the Auto press and 66
  rendered histogram bars.
- Whole-plate Fit survives first and later image arrivals unless the operator
  explicitly requests Fit. Empty-canvas pan/zoom, panel visibility, scan-under-
  plan projection, and the full operator walk pass independently.
- The larger acceptance examines 54 of 54 six-well overview fields with
  focussing hidden; every field contains non-uniform kidney texture.
- Package G is complete: `viewer_service.py` requires the separate
  `zmart-viewer` 0.2.0 distribution, rejects in-repository copies and unproved
  releases, the copied `viz_studio/backend/` and `viz_studio/frontend/src/`
  trees are explicitly reference-only, and the fresh-machine setup pins Viewer
  commit `9ff10b04e803fbe2a71a1735a8065a845ea803dd`.
- Final verification on 2026-09-01: 28 upstream Viewer API/data tests passed
  (four standalone-page pixel tests skipped because that separate page is not
  built), 103 focused Microscopy Python tests passed, 365 JavaScript unit tests
  passed with 15 intentional skips, the production build passed, and all eight
  relevant Microscopy browser tests passed. The isolated install selected
  Viewer 0.2.0 from the pinned sibling checkout and reached `/api/measure`.
- Package H is complete as a separate UX-similarity package. The real Viewer
  0.2 panel and its tests were inspected at `9ff10b0`; the concise comparison is
  in `2026-09-01-smart-viewer-panel-ux-inventory.md`. Its components were too
  coupled to the complete Viewer application to be a clean dependency, so the
  proven interactions are implemented behind the existing Operator panel and
  engine-adapter interfaces rather than copying or mounting the Viewer page.
- The Operator now owns stable requested acquisition/channel state while
  engine-observed visibility, window, opacity, sources, and mismatch history
  remain separately inspectable. Acquisition eyes preserve individual channel
  requests; selection, colour, opacity, window, axis, Log, and collapse survive
  stable source growth and panel reconstruction. Later sources keep the same
  Viewer instance.
- Histogram edge drag, background pan, wheel zoom, double-click reset, typed
  values, sliders, Auto, Log, pointer feedback, stale-response cancellation,
  and visible failure behavior pass as browser interactions. Auto and initial
  measurement use unmodified responses from the real Viewer 0.2
  `/api/measure`; a failed or superseded response leaves the operator window
  unchanged.
- Package H verification on 2026-09-01: all 365 JavaScript unit tests passed
  with 15 intentional skips; all 12 focused panel/reference/production browser
  tests passed; the real live-bridge source-growth and whole-plate Fit browser
  regression passed; and the production bundle rebuilt successfully. Matrix
  snapshots, including Z, are exactly equal before and after group/channel
  visibility actions. No coordinate or Z-placement production code changed.
- The five visually inspected Package H captures and adjacent JSON records are
  under `docs/reviews/evidence/2026-09-01-smart-viewer-panel-ux/`. They show the
  real Viewer reference, the comparable Operator selection/histogram state,
  focussing overlay, overview-only state, and the rebuilt production page. They
  explicitly link to rather than replace the accepted real-kidney 0/3/6/9,
  whole-plate, overview-only, and close-up Step 5 evidence. The UX-similarity
  gates pass; pixel-identical styling and identical component internals are not
  claimed.
