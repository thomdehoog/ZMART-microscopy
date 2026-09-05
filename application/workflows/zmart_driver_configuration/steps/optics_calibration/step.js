/**
 * Step 4 — Optics calibration.
 *
 * This is the step that gives a picture its scale: how many micrometres of
 * specimen one pixel covers, and how the two objectives you work between line
 * up with each other. It is measured for a pair of lenses — the low-power one
 * an overview is taken with and the high-power one targets are acquired with —
 * because what the run needs to know is how to go from a feature spotted in
 * the overview to the same feature under the other objective.
 *
 * Without it a position found on an overview cannot be trusted under a
 * different lens, and a target that looked centred would arrive off the edge
 * of the frame. Run it once for each pair of objectives you intend to use.
 *
 * A measurement can be adopted as the microscope's default, or kept under a
 * name of its own so several lens combinations can live side by side. Either
 * way the published copy under ProgramData is the one the driver reads; the
 * values bundled with the code are only a fallback for a microscope nobody has
 * calibrated yet.
 *
 * In the driver this is the `calibration` subsystem, measured today by the
 * `calibrate_objective_pair` notebook.
 */

export const opticsCalibration = {
  id: "calibration",
  title: "Optics calibration",
  why: "Measure the pixel size and how a pair of objectives line up, so a target "
    + "found on the overview is still centred under the other lens.",
  panels: ["setup"],
  btn: "Calibrate objectives",
  ms: 0,

  ready: ({ done }) =>
    (done?.has("connect") ? null : "connect to the microscope first"),
};
