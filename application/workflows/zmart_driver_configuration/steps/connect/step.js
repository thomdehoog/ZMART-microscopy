/**
 * Step 1 — Connect.
 *
 * Nothing about a microscope can be measured until there is a session to
 * measure it through, so a configuration run starts exactly where an imaging
 * run does. Rather than describe the same step a second time, this borrows the
 * one target acquisition already owns and changes only the sentence under its
 * title, which is what `reworded` is for: what the step *does* stays written
 * down in one place, so a fix to connecting reaches both workflows at once.
 *
 * Two things are changed here. The wording says why you are connecting on this
 * run — to read the instrument's own settings rather than to image anything.
 * And the panel is this workflow's own column of controls instead of the
 * canvas, because there is no picture in a configuration run.
 */

import { connect as connectToTheMicroscope }
  from "../../../target_acquisition/steps/connect/step.js";
import { reworded } from "../../../../framework/rules/steps.js";

export const connect = reworded(connectToTheMicroscope, {
  why: "Choose the microscope, its API and the password, then open the session "
    + "— the settings on the steps below are read from the instrument through it.",
  panels: ["setup"],
});
