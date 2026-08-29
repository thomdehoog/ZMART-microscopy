/**
 * The order a focus map is visited in: tilesets whole, in the plan's own
 * order, and a serpentine sweep inside each.
 *
 * Nearest-neighbour was considered and lost: it is short, but watched live
 * it looks like a random walk -- diagonal hops to whatever is closest. A
 * serpentine reads the way the scan does: rows top to bottom, the first
 * swept left to right and the next right to left, top-left first, ending
 * wherever the bottom corner is. Short, and it looks deliberate.
 *
 * The panel's list shows this same order, so reading it top to bottom
 * replays the run.
 */

/**
 * The points in visiting order.
 *
 * Tilesets never interleave: a group is drained before the next is begun.
 * Their order is the plan's own -- a higher-order fact this function
 * inherits rather than invents. Points of no tileset (laid by hand) are
 * visited last, swept the same way.
 */
export function visitOrder(points) {
  const groups = new Map();
  for (const point of points) {
    const key = Number.isFinite(point.tileset) ? point.tileset : Infinity;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(point);
  }
  return [...groups.keys()].sort((a, b) => a - b)
    .flatMap((key) => serpentine(groups.get(key)));
}

/**
 * Rows top to bottom, alternating direction.
 *
 * Rows are found by the vertical gaps. Two kinds exist: jitter, between
 * points meant as one row, and pitch, between the rows themselves -- and a
 * pitch is not slightly larger than a jitter, it is another order of thing.
 * So the gaps are sorted and the first twenty-fold jump splits the two
 * kinds; rows bind below it. Gaps all of one kind (an exact grid) are all
 * pitches, and every one starts a row.
 */
function serpentine(held) {
  if (held.length < 2) return held;
  const sorted = [...held].sort((a, b) => a.y - b.y || a.x - b.x);
  const gaps = [];
  for (let i = 1; i < sorted.length; i++) {
    const gap = sorted[i].y - sorted[i - 1].y;
    if (gap > 1e-6) gaps.push(gap);
  }
  gaps.sort((a, b) => a - b);
  let tolerance = gaps.length ? gaps[0] / 2 : 0;
  for (let i = 1; i < gaps.length; i++) {
    if (gaps[i] / gaps[i - 1] >= 20) {
      tolerance = Math.sqrt(gaps[i - 1] * gaps[i]);
      break;
    }
  }
  const rows = [];
  let rowY = null;
  for (const point of sorted) {
    if (rowY === null || point.y - rowY > tolerance) {
      rows.push([]);
      rowY = point.y;
    }
    rows[rows.length - 1].push(point);
  }
  return rows.flatMap((row, i) => {
    const swept = [...row].sort((a, b) => a.x - b.x);
    return i % 2 ? swept.reverse() : swept;
  });
}
