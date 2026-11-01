/**
 * The Focus strategy step's channel, and the focus map itself on the page.
 *
 * The focus preset is recorded here, where the sweeps that will be measured
 * with it are chosen — in the same box the acquisition preset is recorded
 * in on the scan-fields step, since it is the same kind of thing being
 * done. The map's controls are markup that was built once (`#focus-controls`,
 * from `focus-controls.html` beside this file, put into the page by
 * `focus-map.ts` as it loads) and is moved into the channel while this step
 * is standing, not rebuilt from a declaration.
 *
 * The map itself — the points, their sweeps, the surface through them, and
 * what a press on the picture means — is `focus-map.ts`. It is opened on the
 * page once, when the page starts (`installFocus`), because the stage draws
 * its layers and other steps read the surface it fitted.
 */

import { css, el, sizeCanvas, type Channel } from "zmart-interface/api";
import type { Backend } from "../../backend/verbs.ts";
import { newFocus, type FocusMap, type MapPoint } from "../../shared/run-document.ts";
import { activeRecording } from "../../microscope/recordings.ts";
import { renderRecordingSlot } from "../../shared/recording-slot.ts";
import type { TaPage, TargetAcquisition } from "../../types.ts";
import { openTheFocusMap, type FocusMapHandle } from "./focus-map.ts";

declare global {
  interface Window {
    /** The selected focus point, for a browser test. */
    __theFocusPoints?: () => MapPoint | null;
  }
}

/**
 * What installing the focus map lends the page: the map and its controls, its
 * own functions under the page's names, its brake, and how the step settles.
 */
export type FocusOnThePage = Pick<FocusMapHandle,
  | "drawFocusLayer" | "drawFocusPoints" | "focusPressed" | "focusCursor" | "focusDraggedTo"
  | "focusGrabbed" | "focusHovered" | "focusMarqueeTo" | "focusMarqueeTook" | "anchorPressed"
  | "detectPressed" | "surfaceZAt" | "renderPointList" | "drawTrace" | "remeasure"> & {
  focusMap: FocusMapHandle;
  focusControls: HTMLElement;
  interruptTheFocusRun: FocusMapHandle["interruptTheRun"];
  focusSettled: () => void;
};

/**
 * Point `run.focus` at the map belonging to the active focussing preset.
 *
 * The one being left is kept first, so going back to it finds the points
 * where they were and the heights that were read for them. A preset nobody
 * has worked under yet starts with nothing on the map — its points are the
 * ones it has, which is none.
 */
function focusFollowsPreset(page: TaPage): void {
  const state = page.run;
  const id = activeRecording(state.focusPreset)?.id ?? null;
  if (id === state.focusFor) return;
  const leaving = state.focus;
  if (state.focusFor) state.focusMaps[state.focusFor] = leaving;
  state.focusFor = id;
  state.focus = id ? (state.focusMaps[id] ?? inheritedFocus(leaving)) : newFocus();
  // and maps whose preset has been forgotten go with it
  const kept = new Set(state.focusPreset.records.map((r) => r.id));
  for (const held of Object.keys(state.focusMaps)) {
    if (!kept.has(held)) delete state.focusMaps[held];
  }
}

/* An updated configuration does not take the operator's places with it.
   The recording is right that its READINGS are its own -- a height read
   through optics this recording no longer describes goes stale, and the
   surface fitted through such heights goes with them -- but the points
   are where the operator decided to measure, and pressing Update used to
   throw the whole laid map away with the reading it replaced. */
function inheritedFocus(leaving: FocusMap): FocusMap {
  if (!leaving || leaving.strategy !== "plane" || !leaving.points.length) {
    return newFocus();
  }
  return {
    ...newFocus(),
    metric: leaving.metric,
    perField: leaving.perField,
    perCarrier: leaving.perCarrier,
    points: leaving.points.map((p) =>
      (p.z !== null || p.traces || p.lost) ? { ...p, stale: true } : { ...p }),
  };
}

/* The recording settles the step. A hardware autofocus is held by the stand
   and there is nothing further to do; a software one focuses at every
   position it is sent to, which is also a complete answer. Measuring a focus
   map is the optional extra on top — worth having, because a measured
   surface is faster than focusing everywhere, but nothing waits for it.

   Forgetting the last reading takes the map with it, the way forgetting the
   last acquisition preset takes the plan: points measured through optics
   nobody can see any more are not points. */
function focusSettled(page: TaPage): void {
  const state = page.run;
  const kind = activeRecording(state.focusPreset)?.kind;
  if (!kind) {
    /* A run opened on a protocol brings its focus points without a
       reading: the focussing is read off this microscope afresh. Those
       points are where the operator decided to measure, so they wait for
       the reading rather than being forgotten before it is taken. */
    if (!state.protocolPending) state.focus = newFocus();
    state.done.delete("focus");
    delete state.notes.focus;
    page.renderPointList();
    page.drawTrace();
    return;
  }
  /* Done by running the map, not by recording the preset: the scan
     stands on the heights the map measured on this sample, so the step
     after waits for the press (Thom, 2026-09-28). */
  if (state.focus.applied) { state.done.add("focus"); return; }
  state.done.delete("focus");
  state.notes.focus = kind === "hardware"
    ? "held by the stand"
    : "focused at every position";
}

export const focusChannel: Channel<TargetAcquisition> = {
  id: "focus",
  label: "Focus strategy",
  mount(host, page) {
    const state = page.run;
    /* The controls, held by `installFocus` below since the page started:
       emptying the channel takes them out of the document, and a lookup
       by id then finds nothing. */
    const { focusControls } = page;
    const box = document.createElement("div");
    box.className = "side-pad-around";
    const rec = document.createElement("div");
    rec.id = "focus-preset";
    box.append(rec);
    host.append(box);
    /* Either kind of focussing can be given a focus map: measure a few
       positions, fit a surface, and the run drives to a known height instead
       of finding one everywhere. A software autofocus finds that height by
       taking a short stack and scoring it; a hardware one is driven to each
       point and the height it settles at is read — so both have something to
       measure and something to fit.

       One map, and it belongs to the recording above it: a run focuses one
       way, so there is one surface to fit and nothing to name or choose
       between. The ways of choosing where to measure appear as soon as
       something has been recorded, and the map is the optional extra either
       way — both kinds are a complete answer on their own. */
    const showTheRest = () => {
      focusControls.hidden = !activeRecording(state.focusPreset);
      focusSettled(page);
      /* Settling is what makes the step done: the rail says so at once. */
      page.renderRail();
      page.renderPointList();
      page.drawTrace();
    };
    const recordingChanged = () => {
      focusFollowsPreset(page); showTheRest();
      page.stateEdited("focus"); page.renderRail(); page.renderActionBar(); page.drawStage();
    };
    renderRecordingSlot(el("focus-preset"), page.recordingOptions({
      label: "Focussing configuration", key: "focusPreset",
      /* Read off the microscope like the optical one, and named after what
         it is rather than by the operator. */
      unnamed: true,
      takes: "Import focussing configuration",
      retakes: "Update",
      locked: !!state.running,
      changed: recordingChanged,
      activated: recordingChanged,
    }));
    showTheRest();
    host.append(focusControls);
    page.renderPointList();
    page.drawTrace();
    return { actionSlot: focusControls.querySelector<HTMLElement>(".focus-action") };
  },
};

/**
 * Open the focus map on the page. Answers the map's own functions under the
 * page's names: the gestures the stage forwards (`focusPressed`, ...), the
 * layers it draws, `surfaceZAt` for the steps that drive to the measured
 * height, `remeasure` for the run, and `renderPointList` and `drawTrace`
 * for whoever changes the points.
 */
export function installFocus(page: TaPage): FocusOnThePage {
  const state = page.run;
  /* Held rather than looked up: emptying the channel takes these out of the
     document, and getElementById cannot find what is not in it. */
  /* Put into the page by `focus-map.ts` as it loads, so it is there. */
  const focusControls = el("focus-controls")!;

  /* The selected focus point, for a test that needs to take hold of one. */
  window.__theFocusPoints = () => state.focus.points[state.focus.selected] ?? null;

  const focusMap = openTheFocusMap({
    run: state,
    tileChosen: () => page.shown.detection?.redraw(),
    backend: {
      measureFocus: (...a: Parameters<Backend["measureFocus"]>) => page.backend.measureFocus(...a),
      stopFocusMeasure: () => page.backend.stopFocusMeasure(),
      /* Where a focus stack's slice pictures are fetched from -- the same
         answer every other picture gets, and `null` from a backend that
         serves none, which is what hides the preview. */
      slicesAt: () => page.backend.viewOf?.("focussing") ?? null,
    },
    stage: page.stage,
    el, css, sizeCanvas,
    step: () => page.step(state.activeIdx),
    focusControls,
    renderActionBar: () => page.renderActionBar(),
    edited: () => page.stateEdited("focus"),
    /* The panel's own Rerun, Run new points and one point measured again
       are the step run again, through the runner like its own press: the
       page is held while the stage is out, and the step lands green with
       the steps after it orange. */
    runTheMap: (measure: () => Promise<void>) => page.runStep(page.indexOfStep("focus"), { measure }),
  });

  /* The trace is drawn in the channel, whose width the operator sets. */
  const ro = new ResizeObserver(() => focusMap.drawTrace());
  ro.observe(focusControls);

  const {
    drawFocusLayer, drawFocusPoints, focusPressed, focusCursor, focusDraggedTo, focusGrabbed,
    focusHovered, focusMarqueeTo, focusMarqueeTook, anchorPressed, detectPressed,
    surfaceZAt, renderPointList, drawTrace, remeasure,
  } = focusMap;
  return {
    focusMap, focusControls,
    drawFocusLayer, drawFocusPoints, focusPressed, focusCursor, focusDraggedTo, focusGrabbed,
    focusHovered, focusMarqueeTo, focusMarqueeTook, anchorPressed, detectPressed,
    surfaceZAt, renderPointList, drawTrace, remeasure,
    interruptTheFocusRun: focusMap.interruptTheRun,
    focusSettled: () => focusSettled(page),
  };
}
