/**
 * Target acquisition on the page: its canvas, and what its steps lend the
 * page so the other steps and the framework can call them by name.
 *
 * Each step keeps its own functions in its own folder, taking the page as
 * their first argument. This is where they are lent to the page
 * (`page.pictureOf(...)` is `pictureOf(page, ...)`), and where the parts
 * that need wiring once at the start -- the canvas, the focus map, the
 * carrier's keyboard -- are installed, in the order they need one another.
 * Each is lent as it is made, since the next one reaches for it; what was
 * lent, and the workflow's hooks, are what `install` answers.
 */

import { installTheCanvas } from "./the-canvas.ts";
import * as helpers from "./shared/page-helpers.ts";
import {
  chosenInstrument, chosenMicroscope, listInstruments, listProtocols, renderSetup,
  theRestOfTheProtocolAppears,
} from "./steps/connect/channel.ts";
import { installCarrier } from "./steps/define_carrier/channel.ts";
import { activePreset, rebuildPlan } from "./steps/define_scan_area/channel.ts";
import { installFocus } from "./steps/focus_strategy/channel.ts";
import { focusFitWord } from "./steps/focus_strategy/run.ts";
import { testTilesChanged } from "./steps/scan_the_overview/channel.ts";
import { overviewGoesGreyForTheMasks } from "./steps/discover_targets/channel.ts";
import { selectTarget, targetAt, targetPressed } from "./steps/acquire_targets/channel.ts";
import { renderProtocolProgress } from "./steps/run_protocol/channel.ts";
import { protocolWithin } from "./steps/run_protocol/run.ts";
import type { Hooks, Installed } from "zmart-interface/api";
import type { Lends, TaPage, TargetAcquisition } from "./types.ts";

export function installTargetAcquisition(page: TaPage): Installed<TargetAcquisition> {
  const lends: Partial<Lends> = {};
  /* Put on the page now, and in the answer: the next thing installed may
     reach for it. */
  const add = (made: Partial<Lends>) => { Object.assign(lends, made); Object.assign(page, made); };
  /* Functions that take the page first, lent under their own names: each
     one as `Lends` names it, the page already given. */
  const lend = (functions: Record<string, (page: TaPage, ...rest: never[]) => unknown>) => add(
    Object.fromEntries(Object.entries(functions)
      .map(([name, fn]) => [name, (...a: never[]) => fn(page, ...a)])) as Partial<Lends>);
  /* What several steps share on the page. */
  lend({
    pictureOf: helpers.pictureOf, redrawSoon: helpers.redrawSoon,
    recordingOptions: helpers.recordingOptions,
    scannedPlan: helpers.scannedPlan, tilesetOfField: helpers.tilesetOfField,
  });
  /* The steps' own functions, by the names the rest of the page calls. */
  lend({
    chosenInstrument, chosenMicroscope, listInstruments, listProtocols, renderSetup,
    theRestOfTheProtocolAppears,
    activePreset, rebuildPlan,
    testTilesChanged,
    overviewGoesGreyForTheMasks,
    selectTarget, targetAt, targetPressed,
    protocolWithin, renderProtocolProgress,
  });
  add({
    focusFitWord,
    /* The clock reading where the stage is while a session is open, set by
       Connect and stopped when the run starts over or the workflow is left. */
    stageWatch: null,
  });
  /* The canvas first: the focus map draws on it. */
  add(installTheCanvas(page));
  add(installFocus(page));
  add(installCarrier(page));

  /* The instruments, asked for once the backend is known; the card fills in
     when the answer lands. The focus list and the plan drawn once, empty. */
  page.listInstruments();
  page.renderPointList();
  page.rebuildPlan();

  /* Every name `Lends` declares has been lent above. */
  return { lends: lends as Lends, hooks: theHooksOf(page) };
}

/**
 * What target acquisition does when the page tells it something: only while
 * it is the workflow open, since only the open workflow's hooks run.
 */
export function theHooksOf(page: TaPage): Hooks<TargetAcquisition> {
  /* The stage's clock, put down: a session is over, or this workflow is no
     longer the one on screen. */
  const stopTheStageClock = () => {
    page.stageWatch?.stop();
    page.stageWatch = null;
  };
  return {
    /* The canvas's framing presses come and go with the session. */
    onRender: () => page.renderFramingPresses(),
    /* The run starts over -- on Disconnect, or when this workflow is chosen:
       the stage's clock is stopped, the picture will fit itself to the next
       session's travel, the instruments are asked for again (the fresh run
       has none) and the boxes that draw their own picture are drawn empty. */
    onReset: () => {
      stopTheStageClock();
      page.view.fitted = false;
      page.shown.gating?.redraw();
      page.renderPointList();
      page.listInstruments();
    },
    /* Another workflow is chosen: the clock that reads the stage stops. */
    onLeave: stopTheStageClock,
    /* The protocol's progress stands over whichever step's controls the walk
       is standing in, so it is put there whenever controls go in. */
    onChannelMounted: () => page.renderProtocolProgress(),
  };
}
