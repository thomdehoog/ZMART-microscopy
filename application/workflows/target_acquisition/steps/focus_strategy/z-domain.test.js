import { describe, expect, it } from "vitest";
import { zColourScale } from "./z-domain.js";

describe("the colour scale of the focus surface", () => {
  it("gives the middle of the ramp a fixed seventy micrometres about the median", () => {
    const scale = zColourScale([-10, 5, 30], [0, 5, 30]);
    expect(scale.t(-30)).toBeCloseTo(0.15);
    expect(scale.t(5)).toBeCloseTo(0.5);
    expect(scale.t(40)).toBeCloseTo(0.85);
    expect(scale.t(12)).toBeCloseTo(0.57);
  });

  it("reports the map's own extent for the legend to crop the ramp to", () => {
    const scale = zColourScale([2, 3, 4], [2, 3, 4]);
    expect([scale.min, scale.max, scale.spread]).toEqual([2, 4, 2]);
    // one micrometre is one percent of the ramp
    expect(scale.t(4) - scale.t(2)).toBeCloseTo(0.02);
  });

  it("stretches the outer band to a surface that reaches past the fixed span", () => {
    const scale = zColourScale([-200, 0, 80], [0, 10, -10]);
    expect(scale.t(-200)).toBeCloseTo(0);
    expect(scale.t(-35)).toBeCloseTo(0.15);
    expect(scale.t(80)).toBeCloseTo(1);
    expect(scale.t(35)).toBeCloseTo(0.85);
  });

  it("does not let one wild point move the colours of the rest", () => {
    const steady = zColourScale([0, 20], [0, 10, 20]);
    const withOne = zColourScale([0, 20, 900], [0, 10, 20, 900]);
    // the median moved five micrometres, so the colours moved five percent, not the wild point's nine hundred
    expect(Math.abs(withOne.t(10) - steady.t(10))).toBeCloseTo(0.05);
  });
});
