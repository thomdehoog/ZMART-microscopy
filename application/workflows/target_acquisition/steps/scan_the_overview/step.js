/**
 * Step 5 — Scan the overview.
 *
 * The count is the smaller half of what this step reports. The other half is
 * the picture: the overview drawn from the images the run is writing, filling
 * in position by position, so the operator can see that the sample is where it
 * was meant to be and that the focus held — neither of which a count can say.
 * `overview.js`, in this same folder, holds that picture and explains how it
 * is kept up to date.
 */

import { hasRecording } from "../../../../parts/microscope/recordings.js";

export const scanOverview = {
  id: "scan",
  title: "Scan the overview",
  why: "Drives the stage through every position, stitching tiles as they are saved.",
  btn: "Start",
  panels: [],
  ms: 0,
  mode: "scan",
  /* A scan by hand is the rehearsal, on the tiles pressed green; with none
     green there is nothing it was asked to take (Thom, 2026-09-28). The
     protocol run takes the whole plan and never asks this. */
  ready: ({ testTiles, protocol, overviewPreset }) =>
    (!hasRecording(overviewPreset) ? "import the optical configuration first"
      : protocol?.running || testTiles?.size ? null : "select the tiles to scan first"),
};
