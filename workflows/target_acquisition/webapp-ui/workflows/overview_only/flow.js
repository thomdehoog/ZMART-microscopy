/**
 * Overview only — the flow.
 *
 * The shortest real run: set up, scan the whole area, save the map. It is
 * built almost entirely from target acquisition's steps — the same session,
 * the same carrier, the same scan — which is the point of steps being shared:
 * a workflow is a list, not a rewrite. Only the closing step is its own, in
 * `steps/5_save_the_run/`, and even that is borrowed by the focus-surface
 * check next door.
 */

import { reworded } from "../../frame/rules/steps.js";
import { setUpTheRun } from "../target_acquisition/the-run.js";
import { scanOverview } from "../target_acquisition/steps/5_scan_the_overview/step.js";
import { saveRun } from "./steps/5_save_the_run/step.js";

export const blurb = "no analysis panel";

export const steps = [
  ...setUpTheRun,
  reworded(scanOverview, {
    why: "Drives the stage through every position and stitches the map.",
  }),
  reworded(saveRun, {
    why: "Writes the stitched map and its report to the run folder.",
    note: "map + report written",
  }),
];
