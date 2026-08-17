# The governed picture grows channels and time

> Written 2026-08-17, beside the depth plan and in its discipline: a plan to
> review, not work in progress — nothing here is started. The depth plan
> (`PLAN_the_picture_grows_a_z_axis.md`) already sets the one rule the axes
> share: the picture is declared over its full (t, c, z, y, x) room before
> the first landing, and nothing that lands may ever move the description.
> This plan is what channels and time need beyond that rule.

## The want

An acquisition records two colours per position, moment after moment, and
the operator wants to watch it the way they watch the flat survey today:
pick a channel, slide through time, and see landings appear live — with a
retake of one moment updating that moment and leaving every other exactly
as it was. Today the governed picture serves the first channel of the first
moment and refuses everything else, loudly
(`declare_a_governed_picture`, pinned by
`test_a_survey_grows_in_a_spiral.py::test_the_viewer_still_refuses_to_collapse_two_colours`).
The refusal was right — better than colours silently collapsed — and this
plan is how it retires.

## What already exists (most of the truth, none of the serving)

- **The file contract for (t, c) is settled and gated.** Every chunk file
  covers exactly one moment of one channel, so a new moment or channel only
  ever ADDS files; publishing moment one leaves every byte of moment zero
  untouched (byte-compared in
  `test_a_survey_grows_in_a_spiral.py::TestTheSpiralWithColoursAndMoments`
  and in the stranger-writer gate). The writer writes it, plain zarr reads
  it back, and each colour keeps exactly its own pixels.
- **The record carries moments.** The manifest commits (position, timepoint)
  units, the gateway folds them, a replacement advances every published
  moment of a position and the size of that spike is pinned
  (`zmart_live/tests/test_a_replacement_advances_every_moment.py`).
- **Arrival has a signal.** The collection declaration names each member's
  written moments, so a watcher learns "a new timepoint exists" from one
  small file (`viz_studio/tests/a_microscope.py` and the contract's
  arrival-signal section). Nothing needs to scan chunk folders.
- **The viewer already speaks channel and time for finished data.** The
  layer panel gives each channel its own row and contrast; the time slider
  counts written frames per store (`server.py`, `frames` /
  `written_timepoints`). What is missing is these axes on the LIVE governed
  picture, not the controls.
- **The piece address space already has the slots.** Both serving doors
  answer `level/c/t/c/z/y/x` in zarr's five-axis chunk form; the governed
  picture simply always says t = 0, c = 0 today.

## What has to be built

1. **Declare the full room, then stop refusing.** The profile already says
   how many channels and timepoints the acquisition will have;
   `declare_a_governed_picture` declares that room and drops its
   multi-channel refusal the same day the serving below exists — never
   before, so the refusal keeps guarding until the whole chain works.
   Ground not yet imaged is absence, exactly as the flat picture already
   expresses it.
2. **The derive answers per (t, c).** A piece request carries its moment
   and channel; the composer reads the one (t, c) frame of each tile it
   composes — which the chunk layout makes a single-file read by
   construction. No cross-moment, no cross-channel arithmetic exists
   anywhere, so this is address plumbing, not new truth.
3. **Dirty footprints carry (t, c).** A landing in moment m, channel k
   dirties pieces of exactly (m, k) — a landing in one moment leaves every
   other moment's pieces untouched, which becomes a gate before it becomes
   a feature. A replacement dirties every published moment of that
   position (the manifest already says so); the spike is O(moments) and
   its size is already pinned at the record layer.
4. **The bake follows the moment being written.** Per landing, the bake
   patches the touched pieces of the landing's own (t, c) only — so the
   per-landing bake bill does not grow with the length of the timelapse.
   Old moments bake on first visit (the cold-open posture the closing plan
   already recommends), and that choice gets a cold-open test before it is
   trusted. Whether both channels of the current moment stay baked-warm
   together is a ladder measurement, not an argument: channels are few and
   viewed together, moments are many and viewed one at a time.
5. **The time slider ends at the declaration.** The live picture's slider
   ranges over declared room but marks written moments from the collection
   declaration's per-member moment counts — an operator can see how far
   the run has come without the slider running off into moments nobody
   imaged.

## An open decision this plan inherits from the depth reviews

Both independent reviews of the depth plan flag the same collision, and it
belongs to time more than to depth: **the declared room meets the
open-ended timelapse.** The declare-the-full-room rule assumes the profile
knows how many moments the acquisition will have, and a "run until
stopped" acquisition does not — while the writer refuses commits beyond
the declared moments, so declaring short is a run that stops early, and
declaring generously is a slider mostly full of never-imaged room. The
rule for this must be STATED before anything is built: either the
controller always declares a generous ceiling and stopping early is
ordinary (absence already expresses it, and the slider marks written
moments, so the operator never sees the empty tail as ground) — or time is
the one axis where a description may grow, with the reload-to-see-it cost
that was measured and rejected for y and x. This plan leans to the first,
but leaning is not deciding, and the decision is the reviews' to force.

## The one scaling term to instrument first

Time multiplies stored pieces; it must not multiply any per-landing cost.
The instrument comes first, as always: the ladder gains a moments column —
land into moment m of a survey that already holds m − 1 written moments,
and the landing/derive/bake numbers must match the single-moment table
(196–210 ms landing, flat) with the moment count varied. The one known
O(moments) event is the replacement spike, already pinned; nothing else may
scale with t, and the gate that says so is red-provable by making the bake
touch a neighbouring moment on purpose.

## How we will know it is done

Every browser gate here is a Playwright test, and every one measures the
same four-square grid — because the two postures catch different diseases,
and the F5 comparison is the oracle for both:

|                    | before F5 (warm)            | after F5 (fresh)          |
|--------------------|-----------------------------|---------------------------|
| **held view**      | growth appears unasked      | must equal the warm shot  |
| **scrolling around** | no stale or dark ground   | must equal the warm shot  |

A held view — hands off, no navigation at all — is the hard test for
in-place refresh, because navigation asks fresh questions and quietly
repairs staleness: the Thy1 announce-word bug was invisible to anyone who
scrolled and obvious to anyone who held still. Scrolling and zooming
during landings is the hard test for the refresh machinery under fire,
because that is where the original black stripes lived. And in both
postures the warm picture is photographed BEFORE a reload and compared to
the same view AFTER one: if F5 changes anything (once both sides are fully
loaded, per the storm census rule), the held page was lying, however
plausible it looked. Pressing F5 must never be a repair tool — that
sentence is the assertion, in every gate, in both postures.

The existing gates grow axes rather than new machinery, in the depth plan's
own pattern — `test_a_built_picture_grows_while_watched.py` is the held-view
template and `test_a_commit_storm_under_zooming.py` the scrolling one, and
each (t, c) gate below states which posture it runs, or runs both:

- **grows-while-watched, per moment**: hold the view on moment m while
  landings arrive in it — they appear within the flat picture's bound;
  switch the slider to m − 1 — nothing there has moved, byte for byte.
- **warm equals reload, across (t, c)**: the pixel census runs at several
  zoom bands, on both channels, on at least two moments.
- **the spiral with colours, on screen**: the record-level colours-and-
  moments tests gain their browser half — the seeded centre grows outward
  in one channel while the other channel and the previous moment hold
  still.
- **the storm rate holds** with two channels: twenty commits a second was
  the flat bar; the (t, c) plumbing must be measured against the same bar,
  not assumed past it.

## Test economics: small first, fast always, the big one opt-in

Every correctness gate here runs on synthetic data, and the loop must stay
fast enough to iterate in — a suite someone waits half an hour for is a
suite that stops being run, and then it guards nothing. The budgets are
part of the plan, not a hope:

- **Arithmetic and record-level tests in milliseconds to seconds.** Spiral
  walks, dirty footprints, moment-untouched byte comparisons — no browser,
  tiny frames, the pattern the colours-and-moments tests already set.
- **Browser gates under ninety seconds each**, on the smallest survey that
  can exercise the claim — 4x4 and 8x8 grids, two channels, two or three
  moments, small frames. Start at the smallest size that can possibly show
  the basics working, and only grow a fixture when a specific claim needs
  the size; the storm gate earns its 40x40 because rate-under-fire IS its
  claim, and nothing else inherits that scale by default.
- **One heavyweight fixture, linked, and opt-in.** The Thy1 evening showed
  the trick: one real volume laid out 49 times through links cost 195 KB.
  The synthetic version is better still — build ONE volume of a gigabyte
  or two, once, full of delicate structures chosen so that mistakes are
  visible (gradients that make any misplacement obvious, fine grids that
  blur if a level lies, point sources that vanish if a plane is dropped,
  per-channel and per-moment signatures so the wrong (t, c) can never
  masquerade as the right one) — and link it into as large a survey as
  the test wants for kilobytes. Every pixel has a known right answer by
  construction. This fixture backs the occasional big run — the ladder, a
  soak, a scale question — behind an environment knob, never in the
  default suite, and it is written once to a durable folder and reused,
  the scale-harness rule this repository already lives by.

The gates prove correctness at small scale; the ladder proves cost at
large scale; nothing waits on both at once.

## What is deliberately not in this plan

- No z — that is the depth plan, reviewed separately; the two share only
  the declare-the-room rule and must not gate on each other.
- No multi-moment compositing (temporal projections, motion overlays):
  views may one day compute them, but the served picture answers one
  (t, c) at a time, full stop.
- No channel merging in the server. Colours meet only in the compositor of
  the viewer, where each keeps its own contrast — the refusal to collapse
  colours retires by being made unnecessary, not by being weakened.
