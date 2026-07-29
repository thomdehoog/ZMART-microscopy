/**
 * What a step is, and what may run when.
 *
 * Pure: no DOM, no globals. Everything here is a function of a workflow and a
 * run, which is why it can be unit-tested and why the frame stays free of any
 * particular workflow's semantics.
 *
 * A step is data plus one function:
 *
 *   { id, title, why, button, widget, ready(run), run(ctx) }
 *
 * `widget` is a key in the widget registry, or null for steps the canvas
 * already serves. `ready` returns null to go, or a string saying why not.
 * `run` does the work through `ctx.backend` — never a timer, never hardware.
 *
 * The frame knows nothing beyond that. Adding a workflow is writing a list.
 */

/**
 * Number the steps by position. Sub-steps opt out with an explicit `n`, which
 * is the only reason 3a and 3b exist. Deriving the rest means reordering or
 * mixing steps costs nothing — nobody has to renumber anything.
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

/** The first step that has not completed — the only one the operator may reach. */
export function firstIncomplete(steps, done) {
  const i = steps.findIndex((s) => !done.has(s.id));
  return i === -1 ? steps.length - 1 : i;
}

/** A step is reachable once everything before it is done. */
export const isReachable = (steps, done, index) =>
  index <= firstIncomplete(steps, done);

/**
 * Why this step cannot run yet, or null. The step decides; the frame only
 * asks. A running step blocks every step, itself included.
 */
export function blockedBecause(step, run) {
  if (run.running) return "another step is running";
  return step.ready ? step.ready(run) : null;
}

/** Which panels the right-hand side shows: the canvas, plus this step's own. */
export function panelsFor(step) {
  return step?.widget ? ["canvas", step.widget] : ["canvas"];
}

/**
 * A step that brought its own panel is not finished when its run is — the
 * gallery is still being curated, the trace still being read. Nothing
 * advances by itself; the operator moves on by clicking. This is here so the
 * rule is written down once, in the layer that owns ordering.
 */
export const advancesOnItsOwn = () => false;
