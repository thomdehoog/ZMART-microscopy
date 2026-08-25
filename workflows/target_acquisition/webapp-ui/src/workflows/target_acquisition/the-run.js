/**
 * The target-acquisition run: its steps, in order.
 *
 * This folder is the code home — the steps in their numbered folders, the
 * shared canvas and geometry, the microscope seam — and this file is the run
 * they compose into. It is deliberately NOT a workflow of its own (no
 * `flow.js` lives here), because the run is offered three ways, one folder
 * each beside this one:
 *
 *   target_acquisition_prototype/  the front end alone — everything rehearsed
 *   target_acquisition_mock/       through the bridge to the controller's
 *                                  mock driver — the whole chain, no hardware
 *   target_acquisition_real/       the same chain to the Leica driver — the
 *                                  instrument itself, or its simulator
 *
 * The three differ only in the backend their `flow.js` declares; the steps
 * below are the one list all of them walk.
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
