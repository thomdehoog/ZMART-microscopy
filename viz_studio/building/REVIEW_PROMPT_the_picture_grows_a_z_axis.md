# Review prompt: the picture grows a z-axis

You are asked to review a **plan**, before anything is built. Nothing in it is
implemented; your findings are cheapest right now. Please attack the design,
its premises, and its test plan — in that order of value — and report findings
numbered, most severe first, each saying plainly whether it is something you
can show (with the file and line, or the arithmetic) or something you suspect.
A finding that names a failure the plan would ship is worth ten wording notes.

## What to read, in order

All on branch `claude/thy1-linked-spiral` (based on the chapter-closing branch
`claude/recent-codex-push-76q08t`), in `viz_studio/`:

1. `building/PLAN_the_picture_grows_a_z_axis.md` — the plan under review.
2. `building/TESTPLAN_the_picture_grows_a_z_axis.md` — how it will be held to
   account.
3. `tests/test_a_built_picture_grows_while_watched.py` — the working browser
   gate the test plan's stage 3 grows from, including the evening-long fault
   its docstring records.
4. `building/PLAN_close_the_neuroglancer_chapter.md` — the state of the flat
   picture this plan stands on, including the workstation's measured numbers.
5. The tail of `FAULTS.md` — an unreproduced observation (the volume view
   brighter warm than after a reload) whose deciding instrument is part of
   this plan's test matrix.

Background if you want it: `DECISION_finish_the_migration_to_one_live_path.md`
(why depth goes on the governed door), `measure_declared_room.py`'s module
docstring (the tall-thin-coarsest-copy trap), and `composer.py` around
`PINNED_SHARE` and `slab_depth` (the machinery the plan extends).

## The claims to attack

1. **The declared room.** The picture's full (t, c, z, y, x) extent is
   declared from the profile before the first landing and never moves. Find
   the acquisition this breaks — a run whose depth or duration genuinely is
   not known at declare time — and say what the plan should do about it.
2. **The convergence premise.** Whole-source invalidation survives because
   refetching what is on screen converges between landings. In depth, "what
   is on screen" includes a volume view holding chunks at several levels at
   once. Estimate the refetch bill for a held volume view at realistic
   survey sizes and say whether the flat picture's landing-to-visible bound
   (90–225 ms) can plausibly survive it, or where it breaks.
3. **The z-halving decision.** The plan holds it open, both ways behind a
   switch, decided by the ladder. Is the experiment as described actually
   decisive? Name what it does not measure — interop (can napari and Fiji
   read a halved-z pyramid the writer produces?), the rounding rule for odd
   depths (291 halves to 146 in the Thy1 set — someone chose ceiling; the
   writer must choose and pin one), and anything else you see.
4. **The bake dial.** The plan demotes the bake to a dial: nothing +
   RAM-pinned coarse levels / coarsest-only / pinned-share, never full
   resolution. Attack the ends: is "bake nothing" safe on an operator's
   machine with far less RAM than the 31 GB workstation the pin budget was
   sized on? Is "never bake L0" safe for every serving path — including a
   finished run whose picture outlives its positions' availability?
5. **The dirty arithmetic.** A landing dirties slabs × rows × columns of
   pieces; a whole-position replacement on a timelapse dirties O(moments)
   more. Are the announcement payloads, the bake's patch batches, and the
   manifest bookkeeping all bounded and honest at those sizes, or does one
   of them hide an O(survey) term the flat picture never exposed?
6. **The test plan's blind spots.** Stage 3 tests held views and revisited
   planes. What growth-visibility fault would pass every gate listed and
   still reach an operator? (The evening behind the browser gate found that
   a chain can be broken by one wrong word while every part tests green in
   isolation — look for the next such seam, e.g. between announce payloads
   and dirty-piece routing, or between the 2-D and volume delivery paths.)
7. **The brightness observation.** FAULTS records the volume view sitting
   brighter warm than after a reload, unreproduced. Are the two candidate
   mechanisms (twin double-draw under additive compositing; a stale volume
   display window) the right suspects, and is the proposed instrument — the
   held-volume gate comparing mean brightness warm against fresh — actually
   able to tell them apart, or only to detect that one of them happened?

## What not to re-litigate

These are decided, with measurements behind them; findings against them need
extraordinary evidence, not preference:

- Whole-source invalidation as the page's default (certified on the T400,
  2026-08-17, storm at 20.00/s, census clean at every band).
- The governed door as the one live path (the migration decision; the
  transfer door stays for finished folders from other microscopes).
- Correctness gates run bake-free on synthetic stamped tiles; real Thy1 is a
  one-time development rung and joins no suite.
- The room is declared, not grown (two measured shape-change failures on
  2026-08-17 stand behind this).

## Form of the answer

Numbered findings, most severe first. For each: the claim it attacks, what
you can show versus what you suspect, and — where you can — the cheapest
instrument that would settle it. Wording and structure notes last, in one
short list, or not at all.
