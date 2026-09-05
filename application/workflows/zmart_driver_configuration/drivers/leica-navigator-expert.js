/**
 * How the Leica Stellaris 5 is configured through Navigator Expert.
 *
 * This is one driver's account of its own setting up, in the shape
 * `what-a-driver-declares.js` asks for. It is deliberately a description
 * rather than a procedure: the page reads it to know what to put on screen and
 * what to call things, and the measuring itself stays behind the driver.
 *
 * The limits document is described here rather than in the step because its
 * shape is this driver's own. A Leica through Navigator Expert has two Z
 * ranges — one for the galvo and one for the wide stage — and twenty settings
 * the driver is able to change, each of which may be fenced. Another
 * manufacturer will have neither the same axes nor the same settings, which is
 * exactly why the step holds only the meaning and the driver holds the list.
 */

export const setup = {
  vendor: "leica",
  microscope: "stellaris5-y42h93",
  api: "navigator-expert",
  label: "Leica Stellaris 5 · Navigator Expert",

  subsystems: {
    limits: {
      supported: true,
      how: "Place four Point markers at the safe X and Y corners in the active "
        + "LAS X template, then read the rectangle back from the instrument.",
      publishes: "limits.json, in a dated folder under the machine's limits tree.",
    },
    orientation: {
      supported: true,
      how: "Image a landmark, move the stage a known distance, and see which way "
        + "it travelled in the picture.",
      publishes: "orientation.json, in a dated folder under the machine's orientation tree.",
    },
    calibration: {
      supported: true,
      how: "Image the same field through both objectives of a pair and match them.",
      publishes: "calibration.json, either as the machine default or under a name "
        + "of its own, so several lens pairs can live side by side.",
    },
    origin: {
      supported: true,
      how: "Drive to the point the run should count from and make it (0, 0, 0).",
      publishes: "Nothing on disk. The origin belongs to the session you are in, "
        + "and the driver does not restore it at the next connect.",
    },
  },

  /**
   * The limits document this driver keeps, as the step should show it.
   *
   * `axes` are the stage ranges, each a low and a high in micrometres, both
   * endpoints included. `measured` names the ones the instrument can be asked
   * for: reading the boundary replaces X and Y and leaves the rest alone,
   * which is why the two boxes of the step are not the same box.
   *
   * `settings` are the driver's own setters. Each is either unrestricted or
   * carries one constraint — a range, or a list of allowed values. An empty
   * entry means "reviewed, and no limit is enforced", which is a different
   * statement from never having looked, and the file keeps every key visible
   * so the difference stays legible.
   */
  limitsDocument: {
    axes: [
      { key: "x_um", label: "X", unit: "µm" },
      { key: "y_um", label: "Y", unit: "µm" },
      { key: "z_galvo_um", label: "Z galvo", unit: "µm" },
      { key: "z_wide_um", label: "Z wide", unit: "µm",
        note: "Starts at zero: the wide stage cannot travel to a negative position." },
    ],
    measured: ["x_um", "y_um"],
    slots: { key: "objective_slot", label: "Objective slots",
      note: "Empty means every slot the turret reports. Slots count from zero." },
    settings: [
      "set_zoom", "set_scan_speed", "set_scan_resonant", "set_scan_mode",
      "set_sequential_mode", "set_scan_field_rotation", "set_image_format",
      "set_z_stack_definition", "set_z_stack_step_size", "set_z_stack_size",
      "set_frame_accumulation", "set_frame_average", "set_line_accumulation",
      "set_line_average", "set_pinhole_airy", "set_detector_gain",
      "set_laser_intensity", "set_laser_shutter", "set_filter_wheel_slot",
      "set_filter_wheel_spectrum",
    ],
  },
};
