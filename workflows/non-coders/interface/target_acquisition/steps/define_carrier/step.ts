/**
 * Step 2 — Define Carrier.
 *
 * The step that puts the run on the stage. Asking for the canvas here is what
 * brings the picture up, and it stays for every step after this one, because
 * from here on the run is something that happens on a stage.
 *
 * The controls this step docks beside the canvas live in `channel.ts` and
 * `carrier-panel.ts`, in this same folder; what a carrier *is* — where its
 * wells sit, how wide they are — lives in `../../shared/carriers.ts`, because
 * the scan-area step needs the same geometry and two copies of a fact drift
 * apart in silence.
 */

import type { TaStep } from "../../types.ts";
import { carrierChannel, carrierSettled } from "./channel.ts";

export const carrierConfiguration: TaStep = {
  id: "carrier",
  title: "Define Carrier",
  panels: ["canvas"],
  mode: "carrier",
  /* Configuring the carrier is the work: standing on the step settles it. */
  settledByStanding: carrierSettled,
  channel: carrierChannel,
};

/* Registering the carrier — saying where the thing described here actually
   sits on the stage — belongs in the step above and will be built into it.
   It had a step of its own for a while, empty and declared a placeholder, and
   an empty step in the rail is a promise the run keeps failing to keep: the
   operator counts it, walks to it, finds nothing, and walks on. What it will
   be is another part of describing the carrier, which is what that step is
   for, so it will arrive there rather than here. */
