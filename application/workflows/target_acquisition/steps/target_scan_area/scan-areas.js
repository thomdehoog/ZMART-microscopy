/**
 * Placing scan areas round sampled targets, under a maximum overlap.
 *
 * Every sampled target gets a scan area of the settings' frame centred on
 * it -- unless that area would overlap one already placed by more than the
 * operator's maximum, as a share of the area's own extent. Two targets a
 * few micrometres apart would otherwise be imaged twice for one frame's
 * worth of tissue. The targets are walked in the order they were sampled,
 * so the first of two neighbours keeps its area and the second is left to
 * the first's. Pure, so it is pinned without a page.
 */

/** The share of one square frame covered by another of the same size. */
export function overlapShare(a, b, frameUm) {
  const ix = Math.max(0, frameUm - Math.abs(a.x - b.x));
  const iy = Math.max(0, frameUm - Math.abs(a.y - b.y));
  return (ix * iy) / (frameUm * frameUm);
}

/**
 * The scan areas to place: `[{ id, x, y, frameUm }]`, and the ids left out
 * because their area would overlap a placed one by more than `maxOverlap`
 * (a fraction, 0 to 1).
 */
export function placeScanAreas(targets, frameUm, maxOverlap) {
  const placed = [];
  const skipped = [];
  for (const target of targets) {
    const crowded = placed.some((one) => overlapShare(one, target, frameUm) > maxOverlap);
    if (crowded) skipped.push(target.id);
    else placed.push({ id: target.id, x: target.x, y: target.y, frameUm });
  }
  return { placed, skipped };
}
