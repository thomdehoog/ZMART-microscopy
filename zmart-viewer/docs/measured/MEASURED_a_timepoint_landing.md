# Measured: a timepoint landing, from the commit to the frame on screen

> Measured 2026-08-19 by `measure_a_timepoint_landing.py` on a Linux
> container drawing in software. Shapes over absolutes, as always. One
> process and one browser serve every rung, which is itself the
> regression gate for the finding below:
>
>     python zmart-viewer/app/picture/measure_a_timepoint_landing.py

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

Re-measured the day the grown per-commit bake landed (a timelapse run's
live picture is now BAKED, so every landing also patches the touched
baked files across the frame room):

| positions | offered s | followed s | worst followed s |
|---|---|---|---|
| 16 | 0.99 | 1.04 | 1.25 |
| 64 | 1.13 | 1.13 | 1.99 |

Still about one second; the per-commit patch adds at most a fraction of
a second at these sizes, and in exchange the run's cold opens read files
instead of composing the coarse ground.

## Found by this instrument, run to ground the same night

Running two rungs of DIFFERENT sizes in one process left the second rung's
page waiting forever on coarse pieces answering 503 -- a real defect, run
fully to ground and FIXED: the world frame's remembered geometry was keyed
without the run's folder, so a second run of the same name read the first
run's extent. `docs/measured/FINDING_grown_slab_windows_race_the_warm.md` holds the
whole story; `test_two_runs_share_one_process.py` pins it, and this
instrument's multi-rung mode doubles as the end-to-end regression.
