# How this is put together

Five parts, each with one job. If you know which part your change belongs to,
you know which file to open.

```
src/
  lib/          pure functions. No DOM, no state. Unit-tested.
  backend/      the seam where the microscope goes. Mock today, real later.
  frame/        the shell: rail, action bar, tabs, run state, step ordering.
  widgets/      the panels on the right. One file each.
  workflows/    step lists. Compose, do not invent.
  live/         acquired data drawn from the run's own images, as it is written.
  canvas/       the picture of a run, drawn by whichever engine is chosen.
```

## The rule that keeps it honest

**One owner per fact.** Sample geometry belongs to `lib/sample.js`; nothing
re-derives it. Peak rules belong to `lib/sweep.js`; nothing else decides what
counts as too narrow. If a constant or a rule has to appear in two files, the
split was wrong — merge them back rather than keeping both in step.

## The seam: `backend/`

This is a mock now and gets a real microscope later, so nothing above this line
knows which it is talking to. A step never calls `setTimeout`, never reaches
for the synthetic sample, and never touches hardware — it calls the backend and
awaits.

```js
// backend/mock.js today, backend/live.js later — same shape
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
`main.js` and nothing else. If wiring the microscope means editing a widget,
the seam leaked and wants fixing first.

## Widgets

A widget owns one panel on the right and nothing else. It never imports another
widget, never reaches into the frame, and never advances the flow.

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
`actions` to change it, and the frame re-renders. That is the whole contract.

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

**The channel belongs to the step standing in it.** Two steps own one — the
carrier is what the canvas is drawing, the scan fields are what is being drawn
on it — and both dock into the same column, with the heading saying whose it
is. One column rather than two, because a second would take width from the
picture to show controls for a step nobody is on. A step with no side widget
gives the canvas the whole width.

## Steps and workflows

A step is data plus one function:

```js
{
  id: "focus",
  title: "Focus strategy",
  why: "Choose how this run keeps every image sharp across the sample.",
  button: "Apply strategy",
  widget: "focus",                  // a key in the widget registry, or null
  ready: (state) => null,           // null = go; a string = why not
  run: async (ctx) => { … },        // calls ctx.backend, never hardware
}
```

A workflow is a name and a list of those. Steps live in `workflows/steps.js`
so several workflows can share them — the point is to mix and match, not to
retype. Numbering is derived from position; only sub-steps like `3a` carry an
explicit `n`.

A step may also say which modules it wants on screen, with `panels`. Most say
nothing and get the canvas, which is right because most steps happen on the
stage. A step that says `panels: ["viewer"]` gets exactly that and nothing
beside it — see the viewer step, whose whole content is a picture to look at.
That is the rule `WORKFLOW_SHELL.md` sets out: which modules a step wants is the
step's business, and how they are laid out is the shell's.

Adding a workflow should mean writing one file that imports existing steps.
If it means editing the frame, the frame is missing something.

**Adding the viewer workflow tested that claim, and it did not hold.** Writing
the workflow was indeed a list, but three things had to be added before the
operator could reach it, and all three are worth knowing about:

- the workflow had to be **declared twice**, once in `workflows/index.js` and
  once in `main.js`, because `main.js` still carries its own copy. That is the
  hazard already named at the end of this file, met in practice.
- `frame/steps.js` gave every step the canvas whether or not it asked, so a step
  wanting only its own module could not be written. `panels` above is the fix.
- a panel that builds a picture of its own — rather than drawing on one of the
  page's canvases — had no way to learn that it was on screen. `PANEL_META` now
  takes an optional `whenShown`, which is the general form of the `if (show ===
  …)` chain that was already there for the page's own panels.

None of those is about the viewer in particular. Each is something the shell
needed before *any* step could bring a module of its own, which is what
`WORKFLOW_SHELL.md` says steps are supposed to be able to do.

## What the frame owns, and what it never gives away

The frame keeps: the run state, step ordering and reachability, the tab bar,
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

| part | state |
|---|---|
| `lib/carriers.js` | built, unit-tested, **used by the app, `widgets/carrier.js` and the scan-field grid** |
| `lib/scanfields.js` | built, unit-tested, **used by `widgets/scanfields.js`** |
| `lib/microscopes.js` | used by the app |
| `lib/surface.js`, `sweep.js`, `sample.js`, `rng.js` | built, unit-tested, **not yet imported by the app** |
| `backend/mock.js` | built, **not yet imported by the app** |
| `frame/steps.js` | built, unit-tested; only `numbered()` is used |
| `workflows/` | built, unit-tested, **not yet imported and now stale** |
| `widgets/carrier.js` | built, used — the first widget, and the shape the rest should follow |
| `widgets/scanfields.js` | built, used — the geometry editor and the grid, in the same channel |
| `live/overview.js` | built, used by the app when it is given a run to watch, and covered by the browser tests that photograph the canvas |
| `canvas/` | built, used by the viewer workflow, and covered by browser tests that photograph the picture |
| `src/main.js` | the rest of the running app, and its own copies of the untaken modules |

**Widget extraction has started, from the outside in.** `widgets/carrier.js` is
the first: it is handed a configuration and a callback and knows nothing about
run state. Its geometry lives in `lib/carriers.js`, so nothing can disagree
about where a well is.

It also shows the second shape a widget can take. A panel is not always a tab:
the carrier is *what the canvas is drawing*, so its controls dock in a channel
beside the picture (`#canvas-side`) and it exports `drawOn(ctx, …)` to put the
carrier on the stage itself. Controls and drawing are in the one file because
they are one subject — change what a carrier is and a single place follows.

The channel belongs to whichever step owns it, and `widgets/scanfields.js` is
the second to. It stops being editable once something later has been done —
positions placed against areas that must not move out from under them.

One rule it establishes, which the next widget should keep: **a widget redraws
itself.** Asking the frame to rebuild the panel on every change destroys the
field being typed into — the defect this page has produced twice. `carrier.js`
writes new values into the controls that already exist and skips the focused
one.

The rest is still inline in `main.js` on purpose. While the UI is being
designed a single file is faster to iterate in, and boundaries drawn around a
moving design get redrawn. Take a panel out when it stops moving.

**The hazard: four facts are currently defined twice.** Surface fitting, the
sweep and peak rules, the synthetic sample, and the workflow declarations all
exist both inline in `main.js` and in the modules beside it. `main.js` is what
runs; the modules are what the tests cover. Change a rule in one and the other
disagrees in silence — the unit suite stays green while the app misbehaves.

The fix is small and does not touch the UI: `main.js` imports the maths, the
sample and the workflows instead of carrying copies, and its runner drops the
mode switch in favour of calling `step.run(ctx)`. Every line worth editing
while iterating on design stays where it is. Until that is done, **treat
`main.js` as the source of truth and the modules as a proposal** — and if you
change a rule, change it in both.

Adding the viewer workflow has now cost that twice over, which is worth
recording because it is the first time somebody has paid it. The workflow is
declared in `workflows/index.js`, where the unit tests can read it, *and* in
`main.js`, which is what an operator actually sees. Either one alone looks
entirely convincing: the tests go green against a workflow the page does not
offer, and the page offers a workflow no test has ever seen. Whoever takes the
duplication out should start here.

## The canvas: `canvas/`

`live/overview.js` draws the overview inside the scan step, with Viv wired in
directly. The canvas is the next thing along and a different arrangement: one
viewer written more than once, once for each drawing engine worth considering,
every version behind the same small interface so that they can be compared and
swapped. It is not kept here — it lives at the top of the repository in
`viz_studio/options/`, with the interface written out in `contract.md` beside it
— and this folder is only the page's side of it.

```
canvas/
  engines.js    which engines this page can open, and what each one is
  panel.js      opening one on a run, the two gestures, and changing engine
```

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

Reaching across to `viz_studio/options/` costs two settings in `vite.config.js`,
and both are explained there.

## Acquired data: `live/`

Everything else on this page is a rehearsal — a synthetic sample, a stage that
moves on a timer. `live/overview.js` is not: given the address of a run, it draws
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

- `tests/unit/**` — vitest, on `lib/` only. Fast, no browser. This is where
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
