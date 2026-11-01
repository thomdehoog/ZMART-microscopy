/**
 * The Target scan area step's channel: the target settings, and the four
 * placement levers over the gated targets.
 *
 * The box itself is `selection-panel.ts`; this hands it what it shows and
 * what a lever moved means for the run: a plan not yet placed, so the
 * press is asked for again.
 */

import type { Channel } from "zmart-interface/api";
import { activeRecording } from "../../microscope/recordings.ts";
import { recordingOptions } from "../../shared/page-helpers.ts";
import { renderRecordingSlot } from "../../shared/recording-slot.ts";
import type { TargetAcquisition } from "../../types.ts";
import { selectionPanel } from "./selection-panel.ts";

export const selectionChannel: Channel<TargetAcquisition> = {
  id: selectionPanel.id,
  label: selectionPanel.label,
  mount(host, page) {
    const state = page.run;
    page.shown.selection = selectionPanel.mount(host, {
      recordingSlot: (into, opts) => renderRecordingSlot(into, recordingOptions(page, opts)),
      restricted: () => state.restricted,
      tiles: () => state.targetTiles,
      rules: () => state.placing,
      /* A lever moved is a plan not yet placed: the press is asked for again. */
      setRule: (key, value) => {
        state.placing[key] = value;
        state.restricted = new Set();
        state.targetTiles = [];
        state.tilePlan = null;
        state.done.delete("select");
        state.ran.delete("select");
        page.stateEdited("select");
      },
      plan: () => state.tilePlan,
      changed: () => {
        state.targetFrameUm = activeRecording(state.targetType)?.frameUm ?? null;
        page.drawStage(); page.renderRail(); page.renderActionBar();
        page.shown.gating?.redraw(); page.shown.selection?.redraw?.();
      },
    });
    return { actionSlot: page.shown.selection.actionSlot };
  },
};
