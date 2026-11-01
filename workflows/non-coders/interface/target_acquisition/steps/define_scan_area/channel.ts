/**
 * The Overview scan area step's channel: the overview's preset, recorded
 * here, and the editor that lays the scan fields over the carrier.
 *
 * The scan fields are *what is being drawn on the canvas*, so their editor
 * docks in the column beside it (`scanfield-editor.ts` builds it and draws
 * the fields on the stage). The preset is recorded in the same box because
 * a field takes its frame from it.
 */

import { el, type Channel } from "zmart-interface/api";
import { hasRecording } from "../../microscope/recordings.ts";
import { recordingOptions } from "../../shared/page-helpers.ts";
import { renderRecordingSlot } from "../../shared/recording-slot.ts";
import type { PlanTile } from "../../shared/run-document.ts";
import type { TaPage, TargetAcquisition } from "../../types.ts";
import scanfieldsWidget, { presetInk, type PlanPreset } from "./scanfield-editor.ts";

declare global {
  interface Window {
    /** The plan as last worked out, for a browser test. */
    __plan?: PlanTile[];
  }
}

/** A recorded preset, as the plan is taken with it: the recording's own words, and the colour its tiles are drawn in. */
export interface RecordedPreset extends PlanPreset {
  kind: "acquisition";
  name: string;
  summary: string;
  ink: string;
}

/* Every preset recorded beside the fields, in the order taken — which is
   the order their colours come in, so the row and the tiles it lays are the
   same fact seen twice. */
const recordedPresets = (page: TaPage): RecordedPreset[] => page.run.overviewPreset.records.map((r, i) => ({
  id: r.id,
  kind: "acquisition",
  name: r.name,
  summary: r.summary,
  frameUm: r.frameUm,
  ink: presetInk(i),
}));

/* What the whole plan is taken with. One preset, not one per field:
   activating another one re-takes everything, which is the only reading of
   it that stays true when the objective in the light path has changed. */
export const activePreset = (page: TaPage): RecordedPreset | null =>
  recordedPresets(page).find((p) => p.id === page.run.overviewPreset.active) ?? null;

/** The plan -- where the stage goes and what each frame covers -- worked
    out again from the fields, the active preset and the carrier. */
export function rebuildPlan(page: TaPage): void {
  const state = page.run;
  state.plan = scanfieldsWidget.plan(state.fields, activePreset(page), state.carrier);
  /* Left where a test can reach it, the way the live picture is. The plan is
     what this half of the run produces — where the stage goes and what each
     frame covers — and a suite that could only read the sentence beside it
     was asking how many positions there are, never where. */
  window.__plan = state.plan;
}

/* Drawing fields is the work, the way recording and configuring are: the
   step is done once there is something to scan, and undone again if the last
   field is removed. */
export function scanfieldsSettled(page: TaPage): void {
  const state = page.run;
  rebuildPlan(page);
  if (page.indexOfStep("scanfields") < 0) return;
  const positions = state.plan.length;
  if (positions) {
    state.done.add("scanfields");
    state.notes.scanfields = `${positions} position${positions === 1 ? "" : "s"}`;
  } else {
    state.done.delete("scanfields");
    delete state.notes.scanfields;
  }
}

export const scanfieldsChannel: Channel<TargetAcquisition> = {
  id: scanfieldsWidget.id,
  label: scanfieldsWidget.label,
  mount(host, page, { locked }) {
    const state = page.run;
    /* The overview's preset is recorded here, where the fields that will be
       taken with it are laid, because a field takes its frame from it.

       Until it exists there is nothing to lay — but the ways of laying are on
       screen anyway, greyed. They used to be absent, and an empty step is a
       worse answer than a disabled one: the operator arrives, sees a single
       box, and has no way to tell whether this step is about recording a
       preset or whether the rest of it is still loading. Greyed, the step
       shows what it is going to be, and that the open bar at the top of it is
       what the rest is waiting on — which is a sentence the panel no longer
       has to carry, because the picture of it says the same thing. */
    const rec = document.createElement("div");
    rec.id = "sf-preset";
    host.append(rec);
    const presetSlot = {
      label: "Optical configuration", key: "overviewPreset" as const,
      /* No name to give it: what is being brought in is whatever the
         microscope is set to, and it is named after that. */
      unnamed: true,
      takes: "Import optical configuration",
      /* One word: the heading over the box already says what would be
         updated, and the reading now stands on the same row. */
      retakes: "Update",
      /* A recording taken or forgotten changes what there is to be taken with,
         so the run is asked again from the top. Activating another one changes
         what the plan covers without changing the plan: the editor is told,
         the tiles are worked out again, and every field stays where the
         operator put it. */
      changed: () => {
        /* The last recording forgotten takes the plan with it. A region or a
           grid position is a statement about what to image and with what, and
           with no preset left there is no with — keeping the outlines would
           leave the operator a picture of a plan the run could not run, and
           the next preset recorded would silently adopt shapes drawn for
           optics nobody can see any more. */
        if (!hasRecording(state.overviewPreset)) state.fields = [];
        page.remountChannel();
        scanfieldsSettled(page);
        page.stateEdited("scanfields");
        page.renderAll();
      },
      activated: () => {
        page.shown.editor?.setPreset(activePreset(page));
        scanfieldsSettled(page);
        page.stateEdited("scanfields");
        page.drawStage();
        page.renderRail();
      },
    };
    renderRecordingSlot(el("sf-preset"), recordingOptions(page, presetSlot));

    page.shown.editor = scanfieldsWidget.render(host, {
      fields: state.fields,
      carrier: state.carrier,
      preset: activePreset(page),
      presetSlot: el("sf-preset"),
      /* Locked by the run having moved past this step, and locked until the
         preset the plan would be taken with exists. */
      locked: locked || !hasRecording(state.overviewPreset),
      /* How far a field may be drawn: the instrument's canvas, said in the
         carrier's own micrometres. Not the carrier — a plate does not limit
         imaging, the instrument does, and a plate centred in a 120 x 80 mm
         travel has reachable stage all round it that the drawing was refusing
         to enter. The instrument reports its canvas at connect (get_xyz); where
         the carrier sits in it is what alignment measures, so this moves when
         the operator snaps a point.

         The canvas is everywhere a picture can show, so it is wider than the
         travel by half the widest field. A field laid at its very edge can
         put a picture's centre a little past the travel; the driver refuses
         that move before anything moves, and the run stops there with the
         driver's sentence, so nothing is taken in the wrong place. The travel
         itself is the driver's to know, and the page does not guess it. */
      reach: (() => {
        const [fw, fh] = page.stage.travelUm;
        const [sx, sy] = page.stage.travelOriginUm;
        const [ox, oy] = page.stage.carrierOriginUm();
        return {
          xMin: sx - ox, xMax: sx + fw - ox,
          yMin: sy - oy, yMax: sy + fh - oy,
        };
      })(),
      onChange: (next) => {
        state.fields = next;
        scanfieldsSettled(page);
        /* A plan redrawn is a plan the test tiles no longer index. */
        state.testTiles = new Set();
        page.stateEdited("scanfields");
        page.drawStage();
        page.renderRail();
      },
      redraw: () => page.drawStage(),
    });
    /* The editor is put away when the channel changes hands. */
    return {
      destroy() {
        page.shown.editor?.destroy?.();
        page.shown.editor = null;
      },
    };
  },
};
