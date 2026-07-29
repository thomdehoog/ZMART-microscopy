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

**The canvas is permanent** and holds acquired data only. Every other widget
belongs to the step that declared it and is only mounted while that step is
selected. Planning surfaces — choosing a focus strategy, tuning detection —
are not acquired data and get their own widgets.

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

## Tests

- `tests/unit/**` — vitest, on `lib/` only. Fast, no browser. This is where
  behaviour that can be stated as a number belongs.
- `tests/*.spec.js` — Playwright, driving the real page. A smoke net, not a
  specification: the page is nearly all canvas, and driving it has repeatedly
  caught what reading the source did not.

Prototyping pace: keep the browser suite small and the unit suite sharp.
