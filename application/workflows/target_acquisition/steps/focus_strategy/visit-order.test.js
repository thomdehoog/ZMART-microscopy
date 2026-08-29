/**
 * The order a focus map is visited in — pinned as behavior, because a stage
 * watched live must look deliberate: two levels of one rule. The tilesets
 * are swept as a serpentine of their centres, and each tileset's points as
 * a serpentine inside it, top-left first at both levels.
 */

import { describe, expect, it } from "vitest";
import { visitOrder } from "./visit-order.js";

const p = (x, y, more = {}) => ({ x, y, z: null, ...more });

describe("the order a focus map is visited in", () => {
  it("sweeps a grid like a page: top row left to right, next row back", () => {
    const grid = [p(20, 0), p(0, 10), p(10, 0), p(0, 0), p(20, 10), p(10, 10)];
    expect(visitOrder(grid).map(({ x, y }) => [x, y])).toEqual(
      [[0, 0], [10, 0], [20, 0], [20, 10], [10, 10], [0, 10]]);
  });

  it("keeps a jittered row together instead of splitting it", () => {
    const rows = [p(0, 0), p(10, 2), p(20, 1), p(20, 1000), p(10, 1002), p(0, 1001)];
    expect(visitOrder(rows).map(({ x }) => x)).toEqual([0, 10, 20, 20, 10, 0]);
  });

  it("sweeps the tilesets themselves shortest-path, whatever their tags", () => {
    const points = [
      p(9000, 0, { tileset: 0 }), p(0, 0, { tileset: 5 }), p(10, 0, { tileset: 5 }),
    ];
    expect(visitOrder(points).map(({ x }) => x)).toEqual([0, 10, 9000]);
  });

  it("sweeps the tilesets in rows too, next row swept back", () => {
    const wells = [
      p(0, 9000, { tileset: 0 }), p(9000, 9000, { tileset: 1 }),
      p(9000, 0, { tileset: 2 }), p(0, 0, { tileset: 3 }),
    ];
    expect(visitOrder(wells).map(({ x, y }) => [x, y])).toEqual(
      [[0, 0], [9000, 0], [9000, 9000], [0, 9000]]);
  });

  it("never interleaves tilesets, even one sitting between another's points", () => {
    const points = [
      p(0, 0, { tileset: 0 }), p(40, 0, { tileset: 0 }), p(30, 0, { tileset: 1 }),
    ];
    expect(visitOrder(points).map(({ x }) => x)).toEqual([0, 40, 30]);
  });

  it("visits hand-laid points outside every tileset last", () => {
    const points = [p(5, 5), p(9000, 9000, { tileset: 0 })];
    expect(visitOrder(points).map(({ x }) => x)).toEqual([9000, 5]);
  });

  it("carries every point whole -- a height travels with its place", () => {
    const measured = [p(10, 0, { z: 42 }), p(0, 0)];
    expect(visitOrder(measured)[0]).toEqual(p(0, 0));
    expect(visitOrder(measured)[1].z).toBe(42);
  });
});
