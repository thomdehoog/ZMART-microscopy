/**
 * Step 7 — Discover Targets.
 *
 * Refinement is the same shape as discovery: the refined targets light up on
 * the canvas, and the channel holds the scatter they are gated on
 * (`channel.ts` and `gate.ts`).
 */

import type { TaStep } from "../../types.ts";
import { gatesArrived, gatesSettledByStanding, gatingChannel } from "./channel.ts";

export const selectCells: TaStep = {
  id: "gate",
  title: "Discover Targets",
  panels: [],
  mode: "gate",
  /* The gates have no press: looking at them applies them. */
  settledByStanding: gatesSettledByStanding,
  arrived: gatesArrived,
  channel: gatingChannel,
};
