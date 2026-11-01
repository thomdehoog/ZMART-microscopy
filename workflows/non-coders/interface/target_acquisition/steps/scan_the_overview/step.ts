/**
 * Step 5 — Scan the overview.
 *
 * The count is the smaller half of what this step reports. The other half is
 * the picture: the overview drawn from the images the run is writing, filling
 * in position by position, so the operator can see that the sample is where it
 * was meant to be and that the focus held — neither of which a count can say.
 * `watching-the-run.ts`, in this same folder, holds that picture and explains
 * how it is kept up to date; `run.ts` drives the scan, and `channel.ts` holds
 * its summary, its test tiles and its progress.
 */

import { hasRecording } from "../../microscope/recordings.ts";
import type { TaStep } from "../../types.ts";
import { scanArrived, scanChannel } from "./channel.ts";
import { runScan, scanFinished } from "./run.ts";

export const scanOverview: TaStep = {
  id: "scan",
  title: "Scan the overview",
  btn: "Start",
  panels: [],
  ms: 0,
  mode: "scan",
  /* A scan by hand is the rehearsal, on the tiles pressed green; with none
     green there is nothing it was asked to take (Thom, 2026-09-28). The
     protocol run takes the whole plan and never asks this. */
  ready: ({ testTiles, overviewPreset }) =>
    (!hasRecording(overviewPreset) ? "import the optical configuration first"
      : testTiles?.size ? null : "select the tiles to scan first"),
  run: runScan,
  finished: scanFinished,
  brake: (page) => page.backend.stopScan?.(),
  arrived: scanArrived,
  channel: scanChannel,
};
