/**
 * The workflows on offer.
 *
 * Each is a name, a sentence about what the workflow is for, and a list of steps
 * from the catalogue. That is the whole file — no logic, no special cases.
 * Adding one means importing the steps you want in the order you want them; if
 * it means editing the frame, the frame is missing something and that is the
 * bug.
 *
 * The name is what the chooser at the top left shows, and the rail it sits in is
 * a fixed column, so keep it to a couple of words. The sentence is shown when
 * the pointer rests on that choice, which is where there is room to say what a
 * name cannot.
 *
 * This is the only place the workflows are written down. The page imports it and
 * so do the unit tests, so a workflow that appears here is a workflow the
 * operator can choose and a workflow the tests can see. It used to be written
 * twice — here and again inside `main.js` — and the two drifted apart without
 * anything going red, which is the reason the note above matters.
 */

import { numbered } from "../frame/steps.js";
import {
  connect, carrierConfiguration, initialScanfields,
  focusStrategy, scanOverview, detectCells, selectCells, acquireAndCurate,
  saveRun, theCanvas,
  reworded,
} from "./steps.js";

const workflow = (name, blurb, steps) => ({ name, blurb, steps: numbered(steps) });

/* Every run that drives the microscope starts the same way: open the session,
   record what the optics are set to, say what the sample is mounted in, and say
   where on it to look. Written once here so the three of them cannot drift. */
const setUpTheRun = [
  connect,
  carrierConfiguration,
  initialScanfields,
];

export const WORKFLOWS = {
  target_acquisition: workflow(
    "Target acquisition",
    "overview, discover, refine, acquire",
    [
      ...setUpTheRun,
      focusStrategy,
      scanOverview,
      detectCells,
      selectCells,
      acquireAndCurate,
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
    ],
  ),

  /* Not a run. This is a bench, and it is named as one so that nobody a month
     from now chooses it expecting a microscope to move and then wonders why
     nothing happens.

     What it is for: the canvas draws three layers, one over the other — the
     operator's own drawing beneath, the acquired picture in the middle, and the
     operator's own drawing above — and this is where you can switch each of them
     on and off and watch what happens. It is deliberately kept out of target
     acquisition, because mixing it into a workflow that drives a microscope
     would turn every question about the picture into a question about the run
     going on around it.

     One step, and the engines are compared inside it. This was two steps — the
     same scene drawn by Viv, then drawn by neuroglancer — and the row of engine
     buttons above the picture makes that arrangement redundant: changing engine
     keeps the view exactly where it is, so one scene seen through each engine in
     turn compares them more closely than two pictures that were never guaranteed
     to be looking at the same place. Two steps also had to be marked as waiting
     for nothing, because a rail means "do this, then that" and these never did.
     What the second step demonstrated — that two viewers can be open at once
     without fighting over shared state — is guarded by
     `test_two_viewers_can_be_open_at_once` rather than by an operator noticing. */
  canvas_layers: workflow(
    "Canvas demonstration",
    "Not a run. A bench for watching the canvas draw its three layers: the " +
      "operator's own drawing beneath, the acquisition, and the operator's own " +
      "drawing above. No microscope moves and nothing is saved.",
    [theCanvas],
  ),
};

/** Which workflow a freshly opened page starts on. */
export const DEFAULT_WORKFLOW = "target_acquisition";
