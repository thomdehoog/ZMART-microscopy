# Review brief: the 80% checkpoint of the viewer delivery migration

Date: 2026-09-02

Please review the implementation; do not implement anything.

## Revisions

- ZMART-microscopy at `/home/user/ZMART-microscopy`, branch
  `claude/viewer-delivery-to-100`, commit `ae40fb58`. Its parent `b79fb46e`
  is Codex's correction of the 50% checkpoint.
- ZMART Viewer at `/home/user/zmart-viewer`, branch
  `claude/viewer-delivery-to-100`, commit `02cf88d`. Its parent `2b4338e` is
  Codex's correction; `9ff10b0` is the released 0.2.0.

Review the committed state. Make a separate worktree of each commit under
`/tmp` for reading and for running tests, so that the working folders are
not disturbed by the review. Do not modify either working folder.

## Read first

1. `docs/design/viewer-delivery-implementation-plan-80-percent.md` — what
   this checkpoint claims and the decisions it closes.
2. `docs/reviews/2026-09-01-review-of-the-50-percent-viewer-delivery-implementation.md`
   — the previous review; its blockers should be closed now.
3. `docs/design/viewer-delivery-implementation-plan-50-percent.md` — the plan
   the packages come from.
4. `CLAUDE.md` in each repository.

## The diffs to review

ZMART-microscopy, `b79fb46e..ae40fb58`:

- `application/parts/storage/viewer_service.py` — the capability handshake.
- `application/parts/storage/test_viewer_service.py`.
- `application/parts/canvas/viewer-panel.js` — the waiting state; no
  `{low: 0, high: 65535}` fallback remains.
- `application/parts/canvas/viewer-panel-waiting.test.js`.
- `application/parts/canvas/viewer.js`, `application/parts/microscope/live.js`,
  `application/parts/microscope/mock.js`, `application/framework/window/main.js`,
  `application/workflows/target_acquisition/steps/scan_the_overview/watching-the-run.js`
  — the upgrade sentence reaching the canvas.
- `application/parts/storage/test_one_window_end_to_end.py` — I1.
- `zmart_storage/cropped.py` — a regression fix.

ZMART Viewer, `2b4338e..02cf88d`:

- `zmart_viewer/acquisition.py` — the capability strings.
- `zmart_viewer/server.py` — `/api/health` and `/api/measure`.
- `zmart_viewer/contrast.py` — a declared window is reported as declared.
- `tests/test_server.py`, `tests/test_contrast.py`,
  `tests/test_a_transfer_is_built_into_one_picture.py`.

Also re-read Codex's parents, `b79fb46e` and `2b4338e`, against the previous
review's four blockers, because this checkpoint builds on the claim that they
are closed.

## Questions

1. Are the previous review's four blockers closed? For each, name the code
   that closes it and any way it could reopen.
2. Is the capability handshake safe in both directions: new writer with an
   old Viewer (the `9ff10b0` health answer is `{"ok": true}`), and old writer
   with a new Viewer? Can the refusal be bypassed — a health answer that is
   slow, malformed, or from a different server on the port?
3. Does the upgrade sentence actually reach an operator? Trace
   `viewer_service.status()["error"]` through `/api/viewer`, `viewerTrouble()`,
   `watching-the-run.js` and `viewer.js`'s `tell`. Is there any path where the
   viewer is refused and the canvas stays silent?
4. In `viewer-panel.js`, search for every place a window is read or assumed
   numeric. Can any control, drag, typed value, `Reset`, `Auto`, or the
   histogram act on a `null` window? Can the four brightness states
   (`waiting`, `unreadable`, `provisional`/`settled`, `declared`) ever
   disagree between the embedded panel and the Viewer's `LayerPanel.jsx`?
5. Does `/api/measure`'s empty answer distinguish absence from fault in the
   same way `measure()` does, and is `_readability_problem` safe to call on
   the store the route resolved?
6. Is the I1 test proving the five equalities, or mirroring the
   implementation? Could it pass with the first-position-wins behaviour it
   is meant to exclude?
7. Decisions 1–9 in the 80% document: is any of them wrong, unsupported by
   the code, or contradicted by a test?
8. What does M3 need that is not in place — name the exact conditions under
   which `_a_window_onto` may be removed.
9. Run the tests. Both repositories' Python suites (install what they need:
   `numpy`, `zarr>=3`, `tifffile`, `scikit-image`, `pooch`, `ome-types`,
   `matplotlib`, `playwright`, and the Viewer as `pip install -e . --no-deps`),
   the microscopy `vitest` suite (`npm --prefix application install` first),
   and at least the Viewer's browser tests for contrast and the transfer with
   the page built (`npm --prefix app/page install && npm --prefix app/page
   run build`) and `ZMART_REQUIRE_BROWSER=1`. Report exact numbers. Say which
   suites you could not run and why.

## Output

Write the review to
`docs/reviews/2026-09-02-review-of-the-80-percent-viewer-delivery-implementation.md`
in the ZMART-microscopy worktree you made for reading (not the working folder),
and return its full text as your final message. Lead with a verdict: accept,
accept with follow-up, or revise before continuing. Then findings ordered by
severity with file and line, facts separated from inferences, then the
answers to the nine questions, then the tests run with numbers. Write in
complete sentences for a reader who is a microscopist, not a software
engineer, as `CLAUDE.md` asks.
