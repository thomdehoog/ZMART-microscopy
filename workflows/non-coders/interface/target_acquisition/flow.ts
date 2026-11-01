/**
 * Target acquisition — the workflow built into this page.
 *
 * The steps are the list in `./the-run.ts`. What the run drives is chosen on
 * the Connect step, not here: the operator picks the microscope — the
 * controller's mock driver, which answers with made-up data through the
 * whole real chain, or the Leica through Navigator Expert — and the page
 * speaks to the controller through the bridge either way.
 */

import "./style.css";
import { canvasPanel } from "./canvas/panel.ts";
/* The seam. Connecting, reading a preset off the instrument, measuring the
   focus map and driving the overview scan all go through the backend and are
   awaited; the page never knows whether a real stage moved. The page speaks
   to the controller through the bridge; which driver the controller runs —
   the mock or a real microscope — is chosen on the Connect step. The
   in-browser rehearsal (timers and a synthetic sample) is reachable only by
   `?backend=pretend`, for this page's own browser tests. */
import { backend as live } from "./backend/live.ts";
import { backend as pretend } from "./backend/pretend.ts";
import { installTargetAcquisition } from "./on-the-page.ts";
import { steps as theRun } from "./the-run.ts";
import type { Backend } from "./backend/verbs.ts";

/* What a run of this workflow holds beside the framework's own keys, what
   of it survives a disconnect, and what a browser test may read of it. The
   framework asks the flow for these rather than knowing any microscope key
   (`framework/window/run-state.ts`). */
export { freshState, keptAcrossSessions, forTests } from "./shared/run-document.ts";

/** How this workflow is wired to the page when the page opens: its canvas,
    and the functions its steps lend the page. */
export const install = installTargetAcquisition;

/** Which backend this workflow's steps speak to, given the page's own
    address: the rehearsal when it asks for `?backend=pretend`, the bridge
    otherwise. */
export const backendFor = (search: URLSearchParams): Backend => (search.get("backend") === "pretend" ? pretend : live);

export const blurb =
  "Find the targets on an overview and acquire them, on the microscope chosen "
  + "at Connect — the mock microscope or a real one.";

export const opensFirst = true;

export const steps = theRun;

/**
 * The panels this workflow offers, and what each one is made of.
 *
 * A step asks for a panel by its key; the framework builds an element for each
 * of these and lets the panel fill it. The canvas is here because it is this
 * workflow's: a run that drives a microscope is looked at on a picture of the
 * stage, and a workflow that is not would declare something else, or nothing.
 */
export const panels = [canvasPanel];
