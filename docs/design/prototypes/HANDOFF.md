# Handoff — ZMART operator page prototype

Paste the section below into a fresh session. It is written to be
self-contained: nothing in it depends on the conversation that produced the
prototype.

---

Continue work on the ZMART operator-page prototype. It is a **mock** — a real
microscope gets wired in later — so it should work well and be easy to change,
not be correct about physics.

## Start here

1. Read `workflows/target_acquisition/webapp-ui/ARCHITECTURE.md`, then the
   rest of this. Get the page running and click through it — most of what
   follows is easier to see than to read.
2. **Say what you would do and why before changing anything.** Check the
   reading against what is actually on screen.

**The focus map is on the canvas, not in a tab.** Step 4 draws its heatmap over
the plan with the canvas's own projection, and its controls — the pattern
picker, the point list, the sweep and its preview — sit in the channel beside
it, named `Focus strategy` at the right end of the tab row. Points are laid as
a **pattern per compartment** — `First` (top-left position), `Interval` (every
nth), `Center`, `Random` (n distinct) — with a number box only where a pattern
asks for one, and always land **on scan positions**, never beside them.
Clicking the canvas is the other lane, not a mode: a press takes the position
under it, a press on a placed point removes it, and a press over no position
pans. SURS and the whole-canvas scope are gone.

**Discovery is the same shape as focus.** Step 6 has no tab of its own: the
canvas keeps the picture — the cells it finds land there — and the channel
holds the settings (algorithm, its parameters, `Test on this tile`) with the
one **test position** beneath them: a pager, the tile preview, and what the
settings found on it. Picking the test position is either the pager or a
press on the canvas — the press takes the position under it, marks it on the
canvas, and resets `tested`, so the step's gate stays honest. The markup for them
is parked in `index.html` under `#focus-controls` and moved into the channel
while the step is standing, so it is built and wired once; anything that writes
into it asks `focusMounted()` first, because the channel hands it back when the
step is left.

**The step that defines the overview positions is built.** It is step 3,
Initial scanfields: a geometry editor and a grid mode in the channel beside the
canvas, ported from `06_scanfields.jsx`. The grid reads the carrier's area
centres, so the plate decides the plan.

**The editor's interaction model, since it is not all obvious from the source.**
The left button does whatever is under it: the editor is asked first, and only
what it turns down pans the stage — so a press on a field picks it up and a
press on empty canvas both lets go of the selection and moves the picture. A
double-click finishes a polygon, and the duplicate vertex its second press
leaves behind is dropped; Alt+drag pans regardless, and without it there is no
way to move the stage while a drawing tool is armed. The cursor is set by the
editor rather than by CSS, and says what the next press will do: `pointer` over
a field or a grip, `crosshair` with a tool armed, `default` otherwise.

**Exactly one thing is ever highlighted.** A grip beats the field it sits on
and the field behind it, and the nearest grip beats the rest — several are
inside the same twelve pixels once a field is small or the view is zoomed out.
Highlighting is a claim about what the next press will take hold of, so two of
them at once is worse than none. Point stays armed after use and its button toggles off; every other
tool disarms itself after one shape. A polygon is drawn closed from the first
two points, with the cursor standing in for the vertex about to be placed.

Three places it deliberately parts company with the JSX. Hover and selection
read the same, rather than as three weights. Grid positions can be picked,
given a preset and deleted but not dragged, because where they are is the
carrier's statement and the next Apply would silently undo a hand-move. And
**marked means brighter** — the field's ink and its tiles go to more chroma,
which is the one signal every kind of field can carry: a region has an outline
to thicken, a grid position has only its tile, and a tile cannot grow without
saying something false about how much of the sample it takes in. Away from grey
rather than towards it, because a plan is mostly tiles and darkening drags the
marked ones towards the greys the carrier is drawn in. A grid position
therefore draws nothing of its own at all; the tile is the position — and when
a preset's frame is under a pixel wide, a mark stands in for the tile, or a
high-magnification plan is hundreds of positions and an empty canvas.

Everything else about how objects appear, select, resize and rotate follows the
JSX — including that fields are clamped to the carrier, which the first port
missed.

**The sample follows the plan.** Tissue belongs to the plate — soft patches
over the carrier, there whether or not anybody looks. Cells belong to the plan:
they are generated inside the tiles the fields ask for, so the run only knows
about what it imaged. Move the fields and a different sample comes back. The
scan, the focus map and the tile detection is tuned on all read the same list.

## Where it is

- Clone: `C:\ProgramData\MinicondaZMB\home\t.de\ZMART-microscopy_main`
- Branch: `design/operator-page-prototype` on
  `github.com/thomdehoog/ZMART-microscopy` — **public repo**. The branch may
  run ahead of the remote — check `git log @{u}..HEAD` rather than assuming,
  and do not push without asking.
- The live project: `workflows/target_acquisition/webapp-ui/` — a Vite app.
  **Read its `ARCHITECTURE.md` first.**
- `git` is not on PATH: `C:\ProgramData\MinicondaZMB\Library\bin\git.exe`

`docs/design/prototypes/operator-page-layout.html` is a frozen snapshot from
before the Vite move. Not the working copy; do not edit it.

## Running it

Node lives in the project conda env. Everything — node, `node_modules`, the
Playwright browsers — must stay under `C:\ProgramData\MinicondaZMB\`, because
AppLocker refuses to run executables from user-writable paths.

```bash
# POSIX form, not C:/... — bash splits PATH on the colon, so "C:/..." is two
# junk entries and python silently falls through to another env
E="/c/ProgramData/MinicondaZMB/envs/zmart-microscopy"
export PATH="$E:$PATH"
export PLAYWRIGHT_BROWSERS_PATH="C:\ProgramData\MinicondaZMB\home\t.de\ms-playwright"
cd workflows/target_acquisition/webapp-ui

npm run dev        # http://127.0.0.1:5174 — hot reload
npm run build      # one self-contained file -> ../workflow/webapp/static/
npm run test:unit  # vitest, ~146 tests, ~1 s
npm run test:ui    # playwright, ~24 tests, ~130 s
python dev_window.py   # the page in a native pywebview window, still hot-reloading
```

CSS edits hot-swap and keep the run's state; a JS edit reloads the page and
resets it to step 1.

## What the page is

A narrow left rail of workflow steps; one layout for every step — the canvas
on the left from the very first step, and the standing step's controls in a
channel on the right whose width the operator drags with the divider (canvas
bigger by default). Eight steps in `target_acquisition`:

1 Connect · 2 Carrier configuration · 3 Initial scanfields · 4 Focus strategy ·
5 Scan the overview · 6 Discover Targets · 7 Refine Targets · 8 Acquire Targets

There is no presets step, no Disconnect step, no Save-the-run step, and no
Restart button: each preset is recorded in the step that uses it, the session
card's own Disconnect ends a run, and choosing a workflow (re)starts one. Two
other workflows exist to prove the frame is not built around one:
`overview_only` (5 steps) and `focus_check` (5).

## Decisions already settled — do not relitigate without asking

**Frame**

- The rail is **navigation only**: number and title, nothing else. The number
  carries the state — grey ahead, **green done**, **blue where you are**, and
  blue wins on a step that is both. There is no tick and no note: the badge
  says done, and what a step produced is on the canvas and in the action bar.
- **Nothing advances by itself.** Finishing a step leaves you on it. The rail
  still gates order — only the next step is enabled.
- **A step's action sits at the end of what it operates.** There is no action
  bar. Steps with a tab panel get a foot at its bottom; the carrier's is inside
  its channel. The button carries `.step-run` wherever it lands, which is what
  the tests find it by. `ownButton: true` means "this panel builds its own"
  (Connect does). Carrier configuration and Initial scanfields have no button
  at all — they are settled by doing the work — and Connect's lives in its
  form.
- **The canvas is always on the stage — and only shows what the run knows.**
  Before a session is open it is empty; the stage limits appear with the
  session, because they are a readout from the connected microscope's
  configuration; the carrier appears at its own step, when the run is told
  what the sample is mounted in. Every step keeps the picture on the left and
  puts its own controls in the channel: the session card, the carrier
  designer, the scanfield editor and its preset, the focus patterns and their
  preset, detection, the gate, the gallery and the acquisition type — one
  layout, no tabs of their own. Configuring the carrier fixes the run's zero
  too, which is why no step asks for an origin; that happens behind the
  scenes and is deliberately not drawn.
- **The channel is resizable**: its edge is a divider the operator drags. The
  width lives in `--side-w` on the root, survives walking between steps, and
  is clamped so neither the picture nor the controls can be crushed. The
  canvas is the bigger half by default.
- **A tab is always drawn, even alone**, because it names what is loaded —
  the Canvas. It said "Setup" for every step once, and hiding it lost nothing.
- **The channel beside the canvas is headed, not tabbed**, and **it belongs to
  the step standing in it**. Carrier configuration owns it on step 2, Initial
  scanfields on step 3; the heading sits at the right end of the tab row over
  the column it heads, styled exactly as a selected tab, because it names whose
  controls those are rather than offering a switch. One column, not two: a
  second would take width from the picture to hold controls for a step nobody
  is on. A step with no side widget gives the canvas the whole width.
- **A panel belongs to its step** and shows only while that step is selected.
  Walk back to Connect and the session and its checks are there again.
- Step **numbers are derived from position**, never typed.

**Setup panels**

- **Connect** is a form headed "Connect to the microscope": microscope, API,
  password, and its own button. Opening the session runs six checks that land
  one at a time (reachable, credentials, API version, stage, objectives,
  storage). An open session is **not editable** — its Disconnect button ends
  the run and is how you begin again. Nothing says "not connected" before it
  is; the fields and the button already do.
- **There is no presets step: each recording lives in the step that uses it,
  so the state is tested where it matters.** Three single-recording slots,
  all drawn the same way — a bold heading, a name box and a **Record
  Microscope State** button; recorded, the bar *becomes* the record in place
  (unfoldable to everything the controller returned, forgettable with ✕):
  - `RECORD ACQUISITION PRESET` heads the Initial-scanfields channel. The
    fields take their frame from it, so the editor waits behind it — and
    forgetting it takes the editor and the plan away again.
  - `RECORD AUTOFOCUS PRESET` heads the Focus-strategy channel; Apply
    strategy waits for it, since the sweeps are measured with it.
  - `RECORD ACQUISITION TYPE` heads the Acquire-Targets channel; the acquire
    button waits for it.
  - Names are capitalised on the way in; `renderRecordingSlot` in `main.js`
    is the one implementation all three share.

- **Carrier configuration** is a full designer, not a dropdown: type, preset,
  rows/columns, area size, pitch and corner, each pair tieable. It has **no tab
  and no picture of its own** — it is what the canvas is drawing, so the
  controls dock in a channel to the right of the canvas and the carrier itself
  is drawn on the stage. One drawing, not two.
  - The channel is **not a menu for step 3**. The frame outlasts the step that
    set it: readable whenever the canvas is.
  - **No Apply button.** Configuring is the work, the way recording is — it always holds a valid carrier and every edit is already on the canvas.
    Standing on the step settles it. It stays editable until a later step has
    run, since that is when changing it would invalidate what was done.
  - `widgets/carrier.js` holds the controls *and* `drawOn` — one subject, one
    file — over the geometry in `lib/carriers.js`. It is the first extracted
    widget and the shape the rest should follow.

**Two panels worth understanding**

- **Focus strategy** works on the position list, not on imagery. Model chosen
  by geometry, matching `workflow/_focus_surface.py`: constant / least-squares
  plane / thin-plate spline, smoothing 0.1. Both sharpness metrics are drawn on
  one plot and the legend is the control. Peaks narrower than 4.5 µm are not
  tissue and are rejected but still drawn; dragging the line overrules the pick
  and the preview beside it defocuses as you drag.
- **Detection** is tuned on one tile before it may run the sample.

## How this user works — read this, it will save a cycle

- **Simplify wherever it makes things more powerful.** Fewer options. Better to
  add one later than ship one that has to be removed.
- **No redundancy.** One owner per fact. If a constant or rule needs to exist
  twice, the split was wrong — merge it back. Redundancy creeping in is the
  signal that something is over-split.
- **Nothing fixed in place.** A value typed at the point of use is a value in
  the wrong module. Derive it, or give it an owner.
- **Do not over-test at prototyping pace** — but do test before building
  further on something. The browser suite is a smoke net, not a specification.
- Expect **many small steering messages**, often mid-turn. Apply them, run the
  suites, commit, and say what changed. Small commits, each green.
- Screenshots are worth taking and *looking at*: several real defects here were
  invisible to assertions.

## Defects this shape has produced twice — watch for them

- **Re-rendering on input destroys the field being typed into.** Fixed for the
  password and the preset name by updating only what depends on the value.
  Any new form field will do it again unless handled.
- **Alignment drifts from structural causes**, not wrong numbers: a
  `grid-column` on a child of the wrong grid conjured an implicit column; a
  label sibling to a list inherited a different gap than one inside a group.
- **An explicit `display` beats the `hidden` attribute** — `.action-bar[hidden]`
  needed saying, and `.panel-foot:empty` does now.
- **A stray `}` in the stylesheet silently ate every custom property after
  it.** The channel and its heading came out 461px and 156px instead of 320,
  both falling back to content width, and the page looked plausible. Measure
  in the browser; do not trust the eye for widths.
- **A fixed-height child overflows its panel and swallows clicks** on whatever
  is beneath it. The focus trace strip did this to Apply strategy; the browser
  suite caught it as a click timeout naming the intercepting element.

## The state of the code — the important caveat

`src/main.js` is **2,600 lines and runs the whole app**. Beside it are modules
that are tested but **not all of them are used**:

| part | state |
|---|---|
| `lib/carriers.js` | tested and **used** — by the app and by the carrier widget |
| `lib/microscopes.js` | used |
| `widgets/carrier.js` | used — the first widget, and the shape the rest should follow |
| `lib/surface.js`, `lib/sweep.js`, `lib/rng.js` | tested; **main.js has its own copies** |
| `lib/sample.js` | tested; not used |
| `frame/steps.js` | tested; only `numbered()` is used |
| `backend/mock.js`, `workflows/` | tested; **not used, and now stale** |

So **surface fitting, the sweep, the sample and the workflow declarations are
each defined twice**. `main.js` is what runs; the modules are what the unit
tests cover — the suite can stay green while the app drifts. **If you change a
rule, change it in both**, or do the de-duplication first: have `main.js`
import them and drop its `mode` switch in favour of `step.run(ctx)`. That is
contained and touches no UI code.

`workflows/` is worse than unused — it still describes the job-picker flow
that was replaced, with no `optics` or `carrier` step. Rewrite it from
`main.js`, do not merge into it.

**A widget owns its panel and redraws itself.** `widgets/carrier.js` is the
pattern: handed a value and a callback, knows nothing of run state, and writes
new values into the controls that already exist rather than rebuilding — a
rebuild per keystroke destroys the field being typed into. It exports `drawOn`
too, because the controls and what they put on the canvas are one subject.

The rest is still inline in `main.js` on purpose: while the UI is being
designed a single file is faster to iterate in, and boundaries drawn around a
moving design get redrawn. Take a panel out when it stops moving.

## Open questions — ask, do not invent

- Which preset the *acquisition* uses. The scan side is answered: a scan field
  names the preset it is taken with, and the tiles covering it are that
  preset's frame — which is now a number on the reading rather than words
  inside its detail line. Nothing yet says which preset step 9 images cells at.
- **Where the carrier sits on the stage** is centred in the travel, and that is
  a default rather than an answer: the real offset comes from calibrating
  against a plate actually on the stage. `carrierOriginUm()` is the one line
  that answer replaces, and everything the run produces is placed through it,
  so the carrier and what was imaged inside it move together.
  `STAGE_LIMITS_MM` (120 × 80) is still a placeholder, standing in for what the
  controller will report.
- The synthetic sample is still a 7×5 tile grid unrelated to the carrier, so
  the scan area sits in the plate's corner rather than inside a well.
- Should the canvas show the planned tile grid before the scan, or stay blank?
- A single click in the focus trace jumps the line; it is not drag-only.
- The focus step wants ≥3 points, but `_focus_surface.py` accepts 1.
- `lib/microscopes.js` now carries microscopes, APIs, connect checks, setting
  types and carriers — more than its name promises. Wants splitting by subject.
- The password is prefilled (`demo`) for clicking through. **A real build must
  ship that empty.**

## The north star — context only, out of scope

Eventually an agent composes workflows: you describe a run and it assembles the
steps and the right-hand panels. That is why steps and panels are declarations.
The boundary to protect: **a workflow declares, the frame owns.** Declarations
get ids, titles, sentences, button labels, prerequisites, and which panels from
a fixed registry. The frame keeps the canvas projection, layer compositing,
selection state, the ordering guard, and every hardware call.

`backend/` is the seam where the real microscope arrives. Steps call the
backend and await — never a timer, never hardware. If wiring a microscope ever
means editing a widget, the seam leaked.
