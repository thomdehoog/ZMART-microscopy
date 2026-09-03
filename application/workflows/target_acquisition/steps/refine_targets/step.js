/**
 * Step 7 — Refine Targets.
 *
 * Refinement is the same shape as discovery: the refined targets light up on
 * the canvas, and the channel holds the scatter they are gated on.
 */

export const selectCells = {
  id: "select",
  title: "Refine Targets",
  why: "Gate the targets worth imaging — draw on the plot — then restrict them to so many per tileset.",
  btn: "Restrict",
  panels: [],
  ms: 600,
  mode: "select",
  ready: ({ gated }) => (gated.size ? null : "nothing gated yet"),
};
