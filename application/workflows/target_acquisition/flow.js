/**
 * Target acquisition — the one workflow this page runs.
 *
 * The steps are the list in `./the-run.js`. What the run drives is chosen on
 * the Connect step, not here: the operator picks the microscope — the
 * controller's mock driver, which answers with made-up data through the
 * whole real chain, or the Leica through Navigator Expert — and the page
 * speaks to the controller through the bridge either way.
 */

import { canvasPanel } from "../../parts/canvas/panel.js";
import { steps as theRun } from "./the-run.js";

export const blurb =
  "Find the targets on an overview and acquire them, on the microscope chosen "
  + "at Connect — the controller's mock driver or the Leica.";

export const opensFirst = true;

export const steps = theRun;

/**
 * The panels this workflow offers, and what each one is made of.
 *
 * A step asks for a panel by its key; the framework builds an element for each
 * of these and lets the panel fill it. The canvas is here because it is this
 * workflow's: a run that drives a microscope is looked at on a picture of the
 * stage, and a workflow that is not would declare something else, or nothing.
 */
export const panels = [canvasPanel];
