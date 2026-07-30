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

Adding a workflow should mean writing one file that imports existing steps.
If it means editing the frame, the frame is missing something.

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

Prototyping pace: keep the browser suite small and the unit suite sharp.
