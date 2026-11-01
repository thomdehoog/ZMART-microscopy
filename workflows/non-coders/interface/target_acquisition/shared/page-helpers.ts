/**
 * What several steps of this workflow share on the page: where a capture's
 * picture is fetched from, one redraw per frame, the recording slots' wiring,
 * and the plan as it was scanned.
 *
 * Every function takes the page first, the way a step's own run does, and
 * the page lends them out under their own names (`page.pictureOf`, ...) so
 * a step calls them without knowing where they live.
 */

import { displayedPictureAddress } from "../canvas/display-of.ts";
import { activeRecording, type Recording, type Slot } from "../microscope/recordings.ts";
import type { Reading } from "../microscope/settings.ts";
import type { TaPage, TaRun } from "../types.ts";
import type { PlanTile } from "./run-document.ts";

/** Where a capture's picture is: the viewer's small copy, by the capture's
    label -- drawn with the canvas's own display settings for that
    acquisition when there are any, so the preview and the gallery show the
    sample the way the picture shows it. */
export const pictureOf = (
  page: TaPage, kind: string, label: string | null | undefined,
  { displayAs = kind }: { displayAs?: string } = {},
): string | null => {
  const where = page.backend.viewOf(kind);
  const snapshot = page.thePicture.panel()?.snapshot?.() ?? null;
  return displayedPictureAddress(where, label, snapshot, displayAs);
};

/* Targets arrive far faster than a picture can be drawn. One redraw per
   frame, however many fields landed in it. */
let redrawPending = false;
export function redrawSoon(page: TaPage): void {
  if (redrawPending) return;
  redrawPending = true;
  requestAnimationFrame(() => { redrawPending = false; page.drawStage(); page.renderAll(); });
}

/* One slot per step, and the rows in it are the recordings.
 *
 * The bar at the top takes the next reading; what has been read stands under
 * it, a row apiece. Readings accumulate rather than replace, because the
 * optics get changed in the middle of a session and both settings stay worth
 * having — an overview taken dry at 5x and a detail taken at 63x in oil are
 * one run. One row is marked as the one the step is taken with, so switching
 * between them is a click rather than a second reading. */

/** Whether two recordings hold the same settings: their whole changeable half,
    whatever keys the driver uses, compared as it reported them. */
export const sameSettings = (a?: Recording | null, b?: Recording | null): boolean => {
  const said = (record?: Recording | null) =>
    record?.changeable && Object.keys(record.changeable).length
      ? JSON.stringify(record.changeable, Object.keys(record.changeable).sort())
      : null;
  return said(a) !== null && said(a) === said(b);
};

/* The one mistake every reading after the overview's invites: importing
   with the microscope still set as for the overview. Said under the reading
   rather than refused -- the reading is fine as a reading, and one setting
   can serve two steps when that is meant. */
const sameSettingAsTheOverview = (state: TaRun) => (record: Recording): string | null =>
  sameSettings(record, activeRecording(state.overviewPreset))
    ? "Same settings as for the overview scan"
    : null;

/* Which step each recording is a setting of: the one whose box it is
   recorded in. */
/** The run's keys that hold a recording slot. */
export type SlotKey = "overviewPreset" | "focusPreset" | "targetType" | "targetFocus";

const STEP_OF_SLOT: Record<SlotKey, string> = {
  overviewPreset: "scanfields", focusPreset: "focus", targetType: "select", targetFocus: "acquire",
};

/* A slot's options, filled in from the run: a step says which recording it
   is showing and what to do when it changes; where that recording is kept,
   and how to read the instrument, is the run's business. */
export const recordingOptions = <O extends { key: SlotKey; warn?: (record: Recording) => string | null }>(
  page: TaPage, opts: O,
) => {
  const state = page.run;
  return {
    ...opts,
    slot: (): Slot => state[opts.key],
    setSlot: (next: Slot) => { state[opts.key] = next; page.stateEdited(STEP_OF_SLOT[opts.key]); },
    running: () => state.running,
    readSetting: (type: string, how?: { nth?: number }): Promise<Reading> => page.backend.readSetting(type, how),
    warn: opts.warn ?? (opts.key === "overviewPreset" ? undefined : sameSettingAsTheOverview(state)),
  };
};

/* The tiles a field index names: the plan as it was scanned, which is how
   the bridge numbered the fields, and the plan itself before any scan. */
export const scannedPlan = (page: TaPage): PlanTile[] => page.run.scanned?.plan ?? page.run.plan;

/** Which compartment a field belongs to, for the per-tileset ceiling. */
export const tilesetOfField = (page: TaPage, field: number): string | number => {
  const t = scannedPlan(page)[field];
  return t ? (t.tileset ?? t.fieldId ?? field) : field;
};
