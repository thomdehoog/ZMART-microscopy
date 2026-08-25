/**
 * The synthetic sample the mock backend images: geometry, tissue and cells.
 *
 * Read honestly, this is the older of the page's two rehearsal samples: a
 * fixed block of tiles, fed only to `../mock.js` and the unit tests on it.
 * The page itself rehearses with a newer sample that follows the plan — cells
 * are generated inside whatever tiles the scan fields ask for — and that one
 * lives in the window (`frame/window/main.js`) until the backend seam is
 * wired for real. When the seam is wired, this file is what the real
 * instrument replaces: the backend stops generating cells and starts
 * reporting them.
 *
 * Everything is deterministic. A mock that looks different on every load
 * cannot be tested and cannot be discussed.
 */

import { makeRng } from "./rng.js";

export const TILE_UM = 2662;          // 2048 px at 1.30 µm/px — a 5x overview tile
export const COLS = 7;
export const ROWS = 5;
export const WIDTH_UM = COLS * TILE_UM;
export const HEIGHT_UM = ROWS * TILE_UM;
export const TILE_COUNT = COLS * ROWS;

export const AREA_LO = 60;
export const AREA_HI = 400;

const rnd = makeRng(20260728);

/** Blobs of tissue. Cells live where these are, and so does image brightness. */
export const blobs = Array.from({ length: 6 }, () => ({
  x: (0.12 + 0.76 * rnd()) * WIDTH_UM,
  y: (0.12 + 0.76 * rnd()) * HEIGHT_UM,
  r: (0.10 + 0.13 * rnd()) * WIDTH_UM,
}));

export function density(x, y) {
  let d = 0;
  for (const b of blobs) {
    const dx = x - b.x;
    const dy = y - b.y;
    d += Math.exp(-(dx * dx + dy * dy) / (2 * b.r * b.r));
  }
  return Math.min(1, d);
}

export const cells = [];
for (let i = 0; cells.length < 1250 && i < 24000; i++) {
  const x = rnd() * WIDTH_UM;
  const y = rnd() * HEIGHT_UM;
  const d = density(x, y);
  if (rnd() > d * 0.92) continue;
  const area = 62 + 330 * Math.pow(rnd(), 1.7);
  const intensity = Math.max(0.02, Math.min(1, 0.18 + 0.62 * d + 0.22 * (rnd() - 0.5)));
  cells.push({ id: cells.length + 1, x, y, area, intensity, r: Math.sqrt(area / Math.PI) });
}

/** Which tile a stage position falls in, and the cells inside one. */
export const tileOf = (x, y) => ({
  col: Math.floor(x / TILE_UM),
  row: Math.floor(y / TILE_UM),
});

export const cellsInTile = (col, row) => cells.filter((c) =>
  c.x >= col * TILE_UM && c.x < (col + 1) * TILE_UM
  && c.y >= row * TILE_UM && c.y < (row + 1) * TILE_UM);

/**
 * Where the tissue is actually in focus. The sample is a tilted plane; the
 * autofocus has to discover that, and sometimes finds dust instead.
 */
export const trueFocusZ = (x, y) =>
  -412 + 96 * (x / WIDTH_UM - 0.5) + 61 * (y / HEIGHT_UM - 0.5);

/** Golden-angle hues, so neighbouring labels never share a colour. */
export const labelColour = (id, alpha = 1) =>
  `hsla(${(id * 137.508) % 360}, 68%, 58%, ${alpha})`;
