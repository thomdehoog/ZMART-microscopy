# Review of the 100% viewer-delivery implementation

**Date:** 2026-09-02.

**What was reviewed, as code:**

- ZMART-microscopy, branch `claude/viewer-delivery-to-100`, commit `78356da6`
  ("record the answers to the 80% review in the 100% checkpoint"). The 80%
  checkpoint was `ae40fb58`; between them are `960d15d9` (Z1 and H1),
  `543ca9f0` (M3), `10cdafb8` (the answers to the 80% review) and `78356da6`
  (the checkpoint document).
- ZMART Viewer, branch `claude/viewer-delivery-to-100`, commit `8880c7d` ("say
  which measurements are provisional, name a corrupt description, test the
  reader"). The 80% checkpoint was `02cf88d`; between them are `f75fa63` (S1)
  and `8880c7d`. The released 0.2.0 is `9ff10b0`.

**Read alongside:** `docs/design/viewer-delivery-implementation-plan-100-percent.md`,
`docs/reviews/2026-09-02-review-of-the-80-percent-viewer-delivery-implementation.md`,
`docs/design/viewer-delivery-implementation-plan-50-percent.md`, and `CLAUDE.md`
in ZMART-microscopy. The Viewer still has no `CLAUDE.md` at `8880c7d`, so the
microscopy one was applied to both.

**How it was reviewed:** each commit was checked out into a worktree of its own
under `/tmp` (`/tmp/final-m` for the microscopy repository, `/tmp/final-v` for
the Viewer). Neither working folder was touched; `node_modules` and the built
pages were copied in from the working folders rather than rebuilt. Tests were
run in the worktrees (section 5). Six small probes were written in a scratch
folder to check things the tests do not; each is described where it matters,
and none was committed anywhere.

Throughout, an **observed** fact is one read in the code or produced by a test
run or a probe named here. An **inference** is labelled as such.

---

## Verdict: revise before continuing

The heart of the migration is sound. M3 is real: the per-position window is
gone, no path left in either repository stamps one, and a run written without a
resolved description produces stores that ngio, the Viewer's composer and the
Viewer's measurement all open (probe A). All six follow-ups from the 80% review
are closed in the code, and four of the six have a test that would fail if they
reopened. The compatibility boundary is refused at start, the socket is closed,
and the scan carries on without the live canvas. The microscopy suites that
were red at 80% are green: 917 passed, none failed.

Two of the four new packages, however, do not do what the 100% document says
they do, and both matter for the very next step, which is the phase-0
measurement on the microscope PC:

- **Z1's photograph cannot tell a drawn picture from an empty box.** The
  harness paints its box `#101014`, which is (16, 16, 20), and both
  `_drawn_share` in the Z1 test and `drawn_share_of` in `real_run.py` count a
  pixel as drawn when any of its colours is above 16. So an empty box counts as
  100% drawn. By probe, the one-plane check reports a share of 1.000 with the
  picture present and 1.000 with the picture gone (finding I1). The 100%
  document's sentence "a source sampled off its edge photographs as black" is
  therefore not something this test can see, and — also by probe — it is not
  true at the edge itself: the picture is still drawn at a height of exactly
  1.0 voxel and disappears only past it.
- **H1 cannot open the runs the microscope writes.** `--external-run` pointed
  at a folder of positions written by `position_store_from_record` — the
  bridge's own path — fails before a picture is opened: the harness page refuses
  any store that has no coverage record, and those stores keep none (probe H1).
  The harness also opens every store as `<name>.ome.zarr` in zarr version 2,
  so the composed `*.zmartview.zarr` that `the_store_to_open` prefers can never
  be opened, and the OME-Zarr 0.5 positions the bridge writes are asked for in
  the wrong generation. The one thing H1 exists for — measuring a run that a
  microscope actually produced — is out of reach for the runs this branch
  produces (finding I2).

There is also one ordering fault in S1's sweep that a probe turned into a
deleted folder under a live owner (finding I3). It is narrow, but it is
precisely the case the plan said must never happen.

None of this touches the writer, the descriptor, the handshake or the Viewer's
reading of windows. M3 and the follow-ups can be released as the pair the
document describes. What should not happen is the phase-0 measurement being run
with the H1 and Z1 that are here, because the "how much was drawn" number it
would produce is always one, and the runs it needs to open will not open.

---

## 1. Findings, by severity

### I1. The drawn-share metric counts the empty box as drawn, so Z1 proves nothing about drawing and H1's coverage number is always one

**Observed.** `viz_studio/options/harness/src/main.js:88` paints the box
`#101014` unless the page is drawing margins. That colour is (16, 16, 20).
`viz_studio/tests/test_a_plane_is_sampled_at_its_centre.py:38-42` and
`viz_studio/options/measure/real_run.py:69-81` both take the brightest of the
three colours of each pixel and count it as drawn when that is `> 16`. Blue is
20. Every background pixel is therefore "drawn".

**Observed, by probe.** Opening the one-plane `square` on `neuroglancer-under`
and photographing it at a series of heights, through the handle's own
`setPlane`: at heights of 0.00, 0.50, 0.99 and 1.00 voxel the photograph holds
twenty distinct colours with a spread (standard deviation) of 62.5 — the
picture; at −0.01, 1.01, 1.25 and 1.50 voxels it holds exactly one colour,
(16, 16, 20), with a spread of 1.9 — the empty box. In every one of those
photographs the test's `_drawn_share` is 1.000. The assertion at line 52
(`share > 0.05`) cannot fail for the reason its message gives.

The same probe on a four-plane stack: the picture is present from a height of
0 to 4.0 voxels inclusive and gone at 4.5 and at −0.5. In every case the
metric read 1.000.

**Observed.** `test_a_foreign_run_can_be_measured.py:84` asserts
`found["drawn_share"] > 0.05` with the message "the store opened but nothing
reached the screen"; it is the same metric and cannot fail either.
`real_run.py`'s `drawn_share` — the number the 100% document describes as
"how much of the box was actually drawn" — will be 1.0 for every run,
including one whose picture never arrives, which is the very failure the
docstring at lines 70-75 says it exists to catch.

**What follows for the Z1 claim.** The 100% document says a one-plane source
"sampled off its edge photographs as black, whatever the engine reports about
itself". The test does not look for that, and the probe shows the picture is
drawn at the upper edge (1.00 voxel) exactly as at the centre (0.50). Only a
height *past* the edge is empty. So "sampling the known upper boundary does not
become the presentation default" — the plan's assertion — cannot be shown by
photographing at the boundary at all. *Inference:* the engine rounds a
position that lies exactly on a voxel boundary into the last voxel, which is
ordinary nearest-sample behaviour; the half-voxel fact is about where the
number an operator sees comes from, not about a black picture.

**What to do.** Measure drawn-ness against the box colour, not against black:
count pixels that differ from `#101014` (or from the photograph's most common
colour), or use the spread of the photograph as the probe did. Then make the
Z1 test take two photographs, one at the centre and one past the edge, and
assert that they differ — that is the contrast the plan asked for. The same
fix goes into `real_run.drawn_share_of`.

### I2. `--external-run` cannot open the runs the microscope writes

**Observed, by probe.** A run folder holding one position written by
`application/parts/storage/zarr_positions.position_store_from_record` (the
bridge's own path, OME-Zarr 0.5) was handed to `real_run.measure`.
`the_store_to_open` resolved it correctly to
`positions/overview/overview_K00_…_V00.ome.zarr`. The harness page then refused
to start: *"the run … has no coverage record, so there is nowhere the picture is
allowed to show through and the page would draw an opaque sheet over
everything"* (`main.js:447-453`). Nothing was written beside the run.

**Observed.** A coverage record is kept by `zmart_storage.canvas.TileCanvases`
(`canvas.py:1123-1157`, `records_coverage=True`). `position_store_from_record`
declares its store through `_declare_one` directly and keeps none. So no
position the bridge has ever written can be opened by this harness. The H1
test avoids this by writing its fixture with `TileCanvases.create`
(`test_a_foreign_run_can_be_measured.py:62`), which does keep a record and
which writes OME-Zarr 0.4 by default (`canvas.py:1211`). Its docstring calls
that "the writer the microscope uses"; for the positions folder it is not.

**Observed.** `main.js:474` forms every store's address as
`${dataBase}/${name}.ome.zarr/|zarr2:`. Two consequences: `real_run.py:36`
prefers a composed `*.zmartview.zarr`, and `real_run.py:87` passes that name
whole, so the page asks for `overview.zmartview.zarr.ome.zarr` — the preferred
candidate can never open; and `|zarr2:` tells the engine to read zarr version
2, while the bridge's positions are zarr version 3 (`zarr.json`). The data
server's `voxel_size_um` and `origin_um` (`data_server.py:154-229`) likewise
read `.zattrs` only.

**What to do.** Either teach the harness to open a store without a coverage
record (draw the whole box, and say in the result that coverage was not
bounded) and to detect the generation from `zarr.json` versus `.zattrs`, or
say in the 100% document that H1 measures OME-Zarr 0.4 runs with a coverage
record only, and that the bridge's positions are not among them. The first is
what phase-0 needs. Add a test that measures a folder written by
`position_store_from_record`, since that is the run the microscope PC will
have.

### I3. The sweep lets go of the lock before it deletes, so a folder a starting Viewer has just claimed can be deleted under it

**Observed.** `zmart_viewer/scratch.py:185-194`: the sweeper takes the lock,
counts the bytes, *releases* the lock, closes the handle, and only then calls
`shutil.rmtree`. Between the release at line 190 and the removal at line 193
the folder is unowned but still present.

**Observed, by probe.** With `_let_go_of_the_lock` wrapped so that, the instant
the sweeper released, a second process opened the same lock file and took the
lock (which it did: `owner locked: True`), the sweep went on to report
`removed: ['session-newborn']`, the folder was gone while the second process
still held its lock, and that process's next write into the folder failed with
`FileNotFoundError`.

*Inference on how real this is.* A new session folder is made by `mkdtemp`
and locked immediately afterwards (`scratch.py:120-126`), so the window is the
few instructions between those two calls, in a Viewer that is starting at the
same moment as another Viewer is sweeping — two Viewers started within
milliseconds of each other on one machine. It is narrow. But the plan's own
failure rule is "scratch cleanup never deletes a locked … target", and this
ordering is the one way the code can do exactly that. Releasing before
deleting was presumably chosen so that Windows, which will not delete an open
file, can remove the folder; on POSIX it is unnecessary.

**What to do.** Hold the lock through the removal on POSIX; on Windows, rename
the folder to a name that does not begin with `session-` while the lock is
held, then close and remove the renamed folder — a folder with another name is
never a candidate again. Either way, add the interleaving above as a test
(the wrapper the probe used is small).

### I4. `neuroglancer-under` asks for one height and reads back another, half a voxel off

**Observed, by probe.** On the four-plane stack at 2 µm, `setPlane(4.0)`
followed by `theDepthItCanShow()` reads `atUm: 3`; `setPlane(6.0)` reads 5;
`setPlane(8.0)` reads 7 (and still draws, past the stack's stated `highUm`
of 6). `viewer.js:2170` puts the position at `z / umPerVoxel` voxels — a voxel
*edge* — and `viewer.js:2155` subtracts a half before reporting, which is
right for a position that stands at a voxel centre and wrong for one that
`setPlane` put on an edge. The comment at lines 2145-2148 says the two "have
to match"; they do not.

*Inference.* This is the half-voxel fact Z1 was meant to pin, and it is loose
in the very engine the test is about. It is not reached by the Z1 test, which
never calls `setPlane`. It lives in `viz_studio`, the options rig, not in the
Viewer that draws the operator page, so no operator sees it today; the rig's
depth control would show 3 µm after being asked for 4 µm.

**What to do.** Make `setPlane(z)` land on the centre of plane `z / step`
(add the half there), or make the reading not subtract it; then a round-trip
assertion belongs in the Z1 stack test, for both engines.

### Minor observations

- **The sweeper reports a folder as removed and its bytes as reclaimed without
  checking** (`scratch.py:177-184, 193-194`): `rmtree(..., ignore_errors=True)`
  hides a folder that would not go — a read-only folder, or on Windows a file
  held open — and `/api/scratch` then says it was reclaimed. I could not
  demonstrate this here because the tests run as root, for whom permission
  bits do not bite; it is read from the code. Count what is gone after the
  call, not what was there before it.
- **On a filesystem where the lock cannot be taken, the Viewer cannot make a
  scratch folder at all.** `_take_the_lock` turns every `OSError` into
  `False` (`scratch.py:59-63`), and `open()` then raises `RuntimeError("could
  not lock the new scratch folder …")` (`scratch.py:124-126`; probe B2). That
  is the right way round — nothing is deleted — but a home directory on a
  share mounted without lock support makes every composed scene fail with a
  sentence about a lock. Worth one line in the document, and a gentler
  sentence for the operator.
- **The server closes its scratch before it stops serving**
  (`server.py:1587-1590`): `close()` runs, then `super().shutdown()`; a
  request that asks for a session folder in that gap makes a fresh, locked
  one that is never closed. It is reclaimed at the next start, so nothing is
  lost. Reverse the two lines.
- **`/api/scratch` walks every file under the root on every request**
  (`scratch.py:197-210`, `server.py:620-631`). Nothing in the page calls it
  (searched `app/page/src`), so today it is on demand only; a replay of many
  thousand pieces would make each call slow. Acceptable as a diagnostic; not
  as something to poll.
- **`the_store_to_open` has a precedence slip** (`real_run.py:48`):
  `run.is_dir() and (run / "zarr.json").is_file() or (run / ".zattrs").is_file()`
  binds as `(A and B) or C`. Harmless today because `C` is false for anything
  that is not a directory, but it reads as a mistake. And a store given
  directly makes the server serve its whole parent folder (`real_run.py:50`),
  read-only and to this machine only; say so in the help text.
- **`many_sources.py`'s numbers will change.** The ledger now records the
  describing files it used to skip (`data_server.py:353-355`), and
  `many_sources.py:428-450, 847-869` reads `ledger.entries` directly, so
  "requests in all" and "of which described a store" will differ from the
  older rows in `RESULTS.md`. `summary()` filters them out (`data_server.py:110`),
  so the table's own numbers are unchanged, as the document says; the
  many-sources report is the one that moved.
- **Three of the six follow-ups have no test of their own** (question 1):
  the watcher's `toldAbout` fix, the `os.replace` fallback, and the Viewer's
  `measurementState` on a *successful* answer (the microscopy jsdom test
  checks the panel against a stub; nothing on the Viewer side asserts what
  `_serve_measurement` sends when it succeeds).
- **The corrupt-description sentence has no new test.** `contrast.py:230-236`
  now names a file that is not JSON; the three tests that write `{ this is not
  json` (`test_contrast.py:169, 208, 270`) assert the state and that an error
  exists, not the sentence.
- **The Viewer's version is still `0.2.0`** (`pyproject.toml:7`, unchanged
  from `9ff10b0`), there is no tag, and the microscopy `pyproject.toml:6-7`
  still names itself `zmart-viewer 0.1.0`. Decision 3 makes the capabilities
  the contract, which is right; but the release section should say that the
  version number will not tell the two apart, and that `pip show` on the
  microscope PC is not evidence of which Viewer is installed — only
  `/api/health` is.
- **`msvcrt.locking` reads plausibly.** I could not reach the Python
  documentation from here (the proxy refuses `docs.python.org`), so this is
  from memory of it: `LK_NBLCK` locks the given number of bytes from the
  current file position and raises `OSError` at once if it cannot, which is
  the non-waiting behaviour the sweep needs; `LK_UNLCK` must unlock the same
  bytes; region locks go when the handle closes or the process ends. The
  lock file is opened `a+` and never written, so both sides stand at offset 0
  and lock the same byte; `_let_go_of_the_lock` seeks to 0 first
  (`scratch.py:71`), `_take_the_lock` does not (`scratch.py:53`), which is
  fine only while the file stays empty. Write the `seek(0)` in both places so
  that invariant is not silent. Nothing here was run on Windows, as the
  document says.
- **`data_server.py:336` bounds the served folder by a string prefix**, so
  `/data/../run2` is refused but a sibling whose name begins with the served
  folder's name is not. Pre-existing, local-only; note it.

### What was checked and is right

- **No path stamps a per-position window.** Searched both repositories for
  `_a_window_onto`, `percentile`, `.described(` and `channel_blocks`. The
  three `percentile` calls left in the microscopy repository are the
  matplotlib overview widget (`widget.py:316`, a slider range on screen, not
  written), the plate drawing (`draw_the_plate.py:152`, a PNG for the eye) and
  an analysis embedding. Every writer that calls `.described()` guards it:
  `canvas.py:1433`, `cropped.py:958`, `positions.py:476-480`,
  `omezarr.py:361-364`. `linked.py:1744-1752` reads windows out of the tiles'
  own blocks and never invents one. The Viewer's only percentiles are in
  `contrast.py`, its measurement.
- **Probe A, the three shapes through every reader.** Two positions (dim and
  bright) written by the real writer with no description, with an unresolved
  one, and with a resolved one. No description: no `omero` in either store;
  ngio 1.0.0 opens both (`channel_0`); the composed group has no `omero` and
  no `zmart` block; the built picture measures `20101…23892`, state
  `provisional`; ngio opens the built picture. Unresolved: no `omero` in the
  stores; the composed group says `displayWindowSource:
  zmart-acquisition.json` with `displayWindows: [{key: 488, index: 0}]` and no
  window; measured `provisional`. Resolved: `GFP` with `300…4200` in every
  store, in the composed group with provenance `acquisition-record`, and
  `declared` in the Viewer's row. That is the verification matrix's "live,
  measurable but unresolved" row as written. (napari's `ome-zarr` reader is
  not installed here and was not run.)
- **The handshake's follow-ups are real.** `viewer_service.py:180-201` parses
  inside the guard and builds an opener with no proxy (`ProxyHandler({})`,
  line 194), which also closes the 80% review's proxy remark;
  `_put_down` (164-177) shuts, joins and closes on both the refusal path and
  the exception path; `stop()` closes the socket (218); the sentence for a
  Viewer that did not answer is separate (143-147). The three tests assert a
  refused connection with a raw socket, not a timeout.
- **The watcher fix is what was asked** (`watching-the-run.js:165-173`):
  `toldAbout` is set only after `canvas.tell` ran.
- **The end-to-end test's tampering is real** (`test_one_window_end_to_end.py:77-80`):
  the first-sorting position claims `5…50` and the composed group still says
  `300…4200`.
- **The ngio fact is a test against ngio** and it ran here (it is one of the
  104 Viewer tests that passed, and ngio 1.0.0 is installed, so it was not
  skipped).
- **The `zmart_live` fix is the same shape as the others**
  (`omezarr.py:355-364`), and the whole suite is green.
- **The strict `xfail` is honest.** The `neuroglancer-under` case of the stack
  test reports `XFAIL`, and with `--runxfail` in mind the reason is the one
  the mark gives: the engine reads `atUm: 0` at its first plane (probe, stack
  default `{'lowUm': 0, 'highUm': 6, 'stepUm': 2, 'atUm': 0}`), not a missing
  depth control. `strict=True` means the day it opens at 4 µm the mark must
  come off.

---

## 2. Answers to the eight questions

### Q1. Are the six follow-ups closed, in code, with a test that would fail if they reopened?

1. **`zmart_live` and `zmart_storage/positions.py` omit the block — closed,
   tested.** Code: `zmart_live/omezarr.py:355-364`, `zmart_storage/positions.py:476-480`.
   Test: `zmart_live/tests/test_omezarr.py::test_channels_that_have_not_chosen_a_window_write_no_channel_block`
   (asserts no `omero`) and `…::test_channels_that_chose_a_window_are_described_the_way_a_reader_expects`.
   The `positions.py` guard has no test of its own; every caller in
   `zmart_storage/tests` supplies a window. The document's choice to fix rather
   than retire `zmart_live` is stated and justified (the vendored viewer under
   `viz_studio/backend` imports it).
2. **The handshake — closed, tested.** Code: `viewer_service.py:104-201, 204-218`.
   Tests: `test_a_refused_viewer_is_stopped_and_its_socket_closed`,
   `test_an_answer_of_an_unexpected_shape_is_no_promise_and_leaks_no_server`,
   `test_a_viewer_that_does_not_answer_is_not_called_too_old`
   (`test_viewer_service.py:93-172`), each ending in `_refuses_connections`,
   which accepts only `ConnectionRefusedError`.
3. **The upgrade sentence counted as told only after a canvas — closed in
   code, not tested.** Code: `watching-the-run.js:165-173`. No vitest covers
   `watching-the-run.js`; `viewer-panel-look.spec.js` mentions it only to say
   it mounts the panel the same way. A reopened fault would not fail anything.
4. **Provisional and settled words — closed, tested on the microscopy side.**
   Code: `server.py:753-758` (the route says `settled` or `provisional` from
   `coarsest_level_is_written`), `viewer-panel.js:787-797` (the sentence).
   Test: `viewer-panel-waiting.test.js:118-140` asserts the sentence for
   `provisional` and none for `settled`, and its stub now matches what the
   route sends. Nothing on the Viewer side asserts the new field on a
   successful answer (`test_server.py` checks `waiting` and `unreadable` only).
5. **Tampering and the hard-link fallback — closed; the first tested, the
   second not.** Code: `test_one_window_end_to_end.py:77-80`;
   `acquisition_description.py:280-291` (`os.replace`, read back, compare,
   fsync). No test drives the `OSError` branch; a fallback that silently kept
   a different description would not be caught.
6. **The ngio fact — closed, tested against ngio.**
   `tests/test_the_channel_shapes_a_strict_reader_accepts.py`, four shapes,
   `importorskip("ngio")`, ran and passed here.

### Q2. M3

**Does any path still stamp a per-position window?** No. `_a_window_onto` is
gone; `zarr_positions.py:155-158` passes the description's blocks or `[]`;
`_declare_one` writes `omero` only when given blocks (`canvas.py:2247-2255`);
the search above found no other writer that invents one, and the Viewer's own
live path was already window-less at 80%. Test: `test_zarr_positions.py:130-161`,
both the no-description and the unresolved dim-and-bright cases assert
`"omero" not in ome`.

**Does an unresolved acquisition write a store every reader opens?** ngio
1.0.0 and the Viewer's composer, builder and measurement: yes, by probe A. A
napari-style reader: not run here (`ome_zarr` is not installed); the OME-Zarr
specification makes `omero` optional and the 80% review's ngio check already
covered the strict end, so I would call this supported but not observed.

**Is the boundary refused at start, and does the run continue without the
live canvas rather than with a black one?** Yes. `bridge.py:243` starts the
Viewer on connect and its comment says a Viewer that cannot start is "a
sentence on `/api/viewer`, never a failed connect"; `_keep_position_as_zarr`
(`bridge.py:721-745`) writes the store first and only then rings
`a_position_landed`, which returns at once when there is no port
(`viewer_service.py:255-257`); the scan does not consult the Viewer. The
sentence's path to the canvas is as the 80% review traced it, now with the
`toldAbout` fix. It still has not been walked in a browser, and the refusal
has still only been seen against a pretend `{"ok": true}` server, not against
`9ff10b0` running — the document admits the first and should admit the second.

**A recording made before `b79fb46e`, with no `channels`.** `bridge.py:851-852`:
`channels is None` publishes no descriptor; `position_store_from_record` then
finds no description and writes no block; the Viewer measures and says
`provisional`. That is now a deliberate, tested state (`test_no_description_writes_no_channel_block_and_measures_nothing`)
rather than the accident the 80% review feared. One thing to know: if the same
run folder already holds a sidecar from an earlier scan of the same type, a
later scan without `channels` inherits it (`zarr_positions.py:119-121`), which
is the I1 rule and is fine, but is worth a sentence in the document. A run that
was upgraded mid-way — early positions with a per-position window, later ones
with none — is the Viewer's `test_a_position_without_omero_beside_positions_with_it_still_opens`,
which passes.

### Q3. S1, read adversarially

- **A symlink named `session-…`:** refused at `scratch.py:148` before anything
  else is looked at, and tested (`test_a_symlink_or_an_escaped_candidate_is_refused…`).
- **A folder reached through a symlinked root:** `home` is resolved
  (`scratch.py:150`), so a root or kind folder that is itself a link is
  followed, and folders under wherever it points are swept if unlocked. That
  is a choice, not a fault — the root is the Viewer's own — but it means the
  plan's "resolve it under the exact managed root" is "under the resolved
  root". Say so.
- **A folder another process locked between the `is_mine` check and the lock
  attempt:** safe — the lock attempt fails and the folder is kept. The
  dangerous interleaving is the one after the lock attempt (finding I3).
- **A filesystem where `flock` is advisory:** every `flock` is advisory; only
  Viewers take part, so that is enough. **Where it is unsupported:** `open()`
  refuses to make any folder (probe B2), and the sweep keeps everything.
  Fail-closed, but the Viewer is then unusable for composing, with a sentence
  about a lock (minor observation).
- **Does `close()` release before `rmtree`?** Yes (`scratch.py:136-140`); if
  `rmtree` fails the folder stays, unlocked and forgotten by this session, and
  the next start reclaims it. That is the design working.
- **Windows:** plausible as read (minor observation), not run.
- **Does `/api/scratch` walk the root on every request?** Yes; acceptable on
  demand, not for polling.

### Q4. Z1

`test_a_plane_is_sampled_at_its_centre.py` does not prove what its docstring
says (finding I1): its metric is satisfied by the empty box, and a source
sampled *at* its upper boundary is drawn anyway. The second assertion — no
depth control for a single plane — is real. The stack half holds `viv-under`
to the rule with a real reading of `atUm == 4.0`, and that is a genuine test.
The strict `xfail` is honest. The claim that changing the engine's opening
height is out of scope is defensible — the first-plane rule was put there for
a documented reason and `planes.js` says which case has to be in front of
whoever changes it — but the package leaves the engine's own arithmetic
inconsistent (finding I4), which is inside scope.

### Q5. H1

- **Does `--external-run` write anything beside the run?** Not under any input
  I tried: the probe's listing of the run before and after was identical, the
  test asserts the same, and reading `real_run.py`, `drive.py` and
  `data_server.py` finds writes only under `out`. `run.py:120` refuses
  `--data` alongside it.
- **Does the byte count include every response?** Every `/data/` response
  body, including empty 404s (0 bytes), `HEAD` (0), and the repaired
  descriptions (the body actually sent, `data_server.py:392-395`). Headers are
  not counted; page assets and `/api/` answers are not counted, which is right.
- **Could the old numbers have changed?** `summary()`'s request arithmetic
  runs over pieces alone (`data_server.py:110`), so the table's numbers are
  unchanged. `many_sources.py`'s are not (minor observation).
- **Does `the_store_to_open` choose sensibly, and refuse sensibly?** It
  refuses a missing path and a folder with no store, plainly. Its preference
  for a composed `*.zmartview.zarr` is sensible in intent and unopenable in
  practice, and the positions it does find do not open either (finding I2).

### Q6. The end-to-end test's legacy half after M3

It is still a proof that nobody's window wins, and it has not become a test
of the stamping. The stamping (`test_one_window_end_to_end.py:110-116`) is
fixture-making: it writes two disagreeing `omero` blocks by hand into stores
the real writer produced, which is exactly what a pre-migration run looks like
on disk. Everything asserted afterwards is Viewer behaviour on that fixture:
no `omero` in the composed group, `displayWindows == []`, a measured window
that equals neither stamped window. The one assertion that has become
tautological is `windows[0] != windows[1]` at line 118 — it now checks the
fixture rather than the writer — and it could go. The measured window
(`20101…23892` in probe A's equivalent) is real and equals neither.

### Q7. Regressions

Nothing red that was green. The four microscopy suites went from `822 passed,
80 failed, 4 skipped, 15 errors` to `917 passed, 7 skipped` (917 = 822 + 80 +
15, so every red test now passes). `application/workflows`: 103 passed, 2
skipped, as before. vitest: 393 passed, 15 skipped, as before. The Viewer's six
listed files: 104 passed, against 94 for the four files the 80% review ran plus
the ten tests in the two new files. The viz_studio checkpoint tests: 4 passed,
1 xfailed. The seven skips in the microscopy suites are optional outside
readers (`ngff-zarr`; four of them in `zmart_live`, which were among the red
tests at 80%), `umap` not being installed, and one deliberate skip in
`test_canvas.py`; nothing new is being skipped. `test_the_options_hold_together.py`
has five failures, which the 100% document names as pre-existing debt while
calling them four; see section 5.

### Q8. Release

The order is right — Viewer first, so that the running Viewer promises both
capabilities before the writer asks, then the microscopy repository — and an
old writer beside the new Viewer was shown safe at 80%. Two things are missing
from the release section: how the Viewer is updated on the microscope PC
(`environment.yml:91-96` says it is a local checkout installed with `pip
install -e`, so "release" means pulling that checkout, and the version number
will not change), and that the acceptance evidence the 80% review asked for
before M3 — the handshake seen accepting the new Viewer and refusing `9ff10b0`
on the microscope PC, the real bridge-driven run photographed, the cold-open
numbers — has not been produced; the document says M3 was "landed after" the
six follow-ups, which is true, and does not say those gate items were skipped.

Missing from "what 100% does not do": H1 does not open the bridge's own
positions (I2); H1 is one opening of one store, not the plan's ten-step trace,
memory proxy or "reproduce one known Viewer measurement within a tolerance"
gate; Z1 is a narrower test in `viz_studio`, not the plan's extension of
`the-window-step-by-step.spec.js` and `which-layer-draws.spec.js` with the
overlay-anchor and raw-Z assertions; the Windows lock has not run on Windows
(said); the browser walk of the upgrade sentence is still missing (said, in
another section).

---

## 3. Facts and inferences, in one place

**Observed:** everything marked observed in sections 1 and 2; the probe
outputs quoted; the test numbers below.

**Inferred:** that the engine rounds a boundary position into the last voxel
(from the photographs, not from the engine's source); that the two-Viewers-
starting-together window is milliseconds wide (from reading `open()`, not
timed); that releasing before deleting was chosen for Windows (from the
shape of the code, not a comment); the `msvcrt` semantics (from memory of the
documentation, which could not be fetched here); that napari-style readers
open a store without `omero` (from the specification, not run).

---

## 4. What the 100% document should say differently

- Z1: "photographs it drawn" → "opens it and confirms a depth control is not
  offered"; drop "a source sampled off its edge photographs as black" until a
  test shows it, and note that the edge itself draws.
- H1: "measures one option on a real store or run folder" → "on an OME-Zarr
  0.4 store that keeps a coverage record; the bridge's positions do not open
  yet", or fix it.
- H1: "how much of the box was actually drawn" → remove until the metric can
  tell.
- S1: state the resolved-root behaviour and the release-before-delete
  ordering, or fix the ordering.
- Release: say the version number does not change and how the checkout is
  updated; say which of the 80% review's M3 gate items were not done.
- The six follow-ups: say which three have no test.

---

## 5. Tests run

Environment: Linux container, Python 3.11.15, numpy, zarr 3.1.6, tifffile,
scikit-image, pooch, ome-types, matplotlib, playwright and ngio 1.0.0 as
installed; Node 22; software rendering; Chromium at
`/opt/pw-browsers/chromium-1194/chrome-linux/chrome` through
`ZMART_CHROMIUM`. `node_modules` and the built pages were copied from the
working folders into the worktrees. The Viewer package was used as
`PYTHONPATH=/tmp/final-v`, checked to resolve `zmart_viewer.__file__` into the
worktree and not the editable install (`pip show zmart-viewer` reports 0.2.0
from the working folder). All pictures were drawn in software.

| Suite | Where | Result |
|---|---|---|
| microscopy `application/parts`, `application/framework`, `zmart_storage/tests`, `zmart_live/tests` | `78356da6` | **917 passed, 7 skipped, 1 warning** in 2 m 58 s (80%: 822 passed, 80 failed, 4 skipped, 15 errors) |
| microscopy `application/workflows` | `78356da6` | 103 passed, 2 skipped in 25 s (unchanged) |
| microscopy `vitest` (`npx vitest run` in `application/`) | `78356da6` | 28 files, **393 passed, 15 skipped** in 4.8 s (unchanged) |
| microscopy `viz_studio/tests/test_a_plane_is_sampled_at_its_centre.py`, `test_a_foreign_run_can_be_measured.py`, from `viz_studio/`, real Chromium, `ZMART_REQUIRE_BROWSER=1` | `78356da6` | **4 passed, 1 xfailed** in 13 s; the xfail is `neuroglancer-under`, as marked |
| microscopy `viz_studio/tests/test_the_options_hold_together.py`, real Chromium | `78356da6` | **42 passed, 5 failed, 1 skipped** in 2 m 48 s: the plane-rule source check, the detail scan on `neuroglancer-under`, and the `foreign` store on all three engines ("has no coverage record" — the same refusal as finding I2). The 100% document calls these "four checks" and then lists five; five is the number. I did not run the suite at `ae40fb58`, so "identical before" is the document's claim, not mine. |
| Viewer `test_session_scratch.py`, `test_server.py`, `test_contrast.py`, `test_a_transfer_is_built_into_one_picture.py`, `test_the_channel_shapes_a_strict_reader_accepts.py`, `test_unresolved_profile_windows.py`, page built, real Chromium, `ZMART_REQUIRE_BROWSER=1` | `8880c7d` | **104 passed** in 36 s; the ngio test ran (not skipped) |
| Viewer full `tests/` | — | **not run by me.** The run from the working folder was still going (47 tests in) when this was written; I did not start a second one. |
| Probe A: no description / unresolved / resolved through ngio, the composer, the builder, the measurement | both | all three open everywhere; windows as in section 1 |
| Probe B: sweep with a new owner arriving as the lock is released | `8880c7d` | folder deleted under a live lock holder (finding I3) |
| Probe B2: a folder that cannot be emptied; a lock that cannot be taken | `8880c7d` | reported removed regardless (as root, it was removed); `open()` raises `RuntimeError` |
| Probe H1: `real_run.measure` on positions written by `position_store_from_record` | both | refused, "has no coverage record"; nothing written beside the run |
| Probe Z1 (three passes): the one-plane source and a four-plane stack photographed at a series of heights | `78356da6` | picture present on [0, 1.0] voxel and absent outside; `_drawn_share` 1.000 throughout; `setPlane`/`theDepthItCanShow` half a voxel apart |

**Not run, and why:** the Viewer's full suite (above); the microscopy Playwright
walks (`application/*.spec.js`), which need a dev server and a bridge and were
not asked for; the driver hardware suites; anything on the microscope PC;
anything on Windows; a napari-style reader (`ome-zarr` not installed).
