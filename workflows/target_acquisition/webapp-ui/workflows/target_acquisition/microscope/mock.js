/**
 * The seam where the microscope goes — the pretend side of it.
 *
 * Everything above this line — steps, widgets, the frame — talks to a backend
 * and awaits. Nothing above this line knows whether a real stage moved. The
 * live backend (`live.js`, speaking HTTP to the bridge and through it to the
 * zmart controller) implements this same shape; if wiring the real microscope
 * means editing a widget, the seam leaked.
 *
 * This backend fakes the work with timers and the pretend sample, so the page
 * can be developed and tested with no instrument anywhere near it.
 *
 * The verbs, and the two kinds they come in
 * -----------------------------------------
 *
 * **Readouts** ask the instrument how it is set and change nothing.
 * `readSetting` is the whole of recording a preset — the acquisition settings
 * and the focussing preset alike are the instrument's state, read now. On the
 * live side this is one `get_state` through the controller.
 *
 * **Procedures** make the instrument do something. `connect` opens the
 * session, `measureFocus` drives to each point and focuses there,
 * `scanOverview` drives the whole plan. On the live side these move a real
 * stage, which is why they are separate verbs and not part of any readout.
 *
 * The seam stops at the overview scan for now: discovery, refinement and
 * acquisition of targets are still rehearsed inside the window, and their
 * verbs arrive here when that work starts.
 */

import {
  pretendCanvas, pretendConnectionStatus, pretendInstruments, pretendPositionUm, sampleReading,
} from "./microscopes.js";
import { makeRng } from "./pretend-sample/rng.js";
import { METRICS, METRIC_KEYS, debrisAt, sweep, pickPeak } from "./pretend-sample/sweep.js";

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/* The pretend sample is not flat and not level: a gentle tilt across the
   carrier, the same surface wherever the plan decides to look at it. This is
   the mock's knowledge of the world — the page never computes it, it asks. */
const focusZAt = (x, y, [w, h]) =>
  -412 + 96 * (x / w - 0.5) + 61 * (y / h - 0.5);

export const backend = {
  /** What can be connected to: the registry's entries, as the controller lists them. */
  async instruments() {
    return pretendInstruments();
  },

  /**
   * Open the session and verify it, one named check at a time.
   *
   * The keys arrive first through `onChecks`, so the window can put every
   * question on screen before any answer exists; each answer then lands
   * through `onCheck(index, value)` as the pretend verification gets to it.
   * Resolves, with the instrument's info, once every check has answered.
   */
  async connect(session, { onChecks, onCheck } = {}) {
    const status = pretendConnectionStatus(session);
    const keys = Object.keys(status);
    onChecks?.(keys);
    await Promise.all(keys.map((key, k) =>
      wait(260 * (k + 1)).then(() => onCheck?.(k, status[key]))));
    return { info: await this.info() };
  },

  /** The instrument's account of itself: here, the pretend canvas. */
  async info() {
    return { canvas: pretendCanvas() };
  },

  /** Where the stage is, per axis in micrometres. */
  async xyz() {
    const { x, y, z } = pretendPositionUm();
    return { x: { value: x, unit: "um" }, y: { value: y, unit: "um" }, z: { value: z, unit: "um" } };
  },

  /**
   * A readout, never a procedure: the instrument's state as it is set now,
   * shaped as the reading the window records. Recording a preset is this and
   * nothing more — nothing on the instrument moves.
   *
   * `nth` is the pretend operator's doing: the mock answers with the nth state
   * it knows, as though the optics were changed between readings. The live
   * backend reads what is there and ignores it.
   */
  async readSetting(type, { nth = 0 } = {}) {
    await wait(480);
    return sampleReading(type, nth);
  },

  /**
   * Drive to each point, focus there, and report what was found.
   *
   * Every measured point comes back with its height, plus everything the
   * window needs to show its work: the sweep traces for both sharpness
   * metrics (so the chart draws exactly what was measured), where the tissue
   * truly focuses, and the speck of debris the position carries, if any. A
   * height the operator moved by hand is kept — a measurement they overruled
   * is still their answer.
   *
   * `extent` is the carrier's size in micrometres; the pretend sample's tilt
   * is a fraction of the plate, so the mock needs to know how big the plate
   * is. The live backend ignores it — a real sample has its own tilt.
   */
  async measureFocus(points, { metric, extent }) {
    await wait(200);
    const measured = points.map((p, index) => {
      const focusZ = focusZAt(p.x, p.y, extent);
      const traces = Object.fromEntries(METRIC_KEYS.map((key) => {
        const sw = sweep({ focusZ, index, metric: key });
        return [key, { samples: sw.samples, candidates: sw.candidates }];
      }));
      const chosen = pickPeak(traces[metric].candidates);
      return {
        ...p,
        zAuto: chosen.z,
        onNarrow: chosen.narrow,
        z: p.manual ? p.z : chosen.z,
        focusZ,
        speck: debrisAt(index),
        traces,
      };
    });
    return { points: measured };
  },

  /**
   * Drive the stage through every position, reporting progress as tiles land.
   *
   * The window's live picture is not fed from here: it watches the run's own
   * store and re-reads it as tiles are saved, which is the same arrangement
   * the real instrument has. This only says how far along the drive is.
   */
  async scanOverview({ positions, ms = 2600, onProgress }) {
    const total = positions.length;
    const started = performance.now();
    await new Promise((resolve) => {
      const tick = () => {
        const t = Math.min(1, (performance.now() - started) / ms);
        onProgress?.(Math.round(t * total), total);
        if (t < 1) requestAnimationFrame(tick);
        else resolve();
      };
      requestAnimationFrame(tick);
    });
    return { done: total, of: total };
  },
};

/* What METRICS looks like is display metadata the window shares (labels,
   colours); re-exported so the page reads it through the seam rather than
   reaching into the pretend sample. */
export { METRICS, METRIC_KEYS };

/* A deterministic random stream for the window's rehearsal drawings (the
   pretend image textures in previews). Re-exported for the same reason. */
export { makeRng };
