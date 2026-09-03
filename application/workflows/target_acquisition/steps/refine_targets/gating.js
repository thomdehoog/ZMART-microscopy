/**
 * The gating rules: what a gate is, and which cells survive them all.
 *
 * A gate is one polygon drawn on one feature pair -- `fx` across, `fy` up,
 * `vertices` in feature units -- and gates accumulate. The selection is the
 * intersection: a cell must fall inside EVERY gate, whatever pair each is
 * drawn on, so adding a gate only ever narrows. A plot shows the gate that
 * belongs to its own pair or none at all; a polygon transplanted onto the
 * wrong axes would be a lie drawn in accent colour.
 *
 * Everything here is geometry and bookkeeping a canvas never touches, which
 * is what lets `gating.test.js` pin the rules without one.
 */

/** A cell's value for a named feature: its own row first, the two the
    detector always reports -- area, intensity -- as the fallback. */
export function cellFeature(cell, name) {
  const row = cell.features;
  if (row && Number.isFinite(row[name])) return row[name];
  return Number.isFinite(cell[name]) ? cell[name] : 0;
}

/** Every feature the cells can offer an axis: the union of their rows, with
    the legacy pair always present, sorted so the pickers read steadily. */
export function featureNames(cells) {
  const names = new Set(["area", "intensity"]);
  for (const cell of cells) {
    for (const name of Object.keys(cell.features ?? {})) names.add(name);
  }
  return [...names].sort();
}

/** Whether (x, y) lies inside the polygon, by ray casting: winding-agnostic,
    and an edge hit counts as inside -- a cell on the line was pointed at. */
export function insidePolygon(x, y, vertices) {
  let inside = false;
  for (let i = 0, j = vertices.length - 1; i < vertices.length; j = i++) {
    const [xi, yi] = vertices[i];
    const [xj, yj] = vertices[j];
    if ((yi > y) !== (yj > y)
      && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** The gate drawn on exactly this pair, or undefined. Axes are ordered --
    a gate on (size, glow) says nothing about a (glow, size) plot. */
export function gateForPair(gates, fx, fy) {
  return gates.find((gate) => gate.fx === fx && gate.fy === fy);
}

/**
 * The ids surviving every gate. No gates select nothing rather than
 * everything: an operator who has drawn no gate has chosen no cells, and a
 * step that quietly took the whole population acquired at every target.
 */
export function cellsInAllGates(cells, gates) {
  const taken = new Set();
  if (!gates.length) return taken;
  for (const cell of cells) {
    const inEvery = gates.every((gate) =>
      insidePolygon(cellFeature(cell, gate.fx), cellFeature(cell, gate.fy), gate.vertices));
    if (inEvery) taken.add(cell.id);
  }
  return taken;
}


/**
 * Systematic Uniform Random Sampling of n cells -- the stereology standard,
 * ported from the lab's MD-HCS curation core (`sample_cells`), which follows
 * stereology.info/sampling: lay a grid sized for n points over the pool's
 * own extent, give the WHOLE grid one uniform-random offset (the random
 * start), and take the nearest not-yet-chosen cell at each grid point. Even
 * spatial coverage over the area, yet unbiased, because where the grid falls
 * is random -- a plain shuffle draws clumps, and a clump is a density bias.
 *
 * `rand` is the source of the two offset numbers, injectable so a test can
 * pin the draw. Fewer cells than asked for returns them all.
 */
export function sursDraw(cells, n, rand = Math.random) {
  if (cells.length <= n) return cells.map((c) => c.id);
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const c of cells) {
    x0 = Math.min(x0, c.x); x1 = Math.max(x1, c.x);
    y0 = Math.min(y0, c.y); y1 = Math.max(y1, c.y);
  }
  const w = (x1 - x0) || 1;
  const h = (y1 - y0) || 1;
  /* About as many grid cells as the ask, however the region is shaped: a
     wide flat region once got far more columns than the ask, and the draw
     ran out after the first few -- all at the left. */
  const ncol = Math.min(n, Math.max(1, Math.round(Math.sqrt((n * w) / h))));
  const nrow = Math.max(1, Math.round(n / ncol));
  const tx = w / ncol;
  const ty = h / nrow;
  const offX = rand();
  const offY = rand();
  const taken = new Set();
  const chosen = [];
  /* Each grid cell takes the cell nearest its own point from INSIDE its own
     bounds, or nothing. Taking the nearest cell from anywhere let a point
     on sparse ground reach into the dense patch next door, so that patch
     was taken twice and the sparse ground stayed untouched -- and the strip
     past the last point, up to a whole step wide, was never reached at all.
     Bounds are inclusive at the far edge, so the last row and column of the
     region belong to a grid cell too. */
  const nearestIn = (gx, gy, within) => {
    let best = null;
    let bestD = Infinity;
    for (const c of cells) {
      if (taken.has(c.id) || !within(c)) continue;
      const d = (c.x - gx) ** 2 + (c.y - gy) ** 2;
      if (d < bestD) { bestD = d; best = c; }
    }
    return best;
  };
  const points = [];
  for (let i = 0; i < ncol; i++) {
    for (let j = 0; j < nrow; j++) {
      const left = x0 + i * tx, top = y0 + j * ty;
      points.push({
        gx: left + offX * tx, gy: top + offY * ty,
        inside: (c) => c.x >= left && c.x <= left + tx && c.y >= top && c.y <= top + ty,
      });
    }
  }
  for (const point of points) {
    if (chosen.length >= n) break;
    const best = nearestIn(point.gx, point.gy, point.inside);
    if (best) { taken.add(best.id); chosen.push(best.id); }
  }
  /* Grid cells that held nothing left the ceiling unmet: the ask is the
     ceiling, so the rest is drawn from what remains, each empty point
     taking its nearest cell from anywhere. Spread first, filled second. */
  let filled = true;
  while (chosen.length < n && filled) {
    filled = false;
    for (const point of points) {
      if (chosen.length >= n) break;
      const best = nearestIn(point.gx, point.gy, () => true);
      if (best) { taken.add(best.id); chosen.push(best.id); filled = true; }
    }
  }
  return chosen;
}

/**
 * The gated cells held under a per-tileset ceiling: at most `max` in each
 * tileset, drawn by {@link sursDraw} over that tileset's own extent so what
 * survives is spread evenly across the compartment. This is what the
 * Restrict press does, and only the press: the gates say what they let
 * through, and the ceiling is applied when the operator asks for it.
 *
 * `tilesetOf` names the tileset a cell's field belongs to; `rand` is the
 * draw's random start, injectable so a test can pin it.
 */
export function keptUnderCeiling(cells, gated, max, tilesetOf, rand = Math.random) {
  const byTileset = new Map();
  for (const c of cells) {
    if (!gated.has(c.id)) continue;
    const key = tilesetOf(c.field);
    if (!byTileset.has(key)) byTileset.set(key, []);
    byTileset.get(key).push(c);
  }
  const kept = new Set();
  for (const pool of byTileset.values()) {
    for (const id of sursDraw(pool, max, rand)) kept.add(id);
  }
  return kept;
}
