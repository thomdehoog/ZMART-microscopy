/**
 * Alignment points that disagree are said to disagree.
 *
 * From the review of 10 October, finding 7: the carrier is placed by the
 * average shift of the points snapped to the stage, and a turn of the
 * carrier is never corrected. Points snapped at the wrong well, or a carrier
 * sitting turned in its holder, made the points disagree by millimetres,
 * and they were averaged without a word. Correcting a turn is a decision
 * still to be made; saying that the points disagree is not.
 */

import { describe, expect, it } from "vitest";
import { ANCHORS_AGREE_WITHIN_UM, anchorDisagreementUm, anchorWarning } from "./alignment.ts";

/* A point on the drawing at (x, y), snapped where the stage stood: the
   carrier's zero is at (1000, 2000) on the stage, plus whatever `off` adds. */
const snapped = (x: number, y: number, off = [0, 0]) => ({ x, y, stage: { x: 1000 + x + off[0], y: 2000 + y + off[1] } });

describe("how far the alignment points disagree", () => {
  it("is nothing to say with fewer than two points snapped", () => {
    expect(anchorDisagreementUm([])).toBeNull();
    expect(anchorDisagreementUm([snapped(0, 0), { x: 5000, y: 0 }])).toBeNull();
  });

  it("is zero for points that all say the same shift", () => {
    expect(anchorDisagreementUm([snapped(0, 0), snapped(80000, 0), snapped(0, 50000)])).toBe(0);
  });

  it("is the farthest any point lies from the shift they agree on on average", () => {
    /* One point snapped 3 mm off in x: the average moves by 1 mm, and that
       point lies 2 mm from it. */
    const points = [snapped(0, 0), snapped(80000, 0), snapped(0, 50000, [3000, 0])];
    expect(anchorDisagreementUm(points)).toBeCloseTo(2000, 6);
  });
});

describe("what the operator is told", () => {
  it("says nothing while the points agree within the tolerance", () => {
    const close = [snapped(0, 0), snapped(80000, 0, [ANCHORS_AGREE_WITHIN_UM / 2, 0])];
    expect(anchorWarning(close)).toBeNull();
  });

  it("says by how much they disagree, and what that may mean", () => {
    const points = [snapped(0, 0), snapped(80000, 0), snapped(0, 50000, [3000, 0])];
    expect(anchorWarning(points)).toBe(
      "The alignment points disagree by up to 2.0 mm. The carrier may be turned in its holder, "
      + "or a point was snapped at the wrong place; only the average shift is corrected, so "
      + "snap the points again or check how the carrier sits.",
    );
  });

  it("says small disagreements in micrometres", () => {
    const points = [snapped(0, 0), snapped(80000, 0, [700, 0])];
    expect(anchorWarning(points)).toMatch(/^The alignment points disagree by up to 350 µm\./);
  });
});
