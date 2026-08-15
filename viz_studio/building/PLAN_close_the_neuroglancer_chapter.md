# Closing the Neuroglancer chapter

This plan ends the campaign that began with "get the live viewer to work"
and hands over a foundation the smart-microscopy work can build on. It says
what is done and proven, what single gate remains before this branch is
production ground, what testing is genuinely still missing (less than it
feels), and how the code should be reorganized — afterwards, in a short
chapter of its own, with the test suites built here as the safety net.

## Where the chapter ends

The branch `claude/recent-codex-push-76q08t` carries, each verified by an
instrument that was red before the fix was believed:

- **The black flash is cured at its source.** Whole-source invalidation
  keeps drawing until each replacement arrives; a per-frame gate
  (`test_the_screen_never_goes_black.py`) measured the one-frame flash
  before the fix and holds the cure in place.
- **A stuck refresh stalls only itself.** Per-key refresh flights replaced
  the batch barrier; the liveness gate holds one reply open at the socket
  and requires unrelated refreshes to proceed.
- **A fault is never absence.** Damage answers 503 and heals; a 404 is
  reserved for ground that truly holds nothing. The gateway can no longer
  fold a damaged manifest as an empty run and unbake real files.
- **The storm gate asserts pixel identity**, both directions, on every run
  — the campaign's strongest measurement is now CI's guard, not a debug
  artefact.
- **Landing cost is bounded and survey-size-independent, proven to
  4,096 positions.** The full ladder (2026-08-15, in-container with the
  browser watching, spreads in
  `MEASURED_ladder_to_4096_in_container.json`): landing a new position
  costs 196 ms median at 64 positions and 210 ms at 4,096 — a 7% rise
  across a 64x survey growth. Replacement stays ~330–380 ms. Derive
  grows 38 → 122 ms with pyramid DEPTH (more zoom levels at bigger
  surveys), never with position count. Landing-to-visible stays
  90–225 ms at every rung. Only the one-time costs scale with the
  survey: the initial bake (30.6 s at 4,096) and the first warm-up
  (70.4 s), each paid once per declare. Software-rendering numbers —
  the pessimistic bound; guarded by the landing-cost gates.
- **The cost surface is permanently instrumented.** Every derive reports
  its phases (`last_phase_ms`), the compose phase reports its components
  (read / build / encode), and the bake reports what it built versus
  reused. The next person reads counters; they do not rerun this campaign.
- **A clean checkout builds.** `npm install && npm run build` works from
  scratch; postinstall patches modules only, the build verifies the bundle.
- **The file structure is the contract's.** The conversion landed: position
  images are members of one collection zarr (`data/survey.ome.zarr/`,
  membership by declaration), everything of ours lives under
  `views/live/` (`live.ome.zarr` beside `metadata/` with `signed.json`,
  `locations.json`, `events.jsonl`, `profiles/`), and the test fixtures
  build the real experiment shape — config/ plus acquisitions/ — so any
  drift breaks a gate first. The standing acceptance gate is
  `zmart_live/tests/test_the_files_follow_the_contract.py`, every
  assertion proven able to fail before its green was trusted.
- **One optimization was built, measured, and deliberately reverted**
  (chunk-file paste-over), and the record of why — including the
  correction of its first wrong post-mortem — lives in
  `governed._keep_the_bake_true`'s docstring and
  `test_the_bake_patch_stays_honest.py`. The named successor (patch the
  inherited slab in memory) may not be built without a red gate in
  `bake_compose_read` milliseconds.

## The one remaining gate: the GPU pass

Nothing merges on a software-GL container's word. On the T400:

1. Pull the branch; `npm install && npm run build` from clean.
2. `python -m pytest viz_studio/tests/test_the_screen_never_goes_black.py
   viz_studio/tests/test_one_stuck_refresh_stalls_only_itself.py
   viz_studio/tests/test_a_commit_storm_under_zooming.py
   viz_studio/tests/test_a_survey_grows_in_a_spiral.py -s` — the browser
   gates on real GPU. The spiral gate runs both invalidation modes by
   itself; raise `ZMART_SPIRAL_ACROSS` / `ZMART_SPIRAL_SEED_RINGS` to
   open on an already-large survey and watch late landings stay prompt.
3. Read the pinned Neuroglancer eviction path once (twenty minutes):
   can a resident chunk be freed while a refresh downloads into it? This
   is review finding C4, still open, and only the installed library
   answers it.
4. The simplification is DECIDED (2026-08-15): whole-source
   invalidation is the page's default, and the named ladder is
   deprecated — still reachable via `?refresh=named` /
   `ZMART_STORM_REFRESH=named` purely so the T400 can sanity-check the
   choice before the ladder's code is deleted in the cleanup chapter.
   The deciding evidence, in-container: both modes' delivery machinery
   proved pixel-clean under direct probes; both failed the storm
   identity census identically until the census learned to wait for
   the engine's own fully-loaded word (the difference was
   Neuroglancer's normal coarse-level appetite, not staleness — zoom
   in and back out and the corner is sharp, as at any microscope); and
   with a fair census, whole mode passes the strictest gate the
   campaign owns while carrying none of the ladder's dirty-map
   bookkeeping. On the T400, run the storm file once in each mode; if
   whole holds its rate there too, delete the ladder (dirty maps,
   level routing, `invalidateTheDirtyPieces`) and the
   `claude/whole-source-only-example` branch with it.

Green on 1–3 means merge; the branch becomes the trunk the next work
stands on.

## Testing that is genuinely still missing

- **Channels and time need no ladder.** The ladder answered the question
  it existed for: cost does not follow survey size. Time and channel are
  outer axes — no pyramid crosses them, viewers fetch one moment and a
  few channels — so their semantics can be tested on tiny surveys in
  seconds, the day the served picture grows those axes. Testing them
  before that would exercise nothing real. When t lands, the checklist
  is: dirty footprints carry (t, c); a landing in one moment leaves other
  moments' pieces untouched; the bake's policy for old moments (bake on
  first visit is the recommended posture) has a cold-open test.
- **One t-shaped semantic exists today and deserves its test now**: a
  replacement advances every published moment of a position, so one
  replacement on a long timelapse legitimately dirties O(moments) pieces.
  A manifest-layer test pinning that spike's size belongs beside the
  gateway's suite.
- **The long soak.** No ninety-second gate substitutes for one afternoon
  run: a realistic acquisition with the viewer open for hours, sampling
  warm-versus-reload equality and the frontend's memory accounting. Run
  it once on the T400 before the first real campaign trusts the system
  overnight.
- **Writer-side, before any 10,000-position campaign**: `committed.json`
  is rewritten whole per commit — the one O(positions)-per-commit term
  never measured. An instrument first, as always.

## The cleanup chapter (after the merge)

The code grew where the campaign needed it to grow; now it should be
reshaped once, deliberately, with the suites green before and after every
step. Not too many files, not too few — each file one subject, explained
at its top in plain language.

1. **Split `governed.py` (~1,300 lines) into its two subjects.** The
   snapshot economy (deriving, inheriting, installing) and the bake
   patcher (locks, recipes, pieces, re-halving, stamps) share a file only
   by history. `building/bake.py` for the patcher; `governed.py` keeps
   the run and its snapshots. The accounting travels with its owners.
2. **Split `server.py` (~1,900 lines) by door.** Routing and HTTP
   plumbing; the data doors (live gate, pointed, built, governed); the
   api endpoints. Three files, each readable in one sitting.
3. **Extract the browser-test scale harness.** The storm test's fixture
   recipes, announcement helpers, dirty arithmetic and pixel oracles are
   imported by four test files from a 1,400-line test module; they belong
   in `tests/scale_harness.py` with the campaign-only diagnostic blocks
   (`ZMART_STORM_HEAL`, `ZMART_STORM_DEBUG`) moved to an opt-in stress
   script under `building/`.
4. **File the campaign records.** The `building/` folder mixes living
   tools with completed investigations. A `building/history/` folder for
   HANDOVER/PROMPT/MEASURED documents of finished campaigns, each with a
   one-line verdict at the top, keeps the front door clear while losing
   nothing.
5. **The OME-Zarr writer stays where it lives** (`zmart_live`,
   `zmart_storage`) — it is production code with its own suite, not test
   scaffolding; the fixtures merely drive it fast. No move needed.
6. **Re-document the record as consumer-neutral.** `zmart_live` grew up
   serving the viewer and reads that way -- the name, and the link-map
   and view-route artifacts the publisher bundles into each publication.
   Architecturally the dependency points one way (the viewer imports the
   record's package, never the reverse), and the smart-microscopy loop
   will be the record's second consumer, reading truth through the same
   gateway. The docs should say so plainly: the manifest and gateway are
   the run's publication record and its one reading API for EVERY
   consumer, and the view-flavoured riders in the record folder are one
   consumer's convenience, ignorable by the rest.
7. **Comment altitude pass, last.** The campaign wrote incident-flavoured
   comments where invariant-flavoured ones should stand. One sweep,
   guided by the rule already in CLAUDE.md: say why, plainly, for a
   reader at the microscope; history belongs in `building/history/`.

Each step is a small commit with the full suite green; none changes
behaviour. Budget: a day of work, none of it urgent, all of it cheaper
now than after the next feature grows on top.

## What "moving on" means

The instruments stay armed — they are the regression floor the next
chapter stands on, not campaign debris. The phase and cost ledgers are
how future slowness gets a name in minutes instead of an evening. And the
discipline that closed this chapter — no fix without an instrument, red
for the right reason, wall clock over proxy, revert on measurement, and
correct the record when the record is wrong — is the part most worth
carrying into the smart-microscopy work, because it is the part that made
this chapter end instead of continuing forever.
