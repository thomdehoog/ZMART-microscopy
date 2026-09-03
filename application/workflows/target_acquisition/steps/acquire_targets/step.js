/**
 * Step 8 — Acquire Targets.
 *
 * The gallery joins the channels: the acquired targets ring on the canvas,
 * and the channel holds the acquisition type being recorded, the pairs, and
 * the verdicts collected on them.
 */

import { hasRecording } from "../../../../parts/microscope/recordings.js";

export const acquireAndCurate = {
  id: "acquire",
  title: "Acquire Targets",
  why: "Record the acquisition type, then image every refined target with it and collect your verdicts.",
  btn: "Acquire Targets",
  panels: [],
  ms: 2200,
  mode: "targets",
  /* Acquiring needs to know what with: the type is a reading taken off the
     instrument in this step's own channel, the way an optics preset is. */
  ready: ({ targetTiles, targetType }) =>
    (!targetTiles?.length ? "add the tiles first"
      : hasRecording(targetType) ? null : "record the acquisition type first"),
};
