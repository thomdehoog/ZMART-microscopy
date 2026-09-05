/**
 * Step 2 — Set up limits.
 *
 * The limits are the envelope the stage is allowed to move in: how far it may
 * travel in X and Y, the two Z ranges, which objective slots automation may
 * turn to, and a permitted value or range for each of the settings the driver
 * is able to change. They are what stands between a mistyped position and the
 * stage driving into the objective, so the driver refuses to move at all until
 * it has them — what the code calls failing closed, meaning that when
 * something is missing the answer is "no" rather than "probably fine".
 *
 * Publishing them is this step's whole job. The values are written to a dated
 * folder under the machine's own ProgramData tree, and the newest folder is
 * the one the driver reads at the next connect. Nothing is overwritten: an
 * earlier set of limits stays where it was, so it is always possible to see
 * what the microscope was told and when.
 *
 * The measuring itself is the `set_limits` notebook that ships with the
 * driver. This step is where that will move to, so an operator setting a
 * microscope up meets one window rather than a notebook and a window.
 */

import channel from "./limits-boxes.js";

export const stageLimits = {
  id: "limits",
  title: "Set up limits",
  why: "Say how far the stage may travel and what the driver is allowed to set, "
    + "then publish it — until this exists the driver refuses to move.",
  panels: ["setup"],
  btn: "Publish limits",
  ms: 0,
  /* The step's cells build the press that publishes, so the shell adds none. */
  ownButton: true,
  /* The cells themselves; the shell mounts them when the step is walked to. */
  channel,

  ready: ({ done }) =>
    (done?.has("connect") ? null : "connect to the microscope first"),
};
