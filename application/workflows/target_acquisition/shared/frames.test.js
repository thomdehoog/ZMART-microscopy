/**
 * A place on the carrier and the same place on the stage differ by where the
 * carrier sits -- the origin alignment measures. Everything handed to the
 * instrument must go out in the stage's frame and come back in the carrier's.
 * On the mock the two happened to line up for as long as nobody aligned; on
 * an aligned Leica every focus point drove to the wrong place.
 */

import { describe, expect, it } from "vitest";

/* The converters as stage.js writes them, over an origin a test can set. */
function converters(origin) {
  const toStage = (p) => ({ ...p, x: p.x + origin[0], y: p.y + origin[1] });
  const toCarrier = (p) => ({ ...p, x: p.x - origin[0], y: p.y - origin[1] });
  return { toStage, toCarrier };
}

describe("carrier and stage frames", () => {
  it("a point handed to the instrument is shifted by the carrier's origin", () => {
    const { toStage } = converters([53_000, 27_500]);
    expect(toStage({ x: 1_000, y: 2_000, z: 8 })).toEqual({ x: 54_000, y: 29_500, z: 8 });
  });

  it("what the instrument reports comes back where it was laid", () => {
    const { toStage, toCarrier } = converters([53_000, 27_500]);
    const laid = { x: 1_000, y: 2_000, traces: { brenner: {} } };
    expect(toCarrier(toStage(laid))).toEqual(laid);
  });

  it("everything else on the point rides along untouched", () => {
    const { toStage } = converters([10, 20]);
    const p = { x: 0, y: 0, z: 5, startZ: 4, manual: true };
    expect(toStage(p)).toEqual({ ...p, x: 10, y: 20 });
  });
});
