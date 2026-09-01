# Viewer delivery implementation — 50% review checkpoint

Date: 2026-09-01

Status: the first half of the core migration chain is implemented for review.
The compatibility-breaking half and every compact-picture experiment remain
unauthorised.

Based on:

- the design revision at `f1e7190a`;
- the first review at `48f72d64`;
- the follow-up review at `e73aa7f1`;
- ZMART Viewer 0.2.0 at `9ff10b0`;
- the Viewer implementation on `codex/viewer-delivery-50-percent`, commit
  `d243736`;
- the ZMART-microscopy implementation in the commit containing this document.

## What “50%” means

“50%” now means three of the six ordered migration packages are implemented,
plus the server/config portion of the fourth:

- V1 is implemented: no pixels produces null windows and a visible waiting
  state, including a real-browser test;
- V2 is implemented for ordinary position collections and their composed,
  declared, baked, ledger-reopened, and standalone-config path;
- M1 is implemented: an explicit acquisition description is validated,
  published atomically, and mirrored into every position;
- I1 has Python integration coverage through the served config, but the
  ZMART-microscopy embedded-panel half intentionally waits for M2;
- the old per-position window remains the compatibility fallback whenever no
  acquisition description exists, and for unresolved channels during M1;
- the real Leica source of channel descriptions remains deliberately unwired;
  the Python and HTTP/JavaScript paths accept explicit descriptions, but the
  operator workflow does not invent one from human-readable preset text;
- M2, M3, S1, H1, Z1, and compact `uint8` work have not started.

This is reviewable production code, not a claim that the migration is ready to
release. In particular, the two repositories must not be deployed as a new
writer/old Viewer pair, and `_a_window_onto` must not be removed at this
checkpoint.

The move from 50% to 80% should review and correct the implementation already
present, complete I1/M2, and close the named decisions with final interfaces and
accepted benchmark thresholds. It should not expand the product scope or begin
M3 before the compatibility gate is proven.

## Outcome this implementation must produce

The operator and standalone Viewer open the same one source. That source:

- is the existing Zarr/OME-Zarr composed picture;
- carries one display window per logical acquisition channel when one is
  honestly known;
- carries an explicit absent window while a live run has neither a declaration
  nor measurable pixels;
- never substitutes camera `min`/`max` for display `start`/`end`;
- reuses the existing decimated position levels and piece route;
- exposes one stable live identity and revision;
- leaves no unbounded session folders after crashes;
- can be measured on a real, read-only ZMART run in browser and PyWebView.

The immediate work does not create an 8-bit source. It prepares a truthful
window contract and a measured baseline that could justify or kill one later.

## Decisions already locked

1. The active operator image path remains ZMART Viewer. There is no
   `jpeg-pyramid-under` engine.
2. JPEG is out of this plan. A Zarr chunk address cannot return JPEG to the
   installed Zarr clients.
3. The composed source is where the standalone and embedded canvases read
   display windows.
4. An acquisition descriptor is where ZMART records how those windows were
   decided.
5. Position stores mirror a resolved acquisition window for interoperability;
   they do not independently decide it after migration.
6. “Nothing declared and nothing measurable” is an absent state, not
   `(0, 65535)`.
7. Decimation remains the production reducer. Other reducers are not part of
   this implementation.
8. Automatic persistent derivatives are bounded by ten per cent per
   acquisition and 5 GiB across managed roots.
9. Acquisition, source-local, presentation, and navigation Z remain separate.
10. A future compact source, if authorised, is one whole `uint8` picture chosen
    at open time instead of the scientific-dtype picture.

## Decisions deliberately open for the 50% review

1. Is `positions/<acquisition-type>/zmart-acquisition.json` the right durable
   descriptor location and filename?
2. Which acquisition preset or protocol field supplies explicit channel keys,
   labels, colours, and display windows on the real Leica path?
3. Should a resolved window become immutable for the run, or may an explicit
   operator action create a new acquisition/source revision?
4. Is a held cross-platform file lock the correct active-session marker for
   crash cleanup?
5. Are the proposed process-cold/warm thresholds and memory proxy defensible on
   the microscope PC?
6. Should a future compact `uint8` view show its controls in encoded `0…255`
   units or translate them back to recorded source units?
7. What package version or capability marker safely separates the Viewer-first
   release from the writer migration?

None of those is silently guessed in the implementation order below.

## Current code facts that shape the plan

### ZMART-microscopy

- `application/parts/storage/zarr_positions.py::position_store_from_record`
  converts every vendor capture into one OME-Zarr 0.5 position.
- The same function calls `_a_window_onto` per position and channel, so the
  current windows are not acquisition-wide.
- `application/framework/bridge.py::_keep_position_as_zarr` writes the
  position and then calls
  `application/parts/storage/viewer_service.py::a_position_landed`.
- The bridge opens the positions folder through `/api/stores/open`; it does not
  hand the Viewer channel metadata separately.
- `capture_positions` and the bridge scan call the driver's `acquire` with an
  acquisition type, label, and optional settings, but no stable display-window
  schema exists yet.
- `viz_studio/options/measure/run.py --data` owns and writes synthetic
  fixtures. It cannot point the comparison at a foreign read-only run.

### ZMART Viewer 0.2

- `zmart_viewer/compose.py::read_the_transfer` currently copies the first
  position store's `omero` block into the mosaic. It does not validate window
  agreement across positions.
- `Composer.bytes_for` returns bytes encoded exactly as the array description's
  dtype and codecs promise.
- `contrast.measure` and `contrast.display_window` return `(0, 65535)` when no
  pixels can be sampled.
- `Measurements._measure` assumes numeric flat and volume windows and writes
  them into frontend configuration.
- parts of the frontend already understand `window: null`, but
  `LayerPanel.jsx` still falls back to `{low: 0, high: 65535}` for its controls.
- `server.py::_a_session_folder` writes temporary scenes and replays beneath
  `~/.zmart-viewer`; shutdown removes only folders known to that live process.
- `measure/measure_cold_open.py` already measures the store reads needed to
  decide opening brightness.

## Proposed acquisition descriptor

The 50% proposal uses this exact location:

```text
<run>/positions/<acquisition-type>/zmart-acquisition.json
```

It is beside the collection it describes, not inside one position store. The
Viewer already receives that collection folder at its open door.

Proposed schema:

```json
{
  "schema": "zmart-acquisition-display/1",
  "acquisitionType": "overview",
  "channels": [
    {
      "key": "488",
      "index": 0,
      "label": "488",
      "color": "00FF00",
      "range": {"min": 0, "max": 65535},
      "displayWindow": {"start": 300, "end": 4200},
      "windowProvenance": {
        "method": "preset",
        "algorithm": null,
        "sampleCount": 0,
        "resolvedAtRevision": 0,
        "resolvedFrom": "acquisition-record"
      }
    }
  ]
}
```

`displayWindow` and `windowProvenance` may both be absent. `range` may be
present without them. That is the unresolved state.

Validation rules:

- schema and acquisition type are non-empty supported strings;
- channel keys are non-empty and unique;
- indices are unique whole numbers from zero through `count - 1`;
- label is non-empty; colour is six hexadecimal digits when present;
- all numeric values are finite;
- `max > min`, `end > start`, and the display pair lies inside the range;
- provenance is required exactly when a display window is present;
- a descriptor already published for a run is byte-semantically identical to
  every later attempt, or the new attempt is refused before another position
  is written.

Publication is atomic: write a sibling temporary file, flush it, then replace
the final name. A reader sees the old complete value or the new complete value,
never partial JSON.

The Viewer converts this description into ordinary OME metadata in the one
composed source:

```text
channel label/color/range/displayWindow
    -> omero.channels[index].label/color/window
windowProvenance
    -> attributes.zmart.displayWindows[index]
```

The composed source is the read authority. Position stores mirror the same OME
channel block so napari, Fiji, and direct store opens remain useful.

## Dependency order

```text
V1 Viewer understands an absent window
        |
        v
V2 Viewer reads/validates the acquisition descriptor
        |
        v
M1 Microscopy writes the descriptor; position behaviour unchanged
        |
        v
I1 End-to-end source authority and legacy tests
        |
        v
M2 Embedded waiting state and minimum Viewer capability enforced
        |
        v
M3 Position writer stops per-position window measurement

S1 Scratch lifecycle/accounting and H1 measurement harness can proceed after V1
Z1 Z evidence test can proceed independently
```

No arrow may be skipped. In particular, M3 cannot land before V1, V2, I1, and
M2 are deployed together.

## Work package V1 — “no window yet” in ZMART Viewer

Repository: `thomdehoog/zmart-viewer`, starting from `9ff10b0` or its reviewed
successor.

Checkpoint status: implemented at Viewer commit `d243736` for the Python
measurement/config path and standalone React panel, with a browser test over a
valid but pixel-empty live array.

### Behaviour

When no declared window and no measurable values exist:

- Python returns `None` for flat and volume display windows;
- JSON exposes `window: null`, `volumeWindow: null`, `histogram: null`, and
  `settled: false`;
- the layer may exist, but its panel says it is waiting for measurable pixels;
- contrast controls are disabled until a declared or measured window exists;
- no component displays `0…65535` as though the run chose it;
- after pixels land and the source revision advances, ordinary measurement
  supplies a provisional window and controls become active.

Camera range remains available separately as `range` for slider bounds after a
real window exists. It never becomes the window itself.

### Target files

- `zmart_viewer/contrast.py`
  - change the no-samples results of `measure` and `display_window`;
  - update their return annotations and docstrings;
  - make `Measurements._measure` preserve `None` without destructuring it.
- `zmart_viewer/server.py`
  - keep `/api/measure`'s empty answer distinct from a numeric window;
  - allow source configuration rows with null windows.
- `zmart_viewer/live.py`
  - preserve `_display_for`'s absent channel window through live rows.
- `app/page/src/LayerPanel.jsx` or the corresponding current frontend path
  - remove the unconditional `0…65535` display fallback;
  - render the waiting state and disabled controls.
- `app/page/src/scene.js`
  - continue omitting shader controls while no window exists;
  - verify that a later config/source revision installs them.

The ZMART-microscopy embedded panel is not changed in this Viewer commit. Its
compatibility is held by the still-present position windows until M2, when it
must gain the same absent/waiting behaviour before M3 removes those windows.

### Tests

- Change the missing/broken-store expectations in `tests/test_contrast.py` and
  `tests/test_harsh_omezarr.py` from `(0, 65535)` to `None`.
- Add a no-pixels channel case to
  `tests/test_brightness_is_measured_honestly.py`.
- Add a server-config assertion that the window is JSON null and not numeric.
- Add a browser test: empty live source shows “waiting for pixels”, then one
  landing produces a measured window without reopening the dataset.
- Keep existing declared-window, measured-window, volume-window, and foreign
  OME-Zarr tests green.

### Gate and rollback

Gate: no test, config document, or screenshot contains a numeric camera-range
window for the no-data state. A declared `0…65535` window remains valid only
when the source explicitly wrote both `start` and `end`.

Rollback is one Viewer commit: no ZMART-microscopy writer change has landed, so
the previous Viewer still sees the old position hints.

## Work package V2 — composed-source window authority

Repository: ZMART Viewer.

Checkpoint status: implemented at Viewer commit `d243736` for ordinary
position collections, composed declarations, baked group metadata, persisted
`tiles.json`, reopen, and standalone config. Review must still identify whether
the manifest-governed live-run path needs the same sidecar or correctly remains
under its existing acquisition-profile authority.

### Behaviour

`read_the_transfer(folder)` checks for `zmart-acquisition.json` before choosing
channel display metadata.

When the descriptor exists:

- validate it against the actual channel count and acquisition folder;
- publish its OME channel block and ZMART provenance into the composed source;
- persist it through `tiles.json`/the written mosaic so requests do not reread
  the collection on every piece;
- use the same metadata in linked, unbaked, baked, reopened, and live sources.

When it does not exist:

- compare the channel count, labels, colours, ranges, and windows of all
  position stores;
- refuse mismatched channel identity, count, labels, or colours;
- if only `start`/`end` disagree, preserve shared identity and range but omit
  the display pair from the composed source;
- if every display pair agrees, carry it as a legacy declaration with
  `resolvedFrom: "legacy-position-consensus"`;
- never select the first position merely because it sorted first.

### Target files

- Add `zmart_viewer/acquisition.py` for schema reading and validation. Keeping
  the format in one module prevents `compose.py` and the HTTP server from
  growing separate interpretations.
- `zmart_viewer/compose.py`
  - replace the first-`omero` loop in `read_the_transfer`;
  - extend `Mosaic` with acquisition display provenance;
  - preserve it in `the_mosaic_written_down` and
    `read_the_mosaic_as_written`;
  - include it in the group description returned by `Composer.group_json`.
- `zmart_viewer/building.py`
  - ensure built and governed pictures publish the same description before
    they can be opened.
- `zmart_viewer/loading.py` and `zmart_viewer/live.py`
  - verify every open door reaches the same described source.

### Tests

- Extend `tests/test_a_transfer_is_built_into_one_picture.py` with explicit,
  unresolved, legacy-consensus, and legacy-disagreement fixtures.
- Add a test proving store filename order cannot change the composed window.
- Add a channel-key/index mismatch refusal.
- Assert linked, unbaked, baked, and reopened descriptions contain byte-equal
  OME windows and ZMART provenance.
- Extend `measure/measure_cold_open.py` to count source-store reads with and
  without the descriptor. A declared window must remove pixel reads done only
  to choose opening brightness.

### Gate and rollback

Gate: the standalone config and composed store both report the descriptor's
window; a legacy disagreement reports no declared window and is measured
provisionally. No code path retains “first `omero` block wins”.

Rollback is safe while M1 still writes conventional position windows. The
descriptor is an ignored sidecar to older Viewer versions.

## Work package M1 — write the acquisition descriptor without changing pixels

Repository: ZMART-microscopy, this branch's repository.

Checkpoint status: implemented in the commit containing this document. Python
workflow calls and the live scan API accept explicit `channels`; neither derives
them from the current Leica reading. Resolved windows are mirrored, unresolved
windows retain the old M1 compatibility hint, and no-description behavior stays
unchanged.

### Behaviour

Add one validated model and atomic writer. Thread an optional channel
description from acquisition setup to the position collection. In this package
the existing `_a_window_onto` behaviour deliberately remains unchanged; M1 is
metadata plumbing only.

This lets V2 be tested on real workflow output before any compatibility hint is
removed.

### Proposed interfaces

New module:

```text
application/parts/storage/acquisition_description.py

validate_acquisition_description(value, *, acquisition_type, channel_count)
write_acquisition_description(folder, description)
read_acquisition_description(folder)
ome_channel_blocks(description, *, depth_max)
```

Proposed capture additions:

```text
capture_positions(..., channels=None)
run_overview(..., channels=None)
acquire_targets(..., channels=None)
/api/scan payload: optional channels
```

The final source of the real Leica values remains open for review. M1 accepts
only explicit values; it does not parse human-readable UI strings or infer a
window from exposure, gain, filenames, or the first field.

### Target files

- new `application/parts/storage/acquisition_description.py`;
- `application/parts/microscope/capture_run.py`;
- `application/workflows/target_acquisition/the_run.py`;
- `application/framework/bridge.py`;
- `application/parts/microscope/live.js` and backend contract if the operator
  path supplies channel descriptions;
- `application/parts/storage/zarr_positions.py` to accept, but not yet require,
  the validated descriptor;
- `application/parts/storage/viewer_service.py` only if the Viewer needs a
  hurry-up announcement after the descriptor is published.

### Tests

- New unit tests for schema validation, atomic publication, idempotent same
  value, and refusal of a changed value.
- Extend `application/parts/storage/test_zarr_positions.py` to prove an
  explicit acquisition window is mirrored exactly across bright and dark
  positions.
- Extend bridge and `capture_run` tests to prove channel identity follows the
  acquisition, not arrival or file order.
- Verify an absent channel description retains the old per-position behaviour
  in M1. This assertion is deleted, not changed, in M3.
- Verify acquisition failure/cancellation never publishes a partially written
  descriptor.

### Gate and rollback

Gate: two deliberately different fields produce position stores and one
composed source with the same explicit acquisition window. Without an explicit
description, behaviour is byte-for-byte compatible with the current writer.

Rollback removes a sidecar and optional arguments; pixel stores remain valid.

## Work package I1 — one authority end to end

Repositories: both.

Checkpoint status: partial. The descriptor reaches positions, the composed
group, a declared/baked source, its ledger, and standalone config in automated
tests. Embedded-panel waiting behavior and the final cross-repository browser
fixture remain behind M2.

Build a fixture using the real M1 writer and open it through V2. Assert:

```text
explicit acquisition descriptor
    == every position's mirrored OME window
    == composed source OME window
    == standalone Viewer config
    == embedded operator panel's as-written window
```

Then build a legacy fixture whose two positions declare different windows.
Assert:

```text
no first-position selection
composed source window is absent
Viewer provisional measurement is used after pixels are readable
Reset control says no declared window
```

Target integration tests:

- Viewer: `tests/test_the_window_a_run_asked_for_reaches_the_screen.py` and
  `tests/test_a_transfer_is_built_into_one_picture.py`;
- ZMART-microscopy: `application/viewer-panel-contrast.spec.js`,
  `application/the-window-step-by-step.spec.js`, and
  `application/framework/test_operator_bridge.py`.

Gate: the five equalities hold in both standalone and embedded screenshots.

## Work packages M2 and M3 — embed and enforce compatibility, then remove local decisions

M2 first updates `application/parts/canvas/viewer-panel.js` so a channel with
neither a declared nor measured window has no numeric working window. It shows
“waiting for measurable pixels”, disables its contrast controls, and must not
use the current `{low: 0, high: 65535}` fallback. Extend
`application/viewer-panel-contrast.spec.js` with the empty-live-source to
first-landing transition and prove that the embedded panel agrees with the
standalone Viewer throughout. This application change is required before M3,
not left as post-migration polish.

M2 chooses one reviewed compatibility mechanism:

- a minimum packaged Viewer version, or
- an explicit Viewer capability such as
  `acquisition-display-window-v1` plus `absent-display-window-v1`.

The current proposal prefers capabilities because the Viewer is installed from
a checkout and is presently optional in `environment.yml`. The operator startup
must refuse the integrated live canvas with a plain upgrade sentence when the
installed Viewer lacks either capability. It must not run the new writer
against an old near-black fallback.

After M2 is deployed, M3 changes
`application/parts/storage/zarr_positions.py`:

- resolved descriptor: mirror its channel window;
- unresolved descriptor: write `min`/`max` but omit `start`/`end`;
- remove `_a_window_onto` and its per-position percentile path;
- delete the temporary M1 compatibility assertion.

M3 tests two bright/dark positions with an unresolved descriptor and proves
neither stores a local display pair, while the composed source measures one
provisional acquisition-wide view after pixels exist.

Rollback boundary: M3 is not reverted independently to an older Viewer. Revert
the application and Viewer compatibility release as one tested pair.

## Work package S1 — session scratch lifecycle and accounting

Repository: ZMART Viewer. This package is independent of M1–M3 after V1 and can
land earlier.

### Proposed structure

Add `zmart_viewer/scratch.py` with one `ScratchSession` abstraction used by
scenes and replays:

```text
open(kind) -> session path plus a held lifetime lock
close() -> release and remove this process's sessions
sweep_orphans(kind) -> reclaim only unlocked session folders
managed_bytes() -> bytes by root and session
```

Each `session-*` folder contains a small owner document and a lock file. The
server holds an exclusive OS lock for its lifetime. Startup attempts the same
lock without waiting:

- lock unavailable: another process owns it; skip;
- lock acquired: no process owns it; resolve it under the exact managed root,
  reject symlinks, count bytes, remove, and log reclaimed bytes.

The final Windows/POSIX lock implementation is an explicit 50% review item.
PID-only deletion is rejected because PID reuse can identify the wrong process.

### Target files

- new `zmart_viewer/scratch.py`;
- `zmart_viewer/server.py::_a_session_folder`, server creation, and shutdown;
- replay and composed-scene call sites in `server.py`;
- the storage/status endpoint or measurement output that reports managed bytes.

### Tests

New `tests/test_session_scratch.py`:

- clean shutdown removes both current session roots;
- an unlocked orphan is swept at startup;
- a separately locked active session survives another server's startup;
- a symlink or escaped candidate is refused and its target survives;
- reclaimed and remaining bytes are exact;
- two server processes cannot delete one another's scratch;
- the 5 GiB root tally includes both scenes and replays.

Use small injected limits in tests. Do not allocate gigabytes.

### Gate

Killing a child Viewer process, then starting another, reclaims the first
process's folders and leaves a concurrently active third process untouched.

Enforcement of eviction priority beyond orphan cleanup moves to the 80% plan
after measured sizes are known. The 50% implementation must at least make every
managed root visible and bounded by a refusal rather than silently growing.

## Work package H1 — real-run adoption harness

Repositories: mostly ZMART-microscopy, reusing Viewer measurement scripts.

### Make a foreign run measurable

Extend `viz_studio/options/measure/run.py` with a separate read-only argument:

```text
--external-run /absolute/path/to/run
```

It does not change `--data`, does not write synthetic fixtures beside the real
run, and does not run synthetic-only suite rows against it. Add one named
real-run trace in:

- `viz_studio/options/measure/run.py`;
- `viz_studio/options/measure/drive.py`;
- `viz_studio/options/measure/data_server.py`;
- `viz_studio/options/measure/suite.py` or a new focused
  `real_run.py` if that keeps the concepts separate.

The server issues a scoped address for the chosen path. It validates and serves
read-only; it never rewrites metadata or pyramids.

### Trace and byte set

The trace is the ten-step open/pan/zoom/channel/live/reopen sequence from the
design. Count all HTTP response body bytes from the open request through the
final settled revisit:

- JSON descriptions;
- array metadata;
- image chunks, including absent/not-found answers;
- live-state and revalidation bodies;
- any retry response.

Record request method, status, content type, cache disposition, and body length
so a later compact comparison cannot choose a favourable subset.

### Mechanical timing definitions

- process-cold: new Viewer process, empty managed delivery cache, OS cache left
  as the machine provides it;
- warm: identical trace repeated in that process;
- useful opening picture: 90% of expected covered visible area at the opening
  level answered and settled, with at least one covered non-background piece;
- navigation latency: input event to the first settled frame satisfying the
  same visible-coverage rule;
- landing latency: publication marker time to first settled frame containing
  the new position.

### Memory proxy

Run 20 navigation cycles. Record:

- browser renderer process working set;
- GPU process working set where the engine exposes a separate process;
- JS heap before and after an explicit test-only GC when Chromium allows it;
- Python process working set.

Proposed gate: renderer plus GPU at most 1 GiB, and final-ten-cycle growth less
than 10% or 20 MiB, whichever permits more. If WebView2 cannot expose the same
breakdown, use process-tree working set and record that the proxy differs.

### Existing Viewer harnesses to call, not copy

- `measure/measure_cold_open.py`;
- `measure/measure_one_more_position.py`;
- `measure/measure_the_four_ways_of_serving.py`;
- `measure/measure_the_relinked_row.py`;
- `measure/measure_loading_per_format.py`;
- `measure/measure_compression_cost.py`;
- selected rungs of `measure/measure_a_ladder_of_surveys.py`.

Store raw JSON, environment, commits, and summary together. Do not transcribe
only median numbers into prose.

### Gate

The harness must first reproduce one known Viewer measurement within a
documented machine-dependent tolerance. Only then are new real-run results used
to authorise Phase 1 or the compact experiment.

The no-position-proportional-request assertion remains a regression test, not a
decision gate: the architecture already guarantees it.

## Work package Z1 — make the half-voxel evidence reproducible

Repository: ZMART-microscopy.

Extend:

- `application/the-window-step-by-step.spec.js` to photograph the same
  one-plane source sampled at its centre and at the reported boundary;
- `application/which-layer-draws.spec.js` to capture the source transform,
  requested world Z, selected local plane, and returned layer state.

Assertions:

- the sole voxel centre maps to shared world `z=0` and contains the expected
  texture;
- sampling the known upper boundary does not become the presentation default;
- all flat overlay anchors meet at `z=0`;
- raw acquisition/focus Z remains present in the record;
- no layer-level second Z translation exists;
- the existing `theMiddlePlaneOf` rule remains the legacy stack fallback.

The screenshots and numeric trace are committed test artifacts or reproducible
test output, not a chat transcript.

This package does not implement physical 3-D registration.

## Phase-0 execution after V1–Z1

Run these comparisons before any composer optimisation:

1. Viewer 0.2 baseline on the target machine and selected real runs.
2. V1–M3 with the declared window, using
   `measure_cold_open.py` before/after to bank the eliminated brightness reads.
3. Process-cold and warm traces for baked finished and unbaked live sources.
4. Repeated navigation memory trace.
5. Scratch bytes before, during, after clean shutdown, and after a killed
   process is swept.
6. Standalone and embedded visual/geometry comparison.

Provisional stop targets:

- warm useful picture within 2 seconds;
- process-cold baked/finished useful picture within 5 seconds;
- pan/zoom p95 within 500 ms;
- live landing p95 within 500 ms;
- memory within the proposed bound and stable over 20 cycles;
- managed scratch and cache within ten per cent per acquisition and 5 GiB
  globally;
- zero transient wrong pixels and zero silent fallback.

Process-cold unbaked time is reported but has no invented bound in this draft;
Viewer 0.2 already measured 13.1 seconds for its 10,000-position case. The 80%
plan must decide whether product requirements demand improving it.

If the existing Viewer meets the accepted targets, stop format work and embed
the one canvas.

## Future compact `uint8` experiment — explicitly not authorised

This section is only enough to review the boundary.

Proposed open-time choice:

```text
scientific: one source declared in the acquisition dtype
compact:    one source declared uint8, mapped from the resolved window
```

Likely Viewer target files if later authorised:

- `zmart_viewer/loading.py` for the explicit open choice;
- `zmart_viewer/building.py` for the chosen source description;
- `zmart_viewer/compose.py` for an output dtype and source-to-uint8 mapping;
- `zmart_viewer/library.py` and frontend configuration to label the source
  visibly as compact;
- tests proving one source at a time, exact geometry, revision invalidation,
  and refusal of unresolved channels.

The compact source declares its actual values as `uint8`, with OME range and
window `0…255`. A ZMART encoding block records the original source window and
algorithm. Whether the UI translates controls back into source units is open.

An experiment proceeds only if the phase-0 data show bytes or decoding are the
dominant remaining cost. It then needs both:

- at least 40% fewer total trace bytes;
- at least 20% improvement in the failing user-facing metric.

It must also meet all no-regression, registration, dim-feature, memory, and
storage gates. JPEG is not compared.

## Commit and release sequence

Each row is independently reviewable and leaves both repositories usable:

1. Viewer V1: absent-window model and UI.
2. Viewer V2: acquisition descriptor reader and legacy reconciliation.
3. Microscopy M1: descriptor writer, optional plumbing, legacy pixels
   unchanged.
4. Cross-repository I1: equality and legacy-disagreement evidence.
5. Viewer S1: scratch lock, orphan sweep, and byte accounting.
6. Microscopy/Viewer M2: capability or minimum-version enforcement.
7. Microscopy M3: remove per-position window measurement.
8. Microscopy H1: foreign-run trace and fixed byte set.
9. Microscopy Z1: voxel-centre visual/numeric evidence.
10. Evidence commit: phase-0 raw data and verdict.

No squash should hide which migration boundary introduced a failure. The two
repositories may use matching issue names, but each change is committed where
the behaviour is owned.

## Verification matrix

| Case | Declared source window | Position mirror | Composed source | UI | Compact allowed |
|---|---|---|---|---|---|
| Explicit preset | fixed | same fixed pair | same fixed pair | active | later, yes |
| Operator-approved | fixed + provenance | same fixed pair | same fixed pair | active | later, yes |
| Deterministic resolved measurement | fixed + algorithm | same after resolution | fixed | active | later, yes |
| Live, no pixels yet | absent | absent after M3 | absent | waiting | no |
| Live, measurable but unresolved | absent | absent | provisional measured | active, marked measured | no |
| Legacy, all positions agree | legacy consensus | existing | same + legacy provenance | active | no until migrated |
| Legacy, windows disagree | conflicting existing | existing | absent/provisional | measured, no Reset | no |
| Channel identity disagrees | conflicting | existing | refused | clear error | no |

## Failure and rollback rules

- A descriptor validation failure stops creation of the composed view, not the
  microscope acquisition; vendor files and already valid positions remain.
- A position conversion failure remains recorded on that capture as today.
- The integrated application refuses an incompatible Viewer before M3 semantics
  are used.
- Scratch cleanup never deletes a locked, symlinked, or out-of-root target.
- A benchmark failure stops the next optimisation phase; it does not loosen the
  threshold after the fact.
- Scientific-dtype opening remains the only production mode throughout this
  50% plan.

## What the next review must decide to reach 80%

1. Accept or replace the descriptor location and schema.
2. Name the real Leica/preset source for channel descriptions.
3. Choose version pinning or capabilities for M2.
4. Approve the absent-window JSON/UI behaviour across standalone and embedded
   canvases.
5. Choose the cross-platform scratch-lock implementation and startup grace
   policy.
6. Accept or replace the mechanical cold/warm, useful-picture, byte, and memory
   definitions.
7. Decide whether process-cold unbaked open has a product bound.
8. Confirm that the compact experiment remains unauthorised until phase-0
   evidence, and that JPEG remains out.

After those answers, the 80% plan should add exact API payloads, final model
types, final test names/fixtures, package/release versions, and the microscope
PC run sheet. It should not start implementation until that review is accepted.
