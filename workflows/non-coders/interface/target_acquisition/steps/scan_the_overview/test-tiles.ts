/**
 * Which tiles a rectangle on the picture takes in, and what a Shift-drag over
 * them means for the green set.
 *
 * Pure, so the rule is tested without a canvas: a tile is inside when its
 * centre is; a drag over tiles that are all green already turns them off,
 * and over any other mix turns them all on -- one gesture, one answer, and
 * the second drag over the same tiles undoes the first. And which tiles the
 * box's two presses pick.
 */

import { sharePoints } from "../../shared/scanfields.ts";
import type { XY } from "../../shared/scanfields.ts";
import type { PlanTile } from "../../shared/run-document.ts";

/** A dragged rectangle: where the drag started and where the pointer is, in the plan's coordinates. */
export interface Marquee {
  sx: number;
  sy: number;
  cx: number;
  cy: number;
}

/** Plan indices of the tiles whose centre lies in the box. */
export function tilesInBox(plan: XY[], box: Marquee): number[] {
  const xMin = Math.min(box.sx, box.cx), xMax = Math.max(box.sx, box.cx);
  const yMin = Math.min(box.sy, box.cy), yMax = Math.max(box.sy, box.cy);
  const found: number[] = [];
  plan.forEach((t, i) => {
    if (t.x >= xMin && t.x <= xMax && t.y >= yMin && t.y <= yMax) found.push(i);
  });
  return found;
}

/** The green set after a Shift-drag took in `inside`. */
export function afterMarquee(green: Set<number>, inside: number[]): Set<number> {
  const next = new Set(green);
  if (!inside.length) return next;
  const allGreen = inside.every((i) => green.has(i));
  for (const i of inside) {
    if (allGreen) next.delete(i); else next.add(i);
  }
  return next;
}

/* So many tiles in each tileset, or so many over the whole carrier, spread
   the way Step 4 spreads its focus points: the ground is shared out by
   `sharePoints`, and each share takes the nearest tile not yet taken. Over
   the carrier the points are let off the middle of their shares when there
   is more than one tileset, as Step 4's are, so identical wells do not all
   give the same tile. Not a random draw -- the same press gives the same
   tiles (Thom, 2026-09-28). */
export function spreadTestTiles(plan: PlanTile[], n: number, over: "tileset" | "carrier"): number[] {
  const groups = new Map<string | number, number[]>();
  plan.forEach((t, i) => {
    const key = t.tileset ?? t.fieldId ?? "plan";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(i);
  });
  const vary = over === "carrier" && groups.size > 1;
  const held = over === "carrier" ? [plan.map((_, i) => i)] : [...groups.values()];
  const chosen: number[] = [];
  for (const these of held) {
    const taken = new Set<number>();
    for (const p of sharePoints(these.map((i) => plan[i]), n, { vary })) {
      let best: { i: number; d: number } | null = null;
      for (const i of these) {
        if (taken.has(i)) continue;
        const d = Math.hypot(plan[i].x - p.x, plan[i].y - p.y);
        if (!best || d < best.d) best = { i, d };
      }
      if (best) { taken.add(best.i); chosen.push(best.i); }
    }
  }
  return chosen;
}
