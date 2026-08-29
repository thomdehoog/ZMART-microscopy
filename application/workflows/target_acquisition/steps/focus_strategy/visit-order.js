/**
 * The order a focus map is visited in: two levels of one rule. The tilesets
 * are swept as a serpentine of their centres, and each tileset's points as
 * a serpentine inside it -- top-left first at both levels, groups never
 * interleaved.
 *
 * Nearest-neighbour was considered and lost: it is short, but watched live
 * it looks like a random walk -- diagonal hops to whatever is closest. A
 * serpentine reads the way the scan does: rows top to bottom, the first
 * swept left to right and the next right to left, ending wherever the
 * bottom corner is. Short, and it looks deliberate.
 *
 * The panel's list shows this same order, so reading it top to bottom
 * replays the run.
 */

/**
 * The points in visiting order.
 *
 * A point's `tileset` tag says which leg it marches with; the legs are
 * ordered by where they stand, not by their tags. Points of no tileset
 * (laid by hand outside every frame) are visited last, swept the same way.
 */
export function visitOrder(points) {
  const groups = new Map();
  for (const point of points) {
    const key = Number.isFinite(point.tileset) ? point.tileset : Infinity;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(point);
  }
  const tail = groups.get(Infinity) ?? [];
  groups.delete(Infinity);
  /* Each leg is stood in for by its centre, and the centres are swept by
     the same serpentine the points inside are -- one rule, two levels. */
  const legs = [...groups.values()].map((held) => ({
    held,
    x: held.reduce((sum, point) => sum + point.x, 0) / held.length,
    y: held.reduce((sum, point) => sum + point.y, 0) / held.length,
  }));
  return [
    ...serpentine(legs).flatMap(({ held }) => serpentine(held)),
    ...serpentine(tail),
  ];
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
