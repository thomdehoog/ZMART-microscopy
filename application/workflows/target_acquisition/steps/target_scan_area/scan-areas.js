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
 * The levers are deliberately few:
 *   margin    the ring, as a fraction of the object's reach
 *   minimise  whether to look for the fewest tiles that cover every
 *             target (on), or simply to centre one tile on each (off)
 *   overlap.min the fixed stitching overlap wherever one target needs
 *             several tiles
 *
 * With minimising on, placing searches the useful candidate areas for the
 * smallest set that covers every target, and equal-size plans are settled
 * by the least reacquired ground. With it off, every target gets a tile of
 * its own, centred on it, however the tiles overlap. Either way a target
 * larger than a frame is covered by the same fixed-overlap raster Step 3
 * uses for a drawn tileset, and every sampled target is covered: the
 * operator bounds the work by how many targets are sampled.
 *
 * Pure, so every rule is pinned without a page.
 */

import { tiles as tilesOver } from "../../shared/scanfields.js";

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

/**
 * Whether the union of several frame rectangles covers the complete square
 * footprint requested for a target. This is deliberately independent of an
 * area's `covers` labels: those labels explain association, but cannot be the
 * evidence from which the coverage summary is calculated.
 */
export function coveredByTiles(cell, areas, frameUm, margin) {
  const reach = reachUm(cell, margin);
  const wanted = {
    x0: cell.x - reach, x1: cell.x + reach,
    y0: cell.y - reach, y1: cell.y + reach,
  };
  const rectangles = areas.map((area) => {
    const half = (area.frameUm ?? frameUm) / 2;
    return { x0: area.x - half, x1: area.x + half, y0: area.y - half, y1: area.y + half };
  }).filter((area) => area.x1 >= wanted.x0 && area.x0 <= wanted.x1
    && area.y1 >= wanted.y0 && area.y0 <= wanted.y1);
  if (!rectangles.length) return false;
  if (reach <= 1e-9) {
    return rectangles.some((area) => cell.x >= area.x0 && cell.x <= area.x1
      && cell.y >= area.y0 && cell.y <= area.y1);
  }

  /* Coverage can change only at a frame edge. In every vertical slab between
     successive edges, merge the frames' y intervals and require them to span
     the target from bottom to top. */
  const xs = [...new Set([
    wanted.x0, wanted.x1,
    ...rectangles.flatMap((area) => [
      Math.max(wanted.x0, area.x0), Math.min(wanted.x1, area.x1),
    ]),
  ])].sort((a, b) => a - b);
  for (let i = 1; i < xs.length; i++) {
    if (xs[i] - xs[i - 1] <= 1e-9) continue;
    const x = (xs[i] + xs[i - 1]) / 2;
    const intervals = rectangles
      .filter((area) => area.x0 <= x && area.x1 >= x)
      .map((area) => [Math.max(wanted.y0, area.y0), Math.min(wanted.y1, area.y1)])
      .filter(([lo, hi]) => hi >= lo)
      .sort((a, b) => a[0] - b[0] || b[1] - a[1]);
    let through = wanted.y0;
    for (const [lo, hi] of intervals) {
      if (lo > through + 1e-9) break;
      through = Math.max(through, hi);
      if (through >= wanted.y1 - 1e-9) break;
    }
    if (through < wanted.y1 - 1e-9) return false;
  }
  return true;
}

/** The share of one square frame covered by another of the same size. */
export function overlapShare(a, b, frameUm) {
  const ix = Math.max(0, frameUm - Math.abs(a.x - b.x));
  const iy = Math.max(0, frameUm - Math.abs(a.y - b.y));
  return (ix * iy) / (frameUm * frameUm);
}

/**
 * The plan: `placed` areas, each with a unique acquisition key and the targets
 * it covers; `uncovered`, the sampled targets the placed tile union does not
 * hold; and `notes`, one sentence per limit that could not be honoured.
 */
export function planScanAreas(targets, frameUm, rules = {}) {
  /* A margin below nought would let an object hang out of its area, and a
     frame of nothing holds nothing: both are said rather than computed. */
  /* Omitted keeps the documented default. Explicit null is the UI switch
     being off, which means no extra ring around the object. */
  const margin = Math.max(0, Number(rules.margin === null ? 0 : rules.margin ?? 1) || 0);
  const overlap = rules.overlap ?? {};
  const minimise = rules.minimise !== false;
  /* Canonical input makes tile keys independent of the order in which
     fields happened to report their targets. */
  targets = [...targets].sort((a, b) => String(a.id).localeCompare(String(b.id))
    || a.x - b.x || a.y - b.y);
  if (!(frameUm > 0)) {
    return { placed: [], uncovered: targets.map((t) => t.id), leftOut: [], notes: ["no frame to place: import the target acquisition settings first"] };
  }

  const holds = (cell, area) => coveredBy(cell, area, frameUm, margin);
  const tooBig = (cell) => reachUm(cell, margin) * 2 > frameUm;
  const placed = [];
  const uncovered = [];
  const notes = [];
  const stitching = Math.min(0.9, Math.max(0, Number(overlap.min) || 0));
  const isCovered = (cell) => coveredByTiles(cell, placed, frameUm, margin);

  /* Only targets that individually need several frames enter the stitching
     path. Ordinary targets whose margins merely touch one of them remain in
     the minimum-tile cover below; they must not stretch a stitching raster
     across a whole cluster. */
  const stitched = stitchedBlocks(targets, frameUm, margin, stitching);
  const inAStitchedBlock = new Set(stitched.flatMap((one) => one.targets.map((target) => target.id)));
  for (const { tiles: block } of stitched) placed.push(...block);

  let exact = { areas: [], bounded: false };
  if (minimise) {
    /* Solve the cover itself: a locally attractive first tile can otherwise
       force two later tiles where another first choice would finish in one.
       The bounded fallback only matters for pathological very large
       components; its incumbent is still the best complete cover found,
       never a partial plan. */
    const pending = targets.filter((target) => !inAStitchedBlock.has(target.id)
      && !tooBig(target) && !isCovered(target));
    const pool = candidateAreas(pending, frameUm, margin);
    exact = minimumAreaCover(pending, pool, placed, frameUm);
    placed.push(...exact.areas);
    /* Once a minimum-count cover is chosen, ordinary tiles may slide
       anywhere inside the common feasible rectangle of the targets they
       promise to hold. Use that freedom to reduce reacquired ground without
       changing the tile count or coverage. Stitched tiles have no feasible
       rectangle here: their fixed Step 3 lattice and overlap remain
       untouched. */
    minimiseRepeatedGround(placed, targets, frameUm, margin);
  } else {
    /* The plain way: one tile on every ordinary target, centred on it. Two
       neighbours each get their own tile even where one would hold both;
       that is the point of the switch being off. */
    for (const target of targets) {
      if (inAStitchedBlock.has(target.id) || tooBig(target)) continue;
      placed.push({ id: target.id, x: target.x, y: target.y, covers: [target.id] });
    }
  }
  /* Recompute coverage from the final union of the rectangles actually being
     drawn and acquired. Candidate labels are useful metadata, but cannot be
     the authority: some footprints are completed jointly by adjacent tiles. */
  const verifiedMissing = targets.filter((target) =>
    !coveredByTiles(target, placed, frameUm, margin)).map((target) => target.id);
  uncovered.splice(0, uncovered.length, ...verifiedMissing);
  /* Preserve the contributing-target labels of a stitched tile, and add any
     ordinary targets that it happens to contain whole. This metadata remains
     descriptive; verifiedMissing above is the coverage authority. */
  for (const tile of placed) {
    const held = targets.filter((target) => holds(target, tile)).map((target) => target.id);
    tile.covers = [...new Set([...(tile.covers ?? []), ...held])];
    tile.completes = [];
    delete tile.feasible;
    delete tile.ordinaryGroup;
    delete tile.groupSize;
  }
  /* Credit each target on the first acquisition prefix whose real union
     completes it. This includes a footprint split across adjacent tiles and
     delays a stitched target's acquired state until its final required tile.
     `covers` remains useful row metadata, so a jointly completed target is
     also named on the tile that completes it. */
  for (const target of targets) {
    for (let at = 0; at < placed.length; at++) {
      if (!coveredByTiles(target, placed.slice(0, at + 1), frameUm, margin)) continue;
      placed[at].completes.push(target.id);
      if (!placed.some((tile) => tile.covers.includes(target.id))) {
        placed[at].covers.push(target.id);
      }
      break;
    }
  }

  /* A target id identifies biology, not an acquisition. A large target has
     several tiles, so every tile gets its own stable key for Step 9. */
  const tileNumber = new Map();
  for (const tile of placed) {
    const targetId = tile.targetId ?? tile.id ?? tile.covers[0];
    const tileIndex = tileNumber.get(targetId) ?? 0;
    tileNumber.set(targetId, tileIndex + 1);
    tile.targetId = targetId;
    tile.tileIndex = tileIndex;
    tile.key = `${targetId}#${tileIndex}`;
  }

  if (exact.bounded) notes.push("minimum-tile search reached its limit; using the best complete cover found");
  if (uncovered.length) {
    notes.push(`${uncovered.length} targets are not covered by the placed tile geometry`);
  }
  return { placed, uncovered, leftOut: [], notes };
}

/**
 * A minimum-cardinality set cover for ordinary targets.
 *
 * Candidate generation is geometric; this search is combinatorial. It starts
 * with a complete greedy cover as an upper bound, then proves away smaller
 * alternatives component by component. For an unusually tangled component a
 * search budget keeps the UI responsive and returns the best complete cover
 * seen so far. In normal microscopy clusters the components are small and the
 * result is the exact minimum.
 */
function minimumAreaCover(targets, pool, fixed, frameUm) {
  if (!targets.length) return { areas: [], bounded: false };
  const byId = new Map(targets.map((target) => [target.id, []]));
  pool.forEach((area) => area.covers.forEach((id) => byId.get(id)?.push(area)));

  /* No candidate crosses these components, so their minimum tile counts add.
     Keeping the search separate is the difference between several small
     microscopy clusters and one exponential problem the size of the plate. */
  const unseen = new Set(targets.map((target) => target.id));
  const components = [];
  while (unseen.size) {
    const first = unseen.values().next().value;
    unseen.delete(first);
    const ids = new Set([first]);
    const areas = new Set();
    const queue = [first];
    while (queue.length) {
      const id = queue.pop();
      for (const area of byId.get(id) ?? []) {
        if (areas.has(area)) continue;
        areas.add(area);
        for (const covered of area.covers) {
          if (!unseen.has(covered)) continue;
          unseen.delete(covered);
          ids.add(covered);
          queue.push(covered);
        }
      }
    }
    components.push({ ids: [...ids], areas: [...areas] });
  }

  const chosen = [];
  let bounded = false;
  for (const component of components) {
    const outcome = minimumComponentCover(component.ids, component.areas,
      [...fixed, ...chosen], frameUm);
    chosen.push(...outcome.areas);
    bounded ||= outcome.bounded;
  }
  return { areas: chosen, bounded };
}

const EXACT_COVER_VISITS = 250000;

function minimumComponentCover(ids, areas, fixed, frameUm) {
  const bitOf = new Map(ids.map((id, i) => [id, 1n << BigInt(i)]));
  const candidates = areas.map((area, order) => ({
    area,
    order,
    mask: area.covers.reduce((mask, id) => mask | (bitOf.get(id) ?? 0n), 0n),
  })).filter((one) => one.mask);
  const full = (1n << BigInt(ids.length)) - 1n;
  const byBit = ids.map((_, i) => candidates.filter((one) =>
    (one.mask & (1n << BigInt(i))) !== 0n));
  const count = (mask) => {
    let many = 0;
    for (let left = mask; left; left &= left - 1n) many += 1;
    return many;
  };
  const extraOverlap = (candidate, selected) =>
    [...fixed, ...selected].reduce((sum, area) =>
      sum + overlapShare(area, candidate.area, frameUm), 0);

  /* A complete incumbent means hitting the search budget can only affect
     optimality, never coverage. */
  let left = full;
  const greedy = [];
  while (left) {
    const best = candidates.map((candidate) => ({
      candidate,
      gain: count(candidate.mask & left),
      overlap: extraOverlap(candidate, greedy.map((one) => one.area)),
    })).filter((one) => one.gain)
      .sort((a, b) => b.gain - a.gain || a.overlap - b.overlap
        || a.candidate.order - b.candidate.order)[0];
    if (!best) return { areas: [], bounded: false };
    greedy.push(best.candidate);
    left &= ~best.candidate.mask;
  }

  let best = greedy;
  let bestOverlap = repeatedOverlap(best.map((one) => one.area), fixed, frameUm);
  let visits = 0;
  let bounded = false;
  const shallowest = new Map();
  const search = (uncovered, selected) => {
    if (++visits > EXACT_COVER_VISITS) { bounded = true; return; }
    if (!uncovered) {
      const overlap = repeatedOverlap(selected.map((one) => one.area), fixed, frameUm);
      if (selected.length < best.length
        || (selected.length === best.length && overlap < bestOverlap - 1e-9)) {
        best = [...selected];
        bestOverlap = overlap;
      }
      return;
    }
    if (selected.length >= best.length) return;
    const seenAt = shallowest.get(uncovered);
    if (seenAt != null && seenAt <= selected.length) return;
    shallowest.set(uncovered, selected.length);

    let maxGain = 0;
    for (const candidate of candidates) maxGain = Math.max(maxGain, count(candidate.mask & uncovered));
    if (!maxGain || selected.length + Math.ceil(count(uncovered) / maxGain) > best.length) return;

    /* Branch on the target with the fewest possible tiles. It fails an
       impossible branch early and keeps the usual search very small. */
    let choices = null;
    for (let i = 0; i < ids.length; i++) {
      if (!(uncovered & (1n << BigInt(i)))) continue;
      const holding = byBit[i].filter((candidate) => candidate.mask & uncovered);
      if (choices == null || holding.length < choices.length) choices = holding;
    }
    choices = (choices ?? []).map((candidate) => ({
      candidate,
      gain: count(candidate.mask & uncovered),
      overlap: extraOverlap(candidate, selected.map((one) => one.area)),
    })).sort((a, b) => b.gain - a.gain || a.overlap - b.overlap
      || a.candidate.order - b.candidate.order);
    for (const { candidate } of choices) {
      selected.push(candidate);
      search(uncovered & ~candidate.mask, selected);
      selected.pop();
    }
  };
  search(full, []);
  return { areas: best.map((one) => ({ ...one.area })), bounded };
}

/**
 * Actual ground acquired more than once, used only to settle equal tile
 * counts. Total frame area minus rectangle-union area counts a pixel twice
 * when three frames cover it, rather than the three times a pairwise sum does.
 */
export function repeatedOverlap(areas, fixed = [], frameUm) {
  const all = [...fixed, ...areas];
  if (all.length < 2) return 0;
  const rectangles = all.map((area) => {
    const side = area.frameUm ?? frameUm;
    const half = side / 2;
    return {
      x0: area.x - half, x1: area.x + half,
      y0: area.y - half, y1: area.y + half,
      area: side * side,
    };
  });
  const xs = [...new Set(rectangles.flatMap((area) => [area.x0, area.x1]))]
    .sort((a, b) => a - b);
  let union = 0;
  for (let i = 1; i < xs.length; i++) {
    const width = xs[i] - xs[i - 1];
    if (width <= 1e-9) continue;
    const x = (xs[i] + xs[i - 1]) / 2;
    const intervals = rectangles.filter((area) => area.x0 < x && area.x1 > x)
      .map((area) => [area.y0, area.y1])
      .sort((a, b) => a[0] - b[0] || b[1] - a[1]);
    let height = 0;
    let lo = null, hi = null;
    for (const [nextLo, nextHi] of intervals) {
      if (lo === null) { lo = nextLo; hi = nextHi; continue; }
      if (nextLo > hi) {
        height += hi - lo;
        lo = nextLo; hi = nextHi;
      } else hi = Math.max(hi, nextHi);
    }
    if (lo !== null) height += hi - lo;
    union += width * height;
  }
  return rectangles.reduce((sum, area) => sum + area.area, 0) - union;
}

/** Area of one tile that is already covered by the union of all other tiles. */
function overlapWithUnion(tile, others, frameUm) {
  const side = tile.frameUm ?? frameUm;
  const half = side / 2;
  const bounds = { x0: tile.x - half, x1: tile.x + half,
    y0: tile.y - half, y1: tile.y + half };
  const clipped = others.map((other) => {
    const otherHalf = (other.frameUm ?? frameUm) / 2;
    return {
      x0: Math.max(bounds.x0, other.x - otherHalf),
      x1: Math.min(bounds.x1, other.x + otherHalf),
      y0: Math.max(bounds.y0, other.y - otherHalf),
      y1: Math.min(bounds.y1, other.y + otherHalf),
    };
  }).filter((area) => area.x1 > area.x0 && area.y1 > area.y0);
  const xs = [...new Set(clipped.flatMap((area) => [area.x0, area.x1]))]
    .sort((a, b) => a - b);
  let union = 0;
  for (let i = 1; i < xs.length; i++) {
    const width = xs[i] - xs[i - 1];
    if (width <= 1e-9) continue;
    const x = (xs[i] + xs[i - 1]) / 2;
    const intervals = clipped.filter((area) => area.x0 < x && area.x1 > x)
      .map((area) => [area.y0, area.y1])
      .sort((a, b) => a[0] - b[0] || b[1] - a[1]);
    let lo = null, hi = null;
    for (const [nextLo, nextHi] of intervals) {
      if (lo == null) { lo = nextLo; hi = nextHi; continue; }
      if (nextLo > hi) { union += width * (hi - lo); lo = nextLo; hi = nextHi; }
      else hi = Math.max(hi, nextHi);
    }
    if (lo != null) union += width * (hi - lo);
  }
  return union;
}

/**
 * Slide ordinary chosen tiles within their coverage-safe seats. Coordinate
 * breakpoints are the feasible edges and the points where another frame just
 * stops overlapping. Coverage of every target held before optimisation is
 * checked against the complete tile union after every trial move. That global
 * check matters when two neighbouring tiles each hold only part of a large
 * requested footprint.
 */
function minimiseRepeatedGround(placed, targets, frameUm, margin) {
  const movable = placed.filter((tile) => tile.feasible);
  const mustRemainCovered = targets.filter((target) =>
    coveredByTiles(target, placed, frameUm, margin));
  const clipped = (value, lo, hi) => Math.max(lo, Math.min(hi, value));
  const seatsFor = (tile, axis, others, affectedTargets) => {
    const lo = tile.feasible[`${axis}0`];
    const hi = tile.feasible[`${axis}1`];
    const side = tile.frameUm ?? frameUm;
    const seats = [tile[axis], lo, hi];
    for (const other of others) {
      const reach = (side + (other.frameUm ?? frameUm)) / 2;
      seats.push(clipped(other[axis] - reach, lo, hi), clipped(other[axis] + reach, lo, hi));
    }
    /* A union-coverage transition occurs when this tile edge meets a target
       footprint edge. Include those seats as well as overlap breakpoints. */
    const half = side / 2;
    for (const target of affectedTargets) {
      const reach = reachUm(target, margin);
      seats.push(
        clipped(target[axis] - reach - half, lo, hi),
        clipped(target[axis] - reach + half, lo, hi),
        clipped(target[axis] + reach - half, lo, hi),
        clipped(target[axis] + reach + half, lo, hi),
      );
    }
    return [...new Set(seats)].sort((a, b) => a - b);
  };
  for (let pass = 0; pass < 6; pass++) {
    let changed = false;
    for (const tile of movable) {
      const others = placed.filter((one) => one !== tile);
      const tileSide = tile.frameUm ?? frameUm;
      const possibleHalf = tileSide / 2;
      const interacts = (other) => {
        const reach = (tileSide + (other.frameUm ?? frameUm)) / 2;
        const closest = (axis) => other[axis] < tile.feasible[`${axis}0`]
          ? tile.feasible[`${axis}0`] - other[axis]
          : other[axis] > tile.feasible[`${axis}1`]
            ? other[axis] - tile.feasible[`${axis}1`] : 0;
        return closest("x") < reach - 1e-9 && closest("y") < reach - 1e-9;
      };
      const neighbours = others.filter(interacts);
      const affectedTargets = mustRemainCovered.filter((target) => {
        const reach = reachUm(target, margin);
        return target.x + reach >= tile.feasible.x0 - possibleHalf
          && target.x - reach <= tile.feasible.x1 + possibleHalf
          && target.y + reach >= tile.feasible.y0 - possibleHalf
          && target.y - reach <= tile.feasible.y1 + possibleHalf;
      });
      const localCoverageIsSafe = () => affectedTargets.every((target) =>
        coveredByTiles(target, placed, frameUm, margin));
      let best = { x: tile.x, y: tile.y };
      let bestScore = overlapWithUnion(tile, neighbours, frameUm);
      const before = { x: tile.x, y: tile.y };
      const canInteract = neighbours.length > 0;
      /* Testing the Cartesian product is intentional. Some triple-overlap
         layouts improve only when both coordinates move together; pairwise
         or axis-at-a-time scores can prefer the wrong seat. */
      for (const x of seatsFor(tile, "x", neighbours, affectedTargets)) {
        for (const y of seatsFor(tile, "y", neighbours, affectedTargets)) {
          tile.x = x; tile.y = y;
          const score = overlapWithUnion(tile, neighbours, frameUm);
          const improves = score < bestScore - 1e-9;
          /* A deterministic move across a flat part of the objective lets a
             later tile expose a joint improvement (two rectangles can have
             to separate together before their overlap decreases). */
          const advancesOnPlateau = canInteract && Math.abs(score - bestScore) <= 1e-9
            && (x > best.x + 1e-9
              || (Math.abs(x - best.x) <= 1e-9 && y > best.y + 1e-9));
          if ((improves || advancesOnPlateau) && localCoverageIsSafe()) {
            best = { x, y };
            bestScore = score;
          }
        }
      }
      tile.x = before.x; tile.y = before.y;
      if (Math.abs(best.x - tile.x) > 1e-9 || Math.abs(best.y - tile.y) > 1e-9) {
        tile.x = best.x; tile.y = best.y;
        changed = true;
      }
    }
    if (!changed) break;
  }
}

/**
 * Targets that individually need several frames, covered on the same
 * fixed-step raster as a region in Step 3. Connected oversized footprints may
 * share that lattice; ordinary targets never enlarge it merely because their
 * margins touch.
 */
function stitchedBlocks(targets, frameUm, margin, stitching) {
  const withBox = targets.map((target) => {
    const reach = reachUm(target, margin);
    return {
      target,
      reach,
      x0: target.x - reach,
      x1: target.x + reach,
      y0: target.y - reach,
      y1: target.y + reach,
    };
  }).filter((one) => one.reach * 2 > frameUm);
  const touches = (a, b) => a.x0 <= b.x1 && a.x1 >= b.x0
    && a.y0 <= b.y1 && a.y1 >= b.y0;
  const left = new Set(withBox.map((_, i) => i));
  const components = [];
  while (left.size) {
    const first = left.values().next().value;
    left.delete(first);
    const component = [];
    const queue = [first];
    while (queue.length) {
      const at = queue.pop();
      component.push(withBox[at]);
      for (const other of [...left]) {
        if (!touches(withBox[at], withBox[other])) continue;
        left.delete(other);
        queue.push(other);
      }
    }
    components.push(component);
  }

  const half = frameUm / 2;
  return components.map((component) => {
    const x0 = Math.min(...component.map((one) => one.x0));
    const x1 = Math.max(...component.map((one) => one.x1));
    const y0 = Math.min(...component.map((one) => one.y0));
    const y1 = Math.max(...component.map((one) => one.y1));
    const field = {
      type: "rectangle",
      /* scanfields rectangles store their top-left corner, not their centre.
         Passing the centre here displaced every margin-enabled raster by half
         its width and height while its optimistic labels still said covered. */
      x: x0,
      y: y0,
      w: x1 - x0,
      h: y1 - y0,
    };
    const targetsInBlock = component.map((one) => one.target);
    const tiles = tilesOver(field, frameUm, stitching * 100)
      .map((at) => ({
        at,
        covers: component.filter((one) => Math.abs(one.target.x - at.x) <= half + one.reach
          && Math.abs(one.target.y - at.y) <= half + one.reach),
      }))
      /* The bounding rectangle supplies one common lattice; tiles touching
         none of the actual target footprints are the empty corners and gaps. */
      .filter((one) => one.covers.length)
      .map(({ at, covers }, tileIndex) => ({
        id: covers[0].target.id,
        targetId: covers[0].target.id,
        tileIndex,
        x: at.x,
        y: at.y,
        frameUm,
        covers: covers.map((one) => one.target.id),
      }));
    return { targets: targetsInBlock, tiles };
  });
}

/**
 * Every materially different area that can hold one or more targets whole.
 *
 * A target defines the rectangle in which an area's centre may sit while
 * preserving its margin. The set of targets covered can only change where
 * one of those rectangles starts or ends, so crossing all x/y boundaries
 * finds every useful shared-frame combination without searching arbitrary
 * pixels. Disconnected groups are crossed separately, keeping the ordinary
 * cost close to quadratic clusters rather than the whole experiment.
 */
function candidateAreas(targets, frameUm, margin) {
  const half = frameUm / 2;
  const ranged = targets.map((target, order) => {
    const slack = half - reachUm(target, margin);
    return {
      target,
      order,
      x0: target.x - slack,
      x1: target.x + slack,
      y0: target.y - slack,
      y1: target.y + slack,
    };
  });
  const meets = (a, b) => a.x0 <= b.x1 && a.x1 >= b.x0
    && a.y0 <= b.y1 && a.y1 >= b.y0;
  const left = new Set(ranged.map((_, i) => i));
  const groups = [];
  while (left.size) {
    const first = left.values().next().value;
    left.delete(first);
    const group = [];
    const queue = [first];
    while (queue.length) {
      const at = queue.pop();
      group.push(ranged[at]);
      for (const other of [...left]) {
        if (!meets(ranged[at], ranged[other])) continue;
        left.delete(other);
        queue.push(other);
      }
    }
    groups.push(group);
  }

  const out = [];
  for (const group of groups) {
    const ordinaryGroup = group.map((one) => one.target.id).sort().join("\u0000");
    const xs = [...new Set(group.flatMap((one) => [one.x0, one.x1]))];
    const ys = [...new Set(group.flatMap((one) => [one.y0, one.y1]))];
    const combinations = new Map();
    for (const x of xs) {
      for (const y of ys) {
        const held = group.filter((one) => x >= one.x0 && x <= one.x1
          && y >= one.y0 && y <= one.y1);
        if (!held.length) continue;
        const key = held.map((one) => one.order).sort((a, b) => a - b).join(",");
        if (!combinations.has(key)) combinations.set(key, held);
      }
    }
    const seated = new Map();
    for (const firstHeld of combinations.values()) {
      /* Seat the frame near the targets rather than at an arbitrary boundary
         that happened to reveal this combination. Reseating may take in an
         extra target; include it and centre again until the set settles. */
      let held = firstHeld;
      let x = 0, y = 0;
      for (let pass = 0; pass <= group.length; pass++) {
        const x0 = Math.max(...held.map((one) => one.x0));
        const x1 = Math.min(...held.map((one) => one.x1));
        const y0 = Math.max(...held.map((one) => one.y0));
        const y1 = Math.min(...held.map((one) => one.y1));
        const meanX = held.reduce((sum, one) => sum + one.target.x, 0) / held.length;
        const meanY = held.reduce((sum, one) => sum + one.target.y, 0) / held.length;
        x = Math.min(x1, Math.max(x0, meanX));
        y = Math.min(y1, Math.max(y0, meanY));
        const expanded = group.filter((one) => x >= one.x0 && x <= one.x1
          && y >= one.y0 && y <= one.y1);
        if (expanded.length === held.length
          && expanded.every((one) => held.includes(one))) break;
        held = expanded;
      }
      const covers = held.map((one) => one.target.id);
      const key = held.map((one) => one.order).sort((a, b) => a - b).join(",");
      if (!seated.has(key)) seated.set(key, {
        id: covers[0], targetId: covers[0], x, y, frameUm, covers,
        ordinaryGroup, groupSize: group.length,
        feasible: {
          x0: Math.max(...held.map((one) => one.x0)),
          x1: Math.min(...held.map((one) => one.x1)),
          y0: Math.max(...held.map((one) => one.y0)),
          y1: Math.min(...held.map((one) => one.y1)),
        },
      });
    }
    out.push(...seated.values());
  }
  return out;
}
