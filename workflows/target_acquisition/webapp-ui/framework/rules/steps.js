/**
 * What a step is, and what may run when.
 *
 * Pure: no DOM, no globals. Everything here is a function of a workflow and a
 * run, which is why it can be unit-tested and why the framework stays free of any
 * particular workflow's semantics.
 *
 * A step is data: what it is called, why it is there, which modules it wants on
 * screen, and what the page should do when it is carried out. The full list of
 * fields is written out in `workflows/README.md`, beside the folders where
 * steps are declared; nothing here needs to know most of them.
 *
 * The framework knows nothing beyond that. Adding a workflow is writing a list.
 */

/**
 * Number the steps by position, so that reordering or mixing steps costs
 * nothing — nobody has to renumber anything by hand.
 *
 * A step may still set its own `n`, which is how two halves of one job can be
 * written as `3a` and `3b` without the steps after them shifting up. No workflow
 * does that at the moment; the ability is kept because it is the kind of thing a
 * workflow wants as soon as a step turns out to be two.
 */
export function numbered(steps) {
  let counter = 0;
  const explicit = new Set(steps.filter((s) => s.n).map((s) => s.n[0]));
  return steps.map((s) => {
    if (s.n) return { ...s, n: s.n };
    counter += 1;
    while (explicit.has(String(counter))) counter += 1;
    return { ...s, n: String(counter) };
  });
}

/**
 * Whether this step is one the run has to wait at.
 *
 * A run is walked in order because each step usually produces something the next
 * one needs: there is no point choosing where to look before the run knows what
 * the sample is mounted in. So a step that has not finished holds up everything
 * after it, and that is the right default.
 *
 * Some steps produce nothing. A step that only shows you something — a picture
 * to look at, a reading to check — leaves the run exactly as it found it, so
 * there is nothing for the steps after it to wait for. Such a step says
 * `nothingWaitsOnThis: true` in the catalogue and the operator may walk straight
 * past it, or come back to it later, in whichever order suits them.
 */
const theRunHasToWaitHere = (step, done) =>
  !done.has(step.id) && !step.nothingWaitsOnThis;

/** The first step that has not completed — the only one the operator may reach. */
export function firstIncomplete(steps, done) {
  const i = steps.findIndex((s) => theRunHasToWaitHere(s, done));
  return i === -1 ? steps.length - 1 : i;
}

/** A step is reachable once everything before it is done. */
export const isReachable = (steps, done, index) =>
  index <= firstIncomplete(steps, done);

/**
 * What this step still needs before it may be carried out, as a short phrase to
 * show the operator, or `null` when there is nothing left to wait for.
 *
 * The step decides and the framework only asks, which is what keeps the shell free
 * of any particular workflow's meaning: nothing here knows that fitting a
 * surface takes three points. A step with no rule of its own is always ready.
 *
 * Whether something else is already running is a separate question, and the
 * shell answers it: every button is disabled while any step is working.
 */
export function blockedBecause(step, run) {
  return step?.ready ? step.ready(run) : null;
}

/**
 * Which modules the step at `index` wants on screen, in the order they are
 * offered.
 *
 * Two things decide this, and it takes the whole list of steps to answer because
 * the second one does.
 *
 * A step names the modules it wants of its own — the focus controls, the
 * gallery, the session form — and gets those. Most steps name nothing, because
 * most steps happen on the stage and the picture of the stage is enough.
 *
 * The canvas itself is the microscope's own limits drawn to scale, so it appears
 * at the step that first asks for it and then stays for the rest of the run. In
 * every workflow that drives a microscope, that step is the first one: the
 * stage is on screen from the start, every step keeps the picture on the left
 * and puts its own controls in the channel beside it. A workflow where nothing
 * asks for the canvas, such as the canvas demonstration, never shows one.
 *
 * Saying which modules it wants is the step's business; how wide they are and
 * which of them is on top is the shell's.
 */
export function panelsFor(steps, index) {
  const own = (steps[index]?.panels ?? []).filter((p) => p !== "canvas");
  const onTheStageFrom = steps.findIndex((s) => s.panels?.includes("canvas"));
  const onTheStage = onTheStageFrom >= 0 && index >= onTheStageFrom;
  return onTheStage ? ["canvas", ...own] : own;
}

/**
 * The same step, in different words.
 *
 * A calibration run and an imaging run both save at the end, but they are
 * saving different things and should say so. This returns a copy of a step
 * with some of its wording replaced, which keeps what the step *does* in one
 * place while letting each workflow explain it in its own terms.
 */
export const reworded = (step, changes) => ({ ...step, ...changes });

/**
 * A step that brought its own panel is not finished when its run is — the
 * gallery is still being curated, the trace still being read. Nothing
 * advances by itself; the operator moves on by clicking. This is here so the
 * rule is written down once, in the layer that owns ordering.
 */
export const advancesOnItsOwn = () => false;
