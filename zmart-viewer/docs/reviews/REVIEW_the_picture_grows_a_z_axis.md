# Review findings: the picture grows a z-axis

> One external reviewer (Claude, general-purpose agent), 2026-08-17, against
> `docs/reviews/REVIEW_PROMPT_the_picture_grows_a_z_axis.md` at commit `524047e8`. The
> reviewer read the plan, the test plan, the gate, the chapter plan, the
> FAULTS tail, and chased claims into `composer.py`, `served.py`,
> `governed.py`, `engine.js` and `zmart_live/coordinator.py`. Findings
> verbatim, most severe first. A second, independent review has not yet run;
> nothing here has been re-verified or acted on.

**Finding 1 — The convergence premise does not survive a held volume view,
and no piece shape or z-halving choice rescues it. (Claim 2. Shown by
arithmetic.)**

The flat picture's refetch bill after `letGoOfDecodedPieces` follows the
window, not the specimen — true only in 2-D. A volume view's "what is on
screen" is the GPU-resident brick set for the whole visible volume. At 4,096
Thy1-shaped positions the volume view's resident level is ~272 MB; with
today's plane-thin wire pieces that is ~1,164 pieces ≈ 4.7 s of warm server
work plus 1,164 round trips plus ~272 MB of browser decode per announcement.
Slab pieces cut the request count, not the bytes; z-halving moves the level,
not the bill. Against gaps of 50 ms (20/s) to 1,000 ms (1/s), the refetch
exceeds the gap by 5–100× at every realistic setting, and whole-source
invalidation restarts it every landing — the held volume view never converges
while the survey grows. The T400 whole-source certification was flat-only and
is not evidence here. The plan ships a 3-D mode in which the decided default
provably cannot converge, and neither names it nor budgets a mitigation
(debounce while a volume view is held; exempt the volume layer from the
wholesale drop; or display volume staleness with an explicit refresh
affordance).

*Cheapest instrument:* zero new code — `show_thy1_one_source.py` with the
volume view on, land one block, read the network log. Then a "held-volume
refetch" column on the ladder; the acceptance section has no such column.

**Finding 2 — "Slab-shaped pieces" changes the wire contract, contradicts the
plan's own premise, and the shape dilemma is never named. (Claims 2, 5, 6.
Shown.)**

The plan asserts both "nothing about the wire format changes" and "declares
slab-shaped pieces". These contradict: the transfer door's declared chunk
shape is `[1, piece, piece]` (`composer.py:986`); the 32-plane slab is a
server-side cache unit, not the wire. Plane-thin wire pieces give the volume
view an O(depth) request bill; 32-deep pieces inflate every 2-D refetch ×32
(~270 MB raw per whole-source refresh at a screenful) — the flat
landing-to-visible bound then carries the depth tax in the certified mode. The
unmentioned third option is chunk shape per level (thin at fine levels, deep
at coarse). Either way the five-part address's z slot changes meaning (slab
index vs plane index) across `served.py:363` (raw path join) and
`served.py:380` (plane argument) — the one-wrong-word seam class again.

*Cheapest instrument:* state piece shape (or shape-per-level) as an explicit
open decision with the 2-D and volume refetch bills as its deciding columns —
one table on the existing Thy1 scripts.

**Finding 3 — "Bake nothing, RAM-pin the coarse levels" pins ~23 GB at 4,096
deep positions; the RAM term is common to every dial setting and was sized
flat. (Claim 4. Shown by arithmetic.)**

`PINNED_SHARE = 0.01` pins levels holding ≤1% of full-res voxels,
unevictable. Flat, that is ~80 MB at 4,096 positions; deep (z never halved),
the pinned sum is ~0.52% of 2.23×10¹² voxels × 2 B ≈ **23 GB** — on the 31 GB
workstation the budget was sized on, before the 1 GB block cache, the slab
cache, and a browser holding ~1 GB of volume. Aggravations: empty declared
ground pins as real zeros (`composer.py:578`, `713-726`); the baked settings
read baked slabs straight back into the same pin (`composer.py:804-815`), so
the dial changes where pins come *from*, not their size — the plan's ordered
ladder measurement (compose vs cold-open time) can never see this failure;
and the guard is a share where the machine's limit is absolute.

*Cheapest instrument:* ten lines in `measure_declared_room.py` printing the
pinned-levels byte total; red on day one.

**Finding 4 — The declared room turns an unknown duration or depth envelope
into a refused commit mid-acquisition, and the plan says nothing about it.
(Claim 1. Shown.)**

The writer refuses a commit beyond the declared timepoints
(`zmart_live/coordinator.py:547-549` — "This run was set up for {N}
moment(s)"): an open-ended timelapse under-declared loses data while the
sample is alive. A z-following acquisition (surface tracking, adaptive
stacks) has nowhere to land outside the profiled z envelope. The plan answers
only ground-not-yet-imaged ("absence"); ground the profile did not anticipate
has two honest answers — declare the envelope generously (then own Finding
3's RAM, the tall-thin window, and the empty-slider UI), or state the
fail-closed wall loudly with an operator recovery that is not a banned
re-declare — and the plan gives neither.

*Cheapest instrument:* none needed; `coordinator.py:547` is the evidence. A
paragraph in the plan plus one gateway test that the refusal is loud and
names the remedy.

**Finding 5 — The ×10 slab bake sits inside the serving path, so the
acceptance bound is arithmetically falsified before anything is measured; the
O(moments) replacement is unbounded per commit. (Claim 5. Shown for the
mechanism; the constant suspected.)**

Governed piece requests derive synchronously with the bake patch inside the
derive (`served.py:347-356`, `governed.py:580-585`). Warm per-commit patching
measured 60–90 ms flat; ×10 slabs = 0.6–0.9 s inside landing-to-visible,
against an acceptance bound of 90–225 ms promised unconditionally. One must
yield: name the mitigation (lazy/async slab patching behind
compose-on-request; per-slab dirty granularity) or widen the bound. A
whole-position replacement on 1,000 moments patches minutes of pieces
synchronously while every request 503s; the test plan pins the spike's size
but nothing bounds its latency. The moved-frame path (D6) deep means the full
pinned share recomposed. (The announcement payload is clean — one boolean,
constant.)

*Cheapest instrument:* the deep bake column already ordered, plus one
replacement-on-large-t rung asserting time-to-first-answered-piece during the
patch.

**Finding 6 — The z-halving experiment as described cannot decide the
question. (Claim 3. Shown for what is missing; interop suspected.)**

Its two columns (bake ms per landing; bytes per zoom-out) miss the binding
constraints: (1) the held-volume refetch bill (Finding 1) differs by orders
of magnitude in request count across the switch; (2) the rounding rule —
291→146 is ceiling; the writer must pin one, and no interop evidence exists
for what napari/Fiji assume; (3) the metadata half — `group_json` offsets
averaged levels' translations per halved axis (`composer.py:946-949`, the
top-left-twitch fix); halve z and z needs that offset, and neither column
would catch a switch that flips the bake but not the metadata — only a
level-substitution frame in the volume view would; (4) the false dichotomy —
Thy1's z voxel is ~6× coarser than x/y, and the standard option "halve z only
once z-spacing ≤ xy-spacing" is on neither arm; (5) blast radius — halving
changes declared per-level shapes, so the two arms are incompatible on-disk
declarations coexisting; the regression floor should be told.

*Cheapest instrument:* three added columns (held-volume refetch; a napari/
Fiji open of a halved writer pyramid; a both-ways rounding assert) and the
isotropy option as a third arm.

**Finding 7 — Stage 3 certifies the wrong door; the baked slab door never
sits under any correctness gate. (Claim 6. Shown.)**

The stage-3 pattern's fixture drives the transfer door (re-declare + mtime
mark + full rebuild); the shipped path is governed (fingerprint → derive →
dirtied → inheritance → synchronous patch), whose nudge path
`catch_up_governed_runs` is a no-op for built pictures. Grown as written,
every stage-3 gate greens on machinery the plan forbids from growing, while
the governed depth path reaches the operator browser-untested. Second seam:
the correctness gates are bake-free forever, but the baked-file short-circuit
(`served.py:363`, raw join of the z slot) is a third, independent place the
plane-vs-slab meaning is decided — a mismatch passes every bake-free gate by
construction and ships as intermittent off-by-slab staleness. Third: the
tall-thin contrast trap has no gate before the one-time stage 6, and
warm-vs-fresh cannot see a window that is wrong the same way in both
screenshots.

*Cheapest instruments:* one sentence — "stage 3 fixtures are a governed run,
committed through zmart_live"; one browser gate with the bake ON, its red
from the shifted-slab-key sabotage; one synthetic fixture with a generous
declared z whose window assertion is against ground truth.

**Finding 8 — The held-volume brightness gate detects that something
happened, not which mechanism, and will also produce false reds. (Claim 7.
Shown by construction.)**

Both candidate mechanisms move mean brightness the same way; a third innocent
cause (a fresh volume not fully loaded, or a legitimately different
auto-window derived from more imaged ground) moves it too — the storm census
re-learned exactly this ("wait for the engine's own fully-loaded word"). As
described the instrument books a fresh-side change against the warm side.

*Cheapest fix, essentially free:* in the same gate, two `page.evaluate` reads
— the layer/twin count (twin present ⇒ mechanism 1) and the volume layer's
display-window range warm vs fresh (ranges differ ⇒ mechanism 2) — plus the
fully-loaded wait before either screenshot. The brightness delta becomes the
alarm; the two reads name the culprit.

**Wording notes:** "Nothing about the wire format changes" and "declares
slab-shaped pieces" cannot both stand. "Under two percent of the data" is
argued from halving while halving is held open; the un-halved figure belongs
beside it. "The client needs nothing" is 2-D evidence only. The acceptance
section promises the flat bound unconditionally while the build section
predicts ×10 bake; state which yields.
