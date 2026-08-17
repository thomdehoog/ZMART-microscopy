# Test plan: the picture grows a z-axis

> The companion of `PLAN_the_picture_grows_a_z_axis.md`, written 2026-08-17
> the same night and revised with it after the two independent reviews. The
> plan says what is to be built; this says how it will be held to account,
> in what order, and on what data. The order is the campaign's standing one
> — with one addition the reviews forced: three deciding instruments now run
> **before anything is built at all**, because they choose between designs
> rather than check one. After that: gates first, bake-free, on synthetic
> data cheap enough to compare every voxel; measurement second, on the
> ladder; the real acquisition last, at the bench, as validation rather than
> as a test bed. Every browser gate is seen red through a named sabotage
> before its green is trusted — the wire-word hunt is the standing reminder
> of why.

## Stage 0 — the three deciding instruments (before any construction)

These do not test the feature; they decide its shape. Nothing downstream
may be built on an answer these have not given.

One practical rule for where they run: **synthetic decides, Thy1
confirms.** The Thy1 data lives at the workstation, not in the container
where iteration happens — so each instrument runs first on a synthetic
deep governed fixture (stamped planes, small, built to the fixture rules
below), and the numbers that decide — request counts, bytes, per-plane
decode cost, pinned bytes — are shape-driven, so the synthetic run is the
deciding one. Each instrument then gets one confirming run on real Thy1
at the bench, recorded beside the synthetic number in the MEASURED
document; a confirmation that disagrees with its synthetic number reopens
the question, loudly.

- **The held-volume refetch counter.** The existing Thy1 one-source script
  with the volume view toggled on; land one block; the server counts
  requests and bytes served in the window after the announcement. One
  evening, zero new code. Its table — one cell per (piece shape × rendered
  level) — chooses the volume view's refresh mitigation and feeds the
  z-halving decision its dominant column.
- **The slab-read measurement on our own stores.** The 119/128 ms
  one-plane-versus-whole-slab experiment, re-run on a store the governed
  writer actually wrote (inner chunks one plane deep). An hour. It decides
  whether the writer's chunking is on the table, and prices every bake
  estimate honestly if it is not.
- **The pinned-bytes arithmetic.** Ten lines computing the pinned-set bytes
  from a deep profile, printed per ladder rung and asserted against the
  machine's RAM. Red on day one by design — it is the instrument that
  demotes the RAM pin from load-bearing tier to garnish under an absolute
  byte bound.
- **The z-step cost counter.** A bench observation (2026-08-17) says that
  navigating in z or t *seems to trigger a refresh of the whole thing*.
  On a FINISHED picture — no landings, nothing to refresh — step the plane
  slider one plane and count requests and bytes at the server. Stepping
  one plane should cost one plane's pieces; if it refetches the world,
  that is a cost bug at any depth and a disaster at 291 planes, found
  before it is built on. The same counter, one moment step, the day t
  exists.

## The two kinds of data, and what each is for

**Synthetic deep tiles carry the whole correctness campaign.** The flat
suite's fixture grows a real depth with **every plane stamped with its own
index**, so a piece served from the wrong slab or a slab built off by one
plane decodes to visibly wrong numbers. Tiles stay small, so every test can
afford to compare every voxel against ground truth laid out by hand. Two
rules the reviews added:

- **Fixtures are governed runs, committed through `zmart_live` — always.**
  The transfer door's growth machinery (re-declare and rebuild) may not
  appear in any fixture, because gates built on it certify the door the
  plan forbids from growing while the governed path ships untested.
- **At least one fixture depth is ragged**: odd, and not a multiple of the
  slab depth (13 planes with an 8-plane slab names both the
  ceiling-versus-floor seam and the final partial slab). Even-only depths
  let a last-plane-blank off-by-one pass every voxel comparison.
- **Every correctness stage runs on both pyramid shapes.** The data
  decides whether a pyramid shrinks only y and x or shrinks z too, so
  both shapes are first-class and the gates are parameterized over them:
  one fixture profile whose per-level downsampling leaves z alone, one
  whose z halves (and, once the mixed rule exists, one that holds z for
  some levels and then halves — the Thy1 shape). A gate green on one
  shape only certifies one shape; the shape that is never run is the
  shape that rots.

**The Thy1 blocks are the bench rung, not a test bed** — claims are
validated there, never debugged there, exactly as before.

## Stage 1 — geometry gates (no browser, minutes to run)

- **The room is declared whole, and generously.** A declared deep picture's
  description covers the full (t, c, z, y, x) room from the profile before
  any position lands, and a landing never changes it: declare, land,
  re-declare, byte-identical `zarr.json`. The reviews' addition: the room
  is declared as a **ceiling** (more room than will be imaged), less is
  landed, and the gate also asserts the landing's cost never noticed the
  ceiling — un-imaged room must be free per landing, or the generous-
  ceiling rule for unknown extents is dishonest.
- **The rounding rule is ceiling, held everywhere.** One geometry test
  drives an odd depth through the three call sites that compute level
  depths (the gateway, the world frame, the pyramid extension) and asserts
  they agree. Today they do not (floor in one, ceiling in two), invisible
  while z divisors are 1; this gate exists before any divisor changes.
- **The dirty footprint is one named shape.** (level, slab, row, column),
  defined once, and the test imports it from all three consumers
  (inheritance, index, patcher) to prove there is exactly one definition.
- **The contrast window samples imaged ground.** Synthetic stamped tiles in
  a generously declared room; the chosen window is asserted against the
  ground truth of the imaged voxels, never the declared emptiness. This is
  a standing gate precisely because warm-versus-fresh censuses are blind
  to it: a window wrong the same way in both screenshots passes every
  census ever taken.
- **Slab addresses bound-checked**, and **the halving decision, whichever
  way the measurement lands, pinned per level in the profile** by a
  geometry test the day it is decided.

## Stage 2 — composed slabs are correct (no browser, bake-free)

- **Every piece equals ground truth**, voxel-for-voxel, the long way.
- **Pieces asked for all at once are not muddled** — the parallel-encoder
  trap re-run in depth, because slab state is new shared state.
- **A landing dirties exactly its footprint**: land one position,
  byte-compare every piece of every level before and after; inside the
  (slab, row, column) footprint changes, outside is byte-identical — and
  the footprint arithmetic is the named shape from stage 1, not a
  reimplementation.
- **A replacement in one moment leaves other moments alone** (the day t
  exists), the O(moments) spike pinned as the record layer already does.

## Stage 3 — browser gates (synthetic, the four-square grid)

All built on the `test_a_built_picture_grows_while_watched.py` pattern, and
every gate here runs the four-square grid from the (t, c) plan: **held view
and scrolling around, each photographed before and after F5**, compared
only when both sides are fully loaded. F5 must never be a repair tool, in
either posture.

**The canonical recipe is the station walk**, and it exists because of a
bench fact: navigating — especially stepping z or t — tends to trigger a
refresh, so any test that moves will quietly repair the staleness it was
sent to find. A single warm-versus-F5 comparison at the end of a session
therefore proves almost nothing; the comparison must happen **at every
station**. The walk: while landings drip continuously (the Thy1-spiral
pattern, synthetic), visit a fixed sequence of stations — a held plane in
a middle slab, a different plane, a different x/y position, a different
zoom, and (the day t exists) a different moment — and at each station,
once fully loaded, photograph warm, reload, photograph fresh, compare.
Landings keep arriving between stations, so every comparison happens on
ground that changed since the page last saw it. A gate passes only if
every station matches, and the failure message names the station.

Two rules keep the walk honest, because assumptions are exactly what it
exists to replace. The z/t-refresh observation is an *observation*: the
stage-0 counter measures it before any gate relies on or compensates for
it — if stepping a plane does not actually refresh, the walk still works,
and if it refreshes the world, that is a finding, not a feature. And every
station-walk gate is red-proven by a named sabotage (suppress the
announcement, shift the slab key, skip a commit) placed so that exactly
one station goes wrong — a walk that cannot say *which* station fails is
an alarm, not an instrument.

- **A landing appears at a held plane, in depth** — the view held on a
  plane in a *middle* slab (never slab zero), a block lands, it appears
  unasked.
- **The revisited plane shows current truth** — visit, move away, land,
  return: no plane may show older truth than the youngest announcement.
- **The held volume view follows, and its brightness instrument
  discriminates.** Mean brightness sampled **during** a burst of landings
  (a transient twin is reaped by quiet-time; a settle-then-measure census
  can miss the very mechanism suspected), the comparison **two-sided** (a
  warm page too bright fails — the one-sided `warm >= fresh - ε` pattern
  would pass the observed fault), and beside the brightness two reads that
  name the mechanism on any red: the engine's managed-layer count (a
  lingering twin is countable) and the applied display window as JSON,
  warm against fresh.
- **One storm variant with the volume view held**, at a realistic synthetic
  depth: sustained landings at the storm's cadence with the 3-D panel on,
  gating whichever mitigation stage 0's table chose — convergence within
  the measured budget, or the staleness affordance visibly engaged. This
  is the failure mode both reviews ranked first; without this gate the
  volume acceptance bullet is uninstrumented.
- **One gate runs with the bake ON**, red first via the shifted-slab-key
  sabotage. The baked-file short-circuit is a third, independent reader of
  the z slot; bake-free gates pass a plane-versus-slab mismatch by
  construction, so exactly one browser gate carries the bake to hold that
  seam.
- **Zero transients throughout**, per-frame recorded, on any plane, in
  both postures.

Each gate's red is produced by a named sabotage before its green counts:
the wire-word sabotage for the announcement chain, a skipped commit for
the serving side, the shifted slab key for delivery and bake. A gate
nobody has watched fail is a comment.

**And "watched" means with eyes, not only with assertions.** While a gate
is being built, its oracle photographs are saved and actually *looked at*
— the red run's screenshots inspected to confirm the picture is wrong in
the way the sabotage intended, the green run's to confirm the picture is
right rather than merely passing. This suite has already been saved twice
by looking where arithmetic had stalled: the blurry-corner investigation
ended the moment the two band photographs were put side by side, and the
frozen-plane bug was an operator's eyes before it was anybody's
assertion. A metric can be satisfied by the wrong picture; an inspected
screenshot cannot. Every new gate's falsification note says what the red
frames showed, not only that the assert fired.

## Stage 4 — the regression floor

The entire existing suite stays green after every step. Any flat test that
has to change to accommodate depth is a design smell to stop on, not to
patch through.

## Stage 5 — measurement (the ladder, real shapes, the T400)

Only after stages 0–4, and separately from them. The ladder grows the
columns the reviews ordered, beside the existing ones:

- **chunk files replaced per landing** and **rehalve milliseconds per
  landing** — the two numbers that catch the plane-loop multipliers;
- **pinned-set bytes per rung**, asserted against the machine's RAM before
  any warm pass;
- **the declared≫imaged parity rung**: the deep rung run twice, declared
  depth equal to imaged and declared far beyond it, and the two rungs'
  landing numbers must match — un-imaged room costs nothing, proven, not
  assumed;
- **the replacement-latency rung**: a whole-position replacement on a
  large t, asserting time-to-first-answered-piece while the patch runs —
  the synchronous-patch decision (shrink it or move the bound) is made
  from this number;
- **the held-volume refetch column** from stage 0, now per rung;
- **the z-halving table**: three arms (never; always; hold-until-isotropic
  -then-halve, pinned per level in the profile), four columns (bake ms per
  landing; bytes per zoom-out; held-volume refetch; and the interop
  afternoon — a halved-z writer pyramid opened in napari and Fiji, the
  reported z scale read back), plus the level-substitution frame that
  checks the halved levels' z offsets, because no cost column can see
  metadata wrong the same way at every level;
- **zero transients at every rung** — a faster number that flickers loses.

## Stage 6 — the bench rung: real Thy1, once, during development

Unchanged in role: not a standing test, joins no suite, run by hand when
the feature is believed done and again only after a rework big enough to
re-open the question. Hands on the workstation, the committed junction
scripts against `Thy1_Mag25x_Ch561.ome.zarr`: the growing one-source
spiral held-view and held-volume; warm-versus-F5 at several planes and
zooms in both postures; the display-window sanity against the specimen's
known range; one long watch with the spiral dripped slowly. Green here,
with the numbers written beside the flat baselines in the MEASURED
document, is the feature's definition of done.
