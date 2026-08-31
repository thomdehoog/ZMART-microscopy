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
