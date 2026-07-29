# Handoff — ZMART operator page prototype

Paste the section below into a fresh session. It is written to be
self-contained: nothing in it depends on the conversation that produced the
prototype.

---

Continue work on the ZMART operator-page prototype. It is a **mock** — a real
microscope gets wired in later — so it should work well and be easy to change,
not be correct about physics.

## Where it is

- Clone: `C:\ProgramData\MinicondaZMB\home\t.de\ZMART-microscopy_main`
- Branch: `design/operator-page-prototype`, pushed to
  `github.com/thomdehoog/ZMART-microscopy` — **public repo**
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
E="C:/ProgramData/MinicondaZMB/envs/zmart-microscopy"
export PATH="$E:$PATH"
export PLAYWRIGHT_BROWSERS_PATH="C:\ProgramData\MinicondaZMB\home\t.de\ms-playwright"
cd workflows/target_acquisition/webapp-ui

npm run dev        # http://127.0.0.1:5174 — hot reload
npm run build      # one self-contained file -> ../workflow/webapp/static/
npm run test:unit  # vitest, ~0.2 s
npm run test:ui    # playwright, ~60 s
python dev_window.py   # the page in a native pywebview window, still hot-reloading
```

CSS edits hot-swap and keep the run's state; a JS edit reloads the page and
resets it to step 1.

## What the page is

A left rail of workflow steps, a right side whose panels follow the step.
Ten steps in `target_acquisition`:

1 Connect · 2 Optical Configuration · 3 Carrier configuration ·
4 Focus strategy · 5 Scan the overview · 6 Detect cells · 7 Select cells ·
8 Acquire and curate · 9 Save the run · 10 Disconnect

Two other workflows exist to prove the frame is not built around one:
`overview_only` (6 steps) and `focus_check` (6).

## Decisions already settled — do not relitigate without asking

**Frame**

- The rail is **navigation only**: number, title, ✓, one-line result.
- **Nothing advances by itself.** Finishing a step leaves you on it. The rail
  still gates order — only the next step is enabled.
- The **run button lives with the widget it operates**, in an action bar above
  the panel. A step that carries its own button (`ownButton: true`) hides the
  action bar entirely — Connect and Optical Configuration do.
- **The canvas arrives at step 3 and never leaves.** It is the microscope's
  own limits drawn to scale, so it exists from *reaching* Carrier configuration,
  not from finishing it — nothing about the frame depends on what is mounted in
  it. Setting it up fixes the run's zero too, which is why no step asks for an
  origin; that happens behind the scenes and is deliberately not drawn. Later
  the limits come from the controller; today it is UI only.
- **Every step declares its own panel** — `connect`, `optics`, `carrier`,
  `focus`, … — rather than sharing one called Setup, so the tab beside the
  canvas says which of them it opens. The three setup panels draw into the same
  element because only one is ever shown.
- **One tab is not a choice, so it is not drawn.** Steps 1 and 2 have no tab bar
  at all. The canvas keeps its tab even alone, because it never goes away.
- **A panel belongs to its step** and shows only while that step is selected.
  Walk back to Connect and the session and its checks are there again.
- Step **numbers are derived from position**, never typed.

**Setup panels**

- **Connect** is a form: microscope, API, password, and its own button. Opening
  the session runs six checks that land one at a time (reachable, credentials,
  API version, stage, objectives, storage). An open session is not editable; a
  red **Disconnect** hands the fields back and **clears the run**, keeping only
  the credentials — everything else was read off that microscope.
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
    set it: readable whenever the canvas is, editable until applied.
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
  needed saying.

## The state of the code — the important caveat

`src/main.js` is **2,600 lines and runs the whole app**. Beside it are modules
that are tested but **not all of them are used**:

| part | state |
|---|---|
| `lib/surface.js`, `lib/sweep.js`, `lib/rng.js` | tested; **main.js has its own copies** |
| `lib/sample.js`, `lib/microscopes.js` | `microscopes.js` is used; `sample.js` is not |
| `frame/steps.js` | tested; only `numbered()` is used |
| `backend/mock.js`, `workflows/` | tested; **not used at all** |
| `widgets/` | does not exist yet |

So **surface fitting, the sweep, the sample and the workflow declarations are
each defined twice**. `main.js` is what runs; the modules are what the unit
tests cover — the suite can stay green while the app drifts. **If you change a
rule, change it in both**, or do the de-duplication first: have `main.js`
import them and drop its `mode` switch in favour of `step.run(ctx)`. That is
contained and touches no UI code.

Widget extraction is deliberately deferred while the UI is still being
designed. Do it when a new widget appears or two people work on the page at
once.

## Open questions — ask, do not invent

- Which preset the scan uses and which the acquisition uses. The old
  survey/target pairing was dropped with the picker; nothing replaced it.
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
