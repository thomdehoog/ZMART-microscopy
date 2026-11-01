/**
 * The Define Carrier step's channel: the carrier's controls beside the
 * canvas, and the alignment marks that register it to the stage.
 *
 * The carrier is *what the canvas is drawing*, so its controls dock in the
 * column beside the picture (`carrier-panel.ts` builds them and draws the
 * carrier on the stage itself). The anchor points belong to the run, not to
 * the panel: the canvas draws them and the press that places them is the
 * canvas's; the panel is handed the few things it needs to show and change
 * them.
 */

import type { Channel } from "zmart-interface/api";
import carrierWidget from "../../shared/carrier-panel.ts";
import { describeCarrier } from "../../shared/carriers.ts";
import type { XY } from "../../shared/scanfields.ts";
import type { TaPage, TargetAcquisition } from "../../types.ts";

/** Standing on the step settles it: the carrier is whatever is configured. */
export function carrierSettled(page: TaPage): void {
  const state = page.run;
  if (page.indexOfStep("carrier") < 0) return;
  state.done.add("carrier");
  state.notes.carrier = describeCarrier(state.carrier);
}

/** What installing the carrier lends the page: settling its step, by name. */
export interface CarrierOnThePage {
  carrierSettled: () => void;
}

/**
 * Wire the keyboard to the marks, once, when the page starts.
 *
 * Delete takes away the alignment mark that was pressed — the one wearing a
 * ring on the picture and standing as the current row in the list. The same
 * key does the same thing to a focus point and to a scan field, so a carrier
 * is edited the way everything else on this canvas is.
 *
 * Taking the last one away leaves the box as the Add button left it: an empty
 * list and a press offering to lay a fresh set, which is what an operator
 * wants after deciding the whole alignment was wrong.
 */
export function installCarrier(page: TaPage): CarrierOnThePage {
  const state = page.run;
  /* How the carrier panel's list of anchors is redrawn. Set by the panel when
     it mounts; called from here and from the picture, because a mark dragged
     on the canvas has to move the numbers in the list with it. */
  page.redrawAnchors = () => {};
  window.addEventListener("keydown", (e) => {
    if (page.step(state.activeIdx)?.mode !== "carrier" || state.running) return;
    if (e.key !== "Delete" && e.key !== "Backspace") return;
    // a number being typed into the count box is not a mark being deleted
    const tag = (e.target as Element).tagName;
    if (tag === "INPUT" || tag === "SELECT") return;
    const chosen = state.anchorPicked ?? -1;
    if (!(chosen >= 0) || !state.anchors[chosen]) return;
    e.preventDefault();
    state.anchors = state.anchors.filter((mark, at) => at !== chosen);
    state.anchorPicked = -1;
    state.anchorLit = -1;
    page.redrawAnchors();
    page.drawStage();
    page.stateEdited("carrier");
  });
  return { carrierSettled: () => carrierSettled(page) };
}

export const carrierChannel: Channel<TargetAcquisition> = {
  id: carrierWidget.id,
  label: carrierWidget.label,
  mount(host, page, { locked }) {
    const state = page.run;
    return carrierWidget.render(host, {
      config: state.carrier,
      locked,
      anchors: {
        list: () => state.anchors,
        arming: () => state.anchoring,
        light: (i) => {
          if ((state.anchorLit ?? -1) === i) return;
          state.anchorLit = i;
          page.drawStage();
        },
        /* The places this carrier is registered from, put down together.
           Replaces rather than adds, so pressing twice does not leave eight
           marks on four spots — and any that had been driven to lose their
           stage reading with them, because a fresh set is a fresh question. */
        suggest: (places) => {
          state.anchors = places.map((p) => ({ x: p.x, y: p.y, at: p.at }));
          state.anchorPicked = -1;
          page.redrawAnchors(); page.drawStage();
          page.stateEdited("carrier");
        },
        /* Which mark the keyboard is talking to: chosen by pressing it on the
           picture, and drawn as the current row in the list, so an operator
           can look at either and know which one the other means. */
        picked: () => state.anchorPicked ?? -1,
        /* And chosen from the list as well as from the picture. Pressing a
           row is how an operator says which of the four they mean when they
           are reading the list rather than looking at the plate, and it has
           to mean the same thing either way — the mark on the picture is
           what says which one that is. */
        pick: (i) => {
          state.anchorPicked = i;
          page.redrawAnchors(); page.drawStage();
        },
        /* Where the microscope is standing now, kept against this point on
           the carrier: the pair is the registration — this place on the
           drawing is that place on the stage. */
        snap: async (i) => {
          /* Ask the instrument where it is, now, rather than taking whatever
             the watch last happened to say. The watch reads every few
             seconds; an operator presses this the moment they have finished
             driving, so the reading it would otherwise record is the one from
             up to five seconds before the drive ended.

             And the reading itself, not the position the picture has worked
             out. Once a scan has run, `whereTheStageIs` answers with the last
             tile it imaged — right for drawing the mark as a scan goes by,
             and wrong for an operator who has since driven somewhere by hand
             to register the carrier from it. Falling back to it only for the
             case where there is no instrument to ask. */
          const at = (await page.stageWatch?.refresh()) ?? page.whereTheStageIs();
          if (!at) return;
          const [oxBefore, oyBefore] = page.stage.carrierOriginUm();
          state.anchors = state.anchors.map((a, n) =>
            (n === i ? { ...a, stage: { x: at.x, y: at.y, z: at.z } } : a));
          /* The carrier's frame just moved under everything already
             measured. What was measured was measured on the stage — that
             truth is unchanged — so its carrier coordinates are re-derived
             by the shift, or the cells and the focus map silently stand a
             frame-move away from the plan they were measured against. */
          const [oxAfter, oyAfter] = page.stage.carrierOriginUm();
          const dx = oxBefore - oxAfter, dy = oyBefore - oyAfter;
          if (dx || dy) {
            const moved = <P extends XY>(p: P): P => ({ ...p, x: p.x + dx, y: p.y + dy });
            state.cells = new Map(
              [...state.cells].map(([id, c]) => [id, moved(c)]));
            for (const map of [state.focus, ...Object.values(state.focusMaps)]) {
              map.points = map.points.map(moved);
            }
          }
          page.redrawAnchors(); page.drawStage();
          page.stateEdited("carrier");
        },
        onChange: (fn) => { page.redrawAnchors = fn; },
      },
      onChange: (next) => {
        state.carrier = next;
        /* The alignment goes with the old carrier. Where the four points sit
           comes from the shape, and what they were snapped to was measured
           against that shape — a plate 75 mm wide aligned by its own borders
           says nothing once it is 128 mm wide, and keeping the marks would
           leave the drawing standing somewhere nobody measured. */
        state.anchors = [];
        page.redrawAnchors();
        // the note in the rail says what the carrier now is
        carrierSettled(page);
        page.stateEdited("carrier");
        // the tissue is spread over the plate, so a different plate is a
        // different sample even before the plan moves
        page.rebuildPlan();
        page.view.fitted = false;
        page.drawStage();
        page.renderRail();
        page.renderActionBar();
      },
    });
  },
};
