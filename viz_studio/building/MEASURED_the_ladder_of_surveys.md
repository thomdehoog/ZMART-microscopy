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

## The first real machine: 24 cores and a real disk

> Measured 2026-08-14 on the lab's Windows 11 workstation: 24 cores,
> fixtures on a large dedicated data disk (``D:\zmart-ladders``), Python
> 3.12, Chromium 151. Note before any number is read: **the drawing is
> still in software** -- headless Chromium chose SwiftShader here exactly
> as it did in the container, and the harness prints as much -- so the
> visible column speaks for the cores and the disk, not for a GPU. Full
> spread in ``MEASURED_ladder_2026-08-14_windows_24core_quickhalf.json``.

The quick half (``--powers 6-12``), run against the branch exactly as
handed over, before any of this day's changes:

| positions | land | replace | derive | visible | bake | warm | finish | transients |
|-----------|------|---------|--------|---------|------|------|--------|------------|
| 64        | 174 [194/204] | 238 [251/277] | 19 [24/44]    | 47 [63/74]    | 1.2  | 1.0  | 0.0 | 0 |
| 121       | 166 [183/205] | 234 [256/272] | 18 [19/37]    | 41 [50/80]    | 1.8  | 1.0  | 0.1 | 0 |
| 256       | 193 [212/233] | 262 [301/358] | 40 [44/62]    | 68 [87/98]    | 3.1  | 2.0  | 0.2 | 0 |
| 529       | 204 [231/236] | 294 [342/374] | 47 [50/57]    | 75 [83/88]    | 4.1  | 5.6  | 0.3 | 0 |
| 1,024     | 176 [190/300] | 252 [264/379] | 62 [72/84]    | 86 [104/109]  | 4.5  | 9.2  | 0.7 | 0 |
| 2,025     | 172 [189/192] | 241 [271/513] | 60 [66/79]    | 86 [100/113]  | 9.3  | 17.4 | 1.3 | 0 |
| 4,096     | 197 [218/227] | 275 [302/932] | 110 [129/144] | 123 [135/138] | 18.2 | 39.1 | 2.7 | 0 |

Read against the container's definitive ladder: every shape holds. The
writer is flat across a 64-fold spread, the derive grows its documented
gentle slope, and zero transients at all seven rungs. The absolutes are
where the machine speaks: landing-to-visible is 40 percent down at
every rung (86 ms at 2,025 against the container's 141), the process
bake pays 4.5 / 9.3 / 18.2 s at 1,024 / 2,025 / 4,096 where the
container's four workers paid 7.5 / 11.0 / 26.7 -- still on the
four-worker cap, so this is the same code merely fed by real cores and
a real disk -- and the warm roughly halves through 2,025. The one
carried-over signature is the cold open's worst derive at 4,096
(2.2 s), the first cold-region patch, exactly where the container first
showed it at 16,384: a faster machine moved the symptom down the
ladder rather than away, which is its own small finding -- the warm
race is a ratio of speeds, not a fixed size.

### What the machine's speed flushed out

The guard suites on this machine opened with 1,229 green and 16 red,
and every red taught something. In value order:

- **The opening fit raced the folder's stores, and always had.** The
  viewer fits the view once, the moment the coordinate space first has
  axes -- and a folder of several stores gives it axes when the FIRST
  description resolves, so the fit framed one tile of many. On the
  container this machine race was hidden: the fit's fallback path (a
  panel not yet laid out reports no size, and the engine's default zoom
  is kept) is what the browser tests actually exercised, which is why
  they passed while the operator's pywebview window fitted correctly.
  The fast machine made the fit real in headless for the first time and
  ten tests failed at once. The fit now waits until every store the
  page asked for has been answered -- the same "answered, whichever
  answer" rule ``whenTheseHaveBeenRead`` uses, heard on each source's
  own changed signal so the fit still lands before the first full
  drawing. Four geometry tests were then measuring in screen pixels
  what the fit deliberately re-frames per scene; they measure in
  on-screen tile widths now, which their own docstrings' "a ratio
  survives any zoom" argument always wanted.
- **A second viewer could silently take a taken port -- Windows only.**
  The standard library server asks to reuse its address, and on Windows
  ``SO_REUSEADDR`` means a second socket may bind a port another
  process is actively listening on, so the friendly "that port is
  taken" message could never fire and two viewers would fight over
  connections. The server now binds exclusively
  (``SO_EXCLUSIVEADDRUSE``) on Windows and keeps the harmless reuse
  meaning elsewhere.
- **Two caches could serve stale answers for good -- the same clock-tick
  race twice.** Windows stamps files and folders from a clock cached for
  up to ~16 ms, and its ``st_ctime`` is creation time, so it never
  helps notice a change. ``written_timepoints`` remembers its count
  against the moments folder's modification time, so a frame landing in
  the same tick as a count left the remembered answer stale for the
  session. Worse, ``shardlink``'s remembered tables key on the bundle
  file's identity (size, inode, both stamps) -- and in-place
  replacement, this project's everyday operation, rewrites a bundle at
  the same size, so a same-tick rewrite kept the old table and would
  serve real, decodable, WRONG pixels; the guard test caught it by
  refusing its own claim on this filesystem. Both now follow the rule
  build tools settled on long ago: an answer measured against a stamp
  still within the clock's reach of "now" is used but not remembered
  (``_MTIME_STILL_MOVING_NS`` in ``stores.py``,
  ``STAMPS_STILL_MOVING_NS`` in ``shardlink.py``), and the guard test
  now exercises both protections -- the hot path where nothing was
  remembered, and the cooled path where the moved stamp is what
  retires the old table.
- **The card was always reachable headless -- the build was the trap.**
  The 6 August 2026 finding said a headless Chromium reports
  SwiftShader whatever arguments it is given and only a window reaches
  the card. What was really measured is Playwright's *headless shell*,
  a build that cannot use a GPU at all; the full Chromium build asked
  for by name (``channel="chromium"``) reports `NVIDIA T400 4GB ...
  D3D11` headless, exactly as the window does. The measuring launcher
  now asks for the full build first, and the per-run renderer
  announcement says which one drew. Every table above this line was
  drawn in software; the full record below is the first on the card.
- **Forty-two pixel tests were quietly skipped.** The suite's
  strictest tests -- the ones that read the drawn pixels -- need the
  options harness built (``npm --prefix viz_studio/options/harness run
  build``), which the setup instructions did not mention; the suite
  said so in its summary and nothing failed. It is built here and the
  setup list corrected.
- **The manifest-refresh file still spoke the retired view names.**
  ``seamless``/``non_seamless`` no longer exist; a run publishes
  positions and its one linked view, served from the baked picture
  (``VIEW_ROLES`` in ``zmart_live/scene.py``). Three tests carried the
  old names -- in panel labels, in expected source identities, in
  which store paths a commit should refetch -- and the behaviour under
  every one of them was correct on screen once asked for by its
  current name. (An earlier reading of these as order-dependent was an
  artifact of a truncated failure list, and is withdrawn: the pristine
  tree fails them identically, alone or in the suite.) One genuine gap
  remains inside ``test_uncommitted_time...``: its second half wants
  the second moment ON SCREEN, and the served governed picture is
  built z-y-x only however far the run's own overview reaches in time.
  That is the recorded migration work -- "the t axis through the
  served picture", ``DECISION_finish_the_migration_to_one_live_path.md``
  -- so that half is an explicit xfail naming it, and what can be
  promised today (uncommitted time is never offered; the committed
  reach is reported) is asserted before it.
- **The never-run pixel tests held real findings once they ran.** With
  the options harness finally built, the foreign-image tests -- an
  OME-Zarr written by somebody else's instrument, three axes, far from
  stage zero -- failed for two honest reasons: the harness page
  refused to frame a store with no coverage record even when opened
  unbounded (it now falls back to the ground the store itself
  declares, translation included), and the drew-anything threshold was
  set above what the page's own framing can produce (the fit puts the
  imaged ground at about a tenth of the window; the bar said a fifth
  -- unattainable since the test was written, which no one could see
  while it only ever skipped). All three options draw the foreign
  image.

## The full record on the card: all ten rungs, and the top one ordinary

> Measured 2026-08-14 on the same 24-core workstation, after the day's
> fixes landed, drawing ON THE CARD (NVIDIA T400, D3D11, the full
> Chromium build's headless — see the launcher note above). Every rung
> re-measured against the committed tree; full spread in
> ``MEASURED_ladder_2026-08-14_windows_24core_card.json``.

| positions | land | replace | derive | visible | bake | warm | finish | transients |
|-----------|------|---------|--------|---------|------|------|--------|------------|
| 64        | 144 [152/166] | 257 [268/274] | 16 [18/42]    | 52 [69/91]    | 1.3   | 1.0   | 0.1  | 0 |
| 121       | 144 [169/181] | 252 [267/280] | 16 [24/42]    | 50 [64/82]    | 2.0   | 1.0   | 0.1  | 0 |
| 256       | 144 [153/177] | 256 [286/296] | 30 [32/41]    | 56 [80/108]   | 3.1   | 2.0   | 0.2  | 0 |
| 529       | 144 [155/199] | 262 [305/321] | 32 [35/40]    | 62 [77/97]    | 3.9   | 3.6   | 0.6  | 0 |
| 1,024     | 149 [170/183] | 267 [361/410] | 50 [57/171]   | 79 [95/213]   | 5.7   | 7.7   | 1.1  | 0 |
| 2,025     | 165 [193/442] | 286 [333/575] | 61 [71/265]   | 90 [106/298]  | 7.9   | 14.9  | 2.6  | 0 |
| 4,096     | 186 [233/262] | 291 [376/998] | 98 [146/667]  | 123 [159/664] | 19.0  | 39.1  | 5.1  | 0 |
| 8,281     | 191 [214/223] | 316 [349/1627]| 102 [117/141] | 136 [157/171] | 24.9  | 60.3  | 4.5  | 0 |
| 16,384    | 252 [311/333] | 359 [466/511] | 199 [308/2464]| 219 [301/383] | 50.7  | 127.0 | 12.5 | 0 |
| 32,761    | 317 [400/951] | 476 [542/598] | 196 [228/295] | 240 [263/359] | 210.6 | 266.9 | 34.9 | 0 |

**The warm finished — 266.9 s, inside the harness's five-minute head
start — and the top rung is an ordinary row for the first time on any
machine.** No star, no caveat: the churn at 32,761 ran on fully warm
ground, and every column says so against the container's warm-poisoned
row — land 1454 → 317, replace 2082 → 476, visible 758 → 240. The
campaign's remaining headline claim is measured, and the open thread
that expected to need the parallel-decode prefill for it closes without
it. The prefill's flicker mechanism is still worth running to ground —
as an investigation, no longer as a rescue.

Two findings live inside the numbers:

- **The derive's top-of-ladder growth was substantially the warm race
  in disguise.** 196 ms at 32,761 against 199 ms at 16,384 — the column
  stopped growing — and the tails tell the story: 16,384's worst derive
  is 2,464 ms (changes landing on ground its own warm had not reached,
  at 127 s of warm against commits starting at once), while 32,761,
  whose warm had all of a five-minute head start's room, shows a tight
  228 ms 90th percentile and a 295 ms worst. The residual slope that
  remains (~5 ms per thousand positions here) is much shallower than
  the container's ladder suggested.
- **Landing-to-visible at thirty-two thousand positions is a quarter of
  a second** (240 ms middling), with zero tiles re-read on any of the
  four hundred watched changes of the whole record, and zero transients
  at every rung. An operator adds a tile to a survey of thirty thousand
  and sees it in the time a key repeat takes.

The one-time costs at the top: 33 minutes writing the fixture (paid
once, kept), 26 minutes bulk-publishing it (the fixture machinery's
cost, not a run's — a real run commits as it goes), 210.6 s of bake,
266.9 s of warm, 34.9 s for the end-of-run linked view. The bake at
this rung is the next thread's target: still on the four-worker cap
from the container, on a machine with twenty-four cores.

## Picking this up on another machine

Everything needed is on this branch. Setup:
``pip install -r requirements.txt playwright pillow pytest``, then
``python -m playwright install chromium``, then build the viewer once
(``cd viz_studio/frontend && npm install && npm run build``) and the
options harness once (``npm --prefix viz_studio/options/harness install``
then ``... run build``) -- without it the suite's pixel-reading tests
skip, and say so only in the summary. Run
``python viz_studio/building/measure_a_ladder_of_surveys.py --fixtures
<somewhere with ~33 GB>`` (add ``--tidy`` for ~17 GB peak; use
``--powers 6-12`` for the quick half first — it resumes from its own
JSON). On a machine with more cores, raise ``_BAKE_PROCESSES`` in
``declare.py`` and compare. The open threads, in order of value, as
they stand after the full record above: the bake worker count (still
the container's four-worker cap; 210 s at the top rung on twenty-four
cores is the thread's target), the reverted parallel-decode prefill's
flicker mechanism (an investigation now, not a rescue — the warm race
it was meant to close is closed above), the per-position metadata
round-trips in the publish path (``NOTE_the_shard_is_written_once.md``
names them), and the derive's small remaining slope.

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

## Found after the record, by watching: stale middle levels under a commit storm

The first evening of *watching* runs grow (``show_a_run_growing.py``)
surfaced what the recorder never could. Driving commits at ten a second
— thirty times a real microscope's rhythm — while zooming, the page was
left holding stale pieces at the middle composed levels (L1/L2): black
stripes tracing the last-landed ground, stuck at those zooms until a
reload. The server was proven innocent piece by piece — every L1/L2
piece over the stripes answered fresh and complete to a cold client —
so the loss is client-side: invalidations for the middle levels dropped
somewhere in the refresh path under a rate it was never gated at. The
recorder shares the blind spot honestly: every transient gate so far
watched the opening zoom, so a middle level gone quietly stale was
invisible to the whole campaign. Reproduction: a spiral at
``--every 0.1`` with ``--quick-page``, zoom during the run, then
compare zoom levels. The thread this opens: gate the churn's recorder
at more than one zoom, and run the lost invalidation to ground the way
the prefill's flicker is queued to be — mechanism first.

### The storm staleness, run half to ground

The stripes were chased through a night of eliminations, each banked as
a gate. Ruled OUT, with the evidence committed: the browser (Chrome,
Edge and the harness's Chromium all reproduce; all are one engine), the
GPU (software and card both show it), the server (every disputed piece
answers fresh to a cold client, at every level), the invalidation
routing (a real bug, found and fixed on the way -- see
``test_dirty_pieces_reach_their_level.py`` -- but not this one), the
absent-memory (a hole first seen empty paints when it lands; gated),
and the beside-the-machine push racing evictions (state now verified at
delivery; kept, not the cause). What reproduces it on demand is
``test_a_commit_storm_under_zooming.py`` -- landings at ten a second
under continuous PANNING and zooming on the eager-check page, judged by
the honest oracle: each zoom band against its own reload, because
whatever a reload cures WAS staleness. It stands in the suite as a
strict expected-failure until the mechanism falls.

Where the trail ends tonight, measured from inside the red state: the
engine's bounds are correct, nothing is starving -- at the worst band
it renders TWO chunks, the coarsest scale, reports needed equal to
available, and never asks for more; the fresh client at the same view
renders the fine scale complete. The level-of-detail machinery is
wedged coarse with mid-storm content, an accumulating wedge (early in
the run it is fine), invisible to every needed-vs-available check, and
undone only by rebuilding the page's world. The next session starts by
diffing the render layers' scale selection between a stormed session
and a fresh one at the same view.

One more surface, checked rather than assumed: the pywebview window —
the production glass, WebView2 underneath — driven by the same hands
through the same storm, broke the same way. The map is complete: every
surface the viewer ships on shares the one engine and the one wedge,
and the one fix.

The recipe closed the same evening, by the operator running the
quadrants: a full-rate storm WATCHED BUT UNTOUCHED is clean, twice
over; the same storm under zooming wedges every time. Interaction
during updates is a NECESSARY ingredient — the wedge is a race between
navigation's scale changes and in-flight refreshes, not an
accumulation — and the position count only ever mattered as chances
for the collision. Which also bounds the exposure honestly: an
operator who is not actively navigating during heavy commits never
meets it, and a reload cures it when they do. The mechanism hunt
starts inside the scale-selection path with that collision in hand.

The operator finished the matrix with a pre-committed core: on a
survey already 1,600 tiles big, zooming during a 20-a-second storm
wedges ALMOST IMMEDIATELY, where the same storm growing from empty only
wedged late — so "late in the run" was survey SIZE all along, never
elapsed time. And a rate ceiling showed itself on the way: at 20
commits a second even an untouched viewer flickers mildly, where ten a
second untouched is clean — a second edge, far beyond any microscope,
now measured. The recipe in final form: updates in flight, navigation
during them, survey size setting the collision window, rate rolling
the dice. One mechanism carries every observation of the evening.
