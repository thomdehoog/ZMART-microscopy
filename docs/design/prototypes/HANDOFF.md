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
2. **Say what you would do and why before changing anything.** The first work
   is below, but check the reading against what is actually on screen.

**Define prescan.** Asked for in the last session and not built: a step after
Carrier configuration where the overview positions are defined. "Pre-scan" is
the working name, chosen so it would not be argued about yet.

Nothing beyond the name was specified. The shape that fits what is already
there is a second channel beside the canvas — like the carrier's — with the
chosen positions drawn on the plate, since the canvas is already the view and
a panel that is *about* the canvas belongs next to it rather than on a tab.
That is a guess. Ask before building it.

While you are in there, two things sitting under it are placeholders rather
than decisions, and prescan is the step that will care: the carrier is pinned
to the stage origin (top left), and the synthetic sample is still a 7×5 tile
grid unrelated to the carrier, so the scan area sits in the plate's corner
instead of inside a well.

## Where it is

- Clone: `C:\ProgramData\MinicondaZMB\home\t.de\ZMART-microscopy_main`
- Branch: `design/operator-page-prototype` on
  `github.com/thomdehoog/ZMART-microscopy` — **public repo**. The branch may
  run ahead of the remote — check
  `git log origin/design/operator-page-prototype..HEAD` rather than assuming,
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
npm run test:unit  # vitest, 63 tests, ~0.2 s
npm run test:ui    # playwright, 14 tests, ~60 s
python dev_window.py   # the page in a native pywebview window, still hot-reloading
```

CSS edits hot-swap and keep the run's state; a JS edit reloads the page and
resets it to step 1.

## What the page is

A left rail of workflow steps, a right side whose panels follow the step.
Ten steps in `target_acquisition`:

1 Microscope Configuration · 2 Optical Configuration · 3 Carrier configuration ·
4 Focus strategy · 5 Scan the overview · 6 Detect cells · 7 Select cells ·
8 Acquire and curate · 9 Save the run · 10 Disconnect

Two other workflows exist to prove the frame is not built around one:
`overview_only` (6 steps) and `focus_check` (6).

## Decisions already settled — do not relitigate without asking

**Frame**

- The rail is **navigation only**: number, title, one-line result. The number
  carries the state — grey ahead, **green done**, **blue where you are**, and
  blue wins on a step that is both. There is no tick; the badge said it twice.
- **Nothing advances by itself.** Finishing a step leaves you on it. The rail
  still gates order — only the next step is enabled.
- **A step's action sits at the end of what it operates.** There is no action
  bar. Steps with a tab panel get a foot at its bottom; the carrier's is inside
  its channel. The button carries `.step-run` wherever it lands, which is what
  the tests find it by. `ownButton: true` means "this panel builds its own"
  (Microscope Configuration does). Three steps have no button at all: Optical
  Configuration and Carrier configuration are settled by doing the work, and
  Microscope Configuration's lives in its form.
- **The canvas belongs to the steps that happen inside it** — Carrier
  configuration onward, and to no others. It is the microscope's own limits
  drawn to scale, so it exists from *reaching* that step, not from finishing it;
  nothing about the frame depends on what is mounted in it. Walk back to the
  session or the instrument and it is gone again: those steps are not about the
  stage, which makes this the same rule every other panel follows. Setting it up
  fixes the run's zero too, which is why no step asks for an origin; that
  happens behind the scenes and is deliberately not drawn. Later the limits come
  from the controller; today it is UI only.
- **Every step declares its own panel** — `connect`, `optics`, `carrier`,
  `focus`, … — rather than sharing one called Setup, so the tab beside the
  canvas says which of them it opens. The three setup panels draw into the same
  element because only one is ever shown.
- **A tab is always drawn, even alone**, because it names what is loaded —
  Microscope configuration, Optical configuration, Canvas. It said "Setup" for
  every step once, and then hiding it lost nothing.
- **The channel beside the canvas is headed, not tabbed.** "Carrier
  configuration" sits at the right end of the tab row, over the column it
  heads, styled exactly as a selected tab and permanently in that state —
  there is nothing to switch to.
- **A panel belongs to its step** and shows only while that step is selected.
  Walk back to Connect and the session and its checks are there again.
- Step **numbers are derived from position**, never typed.

**Setup panels**

- **Microscope Configuration** is a form headed "Connect to the microscope":
  microscope, API, password, and its own button. Opening the session runs six
  checks that land one at a time (reachable, credentials, API version, stage,
  objectives, storage). An open session is **not editable and cannot be
  reopened** — there is no Disconnect here. The run ends the session at its own
  step, and **Restart** is how you begin again. Nothing says "not connected"
  before it is; the fields and the button already do.
- **Optical Configuration** is a recorder, not a picker. Nothing is
  preconfigured. Pick a kind, name it, press Record; the controller reads the
  state back. The bar then *becomes* the record in place and a fresh open bar
  appears. Recording is the work, so a preset existing completes the step, and
  forgetting the last one undoes it.
  - Presets group by kind: `RECORDED ACQUISITION PRESETS`, `RECORDED AUTOFOCUS
    PRESETS`. The kind names the group, not every row.
  - A preset **unfolds** (triangle, leading the row) to show everything the
    controller returned.
  - Names are capitalised on the way in and clash case-insensitively.
  - Adding a kind is one entry in `SETTING_TYPES` — nothing else to touch.
- The panel's alignment is asserted by a test, not eyeballed: one width, one
  left and right edge, labels flush, every row opening and closing in the same
  column. The open bar carries the same fields a session does — one rule in
  the stylesheet serves both — so it stands taller than the line of text a
  recorded preset is, and its kind, name and Record are all one height.

- **Carrier configuration** is a full designer, not a dropdown: type, preset,
  rows/columns, area size, pitch and corner, each pair tieable. It has **no tab
  and no picture of its own** — it is what the canvas is drawing, so the
  controls dock in a channel to the right of the canvas and the carrier itself
  is drawn on the stage. One drawing, not two.
  - The channel is **not a menu for step 3**. The frame outlasts the step that
    set it: readable whenever the canvas is.
  - **No Apply button.** Configuring is the work, the way recording is in step
    2 — it always holds a valid carrier and every edit is already on the canvas.
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

- Which preset the scan uses and which the acquisition uses. The old
  survey/target pairing was dropped with the picker; nothing replaced it.
- **Where the carrier sits on the stage.** It is pinned to the origin — top
  left — which is a placeholder, not a decision. `STAGE_LIMITS_MM` (120 × 80)
  is a placeholder too, standing in for what the controller will report.
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
