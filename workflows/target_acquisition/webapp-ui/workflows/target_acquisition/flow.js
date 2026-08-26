/**
 * Target acquisition — the one workflow this page runs.
 *
 * The steps are the list in `./the-run.js`. What the run drives is chosen on
 * the Connect step, not here: the operator picks the microscope — the
 * controller's mock driver, which answers with made-up data through the
 * whole real chain, or the Leica through Navigator Expert — and the page
 * speaks to the controller through the bridge either way.
 */

import { steps as theRun } from "./the-run.js";

export const blurb =
  "Find the targets on an overview and acquire them, on the microscope chosen "
  + "at Connect — the controller's mock driver or the Leica.";

export const opensFirst = true;

export const steps = theRun;
