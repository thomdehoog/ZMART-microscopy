/**
 * Step 6 — Discover Targets.
 *
 * Discovery brings no panel of its own: the targets it finds land on the
 * canvas, and its controls sit in the channel beside it, the same shape as
 * focus.
 */

export const detectCells = {
  id: "detect",
  title: "Discover Targets",
  why: "Segments every overview tile. Each cell found becomes one target candidate.",
  btn: "Discover Targets",
  panels: [],
  ms: 1600,
  mode: "detect",
  /* Settings are tried on a single tile first, because running them over every
     tile and then finding they were wrong is a long way to go for an answer. */
  ready: ({ detect }) => (detect.tested ? null : "try it on one tile first"),
};
