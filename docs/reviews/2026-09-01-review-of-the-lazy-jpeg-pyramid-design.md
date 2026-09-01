# Review of "A lightweight JPEG pyramid for the ZMART browser viewer"

**Date:** 2026-09-01.
**What was reviewed:** `docs/design/lazy-jpeg-pyramids-for-the-viewer.md` at
commit `d8a67923` ("expand lazy JPEG viewer design") on branch
`claude/viewer-port-remaining-steps-ofm5qp`, against the brief in
`docs/design/lazy-jpeg-pyramids-review-prompt.md` on the same commit. Neither
file is on `main`, so a reader on this branch should have that branch open
beside them.
**ZMART Viewer inspected:** `thomdehoog/zmart-viewer`, commit `9ff10b0`,
version 0.2.0 — the same commit the earlier integration review names, cloned
fresh for this review rather than inferred from the older copy under
`viz_studio/backend/`.
**Verdict, in one line:** revise before measuring. The design is careful and
well written, but it argues from a cost that the current path no longer has,
and Smart Viewer 0.2 has already published measurements that answer its central
question.

Everything asserted below was checked in one of the two repositories, and the
file and line are named each time so the check can be repeated. Where something
is an inference rather than a reading, it says so.

---

## The short version

This is a good document. It is honest about what it has not measured, it names
its rejected shortcuts, and several of its rules — no silent fallback, no
per-tile stretch, no JPEG built from a JPEG, both a relative and an absolute
cache cap — are exactly right and worth keeping whatever happens next.

But the plan is aimed at a problem the project has already moved past, and
building it would give ZMART a second production display format at the moment
the viewer's own plan is to remove the first one. The most valuable thing in
the whole proposal is not the JPEG pyramid; it is the section on the encoding
window, which describes a real gap in what a ZMART run records today and which
is worth closing on its own.

---

## 1. Blocking findings

### 1.1 The measurement the design is built on belongs to an engine that is no longer drawing the canvas

The opening section says the problem is that "at roughly 8,400 fields, every
field asks for its own picture and the queue resolves in scan order". That
observation is real, and it is recorded in `application/PLAN.md` under "Found on
the way". But read what it was observed on: the one-JPEG-per-field path in
`viz_studio/backend/jpeg_tiles.py`, whose small pictures are 128 pixels a side
(`SMALL_ENOUGH`, line 92) and which makes exactly one of them per field.

That path is not what draws the operator's canvas. The canvas opens
`neuroglancer-under` — one named line, at
`application/workflows/target_acquisition/shared/stage.js:87` — reading the
run's own OME-Zarr positions. The JPEG engine was deliberately taken off the
canvas, and section 5 of
`docs/reviews/2026-09-01-why-the-acquired-overview-never-appeared.md` explains
why in terms this proposal itself repeats: it drew *as well*, so a pipeline that
had never worked looked healthy.

So the design's first paragraph attributes to "the current path" a cost that
belongs to a reference engine. That matters, because the current path was
measured and it does not have that cost.

**What Smart Viewer 0.2 actually does.** `zmart_viewer/compose.py` opens with
this, and it is the design's own goal stated as an accomplished fact:

> Every tile carries its own stage corner; the arrangement follows. Tiles land
> at fractional offsets, so pieces are built — the tiles covering a piece are
> read at the level being drawn, laid into one array, encoded — never pointed
> at. Slabs are cached and tiles indexed per level, so cost per piece stays flat
> with survey size.

**And what it has measured.** From
`docs/measured/MEASURED_the_ladder_of_surveys.md` (the viewer's own harness,
2026-08-13, a Linux container drawing in software), a survey growing from 64 to
32,761 positions:

| positions | one landing, painted | one derive |
|---:|---:|---:|
| 64 | 138 ms | 24 ms |
| 1,024 | 143 ms | 72 ms |
| 8,281 | 176 ms | 138 ms |
| 16,384 | 208 ms | 238 ms |

And from `docs/open/MEASURED_the_four_ways_of_serving.md` (2026-08-30), one more
position landing on a warm survey, and the cost of serving a settled one:

| positions | derive for one landing | tiles re-read | warm median per piece, baked |
|---:|---:|---:|---:|
| 400 | 11 ms | 0 | 0.15 ms |
| 2,500 | 25 ms | 0 | 0.15 ms |
| 10,000 | 76 ms | 0 | 0.15 ms |

Zero tiles re-read at every size, with a test named after it
(`test_one_more_landing_reads_one_tile_no_matter_the_survey`). This is the
relationship the design's phase 2 gate proposes to establish, already
established, in the path the design proposes to sit beside.

**Two honest caveats, in the design's favour.** These are the viewer team's own
numbers, taken on synthetic fixtures in a container with software rendering, not
on ZMART runs and not on the microscope PC — so they rank things reliably and
their absolute milliseconds do not travel. And they do show one cost that still
grows with survey size: the one-time *bake* and *warm* (149 s and 107 s at
8,281 positions; 312 s and 214 s at 16,384). That is a real remaining problem,
and it is the one a lazy scheme would genuinely help with.

**What to do.** Rewrite the problem statement around what remains after 0.2,
which on present evidence is the one-time bake and warm, not per-view or
per-landing cost. If after reading those documents there is still a viewport
cost worth a new format, say which number in them is the unacceptable one.

### 1.2 It builds the second production display path that both repositories have decided not to have

The brief says to reject any arrangement that quietly creates a second large
persistent dataset or a second independent production viewer backend. The design
acknowledges this and answers it with an ownership boundary, but the boundary
does not remove the duplication — it only decides who maintains it.

The viewer's own plan runs the other way.
`docs/open/PLAN_one_door_one_source.md` says, at lines 31–34, that the same
canvas is later "embedded in the operator window in place of the JPEG overview",
and at 322–325 that replacing the JPEG overview should be "an embedding task,
not another refactor". `PLAN_two_viewers_one_contract.md` carries the same
intent. This design would install a new JPEG overview in the operator window at
the moment the viewer is preparing to take the old one out.

There is also a plainer point about total work. A second path means a second
grid, a second manifest, a second cache with its own eviction, a second live
invalidation scheme, a second renderer, and a second set of geometry tests — all
for pixels that the existing path already delivers. The proposal is honest that
this is the risk; it does not show what makes it worth paying.

### 1.3 Area averaging would put the JPEG pyramid out of registration with every other pyramid in the project

This is the finding most likely to cost weeks if it is missed, because it
produces a picture that looks right.

The design names area/box averaging as "the reference resampler" and offers max
pooling as the alternative to test. Neither is what this project does. Every
pyramid in both repositories shrinks by **keeping every second pixel** —
decimation — and it is a deliberate, load-bearing choice, written up three
times:

- `zmart_storage/positions.py:139–142` — "shrinking here keeps every second
  voxel rather than averaging four, so a voxel of a position's smaller copy is a
  voxel of the whole picture's smaller copy, and belongs to that one position
  and no other";
- `application/parts/storage/zarr_positions.py:68–77` and line 140, the same
  rule in the position writer;
- `viz_studio/backend/jpeg_tiles.py:252–262`, `_shrink_to`, which strides
  "so nothing is invented that the microscope did not see".

And the viewer states the consequence exactly, in
`docs/how_it_works/HOW_OURS_DIFFERS_FROM_OME_ZARR.md:92–96`:

> a coarse voxel's value is the fine voxel at the *low corner* of the block it
> covers, not the block's average, so a reader that assumes averaging places it
> `(2^k − 1)/2` fine voxels too far along in y and x.

That is the whole finding. A pyramid built by averaging and a pyramid built by
decimation do not agree about *where* a coarse pixel is. At level 6 the
disagreement is 31.5 source pixels, which with the design's own example pixel
size of 0.65 µm is about 20 µm on the stage. The operator's overlays — planned
fields, focus points, detections — are drawn in micrometres over whichever
picture is beneath them, so the two engines would place the same well in two
different places at plate zoom, with nothing on screen to say which is right.
That is the same shape of fault as the four in
`2026-09-01-why-the-acquired-overview-never-appeared.md`: every part reports
success.

**What to do.** Either build the JPEG levels by decimation, so the two paths
agree by construction, or carry the half-block shift in the manifest as an
explicit per-level offset and name the one place that applies it. Whichever is
chosen, add a registration test to the gate: a recognisable feature must land
within one coarse pixel of where the OME-Zarr path puts it, at every level.
This also changes question 3 of the brief — the comparison is not "area versus
max" but "decimation versus area versus max", and decimation is the incumbent,
so it goes in the comparison with its own named failure (a bright spot smaller
than the step simply disappears, and disappears differently at each level).

### 1.4 The encoding window has no source to come from today, and the fallback the design names is a fault this project has already fixed twice

This section of the design is its best thinking, and it is also where it is
furthest from what a ZMART run currently records.

The proposed precedence is: an acquisition-wide window from the recorded preset;
then a run-wide channel description; then "a configured camera range only when
neither of the first two exists".

**The third step must be removed, not kept as a fallback.** A camera range means
the `omero` block's `min` and `max`, and `viz_studio/options/contract.md` §6 is
unusually blunt about it: `min` and `max` are what the camera can produce at
all, a real acquisition sits in the bottom few per cent of that, opening on them
gives "a picture that is very nearly black", and the rule is to fall back to
whatever the option would have done with no description at all — "**never** to
`min` and `max`". The same lesson is written again in
`application/parts/storage/zarr_positions.py:125–129`.

For a *display* window, that fault is recoverable: the operator drags a slider.
For an *encoding* window it is not, because the design bakes it into the JPEG
permanently. Take a specimen occupying counts 100 to 4,500 of a 16-bit camera's
65,535 — the range `zmart_storage`'s own comments describe as typical. Encoded
against the camera range, that specimen's whole signal lands in about 17 of 256
grey levels, roughly four bits, and no later control can bring it back. A cache
generation built that way is scrap.

**And the first two steps do not exist yet.** I could not find an
acquisition-wide or run-wide declared window anywhere in this repository. What
is written is a **per-position** window: `_a_window_onto` in
`application/parts/storage/zarr_positions.py:298`, the 1st to 99.9th percentile
of *that position's own pixels*, stamped into each position's `omero` block. So
on runs as they are written today, the design's precedence falls straight
through to the step that must not exist.

The design is right that "a per-position measurement is not an acquisition-wide
window", and `jpeg_tiles._one_brightening_for_the_whole_scan` already explains
why in the plainest terms in the codebase — brightened per field, "the scan
would read exactly backwards: empty pale, full dark". Whether that currently
bites the OME-Zarr path is worth one check rather than an assumption:
`zmart_viewer/contrast.py` measures a window from a store's smallest written
copy when the store declares none, so a composed picture may well be measuring
its own run-wide window already. Either way, having the run *declare* one
removes a guess.

**What to do.** Make "the run records one display window per channel for the
whole acquisition" a piece of work in its own right, ahead of any of this, and
make the JPEG path *refuse* an acquisition that has none rather than invent one.
This is the recommendation I would keep even if the rest of the proposal is
dropped: it is small, it is useful to the current viewer, and it is a
precondition for any honest 8-bit derivative.

### 1.5 The size budget and the design's own promise pull in opposite directions, and the arithmetic is against the wrong denominator

The caps are defined against "the authoritative acquisition's unique
source-image bytes on disk". The intuition that follows is worked against an
*uncompressed* 16-bit source (`b / 12` bits per sample). Those are different
numbers, and the doc notices — "real TIFFs may already be compressed" — but then
carries on as though the ratio held.

Work it through with the compressed figure. Level 0 of the pyramid holds one
8-bit JPEG sample for every source pixel. If the TIFFs compress about two to one,
the source is roughly one byte per pixel; grayscale JPEG on fluorescence at the
qualities proposed is somewhere around 0.5 to 1.5 bits per pixel, and the whole
pyramid is 4/3 of its finest level. That lands between roughly 8% and 25% of
source — straddling the 10% hard ceiling. The one measured number in the
repository is consistent with a much smaller figure, but it is measuring
something much smaller: `application/parts/canvas/engines.js:32–37` records ten
thousand fields as "tens of gigabytes as TIFFs and about a hundred megabytes as
JPEGs", and those are 128-pixel thumbnails, not a full-resolution level 0.

So the design promises both that close zoom "should reach one source pixel per
screen pixel for only the area being viewed" and that the cache stays under 10%
of source. On a large run those are consistent only because the cache is
partial — meaning level 0 is evicted routinely and re-encoded from TIFF on every
revisit. That may be perfectly acceptable, but it is a different product from
the one the opening section describes, and the doc should say so plainly.

There is also a gap at the small end. The relative cap has no floor, so a
200 MB acquisition is allowed 10 MB. A 512-pixel JPEG tile is tens of
kilobytes; a 2560 × 1440 screen at four channels is on the order of sixty tiles,
before any coarser level. Small runs will thrash. Give the per-acquisition
allowance a floor — "never less than one screenful at every level", a fixed
figure such as 64 MB — and measure it rather than guessing it.

### 1.6 Two of the phase gates cannot fail, and nothing gates the decision the brief actually asks for

The brief asks whether the gates can kill the idea early. Mostly they can, and
phase 0's is genuinely a stop-or-go. Two are weaker than they look:

- **Phase 2's gate** — that going from 1,000 to 10,000 fields does not increase
  requests or decoded memory in proportion to the field count — is a property
  the design guarantees by construction. A tiled pyramid that failed it would be
  broken, not disproved. As written it confirms that the work was done.
- **Phase 3's gate** — that the panel, the engine read-back and the photographed
  pixels agree — is a correctness check, which is valuable, but it cannot end
  the project.

More importantly, **no gate anywhere measures the thing the whole plan turns
on**: whether JPEG beats Smart Viewer 0.2 by enough to justify a second format.
The stop conditions mention it in prose; nothing measures it. Name the margin
now, before any code, in a form that can come back "no" — for example, at least
a five-fold reduction in transferred bytes for a settled whole-plate view at
four channels, *and* a decoded-memory figure below a stated budget, on a real
ZMART run on the microscope PC. If it cannot be stated in advance, that is
itself an answer.

---

## 2. Important corrections that do not block

1. **Two different "middle plane" rules.** The design proposes
   `floor((count - 1) / 2)` as the anchor for a legacy stack with no recorded
   reference plane. The project already has such a rule:
   `theMiddlePlaneOf` in `viz_studio/options/planes.js:55–57` returns
   `Math.floor(n / 2)`. For every even-length stack these disagree — for the
   twenty-two-plane stack in the overview write-up, plane 10 against plane 11.
   Reuse the existing function, or change both together and say why.

2. **The half-voxel claim is the load-bearing sentence in the Z section and it
   cites nothing.** "The current trace proves one boundary correction: the flat
   source renders when its sole voxel centre is sampled at local `z=0`, while
   `z=0.5` samples the upper boundary of that voxel." This is stated as proven,
   but no file, test, or photograph is named, and the two engines this project
   draws with need not share the convention. Name the evidence, and express the
   correction as one constant in one place with a test that fails if the
   convention is flipped.

3. **The caching proposal is already written, with its reasoning.**
   `viz_studio/backend/server.py::_how_long_to_keep` (lines 638, 660–680) already
   implements exactly the three-way policy the design describes — `no-cache` for
   the small files that describe a store, `no-store` for image data during a
   live run, and `max-age=31536000, immutable` for finished data — and it
   explains why live image data is `no-store` rather than `no-cache`. The design
   should cite it and say what it is changing rather than proposing it fresh.

4. **The browser side currently opts out of caching on purpose.** Every option
   fetches with `cache: "no-store"` (`jpeg-under/viewer.js:330`,
   `neuroglancer-under/viewer.js:966`, `viv-under/viewer.js:810` and `:1417`),
   and the bridge sends `Cache-Control: no-store` on every view file
   (`application/framework/bridge.py:1165`). ETag revalidation will do nothing
   until those call sites change. Worth one line, because it is the kind of
   thing that is discovered after the transfer measurements look wrong.

5. **`tilesMayHaveLanded` takes an argument.** All four options implement
   `tilesMayHaveLanded({ coverage })`. The design writes it as
   `tilesMayHaveLanded()`. Small, but the coverage record is the very thing the
   design relies on to tell unimaged ground from acquired black, and it is
   already threaded through to `paintUnder`/`paintOver`.

6. **The WebView2 check already exists.** `viz_studio/backend/launcher.py:25`,
   `_webview2_present`, checks for the runtime on Windows. The design asks for a
   startup capability check; half of it is written. The WebGL2 half is the new
   part.

7. **The renderer section should say why not Viv.** `viv-under` already draws
   this project's pictures with `OrthographicView`, `MultiscaleImageLayer` and
   `ColorPaletteExtension` (`viz_studio/options/viv-under/viewer.js:91–95`),
   which is per-channel window, colour and additive blending on deck.gl,
   already meeting the option contract. The design proposes to write a new
   shader extension without mentioning it. There is probably a good answer — a
   JPEG decodes to an `ImageBitmap` that uploads straight to a texture, where
   Viv's layer wants typed arrays and would need a read-back — but the answer
   should be in the document, because it is the first question anyone will ask,
   and because the read-back cost is itself measurable.

8. **The package versions can be confirmed now.** `application/package.json` and
   its lockfile pin `@deck.gl/core`, `@deck.gl/geo-layers` and `@deck.gl/layers`
   at exactly 9.3.7, the `@luma.gl/*` packages at 9.3.6, and `@vivjs/*` at
   0.22.0. `TileLayer` lives in `@deck.gl/geo-layers`, which is present. (Read
   from the manifests: `node_modules` is not installed in this container, so
   this is a reading of what is pinned, not of what is on a machine.)

9. **One genuine win the design does not claim.** The current small pictures
   fold every channel into one greyscale brightest-of
   (`jpeg_tiles._flatten`, listed as open in `application/PLAN.md`). One pyramid
   per logical channel fixes that by construction. It is worth saying, because
   it is a real improvement over the thing being replaced.

---

## 3. Claims I checked and agree with

- **The TIFFs are authoritative and nothing may measure from a JPEG.** Right,
  and consistent with `focus_score.what_was_captured` having moved the other
  way — towards the run's own store — for the same reason.
- **A TIFF does not reliably say where the stage stood; placement comes from the
  record.** Right, and `application/PLAN.md` records the matching open item:
  `image_to_stage` is assumed to be identity in
  `parts/microscope/detection.py`, while the Leica keeps its turn in
  `orientation.json`.
- **No silent fallback.** The strongest rule in the document, and it is
  supported by the most expensive fault in the project's history — section 5 of
  `2026-09-01-why-the-acquired-overview-never-appeared.md`.
- **No per-tile or per-level stretch.** Right, and
  `jpeg_tiles._one_brightening_for_the_whole_scan` is the existing statement of
  why.
- **Never build a parent JPEG from child JPEGs.** Right.
- **Atomic publication, and a failed generation leaving no final file.** Right,
  and it matches how the run writers already behave.
- **Addresses are server-issued and every integer is range-checked.** Right, and
  it matches contract §3, which exists because an engine given a bad address
  waits for ever rather than complaining.
- **The grid origin cannot move during a live run.** Right, and the reason is
  already on record: the relink storm in section 2 of the overview write-up,
  where changing addresses produced several 403s a second for a whole run.
- **A bounded failure rather than an endless loading promise.** Right — "a
  promise that never settles looks exactly like loading" is this project's own
  sentence.
- **PyWebView must be Edge Chromium/WebView2, and an IE/MSHTML fallback is not
  acceptable.** Right, and already assumed by `launcher.py`.
- **Unimaged ground and acquired black are different facts.** Right, and the
  coverage record that keeps them apart already exists.

---

## 4. A simpler alternative

Aim at what is actually left, in this order, stopping as soon as it is enough.

1. **Read the viewer's own measurements before taking any new ones.**
   `docs/measured/MEASURED_the_ladder_of_surveys.md` and
   `docs/open/MEASURED_the_four_ways_of_serving.md` in `zmart-viewer` at
   `9ff10b0` already answer "does the work follow the viewport" up to 32,761
   positions. This is an afternoon, and it may remove most of the plan.

2. **Give the run one declared display window per channel, for the whole
   acquisition.** Small, useful to the viewer that exists today, and a
   precondition for any 8-bit derivative. This is finding 1.4, and it is worth
   doing whatever happens to the rest.

3. **If the remaining pain is the one-time bake and warm** — which is what the
   ladder actually shows growing with survey size — make *that* lazy, in the
   viewer, where the composer already builds pieces on demand. The gap is that
   the coarse end is baked eagerly; making it lazy is a far smaller change than
   a second format and it keeps one path.

4. **If the remaining pain turns out to be bytes on the wire** to a browser
   away from the microscope, the smallest form of this proposal is a
   display-only 8-bit encoding of the *existing* piece route — the same grid,
   the same manifest, the same live invalidation, one extra content type — not
   a parallel grid, cache, manifest and renderer.

The design's own list of rejected shortcuts is good enough that it should
include one more: **a second display format for a cost that has not been shown
to remain.**

---

## 5. Recommended changes to the phase order and gates

- **Phase 0's first task becomes reading, not running.** Read the viewer's
  recorded measurements and write down which of them still needs repeating on
  ZMART data and on the microscope PC. Then repeat only those.
- **Move the encoding-window question into phase 0.** If the run has no
  acquisition-wide window to declare, everything after phase 0 is built on a
  number somebody invented. Decide it before generating a single tile.
- **Add a margin gate between phase 0 and phase 1** that can return "no": state
  now, in numbers, how much better than 0.2 the JPEG path must be to justify a
  second format, on transferred bytes and on decoded memory, for a settled
  whole-plate view at four channels.
- **Replace phase 2's gate.** Instead of a property the design guarantees by
  construction, compare against `neuroglancer-under` and `viv-under` on the same
  run at the same screen size, with `viz_studio/options/measure/run.py`, which
  is the program that already produces that comparison.
- **Add a registration gate wherever the resampler is chosen** (finding 1.3): a
  recognisable feature must land within one coarse pixel of where the OME-Zarr
  path puts it, at every level.
- **Fold phase 5's boundary work forward.** The design already says the viewer
  repository must be open beside this one before phase 3. Given findings 1.1 and
  1.2, that conversation belongs before phase 1, not before phase 3.

---

## 6. Short answers to the brief's fourteen questions

1. **Does a global JPEG pyramid remove the 8,400-field problem, or is there a
   cheaper correction?** There is a cheaper correction, and it is already made:
   the problem was measured on `jpeg-under`, and 0.2 composes pieces on demand
   with cost per piece flat to 32,761 positions (finding 1.1).
2. **Is the stable channel-wide 8-bit encoding truthful and useful?** The
   principle is right; the sources it proposes to read do not exist yet, and its
   named fallback is a known fault (finding 1.4). What would disprove it: a
   ZMART fluorescence field whose dim structures fall below one grey level under
   the declared window, photographed beside the same field from the TIFF.
3. **Area downsampling versus max?** The comparison is missing its incumbent.
   Decimation is what both repositories do, and it is the only one of the three
   that keeps the JPEG pyramid registered with the OME-Zarr one (finding 1.3).
   Failures to name: area dims isolated puncta at plate scale; max grows hot
   pixels and makes brightness jump between levels; decimation drops a punctum
   smaller than the step entirely, and drops a different set at each level.
4. **Is the live algorithm sound?** Yes, in outline. A bounded transient
   lossless tile in RAM is the right shape and does avoid both the O(total
   fields) rebuild and cumulative JPEG damage. It needs reconciling with two
   existing facts: the thirty-second relink damper
   (`A_PICTURE_MAY_STAND_FOR` in `application/parts/storage/viewer_service.py:86`)
   and the actual `tilesMayHaveLanded({ coverage })` signature.
5. **Is a partial LRU disk cache acceptable, and are 5/10 GiB right?** Partial
   is acceptable and the two-cap rule is right. The defaults cannot be judged
   until the caps are computed against compressed source bytes, and the
   per-acquisition cap needs a floor (finding 1.5).
6. **Is one TileLayer per channel with a BitmapLayer shader the smallest
   renderer?** Unproven, because the document does not say why not Viv, which is
   already installed at 0.22.0 and already draws this project's pictures
   (correction 7). Versions are pinned and checkable now (correction 8).
7. **Does it preserve placement, orientation, live extent, z/t, retakes, and
   acquired-black?** Almost. The gap is the resampler's half-block shift
   (finding 1.3); the rest is handled carefully, and the affine transform in
   place of an implicit top-left convention is a good decision.
8. **Can it work in the supported PyWebView engine?** Probably, and half the
   check is already written (correction 6). What must be measured on the
   microscope PC: WebGL2 presence, the maximum texture size, and decoded-image
   memory with four channels at the chosen tile size.
9. **Where should generation and serving live?** In ZMART Viewer, and the design
   says so. But the viewer's own plan is to remove the operator's JPEG overview
   rather than to grow a new one (finding 1.2), so the ownership question is not
   "which repository" but "does this path exist at all".
10. **Does explicit selection avoid the old silent-fallback failure?** Yes, and
    this part is well done. Keep the requirement that a deliberately broken JPEG
    path produces a visible failure in the phase 5 gate exactly as written.
11. **Can the gates kill the idea early?** Phase 0's can; phases 2 and 3's
    cannot, and nothing gates the comparison the whole plan rests on
    (finding 1.6).
12. **What failure is missing?** Two. A source whose window changes between
    generations — the design forbids mixing profiles within a channel view but
    does not say what happens to tiles already on disk when a run's declared
    window is corrected mid-flight. And a cache root shared by two ZMART
    processes on one microscope PC, where two independent eviction loops can
    each believe they are under the ceiling.
13. **Is the Z model correct?** The separation of acquisition Z, source-local Z
    and presentation Z is right, and keeping acquisition Z recoverable is right.
    The anchor-to-`z=0` rule is right for a flat map. What remains ambiguous is
    the half-voxel claim, which is asserted rather than shown (correction 2), and
    the middle-plane rule, which contradicts the existing one (correction 1).
14. **Should a one-plane source stay pinned while a stack is navigated?** Yes,
    and the contract supports it: plane selection is navigation, and
    `viz_studio/options/planes.js` already holds the fact that which plane an
    option opens on is not part of what is being compared. Per-source plane
    selection is session state and should not be built until an operator asks
    for it.

---

## 7. Verdict

**Revise before measuring**, then proceed to a re-scoped phase 0 only.

Do not start phase 1. The document should be rewritten around three things: the
problem that remains after Smart Viewer 0.2 rather than the one measured on
`jpeg-under`; a resampler that keeps the JPEG pyramid registered with everything
else; and an encoding window that a run actually declares. If after that
rewriting the case still holds, the plan is a good one and its phases are
sensibly ordered.

If only one thing is taken from this review, take finding 1.4. A run that
declares one display window per channel for the whole acquisition is worth
having whether or not a single JPEG pyramid is ever built.
