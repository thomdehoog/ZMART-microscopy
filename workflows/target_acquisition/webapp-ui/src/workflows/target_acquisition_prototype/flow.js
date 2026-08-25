/**
 * Target acquisition prototype — the front end alone.
 *
 * The whole run, rehearsed: a pretend session, a pretend sample, timers in
 * place of a stage. Nothing outside the browser is touched, which is what
 * makes this the right place to design and test the window itself. The steps
 * are the one shared list in `../target_acquisition/the-run.js`; only the
 * backend differs between this workflow and its two siblings.
 */

import { steps as theRun } from "../target_acquisition/the-run.js";

export const blurb =
  "The front end alone: every step rehearsed in the browser, nothing outside "
  + "it touched. Where the window is designed and tested.";

/** A freshly opened page starts here — the variant that always works. */
export const opensFirst = true;

/** The pretend backend: timers and the synthetic sample. */
export const backend = { kind: "pretend" };

export const steps = theRun;
