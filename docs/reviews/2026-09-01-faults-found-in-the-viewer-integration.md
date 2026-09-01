# Faults found while getting the viewer into the operator window

**Date:** 2026-09-01.
**Repository:** `thomdehoog/ZMART-microscopy`.
**Smart Viewer:** a separate repository, `thomdehoog/ZMART-viewer`, commit
`9ff10b0`, version 0.2.0, cloned in this container at
`/home/user/thomdehoog/zmart-viewer`. It installs with
`pip install --no-deps -e .`; a plain install stops on `proxy_tools`, which
arrives through `pywebview` and which the server itself does not use.
**Branches:** `claude/viewer-port-remaining-steps-ofm5qp` (the eight steps of
the panel port and the canvas fallback view),
`claude/every-field-reaches-the-canvas` (superseded by PR #24), and
`claude/step-five-kidney-evidence` (the Step 5 evidence run, and this note).

This document is a record of what was found to be wrong, and how each thing was
measured. It is not a plan and it asks for nothing; it exists so that the next
person meeting one of these symptoms can recognise it rather than rediscover it.
Where something is still open, that is said plainly, along with what is and is
not established about it.

---

## The shape these faults share

Almost every fault below made the operator window look **quiet rather than
broken**. The canvas was blank, or a picture stayed dark, or a slider did very
little, or a count read nine when four had been drawn. None of them raised an
error, and several of them passed the checks written for them.

That has a consequence for how they surface. A fault whose whole signature is
that nothing happens is nearly invisible to a reading of the code, and a green
test suite is no help either, because a check written from the same
misunderstanding as the code agrees with it. All but two of the faults here came
out of running the workflow against the mock instrument and looking at the
screen, and the two that came out of reading are the two least serious.

Three of them were sitting in screenshots that had already been taken and passed
on, and went unnoticed because the images were small and nobody enlarged them.

---

## 1. Open findings

### 1.1 The picture is drawn in the wrong place on the stage

After a nine-field scan of a slide, the composed picture is drawn roughly
**23.3 mm to the right and 29.4 mm below** the planned positions — far enough
that it lands off the slide altogether.

Measured from `test-results/step-five-kidney/whole-plate.png`, taken with the
canvas zoomed out to Fit and the overlay faded to 0.15:

| | on screen | in millimetres |
|---|---|---|
| Scale bar | 50 mm across 135 px | 0.370 mm per pixel |
| Slide outline | 199 × 63 px | 73.7 × 23.3 mm |
| Plan (the scan area) | centre at (409.5, 164.5) px | about 3 mm across |
| The drawn picture | centre at (472.5, 244.0) px | 3.0 × 3.3 mm |
| **Difference** | **+63, +79.5 px** | **+23.3 mm, +29.4 mm** |

Two things follow from those numbers. The slide outline comes out at 73.7 ×
23.3 mm, which is a standard 75 × 25 mm slide, so the canvas's conversion from
millimetres to screen pixels is correct. And the picture's own extent, about
three millimetres square, is what a three-by-three block of roughly
one-millimetre fields with a little overlap should measure — so the nine tiles
are being stitched together correctly and at the correct size relative to one
another. **Only the origin is wrong.** This is a translation, and not a scaling
or a rotation.

The offset is visible only at a zoom that holds both the plan and the picture,
and at that zoom the picture is a speck a few pixels across, which is why it
survived a session's worth of screenshots.

**What is not established.** The cause. The offset does not correspond in any
obvious way to a slide dimension or to a flipped origin. The measurement that
would separate the possibilities is the engine's reported image-space origin for
the `overview` source set beside `window.__theStageCanvas.plan()[0]`, both in
micrometres on a live page: that distinguishes the viewer placing the composed
scene wrongly, the adapter's transform being wrong, and the plan disagreeing
with the mock instrument's stage about where zero is.

**One commit is a suspect, and it is one of ours.** The offset was measured on
`claude/step-five-kidney-evidence`, which contains `4ab5903` — the commit that
gave the canvas a view of its own. That commit does not only add a fallback; it
also changes `intoTheStore` and `outOfTheStore`, which are the conversions
between the frame the page thinks in and the frame the store is described in,
and which are where the reconciliation between the carrier's micrometres and the
stage's lives (`pictureOffsetUm`, section 5 of
`2026-09-01-why-the-acquired-overview-never-appeared.md`). A commit that rewrites
those conversions, on a branch that then draws the picture tens of millimetres
from the plan, is the first place a translation error would be looked for.

This is a suspicion and not a finding. What would settle it is running the same
nine-field walk at `93e374c`, the commit `4ab5903` was taken from, with PR #24's
`viewer_service.py` in place so that the fields actually reach the canvas: if
the offset is there too it is older than this work, and if it is not, `4ab5903`
introduced it. That run has not been done.

Worth stating for balance: the port branch touched none of the pipeline that
`2026-09-01-why-the-acquired-overview-never-appeared.md` describes.
`zarr_positions.py` and `viewer_service.py` are untouched on it, and
`_the_corner_of`, `THE_SMALLEST_COPY_WORTH_KEEPING`, `A_PICTURE_MAY_STAND_FOR`,
`pictureOffsetUm` and `whenChannelsChange` are all still present. Whatever went
wrong, it did not go wrong by undoing those.

### 1.2 The engine's opening view replaces the operator's framing

When an acquisition lands, the drawing engine's own opening view takes over and
whatever the operator had framed is lost, with nothing said. In the Step 5 run
this left the canvas showing a region about 0.66 mm across — the scale bar read
200 µm — while the plan sat some 37 mm away, entirely off screen.

It is an annoyance in its own right, since an operator who has spent a minute
framing their plate should not lose that because a field finished exposing. Its
larger significance here is that **it is what concealed 1.1**: with the view
holding on the plate, the misplacement would have been plain in the first
screenshot.

### 1.3 The check that would settle registration never reaches its assertion

`the-scan-under-the-plan.spec.js` is the specification written to compare where
the picture is drawn against where the plan says it should be. Both of its tests
time out at `waitForFunction(() => !!window.__thePicture)` — the picture never
opens in that harness, so the comparison is never made. Verified identical at
`93e374c`, so this predates the work described here.

This was misread once during the session as "the registration check confirms the
picture is misaligned". It confirms nothing either way, because the assertion
does not run.

---

## 2. Checks that pass without checking anything

These have a section of their own because they are the reason several faults
survived. A check that cannot fail is worse than no check at all, since it also
carries a claim that somebody looked.

### 2.1 A field that is off screen is skipped rather than failed

In `application/step-five-kidney-evidence.spec.js`, the per-field measurement
reads:

```js
const inside = whatIsInside(pixels, field);
if (!inside) continue;
```

`whatIsInside` returns `null` when a field's projected box falls outside the
photograph. A field nobody could see is therefore passed over in silence, and
the assertion that follows — `expect(thin, "every planned field carries picture")
.toEqual([])` — is satisfied by an empty list. **The check cannot distinguish
"all nine fields were drawn" from "not one field was examined."**

In the run reported as passing, the second is what happened. The view was about
0.66 mm across and the plan was some 37 mm away, so all nine boxes lay off
screen and both assertions passed on empty lists.

### 2.2 Measuring inside a wall of picture establishes nothing

The same specification asks how much of each field's square carries picture, and
how many distinct shades it holds. Both are reasonable questions, and both lose
their meaning when the view is zoomed so far in that one field fills the canvas:
every box then lands inside a solid expanse of tissue and returns 100 % covered
and richly textured, wherever it happens to have been placed.

### 2.3 A scan reported finished is not a scan observed drawn

A scan of nine fields that drew four reports `9 / 9 tiles`, and from far enough
away looks exactly like one that drew all nine. This is why
`every-tile-is-filled.spec.js` measures each field separately; a total, an area,
or a comparison made at plate scale does not separate the two cases.

### 2.4 Two panel checks depended on a run whose acquisitions had one colour each

Two checks counted their way along to the eye they wanted, which worked only
because the mock's acquisitions happened to carry a single channel apiece. Fixed
in `5376b7f`: each eye now names the row it belongs to, and the contrast check
asks for two fixed values rather than for "thirty more than wherever the handle
currently is".

---

## 3. Faults fixed on these branches

### 3.1 The plate, the plan and the focus points drawn at NaN

**Commit `4ab5903`.** Every layer the operator draws on is positioned in
micrometres on the sample, and has to be converted into a place on screen before
it can be drawn. That conversion belonged entirely to the drawing engine, which
is correct while there is a picture: the engine is placing the picture too, and
the two have to agree to the pixel.

Neuroglancer, though, takes its axes from its image layers, so before a run has
captured anything it has no coordinate space at all and answers every question
about position with `NaN`. The first four steps of a workflow are precisely that
situation, by definition — an operator laying a plan out on an empty plate.

What it looked like was an empty canvas. Every layer was present and switched
on, each drawn at nowhere. The only thing that appeared was the scale bar,
because a scale bar is measured in screen pixels and needs no such conversion.
After the fix, a planned field at (17324, 17324) µm lands at (123.3, 123.3) on
screen.

This is the largest and least safe change of the session. The canvas now keeps
its own account of where it is looking and uses it whenever the engine cannot
place things, under two rules: while the engine can place things it is the sole
authority and the canvas's copy follows it, and the engine is never asked to
pretend. The parts most exposed to error are
`whoeverCanPlaceThingsHoldsTheDrags`, and the question of whether the canvas's
copy of the view can drift from the engine's while the engine holds authority.

### 3.2 Lending a drag to a tool stopped working

Found while making 3.1. The first attempt attached a second pair of pan and zoom
gestures without settling which pair was in charge, and drags a tool had
borrowed silently stopped reaching it; four checks in
`parts/canvas/canvas-layers.spec.js` went red. The rewrite has exactly one of
the two sets listening at any moment. The symptom, once again, was that
something simply stopped happening.

### 3.3 Hiding an acquisition could hide it permanently

**Commit `5376b7f`.** The panel's `refresh` drew each eye from what the picture
was really doing, which is right, and *also* wrote that back into each row as
though it were the operator's own choice. So while an acquisition was hidden,
every one of its channels was recorded as one the operator had turned off, and
opening the acquisition again asked for nothing at all. The heading's eye opened
over a picture that stayed dark.

The two questions are now kept apart: what is drawn is always read from the
picture, and what the operator chose is only taken from the screen while the
acquisition is being shown at all. This was already failing before the work on
that branch.

### 3.4 The contrast slider had about two pixels of usable travel

**Commit `5376b7f`.** With no measurement available, the brightness and contrast
tracks ran across the whole of what a sixteen-bit camera can produce. Real
acquisitions occupy a small part of that, so the usable range of the slider was
a couple of pixels wide and the control appeared to do nothing at all.

They now fall back to the window the run itself declared, which says roughly
where the signal is. Measured on the mock's own overview, that is a track of
0–3,800 rather than 0–65,535.

### 3.5 The colour chooser opened past the edge of the window

**Commit `5376b7f`.** The panel stands against the right-hand edge of the
window, and naming the colour maps made the list wider than the plain colour
names had been, so it hung 77 px beyond the edge. It now opens to whichever side
has room.

### 3.6 One field of many reaching the canvas

**Commit `d84c684`, on `claude/every-field-reaches-the-canvas`, superseded by
PR #24.**

The viewer can place several addresses under one heading for two quite different
reasons, and the answer looks the same either way. One means "here is the same
picture again, opened afresh", and only the last of those can still be read. The
other means "here are the fields this one picture is made of", and every one of
them is wanted. The rule in place kept exactly one address, which was right for
the first reason and discarded fifty-three fields out of fifty-four for the
second.

PR #24 carries that reasoning forward and adds the part that was actually
missing: the bridge froze the answer from the first `/api/stores/open` call and
never asked again. Two things about the superseded branch are worth recording.
Its commit message is more confident than the evidence supported, having been
written before the change had been run in the real walk — and running it showed
the change did not by itself make Step 5 work. And its test wording describes
several position-store addresses as a "composed acquisition", which is wrong: a
composed scene is normally one `*.zmartview.zarr` address, whereas these are a
watched multi-store acquisition.

---

## 4. Smaller open items

- **A thirty-second timeout on a one-and-a-half-second poll.** `_read` in
  `application/parts/storage/viewer_service.py` waits up to thirty seconds while
  the operator polls every one and a half. Should `/api/config` ever take longer
  than the poll interval, requests accumulate; the bridge is threaded, so slow
  polls become threads queued against the viewer. The code already handles a
  failed read by keeping the last usable list.
- **A rerun is not exercised.** `opened` is held for the life of the service, so
  *Run again* never reopens a folder. New stores are picked up by the viewer's
  own watch, but a rerun that replaces stores under the same names depends on the
  viewer noticing changed bytes, and nothing tests that.
- **Twenty-seven channel rows under one heading.** With every field passed
  through, the engine holds nine `overview` sources of three channels each, and
  the panel lists all twenty-seven under a single `overview` heading. It is
  functionally correct and reads as a fault to anybody looking at it.
- **`test_no_option_decides_for_itself_which_plane_to_open_on` fails**, and
  failed before any of this work: `neuroglancer-under/viewer.js` no longer
  imports `../planes.js`. Inherited from `claude/viewer-layer-020-617xad`.
- **`whenChannelsChange` is not described in the contract.** It is on the
  neuroglancer handle and the panel uses it, but
  `viz_studio/options/contract.md` does not mention it. The three additions made
  on this branch are described; this older one is not, and the omission predates
  the work.

---

## 5. Facts about the environment that cost time

- **Two packages called `zmart-viewer`.** Both repositories declared the same
  distribution name, so installing one shadowed the other and which server was
  answering was not apparent. PR #24 renames this one to `zmart-microscopy`. A
  measurement made against the viewer means nothing until it is known which
  package `from zmart_viewer import server` resolved to.
- **`viz_studio/backend/` and `viz_studio/frontend/src/` are older copies.** The
  backend copy has no `loading` module, so it hands back position stores one at
  a time and never composes them, and `/api/measure` does not exist there — a
  run against it shows an empty histogram and a dead *Auto* button on every
  channel. A stand-in package pointing at that backend was written into
  `dist-packages` early in the session and removed once the real repository
  arrived. The frontend copy is likewise stale: Smart Viewer 0.2's own
  `LayerPanel.jsx` is 1,745 lines against that copy's 1,012.
- **The container needs building before the workflow runs at all.** miniconda
  against conda-forge; the focus environment `ZMART--focus--main`, built by the
  repository's own `setup_env.py`; and `zarr`, `numpy`, `tifffile`,
  `imagecodecs`, `scikit-image` and `pooch`, because the mock instrument's
  sample comes from `skimage.data.kidney()`, which `pooch` fetches once. Without
  these, Step 4 never finishes and Step 5 never begins. None of it is in the
  repository.
- **Smart Viewer's page is not built in a fresh clone.** There is no
  `app/page/dist`, and `make_server`'s `site_dir` defaults to it. The bridge uses
  only the API, so this may not matter in practice, but it is an unlisted build
  step.

---

## 6. Claims made during this work and later withdrawn

The pattern is more informative than the individual corrections: each came from
reading a label rather than taking a measurement, which is the same failure the
rest of this document describes.

- *"The registration specification confirms the picture is misaligned."* It does
  not — see 1.3. Both tests time out before the assertion.
- *"Composition is not happening."* It is. `loading.load` on a folder of
  positions returns `overview.zmartview.zarr`. The loss was downstream, on this
  side.
- *"`/api/stores/construct` is the missing call."* It is not. `open` already
  covers the run-of-positions case in 0.2, and `construct` exists to build a
  picture over raw data explicitly.

And one that belongs with them: the screenshots that disprove registration had
already been taken and passed on before anybody enlarged them. `9-of-9.png` is a
blank white canvas showing neither the picture nor the plan, and it was offered
as evidence that nine fields had landed.

---

## 7. Positions not appearing on the canvas: the nine causes so far

This is the complaint the project keeps returning to — the scan runs, the step
reports `54 / 54 tiles`, and the canvas is empty or nearly so. It has now had
nine distinct causes, each presenting in almost exactly the same way. The
long-form account of the first six is in
`2026-09-01-why-the-acquired-overview-never-appeared.md`.

| # | Cause | What distinguishes it | Status |
|---|---|---|---|
| 1 | A flat scan composed into a stack many planes deep | The linked scene's finest level carries a `z` far greater than 1 — `[1, 3, 22, 10768, 20768]` for a one-plane-per-capture scan. Two or three fields visible, the rest answering "not found" at the viewing plane | Fixed: every position begins at height nought (`_the_corner_of`) |
| 2 | Addresses changing faster than the page could open them | `403` from the viewer, several times a second, for the whole run | Fixed, then superseded — see below |
| 3 | An open that never finishes | The canvas stays empty for the rest of the session with nothing in the console. A promise that never settles looks exactly like loading | Fixed: `whenTheAxesAreKnown` refuses once every acquisition has answered with an error, and the page's open has a time limit |
| 4 | Too few zoomed-out copies for a plate-sized picture | Thousands of pieces composed on demand at plate zoom, most never arriving; a fully imaged plate looks half empty | Fixed: a field keeps six copies rather than two (`THE_SMALLEST_COPY_WORTH_KEEPING`) |
| 5 | Two viewers disagreeing about where the picture was | Wells go oval when the panel opens, a column of the plate hides behind it, and the scan draws nowhere | Fixed: one viewer, with `pictureOffsetUm` reconciling the frames |
| 6 | The JPEG fallback drawing as well | The window shows a scan, so a pipeline that had never worked looked like a quirk of the viewer | Fixed: removed from the operator canvas, and when the one engine cannot draw, the page says so |
| 7 | The bridge froze the answer from the first `/api/stores/open` | One field of fifty-four on the canvas, and no error anywhere | Fixed by PR #24, which re-reads `/api/config` on every poll |
| 8 | Several addresses under one heading, all but one discarded | The same symptom as 7, and the two were tangled together | Fixed: every store in the newest dataset is kept (§3.6) |
| 9 | The picture drawn tens of millimetres from the plan | Everything renders, at the right size, in the wrong place — visible only at a zoom holding both | **Open — see §1.1** |

**On cause 2, and how it stands now.** The original fix rate-limited relinking to
once every thirty seconds, because the viewer numbered what it served in the
order it was opened, so relinking a growing folder changed the address and let
the old one go. Smart Viewer 0.2 does not behave that way: it watches an opened
folder itself and gives every store in one acquisition the same dataset number,
so a folder is opened once and not relinked. PR #24 removes relinking
altogether.

A reproduction repeated independently here bears on whether it could come back.
Compose with two stores and `tiles.json` declares two; let a third store land,
open the same folder again, and the scene path is reused while the description
**still declares two**. On that evidence, relinking a growing acquisition pins
the scene to a stale description of itself, and the thirty-second throttle was
defending an assumption that ceased to hold at 0.2.

**What the list as a whole shows.** Six of the nine were each sufficient on their
own to keep the picture off the screen, and each concealed the ones behind it.
Every one of them reported success — files written, layers built, addresses
served, step finished. Nothing anywhere said "this is not on your screen". When
positions do not appear there is generally no error to find; what separates the
causes is asking the viewer what it is actually serving, and asking the canvas
what it actually drew, field by field.

---

## 8. How these were measured

Everything above was run against the mock instrument, through the real bridge
and the real page. Nothing here has been on a microscope. From `application/`:

| What | How |
|---|---|
| The acceptance walk, six wells | `npx playwright test the-overview-on-the-canvas.spec.js` |
| Every field measured on its own | `npx playwright test every-tile-is-filled.spec.js` |
| A whole 96-well plate, 864 fields | `npx playwright test a-whole-96-well-plate.spec.js` |
| Which acquisition is really drawing | `npx playwright test which-layer-draws.spec.js` |
| Nine fields of kidney on a slide | `PYTHON=python3 npx playwright test step-five-kidney-evidence.spec.js` |
| One photograph per step of the walk | `npx playwright test the-window-step-by-step.spec.js` |
| The plate as a picture, mid-run | `python draw_the_plate.py --bridge <port> --into plate.png` |

Two of these do work the others cannot. `which-layer-draws.spec.js` turns each
acquisition off in turn and records which store every piece of picture was asked
for and what came back, which is how "the overview is listed with no errors" was
finally told apart from "the overview is never fetched". And
`every-tile-is-filled.spec.js` measures each field separately, for the reason in
§2.3.

The newest of them, `step-five-kidney-evidence.spec.js`, passed while measuring
nothing at all; §2.1 describes how.
