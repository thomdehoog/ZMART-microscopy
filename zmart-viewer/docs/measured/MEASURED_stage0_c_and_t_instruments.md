# Stage 0 measurements: the numbers that decide the c-and-t design

> The record-level instruments the revised c-and-t plan orders before any
> construction (`docs/open/PLAN_the_picture_grows_c_and_t.md`). In-container
> (software rendering, 24-core) on 2026-08-17;
> `measure_the_replacement_stall_over_moments.py` re-runs the rung.

## The replacement-latency rung (the review's first finding, priced)

One position, real pixels at moment 0, the later moments' commits
appended to the record; a real replacement lands and the derive plus the
first composed piece are timed. The picture is unbaked so the fold signal
is clean; the per-moment bake does not exist yet, so its synchronous bill
is a projection by arithmetic on the ladder's measured per-replace patch
time (330–380 ms at one moment, this frame size, this machine).

| moments | derive ms | first piece ms | swept units | projected sync bake | lazy |
| ------- | --------- | -------------- | ----------- | ------------------- | ---- |
| 50      | 1.5       | 28.2           | 103         | 16.5–19.0 s         | 0.33 s |
| 200     | 1.6       | 33.9           | 453         | 66.0–76.0 s         | 0.33 s |
| 500     | 1.9       | 32.0           | 1,253       | 165.0–190.0 s       | 0.33 s |

**The verdict, and the mitigation the number chooses.** The review's
projection is confirmed: a synchronous per-moment bake patch inside the
derive lock would freeze the picture for **around three minutes** at a
500-moment retake — against a **third of a second** for the lazy
alternative, flat in m. The plan said the mitigation is chosen from the
number, never assumed; the number has now spoken, some five hundred times
over: **lazy per-moment patching behind compose-on-request** — only the
viewed moment patches synchronously, every other moment patches on its
next visit. Patching outside the derive lock remains available as a
refinement, but it cannot be the answer alone, because minutes of
patching still block that position's freshness wherever it runs. The
build gate that comes with the mechanism: time-to-first-answered-piece
after a retake stays inside the one-moment bound at every rung.

## The fold's O(positions × moments) term (finding 8, counted)

The swept column above is the counter: the derive's bookkeeping walks
every published (position, moment, generation) unit on every landing.
Pinned exactly by `test_the_fold_today_sweeps_every_published_moment`
(two positions, eight moments, every pixel real — the pin fails the day
the fix lands, which is what it is for). The cost today: the slope
measured above is ~0.35 µs per published unit, so at one position even
500 moments is under 2 ms — but the term is multiplicative, and at the
motivating survey's shape (4,096 positions × 500 moments ≈ 2 million
units) the same slope prices every landing's bookkeeping at **roughly
0.7 s** before any pixels move. The fix the plan orders — a landing's
bookkeeping sized by the landing — stays ordered; nothing here softens
it, the number just says when it bites.

## Not measured yet, and why

- **The synchronous bake column** stays a projection until the
  per-moment bake exists; the instrument grows the measured column the
  day it does, and the projection retires.
- **The three refetch bills** (two-channel storm, held-old-moment,
  moment-flip cold) are browser-side counters and need the served (t, c)
  axes to exist before they can count anything; they are ordered with
  the build, gates before merge.
