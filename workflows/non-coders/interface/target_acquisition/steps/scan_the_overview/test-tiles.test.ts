import { describe, it, expect } from "vitest";
import { afterMarquee, spreadTestTiles, tilesInBox } from "./test-tiles.ts";

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

/* Four wells in a row, a block of three by three frames in each. */
const wells = [0, 1, 2, 3].flatMap((w) =>
  [0, 1, 2].flatMap((r) => [0, 1, 2].map((c) => ({
    x: w * 1000 + c * 100, y: r * 100, frameUm: 100, tileset: `well ${w}`, compartment: w, group: 0,
  }))));
const wellOf = (i: number) => wells[i].tileset;

describe("the box picks test tiles spread as the focus points are", () => {
  it("so many in each tileset", () => {
    const picked = spreadTestTiles(wells, 2, "tileset");
    expect(picked).toHaveLength(8);
    for (const w of ["well 0", "well 1", "well 2", "well 3"]) {
      expect(picked.filter((i) => wellOf(i) === w)).toHaveLength(2);
    }
  });

  it("or so many over the whole carrier, shared out between the wells", () => {
    const picked = spreadTestTiles(wells, 4, "carrier");
    expect(picked).toHaveLength(4);
    expect(new Set(picked.map(wellOf)).size).toBe(4);
  });

  it("never more than the plan holds, and never one tile twice", () => {
    for (const over of ["tileset", "carrier"] as const) {
      const picked = spreadTestTiles(wells, 100, over);
      expect(picked).toHaveLength(wells.length);
      expect(new Set(picked).size).toBe(wells.length);
    }
  });

  it("over the carrier, identical wells do not all give the same tile", () => {
    const within = spreadTestTiles(wells, 4, "carrier").map((i) => i % 9);
    expect(new Set(within).size).toBeGreaterThan(1);
  });
});
