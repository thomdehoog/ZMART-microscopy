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

---

## RESOLVED, 2026-08-23 (the following session)

The flicker is found, fixed, photographed, and gated. What follows is the
record, so nobody hunts this ghost twice.

### What it was

Not WKWebView, and not the chunk delivery. **Chromium flickers too** — the
probes above missed it because they sampled the picture ten times a second,
and the flash lasts 100–300 ms *per landing* but the sampler looked either
side of it. Re-run with a per-frame recorder (`requestAnimationFrame`, the
same technique `test_the_screen_never_goes_black.py` uses), the operator's
exact road — sequential tab, `test_grid_16`, Open — showed the whole picture
at **0% lit for 8–19 consecutive frames after every single landing**, sixteen
times in a run, while the chunk bookkeeping stayed perfectly healthy. The
photographs (specimen → black → black → specimen-plus-one-tile) matched what
the chair sees exactly.

### The mechanism

Every landing advances the run's source revision. `syncSources` in
`frontend/src/engine.js` answered a revision advance in two steps: refresh
the decoded pieces in place (correct — that is the patched
keep-drawing-until-replaced delivery), and then `source.spec =
{ ...source.spec }` to make the engine re-resolve the picture's address.
That second step is the flicker. Neuroglancer answers a spec assignment by
**throwing the loaded source away first** and resolving the address again
afterwards — and between those two moments the layer has no drawing layers
at all. Per-frame layer counts made it plain: 17 render layers → 11 → black
→ 17 again, at every landing.

The re-resolution bought nothing: a governed picture's description is
written once, at declaration, and never moves (`declare_a_governed_picture`
— "the frame was never derived from what has arrived"). Re-reading an
immutable description cost the operator the picture, sixteen times.

Why it regressed: the mechanism itself predates the suspect range
(2026-08-21), but until the answer-at-declaration replay (`0c8327d`) the
road was rarely driven — landings did not advance revisions one at a time,
so the teardown fired rarely instead of per landing.

### The fix

One deletion in `engine.js`: a revision advance no longer re-sets
`source.spec`. The refresh is pixels-only, delivered in place through the
patched keep-drawing route. The camera, the operator's settings, and — now —
the drawing layers all stay exactly where they were.

Proved on the operator's road with the per-frame probe, three runs: zero
downward steps, zero layer teardowns, the picture only grows as the sixteen
tiles land. The refresh still genuinely happens: revision advances are
answered with piece requests and the new tile appears (the manifest refresh
contract suite passes unchanged).

### The gate

`test_the_screen_never_goes_black.py` now carries a second test,
`test_the_screen_never_goes_black_when_a_position_lands`: a real landing on
a live run, watched frame by frame. It asserts the picture never collapses,
the drawing layers are never torn down, and the landing genuinely arrived.
Falsified against the old code before being trusted: with the spec reset
restored it fails exactly as the operator saw it — "dropped from 46% lit to
0% lit for 9 frames (167 ms)".

### What remains true, and one thing worth knowing

- The 10 Hz sampling is superseded: sample per frame or not at all. Its
  "Chromium is clean" was a statement about the sampler.
  `probe_the_flicker_in_chromium.py` has been rewritten accordingly — it now
  watches every drawn frame, ignores drops caused by the camera being
  steered, and exits red the moment the picture loses ground with the
  camera still. `probe_the_flicker_in_the_native_window.py` still samples at
  ~8 Hz because a screen capture cannot ride the page's frames; treat a
  clean answer from it as weak evidence and a dirty one as strong.
- The veil, the themed ground, and the brightness snap were not implicated;
  the per-frame recorder saw no other dips over the whole sixteen-landing
  road.
- One bounded residual, deliberately left alone: when a store's committed
  frame count genuinely moves (a timelapse growing past what the engine had
  read), the `grown` branch of `syncSources` still re-resolves the source,
  because there the description really did change. That road tears down the
  same way, but it fires only on true growth, not per landing, and no
  measurement has shown it on an operator's screen. If it ever does, the cure
  belongs one level down — teach the engine to keep the old source drawing
  until its replacement has loaded — not in another special case here.
