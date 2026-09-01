# Handover: the viewer port, and why the scanned plate does not appear

**Written:** 2026-09-01.
**Branch this describes:** `claude/viewer-port-remaining-steps-ofm5qp`, in
`thomdehoog/ZMART-microscopy`.
**Companion notes:** `2026-09-01-what-is-left-in-the-viewer-port.md` (the list of
steps that was worked through) and
`2026-09-01-why-the-acquired-overview-never-appeared.md` (the account of the
faults before it).

This is a handover rather than a review. The work below stopped part-way, with
one large thing understood and not yet acted on, and this note exists so that
whoever picks it up does not have to re-derive any of it. It says what was
built, what was got wrong, what is still broken, and — most importantly — where
the picture server actually lives, because that turned out to be the heart of it.

---

## 0. Where everything is

| Thing | Where |
|---|---|
| This repository | `thomdehoog/ZMART-microscopy`, branch `claude/viewer-port-remaining-steps-ofm5qp` |
| Branched from | `93e374c`, the tip of `claude/viewer-layer-020-617xad` |
| Seven commits, `908a201` … `4ab5903` | pushed |
| **The Smart Viewer** | a **separate repository**, `thomdehoog/ZMART-viewer`, at commit `9ff10b0`, version **0.2.0** |
| Its local clone in this container | `/home/user/thomdehoog/zmart-viewer` |

**The Smart Viewer being a separate repository is the single most important
fact in this note.** This repository contains a copy of an older viewer server
under `viz_studio/backend/`, and a copy of an older viewer front end under
`viz_studio/frontend/src/`. Neither is the current viewer. The current one is
version 0.2.0 in the repository above, and it is the package the operator's
bridge actually asks for by name.

---

## 1. What was built, and is worth keeping

Eight steps from the companion note were carried out, each in its own commit,
each with checks. What follows is what each of them established, so that a
reviewer can keep the finding even if they rewrite the code.

**The contract grew three times, and every one of the four drawing options
answers each addition.** There is a check for each in
`viz_studio/tests/test_the_options_hold_together.py`, in the same shape as the
checks that were already there.

- `whenTheViewMoves(tell)` — a control that only ever writes to the viewer will
  one day be photographed saying something untrue. The depth slider was exactly
  that: it showed where it had last put the operator, not where the picture was.
- `theMomentsItCanShow()` — `setMoment(t)` had existed since the interface was
  written with no way to ask how far it went, so a page could move a timelapse
  but could not draw a control for one.
- `setChannel(index, { lut })` and `lutsItCanDraw` — a panel offers only what
  the engine says it can draw, so nobody meets a menu whose choices do nothing.

**Two pieces of arithmetic were lifted out of the panel and given their own
checks**, because they are the fiddly part and they can be read on their own:
`application/parts/canvas/counting-planes.js` (how a depth in micrometres
becomes "plane 12 of 48") and `application/parts/canvas/the-window.js` (how one
brightness window is described both as min/max and as brightness/contrast).
Twenty-three unit checks between them. These are the least contentious part of
the branch and should survive any rework of the panel.

**The panel itself gained**: a *Reset* that puts back the window the run
declared, brightness and contrast beside min and max, a plain notice when a
measurement fails, a play button that wraps and stops itself, a time slider that
appears only for a real timelapse, colour maps on the swatch, a fold and an
opacity per acquisition, and a selection held by name so that rebuilding the
list does not silently point the sliders at a different channel.

**Three faults were found by running it against a real run rather than by
reading**, and are worth keeping whatever else changes:

1. The acquisition heading's eye could hide a whole acquisition and never bring
   it back. `refresh` drew the eyes from the picture — correct — but also wrote
   that back as the operator's own choice, so while an acquisition was hidden
   every one of its channels was recorded as one the operator had turned off.
   This was already failing on the branch before this work.
2. The contrast sliders had about two pixels of usable travel on a real
   acquisition, because with no measurement they ran over the whole of what a
   sixteen-bit camera can produce.
3. The colour chooser opened seventy-seven pixels off the right-hand edge of the
   window once the colour maps made its entries wider.

---

## 2. What was got wrong

**The panel was ported against the copy in `viz_studio/frontend/src/`, not
against the Smart Viewer at 0.2.0.** Every line number the companion note cites
lands exactly on that copy, so the note and the port agree with each other — but
they may both be describing an interface that has since moved on. The maintainer
has said that the current viewer arranges its sliders, its layer switches and
its histograms differently. **Anything in section 1 that concerns how the panel
looks should be checked against `/home/user/thomdehoog/zmart-viewer` before it
is trusted.** What the panel *asks of the engine* — the three contract additions
— is a separate question and is likely to survive.

---

## 3. Why the scanned plate does not appear on the canvas

This is the unfinished business, and it is worth setting out carefully because
three different things were blamed for it before the real cause was found.

**What an operator sees.** Steps 1 to 4 are correct: the plate is drawn, the
tilesets are drawn, the focus points are measured and drawn. Step 5 scans
fifty-four fields, reports "54 / 54 tiles", and then shows either black squares
where the fields should be, or — once the picture server is running — a single
field of tissue at high magnification with the plate off the edge of the screen.

**What is actually happening.** The operator page asks the bridge for the run's
served addresses. The bridge starts the picture server with
`from zmart_viewer import server` (`application/parts/storage/viewer_service.py`,
line 101). That package is the separate repository above, and it was not
installed, so the bridge recorded *"the viewer server did not start: No module
named 'zmart_viewer'"* and handed the page **no acquisitions at all**. The black
squares were the windows the operator's own drawing cuts wherever a field has
landed, with nothing behind them to show through — not a picture drawn badly.

With a picture server running, a second and deeper problem appears.
`viewer_service.py` asks only three things of it: `/api/announce`,
`/api/stores/close` and `/api/stores/open` (lines 173, 228 and 230). Opening a
positions folder gives back the position stores **one by one**, and
`_only_the_newest_of` then picks exactly one of them. So the page is handed a
single 676 µm field as "the overview", the drawing engine fits its opening view
to that one field, and the plate goes off the screen.

**The most likely smallest fix, and it is not written yet.** Version 0.2.0 of
the Smart Viewer has a route this repository never calls:

```
POST /api/stores/construct        "Construct a viewer over raw data, in the
POST /api/stores/construct-status  background, then open it."
POST /api/stores/construct-cancel
```

That is what turns a folder of per-field stores into one picture and opens it.
It takes the folder holding the images, a folder for the viewer's own files, and
optionally a name. **The first thing to try is asking `construct` for the run's
positions folder instead of `open`, and then reading the sources back as
before.** Until that has been tried, everything else about step 5 is guesswork.

---

## 4. What is already in the Smart Viewer and must not be rebuilt

Time was nearly spent rebuilding two of these on this side of the fence. They
are listed so that nobody does.

- **Composing many per-field stores into one picture.** `zmart_viewer/compose.py`
  does this, and it does it by *building* the pieces rather than by pointing at
  them — which is a different mechanism from the pointer file
  (`zmart-links.json`) that `zmart_storage/linked.py` and
  `viz_studio/backend/linking.py` describe. Do not write a third one.
- **Measuring a channel's brightness.** Version 0.2.0 serves `/api/measure`,
  which is exactly the route the panel already asks for. The vendored copy in
  `viz_studio/backend/` does **not** have it, which is why every histogram in
  the photographs from today is empty and every *Auto* button is dead. That is
  an artefact of running the wrong server, not a gap in the panel.
- **Replaying a run** (`/api/stores/replay` and its status and cancel routes)
  and **listing what is open** (`/api/stores/list`). Neither is used here yet.

---

## 5. Risks in the seven commits, for an adversarial reader

Ranked by how much they would repay a careful look.

1. **`4ab5903`, the canvas fallback, is the largest and least safe change.** It
   gives `application/parts/canvas/viewer.js` a view of its own, used whenever
   the drawing engine cannot place things — which is every step before a run has
   captured anything, because neuroglancer takes its axes from its image layers
   and has none. It also attaches a second set of pan-and-zoom gestures, and
   swaps which of the two may lend a drag to a tool. A first attempt at that
   broke four checks in `parts/canvas/canvas-layers.spec.js` by silently
   stopping lent drags reaching tools; the rewrite makes exactly one of the two
   sets listen at a time. **Look hardest at the swap**
   (`whoeverCanPlaceThingsHoldsTheDrags`) and at whether the canvas's copy of the
   view can ever drift from the engine's while the engine is authoritative.
2. **`theViewNow()` and `aFrameWeCanDrawWith()` write to `ourOwnView` as a side
   effect of being asked a question.** That is deliberate — it is how the copy
   follows the engine — but a getter that mutates is easy to misread and worth a
   second opinion.
3. **`viewer.js` now imports `viz_studio/options/gestures.js`** from inside
   `application/`. That crosses a boundary the repository is otherwise careful
   about. It is the same shared file every engine uses, which is the argument
   for it, but it deserves a decision rather than an accident.
4. **`viewer-panel.js` has grown from 688 lines to about 1,435**, nearly all of
   it inside one function. It works and it is checked, but it is at the point
   where the next person to change it will find it hard.
5. **`watching-the-run.js` gained eleven lines** to carry the chosen channel
   across a rebuild of the panel. Small, but it is the only change on this branch
   inside a workflow step.

---

## 6. Changes made to this container that are **not** in the repository

Whoever picks this up on a fresh machine will need these, and should not go
looking for them in a diff.

- **Miniconda** at `/opt/miniconda3`, configured against conda-forge. Anaconda's
  own channels now require accepting terms of service, which was not something to
  accept on the maintainer's behalf.
- **The focus environment** `ZMART--focus--main`, built by the repository's own
  `setup_env.py`. Its three diagnostics pass, including scoring a z-stack in an
  OME-Zarr position. Without it the focus step of the workflow cannot run at all.
- **Python packages** the bridge needs that were missing: `zarr`, `numpy`,
  `tifffile`, `imagecodecs`, `scikit-image`, `pooch`. The mock microscope draws
  its sample from `skimage.data.kidney()`, which `pooch` fetches once.
- **A stand-in `zmart_viewer` package** was written into `dist-packages`,
  pointing at `viz_studio/backend`, and then **removed** once the real
  repository was cloned. It should not come back. If anything odd remains on the
  import path, that is where it came from. `pip install -e` of the real viewer
  then failed on `proxy_tools`, a `pywebview` dependency that has no wheel here;
  the viewer's server itself does not need it, so installing without the desktop
  window extra is the way round.

---

## 7. How to tell when step 5 is right

None of these can be met today, and all of them are worth writing as checks.

1. **The bridge answers with a picture.** `GET /api/viewer` on the bridge returns
   `error: null` and sources for the acquisitions the run has made — and for the
   overview it returns **one address covering the whole scan**, not one per
   field. This is the check that fails now.
2. **All fifty-four fields are drawn.** `every-tile-is-filled.spec.js` already
   measures each field separately, for the reason its own note gives: a scan of
   fifty-four fields that drew twenty looks, from far enough away, exactly like
   one that drew all fifty-four. Run it, do not re-invent it.
3. **The plate stays on screen when the picture arrives.** Today the engine's
   opening view replaces the workflow's Fit the moment an acquisition lands. An
   operator who has framed their plate should not lose it.
4. **The histogram is drawn and *Auto* does something**, which follows from
   running a server that serves `/api/measure`.
5. **Look at the photograph.** `the-window-step-by-step.spec.js` writes one per
   step into `test-results/step-by-step/`. Every fault in section 3 was visible
   in those pictures and invisible in the assertions, which is the whole reason
   that spec exists.

---

## 8. Known broken, and deliberately not touched

- `test_no_option_decides_for_itself_which_plane_to_open_on` fails, and failed
  before this branch: `neuroglancer-under/viewer.js` no longer imports
  `../planes.js`. Outside the eight steps, so it was left alone.
- `whenChannelsChange` is on the neuroglancer handle and in use by the panel, but
  is still not written into `contract.md`. The three additions made here are; this
  older one is not, and the omission predates this work.
- The Playwright checks added here need `ZV_SOURCE` pointing at two served
  stores and skip themselves without it. That is the same arrangement
  `viewer-panel-eyes.spec.js` already used.
