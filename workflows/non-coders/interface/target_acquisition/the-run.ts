/**
 * The target-acquisition run: its steps, in order.
 *
 * This folder is the code home — the steps in their numbered folders, the
 * shared canvas and geometry, the microscope seam — and this file is the run
 * they compose into; `flow.ts` beside it is the workflow's front door. What
 * the run drives — the controller's mock driver or the Leica — is chosen on
 * the Connect step, so there is one workflow and one list of steps.
 */

import { connect } from "./steps/connect/step.ts";
import { carrierConfiguration } from "./steps/define_carrier/step.ts";
import { initialScanfields } from "./steps/define_scan_area/step.ts";
import { focusStrategy } from "./steps/focus_strategy/step.ts";
import { scanOverview } from "./steps/scan_the_overview/step.ts";
import { detectCells } from "./steps/discover_targets/step.ts";
import { selectCells } from "./steps/refine_targets/step.ts";
import { targetScanArea } from "./steps/target_scan_area/step.ts";
import { acquireAndCurate } from "./steps/acquire_targets/step.ts";
import { runProtocolStep } from "./steps/run_protocol/step.ts";
import type { TaStep } from "./types.ts";

export const steps: TaStep[] = [
  connect,
  carrierConfiguration,
  initialScanfields,
  focusStrategy,
  scanOverview,
  detectCells,
  selectCells,
  targetScanArea,
  acquireAndCurate,
  runProtocolStep,
];
