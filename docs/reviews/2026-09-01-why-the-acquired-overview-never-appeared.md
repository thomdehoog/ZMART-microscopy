# Why the acquired overview never appeared on the operator canvas

**Scope:** the operator window (`application/`), the canvas and its drawing
engines (`viz_studio/options/`), and the position writer that feeds them
(`application/parts/storage/`).
**Branch:** `claude/viewer-layer-020-617xad`.
**Date:** 2026-09-01.
**Instrument:** the mock driver, throughout. Nothing here has been on a real
microscope yet.

The complaint this began with was simple and had been standing for weeks: on
step 5, *Scan the overview*, the scan ran, the tiles were written, the step
said `54 / 54 tiles` — and the canvas stayed empty. The focussing sometimes
showed a patch of tissue; the overview never did.

It turned out to be four separate faults, not one. Each was enough on its own
to keep the picture off the screen, each hid the ones behind it, and — the
reason it took so long — **every one of them reported success**. The files were
written, the layers were built, the addresses were served, the step said it was
finished. Nothing anywhere said "this is not on your screen".

This document is the trail, so that the next person meeting something similar
starts where we finished rather than where we started.

---

## 1. A flat scan was composed into a stack twenty-two planes deep

**The fault.** A scan follows the focus map, so each position is captured at a
slightly different height — a couple of dozen distinct heights across
fifty-four fields on a six-well plate. `zarr_positions.py` wrote that height
into each position store as *where the picture sits*. The viewer links a folder
of positions into one picture by laying each store where it says it is, along
depth as much as across the sample. So a **flat** scan became a
twenty-two-plane stack holding two or three fields on each plane.

The canvas draws one plane at a time. An operator therefore saw two fields out
of fifty-four, or none, with every file present and every layer correctly
placed.

**How it was found.** By asking the viewer what it was actually serving, rather
than reasoning about it. The linked scene's finest level came back as
`[1, 3, 22, 10768, 20768]` — a `z` of twenty-two for a scan with one plane per
capture — and every piece of picture the engine asked for at the viewing plane
answered "not found".

**The fix.** Every position now begins at height nought
(`_the_corner_of` in `application/parts/storage/zarr_positions.py`). The height
itself is untouched in the run's record and in the vendor's files; it is simply
not written as geometry. A flat scan is one plane, which is what a map of a
plate is, and a focus stack still spans its own planes from nought.

---

## 2. The served addresses changed faster than the page could open them

**The fault.** The viewer service relinked the growing folder of positions on
every landing, and the viewer numbers what it serves in the order it was
opened — so a relink changes the address and lets the old one go. During a scan
that lands a position every half-second, nearly every address the page read had
already been closed by the time it tried to open it. The answer was `403`,
several times a second, for the whole run.

**The fix.** Relinking is rate-limited and happens when the page asks what
there is to draw, so the address it is handed is the freshest that has ever
been served (`A_PICTURE_MAY_STAND_FOR` in
`application/parts/storage/viewer_service.py`). It was five seconds; an
eight-hundred-and-sixty-four-field plate showed that was still too fast, and it
is now half a minute. Where several generations answer to one heading, the
newest is offered.

---

## 3. An open that could never finish wedged the canvas for the session

**The fault.** Given only sources it could not read, the engine waited for axes
that would never arrive. The page's "already opening" guard then held, so the
retry clock could never run again: the canvas stayed empty for the rest of the
session with nothing on screen or in the console to say why.

This is the failure this project keeps meeting, and it is worth naming plainly:
**a promise that never settles looks exactly like loading.**

**The fix.** `whenTheAxesAreKnown` now watches the layers as well as the axes
and refuses when every acquisition has answered with an error; the page's open
has a time limit besides. A related one, found the same way: centring the
opening view read the smallest copy of the image *whole*, which for a
plate-sized linked picture is a hundred million values per plane composed on
demand. That read is now refused above a budget, and the view opens on the
middle of the declared ground instead.

---

## 4. A plate-sized picture had two zoomed-out copies where it needed six

**The fault.** A folder of positions is linked into one picture by pointing at
the copies the positions already keep, so the picture has exactly as many
zoomed-out copies as one position does. Left to the chunk size, a 256-voxel
field kept two — itself and a half-size copy. That is ample for looking at one
well and hopeless for looking at a plate: ninety-six wells across a screen is
about a hundred and sixty micrometres to a screen pixel, where the coarsest
copy of a 4 µm field offers eight. The engine then drew the whole plate out of
the second-finest copy, some thousands of pieces each composed on demand; most
never arrived, and a plate that was entirely imaged looked half empty.

**The fix.** A field keeps six copies instead of two
(`THE_SMALLEST_COPY_WORTH_KEEPING` in `zarr_positions.py`). Measured on a
six-well plate, the linked picture goes from two levels to six, its coarsest
128 µm to the voxel — a couple of pieces rather than thousands.

This rests on what the whole arrangement rests on: shrinking keeps every second
voxel rather than averaging four, so a coarse voxel belongs to exactly one
position. That holds while each position begins on a whole number of coarse
voxels, which a run laid out on a grid does. A drifted stage is the open
question in the viewer's own `PLAN_showing_many_stores_as_one.md`, and it is no
more open than it was.

---

## 5. The canvas had two viewers, and they disagreed

Not a cause of the empty canvas, but the reason several symptoms were confusing
and the reason the fixes above were hard to see.

**What it was.** The canvas opened an engine that drew no picture at all — it
was there to hold the operator's layers and own the view — and the acquisition
was drawn by a **second** viewer in a box beneath it, with the view forwarded
by hand and the carrier's origin added on the way. Two viewers meant two
opinions about where the picture was. When the viewer panel opened and made the
canvas narrower, one refitted and the other did not, so the wells went oval and
a column of the plate hid behind the panel. When the forwarding was wrong, the
scan "quietly drew nowhere" — the code already carried a comment saying so.

**What it is now.** One viewer. The canvas takes the run's pictures through
`drawTheseAcquisitions` and draws them itself, with the operator's layers above
on its own overlay. The forwarding is gone. Three things had to be settled:

- the engine could not open with no acquisitions, and a canvas must exist
  before the run has taken a field — no acquisitions is now answered at once,
  with surfaces, gestures and a view but no layers;
- the layers are drawn in the carrier's micrometres and the run's images say
  where they are on the stage; that reconciliation moved into the canvas as
  `pictureOffsetUm`, so a page keeps thinking in its own frame;
- which engine draws the run is one named line in
  `workflows/target_acquisition/shared/stage.js`, overridable with `?engine=`.

**And the JPEG fallback is gone from the operator window.** It is not that it
drew badly — it is that it drew *as well*. The page could always fall back to
small copies, so when the run's own images were not reaching the screen the
window still showed a scan, and a pipeline that had never worked looked like a
quirk of the viewer. That fallback is a large part of why this took weeks. One
engine draws acquired image data now, and when it cannot, the page says so.

Small pictures have **not** gone from the application, and should not: the
focus stack, its side view and the slice under the black line are JPEGs made by
`viz_studio/backend/jpeg_tiles.py`, and nothing in the panel beside the canvas
has to resolve at a dozen magnifications. `jpeg-under` also stays in the engine
list, because the canvas is a part in its own right whose own tests exercise
the layer machinery through the cheapest engine there is, and because the
three-way comparison in `viz_studio/options/` needs it.

---

## 6. The panel could say the opposite of what was on the screen

The eye beside each channel was drawn open when the row was built and changed
only when that eye's own button was pressed. So a channel turned off any other
way kept an open eye, and the panel told the operator the opposite of what
their picture was doing. It is a small thing that costs a great deal of trust,
because the panel is where somebody goes to find out why a colour is missing.

The viewer now announces that which channels are drawn has changed
(`whenChannelsChange`), and the panel subscribes when it is mounted. Both eyes —
a channel's and its acquisition's — go through one place.

---

## 7. Focussing was measured on a different arrangement of the same pixels

Not a fault that hid the picture, but the last place where the run's canonical
image and the number the operator is shown came from different readings.

Every capture is converted to an OME-Zarr position the moment it lands — one
image, its axes declared, its channels described — and that is what the viewer
draws and what an operator can open in napari or Fiji. Focus scoring, however,
still handed the analysis step the vendor's sixty-one loose plane files. The
step could always read either, so this was habit rather than design; the cost
is that the height on the focus plot was measured on an arrangement of the
pixels nobody else looks at.

`what_was_captured` in `application/parts/microscope/focus_score.py` now hands
over the store where the capture has one, and the plane files only where the
conversion did not happen — a driver whose captures cannot be converted still
focusses exactly as before. Measured on the mock: the same stack scores the
same peak either way, and a live point through the bridge came back at
22.3 µm rather than lost.

The one thing to know before running this on a microscope is in section 9: the
store is read with `ngio`, so an old focus environment needs rebuilding.

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
| The panel's eyes | `ZV_SOURCE="<two served stores>" npx playwright test viewer-panel-eyes.spec.js` |
| One photograph per step of the walk | `npx playwright test the-window-step-by-step.spec.js` |
| The plate as a picture, mid-run | `python draw_the_plate.py --bridge <port> --into plate.png` |

Two of those deserve a note, because they are the ones that would have caught
this years earlier. `which-layer-draws.spec.js` turns each acquisition off in
turn and records which store every piece of picture was asked for and what came
back — that is how "the overview is listed with no errors" was finally told
apart from "the overview is never fetched". And `every-tile-is-filled.spec.js`
measures **each field separately**, because a scan of fifty-four fields that
drew twenty looks, from far enough away, exactly like one that drew all
fifty-four.

Where it stands on the mock: 864 of 864 fields drawn on a 96-well plate, and
54 of 54 on six wells after the canvas was collapsed to one viewer, with the
focussing hidden and its eyes asserted closed in the same photographs.

---

## 9. What is still open

- **The panel's unported features.** LUTs, the × close, the Z and T sliders
  with play, and pan and zoom on the histogram are all still in the standalone
  viewer and not yet in the operator window.
- **Rebuild the focus environment if it is older than this branch.** Focussing
  now scores the run's own OME-Zarr position rather than the vendor's loose
  plane files (section 7). Reading an OME-Zarr needs `ngio`, which the focus
  environment has listed since it was first written — but an environment built
  before that line was added does not have it, and every focus point would be
  lost with `No module named 'ngio'`. Running
  `python zmart_analysis/workflows/focus/environments/setup_env.py` puts that
  right, and its own check scores a small stack in an OME-Zarr position, so a
  green run of it is the answer to whether focussing will work.
- **A drifted stage.** Everything above assumes positions land on a grid. What
  happens when they do not is written up in the viewer's
  `PLAN_showing_many_stores_as_one.md` and is unchanged by this work.
- **Nothing here has run on a real instrument.** Every measurement in this
  document is the mock.
