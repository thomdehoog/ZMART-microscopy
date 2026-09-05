/**
 * Step 5 — Set up origin.
 *
 * The origin is the point the run counts from. Once it is set, the position
 * the stage reports is micrometres from that point rather than from wherever
 * the instrument happens to call zero, which is what lets a position written
 * down today still mean the same place tomorrow.
 *
 * This one is different from the three steps above it, and the difference is
 * worth knowing. Limits, orientation and optics are properties of the
 * microscope: measured once, published to the machine, and read back at every
 * connect from then on. The origin belongs to the session you are in. The
 * driver does not restore it when you connect, so a run that wants a frame of
 * its own sets one at the start.
 *
 * It is also the one step here that is a single call rather than a notebook:
 * `Session.set_origin()` in the controller declares that where the stage is
 * standing right now is (0, 0, 0). So the work of this step is driving the
 * stage to the place you want to count from and saying "here".
 */

export const frameOrigin = {
  id: "origin",
  title: "Set up origin",
  why: "Drive to the point the run should count from and make it (0, 0, 0) — "
    + "positions are micrometres from there.",
  panels: ["setup"],
  btn: "Set origin here",
  ms: 0,

  ready: ({ done }) =>
    (done?.has("connect") ? null : "connect to the microscope first"),
};
