import { describe, expect, it } from "vitest";
import { overlapShare, placeScanAreas } from "./scan-areas.js";

describe("placing scan areas under a maximum overlap", () => {
  it("measures the share of a frame another of the same size covers", () => {
    expect(overlapShare({ x: 0, y: 0 }, { x: 0, y: 0 }, 100)).toBe(1);
    expect(overlapShare({ x: 0, y: 0 }, { x: 50, y: 0 }, 100)).toBe(0.5);
    expect(overlapShare({ x: 0, y: 0 }, { x: 50, y: 50 }, 100)).toBe(0.25);
    expect(overlapShare({ x: 0, y: 0 }, { x: 100, y: 0 }, 100)).toBe(0);
  });

  it("keeps the first of two neighbours and leaves the second to it", () => {
    const targets = [
      { id: "a", x: 0, y: 0 }, { id: "b", x: 20, y: 0 }, { id: "c", x: 300, y: 0 },
    ];
    const { placed, skipped } = placeScanAreas(targets, 100, 0.5);
    expect(placed.map((one) => one.id)).toEqual(["a", "c"]);
    expect(skipped).toEqual(["b"]);
    expect(placed[0]).toEqual({ id: "a", x: 0, y: 0, frameUm: 100 });
  });

  it("a maximum of one places every area, whatever the crowding", () => {
    const targets = [{ id: "a", x: 0, y: 0 }, { id: "b", x: 1, y: 1 }];
    expect(placeScanAreas(targets, 100, 1).placed).toHaveLength(2);
  });

  it("a maximum of nought places areas that touch but do not overlap", () => {
    const targets = [{ id: "a", x: 0, y: 0 }, { id: "b", x: 100, y: 0 }, { id: "c", x: 99, y: 0 }];
    const { placed, skipped } = placeScanAreas(targets, 100, 0);
    expect(placed.map((one) => one.id)).toEqual(["a", "b"]);
    expect(skipped).toEqual(["c"]);
  });
});
