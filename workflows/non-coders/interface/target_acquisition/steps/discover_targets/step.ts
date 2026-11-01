/**
 * Step 6 — Detect objects.
 *
 * Discovery brings no panel of its own: the targets it finds land on the
 * canvas, and its controls sit in the channel beside it, the same shape as
 * focus. `run.ts` runs the detection; `channel.ts` holds its settings.
 */

import { detectionChannel } from "./channel.ts";
import { detectionFinished, runDetection } from "./run.ts";
import type { TaStep } from "../../types.ts";

export const detectCells: TaStep = {
  id: "detect",
  title: "Detect objects",
  btn: "Detect objects",
  panels: [],
  ms: 1600,
  mode: "detect",
  /* Trying settings on one tile first is offered, never demanded: the
     operator decides when the settings are worth the whole sample, and a
     press that refused until a test had been staged was a step doing the
     deciding for them. */
  ready: () => null,
  run: runDetection,
  finished: detectionFinished,
  /* Discovery is the analysis run; its brake puts the workers down. */
  brake: (page) => page.backend.stopTargets?.(),
  channel: detectionChannel,
};
