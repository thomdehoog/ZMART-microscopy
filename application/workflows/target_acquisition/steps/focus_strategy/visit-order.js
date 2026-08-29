/**
 * The order a focus map is visited in: two levels of one rule. The tilesets
 * are routed as their centres, and each tileset's points inside it --
 * top-left first at both levels, legs never interleaved.
 *
 * The rule is a cheap shortest path that stays readable: nearest-neighbour
 * from the top-left point, then 2-opt untangling until no crossing remains.
 * Raw nearest-neighbour watched live looks like a random walk; a rigid
 * serpentine reads well but is not short on scattered layouts. A
 * crossing-free path is both -- and on a regular grid it collapses into
 * the page-sweep anyway: top row left to right, next row back.
 *
 * The panel's list shows this same order, so reading it top to bottom
 * replays the run.
 */

/**
 * The points in visiting order.
 *
 * A point's `tileset` tag says which leg it marches with; the legs are
 * ordered by where they stand, not by their tags. Points of no tileset
 * (laid by hand outside every frame) are visited last, routed the same way.
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
  /* Each leg is stood in for by its centre, and the centres are routed by
     the same rule the points inside are -- one rule, two levels. */
  const legs = [...groups.values()].map((held) => ({
    held,
    x: held.reduce((sum, point) => sum + point.x, 0) / held.length,
    y: held.reduce((sum, point) => sum + point.y, 0) / held.length,
  }));
  return [
    ...route(legs).flatMap(({ held }) => route(held)),
    ...route(tail),
  ];
}

const apart = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

/**
 * A cheap shortest path, top-left first.
 *
 * Greedy nearest-neighbour builds it -- from the point nearest the layout's
 * top-left corner, always onward to the closest unvisited, ties broken
 * upward then leftward so a grid reads like a page -- and 2-opt untangles
 * it: any stretch whose reversal shortens the walk is reversed, until
 * nothing improves. Greedy alone leaves crossings and stranded hops; the
 * untangling removes exactly those, and a path that never crosses itself
 * is the one an operator reads as deliberate.
 */
function route(held) {
  if (held.length < 2) return held;
  const corner = {
    x: Math.min(...held.map((p) => p.x)),
    y: Math.min(...held.map((p) => p.y)),
  };
  const left = [...held];
  left.sort((a, b) => apart(a, corner) - apart(b, corner) || a.y - b.y || a.x - b.x);
  const path = [left.shift()];
  while (left.length) {
    const from = path[path.length - 1];
    left.sort((a, b) => apart(a, from) - apart(b, from) || a.y - b.y || a.x - b.x);
    path.push(left.shift());
  }
  for (let pass = 0, better = true; better && pass < 24; pass++) {
    better = false;
    for (let i = 1; i < path.length - 1; i++) {
      for (let j = i + 1; j < path.length; j++) {
        /* Reversing path[i..j] swaps two edges: the way in, and -- when the
           stretch is not the tail -- the way out. The start stays the start:
           top-left first is the rule, not a candidate for shortening. */
        const before = apart(path[i - 1], path[i])
          + (j + 1 < path.length ? apart(path[j], path[j + 1]) : 0);
        const after = apart(path[i - 1], path[j])
          + (j + 1 < path.length ? apart(path[i], path[j + 1]) : 0);
        if (after + 1e-9 < before) {
          let lo = i, hi = j;
          while (lo < hi) { [path[lo], path[hi]] = [path[hi], path[lo]]; lo++; hi--; }
          better = true;
        }
      }
    }
  }
  return path;
}
