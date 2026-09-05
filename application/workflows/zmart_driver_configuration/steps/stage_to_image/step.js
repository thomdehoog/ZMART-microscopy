/**
 * Step 3 — Stage-to-image calibration.
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

export const stageToImage = {
  id: "orientation",
  title: "Stage-to-image calibration",
  why: "Measure how the picture is turned relative to the stage, so moving right "
    + "on the stage means moving right in the image.",
  panels: ["setup"],
  btn: "Measure orientation",
  ms: 0,

  ready: ({ done }) =>
    (done?.has("connect") ? null : "connect to the microscope first"),
};
