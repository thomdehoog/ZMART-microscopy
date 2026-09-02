# Independent review of the finished Viewer delivery migration

Date: 2026-09-02

## Verdict

**Revise before continuing.**

The compatibility handshake works, the acquisition description is published
before a scan moves, and the migrated position writer no longer invents a
display window from each position. Those are substantive improvements. The
finished end-to-end claim is nevertheless false in the operator path that will
receive every current real acquisition: unresolved multi-channel acquisitions
are reduced to one drawable channel, and the channel panel can report a
measured display window that it never applies to the drawing engine. The
drawing engine still has a fixed `0…4095` fallback of its own.

Two further completion claims are not met. The live/provisional wording is
derived from whether the currently served store has a written coarse level,
not from whether the acquisition can still grow, so its sentences are reversed
in the ordinary first-position and finished-composite cases. The scratch work
accounts for bytes but does not enforce either storage bound in the accepted
plan, and a failed Windows removal makes a renamed folder invisible to both
future sweeps and accounting.

I would not start phase-0 performance measurement or a compact `uint8`
experiment until the two operator-path blockers are fixed and covered by a
multi-channel integration test.

## Scope and revisions inspected

I reviewed fresh, separate checkouts and did not modify either implementation
branch:

- ZMART-microscopy `claude/viewer-delivery-to-100` at
  `053f84434f8bceb023c144cc73777e97503d5f06`, against base
  `b79fb46e9c57f174dd09f275c15e4eb207c462fa`.
- ZMART Viewer `claude/viewer-delivery-to-100` at
  `7a380793161e0fe7cde8b75714657236f7a22117`, against base
  `2b4338eb171f1adb5ff230793a56c2c52530a4c4`.
- The compatibility check used the actual old Viewer checkout at `9ff10b0`
  as well as the new Viewer at `7a38079`.

The microscopy review document itself names `4d9056f7` as the final code
revision. The requested review revision, `053f8443`, contains that code plus
the final test-number and independent-review documentation commits. I used
`053f8443`, as the request specified.

I treated the seven admitted gaps in the review brief as known facts, not new
findings. In particular, I do not report the existing five-axis placement
failure, the Neuroglancer stack-opening rule, the lack of a real Windows run,
the absent microscope-PC M3 evidence, the untested `toldAbout` seam, the five
pre-existing options failures, or the software-rendered storm hang as findings
below.

## Findings, ordered by consequence

### 1. Blocking: an unresolved multi-channel acquisition becomes one channel in the operator canvas

#### Facts

The current production state is the case most exposed to this defect. The
100% document says that no production preset supplies a resolved display
window, so every real acquisition is presently unresolved. For an unresolved
acquisition, `application/parts/storage/acquisition_description.py:299-330`
deliberately returns no OME channel blocks, and
`application/parts/storage/zarr_positions.py:144-159` therefore writes a
position without `omero.channels`. This omission is necessary: the real ngio
test confirms that a partial OME channel block is invalid.

The new Viewer does retain the channel description elsewhere. It puts channel
identity in `attributes.zmart.channels` at
`zmart_viewer/acquisition.py:208-255` and includes that metadata in a composed
source at `zmart_viewer/compose.py:1466-1482`. Its own `/api/config` also has
one image row per channel.

That information is then discarded at the boundary to the operator page.
`application/parts/storage/viewer_service.py:327-360` deliberately deduplicates
the Viewer rows to one `{url, name}` object per store. It does not preserve the
rows' channel names, indices, or colours. The embedded panel reads only
`ome.omero.channels` and otherwise constructs one fallback row at
`application/parts/canvas/viewer-panel.js:122-155`. The active Neuroglancer
adapter follows the same rule at
`viz_studio/options/neuroglancer-under/viewer.js:991-1044`: without a channel
list from the acquisition object or `omero.channels`, it creates one white
channel at index zero.

I ran a bridge-driven, one-position, three-channel scan with the new Viewer.
The scan wrote three TIFFs and one position store without error. The Viewer's
configuration contained three image rows named `channel 1`, `channel 2`, and
`channel 3`; `/api/viewer` exposed one source containing only `url` and `name`;
the served position had no `omero` block. I repeated it with two positions and
forced a composed relink. The composed source had three
`attributes.zmart.channels` entries and no `omero`, the Viewer configuration
still had three image rows, and the bridge still exposed one source without
channels.

A jsdom integration probe using the real `mountViewerPanel` made the loss
visible without relying on metadata inspection: an engine with three channel
layers and an unresolved source produced one panel channel row, named
`overview`.

The existing unresolved-composition test does not catch this because its
acquisition-description helper constructs one channel.

#### Consequence and inference

On the paired branches as delivered, a normal unresolved three-channel Leica
acquisition can write all three channels successfully while the embedded
operator canvas offers and draws only channel zero. The data remain on disk,
but two channels are silently absent from the live scientific view. This is a
release blocker.

The two internal reviews were right that invalid partial OME metadata must be
omitted. They were wrong that omission alone completes the contract. Channel
identity and count need a second, explicit route into the embedded consumer,
either from the Viewer's configuration or from ZMART metadata. That route must
be tested for both the first direct position source and a later composed
source.

### 2. Blocking: the panel and engine have different brightness authorities

#### Facts

The active engine is `neuroglancer-under` by default
(`application/workflows/target_acquisition/shared/stage.js:78-88`). When a
channel has no declared window, that engine independently measures a store and
falls back to a fixed `0…4095` window if measurement returns nothing
(`viz_studio/options/neuroglancer-under/viewer.js:845` and
`:991-1032`). A flat tile deliberately returns no measured window at
`viz_studio/options/brightness.js:125-139`, so the fixed fallback is reachable
with a readable image. The Viv adapters retain equivalent fallbacks.

The panel separately asks the new Viewer `/api/measure` for a window at
`application/parts/canvas/viewer-panel.js:189-256`. When that answer arrives,
`chooseRow` records it in the panel row at `viewer-panel.js:1271-1303`, but it
does not call `viewer.setChannel`. Only the later operator-action path
`takeTheWindow` sends a window to the engine (`viewer-panel.js:842-855`).

I exercised that seam with the real panel and an engine spy. The server answer
was a settled `1000…1001` window while the engine began at `0…4095`. The panel
displayed `min 1000` and the settled state, but made zero `setChannel` calls.
Thus this is not merely two implementations that happen to use the same
arithmetic; they can demonstrably disagree on one screen.

There is another stale fallback in the still-used comparison backend:
`viz_studio/backend/contrast.py:423-431` and `:525-528` return `0…65535` when
there are no samples. It is not the new Viewer's `/api/measure`, but it shows
that the repository-wide answer to question 1 is not “no”.

#### Consequence and inference

The operator can see controls that describe `1000…1001` while Neuroglancer is
actually drawing `0…4095`. More generally, the engine samples one middle tile
through Viv while the panel asks the Viewer backend over the requested box;
even non-flat images have no invariant forcing those answers to match. The
hard-coded fallback also contradicts the promised absent-window state: the
panel can say it is waiting while the engine is already using an unrecorded
guess.

This breaks I1, “one authority end to end.” The measured or declared window
shown by the panel must be the window applied to the engine. A regression test
should spy on the real panel/engine contract and prove that declared,
provisional, settled, waiting, flat, and unreadable cases never create a second
window authority.

### 3. High: the first-thirty-seconds brightness sentences do not describe whether the acquisition can still change

#### Facts

The bridge opens no source until the first position store is completely
written (`application/parts/storage/viewer_service.py:244-263`). It then keeps
that one position standing for as long as thirty seconds before a grown folder
may be relinked (`viewer_service.py:63-86` and `:269-300`). Consequently, the
documented “waiting for measurable pixels” state cannot occur before the first
field in the real integrated route: there is no source or panel yet.

The measurement state is based only on whether the currently served store has
a written coarsest level (`zmart_viewer/server.py:730-759` and
`zmart_viewer/contrast.py:331-340`). In my one-position live probe, the first
position was complete, so `/api/measure` returned `settled` with window
`1000…1001`, although the acquisition was the live source and could still add
positions. The panel hides the provisional sentence for that state at
`application/parts/canvas/viewer-panel.js:785-798`.

The converse occurred after a two-position scan had finished and was relinked
as a composed source: `/api/measure` returned `provisional`, because the
composed picture is derived on demand and has no physically written coarse
level. The panel maps that answer to “brightness measured from pixels acquired
so far,” even though acquisition had finished.

The requested mock walk cannot test these words. The pretend backend explicitly
returns no Viewer sources and no Viewer error
(`application/parts/microscope/mock.js:50-69`). No connected browser was
available in this review environment, so the exact DOM-to-pixel display of the
sentences is an inference from these API answers and the cited rendering code,
not a claimed visual observation.

#### Consequence and inference

For the ordinary first thirty seconds, the operator is not told that brightness
was inferred from only the first field. After a finished run is composed, the
operator can instead be told that more acquisition pixels are still expected.
Both sentences can affect whether a microscopist trusts or adjusts contrast.

“Settled” needs acquisition or source-revision liveness, not merely the storage
form of the source currently being served. If the intended product cannot show
a source before the first position lands, its prose and tests should say that
rather than promise a waiting state that the integration cannot reach.

### 4. High: scratch is accounted, but not bounded, and a failed Windows cleanup becomes invisible

#### Facts

The accepted plan locks automatic persistent derivatives to ten per cent per
acquisition and 5 GiB globally
(`docs/design/viewer-delivery-implementation-plan-50-percent.md:67-85`). Its S1
gate says every managed root must be visible and bounded by refusal rather than
silently growing (`:589-596`). The 100% checkpoint marks S1 done
(`docs/design/viewer-delivery-implementation-plan-100-percent.md:14-26`).

`zmart_viewer/scratch.py:99-160` creates, locks, and removes session folders;
`:175-260` sweeps orphans and reports their bytes. `/api/scratch` exposes that
report at `zmart_viewer/server.py:620-630`. There is no per-acquisition limit,
global 5 GiB limit, write refusal, or quota enforcement in these paths. A
healthy long-running process can therefore grow scenes and replays without a
bound. Reporting the size is useful, but it is not the refusal the plan makes a
gate.

The Windows failure path has a separate deterministic defect. It renames an
orphan from `session-X` to `retired-X` before deletion
(`zmart_viewer/scratch.py:210-226`). If `shutil.rmtree` fails, `_remove` reports
the original session as stuck (`:235-246`), but later sweeps and
`managed_bytes` accept only names starting with `session-`
(`:165-172`, `:186-190`, and `:248-260`).

I simulated the Windows branch while forcing removal to fail. The first sweep
reported `session-dead` as stuck. The second sweep reported nothing, the
`retired-dead` folder remained, and `managed_bytes()` reported zero bytes. This
finding does not depend on whether `msvcrt.locking` works on real Windows; it is
the name filter after a successful rename.

#### Consequence and inference

S1 is lifecycle and accounting work, not the bounded-storage package the plan
declares complete. On Windows, precisely the folder that failed to delete can
also become permanently unaccounted. Both are capable of filling an operator's
disk silently. Add the promised refusal with injected small-limit tests, and
make retired folders both visible and retryable before calling S1 done.

### 5. Medium: a current JPEG preview path still lets the first field choose an irreversible display transform

#### Facts

The main overview canvas no longer falls back to `jpeg-under`; that part of the
migration is real. Small per-field pictures are still active for target
detection and the acquisition gallery. `application/framework/window/main.js:92-96`,
`:1122-1141`, and `:1184-1199` construct `.jpg` addresses for those views.
Requests under `/view/...` call `_the_view_of` through
`application/framework/bridge.py:793-817` and `:1173-1205`.

`viz_studio/backend/jpeg_tiles.py:397-454` says and implements that the first
field chooses `low` and `high`, persists them as `brightened_between`, applies
a gamma transform, and holds later fields to those values. The incremental
path skips pictures already listed (`jpeg_tiles.py:385-394`), so I found no
automatic final pass that replaces those JPEGs with a whole-run decision. The
batch helper, when called separately, chooses its own 0.5th and 99.9th
percentiles (`jpeg_tiles.py:265-310`); that also is not a window the acquisition
description selected.

The migration left contradictory prose around this boundary. For example,
`application/parts/microscope/live.js:70-95` and the module comment in
`application/parts/storage/viewer_service.py:11-14` say the page falls back to
JPEG, while `watching-the-run.js:100-120` correctly says the third overview
answer was removed.

#### Consequence and inference

This is not a second whole-overview viewer, so it does not overturn the
architectural stop decision. It does mean the broad claim that no display path
is decided by a position is too strong. A first empty or unusually bright
field can bake misleading target and gallery previews for the run, with no
slider able to recover the source counts. Either bring these retained previews
under the acquisition-wide contract, give them a clearly separate measured
preview contract, or explicitly narrow the migration claim. Clean up the
contradictory comments at the same time.

### 6. Follow-up: real driver channel keys are more stable than the review brief assumes, but their biological labels are lost

#### Facts

`application/parts/microscope/settings.js:24-44` is the browser's sample reading,
not the Leica production parser. The bridge carries the real driver's
`observed.channels` structurally at
`application/framework/bridge.py:370-410`. The Leica adapter walks active
detectors, uses the LAS X detector `Channel` or `ChannelName` as identity, and
emits `leica-channel-<identity>` at
`zmart_drivers/leica/stellaris5_y42h93/navigator_expert/zmart_adapter/zmart_adapter.py:1031-1086`.

I ran that code over all eight committed LRP export fixtures. Across the five
scan-field exports, autofocus consistently emitted detector 3 and overview and
HiRes consistently emitted detectors 2, 3, and 4. The general workflow and two
Z-readback fixtures were internally consistent with their active detector
sets. The keys are therefore detector-slot based and stable across these
fixtures; they do not depend on a wavelength parsed from display prose.

However, the emitted labels were only `Channel 2`, `Channel 3`, and
`Channel 4`. The same detector records carry useful `DyeName` values such as
`Leica/ALEXA 405`, `Leica/ALEXA 488`, and `Leica/ALEXA 594`, but the adapter
does not use them. `setdefault` at adapter line 1061 also collapses the same
detector identity when it appears in both master and sequential sections. The
fixtures do not establish whether a real same-detector sequential acquisition
produces one output C plane or several. Two channels of the same wavelength on
different detector identities would remain distinct by construction; the same
identity repeated would not.

The mesoSPIM adapter likewise reports a single generic
`mesospim-channel-0`/`channel 1` regardless of the current laser and filter
state (`zmart_drivers/mesospim/mesospim_zmart_adapter.py:362-377`).

#### Consequence and inference

I do not see evidence that the current Leica key changes merely because a
wavelength is absent or duplicated. I do see a provenance and usability gap:
the durable description loses the biological dye/wavelength name already
present in the preset. A live microscope-PC check is still needed for the
same-detector sequential case before treating the channel-count parser as
complete.

## Answers to the eight review questions

### 1. Does any path still give a channel a window the acquisition did not decide?

Yes. No migrated OME writer I inspected persists a made-up unresolved window:
the position, canvas, cropped, and `zmart_live` writers all omit the complete
OME block when any channel is unresolved. But the active drawing adapters still
use a fixed `0…4095` window when pixel measurement gives no answer, and the
older comparison backend still has `0…65535`. The panel does not apply its own
measured answer to the engine. Separately, the retained small-JPEG path bakes a
first-field percentile and gamma transform for detection/gallery pictures.

Thus the narrow writer-metadata answer is “no”; the repository-wide display
answer requested in the brief is “yes.”

### 2. Does a real pre-migration run keep the same brightness through the new composed path?

Not established. I searched the user's Documents, Desktop, and Downloads for
OME-Zarr stores and acquisition sidecars. The only stores found were synthetic
`viz_studio/backend/test_stores` fixtures in another project checkout. I found
no real pre-`b79fb46e` run carrying per-position windows, so I did not relabel a
fixture as real evidence. The existing legacy-consensus tests pass, but this
question remains an on-data gate.

### 3. Does the real old/new Viewer handshake work, and does refusal preserve the scan?

Yes at the service and acquisition boundary on this Mac.

With Viewer `9ff10b0`, the new microscopy bridge reported:

> the installed ZMART Viewer is too old for this run: it does not promise acquisition-display-window-v1, absent-display-window-v1. Update the zmart-viewer package (it needs the acquisition-wide display-window contract) and connect again.

The Viewer remained stopped. The same connected bridge scan completed with
`done=1`, `of=1`, no scan error, three TIFFs, one position store, and the
acquisition sidecar. With Viewer `7a38079`, the Viewer started with no error,
the same scan completed, and the source was served. I could not visually prove
the sentence's placement on the canvas because no connected browser was
available; the exact backend sentence and scan independence are facts.

### 4. What do the real Leica preset descriptions produce?

The premise in the brief is not the production path: `settings.js` builds
sample browser readings. The Leica driver produces detector-slot keys. Across
eight committed real LRP exports, those keys were stable for the active
detector sets. Two equal wavelengths on different detector slots remain
different keys. A repeated detector identity across master/sequential sections
is collapsed, and the fixtures cannot prove whether that matches the number of
captured C planes. Labels are generic channel numbers even where the export
contains useful dye names. I did not have the microscope PC or current live LAS
X preset, so that last hardware case remains unverified.

### 5. What happened under reachable concurrency?

- Starting a second scan while the first was running was refused immediately
  with `RuntimeError: a scan is already running`.
- Starting the same acquisition type again after it finished did not overwrite
  data. The new call initially entered the running state, then failed visibly
  because `P000000` already existed. It reported `done=0`, retained the original
  position store, and reset the API's record list to zero at
  `application/framework/bridge.py:846-894`. This is safe for data but awkward
  state for a retry: the prior scan's records disappear from the bridge view.
- A stale `zmart-acquisition.json` with a different channel set was refused
  synchronously as an immutable-contract mismatch before a scan began.
- Two real Viewer server processes started 0.000005 seconds apart under one
  scratch root. A third sweep kept both locked session folders. After both
  processes were killed, the next sweep removed both and reclaimed 135 bytes.
  The ordinary POSIX concurrency case is sound.

### 6. Are the first-thirty-seconds panel and canvas sentences true?

Not consistently, and the mock requested by the brief cannot exercise them.
The mock supplies no Viewer source. In a bridge-driven run, no panel exists
before the first position is complete; the first position then reports
`settled` while the acquisition can still grow, and a completed on-demand
composite reports `provisional`. From the rendering code, the first hides
“brightness measured from pixels acquired so far” when it should be helpful,
and the second shows it after acquisition is done. “Waiting for measurable
pixels” is valid as an isolated panel state but unreachable before the first
field in the integrated source lifecycle.

I read the API answers and exercised the panel in jsdom. I did not claim a live
visual walk because this review environment had no connected browser.

### 7. Do five random new prose blocks meet the microscopist writing rule?

I selected distinct production comment/docstring block starts from the two
diffs, excluding tests, generated/vendor files, and static assets, with seed
`20260902`. There were 30 candidates. The five selected starts were:

1. `zmart_viewer/scratch.py:237`, removal and honest byte counting.
2. `viz_studio/options/measure/data_server.py:169`, reading the two OME-Zarr
   metadata generations.
3. `zmart_viewer/scratch.py:48`, taking a non-blocking ownership lock.
4. `zmart_viewer/scratch.py:155`, releasing ownership and removing session
   folders.
5. `viz_studio/options/measure/real_run.py:33`, the order in which a run's
   stores are worth opening.

All five are complete and understandable. The two one-line scratch docstrings
are close to restating their names, but they add the important return or
ownership condition and are not harmful. I found no unexplained specialist
jargon in this sample.

The broader prose pass did find a real contradiction outside the random
sample: `live.js` and `viewer_service.py` promise a JPEG fallback that
`watching-the-run.js` says, correctly, is gone. Those comments should be
reconciled because they describe what the operator sees when the Viewer is
unavailable.

### 8. Which shared internal-review decisions survive challenge?

- **Omitting partial `omero`: keep the strict-reader rule, reject the claim of
  sufficiency.** The ngio test passes and invalid partial OME metadata should
  not return. The missing part is a channel-description route that survives
  the omission and reaches both panel and engine.
- **Capabilities rather than versions: keep.** The actual `9ff10b0`/`7a38079`
  handshake demonstrates exactly why this is better than the unchanged
  package version.
- **Decimation stays: keep.** I found no new registration evidence that
  justifies replacing it, and changing it would revive the already documented
  half-pixel placement disagreement.
- **No `uint8` before measurement: keep.** There is no real-run brightness or
  target-machine phase-0 evidence, and the present scientific-dtype path still
  loses channels and has two brightness authorities. Compact encoding is not
  the next problem.

## Tests and probes run

### Passing automated suites

- Microscopy storage, bridge, canvas backend dependencies, `zmart_storage`, and
  `zmart_live`: **813 passed, 5 skipped**, one warning, in 68.01 seconds.
- Microscopy Vitest: **28 files passed; 393 tests passed, 15 skipped**, in 4.97
  seconds.
- Viewer focused transfer, contrast, server, scratch, harsh-store, and
  unresolved-window suites: **141 passed, 7 skipped**, one warning, in 34.46
  seconds. The seven skipped tests require a built page and real browser.
- Viewer strict-reader test after installing real ngio 1.1.0: **1 passed**, one
  warning, in 25.98 seconds.

- Full Viewer suite without a built page, with the already-known commit-storm
  file excluded: **597 passed, 319 skipped** in 338.95 seconds. Of those skips,
  314 explicitly report that no real browser picture was inspected. The storm
  file was ignored rather than counted as deselected.

### Diagnostic run that is not a valid aggregate

One broad microscopy invocation from the repository root produced **1,132
passed, 10 skipped, and 24 failed** in 150.09 seconds. The workflow package
tests in that command require their own working-directory/package setup; most
failures were `No module named workflow` or focus-test doubles from the wrong
import context. The included Playwright walk also timed out on a hidden SVG.
I do not attribute that aggregate to this migration and reran the affected
storage/bridge/live scope in the valid context above.

### Independent integration and fault probes

- Real old/new Viewer compatibility and bridge-driven scan: old refused, new
  accepted, and both scans preserved the expected scientific files.
- One- and two-position, three-channel bridge scans: no acquisition errors;
  three Viewer config rows became one embedded source without channel data.
- Real panel with a three-layer engine: one panel channel row.
- Real panel with a `1000…1001` measurement and engine spy: panel displayed the
  measured minimum; engine received zero window changes.
- Two overlapping/repeated scans and an immutable stale sidecar, with the
  outcomes reported in answer 5.
- Two actual Viewer processes sharing one scratch root, with lock survival and
  later reclamation.
- Forced Windows rename-plus-removal-failure branch: `retired-dead` remained
  while the next sweep and byte accounting both ignored it.
- All eight committed Leica LRP fixtures through the real channel-description
  parser.

### Not run or not available

- No connected browser was available, so I did not perform the requested live
  first-thirty-seconds visual walk or claim browser pixels from this machine.
- No real pre-migration acquisition run was present locally.
- The current microscope PC, Leica hardware, a real same-wavelength preset,
  PyWebView, GPU rendering, and Windows were not available.
- The known-open browser, five-axis, stack-plane, storm, `toldAbout`, and
  microscope-PC evidence items remain as admitted in the brief.

## Paste-back instructions for the fixing process

> Revise before phase 0. Preserve unresolved channel count, keys, labels,
> colours, and indices from the Viewer configuration or ZMART metadata through
> `viewer_service` into both the embedded panel and engine; prove three channels
> for the first direct position and the composed source without restoring an
> invalid partial `omero` block. Make the panel/Viewer measurement the one
> display-window authority and actually apply its answer to the engine; remove
> or explicitly surface the engine's `0…4095` fallback and test flat, waiting,
> unreadable, provisional, settled, and declared channels. Derive provisional
> state from acquisition/source liveness rather than whether this storage form
> has a written coarse level. Finish S1 by enforcing the planned ten-per-cent
> and 5 GiB refusals and by retrying/accounting failed `retired-*` removals.
> Decide and document the separate contract for retained detection/gallery
> JPEGs, verify the Leica same-detector sequential case and useful labels, and
> reconcile the stale JPEG-fallback comments. Re-run the real old/new handshake,
> multi-channel bridge integration, focused/full suites, and a browser walk.
> Keep decimation, capability negotiation, strict-reader-safe OME omission, and
> the current stop on `uint8`/JPEG-pyramid work.
