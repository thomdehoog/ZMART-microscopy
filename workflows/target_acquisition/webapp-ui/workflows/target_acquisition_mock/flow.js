/**
 * Target acquisition mock — the whole chain, with no hardware at the end.
 *
 * The same steps as the prototype, but nothing is rehearsed in the browser:
 * the window speaks HTTP to the bridge, the bridge speaks to the zmart
 * controller, and the controller drives its mock driver. Every seam the real
 * instrument will cross is crossed here, which is what makes this the right
 * place to test the plumbing before a stage is anywhere near it.
 *
 * The bridge has to be running (`bridge.py` — the launcher starts it); the
 * driver it connects for this workflow is the controller's own mock.
 */

import { steps as theRun } from "../target_acquisition/the-run.js";

export const blurb =
  "The whole chain — bridge, controller, driver — ending at the controller's "
  + "mock driver instead of an instrument. Where the plumbing is tested.";

/** The live backend, pointed at the controller's mock driver. */
export const backend = { kind: "live", instrument: "mock" };

export const steps = theRun;
