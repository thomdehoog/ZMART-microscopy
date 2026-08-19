# Measured: the load window's doors, 16 to 1,024 positions

> Measured 2026-08-18 by `measure_the_load_doors.py` on a Linux container
> drawing in software (headless Chromium, SwiftShader). As with the survey
> ladders beside this note: the shapes and ratios are the evidence, the
> absolute milliseconds belong to whichever machine runs it. To repeat it
> on the workstation::
>
>     python viz_studio/building/measure_the_load_doors.py --fixtures D:/zmart-doors

Where the survey ladders measure the live path, this measures the
OPERATOR's path: every number below went through the same HTTP doors the
load window drives — the folder listing, the build without and with the
hard copy, opening through `/api/stores/open` exactly as Show does, and a
real page opening the baked scene. The fixtures are two-channel,
two-plane, 384-pixel positions on a 320 µm grid, so the bake is the
per-frame bake writing every (moment, channel) piece as its own file.

| positions | write s | list ms | linked build s | baked build s | open linked s | open baked s | to group s | ready s | pan ms |
|---|---|---|---|---|---|---|---|---|---|
| 16    | 0.0  | 4 | 0.11 | 0.31  | 0.04 | 0.05 | 0.22 | 0.23 | 117 |
| 64    | 1.3  | 5 | 0.11 | 1.24  | 0.02 | 0.05 | 0.16 | 0.17 | 153 |
| 256   | 6.0  | 3 | 0.22 | 5.01  | 0.02 | 0.06 | 0.41 | 0.42 | 171 |
| 1,024 | 24.0 | 4 | 1.07 | 19.36 | 0.02 | 0.06 | 0.16 | 0.16 | 185 |

What the table says:

- **The linked build is effectively instant at every rung** — one second at
  a thousand two-channel positions. The window's claim that the plain
  build "is immediate" holds through the whole ladder.
- **The baked build is honestly linear** (~19 ms per position here, two
  channels of frames each) and never blocks anything: it runs behind the
  progress bar and the operator can keep working. In camera terms this is
  the one-time cost the pane's info line describes.
- **Opening a built scene is flat.** Whether linked or baked, 16 or 1,024
  positions, `/api/stores/open` answers in under a tenth of a second and
  the page shows the group in under half a second — the written-down
  geometry (`tiles.json`) doing exactly what it was built for.
- **Responsiveness degrades only gently with scale.** The drawn-frame time
  while panning grew 117 → 185 ms across a 64-fold spread of positions —
  and those absolutes are software rendering; on the workstation's card the
  same probe should sit far below them. The shape (sub-linear growth) is
  the finding.

## Quirks found by the run, and their state

- **Broken-pipe tracebacks on every page close** — the server printed a
  full `BrokenPipeError` traceback each time a browser disconnected while
  an answer was in flight. The hang-up tolerance existed in
  `handle_one_request` but the constructor's final flush escapes it.
  FIXED the same day: `finish()` now carries the same tolerance
  (`server.py`), citing this run.
- **A replayed channel opens on the full-range window**, so a replay looked
  black until Auto was pressed. FIXED with the watchable-replay chapter:
  the writer's full-camera-range window is its way of declaring ignorance,
  so the reader now treats exactly that as "no window asked for" and every
  layer rests at the measured window instead (`restingWindow` in
  scene.js, shared with the panel's sliders). Any run written without a
  window benefits, not just replays. (Since the timelapse-replay chapter a
  replay is served as a LIVE run -- the run root is opened and bound, so
  the time slider offers only the written moments and follows the front.)
- **A replay does not frame itself** — the view stayed where it was, and
  the operator pressed Overview to see the landing tiles. FIXED the same
  day: starting a replay is an explicit ask to watch something, so once
  its images answer, the view steps to the first plane and moment and
  frames the whole picture (`watchTheReplay` in engine.js). Pinned by the
  hands-off gate: press Replay, touch nothing, and a healthy share of the
  canvas must light up with the landing tiles.
- **A running build or replay cannot be cancelled** from the window; the
  only path is waiting it out. Open.
- **A plate store selected on the view/other tab** opens through the plain
  library door rather than the plate layout; the build tab handles plates
  properly (select the folder holding the plate). Open; rung 2 of the
  plate chapter.

The `settled` column of the raw run (five seconds at every rung) is a
fixed four-second wait inside the instrument plus readiness, kept out of
the table above because it measures the harness, not the viewer.

## The abuse battery, same day: two defects found by testing to falsify

`test_the_doors_survive_abuse.py` feeds every door exactly what nobody
should ever feed it. Its first pass found two real defects, both fixed at
the door the same day:

- **The construct name walked out of the scene folder.** Fed `../escaped`,
  the scene landed beside the folder the operator chose — anywhere the
  server can write. Names carrying path steps are now refused.
- **A negative replay pace killed the replay thread** on `time.sleep`'s
  raw refusal. The pace is clamped at zero.

The same pass hardened the gates themselves: the replay's pixel identity
is now pinned per position (a replay mapping a position onto the wrong
cell passed every count before), the plate layout is pinned
pairwise-disjoint, a 0.4 plate lays out identically to a 0.5 one, wells
without indices take their place from the plate's rows and columns lists,
and the per-frame bake gate was sabotaged once as evidence — two baked
channels swapped on disk — and went red, proving the gate can see the
failure it guards.
