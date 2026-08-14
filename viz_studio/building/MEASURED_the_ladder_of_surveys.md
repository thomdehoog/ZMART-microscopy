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
on four cores, against the threads' 26.8 s. At 4,096 positions the
process bake took 29.2 s where the ladder's serial bake took 62.8 —
the ratio holds at scale, and grows with the machine's cores. zarr's own concurrency
knobs (``async.concurrency``, ``threading.max_workers``) were tried on
the serial loop and moved nothing (19.7 s), which settles it: the
ceiling is one interpreter, not the loop's scheduling. A commit landing
mid-bake stays safe by the stamp's prefix rule — workers can only bake
NEWER ground than the stamp claims, and the first derive re-patches
those commits' footprints (the same catch-up finding D2 pinned).

The coarse warm no longer composes its pinned slabs on a baked
picture: they are read back from the baked files
(``warm_from_the_baked``), which already hold, patched to the current
state, exactly what composing would produce — pinned byte-for-byte by
a test. The picture is thereby SERVABLE in a second at any scale. Full
warmth still includes decoding the tiles' coarse blocks (the patcher
composes from them), which the warm does afterwards in the background,
and the warm flag waits for — so end-to-end warm sits near the
composing warm's time for now, and readiness-to-show collapsed.

## Tried and reverted: the parallel-decode block prefill

Decoding those blocks outside zarr with a few threads (resolver, byte
order, zstd) measured well in isolation and passed byte-for-byte
tests — and then the watched churn caught it doing the one forbidden
thing: transients. Thirty-two flicker events in one rung, all in the
landing row, reproducible on demand, gone the moment the commit is
reverted; the bisect is one commit wide. The mechanism was not run to
ground the same evening, so the commit is reverted on the gate's own
rule — zero transients, or it does not ship — and this note plus the
reverted commit in history are the starting point for whoever
investigates: suspicion falls on the per-commit re-warm's decode
threads racing the patcher, not on the decoded bytes, which two tests
held identical.

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

## The definitive ladder: process bake and file-fed warm included

The state the branch ships: flat writer, O(change) derive, the
process-worker bake, the warm reading its pins from the baked files
(with the serial block prefill — the parallel one is reverted above).
Full spread in `MEASURED_ladder_final_2026-08-13_linux_container.json`;
the 32,761 rung was still measuring when this table was written and is
appended to the JSON when it lands.

| positions | land | replace | derive | visible | bake | warm | finish | transients |
|-----------|------|---------|--------|---------|------|------|--------|------------|
| 64        | 156 [174/201] | 258 [279/299] | 30 [36/56]    | 97 [108/116]  | 1.7  | 1.5   | 0.0  | 0 |
| 121       | 176 [186/189] | 274 [332/344] | 30 [35/81]    | 81 [90/127]   | 3.0  | 1.5   | 0.0  | 0 |
| 256       | 156 [168/173] | 256 [320/334] | 50 [57/104]   | 110 [124/168] | 5.3  | 3.0   | 0.1  | 0 |
| 529       | 158 [177/279] | 264 [280/362] | 59 [66/85]    | 108 [117/132] | 6.3  | 15.3  | 0.2  | 0 |
| 1,024     | 167 [180/379] | 262 [289/435] | 82 [94/100]   | 145 [158/174] | 7.5  | 15.2  | 0.5  | 0 |
| 2,025     | 172 [185/438] | 274 [300/571] | 90 [96/122]   | 141 [154/192] | 11.0 | 30.1  | 0.6  | 0 |
| 4,096     | 182 [194/204] | 274 [294/300] | 120 [147/651] | 202 [230/752] | 26.7 | 60.1  | 2.0  | 0 |
| 8,281     | 192 [208/216] | 298 [316/1502]| 149 [161/214] | 208 [224/341] | 45.7 | 133.0 | 3.9  | 0 |
| 16,384    | 294 [339/380] | 412 [462/493] | 290 [339/2492]| 383 [416/525] | 89.9 | 269.9 | 10.6 | 0 |

The bake is the transformed column — 26.7 / 45.7 / 89.9 s where the
baseline paid 76 / 149 / 312, a factor that GROWS with scale (2.4× to
3.5× on four cores) and grows again with more cores. The warm is the
honest laggard: the picture is SERVABLE in about a second at any scale,
but ready-to-patch warmth still costs composing-order time, and at
16,384 it grazes the harness's five-minute head start — which is what
nudged that rung's churn medians up. The churn medians throughout this
table also carry a long measuring session's machine drift; trust the
shapes, and re-measure on a fresh machine for absolutes.

## Picking this up on another machine

Everything needed is on this branch. Setup:
``pip install -r requirements.txt playwright pillow pytest``, then
``python -m playwright install chromium``, then build the viewer once
(``cd viz_studio/frontend && npm install && npm run build``). Run
``python viz_studio/building/measure_a_ladder_of_surveys.py --fixtures
<somewhere with ~33 GB>`` (add ``--tidy`` for ~17 GB peak; use
``--powers 6-12`` for the quick half first — it resumes from its own
JSON). On a machine with more cores, raise ``_BAKE_PROCESSES`` in
``declare.py`` and compare. The open threads, in order of value: the
reverted parallel-decode prefill (find its commit and revert-of-revert
in the history; its flicker mechanism must be run to ground first),
the warm-race at the top rung that it would close, and the derive's
small remaining slope.

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
