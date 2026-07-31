/**
 * The workflows on offer.
 *
 * Each is a name and a list of steps from the catalogue. That is the whole
 * file — no logic, no special cases. Adding one means importing the steps you
 * want in the order you want them; if it means editing the frame, the frame
 * is missing something and that is the bug.
 */

import { numbered } from "../frame/steps.js";
import {
  connect, setOrigin, captureOverviewJob, captureTargetJob, focusStrategy,
  scanOverview, detectCells, selectCells, acquireAndCurate, saveRun, disconnect,
  lookAtTheRun, reworded,
} from "./steps.js";

const workflow = (name, blurb, steps) => ({ name, blurb, steps: numbered(steps) });

export const WORKFLOWS = {
  target_acquisition: workflow(
    "Target acquisition",
    "overview, detect, select, acquire",
    [
      connect,
      setOrigin,
      { ...captureOverviewJob, n: "3a" },
      { ...captureTargetJob, n: "3b" },
      focusStrategy,
      scanOverview,
      detectCells,
      selectCells,
      acquireAndCurate,
      saveRun,
      disconnect,
    ],
  ),

  overview_only: workflow(
    "Overview only",
    "no detection, no selection",
    [
      connect,
      setOrigin,
      captureOverviewJob,
      scanOverview,
      saveRun,
      disconnect,
    ],
  ),

  focus_check: workflow(
    "Focus surface check",
    "calibration run",
    [
      connect,
      setOrigin,
      reworded(focusStrategy, { why: "Choose how the surface is measured, then run it." }),
      reworded(saveRun, {
        title: "Write the surface",
        why: "Records the fitted surface and its residual for this objective.",
        button: "Write surface",
      }),
      disconnect,
    ],
  ),

  /* One step and nothing else, so that the canvas can be tried inside the real
     operator window before it is put to work in any run. Deliberately not part
     of target acquisition: mixing it into a workflow that drives a microscope
     would mean every question about the picture became a question about the
     acquisition around it. */
  viewer_only: workflow(
    "Viewer on its own",
    "the canvas and nothing else, for trying it out",
    [lookAtTheRun],
  ),
};

export const DEFAULT_WORKFLOW = "target_acquisition";
