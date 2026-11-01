/**
 * Placing the target scan areas: the press samples what the gates let
 * through, then lays the fewest target tiles it can over that sample.
 *
 * The step has no work of its own on the instrument -- the page's runner
 * waits the rehearsal's moment and then calls `placingFinished`, which is
 * where the sampling and the placing happen.
 */

import { activeRecording } from "../../microscope/recordings.ts";
import { keptUnderCeiling } from "../../shared/gating.ts";
import type { TaPage, TaStep } from "../../types.ts";
import type { FoundObject } from "../../backend/verbs.ts";
import type { TilePlan } from "../../shared/run-document.ts";
import { planScanAreas } from "./scan-areas.ts";

/* Scan areas over the sampled targets, by the optimisation in
   scan-areas.ts under the levers the box holds. The sampled targets go
   in their systematic order, cells and all: the object's own size is what
   the margin is measured in. */
function placeTheScanAreas(page: TaPage): void {
  const state = page.run;
  const p = state.placing;
  /* The frame is the recording's, read here rather than remembered from
     the moment it was recorded: settings opened from a protocol were
     never recorded in this session and placed no tiles. */
  state.targetFrameUm = activeRecording(state.targetType)?.frameUm ?? null;
  const targets = [...state.restricted].flatMap((id) => (state.cells.has(id) ? [state.cells.get(id)!] : []));
  const byTileset = new Map<string | number, FoundObject[]>();
  for (const target of targets) {
    const tileset = page.tilesetOfField(target.field);
    if (!byTileset.has(tileset)) byTileset.set(tileset, []);
    byTileset.get(tileset)!.push(target); // set just above
  }
  /* Each overview tileset is planned on its own, so every target tile
     belongs to one tileset: a target near a border never shares a tile
     with a neighbour across it, and Step 9 can account for the tiles per
     tileset. */
  const plans = [...byTileset].map(([overviewTileset, group]) => ({
    overviewTileset,
    plan: planScanAreas(group, state.targetFrameUm, {
      margin: p.margin,
      minimise: p.minimise !== false,
      overlap: { min: p.overlapMin },
    }),
  }));
  const noteCounts = new Map<string, number>();
  for (const { plan: one } of plans) for (const note of one.notes) {
    noteCounts.set(note, (noteCounts.get(note) ?? 0) + 1);
  }
  const plan: TilePlan = {
    placed: plans.flatMap(({ overviewTileset, plan: one }) =>
      one.placed.map((tile) => ({ ...tile, overviewTileset }))),
    uncovered: plans.flatMap(({ plan: one }) => one.uncovered),
    leftOut: [],
    notes: [...noteCounts].map(([note, count]) => count > 1
      ? `${note} (${count} overview tilesets)` : note),
  };
  state.targetTiles = plan.placed.map((tile, positionIndex) => ({ ...tile, positionIndex }));
  plan.placed = state.targetTiles;
  state.tilePlan = plan;
}

/** The press samples, then places: a systematic uniform random sample of
    what the gates let through, so many per tileset, and scan areas over it
    by the optimisation under the box's levers. */
export function placingFinished(page: TaPage, s: TaStep): void {
  const state = page.run;
  const p = state.placing;
  state.restricted = keptUnderCeiling(
    state.cells.values(), state.gated, p.objectsMax ?? state.gated.size, page.tilesetOfField);
  placeTheScanAreas(page);
  const covered = state.restricted.size - (state.tilePlan?.uncovered?.length ?? 0);
  state.notes[s.id] = `${state.targetTiles.length} target tiles · ${covered} of ${state.restricted.size} sampled targets covered`;
  page.shown.gating?.redraw(); page.shown.selection?.redraw?.();
}
