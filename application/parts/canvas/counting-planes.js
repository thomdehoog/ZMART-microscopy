/**
 * Turning what the viewer says about its stack into what an operator counts in.
 *
 * A drawing engine describes the depth of a stack in micrometres, because
 * micrometres are the one unit every part of this project agrees on: the stage
 * moves in them, the store is written in them, and `setPlane` takes them. A
 * microscopist stepping through a stack, though, is not thinking "37
 * micrometres". They are thinking "plane 12 of 48" — how far through the sweep
 * they are, and how much of it is left.
 *
 * Both numbers are worth having and neither replaces the other, so this turns
 * the first into the second and the readout beside the slider shows them
 * together. It is kept here, apart from the panel, because it is plain
 * arithmetic with no screen in it and can therefore be checked directly; see
 * `counting-planes.test.js`.
 */

/**
 * How many planes there are, and which one the picture is standing on.
 *
 * `depth` is what `viewer.theDepthItCanShow()` gives back: `lowUm` and `highUm`
 * are the first and last plane, `stepUm` is the distance between two of them,
 * and `atUm` is where the picture is now. Planes are counted from one, the way
 * an operator counts them, so the first plane of a stack is plane 1 rather than
 * plane 0.
 *
 * Gives back `null` when there is no stack to speak of — no answer at all from
 * the viewer, a single plane, or a step of nought, which would mean dividing by
 * nothing. A single plane is not a stack, and a control for it would be a
 * control that cannot move.
 */
export function thePlanesIn(depth) {
  if (!depth) return null;
  const { lowUm, highUm, stepUm } = depth;
  if (![lowUm, highUm, stepUm].every(Number.isFinite)) return null;
  if (!(stepUm > 0) || !(highUm > lowUm)) return null;
  const count = Math.round((highUm - lowUm) / stepUm) + 1;
  if (count < 2) return null;
  const atUm = Number.isFinite(depth.atUm) ? depth.atUm : lowUm;
  /* Held inside the stack even when the viewer is standing just outside it.
     That happens honestly: an engine puts its bounds at voxel edges, so a view
     nobody has touched can sit a little below the first plane. A readout saying
     "plane 0 / 48" would be describing that arithmetic rather than the
     specimen. */
  const at = Math.min(count, Math.max(1, Math.round((atUm - lowUm) / stepUm) + 1));
  return { count, at, atUm, stepUm };
}

/**
 * The line of text that goes beside the depth slider.
 *
 * "plane 12 / 48 · 37 µm" — the plane number first, because that is what the
 * operator counts in, and the height after it, because that is what the run was
 * written in and what any note they make about the picture will have to say.
 * Gives back `null` when there is no stack, so the caller knows to draw nothing
 * rather than an empty box.
 */
export function theDepthReads(depth) {
  const stack = thePlanesIn(depth);
  if (!stack) return null;
  return `plane ${stack.at} / ${stack.count} · ${Math.round(stack.atUm)} µm`;
}

/**
 * The next plane along, wrapping round at the end of the stack.
 *
 * This is what a stack being played walks through: one step forward each time,
 * and back to the first plane after the last one, so a sweep loops rather than
 * stopping on its final frame and looking as though it has stalled. The answer
 * is in micrometres, ready to hand to `setPlane`.
 */
export function theNextPlaneAfter(depth) {
  const stack = thePlanesIn(depth);
  if (!stack) return null;
  const following = stack.at >= stack.count ? 1 : stack.at + 1;
  return depth.lowUm + (following - 1) * stack.stepUm;
}
