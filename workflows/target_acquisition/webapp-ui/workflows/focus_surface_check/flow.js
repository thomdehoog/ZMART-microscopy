/**
 * Focus surface check — the flow.
 *
 * A calibration run: measure how the sample's focus height varies across the
 * carrier, fit a surface to it, and write that surface down for later runs to
 * reuse. Every step here is borrowed — the set-up from target acquisition, the
 * closing save from the overview-only run — and reworded where this run means
 * something different by it, which keeps what a step *does* in one place while
 * letting each workflow explain it in its own terms.
 */

import { reworded } from "../../frame/rules/steps.js";
import { setUpTheRun } from "../target_acquisition/the-run.js";
import { focusStrategy } from "../target_acquisition/steps/4_focus_strategy/step.js";
import { saveRun } from "../overview_only/steps/5_save_the_run/step.js";

export const blurb = "calibration run";

export const steps = [
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
];
