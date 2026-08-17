# The governed picture grows a z-axis

> Written 2026-08-17, the evening the want was felt at the screen; revised
> the same week after two independent adversarial reviews
> (`REVIEW_the_picture_grows_a_z_axis.md`, `REVIEW_2_…`) filed seventeen
> findings between them, with three severe ones reached independently by
> both. This revision answers every finding — the disposition table at the
> end says which changed the plan and which were refuted, and nothing may
> be built until the instruments this revision orders have run. The
> operator's sentence is unchanged: **"I want 3D to be smooth. It should
> appear properly."**

## The want, and the evening that produced it

A survey was shown growing as **one picture** built from real specimen — 49
blocks of the Thy1 acquisition, each a 1.3 KB description whose pixel folders
are links back to one real tile, so 36 GB of specimen was laid out 49 times
for 195 KB and nothing was copied. The picture was three-dimensional: the
depth slider and the volume view worked, because the transfer door's composer
carries the tiles' full pyramid, depth included, in 32-plane slabs.

It grew, and the growing was **laggy** — and that lag is the transfer door's
contract, not a bug: every re-declaration throws away the server's composer,
and the page's whole-source refresh refetches everything into a server that
has just forgotten everything it knew. The governed door exists so that a
landing costs the change instead; the repository has already decided it is
the one live path. Three-dimensionality therefore belongs **on the governed
picture**, and teaching the transfer door to grow would build the second
live path that decision retired.

We know what smooth growth looks like in 2-D: 196–210 ms landings flat to
4,096 positions, landing-to-visible 90–225 ms, twenty landings a second on
the workstation's real GPU. What the reviews established — and this
revision accepts — is that none of those numbers is evidence about the
volume view, and two of the original plan's premises about depth were
wrong. The bounds this plan promises are therefore conditional until the
instruments below have run, and the acceptance section now says on which
machine its numbers are promised.

## The two premises the reviews broke, and what replaces them

**Broken premise 1: "the client needs nothing."** True in 2-D, where a
whole-source refetch follows the window — a few dozen pieces. False with a
volume view held: its "window" is a whole level of the stack, and by both
reviews' independent arithmetic the refetch bill becomes O(depth) per
landing — on the motivating survey, ~1,700 plane-thin requests (seconds)
per landing at the volume view's level, restarted by every landing, so the
refetch **never converges** under sustained landings. Slab-shaped pieces
trade requests for bytes (hundreds of MB per landing) and tax every 2-D
refetch ×slab-depth; z-halving moves the level, not the bill. No piece
shape rescues the premise.

*What replaces it:* the volume view gets its own refresh budget, measured
before designed. The instrument is nearly free — the existing Thy1
one-source script with the volume view on, one landing announced, the
server counting requests and bytes in the window after it — one evening,
one table cell per (piece shape × rendered level). The mitigation is chosen
from that table, not argued; the candidates, in the order they should be
tried: exempt the held volume layer from the wholesale drop and refresh it
on its own cadence (debounced, latest-wins — the safe pump already knows
how); render the volume from a level whose whole stack is a piece or two
(which is an argument *inside* the z-halving decision, named below, not a
separate free choice); or, if neither converges, an explicit staleness
affordance on the volume panel — honest lateness rather than silent thrash.
Until the mitigation is chosen and gated, the acceptance bound for the
volume view is **suspended** — the flat bound stands, the volume bound is a
measurement in waiting, and the plan no longer promises it.

**Broken premise 2: "composing a slab is built, working code."** The slab
economy (one plane 119 ms, all 32 planes 128 ms) was measured on Thy1's
tiles, which keep 32 planes in one compressed chunk. The governed writer's
own stores compress **every plane separately** (`inner_chunk z=1` at every
level, `zmart_live/profiles.py`); the 32-plane bundle there is the shard, a
packaging of files, not a decompression unit. On a governed store, a
32-plane slab is 32 separate decodes, and every cost estimate the original
plan derived from the slab economy was calibrated against the wrong door.

*What replaces it:* the 119/128 ms experiment re-run on a store the
governed writer actually wrote, before any slab code exists — an hour, and
it decides whether the writer's chunking is on the table. If it is, that
is a format change to every future run with contract and interop
consequences, budgeted openly (the contract pins the profile's chunking);
if it is not, the bake arithmetic below is priced at per-plane decode
honestly. Nothing downstream may assume the slab economy until this number
exists for our own stores.

## What already exists (corrected)

- **The piece address space is already three-dimensional.** Both doors
  answer `level/c/z/y/x`; the governed picture always says z = 0 today.
- **What the z slot MEANS under depth — plane or slab — is an open wire
  decision, stated as such.** The original plan claimed both "nothing about
  the wire changes" and "slab-shaped pieces"; those contradict, and the
  contradiction is retired: piece shape (including shape-per-level — thin
  at fine levels, deep at coarse) is decided by the refetch table from
  broken-premise 1, with the 2-D bill and the volume bill as its two
  columns. Wherever the decision lands, the z slot's meaning must be
  consistent across its three independent readers — the raw baked-file
  path join, the compose-on-request plane argument, and the dirty
  bookkeeping — and a sabotage test (shift the slab key by one) must go
  red at all three.
- **The writer already writes depth** (`z_planes` an ordinary profile
  field; stacks committed whole) — but see broken premise 2 for what its
  chunking means, and finding E for what an *adaptive* depth does.
- **The bake is what makes whole-source refresh converge in 2-D.** That
  sentence survives; its extension to depth is exactly what the ladder
  columns below must earn.

## What has to be built

1. **Declaring the whole room, on every axis, with the per-axis rule for
   unknown extents stated.** The description is written once and never
   moves — that rule stands on two measured failures and is not
   re-litigated. What the reviews forced into the open is the acquisition
   that cannot state its room: the open-ended timelapse has no t extent on
   day zero, and an adaptive-depth run (surface tracking, re-imaging a hit
   deeper) has no single z per position. The rule, per axis: **declare a
   generous ceiling; absence expresses the tail; stopping early is
   ordinary.** That rule is only honest under two conditions this plan now
   owns: un-imaged room must cost nothing per landing (item 2), and the
   contrast window must sample imaged ground, never declared room (the
   standing gate in item 5). The writer's refusal of a commit beyond the
   declared room stays, and stays loud, with the remedy named in its
   message: a new acquisition, priced as a cold open — never a silent
   re-declare. One stage-1 gate pins the whole posture: declare a
   ceiling-shaped room, land less than it, and show the description never
   moved and the landing costs never noticed the ceiling.
   (The same collision for t is recorded in
   `PLAN_the_picture_grows_c_and_t.md`, which inherits this rule.)

2. **The bake patches at slab granularity, and the shipped plane loops are
   the work, not bookkeeping.** The original "×10" was wrong; the shipped
   patcher multiplies by *plane count* in three places — the per-commit
   patch recomposes and atomically replaces every plane of a dirty column,
   the extended-level re-halve walks the full **declared** depth (the
   pyramid extension halves y and x only), and slab inheritance is keyed
   without the slab index, so one touched slab evicts the warmth of its
   whole column. Un-fixed, "×10" ships as ×291 — and a generously declared
   room makes the hot path walk planes nobody will ever image, the
   O(survey)-shaped term the flat campaign spent itself shedding. So the
   dirty footprint is **one named shape, (level, slab, row, column), defined
   once and used by all three consumers** (inheritance, index, patcher);
   the patcher skips slabs that intersect no planned tile; and the
   instrument comes first: two new ladder columns (chunk files replaced
   per landing; rehalve milliseconds per landing), the deep rung run twice
   — declared depth = imaged, and declared ≫ imaged — with the second
   required to match the first before any of this is believed.

3. **The synchronous patch inside landing-to-visible either shrinks or the
   bound moves — measured, then chosen.** Governed requests derive with
   the bake patch inside the derive; the flat picture affords that at
   60–90 ms. Depth multiplies it (item 2), and a whole-position
   replacement on a long timelapse patches O(moments) synchronously while
   requests wait. The candidates: per-slab dirty granularity making the
   synchronous patch small again; or lazy slab patching behind
   compose-on-request (answer fresh now, bake behind). The ladder's deep
   bake column plus one replacement-on-large-t rung — asserting
   time-to-first-answered-piece during the patch — decides; the acceptance
   bound is not promised for depth until it does.

4. **Slab naming stays inside the server.** Dirty pieces named
   (level, slab, row, column) have exactly one consumer: the derive-to-bake
   path. The wire keeps its one word (`wrote_image_in_place`) — the decided
   whole-source client reads no piece names, the ladder that did is
   deprecated, and this suite's costliest evening was one wrong word at
   exactly that boundary. No z vocabulary is added to the wire.

5. **Two standing gates the reviews showed were missing.**
   - **The contrast window samples imaged ground** — asserted against
     ground truth on synthetic stamped tiles, in seconds, as a stage-1
     gate. Warm-versus-fresh cannot catch it: a window wrong the same way
     in both screenshots passes every census, which is exactly why it must
     be its own gate and not a bench note.
   - **The ragged edge exists in every fixture.** Synthetic depths must
     include one that is odd and *not* a multiple of the slab (13 planes
     with an 8-plane slab names both the rounding seam and the final
     partial slab); even-only fixtures let a last-plane-blank off-by-one
     pass every voxel comparison.

## The z-halving decision, restated so it can actually be decided

The binary switch was a false dichotomy — and the resolution is not to
pick a winner but to make the pyramid's shape a fact of the data. **Both
shapes are first-class, forever: a pyramid that shrinks only y and x, and
one that shrinks z too.** Which one a given acquisition gets depends on
what was acquired — a thin stack or a 2-D-ish survey shrinks x/y only; a
true volume earns z-halving — and Thy1 itself uses the mixed form: it
**holds depth for three levels** (its z voxel being ~6× coarser than x/y)
**and then halves**. The profile already has the vocabulary: a per-level
`downsampling` map with a z entry, declared per acquisition, pinned at
sealing. Every consumer — composer, patcher, gateway, declared metadata —
reads that map and assumes nothing; a hard-coded "z never shrinks" or "z
always halves" anywhere in the chain is a bug by definition, and the gates
run every correctness stage on BOTH shapes so neither can rot as the
untested one.

What remains to *decide* is only the recommendation — which shape the
controller should choose per data shape by default — and that is the
experiment's job, with three arms (never halve; halve always;
hold-until-isotropic-then-halve) and four columns: bake milliseconds per
landing, bytes fetched per zoom-out, **the held-volume refetch bill** (the
column that dominates, per broken premise 1), and one interop afternoon —
open a halved-z pyramid the writer produced in napari and Fiji and read
back the z scale they report. Two seams must be pinned before the
experiment exists: the rounding rule is **ceiling**, held by a geometry
test across the three call sites that today disagree (the gateway floors
where the frame and the pyramid extension ceiling — invisible while z-depth
divisors are 1, one plane of skew the day they are not); and the halved
levels' z *translation offsets* follow the same averaging the y/x fix
already does, checked by a level-substitution frame in the volume view,
because neither cost column can see metadata that is wrong the same way at
every level. The arms produce incompatible on-disk declarations; the
regression suite must be told which arm a fixture was declared under.

## The bake dial, resized for depth

The flat picture's dial ran from "bake nothing, pin the coarse levels in
memory" to "bake the pinned share". In depth the cheap end is not a dial
position: the pinned set is geometric (a share of the picture) and a deep
picture is terabytes, so the same share is **an out-of-memory** —
order 18–20 GB unevictable at 4,096 deep positions un-halved, ~8 GB halved,
on a 31 GB machine that also wants a block cache, a slab cache, and a
browser. Aggravations the code already contains: declared-empty ground pins
as real zeros, and the baked settings read baked slabs straight back into
the same pin, so the dial moves where pins come *from*, not their size. So:
**the pin budget becomes an absolute byte bound, not a share**, sized per
machine; the pinned-set bytes are pure profile arithmetic printed by the
ladder per rung and asserted against the machine's RAM before any warm pass
runs (ten lines, red on day one); and the deep dial runs from "bake the
coarsest levels" outward, with in-memory pinning as garnish under the byte
bound, never the load-bearing tier. Full resolution is never baked on the
live path — *until a view is deliberately materialized*, which is the
contract's named escape hatch for a picture that must outlive its
positions' availability, and this plan does not forbid it.

## The tests come bake-free, and the bake comes last (with the door held honest)

The correctness gates for depth stay bake-free: tiny synthetic tiles
compose in microseconds, and a bake inside those tests would only add
moving parts. Two corrections from the reviews: **the gates' fixtures are
governed runs, committed through `zmart_live`** — the growth machinery of
the transfer door (re-declare and rebuild) must not appear in any stage-3
fixture, because it greens gates on machinery the plan forbids from
growing while the governed path ships untested; and **one browser gate
runs with the bake ON**, proven red by the shifted-slab-key sabotage,
because the baked-file short-circuit is a third independent reader of the
z slot and bake-free gates pass a plane-vs-slab mismatch by construction.
The four-square grid from the (t, c) plan — held view and scrolling, each
before and after F5 — applies to every browser gate here, and one storm
variant runs **with the volume view held** at a realistic depth, because
that is the failure mode both reviews rank first and no drafted gate met.

## The brightness observation gets a discriminating instrument

The FAULTS.md observation (volume view brighter warm than after reload)
gets its gate, built to *name* the mechanism, not just ring: mean
brightness sampled **during** a burst of landings (the transient twin is
reaped by quiet-time, so a settle-then-measure census can miss it), the
comparison two-sided (a warm page too bright must fail — the one-sided
pattern in the existing held-view gate would pass it), and beside the
brightness two cheap reads that discriminate: the engine's managed-layer
count (a lingering twin is a countable second layer) and the applied
display window as JSON, warm against fresh. A red then arrives with its
mechanism attached.

## How we will know it is done

On the 24-core / 31 GB workstation with the T400 — the machine every number
here was measured on, now said out loud:

- a landing into a deep survey is visible **in the flat view** within the
  flat picture's own bound (90–225 ms), the cost following the change;
  ladder-proven with the new columns (files replaced, rehalve ms, pinned
  bytes, declared≫imaged parity);
- **the volume view converges under sustained landings** with its chosen
  mitigation, storm-variant-proven — or, if the measured table says the
  budget cannot be met, the volume panel says so honestly on screen, and
  that affordance is itself gated;
- **zero transients** on any plane, held and scrolling, before and after
  F5;
- **warm equals reload** at several zoom bands AND several planes, both
  postures, under the fully-loaded census rule;
- the storm rate holds in the flat view at depth; the volume-view rate is
  whatever its measured budget says, written in the table, not assumed.

## Disposition of the seventeen findings

| Finding (R1 = first review, R2 = second) | Disposition |
| --- | --- |
| R1F1 + R2F1 held-volume convergence (severe, independent) | Accepted; premise retracted, volume refresh budget + instrument + mitigation ladder added; volume acceptance bound suspended until measured |
| R1F2 + R2F2 wire contradiction / slab economy absent (severe) | Accepted; contradiction retired, piece shape an open wire decision with the refetch table deciding; 119/128 re-measurement on governed stores ordered first |
| R1F3 + R2F3 RAM pin (severe, independent) | Accepted; share becomes absolute byte bound, pin demoted to garnish, ten-line instrument red on day one; materializing named as the L0 escape hatch |
| R1F5 + R2F4 plane-loop multipliers, declared-deep cost, synchronous patch (severe) | Accepted; one named dirty shape for three consumers, skip-unplanned-slabs, two ladder columns + declared≫imaged parity rung + replacement-latency rung; bound not promised until they run |
| R1F4 + R2F5 declared room vs real acquisitions (moderate, independent) | Accepted; per-axis ceiling rule stated with its two honesty conditions, loud refusal with named remedy, stage-1 ceiling gate; t recorded in the c-and-t plan |
| R1F6 + R2F6 z-halving experiment (moderate) | Accepted; per-level profile decision, third (anisotropy) arm, held-volume column, ceiling rounding pinned by geometry test, interop afternoon, metadata level-substitution check |
| R1F7 + R2F7 gates certify wrong door / three faults pass (moderate) | Accepted; governed fixtures mandatory, one bake-ON gate with sabotage red, window-sanity standing gate, ragged-depth fixture rule, volume-view storm variant |
| R1F8 + R2F8 brightness instrument (moderate) | Accepted; during-burst sampling, two-sided comparison, layer-count and window reads discriminate the mechanism |
| R2F9 wire vocabulary (minor) | Accepted; slab naming stays server-internal, wire keeps its one word |
| Wording notes (both) | Accepted; Thy1 holds-then-halves stated correctly, one named dirty shape, acceptance machine named |

Nothing was refuted. Two reviews, blind to each other, converged on the
same three severe findings; a plan that argued with that would be arguing
with arithmetic.

## What is deliberately not in this plan

- No named/dirty-piece invalidation on the client — whole-source
  invalidation is the decided default; the volume view's mitigation, if it
  exempts the volume layer from the wholesale drop, is a refresh-cadence
  choice inside that default, not a return of the ladder.
- No growing pictures on the transfer door.
- No linking of foreign pyramids — measured impossible for Thy1-shaped
  data, and the reason is recorded rather than just the verdict.
