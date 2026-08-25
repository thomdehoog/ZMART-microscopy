/**
 * The seam where the microscope goes.
 *
 * Everything above this line — steps, widgets, the frame — talks to a backend
 * and awaits. Nothing above this line knows whether a real stage moved. When
 * the live driver arrives it implements this same shape and `main.js` imports
 * that instead; if wiring it means editing a widget, the seam leaked.
 *
 * This one fakes the work with timers and reports the synthetic sample.
 */

import { cells, TILE_COUNT, trueFocusZ, cellsInTile } from "../lib/sample.js";
import { sweep, pickPeak } from "../lib/sweep.js";
import { fitSurface, residualSummary, affineSurface, looErrors } from "../lib/surface.js";
import { WIDTH_UM, HEIGHT_UM } from "../lib/sample.js";

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export const PREVIOUS_SURFACES = {
  run_0714_a: { label: "2026-07-14 · slide A", plane: { a: 96, b: 61, c: -412 }, residual: 1.8, ageDays: 14 },
  run_0709_c: { label: "2026-07-09 · slide C", plane: { a: 71, b: 88, c: -389 }, residual: 3.1, ageDays: 19 },
};

export const mockBackend = {
  async connect() {
    await wait(900);
    return "session open · run folder created";
  },

  async disconnect() {
    await wait(600);
    return "session closed";
  },

  async setOrigin() {
    await wait(600);
    return "origin at 0.0, 0.0 µm";
  },

  async captureJob(kind) {
    await wait(700);
    return kind === "overview"
      ? "5x · 1.30 µm/px · 2 channels"
      : "63x · 0.10 µm/px · 2 channels";
  },

  /**
   * Measure each requested position and fit a surface through the results.
   * Heights the operator moved by hand are kept — a measurement they overruled
   * is still their answer.
   */
  async measureFocus({ strategy, metric, points, zFixed, reuse }) {
    await wait(1400);

    if (strategy === "fixed") {
      return {
        surface: affineSurface({ c: zFixed, width: WIDTH_UM, height: HEIGHT_UM }),
        points, note: `fixed z ${zFixed} µm`,
      };
    }
    if (strategy === "reuse") {
      const stored = PREVIOUS_SURFACES[reuse];
      return {
        surface: affineSurface({ ...stored.plane, width: WIDTH_UM, height: HEIGHT_UM }),
        points, note: `reusing ${stored.label}`,
      };
    }
    if (strategy === "auto") {
      return { surface: null, points, note: `focused at every position · ${metric}` };
    }

    const measured = points.map((p, i) => {
      const chosen = pickPeak(sweep({ focusZ: trueFocusZ(p.x, p.y), index: i, metric }).candidates);
      return {
        ...p,
        zAuto: chosen.z,
        onNarrow: chosen.narrow,
        z: p.manual ? p.z : chosen.z,
      };
    });

    const surface = fitSurface(measured);
    const { rms, worst } = residualSummary(surface, measured);
    const loo = looErrors(measured);
    measured.forEach((p, i) => { p.loo = loo[i]; });

    return {
      surface, points: measured, rms, worst, loo,
      note: `${surface.model} from ${measured.length} points · rms ${rms.toFixed(1)} µm`,
    };
  },

  /** Drives the stage through every position, reporting tiles as they land. */
  async scanOverview({ onProgress } = {}) {
    const total = TILE_COUNT;
    const started = performance.now();
    const duration = 2600;
    await new Promise((resolve) => {
      const tick = () => {
        const t = Math.min(1, (performance.now() - started) / duration);
        onProgress?.(Math.round(t * total), total);
        if (t < 1) requestAnimationFrame(tick);
        else resolve();
      };
      requestAnimationFrame(tick);
    });
    return `${total} / ${total} tiles`;
  },

  /** Which objects a given setting finds — the same rule for one tile or all. */
  detects(settings, cell) {
    const diameter = 2 * cell.r;
    if (settings.algo === "cellpose") {
      return diameter > settings.diameter * 0.70
        && diameter < settings.diameter * 1.55
        && cell.intensity > 0.36 + settings.cellprob * 0.05;
    }
    return cell.intensity >= settings.thresh && cell.area >= settings.minArea;
  },

  /** Try the settings on one tile. No stage movement, no waiting. */
  testTile(settings, { col, row }) {
    const inTile = cellsInTile(col, row);
    return { found: inTile.filter((c) => this.detects(settings, c)), total: inTile.length };
  },

  async detectAll(settings) {
    await wait(1600);
    const found = cells.filter((c) => this.detects(settings, c));
    return { ids: new Set(found.map((c) => c.id)), note: `${found.length} cells · ${settings.algo}` };
  },

  async confirmSelection(gated) {
    await wait(600);
    return `${gated.size} cells selected`;
  },

  async acquire(cellIds) {
    await wait(2200);
    const picked = [...cellIds].slice(0, 12);
    return { pairs: picked, note: `${picked.length} pairs acquired` };
  },

  async saveResults() {
    await wait(800);
    return "report + layout written";
  },
};
