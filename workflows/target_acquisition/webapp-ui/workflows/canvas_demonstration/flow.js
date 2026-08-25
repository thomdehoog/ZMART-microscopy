/**
 * Canvas demonstration — the flow.
 *
 * Not a run. This is a bench, and it is named as one so that nobody a month
 * from now chooses it expecting a microscope to move and then wonders why
 * nothing happens.
 *
 * What it is for: the canvas draws three layers, one over the other — the
 * operator's own drawing beneath, the acquired picture in the middle, and the
 * operator's own drawing above — and this is where you can switch each of them
 * on and off and watch what happens. It is deliberately kept out of target
 * acquisition, because mixing it into a workflow that drives a microscope
 * would turn every question about the picture into a question about the run
 * going on around it.
 *
 * One step, and the engines are compared inside it — the step's own file says
 * why one step rather than two.
 */

import { theCanvas } from "./steps/1_viewer_comparison/step.js";

export const blurb =
  "Not a run. A bench for watching the canvas draw its three layers: the " +
  "operator's own drawing beneath, the acquisition, and the operator's own " +
  "drawing above. No microscope moves and nothing is saved.";

export const steps = [theCanvas];
