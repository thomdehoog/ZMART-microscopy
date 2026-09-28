import { describe, it, expect } from "vitest";
import { afterMarquee, tilesInBox } from "./test-tiles.js";

const plan = [
  { x: 0, y: 0 }, { x: 10, y: 0 }, { x: 20, y: 0 },
  { x: 0, y: 10 }, { x: 10, y: 10 }, { x: 20, y: 10 },
];

describe("a rectangle on the picture takes in the tiles whose centre it covers", () => {
  it("whichever corner the drag started from", () => {
    expect(tilesInBox(plan, { sx: -1, sy: -1, cx: 11, cy: 11 })).toEqual([0, 1, 3, 4]);
    expect(tilesInBox(plan, { sx: 11, sy: 11, cx: -1, cy: -1 })).toEqual([0, 1, 3, 4]);
  });

  it("takes nothing when it covers no centre", () => {
    expect(tilesInBox(plan, { sx: 1, sy: 1, cx: 9, cy: 9 })).toEqual([]);
  });
});

describe("a Shift-drag turns the tiles it took in green, or back", () => {
  it("turns a mix all green", () => {
    expect([...afterMarquee(new Set([0]), [0, 1, 4])].sort()).toEqual([0, 1, 4]);
  });

  it("turns tiles that were all green off again", () => {
    expect([...afterMarquee(new Set([0, 1, 4, 5]), [0, 1, 4])]).toEqual([5]);
  });

  it("leaves the set alone when the drag took nothing", () => {
    expect(afterMarquee(new Set([2]), [])).toEqual(new Set([2]));
  });
});
