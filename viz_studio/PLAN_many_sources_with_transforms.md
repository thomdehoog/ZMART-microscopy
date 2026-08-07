# Many sources with transforms: what breaks, and how to find out why

Placing tiles by a translation in each store's own description works and is worth
having: it is free of the chunk grid, revisable without moving a voxel, and
`PLAN_placement_by_transform.md` records both the mechanism and its cost.

**It also draws wrongly once there are a hundred of them, and the mechanism is not
yet known.** This document exists so that the finding is not lost, so that a
reviewer does not re-tread four dead ends, and so that the next experiment is
chosen rather than guessed. Nothing here should be implemented until the mechanism
is established.

## The observation

All at 100 positions of the ladder, copied out as separate stores, served as one
layer, drawn in software.

| what was placed | zoom | result |
|---|---|---|
| no translation at all | 4.6 | **clean** — sharp grid, every tile resolved |
| −51.2 voxels, written per dataset | 4.6 | patchwork of blocks at mismatched scales |
| −51.2 voxels, written at the multiscale level | 4.6 | patchwork |
| −64 voxels (whole at every level) | 4.6 | patchwork |
| +64 voxels (tiles separated, never overlapping) | 5.4 | patchwork |

`held` reads 100 in every row, so every source registered. On the last of these
`lit` was sampled every fifteen seconds to ninety and read **0.196 throughout** —
it is settled, not still arriving.

The same offsets at **10** sources draw perfectly, at zoom ≈ 2.

Artefacts, for anyone reproducing: `control100_nooffset.png`, `sources100.png`,
`sources100_whole.png`, `sources100_apart.png`, `sources100_settled.png`, built by
`make_overlapped_sources.py <count> <folder> [overlap in voxels]`.

## Ruled out, with the evidence

Each of these was a hypothesis I asserted and then disproved. They are recorded so
they are not proposed again.

- **The transform slot.** Writing the translation at the multiscale level rather
  than into every dataset changes nothing; both fail identically.
- **Fractional voxels.** 51.2 voxels is a fifth of a voxel and 12.8 at level 2 —
  but 64, whole at every level a position carries, fails the same way.
- **Overlap and compositing.** Separating the tiles so no two ever cover the same
  voxel fails too. It is not double-drawing.
- **Progressive loading.** `lit` is flat at 0.196 from fifteen seconds to ninety.
- **Source count alone.** A hundred sources with no translation is clean.

So the fault needs *many sources* **and** *any translation*. Neither alone does it.

## The confound to resolve first

**Count and pyramid level are confounded, and this was my error in setting the
comparisons up.** The clean 10-source case was viewed at zoom ≈ 2, near the finest
level; every broken 100-source case was viewed at zoom 4.6–5.4, which draws from a
coarser level. So "a hundred sources" and "a coarse level" have never been
separated, and the fault may belong to either.

**Experiment 1, before anything else — two cells of a 2×2:**

- 10 sources with the same translation, zoomed *out* to a coarse level.
- 100 sources with the same translation, zoomed *in* to level 0 on one corner.

If 10 breaks when zoomed out, this is about the pyramid level and the count is
irrelevant. If 100 is clean when zoomed in, likewise. Either result halves the
search. This is cheap and must come first.

## Candidate mechanisms, and what would decide each

Only to be pursued after Experiment 1 says which axis matters.

1. **A capacity limit.** A stable 0.196 is what a budget looks like: the engine
   draws what fits and stops. With a translation the sources' chunks no longer
   align, so nothing can be shared and the number of distinct chunks needed rises.
   *Decide it by* reading the engine's own chunk statistics — `chunkQueueManager`
   and its capacities — with and against the no-translation control, rather than
   inferring from the picture.

2. **Alignment rather than magnitude.** If a **one-voxel** offset breaks it just as
   a 64-voxel one does, magnitude is irrelevant and the mechanism is that any
   translation stops sources sharing a grid. *Decide it by* a sweep: 0, 1, 8, 64,
   128 voxels. Note 0 and 128 are both grid-aligned; if those two are clean and
   1 and 8 are not, that is close to conclusive.

3. **The coordinate space the layer computes from its sources.** With differing
   translations, the union of the sources' bounds is recomputed. Something there
   may clip or quantise. *Decide it by* reading the layer's combined coordinate
   space and comparing the bounds against what the stores declare.

## What changes might follow

Deliberately not decided yet — the mechanism chooses among these, and picking now
would be the same mistake four times over.

- If capacity: a documented ceiling on sources, surfaced in the interface rather
  than left as a silently wrong picture, plus guidance to use the linked picture
  above it.
- If alignment: constrain offsets to the chunk grid at the coarsest level in use,
  which reintroduces a quantisation — finer than the pointer map's, but real, and
  it would weaken the case for this whole approach.
- If coordinate space: likely an upstream neuroglancer fix.

**In every case the picture must not be allowed to be quietly wrong.** That is the
same standard the scale bar is held to, and this fails it today: nothing on screen
says the view is incomplete.

## What this does to the earlier plan

`PLAN_placement_by_transform.md` concludes that transforms are an overlay for small
runs and surveys keep the linked picture. That still stands, but its ceiling is now
in doubt: the cost curve said the limit was performance, and this says there may be
a much lower limit where the picture simply stops being true. **The recommendation
should not be acted on until this is understood.**

## For the reviewer

Specific things worth attacking:

1. Is Experiment 1 the right first cut, or is there a cheaper variable that
   separates count from level?
2. Is a stable `lit` of 0.196 really the signature of a capacity limit, or is that
   another plausible story that wants disproving? What would disprove it?
3. Four hypotheses were asserted from reading the code and each was wrong. Is there
   a way to instrument the engine directly — chunk counts, per-source render state
   — that would settle this without any more visual comparison?
4. Is comparing screenshots at all defensible here, given that reading positions
   off them has produced repeated wrong conclusions in this work? What is the
   numeric equivalent of "the picture is a patchwork"?
5. Should the ceiling, once known, be enforced in the app or merely documented?
