/**
 * Step 4 — Image-to-stage calibration.
 *
 * A camera or a scanner is often mounted a quarter or a half turn away from
 * the stage's own X and Y. When it is, telling the stage to move right shows
 * up in the picture as a shift in some other direction, and every piece of
 * software above would end up chasing features the wrong way.
 *
 * This step measures that fixed relationship once and writes it down. The
 * answer is always one of eight ways of laying the image down — a quarter,
 * half or three-quarter turn, each of them optionally mirrored — because a
 * camera is mounted squarely even when it is mounted sideways. Some
 * acquisition settings mirror the image deliberately, so a measured mirror is
 * recorded rather than treated as a fault. These are lossless rearrangements
 * of the pixels: nothing is resampled and nothing is blurred.
 *
 * Once it is recorded the driver corrects every saved image on the way out, so
 * left-right and up-down in a picture mean the same thing as X and Y on the
 * stage. Workflows above never do this arithmetic, and never see that it
 * happened. Until the measurement is made the driver assumes no turn at all,
 * which is honest rather than convenient: an unmeasured microscope is never
 * rotated by guesswork.
 *
 * In the driver this is the `orientation` subsystem, measured today by the
 * `set_orientation` notebook.
 */

import channel from "./channel.js";

export const stageToImage = {
  id: "orientation",
  title: "Image-to-stage calibration",
  why: "Measure which way the stage has to move to move the image the way you "
    + "mean — we think in pictures, and the stage has to follow.",
  panels: ["setup"],
  btn: "Measure orientation",
  ms: 0,
  /* The step's cells build the press that publishes, so the shell adds none. */
  ownButton: true,
  /* The cells themselves; the shell mounts them when the step is walked to. */
  channel,

  ready: ({ done }) =>
    (done?.has("connect") ? null : "connect to the microscope first"),
};
