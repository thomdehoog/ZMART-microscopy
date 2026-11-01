/**
 * The Discover Targets step's channel: the scatter the targets are gated on.
 *
 * The scatter is this step's own panel (`gate.ts`). It is handed what to
 * draw and what a gate means for the run; the handle it gives back is how
 * the page asks it to draw again.
 */

import { css, sizeCanvas, type Channel } from "zmart-interface/api";
import type { TaPage, TargetAcquisition } from "../../types.ts";
import { cellsInAllGates } from "../../shared/gating.ts";
import gatingPanel from "./gate.ts";

/** Two columns of a plot as they land: their names, the objects they are
    by, and the values of each column in the objects' order. */
interface Landed {
  columns: string[];
  ids: string[];
  values: number[][];
}

/** The gates have no press: looking at them applies them to the objects
    found on this sample, and that is the step settled. With no objects yet
    there is nothing to apply and it stays orange. */
export function gatesSettledByStanding(page: TaPage): void {
  const state = page.run;
  const i = page.indexOfStep("gate");
  const anOrangeStepBefore = page.steps().slice(0, i).some((s) => state.done.has(s.id) && state.stale.has(s.id));
  if (state.cells.size && state.gates.length && !anOrangeStepBefore) {
    state.gated = cellsInAllGates([...state.cells.values()], state.gates);
    state.done.add("gate");
    state.stale.delete("gate");
    page.shown.gating?.redraw();
  }
}

/** The masks showed the whole population; on the way to choosing from it
    the targets are the thing to look at, and every object lit under them
    hid which were chosen. The masks' eyes are pressed off for the operator,
    and stay in the strip for the way back. */
export function gatesArrived(page: TaPage): void {
  for (const mask of page.run.masks) mask.shown = false;
}

export const gatingChannel: Channel<TargetAcquisition> = {
  id: gatingPanel.id,
  label: gatingPanel.label,
  mount(host, page) {
    const state = page.run;
    page.shown.gating = gatingPanel.mount(host, {
      cells: () => state.cells.values(),
      gated: () => state.gated,
      gates: () => state.gates,
      cap: () => state.placing.objectsMax ?? Infinity,
      showing: () => state.cellsShown,
      setGates: (gates, ids) => {
        state.gates = gates;
        state.gated = ids;
        /* Something gated is what makes the gating step done; and a gate
           touched after Restrict is a selection not yet restricted, so the
           step after asks for its press again. */
        if (ids.size) state.done.add("gate"); else state.done.delete("gate");
        state.restricted = new Set();
        state.targetTiles = [];
        state.done.delete("select");
        state.ran.delete("select");
        page.stateEdited("gate");
        page.drawStage(); page.renderAll();
      },
      /* A dimensionality reduction over every candidate: its two columns
         land in each object's features by id, which is all the axis
         pickers need to offer them. Only the columns asked for: a UMAP
         also writes the components it stood on, which have a tick of
         their own. */
      computePlot: async (kind, wanted) => {
        const out = await page.backend.computePlot({ kind, ids: null });
        for (const { columns, ids: landed, values } of out.columns as Landed[]) {
          if (!columns.every((name) => wanted.includes(name))) continue;
          landed.forEach((id, i) => {
            const cell = state.cells.get(id);
            if (!cell) return;
            cell.features = { ...(cell.features ?? {}), [columns[0]]: values[0][i], [columns[1]]: values[1][i] };
          });
        }
        return out;
      },
      stopPlot: () => page.backend.stopPlot?.(),
      forgetColumns: (names) => {
        for (const cell of state.cells.values()) {
          if (!cell.features) continue;
          for (const name of names) delete cell.features[name];
        }
      },
      /* Whether Restrict has drawn under the ceiling: the plot then marks
         what it kept over what the gates let through. */
      restricted: () => state.restricted,
      sizeCanvas, css,
    });
  },
};
