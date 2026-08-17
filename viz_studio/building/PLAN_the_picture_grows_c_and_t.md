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

The existing gates grow axes rather than new machinery, in the depth plan's
own pattern:

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

## What is deliberately not in this plan

- No z — that is the depth plan, reviewed separately; the two share only
  the declare-the-room rule and must not gate on each other.
- No multi-moment compositing (temporal projections, motion overlays):
  views may one day compute them, but the served picture answers one
  (t, c) at a time, full stop.
- No channel merging in the server. Colours meet only in the compositor of
  the viewer, where each keeps its own contrast — the refusal to collapse
  colours retires by being made unnecessary, not by being weakened.
