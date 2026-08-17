# Stage 0 measurements: the numbers that decide the depth design

> The deciding instruments the revised depth plan orders before any
> construction (`TESTPLAN_the_picture_grows_a_z_axis.md`, stage 0).
> Synthetic decides, Thy1 confirms at the bench; every number here is
> in-container (software rendering, 24-core) unless marked otherwise.

## Instrument 2 — the slab read on our own stores (2026-08-17, in-container)

The question: does the Thy1 slab economy (one plane 119 ms, all 32 planes
128 ms — reading the slab nearly free once one plane is paid for) exist on
a store the governed writer actually wrote?

The measurement: one position, 13 planes (ragged on purpose), frame 1152,
written by `LivePublisher` with `z_planes=13`. Level 0 confirmed as the
writer's shipped layout — inner chunks one plane deep
(`chunks (1, 1, 1, 144, 144)`), the 13-plane bundle being the shard.
Best-of-five timings through plain zarr:

| read                | time     | versus one plane |
| ------------------- | -------- | ---------------- |
| one plane           | 36.2 ms  | 1.0×             |
| an 8-plane slab     | 303.6 ms | 8.4×             |
| all 13 planes       | 455.2 ms | 12.6×            |

**The verdict: the slab economy does not exist on our stores.** Reading a
slab costs per-plane, almost exactly linearly (12.6× for 13 planes; Thy1's
chunking would have predicted ~1.1×). The second review's finding 2 is
confirmed by measurement, and the fork it named is now real and must be
chosen:

- **either** the writer's chunking changes for deep acquisitions (inner
  chunks spanning several planes) — a format decision with contract and
  interop consequences, to be priced openly and decided per profile, the
  same way the pyramid's z-shape is a per-profile fact;
- **or** every slab-bake and cold-open estimate in the depth plan is
  priced at per-plane decode cost, honestly — roughly 36 ms × planes for
  frame-sized ground at level 0 on this machine.

Nothing downstream may assume the Thy1 economy until this fork is decided.
Thy1 bench confirmation still owed for the absolute numbers; the RATIO is
shape-driven and already decisive.

## Instrument 3 — the pinned-bytes arithmetic (2026-08-17, in-container)

`measure_the_pinned_bytes.py`, applying the composer's own pinning rule
(every level ≤ `PINNED_SHARE` of full-resolution voxels, plus the coarsest,
decoded and unevictable) to three canvases, for all three pyramid shapes,
against this machine's 16.9 GB:

- **40×40 flat survey** (the ladder's shape): 0.02 GB pinned — the flat
  geometry that made the pin feel safe.
- **49 Thy1 blocks** (the motivating evening): 0.10–0.22 GB — also fine,
  which is why the demo never hurt.
- **4,096 Thy1-shaped positions, 291 deep**: **18.87 GB pinned with z
  never halving — more than this machine has**; ~8.1–8.3 GB with z
  halving (Thy1's held-then-halved shape included) — "tight" at best,
  before the block cache, the slab cache, and a browser.

The verdict both reviews reached by hand, now re-runnable by anyone:
the share-based pin is not a dial position in depth. The pin budget
becomes an absolute byte bound sized per machine (the revised plan
already says so); this instrument joins the ladder per rung and asserts
before any warm pass.

## Instruments still to run

- Instrument 1 — the held-volume refetch counter (requests and bytes in
  the window after one announcement, volume view held), on a synthetic
  deep survey.
- Instrument 4 — the z-step cost counter on a finished picture (one plane
  step should cost one plane's pieces; the bench observation says it may
  refresh far more).
