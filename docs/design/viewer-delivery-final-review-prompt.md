# Review brief: the finished viewer delivery migration, for an independent reviewer

Date: 2026-09-02

Please review; do not implement. This is the third review of this work and
the first by someone who did not take part in it: the 80% and 100% reviews
were done by the same family of assistant that wrote the code. Your job is to
find what that shared blind spot missed.

## Revisions

Both repositories, branch `claude/viewer-delivery-to-100`:

- ZMART-microscopy at `4d9056f7`. Base: your own `b79fb46e`. Commits since,
  oldest first: `ae40fb58` (M2, I1), `960d15d9` (Z1, H1), `543ca9f0` (M3),
  `10cdafb8` (answers to the 80% review), `4b0795b6` (answers to the 100%
  review), plus documentation commits.
- ZMART Viewer at `7a38079`. Base: your own `2b4338e`. Commits since:
  `02cf88d` (capabilities, declared-vs-measured), `f75fa63` (S1),
  `8880c7d` and `7a38079` (answers to the two reviews).

Use fresh clones or worktrees. Do not modify either branch.

## Read first, in this order

1. `docs/design/viewer-delivery-implementation-plan-100-percent.md` — what
   is claimed, what is admitted open, and the test numbers at the final
   commits.
2. `docs/reviews/2026-09-02-review-of-the-100-percent-viewer-delivery-implementation.md`
   and `docs/reviews/2026-09-02-review-of-the-80-percent-viewer-delivery-implementation.md`
   — the two internal reviews. Every finding in them is claimed fixed in
   `4b0795b6` / `7a38079`, except the ones the 100% document lists as open.
3. `docs/design/viewer-delivery-implementation-plan-50-percent.md` — the
   plan the six packages come from, so you can judge each against what was
   asked rather than against what was delivered.
4. `docs/design/viewer-delivery-implementation-plan-80-percent.md` — the
   nine decisions.
5. `CLAUDE.md` — the writing rule applies to code comments and docstrings in
   the diff too.

## What is already known to be open — do not spend your time re-finding it

- The rig's `neuroglancer-under` opens the bridge's OME-Zarr 0.5 positions
  and fetches their pieces but places the view beside them; a strict `xfail`
  records it.
- `neuroglancer-under` opens stacks on plane 0, not the middle-plane rule;
  strict `xfail`, and a documented reason not to change it here.
- The Windows lock branch (`msvcrt.locking`) has never run on Windows.
- The M3 gate evidence on the microscope PC has not been produced: the
  handshake against a real `9ff10b0`, a photographed bridge-driven run, the
  cold-open numbers.
- `watching-the-run.js`'s `toldAbout` fix has no test (nothing in vitest
  reaches that file).
- Five pre-existing failures in `viz_studio/tests/test_the_options_hold_together.py`.
- The Viewer's `test_a_commit_storm_under_zooming.py` hangs under software
  rendering and was deselected from the full run.

## Questions — lead with whichever you can answer with evidence

1. **Is there any path, in either repository, that still gives a channel a
   display window the acquisition did not decide?** Search wider than the two
   reviews did: `viz_studio/backend`, `viz_studio/building`, `zmart_analysis`,
   the notebooks, the mesoSPIM driver, anything that constructs an `omero`
   block or a `Channel(...)` with a window. The migration's whole claim rests
   on "no".
2. **Old writer, new Viewer, real data.** Take a run written before
   `b79fb46e` — every position carrying its own measured window — and open it
   through the new Viewer's composed path. Does it draw at the same brightness
   it drew before? The legacy consensus path was tested on fixtures; it has
   not been run on a real pre-migration run.
3. **The handshake, with the real 0.2.0.** Install Viewer `9ff10b0` beside
   the new microscopy branch and connect. Is the run refused with the sentence
   on the canvas, and does the scan still write positions? Then install
   `7a38079` and confirm it is accepted. This is the M3 gate item nobody has
   done; you are the first with a machine to do it on.
4. **The recording preset as the source of channel descriptions.**
   `application/parts/microscope/settings.js` parses labels out of the
   preset's display string (`split("·")`, a `\d+ nm` match). Take the real
   Leica presets on the microscope PC and check what keys and labels come out.
   Is a channel with no wavelength in its name given a key that is stable
   across runs? Two channels with the same wavelength?
5. **Concurrency you can reach.** Two scans of the same acquisition type
   started in quick succession; a scan started while the previous run's
   `zmart-acquisition.json` still exists with a different channel set; two
   Viewers started within a second of each other on one machine (the scratch
   sweep). The reviews probed these with wrappers; try them for real.
6. **What a biologist sees.** Open the operator page against the mock, run
   the overview scan, and read every sentence the panel and canvas show
   during the first thirty seconds: "waiting for measurable pixels",
   "brightness measured from pixels acquired so far", the upgrade sentence
   if you provoke it. Are they true at the moment they are shown? Are any
   shown when they should not be?
7. **The diff as prose.** Pick five docstrings or comments added in these
   commits at random and read them as the microscopist `CLAUDE.md` describes.
   Is anything jargon without a gloss, or a sentence that only restates the
   code?
8. **Anything the two internal reviews agreed on that you think is wrong.**
   Both accepted "omit the whole `omero` block for an unresolved
   acquisition", "capabilities rather than versions", "decimation stays",
   and "no `uint8` before measurement". Challenge whichever you can.

## Tests

Run what you can; report exact numbers and what you could not run. What was
run at the final commits is tabulated at the end of the 100% document. The
environment notes that cost the internal reviewers time:

- microscopy Python needs `numpy`, `zarr>=3,<4`, `tifffile`, `scikit-image`,
  `pooch`, `ome-types`, `matplotlib`; the Viewer as `pip install -e . --no-deps`;
  `pytest-timeout` for the Viewer's full suite;
- `npm --prefix application install` for vitest; `npm --prefix app/page
  install && npm --prefix app/page run build` for the Viewer's browser tests,
  then `ZMART_REQUIRE_BROWSER=1` so a skipped browser fails rather than
  passes;
- the `viz_studio` tests need `npm --prefix viz_studio/frontend install` and
  `npm --prefix viz_studio/options/harness run build`, and run from
  `viz_studio/`;
- `ngio` for the strict-reader test (`pip install ngio`, possibly with
  `--ignore-installed packaging`).

## Output

A verdict — accept, accept with follow-up, or revise before continuing —
then findings ordered by consequence with file and line, facts separated from
inferences, then answers to the eight questions, then tests run with numbers.
Name the commits you inspected. Write in complete sentences for a reader who
is a microscopist, as `CLAUDE.md` asks. Put the review at
`docs/reviews/2026-09-02-review-of-the-viewer-delivery-migration-by-codex.md`
on a branch of your own, and end with a short paste-back section of
instructions for whoever fixes what you find.
