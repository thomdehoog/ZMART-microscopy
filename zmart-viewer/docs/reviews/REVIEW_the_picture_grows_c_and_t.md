# Review: the picture grows channels and time

Written 2026-08-17 against the plan as it stands on `claude/thy1-linked-spiral`,
before anything is built. This reviewer read the plan, the contract, the cited
tests, the two sibling plans, and the shipped code they all point at — and no
other review file, as the prompt requires. Every finding below says whether it
is shown (with the file and line, or the arithmetic) or suspected.

**Verdict: do not build from this plan as written — its two central premises
("most of the truth already exists" and "this is address plumbing, not new
truth") are overclaimed against the shipped code in ways that hide the real
work, its one known O(moments) event would freeze the picture for minutes on a
long timelapse, and its default test matrix cannot detect the exact disease
the channel refusal exists to prevent.**

---

## Finding 1 (severe, shown): the replacement spike is not "already pinned" — it is an unpriced stall of the whole picture, minutes long on a long timelapse

The plan's whole treatment of the one event that scales with time is: "the
spike is O(moments) and its size is already pinned at the record layer"
(items 3 and the scaling section). What is pinned is a **set size** — the
test asserts *which units* change and *how many*
(`zmart_live/tests/test_a_replacement_advances_every_moment.py:68-75`), never
a millisecond. The cost lands somewhere else entirely, and the shipped code
says exactly where.

The bake patch runs **inside the derive, before any request is answered**
(`zmart-viewer/app/picture/governed.py:584-586` calls `_keep_the_bake_true` before
installation; the docstring at 730-733 says so in words), and every piece
request must take the same derive lock first (`governed.py:425-428`: `composer()`
enters `_derive_guard`). So while one derive patches, the entire picture
answers nothing. The patch loop composes every dirty piece of every baked
level (`governed.py:781-787`), and once footprints carry (t, c), a replacement
dirties its footprint **times every published moment** — that is the manifest's
own rule, correctly pinned at `gateway.py:180-191`.

The arithmetic, from this repository's own measured numbers: a single-moment
replacement costs 330–380 ms today (`docs/open/PLAN_close_the_neuroglancer_chapter.md:33`);
the bake-compose share is 60–90 ms where slabs are warm and **0.5–3 s where
they are cold** (`governed.py:624-628`). Old moments are cold by this plan's
own posture (only the viewed moment stays warm — item 4). A retake on a
500-moment run therefore patches 500 cold footprints inside one derive:
500 × 0.5–3 s = **four to twenty-five minutes** with every piece request
queued behind the lock; even the impossible all-warm best case is
500 × 60 ms = 30 s of frozen screen. The operator's one retake becomes the
longest outage of the whole run.

The sibling depth plan already names this exact problem and orders its
instrument — "a whole-position replacement on a long timelapse patches
O(moments) synchronously while requests wait … one replacement-on-large-t
rung — asserting time-to-first-answered-piece during the patch"
(`docs/open/PLAN_the_picture_grows_a_z_axis.md:154-159`). The c-and-t plan, whose axis
this is, inherits the depth plan "and must not contradict it" — yet its ladder
gains only an ordinary-landing moments column and no replacement rung at all.

**Cheapest deciding instrument:** the depth plan's own rung, run at the record
layer with no browser — replace one position of a synthetic run at m = 50,
200, 500 published moments and measure time-to-first-answered-piece during
the patch. If the number is what the arithmetic above says, the plan must
choose a mitigation (lazy per-moment patching behind compose-on-request, or
patching outside the derive lock) *before* build, not after.

## Finding 2 (severe, shown): "address plumbing, not new truth" is false — the snapshot machinery discards moments today, and its caches cannot key them

The plan's item 2 claims the derive only needs addresses because "no
cross-moment, no cross-channel arithmetic exists anywhere". The arithmetic is
indeed absent; the **state** is not, and the shipped snapshot is built by
throwing the time axis away:

- The fold collapses `(position, moment, generation)` units to one generation
  per position and one tile list per manifest state
  (`governed.py:1117-1131`); the drawn set is gated on **moment zero alone**
  (`governed.py:1129`: `(position_id, 0, …) in published`). A fail-closed
  per-(t, c) picture needs the tile-presence question answered *per moment* —
  a position published at moment 3 but not moment 5 must be drawn at t=3 and
  refused at t=5. That means either one mosaic/tile-set per visited (t, c)
  (state multiplies by moments) or the published-unit gate moving into the
  per-piece compose path (a new check on the hottest path). Neither is an
  address.
- The slab cache key is `(level, low_z, row, column)` with no moment and no
  channel (`composer.py:207`, `composer.py:616`). Two (t, c) frames of the
  same piece collide in the cache. The **block** cache key already carries
  `outer` — and its docstring says why: "a key without it would hand one
  moment's specimen to another's request the day the picture grows those
  axes" (`composer.py:485-489`). The repository saw this day coming and
  prepared exactly one of the two caches for it.
- Dirty footprints are `(level, row, column)` in every consumer — the derive
  (`governed.py:538`, `1246-1259`), slab inheritance (`composer.py:325-337`),
  index inheritance (`composer.py:381`), the bake patcher
  (`governed.py:781-787`), and the stamp-recovery sweep
  (`governed.py:848-852`). Item 3's "dirty footprints carry (t, c)" rewrites
  one shape through five consumers — the very situation whose z-analogue the
  depth plan promoted to a named finding with a one-definition rule and a
  sabotage test (`docs/open/PLAN_the_picture_grows_a_z_axis.md:141-147`).
- The warm pass and the pins have no notion of a current moment: the warmer
  builds **every** slab of every pinned level over the whole declared shape
  (`composer.py:713-729`), warm-completeness counts the whole grid
  (`composer.py:682-687`), and the pinned store never evicts
  (`composer.py:215`). Give the picture a time axis and the warm pass walks
  the declared room, moments nobody imaged included, and the pins hold every
  moment ever warmed.

None of this is cross-moment arithmetic, and all of it is design work the
plan has filed under "bookkeeping". **Cheapest deciding instrument:** none
needed — the lines above are the evidence. The plan should be revised to name
the per-(t, c) snapshot design (one composer per state with (t, c)-keyed
caches, or per-(t, c) snapshots with a shared block cache) as built work with
its own gates, in the depth plan's one-named-shape discipline.

## Finding 3 (severe, shown): "old moments bake on first visit" has no mechanism, and the one-prefix stamp turns any hiccup into a re-bake of the entire declared room

The plan's item 4 leans on "the cold-open posture the closing plan already
recommends". The closing plan *recommends a posture and orders a test*
(`docs/open/PLAN_close_the_neuroglancer_chapter.md:220-221`); nothing of it exists. In
the shipped code there is no first-visit bake at all: baked files are written
only by declare (`declare.py:294-412`) and by the patcher inside the derive
(`governed.py:781-787`); an on-demand compose never writes a file. "Bake on
first visit" therefore means a **write on the read path** — new machinery
with lock consequences the plan does not mention.

Worse, the stamp cannot express the posture. The bake's coverage is one
all-or-nothing prefix identity `{events, tail, layout}`
(`governed.py:656-694`), and anything the stamp cannot prove dirties
**everything** — every piece of every level
(`governed.py:848-858`). "Everything", once the grid carries (t, c), is every
piece of every declared moment and channel, never-imaged tail included. The
arithmetic: a full bake of one moment at 4,096 positions is 30.6 s measured
(`docs/open/PLAN_close_the_neuroglancer_chapter.md:37`). A torn stamp, a rollback, or a
session reopening after a crash — the ordinary recovery paths — on a run with
100 written moments of a 500-moment ceiling would recompose on the order of
100 × 30 s ≈ **an hour inside one derive**, and the sweep would still walk
the 400 empty moments to prove them empty. Bake-on-first-visit and
per-moment recovery both require the stamp to say *which* (t, c) it covers —
a new coverage record, which is precisely the "new truth" the plan says this
work does not contain.

**Cheapest deciding instrument:** a paper one — write the stamp's (t, c)
coverage format down in the plan before anything is built, and add one
record-level recovery test: bake, tear the stamp, reopen, and assert the
repatch touched only written moments' pieces. Red today by construction.

## Finding 4 (severe, shown): "the piece address space already has the slots" is false, and it contradicts the depth plan this plan claims to inherit from

The plan's fifth "already exists" bullet says "Both serving doors answer
`level/c/t/c/z/y/x` in zarr's five-axis chunk form; the governed picture
simply always says t = 0, c = 0 today." The shipped doors refuse that form:

- `served.the_bytes_behind` accepts exactly five path parts —
  `level/c/z/y/x` (`served.py:336`: `len(parts) != 5`); a seven-part (t, c)
  address is answered 404.
- The backend's governed-file door hard-codes the same shape: "A chunk file
  sits exactly five levels inside its store (level/c/plane/row/column), so
  the store is the fifth parent" (`app/server/server.py:456-459`, code at
  466-472), and `_built` peels `parts[-4] != "c"` (`app/server/server.py:536`).
- The picture's own descriptions declare three axes: `group_json` writes
  z/y/x only (`composer.py:963-967`) and `array_json` a 3-entry shape with
  `chunk_shape [1, piece, piece]` (`composer.py:980-993`).
- The baked file tree, the stripe baker, the patcher, the staging arrays,
  the recipe fast path (`governed.py:1018`: `len(chunk) == 3`), the direct
  rehalve, and the warm read-back (`governed.py:879-990`,
  `composer.py:786-815`, `declare.py:95-99`) are all three-axis.

The five-axis form exists only in the **position stores** the writer produces
— which is a different door. And the sibling depth plan, revised after its
reviews, states the truth this plan contradicts: "The piece address space is
already three-dimensional. Both doors answer `level/c/z/y/x`"
(`docs/open/PLAN_the_picture_grows_a_z_axis.md:89-90`). This plan's preamble binds it to
that plan ("must not contradict it"). The consequence is not merely a wording
error: the plan sizes the derive work by this premise ("a single-file read by
construction … address plumbing"), and the premise being false means roughly
ten parsers, writers and fast paths change shape together — each one a reader
of the axis slots that the depth plan's own sabotage rule (shift the key by
one; every reader must go red) applies to.

**Cheapest deciding instrument:** none needed; the lines above decide it. The
plan should list the readers of the chunk key by name and give them the
depth plan's one-shape-one-definition treatment.

## Finding 5 (severe, shown): the default test matrix passes a total channel collapse — the exact disease the refusal exists to prevent

The prompt asks for the (t, c) fault that passes the whole matrix. Here is
one that passes every gate the plan makes default: **serve channel 0's bytes
for every channel's address.** Walk it through the four squares and the
listed gates:

- *Held view, growth appears:* every landing writes **both** channels at once
  (`coordinator.py:625-658` writes `array[timepoint, channel]` for all
  channels of one commit), so both channel rows light up on every landing.
  Growth appears. Pass.
- *Warm equals reload, all zoom bands, both channels, two moments:* the F5
  oracle compares the warm page to a fresh page **through the same wrong
  mapping** — both show channel 0. Identical. Pass. The depth plan itself
  concedes this blindness for its contrast gate: "a window wrong the same
  way in both screenshots passes every census ever taken"
  (`docs/open/PLAN_the_picture_grows_a_z_axis.md:170-173`) — but this plan builds no
  analogous ground-truth gate for (t, c) identity.
- *Moment m − 1 untouched, byte for byte:* the collapse is orthogonal to
  time. Pass.
- *The spiral with colours on screen:* both rows grow (landings carry both
  channels); the lit-geometry instrument measures where light is, not whose
  light it is (`test_a_survey_grows_in_a_spiral.py:264-289`). Pass.
- *Storm rate:* unaffected. Pass.
- *The record-level colours tests:* they read the **position stores** through
  plain zarr (`test_a_survey_grows_in_a_spiral.py:217-223`), never the served
  picture. Pass.

The only fixtures that could catch a wrong-(t, c) mapping — "per-channel and
per-moment signatures so the wrong (t, c) can never masquerade as the right
one" — live in the **one heavyweight fixture that is explicitly opt-in and
never in the default suite** (plan, test-economics section). So the plan
retires the loud refusal (`declare.py:239-246`, pinned by
`test_the_viewer_still_refuses_to_collapse_two_colours`) and replaces it with
a matrix that cannot see the silent collapse the refusal guarded against.

A second fault in the same family, suspected rather than fully shown:
**a bake that fails to patch a non-current moment after a replacement** is
masked by navigation. Reaching moment m − 1 means moving the slider, and the
depth test plan records the bench fact that "navigating — especially stepping
z or t — tends to trigger a refresh, so any test that moves will quietly
repair the staleness it was sent to find"
(`docs/open/TESTPLAN_the_picture_grows_a_z_axis.md:135-137`); under the decided
whole-source default the switch refetches fresh ground by construction. The
plan's "switch the slider to m − 1 — nothing there has moved" must therefore
compare **baked files on disk**, or hold m − 1 in a second page that never
navigates — as specified it proves little.

**Cheapest deciding instrument:** a record-level, browser-free gate in the
default suite, in the depth test plan's stage-2 pattern
(`docs/open/TESTPLAN_the_picture_grows_a_z_axis.md:114-125`): tiny governed fixture
with a distinct stamp per (t, c) — e.g. value = 1000·t + 100·c — ask the
**served composer** for pieces at every (t, c) and compare against ground
truth by construction. Milliseconds, and red under any collapse, swap, or
off-by-one on either axis.

## Finding 6 (moderate, shown): the manifest has no channel in its unit — per-channel landings, per-channel dirt, and the "one channel grows while the other holds still" gate cannot be produced by the shipped writer

Item 3 says "a landing in moment m, channel k dirties pieces of exactly
(m, k)". The record cannot say that: the published unit is
`(position, timepoint, generation)` — no channel (`gateway.py:146`, `191`) —
and the writer only accepts a commit carrying **every** channel at once
(`coordinator.py:591-603` refuses partial channels; `527-529` refuses
republishing a (position, timepoint)). A landing is all channels of one
moment, always. Consequences:

- Per-channel dirty footprints have no source of truth; the honest footprint
  of a landing is (m, *all* channels), which also halves the plan's implied
  worry about the common case paying "two derives, two bakes" — one commit,
  one derive, one patch covering both channels is what the record supports.
- The browser gate "the seeded centre grows outward in one channel while the
  other channel and the previous moment hold still" cannot be arranged:
  no shipped writer can land one channel alone. Either the gate is rewritten
  (both channels grow, with distinct per-channel values asserted — which
  needs finding 5's ground-truth instrument to mean anything), or the plan
  is quietly requiring a per-channel commit capability, which is a record
  change — new truth — that must be named.

**Cheapest deciding instrument:** none needed; the writer's own refusals
decide it. Revise item 3's sentence and the gate's recipe.

## Finding 7 (moderate, shown): the "what already exists" list overclaims in four places a builder would trip over on day one

1. **"The profile already says how many channels and timepoints the
   acquisition will have."** Channels yes (`profiles.py:698`, `816`);
   timepoints **no** — `timepoints` is a constructor argument of the writer
   (`coordinator.py:184`), recorded durably nowhere but in the position
   arrays once one exists (`coordinator.py:333-348`: "The arrays themselves
   are the durable declaration"). Declare-the-full-room-before-the-first-
   landing therefore has **no record to read the t extent from** on an empty
   run. Adding timepoints to the sealed profile is a format change with
   migration, and the plan should say so.
2. **"The collection declaration names each member's written moments."** The
   shipped publisher declares members only —
   `{"members": sorted(members)}`, no moment counts
   (`coordinator.py:411-434`, the write at 427). The per-member `moments`
   field exists only in the **test** stranger-writer
   (`zmart-viewer/tests/a_microscope.py:176`) and in the contract as a promise
   ("which rides beside the list *when time lands*",
   `docs/how_it_works/CONTRACT_the_files_the_viewer_needs.md:296-298`). The arrival signal the
   plan's slider (item 5) reads must first be built into the writer.
3. **"The governed picture … refuses everything else, loudly."** Half true.
   Multi-channel is refused loudly (`declare.py:239-246`). Multi-**moment**
   is not refused at all: no timepoint check exists anywhere in the declare
   or serving door, and the picture silently serves the first moment of a
   timelapse as if it were the whole run (`governed.py:36-38`). The plan's
   own principle — "the refusal keeps guarding until the whole chain works"
   — is already violated for time, today, and the plan does not notice.
4. **The writer's refusal is not a remedy.** The message at
   `coordinator.py:548-550` says only "there is nowhere in it to put moment
   X". The depth plan this plan inherits requires "the remedy named in its
   message: a new acquisition, priced as a cold open"
   (`docs/open/PLAN_the_picture_grows_a_z_axis.md:122-125`). One sentence of work, but
   the plan claims it exists and it does not.

**Cheapest deciding instruments:** for (3), a one-line unit test today:
declare a two-moment single-channel run and assert a loud refusal — red
against the shipped code. For the rest, revision of the plan's list.

## Finding 8 (moderate, shown): a per-landing O(moments) term already ships in the fold, so "nothing else may scale with t" is a known red, not a fact to confirm

The plan's scaling section says the replacement spike is the *one known*
O(moments) event and "nothing else may scale with t". The shipped derive
already scales with t twice per landing: the gateway rebuilds a frozenset of
**every** published unit — positions × moments — on every commit
(`gateway.py:195`), and the derive's fold sweeps that whole set again
(`governed.py:1117-1119`), a cost the code itself already indicts at the
survey scale ("a landing's bookkeeping should be the size of the landing,
and today it is the size of the survey", `governed.py:1163-1174`, held by
`test_absorbing_a_change_touches_the_change`). At 100 positions × 500
moments that sweep is 50,000 units per landing — the O(survey)-shaped term
the flat campaign spent itself shedding, reborn multiplied by t. The plan's
moments ladder column would find this — good — but the plan presents the
column as confirmation of flatness ("must match the single-moment table")
rather than as the instrument for a term it can already name. A plan that
knows where its red will be should say so.

**Cheapest deciding instrument:** the ladder moments column the plan already
orders, plus extending `test_absorbing_a_change_touches_the_change`'s swept
counter with a moments axis — record layer, seconds to run.

## Finding 9 (moderate, shown): the declared-ceiling decision — forced, as the plan asks — is "generous ceiling", but only with conditions the plan does not yet own

The plan defers the ceiling-versus-growing decision to its reviews while its
sibling has already decided it — "The rule, per axis: declare a generous
ceiling; absence expresses the tail; stopping early is ordinary", with the
c-and-t plan named as inheriting it
(`docs/open/PLAN_the_picture_grows_a_z_axis.md:117-129`). Deciding the same way here is
right: a growing description re-litigates two measured failures (the moved
origin, the reload-to-see-it cost), and absence already expresses unimaged
ground everywhere in this system. So: **generous ceiling, decided.** But the
depth plan attached honesty conditions, and for t they are not free in the
shipped code:

- "Un-imaged room must cost nothing per landing." Today's walkers do not
  skip it: the stamp-recovery sweep dirties the whole grid
  (`governed.py:848-852`, finding 3), and the warm pass iterates the whole
  declared shape (`composer.py:713-729`, finding 2). The depth plan ordered
  "the patcher skips slabs that intersect no planned tile" and a
  declared≫imaged **parity rung** — run the ladder with declared = imaged
  and declared ≫ imaged and require the numbers to match
  (`docs/open/PLAN_the_picture_grows_a_z_axis.md:143-147`,
  `TESTPLAN…:88-95`). The c-and-t plan orders **no parity rung for t** and
  no skip-unwritten-moments rule. It must.
- The day the ceiling is reached, the run stops: the refusal is hard
  (`coordinator.py:547-550`), room cannot change after pixels exist
  (`coordinator.py:360-367`), and the remedy — a new acquisition folder,
  priced as a cold open — is real but currently unnamed in the message
  (finding 7.4). The plan should also state what the operator *sees*: two
  acquisitions side by side as two layers is the contract's own answer
  (`CONTRACT…:375-391`), and saying so turns a scary wall into a documented
  gesture.
- The ceiling's per-store cost is genuinely cheap — shape metadata only,
  since every chunk covers one (t, c) frame and absent chunks are no files —
  so the generous end is affordable **provided** the walkers learn to skip.
  That proviso is the whole decision.

**Cheapest deciding instrument:** the declared≫imaged parity rung for t —
one extra ladder configuration, already specified by the sibling plan.

## Finding 10 (moderate, part shown, part suspected): under the decided whole-source refresh, the (t, c) refetch and cold-visit bills have no instrument in this plan

The client's decided default drops the whole source and refetches on every
landing; the named per-piece ladder is deprecated and marked for deletion
(`docs/open/PLAN_close_the_neuroglancer_chapter.md:79-95`), so item 3's server-side
(t, c) footprints never reach the client at all. Three bills follow that the
plan's storm gate (a rate, not a bill) does not measure:

- *Shown by construction:* with both channels on screen — the plan's own
  common case — every landing's refetch covers both channels' visible
  pieces. The 20/s bar was measured single-channel; two channels double the
  requests per landing at the same rate.
- *Shown by construction:* a page holding a **non-current** moment (the
  operator inspecting m − 1 while m lands) refetches its whole screenful on
  every landing in m, though nothing it shows has changed. This is the
  t-shaped shadow of the held-volume bill both depth reviews ranked first
  (`docs/open/PLAN_the_picture_grows_a_z_axis.md:42-51`), smaller only because a
  screenful is not a stack.
- *Suspected, with the bench on its side:* the first visit to an old moment
  is a cold open of that moment — the coarsest level is the dearest ground
  ("12.7 seconds at 12,800 positions", `composer.py:695-697`) — and the slab
  budget is one shared 256 MB LRU (`composer.py:82`), so the operator's most
  natural timelapse gesture, flipping between adjacent moments to compare
  them, may thrash two moments' warmth against each other, seconds per
  flip. The depth test plan already ordered the exact counter "the day t
  exists": step one moment on a finished picture and count requests and
  bytes at the server (`docs/open/TESTPLAN_the_picture_grows_a_z_axis.md:48-55`).
  This plan does not mention it.

**Cheapest deciding instruments:** the t-step counter above (an evening, no
browser changes), a two-channel storm run against the same 20/s bar with
requests-per-landing recorded, and one held-old-moment variant of the storm
gate counting refetches at the server.

## Finding 11 (minor, shown): item 5's slider design contradicts the shipped control and the repository's own documented trap

The shipped slider does not "range over declared room": it offers **only
committed moments** and snaps to the nearest allowed one
(`app/page/src/AxisSlider.jsx:104-131`), capped by the server's
frames count (`app/server/server.py:1686-1688`, `stores.py:768` ff). And the
repository's own doctrine warns against offering unwritten moments at all:
"the engine remembers 'there is nothing here' for a frame it looked at too
early and will not look again, so that frame would stay blank for the rest
of the session even once it had been imaged" (`stores.py:773-776`). Under
live whole-source refresh that staleness is repaired, so ranging wider may
be fine — but the plan should say which behaviour it wants (offer only
written moments, as the control does today, or offer the room with written
marks, which is a new affordance) and why the remembered-absence trap does
not apply, rather than describing a control that matches neither the code
nor the doctrine.

**Cheapest deciding instrument:** none needed — a design sentence in the
plan, plus (if the room is offered) one browser gate: visit an unwritten
moment, land it, and require it to appear without navigation.

---

## What the plan gets right, for the record

The one-frame-per-(t, c) file contract is real, gated, and byte-compared
(`CONTRACT…:22-29`, `test_a_survey_grows_in_a_spiral.py:179-223`); the
replacement rule's *set* semantics are correctly and thoroughly pinned; the
no-pyramids-over-c-or-t section is exactly right and well argued; the
four-square F5 grid is the correct oracle for staleness (its blindness in
finding 5 is to identity, not to staleness — it needs the ground-truth gate
beside it, not replacement); refusing channel merging in the server keeps
the compositor honest; and putting the instrument before the scaling claim
is the discipline that closed the flat chapter. The plan's shape is right.
Its inventory of what exists is not, and the inventory is what the build
would be sized by.
