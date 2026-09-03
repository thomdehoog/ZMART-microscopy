/**
 * Step 6 — Detect objects.
 *
 * Discovery brings no panel of its own: the targets it finds land on the
 * canvas, and its controls sit in the channel beside it, the same shape as
 * focus.
 */

export const detectCells = {
  id: "detect",
  title: "Detect objects",
  why: "Segments every overview tile. Each cell found becomes one target candidate.",
  btn: "Segment all",
  panels: [],
  ms: 1600,
  mode: "detect",
  /* Trying settings on one tile first is offered, never demanded: the
     operator decides when the settings are worth the whole sample, and a
     press that refused until a test had been staged was a step doing the
     deciding for them. */
  ready: () => null,
};
