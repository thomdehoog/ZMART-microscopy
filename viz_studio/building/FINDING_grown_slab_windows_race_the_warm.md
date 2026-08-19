# Finding: grown coarse slabs can compose a negative window under the warm

> Found 2026-08-19 by the timepoint-landing instrument
> (`measure_a_timepoint_landing.py`), run to ground the same night as far
> as one session honestly could. Status: OPEN. The crash is loud and
> fail-closed (a 503, never wrong pixels), which is the correct behaviour
> until the mechanism falls -- do NOT silence it with an emptiness check,
> because a tile the index claims overlaps a piece SHOULD overlap it, and
> skipping one silently would draw missing ground with nothing on screen
> to say so.

## The symptom

Serving a grown (t, c) live run of 64 positions, some coarse pieces
(level 1 and up) answer **503 forever**: `composer._read_from` computes
`np.empty(high - low)` with a **negative extent** and every retry fails the
same way. The composer's own warm thread dies on the same error. A page
opening the run then waits on chunks that never come -- the picture never
paints.

## The bisect ledger (all in one Python process, fresh otherwise)

| sequence | outcome |
|---|---|
| 16-position run alone | fine |
| 64-position run alone, served over HTTP | piece answers 200, **but the warm thread still crashed** (the request won because the warm had already pinned that slab before dying) |
| 16 then 64 | 64's page never paints; five pieces 503 forever |
| 16 then 16 | fine |
| 64 then 64 | fine |
| 16 then 64, first run's folder kept (no deletion, no inode reuse) | still fails -- not a filesystem-identity effect |
| 64-run, warm run SYNCHRONOUSLY on a fresh composer | clean, all slabs |
| 64-run, every level-1 piece composed on a fresh composer, warm off | clean |

So the negative window needs the warm running CONCURRENTLY with request
serving (or with itself under load); the same addresses compose cleanly
single-threaded. It is a race, not an arithmetic error in any one input.

## Where the arithmetic can go negative

In `_build_slab` (composer.py), the depth overlap of tile and slab is
checked and skipped when empty, but the y and x windows are clamped and
**not** checked:

    from_y, to_y = max(top, at[1]), min(bottom, at[1] + held[1])
    from_x, to_x = max(left, at[2]), min(right, at[2] + held[2])

A tile handed to a piece it does not overlap makes `to < from` there. The
per-piece index only lists overlapping tiles *for the geometry it was
built from* -- so the working hypothesis is that under concurrency the
slab bounds and the placements/index are read from **two different
geometry states** (a governed run's mosaic is a snapshot that derives
afresh; `_indexed` is a composer-held cache). The next session's first
move: log, at the moment of the negative window, the identity of
`self.mosaic`, the index's build time, and the slab bounds' source, and
diff them.

## The 30-second reproducer (no browser)

    # one process: write a 16-cell grown run, serve one piece of it,
    # then write a 64-cell grown run and serve piece 1/c/0/0/0/1/1 of it
    # over HTTP (make_server, store="views/live/live.ome.zarr", live=True)
    # -> 503, with the ValueError above in the server log.
    # Both runs: plan_the_writing("overview", frame=384, z_planes=1,
    # timepoints=8), all positions committed at moment 0 before serving.

`measure_a_timepoint_landing.py --rungs 16 64` reproduces it end to end.

## Why it matters, and what it blocks

- A long-lived viewer process serving successive acquisitions of the same
  profile but different survey sizes hits this on the second run.
- The warm thread dying quietly means the cold-open warmth promise fails
  for grown runs at this size even when requests happen to win the race.
- The grown per-commit bake chapter builds directly on this slab path, so
  this finding gates it: the race falls first.
