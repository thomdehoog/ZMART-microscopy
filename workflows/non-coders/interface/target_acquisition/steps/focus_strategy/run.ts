/**
 * Measuring the focus map: the one step that drives the stage must finish
 * on its promise, not on a rehearsal timer. Finishing first marked the map
 * done -- and the rail green -- before the objective had moved, and kept it
 * done when the run failed on the instrument.
 */

import { METRICS } from "../../shared/focus-curves.ts";
import type { FocusMap } from "../../shared/run-document.ts";
import type { TaPage, TaStep } from "../../types.ts";
import type { RunAnswer } from "zmart-interface/api";

/** Measure every point of the map; the focus map's own `remeasure` drives
    the stage, and the answer says whether the operator's hand stopped it.
    The map's own presses hand their measuring over as `measure`: the step
    run again on some of its points. */
export function runFocus(
  page: TaPage, step: TaStep, { measure }: { measure?: () => Promise<void> } = {},
): RunAnswer | Promise<RunAnswer> {
  if (measure) return measure();
  const state = page.run;
  /* Only the plane strategy measures anything; the others are parked and
     would finish at once. */
  if (state.focus.strategy !== "plane") return;
  /* Nothing goes back to point one when the map is done: the stage,
     the mark and the lit row all end on the last point measured. */
  return page.remeasure().then((came) => {
    if (!came?.stopped) return;
    const f = state.focus;
    const measured = f.points.filter((p) => Number.isFinite(p.z)).length;
    return { stopped: true, note: `stopped by hand — ${measured} of ${f.points.length} points measured` };
  });
}

/** The map is measured: say what it came to, and let a run opened on a
    protocol bring the rest of its steps back. */
export function focusFinished(page: TaPage, s: TaStep): void {
  const state = page.run;
  const f = state.focus;
  f.applied = true;
  page.theRestOfTheProtocolAppears();
  page.stageWatch?.refresh();
  state.notes[s.id] =
    f.strategy === "plane" ? (f.surface ? `${f.surface.model} from ${f.points.length} points · ${focusFitWord(f)}`
      : `no focus map: none of the ${f.points.length} points found the tissue`)
    : `focused at every position · ${METRICS[f.metric].label}`;
  page.renderPointList(); page.drawTrace();
}

/** How well the focus map fits its points, in words an operator can weigh.
    A constant or a plane through as many points as it has parameters
    passes through them exactly, so its residual is zero by construction and
    says nothing; only a fit with points to spare has an rms worth reading. */
export function focusFitWord(f: FocusMap): string {
  const found = f.points.filter((p) => Number.isFinite(p.z)).length;
  /* Asked only of a map with a surface, and a fitted surface always has its rms. */
  const parameters = f.surface!.model === "constant" ? 1 : f.surface!.model === "plane" ? 3 : 0;
  return parameters && found <= parameters ? "exact fit" : `rms ${f.residual!.toFixed(1)} µm`;
}
