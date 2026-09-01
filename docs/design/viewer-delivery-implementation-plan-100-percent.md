# Viewer delivery implementation — 100% checkpoint

Date: 2026-09-02

Status: every package in the migration plan is implemented and tested. What
remains is not code: it is the phase-0 measurement on the microscope PC that
decides whether the existing Viewer meets the operator thresholds, and the
review of this checkpoint.

Based on the 80% checkpoint in
`viewer-delivery-implementation-plan-80-percent.md` and its review, and on
the commits after it on `claude/viewer-delivery-to-100` in both repositories.

## The six packages, and where each one is

| Package | State |
|---|---|
| V1 — the Viewer knows an absent window | done |
| V2 — the composed source is the authority | done |
| M1 — the writer publishes the descriptor | done |
| I1 — one authority end to end | done, both repositories |
| M2 — embedded waiting state, capability handshake | done, both repositories |
| M3 — the position writer stops measuring | **done in this checkpoint** |
| S1 — session scratch lifecycle and accounting | **done in this checkpoint** |
| Z1 — the half-voxel evidence as a test | **done in this checkpoint** |
| H1 — the rig can measure a run it did not write | **done in this checkpoint** |

## What this checkpoint adds

### M3 — a position never decides its own window again

`application/parts/storage/zarr_positions.py` no longer measures a window per
position. A resolved acquisition description gives every position the same
label, colour and window; an unresolved one, or no description at all, writes
no channel block into the store. The function that measured per position,
`_a_window_onto`, is gone, and so are the compatibility hint in
`ome_channel_blocks` and the assertion that guarded it — deleted, not
changed, as the plan said.

The end-to-end check's legacy half now stamps its two disagreeing windows by
hand, because that is what a run written before the migration looks like on
disk and the writer no longer produces it.

**This may only run beside a Viewer that promises
`absent-display-window-v1`.** `viewer_service.start()` refuses an older one
at start with an upgrade sentence, and the page shows that sentence beside the
empty picture. The two repositories are released as a pair; rolling one back
means rolling both back.

### S1 — the folders a Viewer makes for itself go when it goes

`zmart_viewer/scratch.py`. Each session folder under `~/.zmart-viewer` is
locked by the process that made it, for as long as it runs; the operating
system releases the lock when the process dies, however it dies. On the next
start, any folder whose lock can be taken has no owner and is reclaimed, and
any whose lock cannot be taken belongs to a Viewer still running beside this
one and is left alone. A symlink, a stray file, or anything that resolves
outside the root is never touched. `GET /api/scratch` reports what the root
holds, by folder, and what the last start reclaimed, so scratch is counted
somewhere. `fcntl.flock` on POSIX, `msvcrt.locking` on Windows, behind one
small function; the Windows half has not been run on Windows in this
checkpoint.

### Z1 — the half-voxel fact is a test

`viz_studio/tests/test_a_plane_is_sampled_at_its_centre.py` opens a one-plane
store in a real browser and photographs it drawn. That is what sampling the
voxel's centre rather than its edge looks like; a source sampled off its edge
photographs as black, whatever the engine reports about itself. The stack
half holds each engine to the middle-plane rule in `options/planes.js`, with
the half-voxel arithmetic inside: four planes at 2 µm open at plane 2, which
is 4 µm from the first plane, not 3 and not 5.

It found something. `viv-under` keeps the rule. `neuroglancer-under` does not:
`theMapStandsOnItsFirstPlane` puts every acquisition on its first plane and
never asks `planes.js`. That is the debt the earlier reviews named under
`test_no_option_decides_for_itself_which_plane_to_open_on`, now recorded as a
strict expected failure that will fail loudly — so the mark has to come off —
the day the engine opens a stack where the rule says. Changing the engine's
opening height is outside this package: the first-plane behaviour was put
there for a documented reason (a flat overview and a focussing stack drawn
together), and it must be revisited with that case in front of it.

### H1 — the rig can look at a run it did not write

`viz_studio/options/measure/run.py --external-run PATH` measures one option
on a real store or run folder, read-only, and writes the result to its own
folder rather than the results table. It records time to a settled picture,
requests, and bytes — pieces and descriptions counted apart, so a later "is
this format smaller" question cannot pick a flattering subset — and how much
of the box was actually drawn. The ledger in `data_server.py` now counts
bytes and counts the describing files it used to leave out; the request
arithmetic the old measurements rest on is unchanged.

### Pre-existing debt found by running everything, and not fixed here

- Four checks in `viz_studio/tests/test_the_options_hold_together.py` fail
  identically before and after this work: the plane-rule source check, the
  detail scan not landing inside the survey on `neuroglancer-under`, and the
  "foreign" store having no coverage record on all three engines. They are
  harness and fixture debt, named here so nobody reads them as this
  checkpoint's.
- The microscopy suite needs `ome-types`, `matplotlib`, `scikit-image` and
  `pooch` to collect fully; without them whole files error at collection and
  are silently missing from the count.

## What the 80% review asked for, and where each answer is

The review at `docs/reviews/2026-09-02-review-of-the-80-percent-viewer-delivery-implementation.md`
accepted the checkpoint with follow-up and named six things to do before M3.
All six are done, and M3 was landed after them:

1. `zmart_live/omezarr.py` and `zmart_storage/positions.py` omit the channel
   block when any channel has no window, like every other writer. The
   `zmart_live` suite, red since `b79fb46e`, is green again (521 passed).
   `zmart_live` is not dormant: the vendored older viewer under
   `viz_studio/backend` imports it, so it was fixed rather than retired.
2. `viewer_service` parses the health answer inside its guard, closes the
   refused server's socket, shuts down a server that failed after starting,
   and says "did not answer" rather than "too old" when the Viewer did not
   answer. Its tests assert a refused connection, not a timeout.
3. `watching-the-run.js` counts the upgrade sentence as told only once there
   was a canvas to tell.
4. `/api/measure` says whether a successful measurement is settled or
   provisional, and the embedded panel shows "brightness measured from pixels
   acquired so far" for a provisional one — the standalone Viewer's sentence.
   Decision 4 is now true as written: the same four states, the same words.
5. The end-to-end check tampers with the first-sorting position and proves
   the sidecar's authority by the numbers. Publication falls back to
   replace-and-compare on a filesystem without hard links; decision 1 no
   longer assumes them.
6. The ngio fact is a test against ngio itself
   (`tests/test_the_channel_shapes_a_strict_reader_accepts.py`), skipped
   where ngio is not installed, never faked.

One minor from the same review is also done: a description file that is not
JSON is named as that. Another is noted, not changed: a request for a box
outside the picture is still answered "waiting", because the panel never
asks for one.

The review's I1 observation stands corrected in this document: the fifth
reading in the end-to-end test is the Viewer's own `display_window`, and the
embedded panel's `asWritten` is covered by the jsdom test only. The missing
browser walk of the upgrade sentence is still missing.

## What 100% does not do

- **It does not decide whether the existing Viewer is fast enough.** That is
  the phase-0 measurement on the microscope PC with H1, and it has not been
  run. The stop targets stand as written in the 50% plan.
- **Nothing in production supplies a resolved window.** The recording preset
  gives names; a `start`/`end` needs an explicit value nobody records yet, so
  every real acquisition is published unresolved and the Viewer measures.
- **The compact `uint8` experiment stays unauthorised and JPEG stays out.**

## Release

Both repositories release together, from `claude/viewer-delivery-to-100`:

- ZMART Viewer first, so that the Viewer on the microscope PC promises both
  capabilities before the writer asks;
- then ZMART-microscopy.

A Viewer that is not updated is refused at start with a sentence that says
so, and the run proceeds without the live canvas rather than with a black
one. The vendor files and the position stores are written either way.
