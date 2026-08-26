# How this is put together

Five parts, each with one job. If you know which part your change belongs to,
you know which file to open.

```
webapp-ui/
  framework/        the engine. It knows how to run any workflow and none in particular.
    window/     what the operator sees: the rail, the chooser, the panels, run state.
    rules/      what the engine enforces: step ordering and readiness, and how
                workflow folders are found and named for the chooser.
  parts/        what a workflow is built from. A part knows nothing about any
                workflow: hand it what to do and it does it. The canvas is one.
  workflows/    what plugs into the engine. One folder per workflow, and the
                folder's name is the chooser's entry: `target_acquisition`
                appears as "Target acquisition".
    <name>/flow.js   the workflow's front door: its steps, in order, plus a
                     sentence for the chooser.
    <name>/steps/    one numbered folder per step — `1_connect/` to
                     `8_acquire_targets/` — each holding the step's declaration
                     and the widgets that belong to it alone.
    <name>/shared/   what several steps of that ONE workflow use: the carrier
                     geometry, the scan-field arithmetic, the layers the run
                     draws.
    target_acquisition/microscope/
                the seam where the instrument goes — mock today, real later —
                with the synthetic specimen the mock images in
                `pretend-sample/`. It lives in the workflow rather than the
                frame because the framework could just as well run an analysis
                workflow that never touches a microscope.
```

`workflows/README.md` walks through the arrangement in more detail.

## The rule that keeps it honest

**One owner per fact.** Sample geometry belongs to `pretend-sample/sample.js`;
nothing re-derives it. Peak rules belong to `pretend-sample/sweep.js`; nothing
else decides what
counts as too narrow. If a constant or a rule has to appear in two files, the
split was wrong — merge them back rather than keeping both in step.

## The seam: the `microscope/` folder

This is a mock now and gets a real microscope later, so nothing above this line
knows which it is talking to. A step never calls `setTimeout`, never reaches
for the synthetic sample, and never touches hardware — it calls the backend and
awaits. Every API call the page will ever make to an instrument lives behind
this seam; a workflow only imports it and calls.

```js
// microscope/mock.js today, microscope/live.js later — same shape
export const backend = {
  async connect(),
  async setOrigin(),
  async captureJob(kind),        // "overview" | "target"
  async measureFocus(points, { metric }),
  async scanOverview({ onTile }),
  async detect(settings),
  async acquire(cellIds, { onPair }),
};
```

Swapping the mock for a real driver should be a one-line change in
`window/main.js` and nothing else. If wiring the microscope means editing a
widget, the seam leaked and wants fixing first.

## Widgets

A widget owns one panel on the right and nothing else. It never imports another
widget, never reaches into the framework, and never advances the flow.

```js
export default {
  id: "focus",
  label: "Focus strategy",
  mount(host, ctx) {
    // build DOM inside host, once
    return {
      update(ctx) {},   // called whenever run state changes
      resize() {},      // called when the panel is shown or the window moves
    };
  },
};
```

`ctx` carries `{ state, actions, backend }`. Widgets read `state`, call
`actions` to change it, and the framework re-renders. That is the whole contract.

**The canvas is the base from step 3 on.** It is the microscope's own limits
drawn to scale, so it exists from *reaching* the carrier step, not from
finishing it. Before that there is no frame to draw and the step's own panel
holds the right-hand side alone — and walking back to one of those steps
returns to exactly that, because the session and the instrument are not on the
stage.

Every step declares the panel it wants — `connect`, `optics`, `focus`, … — and
it shows only while that step is selected, so walking back to Connect brings
the session and its checks with it. The canvas is no exception: it belongs to
the steps that happen inside it, which is why the tab set is a question about
the step being looked at rather than about how far the run has got. Planning
surfaces are not acquired data and get their own widgets.

A panel need not be a tab. Something that *is* the canvas rather than an
alternative to it takes the channel beside it instead: see the carrier below.

**The channel belongs to the step standing in it.** Three steps own one — the
carrier is what the canvas is drawing, the scan fields are what is being drawn
on it, the focus map is what the run knows about it — and all three dock into
the same column, with the heading saying whose it is. One column rather than
two, because a second would take width from the picture to show controls for a
step nobody is on. A step with no side widget gives the canvas the whole width.

Focus is the case that shows why this is worth insisting on. It used to be a
tab with a map of its own, its own camera and its own fit — which meant two
answers to where a well is, and the operator holding both. It now draws onto the
canvas with the canvas's projection and puts its controls in the channel. **If a
step is about the sample on the stage, it belongs on the canvas; a tab is for
something that is not the stage at all** (a scatter plot, a gallery, a form).

## Steps and workflows

A step is data. It says what it is called, why it is there, which modules it
wants on screen, what it still needs before it may run, and which piece of work
the page should carry out for it:

```js
{
  id: "focus",
  title: "Focus strategy",
  why: "Choose how this run keeps every image sharp across the sample.",
  btn: "Apply strategy",            // no btn means there is nothing to press
  panels: ["focus"],                // the modules this step wants beside it
  ms: 1400,                         // how long the rehearsal pretends it takes
  mode: "focus",                    // which behaviour main.js runs for it
  ready: (run) => null,             // null = go; a phrase = what is missing
}
```

Every field is written out in `workflows/README.md`. A step is declared in
its own folder, under the workflow that owns it — `steps/4_focus_strategy/step.js`
— and other workflows share it by importing it; the point is to mix and match,
not to retype. A workflow that wants a shared step to say something different
wraps it in `reworded()` (from `framework/rules/steps.js`), which changes the
wording and nothing else.

A workflow is a folder with a `flow.js` in it: the folder's name is the
chooser's entry, and the flow is the list of steps in order plus a blurb.
Numbering is derived from position, so reordering costs nothing; a step may set
its own `n` if two halves of one job should read as `3a` and `3b`.

**The folders under `workflows/` are the only place the workflows are
written down.** The framework finds every folder holding a `flow.js`
(`framework/rules/finding-workflows.js` says how), and the unit tests read the same
folders through the same assembly, which is what makes a test about a workflow
a test about the page. The browser suite checks the other half: it reads the
folders and then reads the running page, and fails if the chooser and the rail
disagree with them.

Readiness belongs to the step. Only the focus step knows what it is waiting
for, and `framework/rules/steps.js` only asks. That is what lets a new workflow be a list rather than another condition
added to the shell.

Which panels a step gets is `panelsFor` in `framework/rules/steps.js`. A step names the
modules it wants of its own and gets those; most name nothing, because most steps
happen on the stage and the picture of the stage is enough. The canvas itself
appears at the step that first asks for it — the carrier, in every workflow that
drives a microscope — and stays for the rest of the run, because from that point
on everything happens on a stage. A workflow where nothing asks for the canvas
never shows one (the canvas demonstration, since removed, was one).
Which modules a step wants is the step's business; how they are laid out is the
shell's.

Adding a workflow should mean writing one list that uses existing steps. If it
means editing the framework, the framework is missing something.

**Adding the canvas demonstration tested that claim, and at first it did not
hold.** Writing the workflow was indeed a list, but four things had to be added
before the operator could reach it. Three were real gaps in the shell and are now
filled; the other was a duplication, and it has since been taken out:

- the workflow had to be **declared twice**, once in the declaration file and
  once in `main.js`, because `main.js` carried its own copy. Fixed: the page
  assembles the workflows from the folders on disk, and the copy is gone. This was the first time anybody
  paid for that duplication, and it was worth recording because either half
  looked entirely convincing on its own — the tests went green against a list the
  page did not offer, and the page offered a list no test had ever seen.
- the step rules gave every step the canvas whether or not it asked, so a step
  wanting only its own module could not be written. `panels` above is the fix.
- a panel that builds a picture of its own — rather than drawing on one of the
  page's canvases — had no way to learn that it was on screen. `PANEL_META` now
  takes an optional `whenShown`, which is the general form of the `if (show ===
  …)` chain that was already there for the page's own panels.
- **every step held up every step after it.** That is right for a run, where each
  step produces something the next one needs, and wrong for a step that only
  shows the operator something: such a step produces nothing, so there is nothing
  to wait for, and there is nothing for the operator to do to finish it either —
  which left the demonstration's second step greyed out for ever. A step may now
  say `nothingWaitsOnThis`, and the step rules skip it when working out how far
  the run has got. Nothing in a real workflow says it, and a unit test keeps it
  that way.

None of those is about the canvas in particular. Each is something the shell
needed before *any* step could bring a module of its own, or before any two steps
could stand side by side without one gating the other.

## What the framework owns, and what it never gives away

The framework keeps: the run state, step ordering and reachability, the tab bar,
the action bar, and the mount lifecycle. Widgets and workflows only ever
*declare*.

This is deliberate, and it is the boundary to protect if workflows are ever
composed by an agent: something assembling a run from a registry of widgets and
a catalogue of steps cannot break the shell. Something emitting widget code
can.

## Where this stands, and what is deliberately not done yet

The layers above are the target. Some of them are built and used, some are
built and waiting, and one gap is a live hazard. Read this before assuming the
tree matches the picture.

In the table, `ta/` is short for `workflows/target_acquisition/`.

| part | state |
|---|---|
| `ta/shared/carriers.js` | built, unit-tested, **used by the app, the carrier widget and the scan-field grid** |
| `ta/shared/scanfields.js` | built, unit-tested, **used by the scan-area widget** |
| `ta/microscope/microscopes.js` | used by the app |
| `ta/microscope/pretend-sample/` | built, unit-tested, **not yet imported by the app** |
| `ta/microscope/mock.js` | built, **not yet imported by the app** |
| `framework/rules/steps.js` | built, unit-tested, **used by the app** — numbering, ordering, readiness and panels |
| `framework/rules/finding-workflows.js` | built, unit-tested, **used by the app: turns the workflow folders into the chooser's list** |
| `workflows/*/flow.js` | built, unit-tested, **used by the app: the only declaration of the workflows** |
| `ta/steps/2_define_carrier/widget.js` | built, used — the first widget, and the shape the rest should follow |
| `ta/steps/3_define_scan_area/widget.js` | built, used — the geometry editor and the grid, in the same channel |
| `ta/steps/5_scan_the_overview/overview.js` | built, used by the app when it is given a run to watch, and covered by the browser tests that photograph the canvas |
| `parts/canvas/` | built and covered by browser tests that photograph the picture — including which layers reached the screen — but **the operator page does not use it yet**: `viewer.js` is imported by its tests and by nothing else. See `CANVAS.md` and `docs/design/one-canvas-for-the-operator-page.md` |
| `framework/window/main.js` | the rest of the running app, and its own copies of the untaken modules |

**Widget extraction has started, from the outside in.** The carrier widget is
the first: it is handed a configuration and a callback and knows nothing about
run state. It lives beside its step in `steps/2_define_carrier/`, and its
geometry lives in `shared/carriers.js`, so nothing can disagree about where a
well is.

It also shows the second shape a widget can take. A panel is not always a tab:
the carrier is *what the canvas is drawing*, so its controls dock in a channel
beside the picture (`#canvas-side`) and it exports `drawOn(ctx, …)` to put the
carrier on the stage itself. Controls and drawing are in the one file because
they are one subject — change what a carrier is and a single place follows.

The channel belongs to whichever step owns it, and the scan-area widget is
the second to. It stops being editable once something has been **imaged**
against it — the overview scan — rather than once any later step has been done.
The focus map sits in between and does not depend on the plan: a fitted surface
is a statement about the plate, so walking back past it and moving a field is
safe. Tiles are different, because a tile does not know where it should have
been.

That is the general rule for a step that can be walked back to: **editable
while nothing has consumed its output, locked once something has.** There is
deliberately no held-and-applied edit, and no per-step accepted snapshot. Two
copies of the plan — the one on screen and the one the run would use — is the
one-owner rule broken in the way that fails silently, and the window where it
would help is empty anyway: before the scan there is no downstream answer to go
stale, and after it there is nothing left to change. Undo and redo cover
getting back to a previous state within a step, which is what actually gets
reached for.

One rule it establishes, which the next widget should keep: **a widget redraws
itself.** Asking the framework to rebuild the panel on every change destroys the
field being typed into — the defect this page has produced twice. `carrier.js`
writes new values into the controls that already exist and skips the focused
one.

The rest is still inline in `main.js` on purpose. While the UI is being
designed a single file is faster to iterate in, and boundaries drawn around a
moving design get redrawn. Take a panel out when it stops moving.

**The hazard used to be three facts defined twice, and two of them are closed.**
Surface fitting and the sweep-and-peak rules now have one owner each —
`microscope/pretend-sample/surface.js` and `sweep.js` — imported by the page and
read by the unit tests, so the arithmetic the trace draws is the arithmetic the
suite measures. The workflow declarations went the same way earlier: the folders
under `workflows/` are the only place the workflows are written down, and
the page assembles its list from them.

**One fact is still written twice: the synthetic sample.** The page rehearses
with a plan-driven sample (cells generated inside whatever tiles the scan fields
ask for) that lives in `window/main.js`; `pretend-sample/sample.js` is the older
block-shaped one, fed only to `mock.js` and its tests, and its header says so.
The two merge when the backend seam is wired for real — the sample belongs
behind the seam, and wiring it is the moment the page starts asking the backend
what it imaged.

What is left of that fix for the workflows is the runner. `main.js` still decides
what a step *does* from its `mode` — a switch that grows by one arm per kind of
work — where the intention is that a step carries its own `run(ctx)` and calls
the backend. Readiness has already moved that way and is a good model for it: the
rule now sits on the step, `framework/rules/steps.js` only asks, and adding a workflow
needs no change to the shell.

## The canvas: `parts/canvas/`

The scan step's own `overview.js` draws the overview inside that step, with Viv
wired in directly. The canvas is the next thing along and a different arrangement: one
viewer written more than once, once for each drawing engine worth considering,
every version behind the same small interface so that they can be compared and
swapped. It is not kept here — it lives at the top of the repository in
`viz_studio/options/`, with the interface written out in `contract.md` beside it
— and this folder is only the page's side of it.

It is a **part**, not the workflow's: it takes a list of layers and knows
nothing about what any of them mean. What target acquisition draws on it — the
carrier, the plan, the focus map, the stage mark — stays in the workflow, in
`shared/stage.js`.

```
parts/canvas/
  engines.js    which engines this page can open, and what each one is
  viewer.js     opening one on a run, changing engine, and the layer buttons
  layers-above.js   the stack drawn over the picture, faded and cut through
  panel.js      the canvas as a panel a workflow declares, and its markup
```

The two gestures are not in this list, and that is deliberate. Dragging and the
wheel used to be arranged by this page, on the box the picture sits in. They now
come with the canvas: every engine attaches the same shared piece of code for
them when it opens. This page therefore does nothing about them at all, which is
what you want — if each engine had interpreted a drag for itself, a difference in
how two of them felt might have been the engine or might have been somebody's
idea of how far a wheel notch should zoom, with no way to tell which.

Two rules hold this together and both are load-bearing.

**The canvas is never told which step it is in.** It is handed a run to draw
and, when the page wants them, two functions to draw with — one for beneath the
picture and one for above it. It learns nothing else. A picture that has taken
on the shape of one workflow cannot be moved into the next one without being
taken apart again, and being movable is the whole reason it was built behind an
interface. If wiring it into a future step seems to want a piece of run state
passed in, the interface is where the answer belongs.

**Everything about how a picture is drawn stays behind that interface.** Nothing
in this page imports Viv or deck.gl on the canvas's behalf; it calls
`openViewer` and drives the handle that comes back. That is what makes a
difference between two engines a difference in the engines, rather than a
difference in how somebody happened to wire one of them up.

Reaching across to `viz_studio/options/` costs a few settings in
`vite.config.js`, and all of them are explained there.

**One engine changes what the build produces.** Neuroglancer, the third of the
three, hands the fetching and unpacking of image pieces to background programs,
and a browser will only start one of those from a file of its own. So the build
is no longer one file: it is `index.html` with everything else folded into it,
and those two programs beside it. That was accepted after the alternative was
tried and measured; `README.md` records what was tried, `neuroglancer-workers.mjs`
compiles the two programs, and `vite.config.js` places them.

It has one consequence that reaches into this folder. A page opened straight off
the disk rather than served over HTTP has no address of its own, and a browser
will not start a background program for it — so neuroglancer cannot draw there
however well it was built. `engines.js` therefore has two lists: what the page
was built with, and what it can actually open where it is now. Only the second is
put in front of an operator. A button that draws nothing would be the worst of
the available behaviours, because an empty box looks exactly like one that is
still loading.

## Acquired data: the scan step's `overview.js`

Everything else on this page is a rehearsal — a synthetic sample, a stage that
moves on a timer. `steps/5_scan_the_overview/overview.js` is not: given the
address of a run, it draws
the OME-Zarr images the microscope is writing, and reads them again as tiles
land, so the scan step shows the overview appearing rather than a count.

It is drawn by Viv's layers on deck.gl, deliberately not by Viv's ready-made
React viewers: those own the whole drawing surface and the whole layout, which is
the opposite of what a panel inside this page can allow. Several acquisitions can
be drawn at once — a survey underneath, the target scan over it — which is the
shape the writer already produces, one image per acquisition type.

Two properties of it are worth knowing before changing anything, and both are
written out at length in the file:

- **Nothing on disk announces a saved tile.** The images are declared at their
  full size before any of them exists, so their description never changes. The
  picture is told by the scan step, and it re-reads the run rather than waiting
  to be notified.
- **Viv draws an unimaged part of the canvas as solid black**, not as nothing.
  A shader extension in the same file makes the dark parts see-through, which is
  what allows an acquisition to be a layer over anything else.

## Tests

- `tests/unit/**` — vitest, on the pure modules only. Fast, no browser. This is where
  behaviour that can be stated as a number belongs.
- `tests/*.spec.js` — Playwright, driving the real page. A smoke net, not a
  specification: the page is nearly all canvas, and driving it has repeatedly
  caught what reading the source did not.

The Playwright tests need a Chromium and will not run without one. On the
containers this project is developed in it sits at `/opt/pw-browsers/chromium`,
and `playwright.config.js` honours `PLAYWRIGHT_CHROMIUM`, so the browser suite
is run as `PLAYWRIGHT_CHROMIUM=/opt/pw-browsers/chromium npm run test:ui`.
Playwright fails rather than skipping when it cannot find a browser, which is
the behaviour to want: a suite that quietly skips the tests which look at
pixels and then reports success is worse than no suite at all.

Prototyping pace: keep the browser suite small and the unit suite sharp.
