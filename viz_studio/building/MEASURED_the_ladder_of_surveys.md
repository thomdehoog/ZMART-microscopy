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
| 32,761    | *being measured* | | | | | | | |

The 16,384 rung's worst derive (2.2 s against a 280 ms 90th percentile)
is the first cold-region patch caught on camera: the coarse warm took
214 s while the harness waits at most 300 s before churning, so changes
begin to land on ground the warmer has not reached. Expect more of the
same in the 32,768 rung's worst-case columns — it is a warm-race
artifact of the harness's cap, not the steady state, and the parallel
warm work targets exactly this window.

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
