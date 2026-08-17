# Review 2: the picture grows a z-axis

> An independent review of `PLAN_the_picture_grows_a_z_axis.md` and its test
> plan, written 2026-08-17 against the code on this branch and the measured
> records in this folder, without reading the first review. Findings are
> numbered, most severe first. For each one: the claim it attacks, what can
> be shown (with the file and line, or the arithmetic) against what is only
> suspected, and the cheapest instrument that would settle it.

**Verdict in one line:** the plan's machinery list is right but two of its
premises are wrong — the slab economy it inherits from the transfer door does
not exist in the governed writer's own stores, and the held volume view makes
the whole-source refetch bill O(depth) per landing — and until both are
measured, the acceptance bound (a landing visible in 90–225 ms with the
volume view in use) is a hope, not a plan.

---

## Finding 1 — the held volume view breaks the convergence premise, by arithmetic (severe)

**Attacks:** "The client needs nothing — but only because the bake exists"
(plan, *What already exists*), and the acceptance criterion "with the depth
slider **and the volume view in use** … a landing is visible within the flat
picture's own bound (90–225 ms)".

**What can be shown.** Whole-source invalidation drops everything the page
has decoded and refetches what is on screen (`frontend/src/engine.js`,
`letGoOfDecodedPieces`, with its own comment: the refetch bill "follows the
size of the window"). That comment is true for a flat view — a screenful is
a few dozen pieces. It stops being true the moment a volume view is held,
because a volume view's "window" is a whole level of the stack.

The served picture's wire pieces are one plane deep — `chunk_shape
[1, piece, piece]` (`composer.py:985-986`). Take the plan's own motivating
survey: 49 Thy1 blocks of 1264 × 1480 × 291 voxels at ~10 % overlap, a
picture of roughly 8,000 × 9,400 × 291. Suppose the volume view is rendering
from level 3 (each level quarters y and x): about 1,000 × 1,180, which is a
2 × 3 grid of 512-pixel pieces — six piece columns, times **291 planes =
1,746 chunks**. One landing, one whole-source refresh, 1,746 HTTP requests.
Even at one millisecond per served piece — baked files, localhost — that is
~1.7 s, seven times the 225 ms bound; at the storm gate's twenty landings a
second the refetch window is 50 ms and the refetch **never converges**. That
is exactly the whole-picture-granularity thrash the plan describes on the
transfer door, reproduced on the governed door by the volume view. Even the
coarsest tile level (~500 × 590, two piece columns) is 582 chunks per
landing.

Making the pieces slab-shaped, as plan item 1 proposes, trades requests for
bytes and taxes the other view: a 32 × 512 × 512 piece is 16.8 MB decoded, a
few MB on the wire, so the level-3 volume refetch becomes 60 requests but
~200–500 MB per landing — and every **2-D** plane refetch now pays 32× the
bytes for ground it will draw one plane of, at every landing, forever.

**What is suspected.** The bound can only survive if the volume view renders
from a level whose whole stack is a piece or two — which is the plan's own
argument *for* z-halving ("the whole depth at a glance becomes cheap exactly
where the volume view … needs it"). In other words: the acceptance criterion
quietly decides the z-halving question the plan declares open, and also
decides the wire-piece shape the plan treats as a free starting choice.
Neither dependency is named anywhere in the plan.

**Cheapest instrument.** Before building anything: a server-side counter of
requests and bytes served in the window after one announcement, run on the
existing Thy1 one-source script with the volume view toggled on. One evening,
no new machinery, and it turns "plausibly survives" into a number per
(piece shape × level rendered) cell.

## Finding 2 — the slab economy the plan inherits does not exist in the governed writer's stores (severe)

**Attacks:** "Composing a slab is built, working code" and "less is missing
than it feels" (plan, *What already exists*).

**What can be shown.** The slab economy's measurement — read one plane
119 ms, all 32 planes 128 ms, "a thirtyfold saving" (`composer.py:14-19`) —
was made on the Thy1 transfer, whose tiles keep **32 planes in one
compressed chunk** (`composer.py:76`). The governed writer's stores do not:
`plan_the_writing` fixes `inner_chunk={"z": 1, …}` at every level
(`zmart_live/profiles.py:783-786`) — every plane is compressed separately,
and the 32-ish-plane "slab" there is the *shard*, a bundling of files, not a
decompression unit. `TheWorldFrame.slab_depths` reads exactly that inner
chunk (`governed.py:307-316`), so on a governed run the composer's slab is
**one plane deep** and the "next 31 requests already answered" economy the
plan builds its bake arithmetic on simply is not there: a 32-plane slab
piece of a governed picture is 32 separate chunk decodes (each through the
shard resolver's presence check, `composer.py:501`), not one.

**What is suspected.** Either the writer's chunking changes (a format change
to every future run, with interop and contract consequences the plan never
budgets — the contract pins "the profile's chunking and encoding",
`CONTRACT_the_files_the_viewer_needs.md`), or the plan's per-landing bake
multiplier and its cold-open estimates are computed from a saving that the
governed door does not get. Either way, item 2's cost model is currently
calibrated against the wrong door.

**Cheapest instrument.** Re-run the one-plane-versus-whole-slab read
measurement (the 119/128 ms experiment) on a store the governed writer
actually wrote, before any slab code is written. An hour's work; it decides
whether the writer's chunking is on the table.

## Finding 3 — "bake nothing, pin the coarse levels in memory" is an out-of-memory, not a dial position (severe)

**Attacks:** the bake dial's cheap end (plan, *The tests come bake-free…*
disk-bill paragraph).

**What can be shown.** Pinned slabs are held decoded and are deliberately
unevictable — "held apart from the byte bound above so nothing can ever
evict them … bounded by geometry instead" (`composer.py:211-215`). That
geometric bound is a *fraction of the picture*, and in depth the picture is
terabytes. Arithmetic: 4,096 Thy1-shaped positions ≈ 1264 × 1480 × 291 × 2
bytes ≈ 1.09 GB each; with overlap the full-resolution picture is ~3.5–4 TB.
Without z-halving, levels quarter, so the pinned set (every level holding
≤ 1 % of full-resolution voxels, `PINNED_SHARE`, `composer.py:120`) sums to
roughly 0.5 % of the picture — **on the order of 18–20 GB of unevictable
decoded RAM**. With z-halving it is ~0.2 %, still ~8 GB. The machine the pin
budget was reasoned on has 31 GB, and even there the comment beside the
1 GB block budget already warns "a number to lower on a smaller machine
rather than a constant of nature" (`composer.py:98-101`); the pin has no
number at all, only geometry, and in depth the geometry is the wrong bound.
"Minutes at ten thousand positions" for the cold re-warm is also computed
without finding 2: with one-plane chunks the warm pays a decode per plane,
not per slab.

**On the other end** ("never bake L0"): the plan should name the case the
contract already names — a finished run whose picture must outlive its
positions' availability (data/ archived to tape, or the demo's junction
stores whose 49 blocks all resolve to one real tile that can move). The
contract's answer is the explicit third gesture, *materializing*
(`CONTRACT_the_files_the_viewer_needs.md`, "Sealing… materialized"). "L0 is
links or on-request, always" is right for the live path and wrong as an
absolute; the plan should say "always, until a view is deliberately
materialized" so nobody reads it as forbidding the escape hatch.

**Cheapest instrument.** The pinned-set size is pure arithmetic from the
profile — a ten-line calculation printed by the ladder harness per rung,
asserted against the machine's RAM before any warm pass starts.

## Finding 4 — the plan's "×10" bake multiplier is wrong as stated; the true multipliers are ×deep and ×declared-deep (severe)

**Attacks:** plan item 2, "the per-landing bake cost multiplies by roughly
the slab count — ten at 291 planes", and item 1's "ground not yet imaged is
expressed by absence" as if absence were free.

**What can be shown.** Three loops in the shipped patcher multiply by
*plane count*, not slab count:

- The per-commit patch recomposes every plane of a dirty column:
  `deep = made.grid(level)[0]; for plane in range(deep): _replace_one_piece`
  (`governed.py:783-787`). At 291 planes that is 291 encodes and 291 atomic
  file replaces per dirty (row, column) per baked level — the flat picture's
  measured 3–10 ms of encode per landing becomes seconds, and the file
  replaces alone are hundreds of `os.replace` calls inside
  landing-to-visible.
- The extended-level re-halve walks every plane too, both the staged-move
  loop (`governed.py:977-987`) and the direct path
  (`for plane in range(deep)`, `governed.py:1059`) — and the extended levels
  keep the **full declared depth**, because the pyramid extension halves y
  and x only (`declare.py:389-395`).
- Slab inheritance is keyed by (row, column) with the slab index discarded
  (`level, _, row, column = key; if (row, column) in dirty…`,
  `composer.py:326`), so a landing that touched one 32-plane slab evicts the
  warmth of **every** slab in that column, and the next request pays to
  rebuild all of them.

Now combine with item 1's declared room. The standing advice is to declare
generously — "size the canvas … to the stage's whole travel range"
(`measure_declared_room.py`, module docstring), measured free *on disk*. In
the patcher it is not free: a room declared 1,000 planes deep with 32 imaged
makes every one of the loops above walk ~1,000 planes per dirty column per
landing (a zero-slab build, an `.any()` scan and a stat each) — cost
proportional to ground that will never be imaged, on the hot path, at every
landing, which is precisely the O(survey)-shaped term the flat picture spent
a campaign shedding.

**What is suspected.** The fix is probably cheap — dirty footprints named as
(level, slab, row, column) end-to-end, and the patcher skipping slabs that
intersect no planned tile — but the plan's item 3 currently calls this
"bookkeeping, not new truth", and the three loops above are exactly where
the bookkeeping has to land or the ×10 claim ships as ×291.

**Cheapest instrument.** The plan already says ladder-first; add two columns
now — chunk files replaced per landing, and rehalve milliseconds per landing
— and run the deep rung twice, once with declared depth = imaged depth and
once with declared depth ≫ imaged, before the patcher is touched.

## Finding 5 — the declared room breaks on real acquisitions, and the plan should say what happens then (moderate)

**Attacks:** plan item 1, "the profile already says how many channels and
timepoints the acquisition will have, so the picture is declared over its
full (t, c, z, y, x) room on day zero".

**What can be shown.** Two acquisitions this repository explicitly serves
cannot state that room at declare time. First, the open-ended timelapse:
"image every ten minutes until the response ends" has no `t` extent on day
zero, and the profile has nowhere to put "unknown". Second, adaptive depth:
`frame_shape` holds **one** z for every position of the run
(`zmart_live/profiles.py:805`), so a run whose stacks track a tilted or
thickening specimen — autofocus choosing the surface per position, the
smart-microscopy loop re-imaging a hit deeper — either lies (declares the
ceiling, images less) or cannot be declared at all. The declare-don't-grow
rule itself stands on two measured failures and is not being re-litigated;
what is missing is the plan's answer for these runs.

**What is suspected.** The honest answers are (a) declare a generous ceiling
and let absence carry the rest — which is only viable once finding 4 makes
un-imaged depth cost nothing per landing, and once the contrast window
samples imaged ground (the plan's own trap #1); or (b) re-declare as a new
picture, which today means a reload and a cold open, priced honestly. The
plan should pick and write down the rule per axis; today it asserts the
premise "by definition" and moves on.

**Cheapest instrument.** None needed — this is a decision, not a
measurement. One paragraph in the plan naming the rule for an unknown
extent, per axis, and one stage-1 gate that declares a ceiling-shaped room,
lands less than it, and shows the description never moved.

## Finding 6 — the z-halving experiment as described cannot decide the question (moderate)

**Attacks:** plan trap #2, "*The deciding experiment*: … bake milliseconds
per landing against bytes-fetched-per-zoom-out … read the answer off the
table."

**What can be shown, in four parts.**

- **The binary switch is a false dichotomy.** Thy1 itself neither always
  halves nor never halves: it "leaves depth alone for three levels, its
  voxels being 1 micrometre deep against 0.17 across" (`composer.py:928`) —
  the anisotropy-aware rule, hold z until its voxel is no longer the coarse
  one, then halve. A switch offering only "every level" and "never" cannot
  land on the shape the acquisitions this viewer exists for actually use.
  And the vocabulary for the right answer already exists: the profile
  carries a **per-level** `downsampling` map with a z entry
  (`zmart_live/profiles.py:782`) — the decision belongs there, pinned per
  profile, not in a global switch.
- **The rounding rule is already inconsistent in shipped code.** The gateway
  computes level depth by floor division (`frame_shape.get("z", 1) // by_z`,
  `zmart_live/gateway.py:332` and `:371`), while the world frame ceilings
  (`-(-int(edge) // int(down))`, `governed.py:291`) and the pyramid
  extension ceilings (`-(-height // 2)`, `declare.py:389`). Today `by_z` is
  always 1 and the disagreement is invisible; the day it is 2, an odd depth
  (291 → 146 by ceiling, 145 by floor) makes the view-route validation and
  the served frame disagree by one plane, and the last plane of every odd
  level is either unreachable or unvalidatable. The writer must pin one
  rule (Thy1's own files say ceiling) and a stage-1 geometry test must hold
  all three call sites to it.
- **Interop is asserted, not measured.** "Interop reads it natively" is
  probably true and costs one afternoon to show: open a halved-z pyramid the
  writer produced in napari and Fiji, and read the z scale it reports back.
- **The experiment's two columns are not the whole bill.** Finding 1 shows
  the held-volume refetch-convergence column depends on the halving choice
  more strongly than either column the plan names; without it the table can
  crown the loser.

**Cheapest instrument.** Add the held-volume refetch column (finding 1's
counter) to the deciding table, run the interop afternoon once, and write
the rounding assertion before the switch exists.

## Finding 7 — three faults pass every gate in the test plan and reach the operator (moderate)

**Attacks:** the test plan's stages 1–5 as a complete net.

- **Warm-versus-fresh is blind to symmetric faults.** Every stage-3 census
  compares the held page against a reload; a fault that wrongs both
  identically passes. The plan's own trap #1 is exactly such a fault: a
  contrast window sampled from declared emptiness is the same useless
  window warm and fresh, so the operator gets a picture with "no usable
  range at all" (`measure_declared_room.py`) while every census in stages
  1–5 stays green — the only check is stage 6, run once, by hand, on one
  acquisition. The window sanity ("the window must describe imaged ground,
  not declared room") is testable on synthetic stamped tiles in seconds and
  should be a standing stage-1/2 gate, not a bench note.
- **The synthetic depths never exercise a ragged edge.** "Eight to
  thirty-two planes" (test plan, stage heading *The two kinds of data*) are
  all even and all likely multiples of the slab depth, so the final
  *partial* slab — where the ceiling-versus-floor seam of finding 6 and
  every clamp in `_build_slab` (`composer.py:571`, `high_z = min(low_z +
  depth, deep)`) actually bite — is never built. A last-plane-blank
  off-by-one passes every voxel comparison. The fixture rule should demand
  a depth that is odd and *not* a multiple of the slab (13 planes with an
  8-plane slab names both bugs), alongside the middle-slab discipline the
  plan already has.
- **No gate runs landing rate with the volume view held.** Stage 3's volume
  gate lands single blocks on tiles that compose in microseconds; stage 5's
  ladder harness holds a flat browser view (no volume view appears anywhere
  in `measure_a_ladder_of_surveys.py`); stage 6 drips the spiral slowly.
  Finding 1's failure mode — the refetch that never converges under
  sustained landings with the volume view on — passes every listed gate and
  is met for the first time by an operator. The storm gate needs a
  volume-view variant at a realistic depth, or the acceptance bullet about
  the volume view is uninstrumented.

**Cheapest instrument.** All three are additions to planned gates, not new
machinery: one synthetic window-sanity assertion, one fixture-depth rule,
one storm variant with the volume panel on.

## Finding 8 — the brightness instrument detects, but cannot discriminate — and may not even detect the likelier mechanism (moderate)

**Attacks:** the claim that the held-volume gate "is also the instrument
that decides the open FAULTS observation".

**What can be shown.** The two candidate mechanisms (FAULTS.md, tail) leave
the same fingerprint the instrument reads — warm mean brightness ≠ fresh —
so a red tells you *that* one happened, never *which*. Worse, the twin
double-draw candidate is transient by design ("draws the elder layer and
its replacement together **for a moment**"), and the census discipline this
suite learned on the storm gate is to wait for the engine's own
fully-loaded word before measuring — by which time a lingering twin has
been reaped and the gate is green while the operator's storm-time
observation stays real. And the existing held-view gate's assertion is
one-sided (`warm_lit >= fresh_lit - 0.02`,
`test_a_built_picture_grows_while_watched.py:157`) — a pattern that, if
copied, passes a *too-bright* warm page, which is the very direction
observed.

**What is suspected / the cheaper instrument.** Both mechanisms have direct,
cheap probes the gate should read alongside brightness: the number of
managed layers in the engine (a lingering twin is a countable second
layer), and the volume display window the engine is actually applying
(readable from its state, comparable warm against fresh as JSON). Sample
mean brightness *during* a burst of landings, not after quiet; make the
brightness comparison two-sided; and record layer count and window at the
moment of any red. Then a red names its mechanism instead of opening a
second investigation.

## Finding 9 — "the announcements carry z" builds vocabulary the decided client will never read (minor)

**Attacks:** plan item 3.

**What can be shown.** The page's announcement is one word with no piece
names in it (`{"wrote_image_in_place": true}`, `backend/server.py:885-899`),
and whole-source invalidation — the decided default, not re-litigated here —
ignores dirty-piece naming entirely; the named ladder that consumed it is
deprecated and scheduled for deletion (`PLAN_close_the_neuroglancer_chapter.md`,
step 4). Dirty pieces named (level, slab, row, column) are needed by exactly
one consumer: the server's own derive-to-bake path. Calling that an
"announcement" plants z-carrying words at the wire boundary where nothing
reads them — and this suite's costliest evening was one wrong word at
exactly that boundary. Keep the slab naming internal to the derive, and
leave the wire vocabulary untouched and sabotage-tested as it already is.

---

## Wording and structure notes

- The plan says Thy1 "halves depth as it coarsens (291 → 146 → 73 → 37)";
  `composer.py:928` records that it holds depth for three levels first. Both
  are true of different parts of the pyramid — the plan's sentence should
  not read as "every level halves", since that framing is what makes the
  switch look binary (finding 6).
- "Slabs × rows × columns" is used both for the dirty footprint (item 2) and
  for what the announcements carry (item 3); after finding 4 these should be
  one named shape, defined once, so the three consumers (inherit, index,
  patcher) cannot drift.
- The acceptance section should state *which machine and RAM* its bounds are
  promised on; every number it cites was measured on the 24-core/31 GB
  workstation, and findings 1 and 3 both turn on smaller machines.
