# Review of the Smart Viewer integration plan

**Date:** 2026-09-01.
**Plan reviewed:** "Smart Viewer in Smart Operator — integration plan", dated
2026-09-01, intended for branch `codex/smart-viewer-integration-cleanup`.
**How it reached this review:** as text. The branch was not on the remote when
this was written, so the plan is not quoted here in full; whoever reads this
should have it open beside them.
**Smart Viewer at the time of review:** `thomdehoog/ZMART-viewer`, commit
`9ff10b0`, version 0.2.0, cloned in this container at
`/home/user/thomdehoog/zmart-viewer`.
**The branch being commented on:** `claude/viewer-port-remaining-steps-ofm5qp`,
seven commits `908a201` … `4ab5903`, described in
`2026-09-01-handover-smart-viewer-integration.md`.

Everything asserted below was checked against the two repositories rather than
remembered, and the check is named each time so it can be repeated.

---

## 1. The one finding that changes the plan's shape

In Smart Viewer 0.2, `POST /api/stores/open` no longer opens a folder directly.
It goes through `zmart_viewer/loading.py`, described by its own author as "one
door: classify what a path is, then open it the one right way". The docstring of
`load` says what happens to a folder of per-position stores:

> `scenes` is where a composed description may be written for a run of positions
> opened directly (left None, such a run is refused).

The server always passes it. `_scenes_of_this_session()` makes
`~/.zmart-viewer/scenes/session-…` the first time it is wanted, so there is
nothing to configure. **A run of positions opened through `/api/stores/open` is
therefore composed into one picture by the viewer itself.**

That is the call this repository already makes.
`application/parts/storage/viewer_service.py` asks for exactly three things —
`/api/announce`, `/api/stores/close` and `/api/stores/open`, at lines 173, 228
and 230 — and `_link` already closes **both** the acquisition's own name and
`f"{acquisition_type}.zmartview.zarr"` before opening again. The operator code
already knows the composed scene by name. It has simply never been talking to a
server that makes one: the copy under `viz_studio/backend/` has no `loading`
module at all, so it hands back the position stores one at a time and
`_only_the_newest_of` keeps one of them.

**Correction.** The plan should open with a measurement rather than a port.
Install 0.2, run Step 5 unchanged, and read `GET /api/viewer` on the bridge. If
it answers with one overview source covering the whole scan, then plan steps 2
to 6 are largely solving a problem the version bump has already solved, and the
plan should be re-scoped around whatever genuinely remains. This is a
fifteen-minute experiment that may remove weeks of work, and no part of the plan
should be started before it has been done.

A note against an earlier suggestion of this reviewer's, so that it is not
followed by mistake: `/api/stores/construct` is probably *not* the right route
here. It exists to build a picture over raw data explicitly, and `open` already
covers the run-of-positions case.

---

## 2. Corrections of fact

**"currently fails at least one cross-engine plane-selection contract."** This is
offered as a reason to set the earlier branch aside, and it is not true of that
branch. `test_no_option_decides_for_itself_which_plane_to_open_on` fails
identically at `93e374c`, the commit the branch was taken from (45 tests
deselected), and at its head (47 deselected, because two checks were added). It
is inherited from `claude/viewer-layer-020-617xad`:
`neuroglancer-under/viewer.js` no longer imports `../planes.js`. The claim
should be dropped, and the failure carried forward as debt that has to be fixed
whichever branch wins.

The plan's *conclusion* — that the earlier branch should not be the viewer
authority — is right, and there is a better argument for it available. Smart
Viewer 0.2's `app/page/src/LayerPanel.jsx` is 1,745 lines; the copy under
`viz_studio/frontend/src/` that the earlier work was ported from is 1,012. The
interface has moved on substantially, which is what the maintainer said at the
outset. That is a stronger and more honest reason than a failing test that
predates the work.

**The "retain and re-verify" list mixes up where things came from.** Four of its
seven items — flat positions meeting on one map plane, a rerun acquisition
leaving the page on a revoked source, resolution levels at plate scale, and one
viewer owning both pixels and overlay projection — belong to the companion note
`2026-09-01-why-the-acquired-overview-never-appeared.md` and to earlier work on
`claude/viewer-layer-020-617xad`. They are worth retaining, but nobody should go
looking for them in the seven commits under review; they are not there.

---

## 3. Two things the plan asks for that are already written

Worth naming plainly, because deciding not to adopt them means writing them
again rather than not having them.

**Plan step 4** asks that "before any acquisition exists, the operator canvas
still needs its own finite view so the plate and plan can be drawn. Once Smart
Viewer has a measured image space, the image view becomes authoritative and the
overlays follow it." That is precisely what commit `4ab5903` does. Before it,
every position in micrometres projected to `NaN` for the first four steps of the
workflow and the canvas was blank; after it, a planned field at (17324, 17324)
micrometres lands at (123.3, 123.3) on screen. It is also the riskiest commit on
the branch and the one most deserving an adversarial read — but it should be
reviewed rather than re-derived.

**Plan step 5** asks that "showing focussing again must restore the channel
choices it had before the group was hidden." That is the fault found and fixed
in `5376b7f`. The panel's `refresh` drew each eye from what the engine was
really doing, which is correct, and *also* wrote that back as the operator's own
choice — so while an acquisition was hidden, every one of its channels was
recorded as one the operator had turned off, and showing the acquisition again
asked for nothing at all. The heading's eye opened over a picture that stayed
dark. This was already failing on the branch before the work under review.

Three further pieces are worth carrying whichever viewer ends up drawing,
because none of them depends on the viewer:

- the three additions to `viz_studio/options/contract.md` —
  `whenTheViewMoves`, `theMomentsItCanShow`, and `setChannel({ lut })` with
  `lutsItCanDraw` — each answered by all four options and each with a guard
  check in `viz_studio/tests/test_the_options_hold_together.py`;
- `application/parts/canvas/counting-planes.js` and
  `application/parts/canvas/the-window.js`, with twenty-three unit checks
  between them; both are plain arithmetic with no engine in them;
- the contrast track falling back to the window the run declared rather than to
  the whole of what a sixteen-bit camera can produce. Measured on the mock's own
  overview, that is the difference between a slider with about two pixels of
  usable travel and one that works.

---

## 4. Where the plan would rebuild what Smart Viewer already has

**Step 3 contradicts the plan's own boundary.** It proposes porting
`app/page/src/scene.js`, `engine.js` and `live-refresh.js` into the operator.
That is 2,217 lines, of which `engine.js` alone is 1,732 — and `engine.js` *is*
the Neuroglancer synchronisation that the plan's own boundary section assigns to
Smart Viewer. Porting it across is the "second, parallel Neuroglancer
implementation" the plan forbids two sections earlier.

It also collides with structure that already exists here. The operator keeps its
drawing engine behind `viz_studio/options/contract.md`, and
`test_the_engine_stays_behind_its_adapter` fails if any file other than
`neuroglancer-under/viewer.js` imports neuroglancer. A ported `engine.js` would
either break that guard or require a second exemption from it, and the guard
exists so that changing engines one day stays a single-file job.

The choice should be made explicitly rather than by drift. Either the operator
keeps its adapter and Smart Viewer's configuration drives it, or Smart Viewer's
own page is mounted whole inside the operator window. Porting the viewer's
internals into the operator is the one option that gives the costs of both.

---

## 5. Risks the plan does not mention

1. **The viewer's page is not built in a fresh clone.** There is no
   `app/page/dist`, and `make_server`'s `site_dir` defaults to it and serves it
   as the static directory. The bridge only uses the API, so this may not be
   fatal, but it is an unlisted build step and should be stated either way.
2. **Installing the viewer fails on a dependency it does not need.**
   `pip install -e .` stops on `proxy_tools`, which comes in through
   `pywebview` — the desktop window — and has no wheel for this container. The
   server itself does not need it.
3. **Every acceptance gate must name the server it ran against.** `/api/measure`
   exists in 0.2 and does not exist in `viz_studio/backend/`. A run against the
   vendored copy shows an empty histogram and a dead *Auto* button on every
   channel, and proves nothing about either.
4. **The plan does not say what becomes of the older copies.** Leaving both
   `viz_studio/backend/` and `viz_studio/frontend/src/` importable is how the
   present confusion arose — a stand-in server was written against the wrong one
   and behaved almost, but not quite, correctly. At minimum they should be
   declared reference-only, and nothing reachable at run time should be able to
   import them.
5. **The container has to be able to run the workflow at all.** The focus
   environment `ZMART--focus--main`, and the packages `zarr`, `numpy`,
   `tifffile`, `imagecodecs`, `scikit-image` and `pooch`. Without them Step 4
   never finishes and Step 5 never begins. These are recorded in
   `2026-09-01-handover-smart-viewer-integration.md`.

---

## 6. Gates that are missing, and one that contradicts itself

**The 0, 3, 6 and 9 screenshots cannot be taken with Step 5's own Run button**,
which the plan also requires. That button scans all nine positions. Stopping
part-way is what `live-bridge.js`'s `image(positions)` is for — it drives the
bridge one call at a time, which is the only way to photograph a scan as it
arrives rather than after it has finished. The plan asks for both and should
choose.

Three gates are missing, and each of them guards something that has actually
been broken here:

- **The plate must stay on screen when the picture arrives.** At present the
  engine's opening view replaces the workflow's Fit the moment an acquisition
  lands, so an operator who has framed their plate loses that framing without
  being told. The whole-plate screenshot checks that the overview sits in the
  right physical place; it does not check that the framing survived.
- **The canvas must draw before any acquisition exists.** With no picture, a
  planned field must project to a finite position on screen. This is what was
  blank for the first four steps of the workflow, and the 0-of-9 screenshot
  covers only part of it.
- **Panning and zooming must work before any acquisition exists**, because
  laying a plan out on an empty plate is exactly when an operator needs to move
  around it.

---

## 7. The smallest changes most likely to give a working Step 5 today

In this order, stopping as soon as it works.

1. Install Smart Viewer 0.2 without the desktop-window extra, so that
   `from zmart_viewer import server` resolves to the real package.
2. Run the existing walk unchanged and read `GET /api/viewer` on the bridge.
   **This is the decisive measurement:** either one overview source covering the
   whole scan, or one per field.
3. If it is one, run `every-tile-is-filled.spec.js` with the focussing hidden,
   and then look at the photographs in `test-results/step-by-step/`. That may be
   the whole of the work.
4. Only if it is still one per field, look at how `loading.load` classifies a
   `positions/<type>` folder, and treat `/api/stores/construct` as the fallback
   rather than the first move.

Plan steps 2, 3 and 6 are large. None of them should begin until steps 1 to 3
above have shown where the boundary between the two projects genuinely needs to
move.
