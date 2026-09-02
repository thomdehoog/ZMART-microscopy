# Review brief: the detailed plan for the rendering engine and the register, for Codex

Date: 2026-09-02

Please review; do not implement. The design record
(`docs/design/own-rendering-engine-and-position-register.md`, fourth
revision) has been through three rounds of review and is handed over on the
terms of its "Handing over" section. This brief is about the next document:
a detailed plan that expands the record's six steps into work items, each
tied to the files that exist today and to gaps found by reading both
repositories, and that collects nine decisions for the owner up front. The
plan is a proposal for discussion. The owner will decide the nine decisions
after reading your review, so the most useful thing you can do is test the
plan's claims about the code and its recommendations against what you find.

## What to read

ZMART-microscopy, branch `claude/viewer-delivery-to-100` at `c287e8f3` or
later on that branch. Use a fresh clone or worktree; do not modify the
branch. The ZMART Viewer is on its own `claude/viewer-delivery-to-100` at
`9b67bf8`. Neuroglancer 2.41.2 is pinned in the microscopy repository.

1. `docs/design/own-rendering-engine-detailed-plan.md`, whole. This is the
   document under review.
2. `docs/design/own-rendering-engine-and-position-register.md`, fourth
   revision, in particular "Gates", "Order of work" and "Handing over", so
   you can check that the plan carries every item of the record's step 1 and
   step 2 and adds nothing the record did not authorise.
3. The code the plan makes claims about. The plan names files; the claims
   most worth checking are listed under question 1.
4. `docs/design/lazy-jpeg-pyramids-for-the-viewer.md` around lines 400 to
   465, the earlier design's ten-step trace, its definitions of cold, warm
   and "useful picture", and its memory gate, which the plan's items 1.4 and
   1.5 are meant to implement.
5. `CLAUDE.md`.

## Questions, lead with whichever you can answer with evidence

1. **Are the plan's claims about the code true?** Check at least these, and
   say for each: true, false, or true with a qualification.
   - The rig's external-run door opens one store through the rig's own file
     server, not a run through the Viewer
     (`viz_studio/options/measure/real_run.py`, `run.py`).
   - "Settled" in the driver is two byte-identical photographs 0.2 s apart
     (`viz_studio/options/measure/drive.py`), and the adapter's counters hold
     paints and let-goes but no needed-versus-available
     (`viz_studio/options/neuroglancer-under/viewer.js`).
   - No memory reader exists in the rig; the ten-step trace exists only as a
     list; no protocol document exists.
   - The Viewer's composer keeps timers and a read counter at the storage
     boundary that no route serves, and the server keeps no per-route counts
     (`zmart_viewer/compose.py`, `zmart_viewer/server.py`).
   - The Viewer's record has one writer, the publisher in
     `zmart_viewer/record/coordinator.py`, whose only live caller is the
     replay route; the bridge writes position stores through the storage
     library with no sharding and every height at nought
     (`application/parts/storage/zarr_positions.py`).
   - `zmart_viewer/record/coarse.py` is imported by nothing.
   - The marker's reader checks the schema name and reads named fields, so
     an extra field on the marker passes today
     (`zmart_viewer/record/manifest.py`).
   - The Leica adapter reports the frame size before capture; neither
     instrument records a wall-clock time at a landing.
   - The five-axis placement bug is pinned by a strict expected-failure test
     in `viz_studio/tests/test_a_foreign_run_can_be_measured.py`.
2. **Are the nine decisions the right nine, and are the recommendations
   sound?** For each: is it really the owner's to decide, or is it settled
   by the record already; is the recommendation right; and is there a
   consequence the plan does not name. Decision 3, the bridge as a client of
   the Viewer's publisher, is the one with the largest consequences; say
   what it costs that the plan leaves out, including the profile sealed
   before the first capture, the folder shape, the viewer service's open and
   relink path, and what happens to today's `zmart-acquisition.json` and the
   channel attributes the position writer copies.
3. **Does step 1 deliver phase 0 as the record and its three promises
   require?** Check that the harness work is exactly what the record
   authorised by name, that every phase-0 gate in the record's "Gates" has
   an item producing its instrument, and that nothing in step 1 builds the
   engine or the data layer early. Say whether item 1.1's "through the
   Viewer" mode changes what phase 0 measures compared with what the record
   describes, and whether that is right.
4. **Is each "done when" a test that can fail?** For every work item, say
   whether its completion condition can be checked by a test or a
   measurement as written, or whether it is a description that would pass by
   assertion.
5. **Is the sequence right?** Check the dependency table: anything that
   depends on something the table omits, anything that could start earlier,
   and whether the plan's claim that items 1.2, 1.3, 1.5 and 1.7 can start
   now holds.
6. **Are the sizes believable?** The plan sizes items as small, medium and
   large for one person who knows both repositories. Name any you would
   double or halve, with the reason.
7. **What does step 2 leave out?** The record's "Handing over" lists what
   the data-layer designer still decides. Check that the plan's step 2
   covers every item of the record's step 2 and every "Handing over" item,
   and name anything the record settled that the plan reopens, or anything
   the plan settles that the record left to the data-layer record.
8. **What is still wrong?** Anything false; any hypothesis stated as fact;
   anything a biologist would not follow; anything in the risks section
   that is not a risk, and any risk the plan does not name.

## Output

A verdict on the plan as a basis for discussion (usable as is, usable with
changes, or rework), then findings ordered by consequence, facts separated
from inferences, then answers to the eight questions, then one paragraph
on which decisions you would take differently from the recommendations and
why. Name the commit you read. Write in complete sentences for a reader who
is a microscopist, as `CLAUDE.md` asks. Put the review at
`docs/reviews/2026-09-02-review-of-the-rendering-engine-plan-by-codex.md`
on a branch of your own, and end with a short paste-back section, or, if
nothing remains, say so in one line.
