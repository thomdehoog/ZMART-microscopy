/**
 * The target-acquisition run: its steps, in order.
 *
 * This folder is the code home — the steps in their numbered folders, the
 * shared canvas and geometry, the microscope seam — and this file is the run
 * they compose into; `flow.js` beside it is the workflow's front door. What
 * the run drives — the controller's mock driver or the Leica — is chosen on
 * the Connect step, so there is one workflow and one list of steps.
 */

import { connect } from "./steps/1_connect/step.js";
import { carrierConfiguration } from "./steps/2_define_carrier/step.js";
import { initialScanfields } from "./steps/3_define_scan_area/step.js";
import { focusStrategy } from "./steps/4_focus_strategy/step.js";
import { scanOverview } from "./steps/5_scan_the_overview/step.js";
import { detectCells } from "./steps/6_discover_targets/step.js";
import { selectCells } from "./steps/7_refine_targets/step.js";
import { acquireAndCurate } from "./steps/8_acquire_targets/step.js";

/* Every run that drives the microscope starts the same way: open the session,
   say what the sample is mounted in, and say where on it to look. Written once
   here so the workflows that share these steps cannot drift apart — the
   overview-only and focus-check flows import this list rather than retyping
   it. */
export const setUpTheRun = [
  connect,
  carrierConfiguration,
  initialScanfields,
];

export const steps = [
  ...setUpTheRun,
  focusStrategy,
  scanOverview,
  detectCells,
  selectCells,
  acquireAndCurate,
];
