# The governed picture grows channels and time

> Written 2026-08-17 beside the depth plan; revised the same week after a
> blind adversarial review filed eleven findings
> (`REVIEW_the_picture_grows_c_and_t.md`) and its verdict — do not build
> from this plan as written — was accepted. The revision keeps what the
> review endorsed (the file contract, the four-square F5 grid, the
> no-pyramids-over-c-or-t rule, instrument-before-scaling) and replaces
> what fell: the inventory of what exists was wrong, and the inventory is
> what a build is sized by. The disposition table at the end maps every
> finding. Nothing here is started, and nothing may be built before the
> instruments this revision orders have run.

## The want

An acquisition records two colours per position, moment after moment, and
the operator wants to watch it the way they watch the flat survey today:
pick a channel, slide through time, and see landings appear live — with a
retake of one moment updating that moment and leaving every other exactly
as it was.

## What actually exists, corrected

The review audited the original list against the shipped code; this is the
honest version.

**Real and gated:**
- The (t, c) **file contract**: every chunk covers one moment of one
  channel, new moments only add files, byte-compared in the spiral's
  colours-and-moments gates and the stranger-writer gate.
- The record carries **moments** — the published unit is
  (position, timepoint, generation) — and the replacement rule's *set*
  semantics (every published moment advances) are thoroughly pinned.
- The layer panel's per-channel rows and contrast, for finished data.

**Claimed before, false or absent, now named as work:**
- The record has **no channel in its unit**, and the writer only accepts a
  commit carrying every channel of a moment at once. A landing IS all
  channels of one moment; per-channel landings do not exist and are not
  needed. Footprints are per (moment, all-channels), and every gate recipe
  says so.
- The profile declares channels but **not timepoints** — the t extent
  lives only in a writer constructor argument and, once pixels exist, in
  the arrays. Declaring the room from the profile requires **timepoints in
  the sealed profile**, a format change with migration, named here as
  built work.
- The shipped collection declaration lists members only; the per-member
  **written-moments field exists only in the test writer and the
  contract's promise**. The arrival signal the slider needs must first be
  built into the publisher.
- The governed door's piece address is **three-axis** (`level/c/z/y/x`) in
  roughly ten parsers, writers and fast paths — the five-axis form exists
  only in the position stores, a different door. Growing (t, c) into the
  piece address is a change to every reader of the chunk key, and gets the
  depth plan's discipline: the readers listed by name, one shape defined
  once, and the shift-the-key sabotage that must go red at every reader.

  **Landed 2026-08-17.** The readers were enumerated first (every parse,
  format, and arity assumption, both server doors, the bake paths, the
  frontend); the address now has exactly one definition
  (`composer.the_piece_address`, identity-checked across the doors by the
  oracle suite), reading the flat five-part form as frame (0, 0) and the
  grown seven-part form (`level/c/t/c/z/y/x`) in full — so nothing about
  a flat picture's wire traffic moved. The composer serves any (moment,
  channel): the request's pair threads to the position stores' own front
  axes, slab and block caches key by frame, and a governed tile carries
  its committed-moment set, so an unpublished moment's pixels on disk
  serve as absent — the record, never the files. The snapshot's drawn-set
  gate moved from moment zero to any-committed-moment (finding 2's fold
  item), and the change-detection learned that a new moment dirties its
  footprint without moving a generation — a bug the combined-axes oracle
  caught within its first hour, inherited stale emptiness serving over a
  fresh commit. The oracle itself (value = 1000·t + 100·c + z + 7, both
  doors, default suite) stands; the bake refuses grown pictures until the
  per-(t, c) bake lands; the declare-door refusals stand until the
  browser gate proves the grown picture draws.

  **The browser gate stands too** (same day,
  `test_a_grown_picture_draws_in_the_browser`, screenshots inspected by
  eye): the engine's own space carries the time axis, the page offers
  the T slider and per-channel rows without a line of new frontend code
  — the linked door's five-axis machinery carries over — and steering
  t and z moves the drawn pixels by exactly the stamped steps, with the
  operator's F5 pair holding at every station. What still holds the
  live-door refusals in place is the slider contract alone: a grown
  LIVE source would today offer the declared t room rather than the
  written moments, and uncommitted time must never be offered — so the
  refusals retire with the written-moments slider work, next.
- **Time is not refused today — it is silently truncated.** The picture
  serves the first moment of a timelapse as if it were the whole run,
  which violates the plan's own refuse-until-it-works principle right now.
  Day-one change, ordered before anything else in this plan: declaring a
  multi-moment run refuses loudly, exactly as multi-channel does, with the
  remedy named in the message. One unit test, red against the shipped
  code today.

  **Landed 2026-08-17.** The declare door reads the timepoint room from
  the run's own arrays (the writer's durable declaration) and refuses
  beside the channel check; the registry withholds the binding with the
  reason, the same posture as a failed bake. The red-then-green gate is
  `test_the_viewer_refuses_to_truncate_a_timelapse`, and the registry
  posture is pinned by
  `test_a_timelapse_run_is_refused_loudly_not_silently_truncated`. Two
  consequences the landing surfaced, both now owned here: the rows
  machinery under the future slider keeps its own gate by direct binding
  (`test_the_rows_report_committed_time_ranges_and_no_false_high_water`),
  and a browser gate's claim went dormant with the refusal — **a landing
  that fills a committed time gap must heal the ranges without tripping
  the whole-source decoded-cache flush** — recorded in the slider section
  below and returning with the axis. One honest gap remains until
  timepoints enter the sealed profile: a timelapse run that has not yet
  landed a single position cannot be told from a flat one, because the
  room is written nowhere but the arrays.

## The synchronous stall this axis owns (the review's first finding)

A replacement on a long timelapse dirties its footprint times every
published moment, and the bake patch runs inside the derive while every
piece request queues behind the lock. By this repository's own measured
numbers, a retake at 500 moments is minutes of frozen picture in the
worst case and tens of seconds in the impossible best. This is the
c-and-t chapter's version of depth's synchronous-patch finding, and it
gets the same treatment: **measured first, then mitigated, before build.**
The instrument is the replacement-latency rung at the record layer, no
browser: replace one position at m = 50, 200, 500 published moments and
measure time-to-first-answered-piece during the patch. The mitigation is
chosen from that number — lazy per-moment patching behind
compose-on-request (only the viewed moment patches synchronously; others
patch on their next visit), or patching outside the derive lock — never
assumed.

**Measured 2026-08-17, and the mitigation chosen**
(`MEASURED_stage0_c_and_t_instruments.md`): the projected synchronous
bill is ~165–190 s of frozen picture at a 500-moment retake, against
0.33 s flat for the lazy path — so the mitigation is **lazy per-moment
patching behind compose-on-request**, with patching outside the derive
lock available only as a refinement on top. The build gate that ships
with the mechanism: time-to-first-answered-piece after a retake stays
inside the one-moment bound at every rung, measured, not assumed.

## The per-(t, c) snapshot is designed work, not bookkeeping

The shipped snapshot machinery throws the time axis away, and the review
listed where; this plan now owns each as design work with its own gate:

- **The published-unit gate moves to per-moment.** The fold collapses
  units to one generation per position and gates the drawn set on moment
  zero; a fail-closed per-(t, c) picture must answer tile presence per
  moment — drawn at t = 3, refused at t = 5, for the same position.
- **The caches learn the axes.** The block cache already carries the
  outer index (the repository prepared it for exactly this day); the slab
  cache and warm bookkeeping do not, and two (t, c) frames of one piece
  must never collide. Cache keys grow (t, c) together with the dirty
  shape.
- **One named dirty shape**: (t, c-set, level, row, column), defined
  once, imported by all five consumers the review enumerated (derive,
  slab inheritance, index inheritance, bake patcher, stamp-recovery
  sweep), with the sabotage test proving there is exactly one definition.
- **The warm pass and the pins follow the written, current ground.** The
  warmer walks written moments only — never the declared tail — and pins
  are bounded by the absolute byte budget the depth plan already ordered,
  with the viewed moment's warmth prioritized and old moments evictable.

## The bake follows the moment being written — with its mechanism named

Per landing, the bake patches the touched pieces of the landing's own
moment (all channels — that is what a commit is). Old moments bake on
first visit, and that posture now says what it is: **a write on the read
path**, new machinery with lock consequences, built deliberately. Two
prerequisites the review proved missing:

- **The stamp gains per-(t, c) coverage.** Today's one-prefix stamp makes
  any hiccup dirty everything, and "everything" times a declared room is
  hours of recompose plus a sweep of moments nobody imaged. The coverage
  record — which moments' baked ground this stamp vouches for — is
  written down in format before any code, and the recovery gate is
  record-level and red today by construction: bake, tear the stamp,
  reopen, and the repatch touches only written moments' pieces.
- **The sweep and the walkers skip unwritten ground**, so the generous
  ceiling costs nothing — proven by the t parity rung below, not assumed.

## The scaling terms, honestly: one known red, one spike, three bills

- **A per-landing O(positions × moments) term already ships** in the unit
  fold — the plan says so now instead of presenting the moments column as
  confirmation of flatness. The instrument: the ladder's moments column
  plus the swept-counter of `test_absorbing_a_change_touches_the_change`
  extended with a moments axis. The fix must make a landing's bookkeeping
  the size of the landing again, with t in the room.
- **The replacement spike** is the stall section above — priced, then
  mitigated.
- **Three refetch bills under the decided whole-source default**, each
  with its counter before build: the **two-channel storm** (both channels
  on screen is the common case; the 20/s bar was measured single-channel,
  and requests-per-landing is recorded against the same bar); the
  **held-old-moment bill** (a page inspecting m − 1 refetches its
  screenful on every landing in m — the t-shaped shadow of depth's
  held-volume finding, measured by the same kind of counter); and the
  **moment-flip cold bill** (the operator's compare-two-moments gesture
  against one shared slab budget — the t-step counter the depth test plan
  already ordered, adopted here by name).

## The declared room for time: decided, with its conditions owned

**Generous ceiling, inherited from the depth plan's per-axis rule.**
Absence expresses the tail; stopping early is ordinary. The conditions,
now owned rather than waved at: timepoints enter the sealed profile (the
format change above); the walkers skip unwritten moments and the
**declared≫imaged parity rung for t** proves it (declared 500, written
50, numbers must match declared-equals-written); and the day the ceiling
is reached, the writer's refusal names the remedy — a new acquisition,
priced as a cold open — and the operator's experience of it is the
contract's own answer: two acquisitions opened side by side as two
layers on the one canvas.

## The slider says what is written

The shipped control offers only committed moments and snaps to them, and
the repository's remembered-absence doctrine warns against offering
unwritten frames. This plan keeps that behaviour: **the slider ranges
over written moments** (driven by the publisher's written-moments
declaration, once it exists), and the declared ceiling appears as text
beside it ("moment 37 of 500 declared"), not as slider room. Two browser
gates cover the seam: hold the page while a new moment lands, and the
slider's range grows without navigation or reload; and a landing that
fills a committed time gap heals the ranges into one without tripping
the whole-source decoded-cache flush — the gate that watched this
(`zmartLetGo.times` unchanged while the gap closes) went dormant when
the day-one refusal landed, and returns with the axis, asserting pixels
as well as ranges.

## How we will know it is done

Every browser gate runs the four-square grid — held view and scrolling,
each before and after F5, compared fully loaded — and the station walk
with its per-station F5 pairs, exactly as the depth test plan records
the operator's protocol. The review proved the grid is an oracle for
*staleness*, not *identity* — a total channel collapse passes every F5
comparison because both sides lie identically — so identity gets its own
standing gate, in the default suite, record-level and browser-free:

- **The (t, c) identity oracle.** A tiny governed fixture stamped
  value = 1000·t + 100·c; the served composer is asked for pieces at
  every (t, c) and compared against ground truth by construction.
  Milliseconds to run; red under any collapse, swap, or off-by-one on
  either axis. This gate is what lets the multi-channel refusal retire
  without reopening the door to the disease it guarded against — the
  refusal falls only the day this oracle stands.
- **The axes are proven together, not only one at a time** (the
  operator's order, 2026-08-17). The oracle's stamp grows the third
  axis for almost nothing — value = 1000·t + 100·c + z on a fixture a
  few planes deep — so one record-level gate catches a collapse, swap,
  or off-by-one on any of z, c, t **or their combinations**. Neither
  this chapter nor the depth chapter closes on independent-axis gates
  alone; the combined rung is shared between the two plans, and a
  station-walk variant that steps all three axes follows once the
  served axes exist.
- **The moment-untouched checks compare files, not screenshots.** "Switch
  to m − 1 and nothing has moved" is masked by navigation-triggered
  refresh under the whole-source default, so the assertion is on the
  baked files and served bytes of m − 1, byte-compared — or on a second
  held page that never navigates.
- **The growth gate, rewritten to what the record supports**: landings
  carry all channels, so the spiral grows in both channels at once and
  the per-channel *values* are asserted against the stamp — one channel's
  growth showing the other channel's numbers is exactly what the identity
  oracle exists to catch.
- The storm bar holds with two channels live; the parity rung holds with
  a generous t ceiling; the replacement rung's chosen mitigation holds
  its time-to-first-answered-piece bound.

## What is deliberately not in this plan

- No per-channel commits: the record's unit is a moment with all its
  channels, and the plan builds on that truth rather than quietly
  changing the writer.
- No pyramids over c or t — a pyramid is a spatial economy; averaged
  channels are colours nobody recorded, blurred time is motion smeared
  into ghosts that exist in no frame. Every (t, c) pair carries its own
  spatial pyramid.
- No multi-moment compositing in the server; views may compute such
  things one day, the served picture answers one (t, c) at a time.
- No channel merging in the server; colours meet only in the viewer's
  compositor, each with its own contrast.
- No z — the sibling depth plan owns it; the two share the ceiling rule,
  the one-shape discipline, and the test economics, and must not
  contradict each other.

## Test economics: small first, fast always, the big one opt-in

Unchanged from the first version, with one correction the review forced:
the wrong-(t, c) signatures live in the DEFAULT suite now (the identity
oracle above, milliseconds), not only in the opt-in heavyweight fixture.
The budgets stand: record-level tests in milliseconds to seconds, browser
gates under ninety seconds on the smallest survey that exercises the
claim, and the gigabyte-scale linked fixture — delicate structures,
per-(t, c) signatures, every pixel a known right answer — behind an
environment knob for the ladder and the soak, never in the default suite.

## Disposition of the eleven findings

| Finding | Disposition |
| --- | --- |
| 1 replacement stall (severe) | Accepted; priced by the record-layer latency rung at m = 50/200/500 before build; mitigation chosen from the number |
| 2 snapshot discards moments (severe) | Accepted; per-moment unit gate, (t, c) cache keys, one named dirty shape across five consumers, written-ground warm pass — all named as designed work with gates |
| 3 bake-on-first-visit unmechanized, one-prefix stamp (severe) | Accepted; write-on-read named, per-(t, c) stamp coverage designed on paper first, tear-the-stamp recovery gate red today |
| 4 three-axis address, contradiction with depth plan (severe) | Accepted; inventory corrected, readers enumerated, one-shape rule and shift-key sabotage inherited |
| 5 matrix passes channel collapse (severe) | Accepted; the (t, c) identity oracle joins the default suite, the refusal falls only when it stands; m − 1 checks compare files |
| 6 no channel in the manifest's unit (moderate) | Accepted; landings are all-channels-of-one-moment everywhere, growth gate rewritten to value assertions, no per-channel commits |
| 7 four inventory overclaims (moderate) | Accepted; corrected above — timepoints into the profile, moments into the publisher's declaration, the loud time refusal ordered day-one, the remedy into the message |
| 8 fold already O(positions × moments) (moderate) | Accepted; named a known red with its counter, not a fact to confirm |
| 9 ceiling with unowned conditions (moderate) | Accepted; ceiling decided, t parity rung and skip-unwritten ordered, ceiling-reached experience documented |
| 10 uninstrumented refetch bills (moderate) | Accepted; two-channel storm, held-old-moment counter, moment-flip cold bill — counters before build |
| 11 slider contradiction (minor) | Accepted; written-moments slider kept, ceiling as text, one grows-without-reload gate |

Nothing was refuted. The review's closing note — the plan's shape was
right, its inventory was not — is the lesson this revision encodes: the
inventory is what a build is sized by, and every "already exists" claim
above now points at the line that proves it.
