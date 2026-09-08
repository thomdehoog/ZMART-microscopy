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

import { windowForTheLook } from "./auto-window.js";

// a background of many dim pixels in bins 0..5, tissue in 10..30, a bright object in 90..99
const withBackground = {
  low: 0, high: 1000,
  counts: Array.from({ length: 100 }, (_, i) =>
    (i < 5 ? 200 : i >= 10 && i < 30 ? 40 : i >= 90 ? 20 : 0)),
};

describe("the window the one-press look asks for", () => {
  it("puts the background under the window and keeps the bright object inside it", () => {
    const { low, high } = windowForTheLook(withBackground);
    expect(low).toBeGreaterThanOrEqual(50);
    expect(low).toBeLessThan(150);
    expect(high).toBeGreaterThan(900);
  });

  it("starts just above the background whatever share of the frame it is", () => {
    const mostlyCells = {
      low: 0, high: 1000,
      counts: Array.from({ length: 100 }, (_, i) =>
        (i < 5 ? 30 : i >= 10 && i < 60 ? 40 : i >= 90 ? 20 : 0)),
    };
    const { low } = windowForTheLook(mostlyCells);
    expect(low).toBeGreaterThanOrEqual(50);
    expect(low).toBeLessThan(150);
  });

  it("has nothing to say about an empty or flat histogram", () => {
    expect(windowForTheLook({ low: 0, high: 10, counts: [] })).toBeNull();
    expect(windowForTheLook({ low: 5, high: 5, counts: [3] })).toBeNull();
  });
});
