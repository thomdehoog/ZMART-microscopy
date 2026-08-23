# Handover: the flicker the operator sees, and how to catch it

*Written 2026-08-23, at the end of a long day of work on branch
`claude/thy1-linked-spiral`. The operator sees the picture flicker in the
native ZMART Viewer window and asked for it to be found and fixed. This file
is everything the next session needs to pick the hunt up exactly where it
stands, without redoing a step of it.*

## The symptom

While using the viewer — most recently around sequential replays of
`backend/test_stores/test_grid_16` — the operator sees the picture flicker.
This class of fault was cured once before: the repository maintains one
patch against its pinned Neuroglancer
(`frontend/scripts/patch_neuroglancer.mjs`) that reroutes chunk
invalidation into keep-drawing-until-replaced delivery, so a live commit
never paints a black frame. The gate that holds that cure in place,
`tests/test_the_screen_never_goes_black.py`, **passes today** — so either
the flicker travels a road the cure was never wired to, or it lives in an
engine the gate never runs.

## What has been measured (all of it reproducible)

- `probe_the_flicker_in_chromium.py` (this folder) drives the operator's
  exact road — sequential tab, `test_grid_16`, Open — in headless Chromium
  and samples the lit fraction of the picture at 10 Hz through all sixteen
  landings. Result, three runs: **flat 1.0 after first visibility, zero
  drops**. Chromium does not flicker.
- An earlier, cruder probe reported four fully-black samples, which set off
  this hunt — but those zeros were the *first* samples, taken before the
  first position had landed. Arrival is not flicker; the detector was
  wrong, not the picture. Do not chase that ghost again.
- API-driven replays (no camera move, page watching from the side) are also
  flat: no layer rebuilds, no coordinate-space changes, sampled at 6–12 Hz.

## The prime suspect: the engine in the native window

Chromium is clean and the operator watches through **pywebview, which is
WKWebView — Safari's engine**. Today already produced one bug with exactly
this shape: the sliders' blue fill, drawn fine by Chromium and never drawn
by WKWebView. A WebGL-heavy canvas being invalidated per commit is a
plausible place for the two engines' compositors to behave differently.

Two prepared ways to catch it in the act:

1. **Photograph the native window itself** —
   `probe_the_flicker_in_the_native_window.py` (this folder) finds the
   pywebview window (owner `python`, the large one), starts a replay
   against the running viewer on port 8848, and screen-captures the window
   ~8 times a second, measuring the lit fraction of the picture area.
   It needs macOS **Screen Recording permission** for the terminal; the
   operator granted it at the very end of the session but the terminal was
   not restarted, so the probe has NOT yet run with permission. Start here:
   run the viewer (`python run_demo.py`), run this probe, read the trace.
2. **Playwright's WebKit browser** — same engine family as WKWebView,
   headless, no permissions needed:
   `python -m playwright install webkit` (was interrupted today), then run
   `probe_the_flicker_in_chromium.py` with `p.chromium` swapped for
   `p.webkit`. If WebKit shows drops where Chromium shows none, the fault
   is engine-specific and can be hunted entirely headlessly.

## If the probes stay flat everywhere

Then the flicker is not the picture emptying, and the next candidates are
things a lit-fraction probe cannot see: the 120 ms veil fade on open
(`NeuroglancerView.jsx`), brightness snapping when the automatic window
measurement lands on a still-arriving channel (`App.jsx`, the effect marked
"A channel that arrives knowing nothing about its brightness"), or a
repaint hitch specific to the native window's compositor. Ask the operator
to point at the moment: *what was on screen, what did they press, does it
blink black, white, or jump brightness?* One sentence from the chair is
worth an afternoon of guessing.

## Rules that bind any fix (the operator's, all dated 2026-08-23)

- Never a new mechanism beside an old cure: route the broken road through
  the existing patched delivery / veil philosophy.
- Change only what has to change; better, not different.
- Raw data is read-only, always.
- Prove the fix with the probe (three clean runs), then extend
  `test_the_screen_never_goes_black.py` with the scenario so it stays
  fixed.

## Where everything else stands

Suite: **923 passed, 0 failed** as of `83a2d645`. The awkward-store battery
(`backend/make_awkward_stores.py` + `backend/sweep_awkward_stores.py`)
passes 18/18. The ladder benchmark (`measure_the_ladder_in_the_view.py`)
puts the churn at 0.06 requests/position at 1024 positions. The flicker is
the one open item, tracked as task #17 in the session task list.

## Decisive fact, added last: this is a regression

The operator states there was **no flicker in previous versions**. Today
put ~30 commits on this branch, so the fault is IN that range and `git
bisect` will corner it — drive each candidate build down the same road
(open the viewer, replay `test_grid_16`, watch) and mark good/bad. Rebuild
the frontend at every step (`npm --prefix frontend run build`), because the
served page is `dist`, not `src`.

Candidates worth suspecting first, newest concerns last:

1. **The veil** (`a0409824`, "The picture is unveiled only after its first
   fit") — it added a wrapper and a 120 ms opacity transition around the
   engine's canvas in `NeuroglancerView.jsx`. If WKWebView re-composites
   that layer badly, every redraw could shimmer. Cheap test: set the
   transition to none and the opacity permanently 1 in a scratch build.
2. **The themed ground** (`2f82ee82` + `c4fe41e8`) — `syncView` now calls
   `getComputedStyle` on every change to the view, and the engine's ground
   colour is re-asserted constantly. Cheap test: hard-code black there.
3. **Answer-at-declaration replay** (`0c8327d7`) — layers arrive and
   refresh per landing rather than once.
4. **The automatic window measurement** (`0c8327d7`) — a brightness snap
   when a measurement lands can read as a blink, though it happens at most
   once per channel.

The one-day-earlier state, known good per the operator: anything before
today's first commit (`8330ae5d`, the slider fill). `git log --oneline
8330ae5d^..98153a31` lists the whole suspect range.
