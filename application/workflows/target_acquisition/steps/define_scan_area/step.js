/**
 * Step 3 — Overview scan area.
 *
 * The preset the overview is taken with is recorded here, not in a step of
 * its own: the fields take their frame from it, so it is tested where it
 * matters.
 *
 * The geometry editor and the grid this step docks beside the canvas live in
 * `widget.js`, in this same folder; the arithmetic of the plan itself — how a
 * drawn region becomes a grid of frames — lives in `../../shared/scanfields.js`,
 * where later steps that consume the plan can read the same answer.
 */

export const initialScanfields = {
  id: "scanfields",
  title: "Overview scan area",
  why: "Record the preset the overview is taken with, then say where on the carrier it is taken.",
  panels: [],
  mode: "scanfields",
};
