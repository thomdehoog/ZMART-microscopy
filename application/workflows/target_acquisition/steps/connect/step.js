/**
 * Step 1 — Connect.
 *
 * Choose the microscope, its API and the password, then open the session.
 * Every run that drives a microscope starts here: nothing can be measured,
 * moved or imaged until there is a session to do it through.
 *
 * What the fields of a step mean is written out once, in `workflows/README.md`.
 */

export const connect = {
  id: "connect",
  title: "Connect",
  why: "Choose the microscope, its API and the password, then open the session.",
  btn: "Connect",
  ownButton: true,
  /* The first step asks for the canvas, so the stage is there from the start:
     every step keeps the picture on the left and its controls in the channel. */
  panels: ["canvas"],
  ms: 0,
};
