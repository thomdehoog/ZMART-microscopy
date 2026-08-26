/**
 * The sample the pretend instrument images: tissue on the plate, cells in it.
 *
 * Deterministic, so the rehearsal looks the same every load and can be argued
 * about. Carrier micrometres throughout — the same frame the scan fields and
 * the carrier's areas are in.
 *
 * Two things, and the split is the point. **Tissue belongs to the plate**:
 * soft patches spread over the carrier, there whether or not anybody looks.
 * **Cells belong to the plan**: a run only knows about what it imaged, so
 * they are generated inside the tiles the scan fields ask for. Look somewhere
 * else and a different sample comes back, which is the honest behaviour — an
 * earlier version was a fixed block of tiles in the corner that the plan
 * could not move.
 *
 * This is what a real instrument replaces: when the backend reports what it
 * imaged, nothing here is asked any more.
 */

import { makeRng } from "./rng.js";

/** How many cells a whole plan finds, spread over its positions by richness. */
const TARGET_CELLS = 1250;

/** The range of cell areas, in µm² — what the gate's axis is drawn across. */
export const AREA_LO = 60;
export const AREA_HI = 400;

/** The plate's soft patches, in the carrier's own micrometres. */
export function tissueFor([w, h]) {
  const rnd = makeRng(20260728);
  return Array.from({ length: 7 }, () => ({
    x: (0.08 + 0.84 * rnd()) * w,
    y: (0.08 + 0.84 * rnd()) * h,
    r: (0.10 + 0.16 * rnd()) * Math.min(w, h),
  }));
}

/** How rich the tissue is at a place: 0 bare, 1 thick. */
export function densityAt(tissue, x, y) {
  let d = 0;
  for (const patch of tissue) {
    const dx = x - patch.x, dy = y - patch.y;
    d += Math.exp(-(dx * dx + dy * dy) / (2 * patch.r * patch.r));
  }
  return Math.min(1, d);
}

/**
 * The sample a run would find: the plate's tissue, and the cells inside the
 * positions the plan lays. Each cell remembers which position imaged it, so
 * tuning detection on one position is a question the sample can answer.
 *
 * Rebuilt whenever the plan or the plate changes, because either changes what
 * there is to find.
 */
export function sampleFor(extentUm, plan) {
  const tissue = tissueFor(extentUm);
  if (!plan.length) return { tissue, cells: [], bounds: null };

  const rnd = makeRng(90210);
  const per = TARGET_CELLS / plan.length;
  const cells = [];
  let xMin = Infinity, yMin = Infinity, xMax = -Infinity, yMax = -Infinity;

  plan.forEach((position, tile) => {
    const half = position.frameUm / 2;
    xMin = Math.min(xMin, position.x - half); xMax = Math.max(xMax, position.x + half);
    yMin = Math.min(yMin, position.y - half); yMax = Math.max(yMax, position.y + half);

    /* A rich patch comes back crowded and a bare one nearly empty, rather
       than every position returning the same handful. */
    const rich = densityAt(tissue, position.x, position.y);
    const many = Math.round(per * (0.15 + 1.85 * rich));
    for (let i = 0; i < many; i++) {
      const area = 62 + 330 * Math.pow(rnd(), 1.7);
      cells.push({
        id: cells.length + 1,
        tile,
        x: position.x + (rnd() - 0.5) * position.frameUm,
        y: position.y + (rnd() - 0.5) * position.frameUm,
        area,
        intensity: Math.max(0.02, Math.min(1, 0.18 + 0.62 * rich + 0.22 * (rnd() - 0.5))),
        r: Math.sqrt(area / Math.PI),
      });
    }
  });

  return { tissue, cells, bounds: { xMin, yMin, xMax, yMax } };
}

/** The cells one position imaged. */
export const cellsInTile = (sample, tile) => sample.cells.filter((c) => c.tile === tile);
