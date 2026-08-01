/**
 * The workflows on offer.
 *
 * Each is a name, a short blurb for the chooser at the top left, and a list of
 * steps from the catalogue. That is the whole file — no logic, no special
 * cases. Adding one means importing the steps you want in the order you want
 * them; if it means editing the frame, the frame is missing something and that
 * is the bug.
 *
 * This is the only place the workflows are written down. The page imports it and
 * so do the unit tests, so a workflow that appears here is a workflow the
 * operator can choose and a workflow the tests can see. It used to be written
 * twice — here and again inside `main.js` — and the two drifted apart without
 * anything going red, which is the reason the note above matters.
 */

import { numbered } from "../frame/steps.js";
import {
  connect, opticalConfiguration, carrierConfiguration, initialScanfields,
  focusStrategy, scanOverview, detectCells, selectCells, acquireAndCurate,
  saveRun, disconnect, lookAtTheRun, reworded,
} from "./steps.js";

const workflow = (name, blurb, steps) => ({ name, blurb, steps: numbered(steps) });

/* Every run that drives the microscope starts the same way: open the session,
   record what the optics are set to, say what the sample is mounted in, and say
   where on it to look. Written once here so the three of them cannot drift. */
const setUpTheRun = [
  connect,
  opticalConfiguration,
  carrierConfiguration,
  initialScanfields,
];

export const WORKFLOWS = {
  target_acquisition: workflow(
    "Target acquisition",
    "overview, detect, select, acquire",
    [
      ...setUpTheRun,
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
    "no analysis panel",
    [
      ...setUpTheRun,
      reworded(scanOverview, {
        why: "Drives the stage through every position and stitches the map.",
      }),
      reworded(saveRun, {
        why: "Writes the stitched map and its report to the run folder.",
        note: "map + report written",
      }),
      reworded(disconnect, { why: "Releases the microscope." }),
    ],
  ),

  focus_check: workflow(
    "Focus surface check",
    "calibration run",
    [
      ...setUpTheRun,
      reworded(focusStrategy, {
        why: "Choose how the surface is measured, then run it.",
      }),
      reworded(saveRun, {
        title: "Write the surface",
        why: "Fits the plane and records its residual for this objective.",
        btn: "Write surface",
        ms: 700,
        note: "residual 1.8 µm · written",
      }),
      reworded(disconnect, { why: "Releases the microscope." }),
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

/** Which workflow a freshly opened page starts on. */
export const DEFAULT_WORKFLOW = "target_acquisition";
