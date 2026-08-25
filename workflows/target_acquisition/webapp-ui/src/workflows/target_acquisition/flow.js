/**
 * Target acquisition — the flow.
 *
 * A flow is the ordered list of a workflow's steps, and this file is all a
 * workflow has to say about itself: which steps, in which order, plus one
 * sentence for the chooser. Each step lives in its own numbered folder under
 * `steps/`, beside the controls that belong to it, so the folder listing reads
 * the way the rail down the left of the window does.
 *
 * The name in the chooser is this folder's name with the underscores read as
 * spaces — `target_acquisition` becomes "Target acquisition". The frame finds
 * every folder in `src/workflows/` that has a `flow.js` and offers it, so
 * adding a workflow means adding a folder, and nothing else has to change.
 */

import { connect } from "./steps/1_connect/step.js";
import { carrierConfiguration } from "./steps/2_define_carrier/step.js";
import { initialScanfields } from "./steps/3_define_scan_area/step.js";
import { focusStrategy } from "./steps/4_focus_strategy/step.js";
import { scanOverview } from "./steps/5_scan_the_overview/step.js";
import { detectCells } from "./steps/6_discover_targets/step.js";
import { selectCells } from "./steps/7_refine_targets/step.js";
import { acquireAndCurate } from "./steps/8_acquire_targets/step.js";

/** The sentence the chooser shows when the pointer rests on this workflow. */
export const blurb = "overview, discover, refine, acquire";

/** Which workflow a freshly opened page starts on: this one. */
export const opensFirst = true;

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
