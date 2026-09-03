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
 * Systematic Uniform Random Sampling of n cells -- the stereology standard:
 * one random start, then every k-th member of the population in a fixed
 * order. The order is spatial, along a Z-order curve through the cells'
 * own extent, so that "every k-th" walks the sample region by region and
 * each region contributes in proportion to how many cells it holds. That
 * is the uniformity a systematic draw promises: a dense cluster gives more
 * than a sparse one, and no side of any cluster is favoured.
 *
 * The grid-point draw this replaces laid n points over the extent and took
 * the nearest cell to each; with cells clustered, most points were empty
 * and the fill walked the grid from one side, piling the draw up on the
 * side of each cluster it reached first -- the operator saw it.
 *
 * `rand` is the source of the random start, injectable so a test can pin
 * the draw. Fewer cells than asked for returns them all.
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
  /* The curve: x and y quantised to 16 bits each and their bits interleaved,
     so cells near each other on the sample are near each other in the order. */
  const spread = (v) => {
    let b = v & 0xffff;
    b = (b | (b << 8)) & 0x00ff00ff;
    b = (b | (b << 4)) & 0x0f0f0f0f;
    b = (b | (b << 2)) & 0x33333333;
    b = (b | (b << 1)) & 0x55555555;
    return b;
  };
  const keyed = cells.map((c) => {
    const qx = Math.round(((c.x - x0) / w) * 0xffff);
    const qy = Math.round(((c.y - y0) / h) * 0xffff);
    return { id: c.id, key: spread(qx) * 2 + spread(qy) };
  });
  keyed.sort((a, b) => a.key - b.key || String(a.id).localeCompare(String(b.id)));
  const k = keyed.length / n;
  const start = rand() * k;
  const chosen = [];
  for (let i = 0; i < n; i++) {
    const at = Math.min(keyed.length - 1, Math.floor(start + i * k));
    chosen.push(keyed[at].id);
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
