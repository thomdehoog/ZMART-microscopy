# Review brief: the third revision of the rendering-engine design, for Codex

Date: 2026-09-02

Please review; do not implement. This is the third round. Two reviewers
(you and an internal one) reviewed twice; every finding from all four
reviews was checked against the code and folded into the record, and the
record's "Decisions on the four reviews" section says what was taken and,
with reasons, what was not. Both second-round verdicts were "accept with
changes"; the changes are in. This round decides whether the record can be
handed to the data-layer design as it stands.

## What to read

ZMART-microscopy, branch `claude/viewer-delivery-to-100` at `d80717b2` or
later on that branch. Use a fresh clone or worktree; do not modify the
branch. The ZMART Viewer is on its own `claude/viewer-delivery-to-100` at
`9b67bf8`. Neuroglancer 2.41.2 is pinned in the microscopy repository.

1. `docs/design/own-rendering-engine-and-position-register.md` — the third
   revision, whole.
2. Your second review
   (`docs/reviews/2026-09-02-second-review-of-the-rendering-engine-design-by-codex.md`)
   and the internal second review
   (`docs/reviews/2026-09-02-second-review-of-the-rendering-engine-design.md`),
   so you can check that each finding and each paste-back item was carried
   into the record as meant.
3. `docs/design/prior-art-larger-than-memory-3d-rendering.md`, whose body
   was rewritten this round, not only its preface.
4. The code behind any "exists" claim you doubt; the record lists what it
   claims exists, what it calls new, and what it now labels a hypothesis.
5. `CLAUDE.md`.

## Questions — lead with whichever you can answer with evidence

1. **Were the second-round findings carried faithfully this time?** For
   each of your six findings and your paste-back, and for the internal
   review's sixteen findings and its paste-back, say: carried whole, carried
   weaker, or not carried. Softening is the thing to catch, as before.
2. **Is the record now ready to hand to the data-layer design?** That
   record will take the register (three documents, the extension, the
   collection index), the coordinate frame with half-open plane intervals,
   coverage, dirty boxes, the cost model and tile sizes, sharding of every
   level with more than one chunk, the single-file-levels decision, the
   terminal state, the re-scan rule and the (channel, kind) window key as
   settled inputs. Name anything among those an implementer would still have
   to decide, and anything the data-layer designer would find contradictory
   between sections.
3. **Are the three phase-0 promises enough, and are they kept by the rest of
   the record?** Check that the order of work, the gates and the engine
   section do not quietly violate them: nothing built before phase 0 except
   the named harness work; neuroglancer stays the operator's engine until the
   gates pass; the brief shrinks if the data layer alone passes.
4. **Are the three tile identities right?** Raw chunk, assembled slice tile
   with placement and a content generation, stored projection. Say whether
   the content generation can actually be advanced by a dirty-box protocol
   without a global scan, whether placement belongs in the key, and whether
   anything is still missing that would invalidate cached or stored
   derivatives if added later.
5. **Does the scheduler section now match neuroglancer's behaviour where it
   says it does**, and does it say anything neuroglancer's pinned source
   contradicts? Check the tier and admission rule, abort on pressure, the
   decode pool, the upload slice, the counters that define "settled", and
   the three kinds of nothing.
6. **Are the gates measurable as written**, each of them, with the harness
   after step 1's authorised work? Name any that still cannot be won,
   cannot be measured, or let a failure hide.
7. **Are the numbers and their cases right?** The two plate cases, the
   200,000-file figure after sharding and dropping single-file levels, the
   kept-levels cost, and the warm-read estimate for the 2048 plate.
8. **What is still wrong?** Anything false; any hypothesis stated as fact
   or fact stated as hypothesis; anything a biologist would not follow
   (the glossary is now long; say whether it works); and anything in "Not
   taken" whose reasoning does not hold.

## Output

A verdict — accept, accept with changes, or rethink — then findings ordered
by consequence, facts separated from inferences, then answers to the eight
questions, then one paragraph on whether the record is ready for the
data-layer design. Name the commit you read. Write in complete sentences for
a reader who is a microscopist, as `CLAUDE.md` asks. Put the review at
`docs/reviews/2026-09-02-third-review-of-the-rendering-engine-design-by-codex.md`
on a branch of your own, and end with a short paste-back section, or, if
nothing remains, say so in one line.
