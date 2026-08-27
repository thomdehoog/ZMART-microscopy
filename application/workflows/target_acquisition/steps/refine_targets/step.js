/**
 * Step 7 — Refine Targets.
 *
 * Refinement is the same shape as discovery: the refined targets light up on
 * the canvas, and the channel holds the scatter they are gated on.
 */

export const selectCells = {
  id: "select",
  title: "Refine Targets",
  why: "Gate the targets worth imaging — drag a box on the plot, or pick them on the canvas.",
  btn: "Confirm selection",
  panels: [],
  ms: 600,
  mode: "select",
  ready: ({ gated }) => (gated.size ? null : "nothing gated yet"),
};
