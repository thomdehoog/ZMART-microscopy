/**
 * Step 3 — Overview scan area.
 *
 * The preset the overview is taken with is recorded here, not in a step of
 * its own: the fields take their frame from it, so it is tested where it
 * matters.
 *
 * The geometry editor and the grid this step docks beside the canvas live in
 * `channel.ts` and `scanfield-editor.ts`, in this same folder; the arithmetic
 * of the plan itself — how a drawn region becomes a grid of frames — lives in
 * `../../shared/scanfields.ts`, where later steps that consume the plan can
 * read the same answer.
 */

import type { TaStep } from "../../types.ts";
import { scanfieldsChannel, scanfieldsSettled } from "./channel.ts";

export const initialScanfields: TaStep = {
  id: "scanfields",
  title: "Overview scan area",
  panels: [],
  mode: "scanfields",
  /* Drawing fields is the work: standing on the step settles it. */
  settledByStanding: scanfieldsSettled,
  channel: scanfieldsChannel,
};
