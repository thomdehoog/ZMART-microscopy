/**
 * Step 1 — Connect.
 *
 * Choose the microscope, fill in what its driver needs and the folder the
 * run goes to, then open the session.
 * Every run that drives a microscope starts here: nothing can be measured,
 * moved or imaged until there is a session to do it through.
 *
 * What the fields of a step mean is written out once, in `workflows/README.md`.
 */

import type { TaStep } from "../../types.ts";
import { connectChannel } from "./channel.ts";
import { connectFinished, runConnect } from "./run.ts";

export const connect: TaStep = {
  id: "connect",
  title: "Connect",
  btn: "Connect",
  ownButton: true,
  /* The first step asks for the canvas, so the stage is there from the start:
     every step keeps the picture on the left and its controls in the channel. */
  panels: ["canvas"],
  ms: 0,
  run: runConnect,
  finished: connectFinished,
  channel: connectChannel,
};
