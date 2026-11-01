/**
 * Whether the alignment points snapped so far agree with each other.
 *
 * The carrier is placed on the stage by the average of what its snapped
 * points say: each point says "this place on the drawing is that place on
 * the stage", and the shift between the two is the same for every point
 * when the carrier sits square in its holder and every point was snapped
 * where it should be. A turn of the carrier is not corrected (that is a
 * decision still to be made), so points that disagree are averaged into a
 * placement that is wrong somewhere. This says so, in a sentence the carrier
 * panel shows under its list of points.
 *
 * Pure: no page, no state, micrometres in and a sentence out.
 */

/** How far one point's shift may lie from the average before the operator is
    told. A drive and a snap by eye are good to a few tens of micrometres;
    a carrier turned by a tenth of a degree already moves points 10 cm apart
    by 175 µm, and a point snapped at the neighbouring well by millimetres. */
export const ANCHORS_AGREE_WITHIN_UM = 200;

/** An alignment point: a place on the carrier drawing, which landmark it is,
    and, once snapped, where the stage stood when it was. */
export interface Anchor {
  x: number;
  y: number;
  at?: string | null;
  stage?: { x: number; y: number; z?: number } | null;
}

/** The farthest any snapped point's shift lies from the average shift, in
    micrometres, or null while fewer than two points have been snapped. */
export function anchorDisagreementUm(anchors: Anchor[]): number | null {
  const snapped = anchors.filter((a): a is Anchor & { stage: { x: number; y: number } } => !!a.stage);
  if (snapped.length < 2) return null;
  const shifts = snapped.map((a) => [a.stage.x - a.x, a.stage.y - a.y]);
  const mean = [0, 1].map((k) => shifts.reduce((sum, s) => sum + s[k], 0) / shifts.length);
  return Math.max(...shifts.map(([sx, sy]) => Math.hypot(sx - mean[0], sy - mean[1])));
}

/** The sentence the operator reads when the points disagree, or null. */
export function anchorWarning(anchors: Anchor[]): string | null {
  const apart = anchorDisagreementUm(anchors);
  if (apart === null || apart <= ANCHORS_AGREE_WITHIN_UM) return null;
  const said = apart >= 1000 ? `${(apart / 1000).toFixed(1)} mm` : `${Math.round(apart)} µm`;
  return `The alignment points disagree by up to ${said}. The carrier may be turned in its holder, `
    + "or a point was snapped at the wrong place; only the average shift is corrected, so "
    + "snap the points again or check how the carrier sits.";
}
