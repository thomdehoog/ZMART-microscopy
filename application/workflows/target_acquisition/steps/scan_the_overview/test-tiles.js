/**
 * Which tiles a rectangle on the picture takes in, and what a Shift-drag over
 * them means for the green set.
 *
 * Pure, so the rule is tested without a canvas: a tile is inside when its
 * centre is; a drag over tiles that are all green already turns them off,
 * and over any other mix turns them all on -- one gesture, one answer, and
 * the second drag over the same tiles undoes the first.
 */

/** Plan indices of the tiles whose centre lies in the box. */
export function tilesInBox(plan, box) {
  const xMin = Math.min(box.sx, box.cx), xMax = Math.max(box.sx, box.cx);
  const yMin = Math.min(box.sy, box.cy), yMax = Math.max(box.sy, box.cy);
  const found = [];
  plan.forEach((t, i) => {
    if (t.x >= xMin && t.x <= xMax && t.y >= yMin && t.y <= yMax) found.push(i);
  });
  return found;
}

/** The green set after a Shift-drag took in `inside`. */
export function afterMarquee(green, inside) {
  const next = new Set(green);
  if (!inside.length) return next;
  const allGreen = inside.every((i) => green.has(i));
  for (const i of inside) {
    if (allGreen) next.delete(i); else next.add(i);
  }
  return next;
}
