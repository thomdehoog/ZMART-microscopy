# Review prompt for Codex

Paste everything below the line into Codex, pointed at the branch
`agent/live-position-timepoint-publication`.

It is written to invite disagreement rather than approval. A reviewer who comes
back with "looks good" has told us nothing; the useful outcome is a list of
things that are wrong, in an order we can act on.

---

You are reviewing a live-microscopy storage and publication layer in
`thomdehoog/ZMART-microscopy`, branch `agent/live-position-timepoint-publication`.
Be adversarial and concrete. Assume the author is competent and has already
thought about the obvious things; your value is in what they missed.

## What the code is for

A microscope writes positions and timepoints continuously. A viewer
(Neuroglancer) is open the whole time. The requirement is that a viewer never
shows data from a position or timepoint that is only partly written, because a
picture built from half-written data is not a slow picture — it is a wrong one,
and it looks exactly like a right one. Nothing raises.

Read `docs/design/live-position-timepoint-publication-decisions.md` for the
architecture, then `docs/design/live-writer-and-linked-views-plan.md` for the
implementation plan, which records several measurements.

## What to review

New code, all under `zmart_live/`:

- `model.py` — shared frozen records: half-open regions, profiles, grid cells,
  layout revisions, commit events.
- `profiles.py` — chooses chunk, overlap, step, pyramid depth and shard shape per
  acquisition type.
- `manifest.py` — the append-only publication record and its atomic commit.
- `ownership.py` — which tile owns which pixel, visually and for analysis, plus
  the grid contract.
- `tests/` including `check_the_tests_can_fail.py`, which is a mutation check.

## The specific claims I want attacked

Each of these is load-bearing. Try to break them, and prefer running code over
reading it — several of the author's own conclusions were overturned by
execution.

1. **The seam is given to the lower/right neighbour, with every tile trimmed
   identically to one `step`.** The claim is that this makes every placement
   number a multiple of the step and so raises the number of pyramid levels the
   view can point at (measured: 1 → 4 at a 256 chunk on a 2304 frame, 3×3
   mosaic). Verify against `zmart_storage/linked.py`'s real refusals, not against
   the description. Note this deliberately contradicts Decision 7 of the
   architecture record, which says top/left wins — is the contradiction actually
   harmless, as claimed?

2. **`plan_the_writing` never emits a plan the real writer rejects.** The stated
   rule `overlap % chunk == 0` is known to be necessary but not sufficient — a
   2000-pixel frame satisfies it and is still refused. Find a frame, band, or
   acquisition type where the chooser emits something `link_the_tiles` will not
   accept. This is the highest-value bug you can find.

3. **The "nine chunks across, one chunk of overlap" convention.** Claimed to give
   11.1% overlap and four pointed levels at every scale (1152/128, 2304/256,
   4608/512). Is the preference ordering in `choose_the_geometry` right? It
   deliberately ranks staying in the comfortable overlap band above chunk size,
   on the argument that overlap is microscope time and chunk size is only viewer
   latency. Is there a case where that produces a bad plan?

4. **Nothing half-written can be published.** `manifest.py` gates on four
   readiness flags and publishes by renaming a small file over another. Find a
   sequence — crash, concurrent writers, clock change, a reader mid-read — where
   a viewer can observe a revision that is not fully backed by data. The record
   claims a reader sees either the previous complete revision or the next, never
   a mixture.

5. **Every pixel has exactly one owner.** `ownership.py` claims no gaps and no
   duplicates for any rectangular mosaic, including odd overlaps and four-tile
   corners. The test sweeps with a stride of 3 pixels — find a case that stride
   misses, or a shape (single row, single column, L-shaped component, 1×1) that
   breaks the invariant.

6. **Sharding does not constrain chunk choice.** The claim is that an inner chunk
   can be lifted out of a Zarr v3 shard by byte range and decoded identically,
   so views can advertise inner chunks while positions stay sharded. Check the
   index parsing against the Zarr v3 sharding-indexed spec: index location,
   checksum handling, entry order, and the empty-chunk sentinel.

## Also worth your attention

- **Are the tests honest?** Run `python -m zmart_live.tests.check_the_tests_can_fail`.
  It introduces sixteen faults and claims all are caught. Add faults it does not
  cover and see what survives. A surviving fault is a claim the suite is not
  really making.
- **Docstrings are written for biologists, not engineers** (see `CLAUDE.md`).
  Flag anything that is inaccurate, or that is jargon left unexplained. Do not
  flag prose for being long — that is deliberate.
- **What is missing entirely?** The architecture record lists 27 required tests.
  Which are unaddressed, and which of those actually matter?

## How to report

Rank findings by whether they can produce a **silently wrong picture or a wrong
count**, then by everything else. For each: the file and line, a concrete failing
input, and what you would change. Say explicitly which claims you verified by
running something and which you only read. If a claim survives your attack, say
so — that is useful too, but only if you genuinely tried.
