/**
 * Step 3 — Define coordinate system origin.
 *
 * The origin is the point the run counts from. Once it is set, the position
 * the stage reports is micrometres from that point rather than from wherever
 * the instrument happens to call zero, which is what lets a position written
 * down today still mean the same place tomorrow.
 *
 * It is the fourth of the four things the driver keeps for a machine, beside
 * the limits, the image-to-stage turn and the optics. Its folder sits with
 * theirs under ProgramData and every change to it keeps its own dated record.
 * What makes it unlike the other three is only when it is applied: the driver
 * does not restore it at the next connect, so a run that wants a frame of its
 * own says so at the start.
 *
 * Like the other three, it is published by the driver rather than reached
 * through the controller, and for the same reason. Moving the origin redefines
 * the frame that every position already recorded is expressed in. Nothing
 * breaks loudly when it changes — a target list captured beforehand simply
 * means somewhere else afterwards, and no tile knows it — which is exactly the
 * kind of quiet damage the boundary exists to prevent.
 *
 * The work of the step is driving the stage to the place you want to count
 * from and saying "here".
 */

import channel from "./channel.js";

export const frameOrigin = {
  id: "origin",
  title: "Define coordinate system origin",
  why: "Drive to the point the run should count from and make it (0, 0, 0) — "
    + "positions are micrometres from there.",
  panels: ["setup"],
  btn: "Set origin here",
  ms: 0,
  /* The step's cells build the press that publishes, so the shell adds none. */
  ownButton: true,
  /* The cells themselves; the shell mounts them when the step is walked to. */
  channel,

  ready: ({ done }) =>
    (done?.has("connect") ? null : "connect to the microscope first"),
};
