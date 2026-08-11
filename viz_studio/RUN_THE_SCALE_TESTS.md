# Running the scale tests on your own machine

Written 11 August 2026, for branch `claude/live-plus-viewer-gui-push-a68d9m`.
Everything below has already been run on a sandbox with no graphics card, and
every number it produced is recorded in `LINKING_INSTEAD_OF_COPYING.md` and
`PLAN_live_smart_microscopy.md`. Your machine answers the questions a sandbox
cannot: what the graphics card is worth, what a real disk changes, and whether
the endpoint protection lets an acquisition-shaped write through. Where your
figures disagree with the recorded ones, **yours are the real ones** — write
them down next to the old, with the date and the machine.

## What is being tested, in one paragraph

A smart-microscopy run writes one zarr that is the whole acquisition —
positions directly inside it, each a complete OME-Zarr with the run's name on
it — and the viewer shows it as **one picture** that grows in space and time
while the operator watches. The claims under test: opening does not scale with
the number of positions or the bytes on disk (only with the screenful); one
more position landing costs milliseconds however many came before; bundling a
position's pieces into one file (sharding) changes nothing for reading and
divides the file count; and the picture is *right* — every pointer followed
resolves to a tile that really covers it.

## Setting up

```bash
conda activate zmart-viz
git fetch origin claude/live-plus-viewer-gui-push-a68d9m
git checkout claude/live-plus-viewer-gui-push-a68d9m
git pull
python -m pip install -e ".[dev]"
python -m playwright install chromium
npm --prefix viz_studio/frontend install
npm --prefix viz_studio/frontend run build
```

Set `ZMART_REQUIRE_BROWSER=1` in the environment, so a test that cannot reach a
browser **fails** instead of quietly skipping — a green run that never drew a
pixel is the failure mode this project guards against most.

**The antivirus, read this before the big runs.** The measurements write tens
of thousands of small files quickly, which is the exact pattern a ransomware
heuristic watches for; on this machine it has already killed a build twice,
silently, exit code 5, no traceback. Either add an exclusion for the folder
the measurements use, or run without one *on purpose* and record what
happens — "did the sharded arm get through where the plain one was killed" is
itself a result worth a row in the plan.

## Step 1 — the test suites (about five minutes)

```bash
python -m pytest zmart_storage/tests viz_studio/tests -q
```

Expect everything to pass, with the browser-drawing tests genuinely drawing
(the run announces which Chromium it used). One test may complain if run from
the repository root rather than `viz_studio/` — `test_many_positions_arrive`
resolves a measurement module by path — so if it errors at collection, run it
once from inside `viz_studio/` and carry on.

## Step 2 — the scatter, sharded against plain (the main event)

Each command scatters positions at random over an 82k-voxel stage, writes them
**through the production run writer** (`start_a_run` — so what lands on disk
is the real layout), grows the linked view live, proves a sample of pointers
against the placements, then opens the result in a real browser and drives a
ladder of zooms. `--headed` opens a visible window, and on Windows it is the
only way to reach the graphics card — headless Chromium draws in software
whatever it is told. Every run announces which renderer really drew.

```bash
python viz_studio/measure_a_random_scatter.py 10000 --sharded --headed
python viz_studio/measure_a_random_scatter.py 10000 --coarse  --headed
python viz_studio/measure_a_random_scatter.py 1500 --tile 2048 --sharded --headed
python viz_studio/measure_a_random_scatter.py 1500 --tile 2048 --coarse  --headed
```

The first pair is the position-count test at the demo tile size (about 10
minutes each, most of it writing). The second pair is the pieces-per-bundle
test — 64 pieces in one file against 64 files — at about 13 GB a run; **do
not** run `--tile 2048` at anything like 10,000: a 2048 tile on its own
lattice has only 1,600 distinct places over this stage, which is why this
pair asks for 1,500 and the script refuses a larger ask in words. (This
document first said 2,000 here; the machine with the card found that ask
impossible to place, after five minutes of one busy core and an empty
folder.) `--coarse` places the plain arm on the same lattice as the sharded
one, so the two land on identical spots and compare fairly.

What each line of the output means:

- **linked in … (N ms each)** — the whole build through the run writer,
  positions written included. Should be flat in run size (sandbox: 42–48 ms at
  every size; the absolute number tracks your disk).
- **files on disk** — the column the antivirus and the filesystem care about;
  the sharded arm should be markedly lower, and the gap grows with tile size.
- **N pointers followed and proven to cover their piece** — correctness. Any
  failure here is a bug worth reporting over any speed number.
- **fully loaded from a cold page / whole stage fitted** — the operator's
  wait. Sandbox floors: 2.5–3.8 s at 10,000 positions. The piece counts beside
  them should match the sandbox almost exactly — they are set by the window,
  not the machine — so if *pieces* differ something real changed.
- **the ladder of zooms** — each rung's settle time and new pieces. Sandbox:
  ~0.3–0.8 s a rung, collapsing piece counts on the way out. Watch the first
  full-resolution rung in the sharded arm: it was the one place bundling paid
  anything (about 2 ms per piece of index reads, on a software renderer).

Reference tables to compare against, and the seats waiting for your numbers:
`PLAN_live_smart_microscopy.md`, section "Benchmark last".

## Step 3 — frames a second on the card

```bash
python viz_studio/measure_the_frame_rate_of_a_linked_view.py --steps 100,400,1600 --headed
```

Already measured once on an NVIDIA T400: 123 fps with a 2 ms middle frame at
1,600 tiles, flat down the table. This confirms it on the current branch, and
a run without `--headed` gives the software row of the same table for free.

## Step 4 — one more position, while ten thousand are open

```bash
python viz_studio/measure_ten_thousand_linked.py
```

No browser needed. This is the growing-run arithmetic at scale — add cost per
position, the map's weight, the server's memory and lookup times. Sandbox:
0.5–0.8 ms an add, flat from first to ten-thousandth; 8 MB of memory; lookups
in tens of microseconds; and after the incremental-index change, a landing
position costs the server ~0.14 ms of bookkeeping however many came before.

## What to bring back

Four things, in this order of value: any test or pointer-proof **failure**;
the sharded-against-plain table with the card (and what the endpoint
protection did to each arm); the frame-rate rows; and the surprises — the
numbers that disagree with the recorded ones. Put them beside the sandbox
figures in the two documents named above, dated, with a line saying what
machine they came from. Disagreement is not a problem to explain away; it is
the measurement working.
