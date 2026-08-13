# Decision: finish the migration to one live path

> Written 2026-08-13, at the end of the day the per-commit bake was built,
> review-hardened, and benchmarked. The operator asked whether the system
> is "fundamentally wrong"; the answer found is narrower and more useful:
> it is straddling a migration it already decided, and the straddle is
> both the remaining publish cost and most of the felt complexity.

## The operator's scenario, stated as the contract

Positions arrive as their own OME-Zarrs. Positions are withdrawn.
Timepoints are appended to a position's zarr. Positions never move. The
derived picture changes only in the small bit a change touches — patched
with data, or emptied. Nothing else happens to a run.

## What exists, and why it costs

A publish today maintains TWO products and one diary:

1. **The served picture** — the governed, baked, per-piece-patched
   pyramid. Proven on screen at 1,024 / 6,400 / 12,769 with zero
   transients; cost per change is the change.
2. **The zero-copy linked view** (`views/overview.ome.zarr` + the link
   map) — plain files any external tool could open mid-run without our
   server. Keeping its map true per publish is the write-gate routing:
   the last O(survey) pass, ~13 s of the remaining ~16 s warm publish at
   12,769.
3. **The manifest** — append-only history, folded incrementally. Cheap.
   Not a cost problem; listed for completeness.

The decision of 2026-08-12 — building serves the live view, pointing
retires to single-store serving — was made but never finished: the
viewer's live registry still hands the frontend the LINKED view as the
live source, which is the only thing keeping product 2 on the hot path.

## The decision proposed

**Finish the migration.**

- The live registry serves the governed baked picture as the live
  source. The per-piece announce/refresh flow already works against it —
  this is consolidation, not construction.
- The linked view's map moves to END-OF-RUN: written once when the run
  finishes, exactly as a transfer is declared. The zero-copy product
  survives in full for every after-the-run consumer.
- Q6 (per-change route validation) is NOT built: it optimizes the pass
  this decision removes from the hot path.
- The unchanged layout stops being re-recorded per publish (free,
  independent of this decision).

A publish then costs: write the zarr, patch the bake, one manifest
commit — measured pieces suggest 3–4 s at 12,769, flat with scale, and
the system is describable in one sentence.

## What each dropped hot-path piece currently guarantees, and who inherits it

- *"External tools can open the run as plain files mid-run"* — the ONLY
  guarantee genuinely given up during a run. Inherited at run end by the
  end-of-run declare. **GATE: the operator confirms with the lab that no
  workflow or script opens `views/overview.ome.zarr` on a still-running
  experiment.** Everything inside this repository will be migrated; only
  outside consumers cannot be grepped.
- *"The link map is validated before it is trusted"* — unchanged; it is
  validated when it is written, at run end, by the same gate.
- *Fail-closed serving, later-wins overlap, withdrawal, rollback* — all
  live in the governed picture path and its manifest gate; none touch
  the linked view.

## Explicitly kept

The manifest as append-only history (audit + recovery + the fold);
the bake with its stamp identity, patch locking and atomic replaces;
per-piece invalidation; the declared world frame. The current-state-file
idea (serve from a swapped snapshot instead of the fold) is recorded as
elegance, not speed — the fold is already incremental — and is not part
of this decision.

## Also on the table, sequenced after

- Pixel-write workers: once the migration lands, writing the pixels IS
  the publish; parallelize then, not before.
- The t axis through the served picture: the operator's third scenario
  (timepoints appended per position). Feature work, riding on the same
  governed path this decision consolidates; the manifest already
  publishes per-moment.
- `test_manifest_refresh_browser.py` still exercises seamless-era names
  and should be ported or retired WITH the registry change, since it
  pins the very wiring this decision replaces.

## Landed: the second slice (2026-08-13, later the same day)

The link map now moves to end-of-run, exactly as decided above, and the
route gate at publish time checks only the position being published.
What changed, and where:

- A run can be opened with ``linked_view="at_run_end"``
  (`zmart_live.coordinator.LivePublisher`). Mid-run, a publish then owes
  the shared records nothing beyond the arrangement — no link map, no
  view description — and the commit records the deferral honestly in a
  new ``linked_view_deferred`` field, so ``ready`` never claims a check
  that did not run. Every check about the position's OWN bytes runs
  exactly as before; the mutation campaign that proves the tests notice
  a softened gate still passes.
- ``finish_the_run()`` writes the linked plain-file view once, when the
  run finishes: the map over every committed position, the view
  description, the arrangement. Each write carries the same gates it
  always had, so the map is validated at the moment it is written — the
  after-the-run consumers lose nothing.
- The arrangement read-back inside every publish now remembers the file
  it just verified, by the same identity rule the shard tables use, so
  an unchanged layout costs a stat instead of a survey-sized parse. A
  swapped or tampered file still drops back to the full read, and a test
  pins that.
- The bake lock beside the served picture speaks ``fcntl`` as well as
  ``msvcrt`` now (the same split the manifest's writer lock already
  made), so the serving path and its measurements run on any machine.

Measured by the same harness as the baseline — the 20-change watched
churn (10 boundary landings, 10 interior replacements), headless Linux,
software drawing; ratios are the evidence, not the milliseconds. The
baseline columns are the per-publish writer, measured earlier the same
day on the same fixtures:

| positions | writer median, was → now | landings | replacements | derive | landing→visible | finish_the_run | transients |
|-----------|--------------------------|----------|--------------|--------|-----------------|----------------|------------|
| 100       | 363 → 227 ms             | 169 ms   | 243 ms       | 29 ms  | 98 ms           | 0.0 s          | 0          |
| 196       | 412 → 218 ms             | 142 ms   | 240 ms       | 45 ms  | 105 ms          | 0.1 s          | 0          |
| 400       | 474 → 245 ms             | 161 ms   | 261 ms       | 58 ms  | 122 ms          | 0.2 s          | 0          |
| 784       | 747 → 230 ms             | 158 ms   | 255 ms       | 83 ms  | 149 ms          | 0.5 s          | 0          |
| 1600      | — → 247 ms               | 154 ms   | 261 ms       | 96 ms  | 170 ms          | 1.3 s          | 0          |
| 3249      | — → 253 ms               | 167 ms   | 256 ms       | 159 ms | 240 ms          | 3.0 s          | 0          |
| 6400      | — → 264 ms               | 179 ms   | 290 ms       | 239 ms | 328 ms          | 6.7 s          | 0          |

The baseline's writer grew with the survey — ~0.55 ms per already-
committed position, which extrapolates to the 6.9–7.7 s publishes
measured at 12,769. The writer is now **flat with scale**: a landing is
~150–180 ms and a replacement ~240–290 ms whether the survey holds one
hundred positions or six thousand four hundred, because nothing on the
publish path walks the survey any more. The linked view for outside
tools costs seconds once, at run end (6.7 s at 6,400), instead of that
much bookkeeping spread through every landing.

What still grows, and is now the whole of what grows, is the SERVER's
per-commit snapshot derive — the known linear term the harness's derive
column exists to measure (96 → 159 → 239 ms from 1,600 to 6,400) — and
with it the landing-to-visible latency (170 → 240 → 328 ms). At 6,400
positions an operator still sees a new tile in about a third of a
second; the derive's honest fix (reuse the unchanged tiles' objects) is
already written down in the prove-it plan, and it is a server-side
change that never holds up the microscope.

