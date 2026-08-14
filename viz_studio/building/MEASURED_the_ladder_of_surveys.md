# Measured: the ladder of surveys, 64 to 32,768 positions

> Measured 2026-08-13 by `measure_a_ladder_of_surveys.py` on a Linux
> container drawing in software (headless Chromium, SwiftShader). The
> shapes and ratios are the evidence here; the absolute milliseconds
> belong to whichever machine runs the ladder. To repeat it on the
> microscope machine or a GPU workstation::
>
>     python viz_studio/building/measure_a_ladder_of_surveys.py \
>         --fixtures D:/zmart-scale-runs
>
> The full spread per rung (least / middling / mean / 90th percentile /
> worst, landings apart from replacements, plus every one-time cost) is
> in `MEASURED_ladder_2026-08-13_linux_container.json`; the run appends
> its own `ladder_results.json` beside the fixtures and resumes from it.

Each rung is the full watched churn — 40 changes, half landings at the
survey's dark boundary and half interior replacements, each timed from
the writer's publish to the first painted frame — on the deferred-view
writer with the per-commit bake, warmed first, exactly as a real run
serves. Cells are middling [90th percentile / worst] milliseconds;
one-time costs are seconds.

| positions | land | replace | derive | visible | bake | warm | finish | transients |
|-----------|------|---------|--------|---------|------|------|--------|------------|
| 64        | 138 [147/152] | 228 [267/289] | 24 [27/33]    | 80 [89/122]   | 0.9   | 1.5   | 0.0 | 0 |
| 121       | 139 [148/204] | 219 [242/288] | 24 [27/31]    | 64 [73/90]    | 2.0   | 1.5   | 0.0 | 0 |
| 256       | 144 [162/199] | 227 [262/285] | 46 [52/62]    | 98 [114/133]  | 4.3   | 2.5   | 0.1 | 0 |
| 529       | 138 [148/221] | 224 [254/292] | 50 [56/66]    | 90 [97/134]   | 9.6   | 6.1   | 0.1 | 0 |
| 1,024     | 143 [152/173] | 226 [264/329] | 72 [83/190]   | 126 [150/247] | 16.1  | 12.6  | 0.4 | 0 |
| 2,025     | 160 [182/201] | 235 [278/567] | 79 [92/102]   | 122 [139/160] | 35.9  | 26.4  | 0.8 | 0 |
| 4,096     | 156 [171/190] | 242 [260/744] | 110 [125/138] | 170 [188/226] | 76.2  | 53.3  | 1.6 | 0 |
| 8,281     | 176 [190/200] | 270 [304/310] | 138 [151/184] | 183 [205/247] | 149.2 | 107.3 | 4.3 | 0 |
| 16,384    | 208 [222/226] | 314 [335/348] | 238 [280/2238] | 326 [352/394] | 312.0 | 214.2 | 8.8 | 0 |
| 32,761    | 1454 [1639/5124] | 2082 [2414/2652] | 746 [977/10102] | 758 [1015/1122] | 477.5 | 300.2* | 29.1 | 0 |

The 16,384 rung's worst derive (2.2 s against a 280 ms 90th percentile)
is the first cold-region patch caught on camera: the coarse warm took
214 s while the harness waits at most 300 s before churning, so changes
begin to land on ground the warmer has not reached.

At 32,761 that race takes over the whole row. The starred warm time is
the harness's five-minute cap expiring, not the warm finishing — the
churn then ran WITH the warmer still building in the background,
stealing a core and flooding the disk, which is what inflated every
column (a 10-second worst derive is a change landing on stone-cold
coarse ground). The honest reading of the top rung is therefore "what a
survey this size feels like when the warm has not finished", and even
there: a tile is visible in three quarters of a second and the recorder
counted zero transients.

## Tried and reverted: thread-parallel bake and warm

The obvious fix for the one-time costs — fan the bake's independent
pieces and the warm's slabs over a few threads — was built, tested
(byte-identical output), and measured, and it made things WORSE: at
1,024 positions the bake went 16 s serial, 17 s through a one-thread
pool, 20 s with two threads and 27 s with four. Every zarr read and
every piece encode funnels through zarr's one internal event loop, so
the threads had nothing real to parallelize and paid lock churn for
trying; the warm, which only reads and steps aside constantly, was
merely flat. Both were reverted the same evening — the O(change) derive
bookkeeping from the same change survived, because it measured well.

The route that genuinely works is process-level, and it is now built
for the governed bake: worker processes that each open the run
themselves through the same gateway a server uses, so the full
fail-closed gate rides along, striping the rows of each pinned level
across workers. Measured on the same 1,024-position fixture that
refuted the threads: serial 20.4 s, two processes 13.0 s, four 10.4 s —
on four cores, against the threads' 26.8 s. zarr's own concurrency
knobs (``async.concurrency``, ``threading.max_workers``) were tried on
the serial loop and moved nothing (19.7 s), which settles it: the
ceiling is one interpreter, not the loop's scheduling. A commit landing
mid-bake stays safe by the stamp's prefix rule — workers can only bake
NEWER ground than the stamp claims, and the first derive re-patches
those commits' footprints (the same catch-up finding D2 pinned).

The coarse warm is still serial: it lives inside the serving process by
design (its slabs must land in the serving composer's own memory), so
the process trick does not transfer directly. Feeding the warm from
already-baked FILES instead of composing — the bake now finishes fast
enough to come first — is the recorded idea for it.

## The ladder again, with the surviving fixes

The same ten rungs, re-measured after the day's work settled: the
deferred linked view and narrowed gate, the derive's inheritance and
O(change) bookkeeping — and the serial bake and warm, kept after the
thread experiment above measured against them. Full spread in
`MEASURED_ladder_final_2026-08-13_linux_container.json`.

| positions | land | replace | derive | visible | bake | warm | finish | transients |
|-----------|------|---------|--------|---------|------|------|--------|------------|
| 64        | 141 [154/163] | 214 [241/244] | 24 [30/57]    | 77 [85/114]   | 1.0   | 1.0    | 0.0  | 0 |
| 121       | 128 [138/174] | 224 [249/276] | 22 [26/59]    | 61 [69/97]    | 2.1   | 1.0    | 0.0  | 0 |
| 256       | 145 [168/179] | 230 [260/290] | 44 [52/61]    | 95 [103/116]  | 4.1   | 2.5    | 0.1  | 0 |
| 529       | 132 [143/148] | 214 [271/291] | 48 [52/59]    | 86 [92/99]    | 7.5   | 6.0    | 0.1  | 0 |
| 1,024     | 146 [162/174] | 225 [267/364] | 70 [78/110]   | 122 [137/167] | 16.4  | 23.8   | 0.4  | 0 |
| 2,025     | 132 [143/147] | 203 [218/418] | 69 [74/87]    | 105 [113/127] | 27.9  | 24.3   | 0.8  | 0 |
| 4,096     | 143 [149/152] | 220 [232/677] | 94 [110/114]  | 155 [165/179] | 62.8  | 49.9   | 1.7  | 0 |
| 8,281     | 172 [179/199] | 266 [287/1265]| 128 [143/160] | 170 [187/203] | 113.7 | 104.5  | 2.4  | 0 |
| 16,384    | 220 [262/270] | 308 [345/394] | 224 [262/2252]| 304 [328/356] | 258.0 | 216.9  | 9.0  | 0 |
| 32,761    | 1492 [1957/2290] | 1844 [3009/6667] | 742 [6666/12458] | 867 [1600/1907] | 519.2 | 300.3* | 29.2 | 0 |

Read against the baseline above: the middle rungs improved across every
churn column (at 2,025: land 160→132, derive 79→69, visible 122→105,
bake 35.9→27.9; at 8,281: derive 138→128, bake 149→114), the writer
stayed flat through 16,384, and zero transients held at every rung of
both ladders — twenty runs of forty watched changes without one
flicker. The starred 32,761 row reproduces the baseline's warm-race
regime almost exactly, which is its own finding: that row is governed
by the warm outrunning the five-minute cap, not by anything the day's
fixes touched, and it will stay that way until the warm is made
process-parallel or the cap learns to wait for warmth at scale.

## What the ladder says so far

- **The writer does not know the survey's size.** A landing is
  ~140–175 ms and a replacement ~220–270 ms across a 130-fold spread of
  survey sizes. The slight drift at the top rungs is the pixels' own
  I/O on a busier disk, not bookkeeping — the flat shape is the claim
  the deferred-view migration made, holding.
- **Landing-to-visible stays under a fifth of a second through 8,281
  positions**, and its growth tracks the derive column — the remaining,
  documented server-side term (~15 ms per thousand positions after the
  inheritance work), not the microscope's path.
- **Zero transients at every rung.** The picture never flickered while
  growing and being replaced under watch.
- **The one-time costs are honestly linear**: the initial bake and the
  first warm scale with the survey and are paid once per declare and
  once per cold open; the end-of-run linked view costs seconds at the
  top of the ladder, where it used to be inside every landing.
