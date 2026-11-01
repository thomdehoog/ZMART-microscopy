/**
 * Detecting the objects: every field of the overview through the analysis,
 * each field's targets landing on the canvas as it is found.
 */

import { status } from "zmart-interface/api";
import { newMaskLayer, replaceMaskLayer } from "../../shared/mask-layers.ts";
import { cellsInAllGates } from "../../shared/gating.ts";
import { settingsFor } from "./detection.ts";
import { forgetTheMasks } from "./layers.ts";
import type { RunAnswer } from "zmart-interface/api";
import type { FoundField } from "../../backend/verbs.ts";
import type { TaPage, TaRun, TaStep } from "../../types.ts";

/* A field's targets, as discovery reports them: in the stage's frame, where
   the instrument imaged them. They are kept in the carrier's frame, as
   everything drawn on the picture is, and the field's label is kept with
   them, because it is where the field's picture is. */
function fieldFound(page: TaPage, field: FoundField) {
  const state = page.run;
  /* Discovery files every field under its label. */
  state.fieldLabels[field.field] = field.position_label!;
  state.examined.add(field.field);
  for (const cell of field.cells) state.cells.set(cell.id, page.stage.toCarrier(cell));
  const laid = state.masks.find((one) => one.kind === "overview");
  if (laid) laid.objects = state.cells.size;
}

/** What discovery came to, said beside the button. */
const discoveryNote = (state: TaRun) => `${state.cells.size} targets`;

export function runDetection(page: TaPage, s: TaStep): Promise<RunAnswer> {
  const state = page.run;
  page.overviewGoesGreyForTheMasks();
  state.cells = new Map();
  /* A fresh discovery invalidates everything named by the old ids: what
     the gates let through and the acquired pairs -- a stale id crashed
     the draw and the gallery alike. The gates themselves are kept: they
     are drawn on the features, not on the objects, and are applied to
     the new population when the discovery finishes. */
  state.gated = new Set();
  state.restricted = new Set();
  state.targetTiles = [];
  state.acquired = [];
  state.acquiredLabels = {};
  state.acquiredTiles = {};
  state.selectedTarget = null;
  state.hoveredTarget = null;
  state.cellsShown = true;
  state.examined = new Set();
  forgetTheMasks();
  /* The run's masks are a mask layer on the overview, born wearing the
     dress the tile test wears now. A run writes over the last run's
     mask files, so it takes the last run's place in the bar. */
  state.masks = replaceMaskLayer(state.masks, newMaskLayer({
    algo: state.detect.algo, kind: "overview", existing: state.masks,
    dress: { colour: state.detect.maskColour, show: state.detect.maskShow === "line" ? "line" : "fill", alpha: state.detect.maskAlpha },
  }));
  const detection = page.shown.detection;
  detection?.progress?.({ start: true, doing: "starting the workers…" });
  return page.backend.discoverTargets({
    settings: settingsFor(state.detect),
    onDoing: (sentence) => {
      status.say(sentence);
      detection?.progress?.({ doing: sentence });
    },
    onProgress: (done, of, detail: { phase?: unknown; objects?: number; running?: boolean } = {}) => {
      detection?.progress?.({ done, of, ...detail });
      page.protocolWithin(done, of);
      /* A field's masks land on the canvas as its object detection does. */
      page.redrawSoon();
    },
    onField: (field) => {
      if (state.running !== s.id) return;
      fieldFound(page, field);
      /* The lit frame stays where the operator left it: fields land in
         the order the analysis finishes them, several at a time, and a
         frame that jumped to each would only flicker across the sample. */
      state.notes[s.id] = discoveryNote(state);
      page.redrawSoon();
    },
  }).then((out) => {
    /* Every field once more, by id: a poll can miss the last one to
       land, and the answer is the whole list. */
    for (const field of out?.fields ?? []) fieldFound(page, field);
    /* What the bridge says of a field it could not examine. */
    const failed = (out?.failed ?? []) as { why?: string }[];
    detection?.progress?.({
      ended: true,
      failed: failed.length > 0,
      note: out?.stopped
        ? "stopped by hand"
        : failed.length
          ? `finished — ${failed.length} field(s) failed; the first said: ${failed[0].why}`
          : "object detection finished",
    });
    return out?.stopped ? { stopped: true, note: `stopped by hand — ${state.cells.size} targets found` } : undefined;
  }, (why) => {
    detection?.progress?.({ ended: true, failed: true, note: why.message });
    throw why;
  });
}

/** Detection finished: the gates are applied to the new population. */
export function detectionFinished(page: TaPage, s: TaStep): void {
  const state = page.run;
  state.notes[s.id] = discoveryNote(state);
  /* The gates are definitions on the features and outlive the
     objects: what they let through of the new population is worked
     out again, so the gating step stands done -- orange by hand,
     green under the protocol -- and the step after it has its
     selection. */
  state.gated = cellsInAllGates([...state.cells.values()], state.gates);
  if (state.gates.length) state.done.add("gate");
  page.shown.gating?.redraw();
}
