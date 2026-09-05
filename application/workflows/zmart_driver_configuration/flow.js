/**
 * ZMART driver configuration — setting a microscope up, before any run.
 *
 * Target acquisition is a run on a microscope that has already been set up.
 * This is the setting up: five steps that walk an operator through what a
 * driver needs before an imaging workflow can stand on it. Connect; say how
 * far the stage may travel; measure which way the picture is turned relative
 * to the stage; measure the optics; choose the point the run counts from.
 *
 * Two things make this workflow unlike the imaging one, and both are
 * deliberate. There is no canvas: setting a microscope up is reading numbers
 * off an instrument and writing them down, and every one of those readings is
 * a control rather than a picture, so the workflow brings a notebook-shaped
 * panel of its own. And it does not go through the controller: it talks to
 * the driver's *setup*, through a seam nothing holding a session can reach.
 * `docs/design/2026-09-05-zmart-driver-configuration-workflow.md` says why
 * that separation is a safety property rather than a convenience.
 *
 * The steps hold the meaning; the connected driver holds the method. After
 * Connect the page knows which driver it is talking to, and each step asks
 * that driver what it can do and draws itself accordingly.
 */

import { setupAsBackend } from "../../parts/microscope/setup.js";
import { setupPanel } from "./panel/setup-panel.js";
import { connect } from "./steps/connect/step.js";
import { stageLimits } from "./steps/stage_limits/step.js";
import { stageToImage } from "./steps/image_to_stage/step.js";
import { opticsCalibration } from "./steps/optics_calibration/step.js";
import { frameOrigin } from "./steps/frame_origin/step.js";

/* The folder rule would read "Zmart driver configuration". ZMART is a name. */
export const name = "ZMART driver configuration";

export const blurb =
  "Set a microscope up for ZMART: its stage limits, which way its picture is "
  + "turned, its optics, and the point it counts from. Through the driver's "
  + "setup, never through a session.";

/* The origin comes straight after the limits: both are said in the stage's
   own coordinates, and the origin is a snapshot of the drives that depends
   on no picture. The two measuring steps follow in the order they depend on
   each other -- the objective pair is matched on orientation-corrected
   pictures, so image-to-stage comes first. */
export const steps = [connect, stageLimits, frameOrigin, stageToImage, opticsCalibration];

/** One panel, a notebook down the middle of the window. No canvas. */
export const panels = [setupPanel];

/** This workflow speaks to the setup seam, not to the controller. */
export const backend = setupAsBackend;
