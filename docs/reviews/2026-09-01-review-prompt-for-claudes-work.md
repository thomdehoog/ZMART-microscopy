# A prompt for reviewing this session's work

**Date:** 2026-09-01.
**Repository:** `thomdehoog/ZMART-microscopy`.
**Smart Viewer:** a *separate* repository, `thomdehoog/ZMART-viewer`, commit
`9ff10b0`, version 0.2.0. Cloned here at `/home/user/thomdehoog/zmart-viewer`.
Install it with `pip install --no-deps -e .` — a plain install stops on
`proxy_tools`, a `pywebview` dependency the server itself does not need.

This is written for whoever reviews the work next, and it is deliberately more
interested in what is doubtful than in what went well. Nothing below should be
taken on trust; every claim names the check that produced it so it can be
repeated or overturned.

---

## What to review, and where it is

| Branch | What it holds | State |
|---|---|---|
| `claude/viewer-port-remaining-steps-ofm5qp` | The eight steps of the viewer port, the canvas fallback view, and two review documents | 9 commits, pushed |
| `claude/every-field-reaches-the-canvas` | One fix to the source reduction, with six tests | 1 commit, **superseded by PR #24** |
| `claude/step-five-kidney-evidence` | The Step 5 evidence check, on real tissue | 1 commit, pushed |

Two documents already on the first branch carry the background and should be
read before the code: `2026-09-01-handover-smart-viewer-integration.md` and
`2026-09-01-review-of-the-smart-viewer-integration-plan.md`.

---

## The three things most likely to be wrong

Start here. These are ranked by how much a careful reader would repay the
project by disagreeing.

**1. The canvas fallback view (`4ab5903`).** This is the largest and least safe
change of the session. It gives `application/parts/canvas/viewer.js` a view of
its own, used whenever the drawing engine cannot place things — which is every
step before a run has captured anything, because neuroglancer takes its axes
from its image layers and has none. It also attaches a second pair of pan and
zoom gestures and swaps which of the two may lend a drag to a tool.

A first attempt at that silently stopped lent drags reaching tools and broke
four checks in `parts/canvas/canvas-layers.spec.js`; the rewrite makes exactly
one of the two sets listen at a time. Look hardest at
`whoeverCanPlaceThingsHoldsTheDrags`, and at whether the canvas's copy of the
view can drift from the engine's while the engine is the authority. Note also
that `theViewNow()` and `aFrameWeCanDrawWith()` write to `ourOwnView` as a side
effect of being asked a question — deliberate, since it is how the copy
follows, but easy to misread.

**2. The panel is one very large function.** `viewer-panel.js` has gone from 688
lines to about 1,435, nearly all inside `mountViewerPanel`. It works and it is
checked, but the next person to change it will find it hard, and that is a fair
thing to insist on before it grows again.

**3. The port was made against the wrong reference.** Everything in the panel
follows `viz_studio/frontend/src/`, which is an older copy. Smart Viewer 0.2's
own `LayerPanel.jsx` is 1,745 lines against that copy's 1,012. The maintainer
said so at the outset and it was not acted on until late. What the panel *asks
of the engine* — the three contract additions — is a separate question and
likely survives; how it *looks* should be checked against 0.2 before it is
trusted.

---

## What was built, and what each thing is worth

Judge these separately. Some are firmer than others.

**Firmest — plain arithmetic with no viewer in it.**
`application/parts/canvas/counting-planes.js` and `the-window.js`, twenty-three
unit checks between them. If the panel is rewritten these should survive it.

**Firm — the contract additions.** `whenTheViewMoves`, `theMomentsItCanShow`,
and `setChannel({ lut })` with `lutsItCanDraw`. Each is answered by all four
options in `viz_studio/options/`, and each has a guard check in
`viz_studio/tests/test_the_options_hold_together.py`. These describe the
boundary between the operator and *any* drawing engine, so they are largely
independent of which viewer wins.

**Worth keeping, found by running rather than reading.** The acquisition
heading's eye could hide a whole acquisition and never bring it back: `refresh`
drew the eyes from the picture, correctly, and also wrote that back as the
operator's own choice, so while an acquisition was hidden every one of its
channels was recorded as one the operator had turned off. Already failing before
this work. The contrast track falling back to the window the run declared rather
than to the whole sixteen-bit range — measured, the difference between about two
pixels of usable slider and a working one. And the colour chooser opening on
whichever side has room, after the colour maps made it run off the screen.

**Superseded.** `claude/every-field-reaches-the-canvas` changed the source
reduction from "keep one URL" to "keep every URL in the newest dataset". PR #24
carries that reasoning forward correctly and adds the part that was actually
missing, so the branch should not be merged. Two things about it are worth
saying plainly. Its commit message is more confident than the evidence
supported — it was written before the change had been run in the real walk, and
running it showed the fix did not by itself make Step 5 work. And its test
wording calls several position-store addresses a "composed acquisition", which
is wrong: a composed scene is normally one `*.zmartview.zarr` address, and these
are a watched multi-store acquisition. PR #24's review says both, and is right
about both.

---

## Corrections made during the session, which say something about the method

Three claims were made and then withdrawn. They are listed because the pattern
matters more than any one of them: each came from reading a label instead of
taking a measurement, which is the exact failure this whole piece of work exists
to remove.

- *"The registration spec confirms the picture is misaligned."* It does not.
  Both its tests time out on `waitForFunction(() => !!window.__thePicture)` —
  the picture never opens in that harness, so the projection comparison is never
  reached. Verified identical at `93e374c`, so it predates this work. **The
  alignment question is still open**, and repairing that harness is the way to
  settle it.
- *"Composition is not happening."* It is. `loading.load` on a positions folder
  returns `overview.zmartview.zarr`. The loss was downstream, on this side.
- *"`/api/stores/construct` is the missing call."* It is not. `open` already
  covers the run-of-positions case in 0.2.

A reviewer should assume there are more of these and look for them.

---

## The Step 5 evidence, and what it does not yet prove

`application/step-five-kidney-evidence.spec.js` on
`claude/step-five-kidney-evidence`. A slide carrier gives exactly nine fields in
one tileset; the mock microscope draws from a real micrograph of mouse kidney.
Run with `PYTHON=python3 npx playwright test step-five-kidney-evidence.spec.js`.

It passed against PR #24, and it asserts two things worth having: every planned
field is measured **separately** — a scan of nine that drew four looks, from far
enough away, exactly like one that drew all nine — and each field is asked how
many distinct shades it holds, so a fault that paints every field one flat
colour in the right place fails rather than passes. The focussing is put away
through the engine, and the engine and the panel's eyes are then both asked what
they say about it.

**Three honest gaps:**

1. **There is no 3-of-9 or 6-of-9.** The nine-field scan finishes inside one
   poll of the bridge, so photographing Step 5's own Run button cannot catch the
   intermediate counts — all three photographs were taken at nine, and the file
   names record that rather than pretending otherwise. The deterministic set
   needs `live-bridge.js`'s `image(positions)`, which exists for exactly this
   and drives the bridge one call at a time. That is a second pass and it has
   not been written.
2. **It was run with PR #24's `viewer_service.py` applied to the working tree**,
   not on the PR branch itself. The result should be reproduced on the branch.
3. **It does not check registration**, because the harness that would is the one
   that times out.

---

## Findings against PR #24, for whoever arbitrates

The four decisions — open each folder once, refresh `/api/config` on the poll,
retain every same-dataset source, remove relinking — are all sound, and the
account of why the bridge froze the first answer is better than the one offered
here earlier. The stale-scene reproduction was repeated independently: composed
with two stores, `tiles.json` declares two; a third store lands, the same folder
is opened again, the scene path is reused and it **still** declares two. So the
thirty-second relink should not come back, and this session's own throttle was
defending an assumption that stopped being true at 0.2.

Three things to put to it:

1. **`_read` uses a thirty-second timeout on a one-and-a-half-second poll.** If
   `/api/config` ever takes longer than the poll interval, requests pile up —
   the bridge is threaded, so slow polls become threads queued against the
   viewer. A short timeout would degrade to "keep the last usable list", which
   the code already handles. This is the one change worth asking for before
   merge.
2. **A rerun is not exercised.** `opened` is held for the life of the service, so
   *Run again* never reopens. New stores are picked up by the watch, but a rerun
   that replaces stores under the same names relies on the viewer noticing
   changed bytes, and nothing tests it.
3. **Twenty-seven channel rows.** With every field passed through, the engine
   holds nine `overview` sources of three channels each and the panel groups
   them under one heading with twenty-seven rows. Functionally right, and it
   reads as a fault to anybody looking at it.

---

## Things not in any diff

The container was changed to make the workflow runnable, and none of it is in
the repository:

- miniconda at `/opt/miniconda3`, against conda-forge, because Anaconda's own
  channels now require accepting terms that were not this session's to accept;
- the focus environment `ZMART--focus--main`, built by the repository's own
  `setup_env.py`, whose three diagnostics pass;
- `zarr`, `numpy`, `tifffile`, `imagecodecs`, `scikit-image`, `pooch` — the mock
  microscope's sample comes from `skimage.data.kidney()`, which `pooch` fetches
  once;
- Smart Viewer 0.2 installed with `--no-deps` from the clone above.

A stand-in `zmart_viewer` package was written into `dist-packages` early on,
pointing at `viz_studio/backend`, and removed once the real repository arrived.
It should not come back.

---

## Known broken, and left alone deliberately

- `test_no_option_decides_for_itself_which_plane_to_open_on` fails, and failed
  before any of this: `neuroglancer-under/viewer.js` no longer imports
  `../planes.js`. Outside the eight steps, so untouched.
- `the-scan-under-the-plan.spec.js` times out before its alignment assertion, at
  `93e374c` as well as now. Repairing it is the only way to settle the
  registration question.
- `whenChannelsChange` is on the neuroglancer handle and used by the panel but
  still is not written into `contract.md`. The three additions made here are;
  this older one is not, and the omission predates this work.
