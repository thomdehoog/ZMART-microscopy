/**
 * The Scan the overview step's channel: what the scan will do, the test
 * tiles it is rehearsed on, its progress, and the press that starts it.
 *
 * The scan consults nothing: it takes the run's one recorded preset, and it
 * keeps focus with the map the focus step generated — or at every position,
 * when no map was measured. There is nothing here to choose, so the channel
 * is a short summary the operator can check at a glance, and the press that
 * starts the scan.
 */

import { sideGroup } from "zmart-interface/api";
import { progressBox } from "../../shared/progress.ts";
import { spreadTestTiles } from "./test-tiles.ts";
import type { Channel } from "zmart-interface/api";
import type { TaPage, TargetAcquisition } from "../../types.ts";

/* The test tiles changed, on the picture or in the box: Step 5's own
   setting edited, so the steps after it are orange and the box says the
   new count. */
export function testTilesChanged(page: TaPage): void {
  page.stateEdited("scan");
  page.remountChannel();
  page.drawStage();
  page.renderAll();
}

export const scanChannel: Channel<TargetAcquisition> = {
  id: "scan",
  label: "Scan the overview",
  mount(host, page) {
    const state = page.run;
    const pad = document.createElement("div");
    pad.className = "side-pad-around";
    host.append(pad);

    /* What the scan will do, as labelled rows: how many positions, how
       wide each frame, and how the focus is found at each. */
    const { group, body } = sideGroup("Scan summary");
    const summary = document.createElement("div");
    summary.className = "scan-summary";
    const row = (label: string, value: string) => {
      const key = document.createElement("div");
      key.className = "k";
      key.textContent = label;
      const val = document.createElement("div");
      val.className = "v";
      val.textContent = value;
      summary.append(key, val);
    };
    /* The protocol takes the whole plan whatever is green. */
    const testing = state.testTiles.size && !state.walk.running;
    row("Positions", testing
      ? `${state.testTiles.size} of ${state.plan.length} (test tiles)` : String(state.plan.length));
    const frameUm = state.plan[0]?.frameUm;
    if (frameUm) row("Frame", `${Math.round(frameUm)} µm`);
    const measured = state.focus.applied && state.focus.strategy === "plane";
    row("Focus", measured
      ? (state.focus.surface ? `measured map · ${page.focusFitWord(state.focus)}` : "no focus map")
      : "found at every position");
    body.append(summary);

    /* The test tiles: a few of the plan pressed green, on the picture or
       picked by the box, so the protocol is rehearsed on them before the
       whole area is scanned. The box picks them as Step 4 lays its focus
       points: so many in each tileset, or so many over the whole carrier.
       The scan takes only the green tiles while any are green; the
       protocol run takes the whole plan regardless. */
    const test = sideGroup("Test tiles");
    test.group.id = "test-tiles";
    const draw = document.createElement("div");
    draw.className = "fp-row";
    draw.id = "test-tiles-count";
    draw.dataset.green = String(state.testTiles.size);
    const busy = !!state.running || state.walk.running;
    /* A count joined to its press, as in Step 4's Automatic row. */
    const pick = (over: "tileset" | "carrier", key: "testN" | "testNCarrier",
                  nId: string, pressId: string, label: string, where: string) => {
      const lay = document.createElement("div");
      lay.className = "fp-lay";
      const n = document.createElement("input");
      n.type = "number"; n.min = "1"; n.max = String(Math.max(1, state.plan.length)); n.step = "1";
      n.id = nId;
      n.title = `How many tiles to select ${where}, spread over it as the focus points are`;
      n.value = String(Math.min(state.plan.length, state[key] ?? 3));
      n.addEventListener("input", () => { state[key] = Number(n.value); });
      const press = document.createElement("button");
      press.type = "button"; press.className = "sf-flat sf-doing"; press.id = pressId;
      press.textContent = label;
      press.disabled = busy || !state.plan.length;
      press.addEventListener("click", () => {
        const asked = Math.max(1, Number(n.value) || 1);
        state.testTiles = new Set(spreadTestTiles(state.plan, asked, over));
        testTilesChanged(page);
      });
      lay.append(n, press);
      return lay;
    };
    const clear = document.createElement("button");
    clear.type = "button"; clear.className = "sf-flat"; clear.id = "test-clear";
    clear.textContent = "Clear all";
    clear.disabled = busy || !state.testTiles.size;
    clear.addEventListener("click", () => { state.testTiles = new Set(); testTilesChanged(page); });
    draw.append(
      pick("tileset", "testN", "test-n", "test-random", "Per tileset", "in each tileset"),
      pick("carrier", "testNCarrier", "test-n-carrier", "test-carrier", "Per carrier", "over the whole carrier"),
      clear);
    test.body.append(draw);

    /* The scan's progress, the same box the acquisition has: built with the
       panel, spoken to by the run. */
    const scanProgress = progressBox("Scan progress");
    scanProgress.doing.id = "scan-doing";
    scanProgress.count.id = "scan-count";
    page.shown.scanProgress = scanProgress;
    pad.append(group, test.group, scanProgress.group);

    // and the press that starts it, at the end of what it acts on
    const action = document.createElement("div");
    action.className = "scan-action side-act";
    pad.append(action);
    return { actionSlot: action };
  },
};

/** Arriving at the scan: the focus stack was there to judge the focus; over
    the overview it is a square of other pixels on the picture the operator
    came to look at. Its eye is pressed for them on the way to the scan. */
export function scanArrived(page: TaPage) {
  page.thePicture.panel()?.showAcquisition?.("focussing", false);
}
