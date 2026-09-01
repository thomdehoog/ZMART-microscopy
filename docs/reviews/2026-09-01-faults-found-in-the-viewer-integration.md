# Every fault found while getting the viewer into the operator window

**Date:** 2026-09-01.
**Repository:** `thomdehoog/ZMART-microscopy`.
**Smart Viewer:** a separate repository, `thomdehoog/ZMART-viewer`, commit
`9ff10b0`, version 0.2.0, cloned here at `/home/user/thomdehoog/zmart-viewer`.
Install it with `pip install --no-deps -e .`; a plain install stops on
`proxy_tools`, which arrives through `pywebview` and which the server does not
need.
**Branches:** `claude/viewer-port-remaining-steps-ofm5qp` (the eight steps and
the canvas fallback), `claude/every-field-reaches-the-canvas` (superseded by
PR #24), `claude/step-five-kidney-evidence` (the Step 5 evidence run).

This is a list of the things that were actually wrong, written so that somebody
working on the same code can check whether each one is still wrong for them. It
is not a summary of what was built; that is in
`2026-09-01-review-prompt-for-claudes-work.md`.

---

## The thing they nearly all have in common

Almost every fault below made the window look **quiet rather than broken**. The
canvas was blank, or a picture was dark, or a slider did nothing much, or a
count said nine when four had been drawn. Not one of them raised an error, and
several of them passed their own tests.

That matters for how you look for them. Reading the code will not find a fault
whose whole signature is that nothing happens, and neither will a green test
suite, because a check written against the same misunderstanding as the code
agrees with it. The faults in this list were found, with two exceptions, by
**running the workflow and looking at the screen** — and the two that were found
by reading were both the least serious ones.

So the practical advice, before the list: run the real walk, take photographs,
and then look at the photographs properly. Three of the faults below were
sitting in screenshots that had already been taken and sent on, mine included,
and went unnoticed because nobody enlarged them.

---

## 1. Open, and the most serious

### 1.1 The picture is drawn in the wrong place on the stage

**This is the important one.** After a nine-field scan of a slide, the composed
picture is drawn roughly **23.3 mm to the right and 29.4 mm below** the planned
positions — far enough that it lands off the slide altogether.

Measured from `test-results/step-five-kidney/whole-plate.png`, with the canvas
zoomed out to Fit:

| | on screen | in millimetres |
|---|---|---|
| Scale bar | 50 mm across 135 px | 0.370 mm per pixel |
| Slide outline | 199 × 63 px | 73.7 × 23.3 mm — correct for a 75 × 25 mm slide |
| Plan (scan area) | centre at (409.5, 164.5) px | about 3 mm across |
| The drawn picture | centre at (472.5, 244.0) px | 3.0 × 3.3 mm |
| **Difference** | **+63, +79.5 px** | **+23.3 mm, +29.4 mm** |

Two things follow from those numbers, and both narrow the search a great deal.
The slide outline comes out at its true physical size, so the canvas's
millimetres-to-pixels scale is right. And the picture's own extent, about three
millimetres square, is what a three-by-three block of roughly one-millimetre
fields with a little overlap should be — so the nine tiles are being stitched
together correctly, at the correct size, relative to each other. **Only the
origin is wrong.** This is a translation, not a scaling or a rotation.

**How to see it for yourself.** Run the Step 5 walk, then press Fit and set the
overlay fade to about 0.15 so the plan is faint but visible. The picture will be
a speck several centimetres away from the plan rectangle. It is small at that
zoom, so enlarge the region rather than trusting a glance at the full
screenshot.

**Not yet diagnosed.** The offset does not obviously correspond to a slide
dimension or to a flipped origin, and guessing would waste your time. The one
measurement that settles it is to put two numbers side by side, in micrometres,
on a live page: the image-space origin the engine reports for the `overview`
source, and `window.__theStageCanvas.plan()[0]`. That says immediately whether
the viewer is placing the composed scene wrongly, the adapter's transform is
wrong, or the plan and the mock instrument's stage disagree about where zero is.

### 1.2 The engine's opening view replaces the operator's framing

When an acquisition lands, the drawing engine's own opening view takes over, and
whatever the operator had framed is lost without a word. In the Step 5 run this
left the canvas showing a region about 0.66 mm across — the scale bar read
200 µm — while the plan sat some 37 mm away, entirely off screen.

This is a real annoyance in its own right: an operator who has spent a minute
framing their plate should not lose it because a field finished exposing. But it
is on this list mainly because **it is what hid fault 1.1**. Had the view stayed
on the plate, the misplacement would have been obvious in the very first
screenshot rather than surviving a whole session.

### 1.3 Nothing yet proves the picture lands where the plan says

`the-scan-under-the-plan.spec.js` is the check that would settle registration,
and both of its tests time out at
`waitForFunction(() => !!window.__thePicture)` — the picture never opens in that
harness, so the comparison it exists to make is never reached. Verified
identical at `93e374c`, so this predates all of the work described here.

Two warnings attached to it. First, this was misread once during the session as
"the registration check confirms the picture is misaligned"; it confirms
nothing, because the assertion does not run. Second, repairing this harness is
the cheapest route to a standing guard against fault 1.1 coming back.

---

## 2. Checks that pass without checking anything

These are worth their own section because they are the reason the faults above
survived. A check that cannot fail is worse than no check, since it is also a
claim that somebody looked.

### 2.1 A field that is off screen is skipped rather than failed

In `application/step-five-kidney-evidence.spec.js`, the per-field measurement
does this:

```js
const inside = whatIsInside(pixels, field);
if (!inside) continue;
```

`whatIsInside` returns `null` when the field's projected box falls outside the
photograph. So a field nobody could see is quietly passed over, and the
assertion that follows — `expect(thin, "every planned field carries picture")
.toEqual([])` — is satisfied by an empty list. **The check cannot tell "all nine
fields were drawn" from "not one field was even looked at."**

In the run that was reported as passing, the second of those is what happened:
the view was 0.66 mm across and the plan was 37 mm away, so all nine boxes were
off screen and both assertions passed on empty lists. The fix is that a field
which cannot be measured must fail rather than `continue`, and the measurement
must be taken at a view that actually contains the plan.

### 2.2 Measuring inside a wall of picture proves nothing

The same spec asks how much of each field's square carries picture and how many
distinct shades it holds. Both are sensible questions, and both become
meaningless when the view is zoomed so far in that a single field fills the
whole canvas: every box lands inside a solid expanse of tissue and comes back
100 % covered and richly textured, wherever it was placed.

If you are checking that fields landed where they were planned, the photograph
has to be taken at a zoom where the fields are distinguishable from one another
and from their surroundings.

### 2.3 Counting a scan finished is not counting a scan drawn

A scan of nine fields that drew four reports "9 / 9 tiles" and, from far enough
away, looks exactly like one that drew all nine. Any check on this path must
measure each planned field **separately**; a total, an area, or a screenshot
comparison at plate scale will not distinguish them.

### 2.4 A check pinned to a run whose acquisitions happen to have one colour each

Two panel checks counted their way to the eye they wanted, which worked only
because the mock's acquisitions each had a single channel. Fixed in `5376b7f`:
each eye now says which row it belongs to, and the contrast check asks for two
fixed values rather than for "thirty more than wherever the handle is".

---

## 3. Fixed on these branches

### 3.1 The plate, the plan and the focus points drawn at NaN

**Commit `4ab5903`.** Every layer the operator draws on is positioned in
micrometres on the sample and has to be turned into a place on screen. That sum
belonged entirely to the drawing engine — right while there is a picture, since
the engine is placing the picture too and the two must agree to the pixel.

But neuroglancer takes its axes from its image layers, so before a run has
captured anything it has no coordinate space at all and answers every question
about position with `NaN`. The first four steps of a workflow are exactly that
situation by definition: an operator lays a plan out on an empty plate.

What it looked like was an empty canvas. Every layer was present and switched
on, each drawn at nowhere. The only thing that appeared was the scale bar,
because a scale bar is measured in screen pixels and needs no such sum. **The
canvas looked quiet, not broken.** After the fix, a planned field at
(17324, 17324) µm lands at (123.3, 123.3) on screen.

This is also the riskiest change of the session and deserves an adversarial
read — particularly `whoeverCanPlaceThingsHoldsTheDrags`, and the question of
whether the canvas's copy of the view can drift from the engine's while the
engine is the authority.

### 3.2 Lending a drag to a tool stopped working

Found while making 3.1. The first attempt attached a second pair of pan and zoom
gestures without deciding which pair was in charge, and drags that a tool had
borrowed silently stopped reaching it — four checks in
`parts/canvas/canvas-layers.spec.js` went red. The rewrite has exactly one of
the two sets listening at any moment. Worth knowing about if you touch that area
again, because the symptom is once more that something simply stops happening.

### 3.3 Hiding an acquisition could hide it permanently

**Commit `5376b7f`.** The panel's `refresh` drew each eye from what the picture
was really doing, which is correct, and *also* wrote that back into each row as
though it were the operator's own choice. So while an acquisition was hidden,
every one of its channels was recorded as one the operator had turned off, and
opening the acquisition again asked for nothing at all. The heading's eye opened
over a picture that stayed dark.

The two questions are now kept apart: what is drawn is always read from the
picture, and what the operator chose is only taken from the screen while the
acquisition is being shown at all. This was already failing before the work on
this branch.

### 3.4 The contrast slider had about two pixels of usable travel

**Commit `5376b7f`.** With no measurement available, the brightness and contrast
tracks ran over the whole of what a sixteen-bit camera can produce. Real
acquisitions occupy a small part of that, so the entire usable range of the
slider was a couple of pixels wide and the control appeared to do nothing.

They now fall back to the window the run itself declared, which says roughly
where the signal is. Measured on the mock's own overview, that is a track of
0–3,800 rather than 0–65,535.

### 3.5 The colour chooser opened off the edge of the window

**Commit `5376b7f`.** The panel stands against the right-hand edge, and naming
the colour maps made the list wider than the plain colour names had been, so it
hung 77 px past the edge of the window. It now opens to whichever side has room.

### 3.6 One field of many reaching the canvas

**Commit `d84c684`, on `claude/every-field-reaches-the-canvas` — superseded by
PR #24, and that branch should not be merged.**

The viewer can put several addresses under one heading for two quite different
reasons, and the answer looks the same either way. One means "here is the same
picture again, opened afresh", and only the last of those can still be read. The
other means "here are the fields this one picture is made of", and every one of
them is wanted. The old rule kept exactly one address, which was right for the
first reason and threw away fifty-three fields out of fifty-four for the second.

The reasoning is sound and PR #24 carries it forward, having also found the part
that was actually missing: the bridge froze the answer from the first
`/api/stores/open` call and never asked again. Two honest notes on the
superseded branch — its commit message is more confident than the evidence
supported, having been written before the change was run in the real walk, and
its test wording calls several position-store addresses a "composed
acquisition", which is wrong. A composed scene is normally one
`*.zmartview.zarr` address; these are a watched multi-store acquisition.

---

## 4. Open, smaller

- **A thirty-second timeout on a one-and-a-half-second poll.** `_read` in
  `application/parts/storage/viewer_service.py` waits up to thirty seconds while
  the operator polls every one and a half. If `/api/config` ever slows down,
  requests pile up, and the bridge is threaded, so slow polls become threads
  queued against the viewer. A short timeout would degrade to "keep the last
  usable list", which the code already handles. This is the one thing worth
  asking for before PR #24 merges.
- **A rerun is not exercised.** `opened` is held for the life of the service, so
  *Run again* never reopens a folder. New stores are picked up by the viewer's
  own watch, but a rerun that replaces stores under the same names relies on the
  viewer noticing changed bytes, and nothing tests that.
- **Twenty-seven channel rows under one heading.** With every field passed
  through, the engine holds nine `overview` sources of three channels each, and
  the panel lists all twenty-seven under a single `overview` heading.
  Functionally correct, and it reads as a fault to anybody looking at it.
- **`test_no_option_decides_for_itself_which_plane_to_open_on` fails**, and
  failed before any of this work: `neuroglancer-under/viewer.js` no longer
  imports `../planes.js`. Inherited from `claude/viewer-layer-020-617xad`.
- **`whenChannelsChange` is not in the contract.** It is on the neuroglancer
  handle and the panel uses it, but `viz_studio/options/contract.md` does not
  describe it. The three additions made on this branch are described; this older
  one is not, and the omission predates the work.

---

## 5. Traps in the environment, which cost real time

- **Two packages called `zmart-viewer`.** Both repositories declared the same
  distribution name, so installing one shadowed the other and it was not obvious
  which server was answering. PR #24 renames this one to `zmart-microscopy`.
  Until you have confirmed which package `from zmart_viewer import server`
  actually resolves to, no measurement against the viewer means anything.
- **`viz_studio/backend/` and `viz_studio/frontend/src/` are older copies.** The
  backend copy has no `loading` module, so it hands back position stores one at
  a time and never composes them; `/api/measure` does not exist there either, so
  a run against it shows an empty histogram and a dead *Auto* button on every
  channel. A stand-in package pointing at that backend was written into
  `dist-packages` early in the session and removed once the real repository
  arrived; **it should not come back.** The frontend copy is likewise stale —
  Smart Viewer 0.2's own `LayerPanel.jsx` is 1,745 lines against that copy's
  1,012.
- **Every acceptance gate must name the server it ran against.** Given the two
  points above, a green result that does not say which code answered proves
  nothing.
- **The container needs building before the workflow runs at all.** miniconda
  against conda-forge; the focus environment `ZMART--focus--main` built by the
  repository's own `setup_env.py`; and `zarr`, `numpy`, `tifffile`,
  `imagecodecs`, `scikit-image` and `pooch`, because the mock instrument's
  sample comes from `skimage.data.kidney()`, which `pooch` fetches once. Without
  these, Step 4 never finishes and Step 5 never begins. None of it is in the
  repository.
- **Smart Viewer's page is not built in a fresh clone.** There is no
  `app/page/dist`, and `make_server`'s `site_dir` defaults to it. The bridge
  uses only the API, so this may not matter, but it is an unlisted build step.

---

## 6. Three claims made here and withdrawn, so nobody repeats them

The pattern is worth more than the individual corrections: each came from
reading a label instead of taking a measurement, which is the exact failure this
whole piece of work exists to remove.

- *"The registration spec confirms the picture is misaligned."* It does not —
  see 1.3. Both tests time out before the assertion.
- *"Composition is not happening."* It is. `loading.load` on a folder of
  positions returns `overview.zmartview.zarr`. The loss was downstream, on this
  side.
- *"`/api/stores/construct` is the missing call."* It is not. `open` already
  covers the run-of-positions case in 0.2, and `construct` exists to build a
  picture over raw data explicitly.

And one worse than those three: **the screenshots that disprove registration had
already been taken, sent on, and not looked at.** `9-of-9.png` is a blank white
canvas showing neither the picture nor the plan, and it was offered as evidence
that nine fields had landed. Enlarging a screenshot costs a minute.

---

## 7. Positions not appearing on the canvas — the differential diagnosis

This is the complaint the whole project keeps coming back to: the scan runs, the
step says `54 / 54 tiles`, and the canvas is empty or nearly so. It has now had
**nine distinct causes**, and each one presented in almost exactly the same way.
The long-form account of the first six is in
`2026-09-01-why-the-acquired-overview-never-appeared.md`, which is worth reading
in full; this is the short list to work down when it happens again.

| # | Cause | What tells it apart | Status |
|---|---|---|---|
| 1 | A flat scan composed into a stack many planes deep | The linked scene's finest level has a `z` far greater than 1 — e.g. `[1, 3, 22, 10768, 20768]` for a one-plane-per-capture scan. Two or three fields visible, the rest "not found" at the viewing plane | Fixed: every position begins at height nought (`_the_corner_of`) |
| 2 | Addresses changing faster than the page could open them | `403` from the viewer, several times a second, for the whole run | Fixed then **superseded** — see below |
| 3 | An open that never finishes | Canvas empty for the rest of the session, nothing in the console. *A promise that never settles looks exactly like loading* | Fixed: `whenTheAxesAreKnown` refuses when every acquisition has errored, plus a time limit |
| 4 | Too few zoomed-out copies for a plate-sized picture | Thousands of pieces composed on demand at plate zoom; most never arrive; a fully imaged plate looks half empty | Fixed: a field keeps six copies rather than two (`THE_SMALLEST_COPY_WORTH_KEEPING`) |
| 5 | Two viewers disagreeing about where the picture was | Wells go oval when the panel opens; a column hides behind the panel; the scan "quietly draws nowhere" | Fixed: one viewer, `pictureOffsetUm` reconciles the frames |
| 6 | The JPEG fallback drawing *as well* | The window shows a scan, so a pipeline that never worked looks like a quirk of the viewer | Fixed: removed from the operator canvas; when the one engine cannot draw, the page says so |
| 7 | The bridge froze the answer from the first `/api/stores/open` | One field of fifty-four on the canvas, no error anywhere | Fixed by PR #24 (`/api/config` re-read on every poll) |
| 8 | Several addresses under one heading, all but one thrown away | Same symptom as 7, and the two were tangled together | Fixed: keep every store in the newest dataset (§3.6) |
| 9 | **The picture drawn tens of millimetres from the plan** | Everything renders, at the right size, in the wrong place — and only visible at a zoom that holds both | **Open — see §1.1** |

**On cause 2, and why it matters now.** The original fix rate-limited relinking
to once every thirty seconds, because the viewer numbered what it served in the
order it was opened, so relinking a growing folder changed the address and let
the old one go. **Smart Viewer 0.2 does not behave that way**: it watches an
opened folder itself and gives every store in one acquisition the same dataset
number, so the folder should be opened exactly once and never relinked. PR #24
removes relinking altogether, and that is right.

It should not be put back. The reason is a reproduction that was repeated
independently here: compose with two stores and `tiles.json` declares two; let a
third store land, open the same folder again, and the scene path is reused and
it **still declares two**. Relinking a growing acquisition therefore pins the
scene to a stale description. Anyone tempted to restore the throttle needs to
disprove that first.

**The moral of the list.** Six of the nine were each enough on their own to keep
the picture off the screen, and each hid the ones behind it. **Every one of them
reported success** — files written, layers built, addresses served, step
finished. Nothing anywhere said "this is not on your screen". So when positions
do not appear, do not look for an error; there will not be one. Ask the viewer
what it is actually serving, and ask the canvas what it actually drew, field by
field.

---

## 8. How to prove any of this again

All of it runs against the mock instrument through the real bridge and the real
page. From `application/`:

| What | How |
|---|---|
| The acceptance walk, six wells | `npx playwright test the-overview-on-the-canvas.spec.js` |
| Every field measured on its own | `npx playwright test every-tile-is-filled.spec.js` |
| A whole 96-well plate, 864 fields | `npx playwright test a-whole-96-well-plate.spec.js` |
| Which acquisition is really drawing | `npx playwright test which-layer-draws.spec.js` |
| Nine fields of kidney on a slide | `PYTHON=python3 npx playwright test step-five-kidney-evidence.spec.js` |
| One photograph per step of the walk | `npx playwright test the-window-step-by-step.spec.js` |
| The plate as a picture, mid-run | `python draw_the_plate.py --bridge <port> --into plate.png` |

Two of those are the ones that earn their keep. `which-layer-draws.spec.js`
turns each acquisition off in turn and records which store every piece of
picture was asked for and what came back — that is how "the overview is listed
with no errors" was finally told apart from "the overview is never fetched".
And `every-tile-is-filled.spec.js` measures **each field separately**, for the
reason given in §2.3.

Read §2.1 before trusting a green result from any of them: the newest of these
specs passed while measuring nothing at all.
