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

## Tests

- `tests/unit/**` — vitest, on `lib/` only. Fast, no browser. This is where
  behaviour that can be stated as a number belongs.
- `tests/*.spec.js` — Playwright, driving the real page. A smoke net, not a
  specification: the page is nearly all canvas, and driving it has repeatedly
  caught what reading the source did not.

Prototyping pace: keep the browser suite small and the unit suite sharp.
