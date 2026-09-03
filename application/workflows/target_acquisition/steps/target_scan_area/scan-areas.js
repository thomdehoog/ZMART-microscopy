/**
 * Placing scan areas over sampled targets: the optimisation, and its levers.
 *
 * A target counts as covered by a scan area only when it lies inside it
 * with a margin round it -- and the margin is in the target's own size.
 * The size is the object's longest reach: half the major axis of the
 * ellipse fitted to it, which the detector reports for every object.
 * Call that 100 %; a margin of 100 % is a ring one reach wide. Pixels
 * are not a stable measure and micrometres are hard to hold in the head;
 * the object's own size is both, and the longest reach holds the object
 * whole whichever way it lies.
 *
 * The levers, each switchable:
 *   margin    the ring, as a fraction of the object's reach
 *   areas     { min, max } scan areas, either null
 *   overlap   { max, min } as shares of a frame, either null. Two areas
 *             that meet must meet by at least the minimum -- an area that
 *             would overlap a neighbour by less is slid to meet it by
 *             exactly that, where sliding still holds its targets -- so
 *             every seam is one that can be stitched. `join` asks for one
 *             contiguous scan over the sampled targets, stepped by the
 *             minimum overlap, instead of scattered areas
 *   prefer    when the maximum number of areas and covering every sampled
 *             target cannot both hold: "coverage" places on past the
 *             maximum and says so; "areas" stops and says which targets
 *             were left uncovered
 *
 * Scattered placing walks the sampled targets in their systematic order. A
 * target already covered is passed over; an uncovered one gets an area
 * nudged to take in whichever uncovered neighbours fit in one frame beside
 * it. An area that would overlap a placed one by more than the maximum is
 * not placed, and its target is left uncovered.
 *
 * Pure, so every rule is pinned without a page.
 */

/** Micrometres per pixel for one object: its area is known in both. */
function pixelUmOf(cell) {
  const px = Number(cell.features?.area);
  const um = Number(cell.area);
  return px > 0 && um > 0 ? Math.sqrt(um / px) : 1;
}

/**
 * The object's longest reach in micrometres, before any margin: half the
 * fitted ellipse's major axis. An object that reports none falls back to
 * the radius of a disc of its area, which every object has.
 */
export function objectReachUm(cell) {
  const major = Number(cell.features?.axis_major_length);
  if (Number.isFinite(major) && major > 0) return (major / 2) * pixelUmOf(cell);
  const area = Number(cell.area);
  return area > 0 ? Math.sqrt(area / Math.PI) : 0;
}

/** How far a target reaches with its margin: what an area must hold whole. */
export const reachUm = (cell, margin) => objectReachUm(cell) * (1 + margin);

/** Whether an area centred at `area` holds the target whole, margin and all. */
export function coveredBy(cell, area, frameUm, margin) {
  const reach = reachUm(cell, margin);
  return Math.abs(cell.x - area.x) + reach <= frameUm / 2
    && Math.abs(cell.y - area.y) + reach <= frameUm / 2;
}

/** The share of one square frame covered by another of the same size. */
export function overlapShare(a, b, frameUm) {
  const ix = Math.max(0, frameUm - Math.abs(a.x - b.x));
  const iy = Math.max(0, frameUm - Math.abs(a.y - b.y));
  return (ix * iy) / (frameUm * frameUm);
}

/**
 * The plan: `placed` areas, each with the targets it covers; `uncovered`,
 * the sampled targets no area holds; `leftOut`, those whose area was
 * refused for overlap; and `notes`, one sentence per lever that could not
 * be honoured.
 */
export function planScanAreas(targets, frameUm, rules = {}) {
  /* A margin below nought would let an object hang out of its area, and a
     frame of nothing holds nothing: both are said rather than computed. */
  const margin = Math.max(0, Number(rules.margin ?? 1) || 0);
  const areas = rules.areas ?? {};
  const overlap = rules.overlap ?? {};
  const prefer = rules.prefer ?? "coverage";
  if (!(frameUm > 0)) {
    return { placed: [], uncovered: targets.map((t) => t.id), leftOut: [], notes: ["no frame to place: import the target acquisition settings first"] };
  }
  if (overlap.join && overlap.min != null) return joinedPlan(targets, frameUm, margin, areas, overlap);

  const holds = (cell, area) => coveredBy(cell, area, frameUm, margin);
  const tooBig = (cell) => reachUm(cell, margin) * 2 > frameUm;
  const placed = [];
  const uncovered = [];
  const leftOut = [];
  const notes = [];
  const isCovered = (cell) => placed.some((area) => holds(cell, area));
  let stopped = false;
  let oversized = 0;
  let thinSeams = 0;
  for (const target of targets) {
    if (isCovered(target)) continue;
    if (tooBig(target)) { oversized += 1; uncovered.push(target.id); continue; }
    if (areas.max != null && placed.length >= areas.max && prefer === "areas") {
      stopped = true;
      uncovered.push(target.id);
      continue;
    }
    const neighbours = targets.filter((one) => one !== target && !tooBig(one) && !isCovered(one));
    const area = nudged(target, neighbours, frameUm, margin);
    if (overlap.max != null && placed.some((one) => overlapShare(one, area, frameUm) > overlap.max)) {
      leftOut.push(target.id);
      uncovered.push(target.id);
      continue;
    }
    if (overlap.min != null && overlap.min > 0) {
      const met = meetingByAtLeast(area, placed, frameUm, overlap.min, overlap.max, (at) => holds(target, at));
      if (met) { area.x = met.x; area.y = met.y; } else thinSeams += 1;
    }
    area.covers = targets.filter((one) => holds(one, area)).map((one) => one.id);
    placed.push(area);
  }
  if (thinSeams) notes.push(`${thinSeams} areas meet a neighbour by less than the minimum overlap`);
  if (stopped) notes.push(`stopped at ${areas.max} scan areas: ${uncovered.length} sampled targets are not covered`);
  else if (areas.max != null && placed.length > areas.max) notes.push(`${placed.length} scan areas, past the maximum of ${areas.max}, to cover every sampled target`);
  if (areas.min != null && placed.length < areas.min) notes.push(`${placed.length} scan areas, under the minimum of ${areas.min}: every sampled target is covered already`);
  if (oversized) notes.push(`${oversized} sampled targets are larger than a frame with their margin`);
  if (leftOut.length) notes.push(`${leftOut.length} left out for overlap`);
  return { placed, uncovered, leftOut, notes };
}

/**
 * Where two areas meet they meet by at least the minimum: an area that
 * overlaps a placed one by more than nothing and less than the minimum
 * is slid along one axis until the overlap is exactly the minimum --
 * towards the neighbour, so nothing between them is left out -- provided
 * the slid area still holds its anchor and overlaps no other placed area
 * past the maximum. The first slide that holds wins; none holding, the
 * area stays and the seam is counted as thin. Areas that do not meet at
 * all are left alone: nothing joins them.
 */
function meetingByAtLeast(area, placed, frameUm, min, max, stillHolds) {
  const thin = placed.filter((one) => {
    const share = overlapShare(one, area, frameUm);
    return share > 0 && share < min;
  });
  if (!thin.length) return area;
  const fine = (at) => stillHolds(at)
    && placed.every((one) => {
      const share = overlapShare(one, at, frameUm);
      return (share === 0 || share >= min - 1e-9) && (max == null || share <= max + 1e-9);
    });
  for (const one of thin) {
    const dx = Math.abs(area.x - one.x), dy = Math.abs(area.y - one.y);
    const ix = Math.max(0, frameUm - dx), iy = Math.max(0, frameUm - dy);
    const tries = [];
    if (iy > 0) {
      const wantedIx = (min * frameUm * frameUm) / iy;
      if (wantedIx <= frameUm) tries.push({ x: one.x + Math.sign(area.x - one.x || 1) * (frameUm - wantedIx), y: area.y });
    }
    if (ix > 0) {
      const wantedIy = (min * frameUm * frameUm) / ix;
      if (wantedIy <= frameUm) tries.push({ x: area.x, y: one.y + Math.sign(area.y - one.y || 1) * (frameUm - wantedIy) });
    }
    for (const at of tries) {
      if (fine(at)) return { x: at.x, y: at.y };
    }
  }
  return null;
}

/**
 * An area round `target` nudged to take in uncovered neighbours: the box
 * holding the target with its margin grows by the nearest neighbour while
 * the grown box still fits in one frame, and the area is centred on what
 * it holds. Grown nearest-first, so a crowd is taken in from the middle.
 */
function nudged(target, neighbours, frameUm, margin) {
  const boxOf = (cell) => {
    const r = reachUm(cell, margin);
    return { x0: cell.x - r, y0: cell.y - r, x1: cell.x + r, y1: cell.y + r };
  };
  const union = (a, b) => ({
    x0: Math.min(a.x0, b.x0), y0: Math.min(a.y0, b.y0), x1: Math.max(a.x1, b.x1), y1: Math.max(a.y1, b.y1),
  });
  const fits = (b) => b.x1 - b.x0 <= frameUm && b.y1 - b.y0 <= frameUm;
  let box = boxOf(target);
  const near = neighbours
    .map((one) => ({ one, d: Math.hypot(one.x - target.x, one.y - target.y) }))
    .filter(({ d }) => d <= frameUm)
    .sort((a, b) => a.d - b.d);
  for (const { one } of near) {
    const grown = union(box, boxOf(one));
    if (fits(grown)) box = grown;
  }
  return { id: target.id, x: (box.x0 + box.x1) / 2, y: (box.y0 + box.y1) / 2, frameUm };
}

/**
 * One contiguous scan over the sampled targets: a grid stepped by the frame
 * less the minimum overlap, laid over the targets' extent with their
 * margins, every tile of it.
 */
function joinedPlan(targets, frameUm, margin, areas, overlap) {
  const placed = [];
  if (!targets.length) return { placed, uncovered: [], leftOut: [], notes: [] };
  /* Adjacent tiles overlap by the minimum, and never by more than nine
     tenths: a minimum of one would step by nothing and never end. */
  const step = frameUm * (1 - Math.min(0.9, Math.max(0, overlap.min)));
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const t of targets) {
    const r = reachUm(t, margin);
    x0 = Math.min(x0, t.x - r); y0 = Math.min(y0, t.y - r);
    x1 = Math.max(x1, t.x + r); y1 = Math.max(y1, t.y + r);
  }
  const cols = Math.max(1, Math.ceil((x1 - x0 - frameUm) / step) + 1);
  const rows = Math.max(1, Math.ceil((y1 - y0 - frameUm) / step) + 1);
  for (let j = 0; j < rows; j++) {
    for (let i = 0; i < cols; i++) {
      /* Every tile of the grid, held or not: one scan is one piece, and a
         gap where no target stands would be a gap in the piece. */
      const area = { x: x0 + frameUm / 2 + i * step, y: y0 + frameUm / 2 + j * step, frameUm };
      area.covers = targets.filter((t) => coveredBy(t, area, frameUm, margin)).map((t) => t.id);
      area.id = area.covers[0] ?? `scan-${j}-${i}`;
      placed.push(area);
    }
  }
  const covered = new Set(placed.flatMap((a) => a.covers));
  const uncovered = targets.filter((t) => !covered.has(t.id)).map((t) => t.id);
  const notes = [];
  if (areas.max != null && placed.length > areas.max) notes.push(`${placed.length} scan areas, past the maximum of ${areas.max}, to join into one scan`);
  if (uncovered.length) notes.push(`${uncovered.length} sampled targets are not held whole with their margin`);
  return { placed, uncovered, leftOut: [], notes };
}
