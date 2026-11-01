/**
 * Connecting: the one step whose run is a handful of questions rather than
 * one action.
 *
 * The backend owns the asking — it opens the session and verifies it — and
 * each answer lands here as it comes, so a session that fails does so at a
 * named check rather than as a spinner that stops. Once every check has
 * answered, the canvas becomes the instrument's and the stage watch starts.
 */

import { isFailed } from "../../microscope/connection-status.ts";
import { watchStagePosition } from "../../shared/stage-position.ts";
import type { RunAnswer } from "zmart-interface/api";
import type { TaPage, TaStep } from "../../types.ts";

/** Open the session; answers when it is open, or `{ failed }` once the
    failure has been written into the card's checks. */
export function runConnect(page: TaPage, s: TaStep): Promise<RunAnswer> {
  const state = page.run;
  return page.backend.connect({
    ...state.session,
    /* The name chosen on this card: the bridge plugs that driver in,
       with the connection saved for it when it was installed. */
    instrument: page.chosenInstrument() ?? undefined,
  }, {
    /* The questions, before any answer: one row per key the driver reports. */
    onChecks: (keys) => {
      if (state.running !== "connect") return;
      state.checks = keys.map((label) => ({ label, result: null }));
      page.renderSetup();
    },
    onCheck: (k, result) => {
      if (state.running !== "connect") return;
      state.checks[k].result = result;
      page.shown.session?.answer(k, result);
    },
  }).then(async () => {
    /* The session is open and every check has answered. The canvas is
       the instrument's from here — laid out over the canvas get_xyz
       reports, everywhere a picture can show — and the stage mark stands
       where get_xyz says the stage is. A driver that gives no canvas is
       told to the operator as a failed connection. */
    page.takeTheCanvas(await page.backend.get_xyz());
    /* From here the stage mark is the instrument's: a watch of its own
       reads get_xyz every few seconds for as long as the session is open,
       and again at once after any move this page makes. */
    page.stageWatch?.stop();
    page.stageWatch = watchStagePosition(page.backend, page.takeThePosition, {
      onError: (why) => console.warn(`where the stage is: ${(why as Error).message}`),
    });
    await page.stageWatch.refresh();
  }).catch((why: Error) => {
    /* The instrument's side said no — the bridge is not there, the
       driver it needs is not, or a check failed. The sentence lands where
       the answers would have, marked as the failure it is, and the step
       stays undone: a connection that failed is not a session. The
       runner files the failure (`{ failed }` below). */
    /* The bridge had already opened the driver's session before a check
       failed; left open, the next press opened a second one. A failed
       connection is not a session, so it is closed like one. */
    page.backend?.disconnect?.().catch(() => {});
    if (!state.checks.some((c) => c.result !== null && isFailed(c.result))) {
      state.checks = [...state.checks.filter((c) => c.result !== null),
        { label: "Connection failed", result: `failed — ${why.message}` }];
    }
    page.renderSetup();
    return { failed: why };
  });
}

/** Connected: the protocols this machine has written can be listed now. */
export function connectFinished(page: TaPage): void {
  page.listProtocols();
}
