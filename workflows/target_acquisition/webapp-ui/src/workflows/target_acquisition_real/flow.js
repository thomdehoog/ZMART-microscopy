/**
 * Target acquisition real — the instrument itself.
 *
 * The same steps and the same chain as the mock, ending at the Leica driver:
 * real LAS X, or its simulator — the driver speaks to either without knowing
 * which. This workflow is here from the start so the chooser tells the truth
 * about where the work is going; until the Leica is reachable from the
 * machine the bridge runs on, connecting fails with the bridge's own sentence
 * saying so, which is the honest state of a run that needs an instrument.
 */

import { steps as theRun } from "../target_acquisition/the-run.js";

export const blurb =
  "The instrument itself: bridge, controller, and the Leica driver — real "
  + "LAS X or its simulator. Needs the microscope reachable.";

/** The live backend, pointed at the Leica driver. */
export const backend = { kind: "live", instrument: "leica" };

export const steps = theRun;
