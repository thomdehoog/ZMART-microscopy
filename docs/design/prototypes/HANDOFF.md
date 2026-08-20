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

**The focus map is on the canvas, not in a tab.** Step 5 draws its heatmap over
the plan with the canvas's own projection, and its controls — the pattern
picker, the point list, the sweep and its preview — sit in the channel beside
it, named `Autofocus settings` at the right end of the tab row. Points are laid as
a **pattern per compartment** — `First` (top-left position), `Interval` (every
nth), `Center`, `Random` (n distinct) — with a number box only where a pattern
asks for one, and always land **on scan positions**, never beside them.
Clicking the canvas is the other lane, not a mode: a press takes the position
under it, a press on a placed point removes it, and a press over no position
pans. SURS and the whole-canvas scope are gone.

**Discovery is the same shape as focus.** Step 7 has no tab of its own: the
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
Overview scan settings: the ways of making fields in one box beside the canvas,
ported from `06_scanfields.jsx`. The grid reads the carrier's area centres, so
the plate decides the plan. Drawing and the grid share that box under a title
apiece, `GEOMETRY` and `GRID OF POSITIONS` — they are two answers to the same
question and the operator moves between them without leaving anything; the
verb sits on the button that does it, `Add grid` — and **the box is only there once a
preset has been recorded**, going again with the last one forgotten. It used
to stand greyed on the argument that a step showing what it will be beats an
empty column; with the recording above it saying what it waits for, a greyed
copy of the whole editor said it twice.

**What the objective sees must be inside an area.** A tile whose frame does not
fit wholly inside one of the carrier's areas is not in the plan — a square
hanging over the edge of a well is a square of plastic, and imaging it costs
what imaging sample costs. Three consequences worth knowing before reading a
number off the screen:
- **A block is only as big as a well can hold.** Three by three at 5x, whose
  frame is 2.66 mm, lays *one* position in a 6.6 mm well and nine in a 34.8 mm
  one. The same numbers on a different plate — or the same plate through a
  different objective — give a different plan, which is what changing the
  objective actually does.
- **A field is imaged in one area — the one it covers most.** A rectangle drawn
  over the gap reaches into two wells, and covering both is almost never what
  was meant: it is one sample, in one well, and the outline was loose at the
  edge. The larger share wins and the rest of the outline images nothing.
  Splitting it would quietly turn one field into two acquisitions of two
  different samples. Ties go to the first, which is the top-left of the ones
  tied, because the tiles are counted row-major.
- **What a run images inside an area is a square, whatever shape the area is.**
  A well is round and a plan is not: tiles laid to the edge of a circle come
  out as a rounded blob, no two rows the same length, an outline nobody drew.
  `scanBox()` in `lib/carriers.js` is the area's own rectangle with the corner
  arcs cut back to their chords — the whole rectangle when there is no corner,
  the inscribed square when the area is a circle — and every fitting test is
  against that. **An Area carrier is square-cornered**: the soft corner a glass
  slide happens to have is not part of what can be imaged in it, and carried in
  the preset it pulled the imageable rectangle in at every edge for a shape
  nobody was working to.
- **A region is drawn and resized in whole frames.** Dragging one out, or
  dragging a grip on it, moves its width and height a frame at a time, so its
  border and the tiles inside it land on the same line: nothing imaged outside
  what was drawn and no strip of it left unimaged. It rounds **down** — the
  shape never grows past the hand — with one frame as the floor, there being no
  imaging less than the objective sees at once. Activating another preset
  re-fits every region to the new frame (sizes only; where each sits is the
  operator's statement). A hand-drawn polygon is the one shape this cannot
  apply to, its outline being arbitrary, so its tiles still cross it by a
  fraction. `snapSpan()` in `lib/scanfields.js`.
- **A region's tiles are one lattice, moved as one.** Where the lattice runs
  over the edge of the area, the whole lattice is pushed back in until it
  fits, so the outline is covered into its corners. Moving the edge tiles on
  their own would fill the corner too, and it would change the overlap between
  an edge tile and its neighbour — the overlap is a number the operator set,
  not slack for the plan to spend. What still hangs over after the lattice has
  moved is dropped: a region wider than the well cannot be pushed into it. So
  is a tile the move carried off the outline it was laid for — moving the
  lattice must not image what nobody drew, which is what `covers()` in
  `lib/scanfields.js` is asked a second time for.
- **A position is seated where it is put down; a region is never moved.** A
  position is one frame and nothing else, so pressed or dropped on the plastic
  it slides into the well it was nearest — dragging one across a plate steps
  from well to well. A region is an outline somebody drew around something
  they were looking at: the plan reads it rather than obeys it, so it stays
  exactly where it was drawn even when it covers no well at all. Sliding it
  would move the statement instead of answering it.
  - **A drag is worked out from where it began**, against the fields as they
    were when the pointer went down — `ed.drag.held`. Stepping the current
    positions on by the last event's delta looks equivalent and is not, once
    seating exists: every step is pulled back into the middle of the well
    before the next one is added, so a position never leaves the well it
    started in while the pointer walks off without it. The browser suite holds
    this down — *a position dragged across the plate steps from well to well*.
- `frameFitsArea` / `frameSeat` / `nearestArea` in `lib/carriers.js` are the
  rule; `plan()` in the scanfields widget is the only place it is applied to a
  plan, and the widget's `clamped()` is the only place a field is seated.

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

- Clone: `C:\ProgramData\MinicondaZMB\home\t.de\ZMART-microscopy_merge`
- Branch: `agent/server-builds-the-picture-opus-5` on
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
bigger by default). Nine steps in `target_acquisition`:

1 Connect · 2 Define Carrier · 3 Register Carrier · 4 Overview scan settings ·
5 Autofocus settings · 6 Scan the overview · 7 Discover Targets · 8 Refine Targets ·
9 Acquire Targets

Register Carrier is a declared **placeholder** — empty channel, and it holds
nothing up (`nothingWaitsOnThis`) until registering the mounted carrier
against the stage actually lives there. There is no presets step, no
Disconnect step, no Save-the-run step, and no Restart button: each preset is
recorded in the step that uses it, the session card's own Disconnect ends a
run, and choosing a workflow (re)starts one. Two other workflows exist to
prove the frame is not built around one: `overview_only` (6 steps) and
`focus_check` (6).

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
  (Connect does). Define Carrier and Overview scan settings have no button
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
  the step standing in it**. Define Carrier owns it on step 2, Initial
  scanfields on step 4; the heading sits at the right end of the tab row over
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
  so the state is tested where it matters.** Three slots, all drawn the same
  way — a bold heading, then the bar that takes the next reading (a name box
  and a **Record Microscope State** button), and under it **one row per
  reading taken**, each unfoldable to everything the controller returned and
  forgettable with ✕:
  - `ACQUISITION PRESET` heads the Overview-scan-settings channel. The plan takes
    its frame from the active one, so the editor waits behind it — and
    forgetting the last one takes the editor and the plan away again.
  - `AUTOFOCUS PRESET` heads the Autofocus-settings channel, in the same box the
    acquisition preset sits in, and the rest of the step appears only once a
    reading is taken. **An autofocus is software or hardware**, and which one
    decides what the step is: software focuses by taking a short stack and
    scoring it, so it needs a focus map — patterns, points, the sweep, Apply
    strategy. Hardware focuses by measuring a beam off the coverslip and holds
    that distance at every position, so it needs nothing: no map, no button,
    and the step is finished the moment such a reading is the active one. A
    step says whether it has anything to run through `acts(run)`, and the
    frame only asks. `softwareAutofocus` / `hardwareAutofocus` in
    `lib/microscopes.js` are two builders rather than one with a flag, because
    a hardware autofocus has no metric, no sweep and no steps.
  - `RECORD ACQUISITION TYPE` heads the Acquire-Targets channel; the acquire
    button waits for it.
  - Names are capitalised on the way in; `renderRecordingSlot` in `main.js`
    is the one implementation all three share, over `lib/recordings.js`.

- **Readings accumulate, and one of them is active.** Recording used to
  replace what the slot held, which said a reading is a thing done once — and
  it is not: the optics get changed in the middle of a session, and an
  overview taken dry at 5x and a detail taken at 63x in oil are one run. So a
  new reading lands beside the old ones, and the newest becomes the active
  one, because a reading is taken in order to be used.
  - **The row is the button: pressing one activates it, and activating is the
    whole of applying it.** Everything the step produces is taken with the
    active recording — the plan included, all of it, at once. There is no
    `Apply to selected` and no `Apply to all`, and a field carries no preset
    of its own: half a plan taken with optics that are no longer in the light
    path is not a state the run should be able to be in. Activating another
    preset re-takes every field where it stands; the plan changes what it
    covers, never where it looks.
  - There is no separate list of presets beside the rows — the same list drawn
    twice is one list and one copy that goes stale. The active preset's colour
    is the dot on its row and the ink the whole plan is drawn in.
  - **One recording is unfolded at a time**: opening a second closes the
    first, since two columns of detail do not fit down one channel.
  - **Three readings is as tall as the list gets**, and it scrolls past that,
    with the active one kept in sight. A slot that kept growing would push the
    ways of laying fields off the bottom of the channel.
  - ✕ forgets a recording whatever has been done with it. Nothing names a
    recording except the step itself, so what is left becomes active and the
    plan follows it. **Forgetting the last one takes the plan with it** —
    regions and grid positions included, not just the tiles: a field says what
    to image and with what, and with no preset left there is no with, so
    outlines kept on the canvas would be a picture of a plan the run could not
    run.
  - The slot is `{ type, from, records, active, seq }` in `lib/recordings.js`,
    with `withRecording` / `withoutRecording` / `withActive` returning new
    slots. Ids are counted, never positional, so a forgotten record cannot
    hand its id to the next one. `from` is which of the mock controller's
    states the slot's first reading comes back as — the acquisition type reads
    from a different one than the overview preset, so a plan that never
    switched objectives cannot look like one that did.

- **The carrier types read Area · Dish · Chamber · Wellplate**, wellplate at
  the right end. **Volume is gone for now** (2026-08-20) — the type, its
  cuvette preset, its icon and its tests. What it needed from the frame is
  still there and unused: a type may declare `deep`, and a carrier with a
  depth is drawn as a box behind its footprint. Nothing on offer declares one,
  and a unit test says so, so the day a deep carrier comes back the frame does
  not have to be rebuilt for it.
- **Define Carrier** is a full designer, not a dropdown: type, preset,
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

- **Autofocus settings** works on the position list, not on imagery. Model chosen
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
| `lib/recordings.js` | tested and **used** — the three recording slots |
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

- Which preset the *acquisition* uses. The scan side is answered: the plan is
  taken with the active acquisition preset, and the tiles covering a field are
  that preset's frame — a number on the reading rather than words inside its
  detail line. Nothing yet says which preset step 9 images cells at, and the
  autofocus and acquisition-type slots keep an active recording that nothing
  downstream reads yet.
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
