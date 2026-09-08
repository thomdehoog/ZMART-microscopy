/* The window Auto asks for, at the saturation the operator chose. */
import { describe, expect, it } from "vitest";
import { windowFromHistogram } from "./auto-window.js";

// a hundred bins over 0..1000: dim tissue in bins 10..30, a bright object in bins 90..99
const histogram = {
  low: 0, high: 1000,
  counts: Array.from({ length: 100 }, (_, i) => (i >= 10 && i < 30 ? 40 : i >= 90 ? 20 : 0)),
};

describe("the window Auto asks for", () => {
  it("at one percent the bright object holds the top of the window", () => {
    const { low, high } = windowFromHistogram(histogram, 1);
    expect(low).toBeCloseTo(105);
    expect(high).toBeGreaterThan(900);
  });

  it("at twenty percent the bright object saturates and the tissue fills the window", () => {
    const { low, high } = windowFromHistogram(histogram, 20);
    expect(high).toBeLessThan(300);
    expect(low).toBeGreaterThan(100);
  });

  it("has nothing to say about an empty or flat histogram", () => {
    expect(windowFromHistogram({ low: 0, high: 10, counts: [] }, 1)).toBeNull();
    expect(windowFromHistogram({ low: 5, high: 5, counts: [3] }, 1)).toBeNull();
  });
});
