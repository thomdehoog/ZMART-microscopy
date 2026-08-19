# Measured: a timepoint landing, from the commit to the frame on screen

> Measured 2026-08-19 by `measure_a_timepoint_landing.py` on a Linux
> container drawing in software. Shapes over absolutes, as always. Each
> rung ran in its own browser and, because of the finding below, its own
> process:
>
>     python viz_studio/building/measure_a_timepoint_landing.py --rungs 16
>     python viz_studio/building/measure_a_timepoint_landing.py --rungs 64
>     python viz_studio/building/measure_a_timepoint_landing.py --rungs 256

The survey ladders measure a POSITION landing; this measures the other
growth: a run already showing its positions gains a new MOMENT, committed
by one position, on a page held open with the view sitting on the front.
Two clocks: **offered** (commit to the slider offering the new moment) and
**followed** (commit to the view standing ON it -- the follow-the-front
behaviour, so the frame that just landed is the frame on screen).

| positions | offered s | followed s | worst followed s |
|---|---|---|---|
| 16  | 1.06 | 1.13 | 1.34 |
| 64  | 0.76 | 0.99 | 1.04 |
| 256 | 0.98 | 0.99 | 1.12 |

**A timepoint landing reaches the watcher in about one second, flat in
the survey's size.** The path is the announcement, the catch-up, and the
follow, none of which walk the positions, which is why 256 costs what 16
costs. The follow itself adds almost nothing over the offer.

## Found by this instrument, run to ground the same night

Running two rungs of DIFFERENT sizes in one process left the second rung's
page waiting forever on coarse pieces answering 503 -- a real defect in
the grown serving path, not in this instrument. The whole ledger, the
mechanism hypothesis and the 30-second reproducer live in
`FINDING_grown_slab_windows_race_the_warm.md`; it is why the table above
was measured one process per rung, and it gates the grown per-commit bake
chapter.
