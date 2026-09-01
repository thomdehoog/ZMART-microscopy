# Viewer delivery implementation — 80% checkpoint

Date: 2026-09-02

Status: the compatibility half of the migration is implemented for review. The
position writer still measures a window per position; that is the last thing
to remove, and it waits for the review of this checkpoint.

Based on:

- the 50% checkpoint at `ca8e176d`, reviewed at `eecf763c`;
- Codex's corrections at ZMART-microscopy `b79fb46e` and ZMART Viewer
  `2b4338e`;
- this checkpoint's own commits on `claude/viewer-delivery-to-100` in both
  repositories.

## What "80%" means

Of the six ordered packages, four are implemented and two are not:

| Package | State at 80% |
|---|---|
| V1 — the Viewer knows an absent window | done, including the writer side and the fault/absence distinction |
| V2 — the composed source is the authority | done, legacy disagreement degrades rather than refuses |
| M1 — the writer publishes the descriptor | done, one publisher, before the stage moves |
| I1 — one authority end to end | done, both repositories, real writer through real Viewer |
| M2 — embedded waiting state and capability handshake | **done in this checkpoint** |
| M3 — stop the per-position window | not started; waits for this review |
| S1, H1, Z1 | not started; independent, scheduled for the 100% checkpoint |

## What this checkpoint adds

### M2, both halves

**The Viewer says what it promises.** `GET /api/health` now answers
`{"ok": true, "version": …, "capabilities": [...]}`. The two promises are named
by exact strings in `zmart_viewer/acquisition.py`:

- `acquisition-display-window-v1` — the composed source reads one
  acquisition-wide window from `zmart-acquisition.json` and never lets the
  first position decide for the rest;
- `absent-display-window-v1` — a channel with neither a declared nor a
  measurable window is reported as absent, in JSON as `null`, and the page says
  it is waiting rather than showing `0…65535` as though somebody chose it.

**The writer asks before it draws.** `viewer_service.start()` starts the Viewer
as before, then asks it `/api/health` over the same local HTTP the page will
use. A Viewer that does not promise both is stopped again, and one sentence is
left in the run's status naming what is missing and what to install. The page
reads that sentence through a new `viewerTrouble()` on the backend and puts it
beside the empty picture, because a blank canvas with the explanation in a
status document is the fault this project keeps meeting.

**The embedded panel waits honestly.** `application/parts/canvas/viewer-panel.js`
no longer has a `{low: 0, high: 65535}` fallback anywhere. A channel with no
window disables its four brightness controls and says "waiting for measurable
pixels"; a store the Viewer cannot read says "this acquisition cannot be read"
with the reason, and never waits; a measured window is labelled measured, and
only a window the run wrote is labelled declared. `/api/measure` carries the
state in its empty answer (`measurementState`, `measurementError`) so the panel
never has to guess which kind of nothing it was handed.

### I1, both halves

`application/parts/storage/test_one_window_end_to_end.py` writes a dim and a
bright position with the real writer, publishes a descriptor, and opens the
folder through the installed Viewer. Five readings must agree: the sidecar,
every position's mirrored OME window, the composed group, the built picture,
and the configuration row the page is handed. The legacy half writes the same
two positions without a descriptor, proves their windows disagree, and proves
the composed source declares none and the Viewer measures one — labelled
measured, not declared.

Writing that test found a Viewer defect: a store-declared window was reported
as `provisional`, so the standalone panel would have called a run's own
decision "measured from pixels acquired so far". Fixed in `contrast.measure`,
with its own test in `tests/test_contrast.py`.

### Corrections found while running everything

- `zmart_storage/cropped.py` still asked `Channel.described()` for a channel
  with no window, which since `b79fb46e` raises. Sixteen tests in
  `zmart_storage/tests/test_cropped.py` failed; the cropped writer now omits
  the advisory block exactly as `TileCanvases` does.

## Decisions closed at this checkpoint

The 50% plan listed eight things the next review had to decide. They are
decided here, and any of them can be reopened by the review of this document.

1. **Descriptor location and schema — accepted.**
   `<run>/positions/<acquisition-type>/zmart-acquisition.json`, schema
   `zmart-acquisition-display/1`. One publisher: the bridge's `_start_scan`,
   before the scan thread exists. Publication is a hard link of a complete
   temporary file, so two writers cannot both win; the loser compares and
   either agrees or refuses. The directory is fsynced where the platform
   allows. `acquisitionType` must equal the folder name, and that is a check,
   not a convention.
2. **The real source of channel descriptions — the recording preset.**
   `application/parts/microscope/settings.js` derives a key, an index and a
   label per channel from the preset the operator recorded, and the bridge
   checks the count against what the instrument reports it will capture. No
   window is derived from the preset, because none is recorded there: the
   descriptor is published *unresolved*, which is the honest state, and a
   window arrives only from an explicit preset value or operator action. The
   descriptor never invents one.
3. **Capabilities, not version pinning, for M2.** The Viewer is installed from
   a checkout and is optional in `environment.yml`; a version number would say
   nothing about what a checkout can do. Two named promises on `/api/health`
   are a lookup, not a comparison.
4. **Absent-window behaviour — approved, and the same in both canvases.**
   Four states, one vocabulary: `waiting`, `unreadable`, `provisional` or
   `settled`, and `declared`. The standalone `LayerPanel.jsx` and the embedded
   `viewer-panel.js` show the same words for the same state.
5. **Scratch lock — an exclusive OS file lock, held for the process lifetime.**
   `fcntl.flock` on POSIX, `msvcrt.locking` on Windows, behind one small
   module. The lock is the liveness signal, so no age-based grace is needed: a
   folder whose lock can be taken has no owner. Implemented in S1 at 100%.
6. **Mechanical definitions — accepted as written in the 50% plan.** Process-
   cold, warm, useful picture, navigation latency, landing latency, the byte
   set, and the memory proxy stand unchanged.
7. **Process-cold unbaked open has no product bound at 80%.** It is reported.
   The Viewer's own measurement of 13.1 s at 10,000 positions is the known
   number; whether it must improve is a product question for after H1 has
   measured a real run on the microscope PC.
8. **The compact experiment stays unauthorised and JPEG stays out.** Nothing
   in this checkpoint makes a future whole-`uint8` picture harder; the
   composer's codec choice already handles a one-byte dtype.

And one decision the 50% plan left to the implementation:

9. **ngio and the unresolved channel — omit the whole `omero` block.** Checked
   against ngio 1.0.0 on 2026-09-02 (recorded in
   `zmart_viewer/acquisition.py`): no block and a complete window open;
   label-only and `min`/`max`-only channels are refused. So an unresolved
   acquisition writes no channel names or colours into the store at all, and
   keeps them for the live UI through `the_channels_for_display`. Names and
   colours reach the store the moment a window is resolved.

## What 80% does not yet do

- **Positions still carry a measured window** (`_a_window_onto`). Removing it
  is M3, and it may not land until the M2 handshake is deployed on the
  microscope PC — the two repositories must be released as a pair.
- **Nothing in production supplies a resolved window.** The preset gives
  names; a `start`/`end` needs an explicit value nobody records yet.
- **The upgrade sentence is tested at the bridge and in the panel, not in a
  browser walk.** A Playwright walk that starts the page against a bridge
  whose viewer was refused is the missing photograph.
- **S1, H1, Z1** are not started.

## From 80% to 100%

In this order, each landing on its own:

1. M3 — the position writer stops measuring; resolved descriptors mirror,
   unresolved ones write no `omero` block; `_a_window_onto` and the M1
   compatibility assertion go.
2. S1 — `zmart_viewer/scratch.py`, the lock, the orphan sweep, the byte
   tally; wired into the server's session folders and shutdown.
3. Z1 — the half-voxel evidence as a committed test.
4. H1 — `--external-run` on the options rig, read-only, and the fixed byte
   set.
5. The evidence commit: phase-0 raw data from the microscope PC, and the
   verdict on whether the existing Viewer meets the operator thresholds.
