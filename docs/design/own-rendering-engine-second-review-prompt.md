# Review brief: the revised rendering-engine design, for Codex

Date: 2026-09-02

Please review; do not implement. This is the second round. Your first review
(`docs/reviews/2026-09-02-review-of-the-rendering-engine-design-by-codex.md`,
verdict "rethink") and an internal one
(`docs/reviews/2026-09-02-review-of-the-rendering-engine-design.md`, verdict
"accept with changes") were both folded into the record, finding by finding.
Every factual claim in both was re-checked against the code before being
taken, and the record now has a section, "Decisions on the two reviews",
that says what was taken and what was not, with reasons. This round is
about whether the revised record is right, complete and honest, and
whether the decisions not taken were argued fairly.

## What to read

ZMART-microscopy, branch `claude/viewer-delivery-to-100` at `3bbf9c0b`. Use a
fresh clone or worktree; do not modify the branch. The ZMART Viewer is on
its own `claude/viewer-delivery-to-100` at `9b67bf8`.

1. `docs/design/own-rendering-engine-and-position-register.md` — the revised
   record. Read the section "The one decision that was contested" first, then
   "Decisions on the two reviews", then the rest.
2. Your own review and the internal one, so you can check that each finding
   was carried into the record as it was meant, not softened on the way.
3. `docs/design/prior-art-larger-than-memory-3d-rendering.md`, which now
   opens with a correction taken from your finding 8.
4. `docs/design/lazy-jpeg-pyramids-for-the-viewer.md` (phases 0 and 1) and
   `docs/design/viewer-delivery-implementation-plan-100-percent.md` ("What
   100% does not do"), which the contested decision refers to.
5. The code behind any "exists" claim you doubt. The record lists what it
   claims exists under "Facts checked against the code, and what is new".
6. `CLAUDE.md` — the writing rule applies to the record.

## The decision you should argue with, openly

The record keeps the engine as a settled decision and refuses your "rethink"
on one point: it takes the order (phase 0 first, with the breakdown; the data
layer built and measured under the existing engine before the new one is
written) and refuses the condition (that the engine be authorised only if a
named metric fails). Its reason: the engine is the project owner's decision
for reasons beyond speed, listed in that section, and the record supersedes
the earlier "only if" clause explicitly rather than contradicting it in
silence.

Say whether that reasoning is sound as written. If you still think the
condition should stand, say what the owner loses by deciding now that a
measurement could have told them, in concrete terms; if you accept it, say
what the record must still promise so that phase 0 keeps its teeth.

## Questions — lead with whichever you can answer with evidence

1. **Were your findings carried faithfully?** For each of your eight
   findings and your paste-back list, say whether the record now does what
   you asked, does something weaker, or does something you did not ask for.
   Be specific about softening: a finding "taken" in the decisions section
   but only half-present in the body is the thing to catch.
2. **Is the geometry now defined tightly enough to implement without
   choosing its meaning in code?** The coordinate frame, the z datum, raw
   plane heights kept, aligned placement's one meaning, edge-based names, the
   side view's own slider and projection axis. Name anything an implementer
   would still have to decide.
3. **Is the register extension complete and consistent with the Viewer's
   record as it is?** Check the versioned extension list against
   `zmart_viewer/record/model.py`, `coordinator.py`, `manifest.py` and
   `gateway.py`: does anything proposed conflict with the sealed profile,
   the immutable layout, the append-only events or the signed truth file?
   Is the "one profile per frame shape" rule enough for a target collection
   whose fields differ in size, or does it need more?
4. **Is the end-to-end identity right and minimal?** Collection, source and
   generation, time, stable channel key, level, orientation, slice or
   projection with kind and range, row, column, revision, plus data kind and
   type, window with state, coverage mask. Is anything missing that would
   invalidate cache keys or stored derivatives if added later? Is anything
   there that does not belong in a tile's identity?
5. **Does the scheduler specification now cover what neuroglancer does?**
   Compare the engine section's list against `src/chunk_manager` and
   `src/async_computation` in the pinned neuroglancer 2.41.2, and name what is
   still missing.
6. **Are the numbers and their assumptions stated so that "ten thousand
   positions" means one thing?** Check the data-layer section's two cases,
   the tile-size statement, the kept-levels cost, and the sharding
   prerequisite against `zarr_positions.py`, `zmart_storage/canvas.py` and
   `zmart_viewer/compose.py`. Say whether the sharding design must cover
   every level, or whether some levels can be dropped instead, and what that
   decision depends on.
7. **Are the gates measurable as written, and in the right order?** Phase 0
   with its breakdown, the five data-layer gates, the seven engine gates.
   Name any gate that cannot be won, cannot be measured with the existing
   harness, or lets a failure hide.
8. **What is still wrong?** Anything false, anything stated as a fact that
   is an inference, anything a biologist reading the record would not
   understand, and anything in the "Not taken" section whose reasoning does
   not hold.

## Output

A verdict — accept, accept with changes, or rethink — then findings ordered
by consequence, facts separated from inferences, then answers to the eight
questions, then your position on the contested decision in one paragraph.
Name the commit you read. Write in complete sentences for a reader who is a
microscopist, as `CLAUDE.md` asks. Put the review at
`docs/reviews/2026-09-02-second-review-of-the-rendering-engine-design-by-codex.md`
on a branch of your own, and end with a short paste-back section of the
changes the record should take before the data-layer design record is
written.
