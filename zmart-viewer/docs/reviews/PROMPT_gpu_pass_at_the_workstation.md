# Prompt: the GPU pass at the workstation

Paste this into a fresh Claude session on the workstation (T400), with this
repository checked out. It carries everything the session needs to know.

---

You are at the microscope workstation with a real GPU. The branch
`claude/recent-codex-push-76q08t` closes the Neuroglancer chapter: the file
structure follows `zmart-viewer/app/picture/CONTRACT_the_files_the_viewer_needs.md`,
every suite is green in-container, and every gate was proven able to fail
before its green was trusted. Your job is the one thing a container cannot
do: certify the browser gates on real hardware, and bring back numbers.

The full background lives in `zmart-viewer/app/picture/PLAN_close_the_neuroglancer_chapter.md`
(what is done, what this pass decides) and
`MEASURED_ladder_to_4096_in_container.json` (the software-rendering
baseline: landing ~200 ms median flat to 4,096 positions, landing-to-visible
under 225 ms, storm held at 20 commits/s). The GPU should beat all of it.

Work through these in order, and stop to report rather than improvise if a
step goes red:

1. **Clean build.** `cd zmart-viewer/app/page && npm install && npm run build`.
   The build must end with the bundle-verification line — that proves the
   patched engine (the no-black refresh pump) is in the bundle.

2. **The browser gates, on the real GPU.** From `zmart-viewer/`:

       ZMART_REAL_GPU=1 ZMART_REQUIRE_BROWSER=1 python -m pytest \
         tests/test_the_screen_never_goes_black.py \
         tests/test_one_stuck_refresh_stalls_only_itself.py \
         tests/test_a_commit_storm_under_zooming.py \
         tests/test_a_survey_grows_in_a_spiral.py -s

   `ZMART_REAL_GPU=1` is essential: without it the fixtures force software
   rendering even on this machine, and the pass would certify SwiftShader.
   `ZMART_REQUIRE_BROWSER=1` turns a missing browser into a failure instead
   of a silent skip. Note the storm's printed drawing rate and the spiral's
   growth story; they are the numbers to compare against the container's.

3. **The retirement sanity check.** Whole-source invalidation is the page's
   default; the named ladder is deprecated and will be deleted in the
   cleanup chapter. Confirm the choice holds on hardware:

       ZMART_REAL_GPU=1 ZMART_STORM_REFRESH=named python -m pytest \
         "tests/test_a_commit_storm_under_zooming.py::test_every_zoom_shows_the_survey_after_a_storm_of_landings" -s

   Both modes green on GPU means the ladder's deletion is safe.

4. **Scale the spiral, optionally.** `ZMART_SPIRAL_ACROSS=24
   ZMART_SPIRAL_SEED_RINGS=8` opens the viewer on an already-large survey
   and confirms late landings still appear promptly on real hardware.

5. **Review finding C4 — the one open review item.** Twenty minutes reading
   the pinned Neuroglancer eviction path
   (`zmart-viewer/app/page/node_modules/neuroglancer/lib/chunk_manager/backend.js`,
   the queue-promotion and eviction routines): can a resident chunk be
   freed while a refresh is downloading into it? The per-key refresh
   flights (`frontend/scripts/patch_neuroglancer.mjs`, marker
   `zmartRefreshOneKey`) assume not. Write down what you find — a sentence
   in the PLAN is enough.

6. **The soak.** A realistic acquisition with the viewer open for a few
   hours: watch for warm-versus-reload divergence (zoom out, then F5 — the
   two pictures should match once both are fully loaded) and for browser
   memory growth. This is the one test no ninety-second gate substitutes
   for.

If a gate goes red: do not debug at the bench. Rerun the failing test with
`ZMART_STORM_DEBUG=/some/folder` (the storm and spiral gates save
screenshots, invalidation ledgers, and network logs there), commit nothing,
and report the folder's contents. Every red this campaign has ever produced
ended in a named mechanism; a GPU red will too, but only with its evidence
preserved.

Green on steps 1–3 means the branch is merge-ready by the plan's own
standard. Record the numbers (storm drawing rate, spiral timings, anything
from a ladder rung if you run one) in the PLAN beside the container
baselines, commit, and push.
