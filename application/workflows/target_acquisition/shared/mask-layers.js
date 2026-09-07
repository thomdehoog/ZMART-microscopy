/**
 * Mask layers: what a detection lays over a picture, as the row shows it.
 *
 * A mask layer is one detection's masks on one image layer. It has a name
 * built from what it outlines and how it was made, the image layer it lies
 * on, how many objects it holds, whether it is shown, and a dress of its
 * own -- colour, filled or outlined, opacity. The masks bar at the right of
 * the canvas row draws one cell per mask layer lying on the image layer
 * the row is on, and that bar's card edits one layer's dress.
 *
 * Pure, so the naming and the filter are pinned without a page.
 */

/* What each detector outlines and what it is called: the fast watershed
   finds nuclei; Cellpose, the robust choice, finds whole cells. */
const DETECTORS = {
  fast: { what: "nuclei", how: "fast" },
  robust: { what: "cells", how: "cellpose" },
};

/**
 * The name a new mask layer gets: "<what>, <how>", and a count when a layer
 * of that name already lies somewhere in `existing` -- "nuclei, fast 2".
 */
export function maskLayerName(algo, existing = []) {
  const { what, how } = DETECTORS[algo] ?? { what: "objects", how: algo };
  const base = `${what}, ${how}`;
  const taken = new Set(existing.map((one) => one.name));
  if (!taken.has(base)) return base;
  let n = 2;
  while (taken.has(`${base} ${n}`)) n += 1;
  return `${base} ${n}`;
}

let nextId = 1;

/**
 * A fresh mask layer for a detection with `algo`, lying on the image layer
 * `kind`, wearing `dress` (colour | null for each object its own, show:
 * fill | line, alpha 0..1). Shown from the start: a run that lays masks
 * lays them to be seen.
 */
export function newMaskLayer({ algo, kind, dress, existing = [] }) {
  nextId += 1;
  return {
    id: `mask-${nextId}`,
    name: maskLayerName(algo, existing),
    how: (DETECTORS[algo] ?? { how: algo }).how,
    kind,
    objects: 0,
    shown: true,
    dress: {
      colour: dress?.colour ?? null,
      show: dress?.show === "line" ? "line" : "fill",
      alpha: Number.isFinite(dress?.alpha) ? dress.alpha : 0.8,
    },
  };
}

/**
 * The dress the chosen targets wear on the picture, the same shape a mask
 * layer's is so the one card dresses both. Colour null is each target in
 * its own ink: the selected green, or the warning amber for one no tile
 * covers. Two thirds opaque, as the tint they wore before they had a dress.
 */
export const targetsDress = () => ({ colour: null, show: "fill", alpha: 0.67 });

/**
 * The dress the target tiles wear: colour null is the page's accent blue,
 * filled, half opaque -- the tint they wore before they had a dress.
 */
export const tilesDress = () => ({ colour: null, show: "fill", alpha: 0.5 });

/** The mask layers lying on the image layer `kind`, in the order laid. */
export const maskLayersOn = (layers, kind) => layers.filter((one) => one.kind === kind);

/**
 * `layers` with a fresh layer for `kind` in place of the one that was
 * there: a detection writes its masks over the last run's files, so on one
 * picture the newest run is the only one whose masks exist to be drawn.
 * Other pictures' layers are untouched.
 */
export function replaceMaskLayer(layers, fresh) {
  return [...layers.filter((one) => one.kind !== fresh.kind), fresh];
}
