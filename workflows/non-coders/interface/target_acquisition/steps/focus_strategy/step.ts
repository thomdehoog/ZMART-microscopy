/**
 * Step 4 — Focus strategy.
 *
 * The focus preset is recorded here for the same reason the overview preset is
 * recorded in the scan-area step: the sweeps that measure the surface are
 * taken with it, so the reading lives in the step that uses it.
 *
 * The map itself -- the points, their sweeps and the surface through them --
 * is `focus-map.ts`; `channel.ts` puts its controls in the channel, and
 * `run.ts` measures it.
 */

/* Whether a step has what it needs is asked of the slot itself: a step waits
   for a reading to have been taken, not for a particular field on a record. */
import { hasRecording } from "../../microscope/recordings.ts";
import { focusChannel } from "./channel.ts";
import { focusFinished, runFocus } from "./run.ts";
import type { TaStep } from "../../types.ts";

export const focusStrategy: TaStep = {
  id: "focus",
  title: "Focus strategy",
  btn: "Run focus map",
  panels: [],
  ms: 0,
  mode: "focus",
  /* What the press needs: the reading the map is measured with, and points
     to measure.

     Not for three points, though a plane needs three: the fit chooses what the
     geometry buys — one point is a height, a few are a plane, enough are a
     spline — so a map of two is a map of two, measured and reported as such.
     Refusing to run it made the operator argue with the step about arithmetic
     it was doing anyway. */
  ready: ({ focus, focusPreset }) =>
    (!hasRecording(focusPreset) ? "record the focussing preset first"
      : focus.points.length ? null
        : "no points to measure yet"),

  /* Running the map finishes the step, not recording the preset: the scan
     stands on the heights the map measured on this sample (Thom,
     2026-09-28). The press that measures it stands in its box from the moment
     the box is there — greyed while there is nothing to measure, and saying
     so. It used to disappear instead, which made clearing the points look
     like it had broken the step. */
  run: runFocus,
  finished: focusFinished,
  /* The map's own brake, so a run of new points stops between two points
     as well as inside one. */
  brake: (page) => page.interruptTheFocusRun(),
  /* The focus step says nothing beside its press. What it waits for is the
     box it stands in — points, laid by the row above it — and what it came to
     is the traces below; a greyed button between the two is already the whole
     sentence. */
  noHint: true,
  channel: focusChannel,
};
