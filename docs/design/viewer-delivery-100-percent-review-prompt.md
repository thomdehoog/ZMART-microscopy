# Review brief: the 100% checkpoint of the viewer delivery migration

Date: 2026-09-02

Please review the implementation; do not implement anything.

## Revisions

- ZMART-microscopy at `/home/user/ZMART-microscopy`, branch
  `claude/viewer-delivery-to-100`, commit `78356da6`. The 80% checkpoint was
  `ae40fb58`; between them: `960d15d9` (Z1, H1), `543ca9f0` (M3), `10cdafb8`
  (the answers to the 80% review), `78356da6` (the checkpoint document).
- ZMART Viewer at `/home/user/zmart-viewer`, branch
  `claude/viewer-delivery-to-100`, commit `8880c7d`. The 80% checkpoint was
  `02cf88d`; between them: `f75fa63` (S1), `8880c7d` (the answers to the 80%
  review).

Review the committed state. Make a separate worktree of each commit under
`/tmp` for reading and for running tests, so that the working folders are not
disturbed. Do not modify either working folder.

## Read first

1. `docs/design/viewer-delivery-implementation-plan-100-percent.md` — what is
   claimed complete and what is left open.
2. `docs/reviews/2026-09-02-review-of-the-80-percent-viewer-delivery-implementation.md`
   — the previous review; its six follow-ups should be closed.
3. `docs/design/viewer-delivery-implementation-plan-50-percent.md` — the
   packages M3, S1, H1, Z1 as originally specified.
4. `CLAUDE.md` in ZMART-microscopy.

## Questions

1. **The six follow-ups.** Is each closed, in code, with a test that would fail
   if it reopened? Name the code and the test for each.
2. **M3.** With `_a_window_onto` gone: does any path still stamp a
   per-position window? Does an unresolved acquisition write a store that
   ngio, napari-style readers, and the Viewer's own reader all open? Is the
   compatibility boundary (this writer beside a `9ff10b0` Viewer) refused at
   start, and does the run continue without the live canvas rather than with a
   black one? What happens to a recording made before `b79fb46e`, which carries
   no `channels`?
3. **S1.** Read `zmart_viewer/scratch.py` adversarially. Can `sweep_orphans`
   delete something it should not: a symlink whose name starts with
   `session-`, a folder reached through a symlinked root, a folder another
   process locked between the `is_mine` check and the lock attempt, a folder
   on a filesystem where `flock` is advisory-only or unsupported? Does
   `close()` release before `rmtree`, and what happens if `rmtree` fails? Is
   the Windows branch (`msvcrt.locking`) plausible — it cannot be run here,
   so read it against the documentation. Does `/api/scratch` walk the root on
   every request, and is that acceptable?
4. **Z1.** Does `test_a_plane_is_sampled_at_its_centre.py` prove what its
   docstring says, or could a source sampled off its edge still photograph
   as drawn? Is the strict `xfail` for `neuroglancer-under` honest, and is the
   claim that changing the engine's opening height is out of scope defensible?
5. **H1.** Does `--external-run` write anything beside the run under any
   input? Does the byte count in the ledger include every response, and could
   the old measurements' numbers have changed? Does `the_store_to_open`
   choose sensibly, and refuse sensibly?
6. **The end-to-end test after M3.** Its legacy half now stamps disagreeing
   windows by hand. Is that still a proof that nobody's window wins, or has it
   become a test of the stamping?
7. **Regressions.** Run the tests (section below) and compare with the
   numbers the previous review recorded. Anything red that was green?
8. **Release.** Is the release order in the 100% document right, and is
   anything missing from "what 100% does not do"?

## Tests to run

Python is installed with numpy, zarr, tifffile, scikit-image, pooch,
ome-types, matplotlib, playwright and ngio 1.0.0. The microscopy
`application/node_modules`, `viz_studio/frontend/node_modules`, and the built
`viz_studio/options/harness/dist` exist in the working folder; the Viewer's
`app/page/node_modules` and built `app/page/dist` exist in its working folder.
Copy built pages and `node_modules` into your worktrees rather than
reinstalling. Use `PYTHONPATH=<viewer worktree>` for the Viewer package.
Chromium is at `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`; the
Viewer's `tests/conftest.py` honours `ZMART_CHROMIUM`.

- microscopy: `application/parts`, `application/framework`,
  `application/workflows`, `zmart_storage/tests`, `zmart_live/tests`;
- microscopy `vitest` in `application/`;
- microscopy `viz_studio/tests/test_a_plane_is_sampled_at_its_centre.py` and
  `viz_studio/tests/test_a_foreign_run_can_be_measured.py` (run from
  `viz_studio/`; they need the harness dist and a browser);
- Viewer: `tests/test_session_scratch.py`, `tests/test_server.py`,
  `tests/test_contrast.py`, `tests/test_a_transfer_is_built_into_one_picture.py`,
  `tests/test_the_channel_shapes_a_strict_reader_accepts.py`,
  `tests/test_unresolved_profile_windows.py`, page built,
  `ZMART_REQUIRE_BROWSER=1`;
- the Viewer's full suite if time allows (it takes about 20 minutes with
  browsers); report what you ran either way.

Report exact numbers, and which suites you could not run and why.

## Output

Write the review to
`docs/reviews/2026-09-02-review-of-the-100-percent-viewer-delivery-implementation.md`
in the ZMART-microscopy worktree you made for reading, and return its full
text as your final message. Lead with a verdict: accept, accept with
follow-up, or revise before continuing. Then findings ordered by severity with
file and line, facts separated from inferences, then the answers to the eight
questions, then the tests run with numbers. Write in complete sentences for a
reader who is a microscopist, not a software engineer, as `CLAUDE.md` asks.
