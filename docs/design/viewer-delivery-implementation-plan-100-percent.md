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
one and is left alone. The lock is held all the way through the removal, so
there is no instant in which a folder is unowned but still there; on Windows,
which will not delete an open file, the folder is renamed out of the sweep's
sight first and removed after. A Viewer that makes a folder and finds a
sweeper already holding its lock makes another. A symlink, a stray file, or
anything that resolves outside the root is never touched, and the root is
taken as resolved — a symlinked root is followed. What was reclaimed is
counted after the removal, not before it, so a folder that would not go is
reported as stuck rather than as reclaimed. `GET /api/scratch` reports what
the root holds, by folder, and what the last start reclaimed; it walks the
root on every call, so it is for looking, not for polling. On a drive or
share without file locks the Viewer cannot make a scratch folder and says so.
`fcntl.flock` on POSIX, `msvcrt.locking` on Windows; the Windows half has not
been run on Windows.

### Z1 — the half-voxel fact is a test

`viz_studio/tests/test_a_plane_is_sampled_at_its_centre.py` opens a one-plane
store in a real browser and takes two photographs: one where the engine
opens, which is the voxel's centre, and one after the height has been pushed
a whole voxel past the only plane there is. The first must hold a picture and
the second must not, judged by how varied the photograph's colours are — not
by "brighter than black", because the box is painted a dark grey and that
rule once called an empty box fully drawn. The edge itself, at exactly one
voxel, still draws; only a height past it is empty.

A second check holds `setPlane` and `theDepthItCanShow` to the same
arithmetic on both engines: asked for 4 µm at 2 µm a plane, the reading says
4 µm. It did not: `neuroglancer-under` put the height on a plane's edge and
read it back from its centre, half a plane short. Fixed in the engine's
`setPlane`.

The stack half holds each engine to the middle-plane rule in
`options/planes.js`. `viv-under` keeps it. `neuroglancer-under` does not —
`theMapStandsOnItsFirstPlane` puts every acquisition on its first plane —
and that is recorded as a strict expected failure that fails loudly the day
the engine opens a stack where the rule says. Changing the engine's opening
height is outside this package: the first-plane behaviour was put there for a
documented reason (a flat overview and a focussing stack drawn together) and
must be revisited with that case in front of it.

This is a narrower Z1 than the plan wrote — a test in `viz_studio`, not an
extension of `the-window-step-by-step.spec.js` with the overlay-anchor and
raw-Z assertions. Those remain to do.

### H1 — the rig can look at a run it did not write

`viz_studio/options/measure/run.py --external-run PATH` measures one option
on a real store or run folder, read-only, and writes the result to its own
folder rather than the results table. It records time to a settled picture,
requests, and bytes — pieces and descriptions counted apart, so a later "is
this format smaller" question cannot pick a flattering subset — and the share
of the box that differs from the box's own colour. The ledger in
`data_server.py` now counts bytes and counts the describing files it used to
leave out; the request arithmetic the old measurements rest on is unchanged.

The rig's server now serves both generations of the format — the OME-Zarr
0.5 positions the microscope's bridge writes as well as the 0.4 stores the
rig writes for itself — resolves a store by its exact name before adding
`.ome.zarr`, and, for a store that kept no coverage record, treats the whole
frame as imaged and says so in its answer (`coverage_bounded: false`). The
harness takes the store's real name and generation from that answer.

**What H1 does not yet do.** The bridge's positions open and their pieces
are fetched, but the rig's own `neuroglancer-under` adapter places the view
beside a five-axis 0.5 store, so the photograph is empty. That is recorded
as a strict expected failure
(`test_the_positions_the_microscopes_bridge_writes_are_drawn`) and belongs
to the same family as the pre-existing foreign-store failure in
`test_the_options_hold_together.py`. Until it is fixed, `--external-run`
gives honest request and byte numbers for a bridge-written run and an honest
zero for how much was drawn. It is also one opening of one store, not the
plan's ten-step trace, memory proxy, or "reproduce one known Viewer
measurement within a tolerance" gate.

### Pre-existing debt found by running everything, and not fixed here

- Five checks in `viz_studio/tests/test_the_options_hold_together.py` failed
  identically before this work: the plane-rule source check, the detail scan
  not landing inside the survey on `neuroglancer-under`, and the "foreign"
  store on all three engines. The foreign store used to be refused for having
  no coverage record; with coverage now synthesised it opens and draws less
  of the window than the check asks for, which is the same drawing gap the
  bridge's positions show. They are harness and fixture debt, named here so
  nobody reads them as this checkpoint's.
- The microscopy suite needs `ome-types`, `matplotlib`, `scikit-image` and
  `pooch` to collect fully; without them whole files error at collection and
  are silently missing from the count.

## What the 100% review asked for, and where each answer is

The review at `docs/reviews/2026-09-02-review-of-the-100-percent-viewer-delivery-implementation.md`
found the migration core sound and four things wrong in the new packages.
Each is answered above in its package's section; in short: the drawn-share
metric now measures against the box's own colour and Z1 is a contrast between
two photographs; the rig's server serves both format generations, exact
names, and synthesised coverage for a bridge-written run, with the remaining
drawing gap recorded as a strict expected failure; the sweep holds its lock
through the removal and counts what actually went; `setPlane` and the depth
reading agree. Of the minors: the server stops serving before it lets go of
its scratch, the served-folder bound is a path check rather than a string
prefix, the store-resolution precedence is fixed, and the three follow-ups
the review found untested now have tests (the hard-link fallback, a
successful measurement's `measurementState`, the corrupt-description
sentence); the watcher's `toldAbout` still has no test of its own, because
nothing in the vitest suite reaches `watching-the-run.js`.

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

Both repositories release together, from `claude/viewer-delivery-to-100`.
On the microscope PC the Viewer is a local checkout installed with
`pip install -e` (`environment.yml`), so releasing it means pulling that
checkout; its version number stays `0.2.0` and does not tell the two apart.
Only `/api/health` does — `pip show` is not evidence of which Viewer is
installed. The M3 gate items the 80% review asked for have not been
produced here: the handshake has been seen accepting and refusing only
pretend servers, not `9ff10b0` running on the microscope PC; no real
bridge-driven run has been photographed with the five equalities; and the
cold-open numbers before and after the declared window do not exist yet.
They are the first things to do on the microscope PC.

- ZMART Viewer first, so that the Viewer on the microscope PC promises both
  capabilities before the writer asks;
- then ZMART-microscopy.

A Viewer that is not updated is refused at start with a sentence that says
so, and the run proceeds without the live canvas rather than with a black
one. The vendor files and the position stores are written either way.
