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
