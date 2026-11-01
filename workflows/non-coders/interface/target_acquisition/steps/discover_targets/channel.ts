/**
 * The Detect objects step's channel: the detection settings, tried on one
 * position before the whole sample is run.
 *
 * Detection is the same shape as focus: the step happens on the canvas —
 * the cells it finds land there — and its controls sit in the channel
 * (`detection.ts` builds them). This file hands them what they need from
 * the run and the backend.
 */

import { css, sizeCanvas, status } from "zmart-interface/api";
import detectionPanel from "./detection.ts";
import type { TestAnswer } from "./detection.ts";
import type { Channel } from "zmart-interface/api";
import type { TaPage, TargetAcquisition } from "../../types.ts";

/* Detection is judged by its masks, and coloured masks read best on
   quiet ground: running one, on a tile or over the sample, draws the
   overview in grey if it was not already. The chip in the canvas's row
   and the card's Grey press are the way back; nothing else switches it. */
export const overviewGoesGreyForTheMasks = (page: TaPage): void => {
  const panel = page.thePicture.panel();
  if (!panel?.acquisitionGrey?.("overview")) panel?.drawInGrey?.("overview", true);
};

export const detectionChannel: Channel<TargetAcquisition> = {
  id: detectionPanel.id,
  label: detectionPanel.label,
  mount(host, page) {
    const state = page.run;
    page.shown.detection = detectionPanel.mount(host, {
      settings: () => state.detect,
      /* Colour or grey is the overview's own, held on its chip in the
         canvas's row; the card reads it there and its Grey press flips
         the same switch. */
      inGrey: () => Boolean(page.thePicture.panel()?.acquisitionGrey?.("overview")),
      setGrey: (grey: boolean) => page.thePicture.panel()?.drawInGrey?.("overview", grey),
      plan: () => page.scannedPlan(),
      /* The overview's colours by the names the canvas gives them. */
      channels: () => page.thePicture.panel()?.channelsOf?.("overview").map((one) => one.name) ?? [],
      tryOn: (field: number, settings: Record<string, unknown>): Promise<TestAnswer> => {
        overviewGoesGreyForTheMasks(page);
        /* The bridge reads a field's name as its number, and so does the pretend backend. */
        return page.backend.discoverTargets({ fields: [String(field)], settings }).then(({ fields, failed, stopped }): TestAnswer => {
          const found = fields?.[0];
          /* Stopped by the operator's hand before the field answered: the
             backend says so, and that is neither a field nor a failure. */
          if (!found && stopped) return { stopped: true };
          /* A field the bridge could not examine arrives under `failed` with
             the analysis's own sentence. Reading `fields[0]` regardless threw
             a TypeError, and the panel showed that instead of the reason. */
          if (!found) {
            throw new Error((failed?.[0] as { why?: string } | undefined)?.why ?? `position ${field + 1} was not examined`);
          }
          return { ...found, cells: found.cells.map(page.stage.toCarrier) };
        });
      },
      /* The same brake the step's own Run has: the bridge stops the field
         being segmented now, not at the next one. */
      stopTargets: () => page.backend.stopTargets?.(),
      pictureOf: (label: string | undefined) => page.pictureOf("overview", label),
      /* Which capture stands at a plan position: the scan filed each field's
         label as it landed, so the panel can show a field's picture without
         having tested anything on it. */
      labelOf: (field: number) => state.fieldLabels[field],
      /* The field's colorized segmentation, served beside its picture. */
      maskOf: (label: string | undefined) => {
        const where = page.backend.viewOf("overview");
        return where && label ? `${where}/${label}.mask.png` : null;
      },
      status,
      sizeCanvas, css,
      changed: () => { page.renderActionBar(); page.drawStage(); },
      edited: () => page.stateEdited("detect"),
    });
    return { actionSlot: page.shown.detection.actionSlot };
  },
};
