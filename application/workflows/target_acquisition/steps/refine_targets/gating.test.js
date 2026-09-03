/**
 * The gating rules, pinned as behavior — Thom's dictated design:
 * a gate is one polygon on one feature pair; one polygon per plot; gates
 * accumulate in a list; the selection is the intersection of them all; a
 * plot shows its own pair's gate or none.
 */

import { describe, expect, it } from "vitest";
import {
  cellFeature, cellsInAllGates, featureNames, gateForPair, insidePolygon,
  keptUnderCeiling, sursDraw,
} from "./gating.js";

const cell = (id, features, more = {}) => ({
  id, area: features.area ?? 1, intensity: features.intensity ?? 1,
  features, ...more,
});

const square = (fx, fy, lo, hi) => ({
  fx, fy,
  vertices: [[lo, lo], [hi, lo], [hi, hi], [lo, hi]],
});

describe("the gating rules", () => {
  it("a polygon knows its inside, edges and winding regardless", () => {
    const poly = [[0, 0], [10, 0], [10, 10], [0, 10]];
    expect(insidePolygon(5, 5, poly)).toBe(true);
    expect(insidePolygon(15, 5, poly)).toBe(false);
    expect(insidePolygon(5, 5, [...poly].reverse())).toBe(true);
  });

  it("a concave polygon keeps its notch outside", () => {
    const notched = [[0, 0], [10, 0], [10, 10], [5, 3], [0, 10]];
    expect(insidePolygon(5, 8, notched)).toBe(false);
    expect(insidePolygon(2, 2, notched)).toBe(true);
  });

  it("the selection is the cells inside EVERY gate", () => {
    const cells = [
      cell("a", { size: 5, glow: 5, round: 5 }),
      cell("b", { size: 5, glow: 5, round: 50 }),
      cell("c", { size: 50, glow: 5, round: 5 }),
    ];
    const gates = [square("size", "glow", 0, 10), square("round", "glow", 0, 10)];
    expect([...cellsInAllGates(cells, gates)].sort()).toEqual(["a"]);
  });

  it("no gates selects nothing rather than everything", () => {
    expect(cellsInAllGates([cell("a", { size: 1 })], []).size).toBe(0);
  });

  it("a plot shows its own pair's gate or none", () => {
    const gates = [square("size", "glow", 0, 10), square("round", "glow", 0, 10)];
    expect(gateForPair(gates, "size", "glow")).toBe(gates[0]);
    expect(gateForPair(gates, "glow", "size")).toBeUndefined();
    expect(gateForPair(gates, "size", "round")).toBeUndefined();
  });

  it("features are read off the cell's own row, with the legacy pair kept", () => {
    const c = cell("a", { odd_moment: 7 });
    expect(cellFeature(c, "odd_moment")).toBe(7);
    expect(cellFeature(c, "area")).toBe(1);
    const names = featureNames([c]);
    expect(names).toContain("odd_moment");
    expect(names).toContain("area");
    expect(names).toContain("intensity");
  });


  it("a systematic draw spreads over the area instead of clumping", () => {
    /* 100 cells on a 10x10 lattice; a fixed random start makes the draw
       deterministic. 25 asked for: every quadrant must contribute its share,
       which a shuffle cannot promise and SURS does by construction. */
    const lattice = [];
    for (let gx = 0; gx < 10; gx++) {
      for (let gy = 0; gy < 10; gy++) {
        lattice.push({ id: `c${gx}-${gy}`, x: gx * 10, y: gy * 10 });
      }
    }
    const drawn = sursDraw(lattice, 25, () => 0.5);
    expect(drawn).toHaveLength(25);
    expect(new Set(drawn).size).toBe(25);
    const counts = { nw: 0, ne: 0, sw: 0, se: 0 };
    for (const id of drawn) {
      const cell = lattice.find((c) => c.id === id);
      const key = `${cell.y < 45 ? "n" : "s"}${cell.x < 45 ? "w" : "e"}`;
      counts[key] += 1;
    }
    for (const share of Object.values(counts)) {
      expect(share).toBeGreaterThanOrEqual(4);
      expect(share).toBeLessThanOrEqual(9);
    }
  });

  it("a pool smaller than the ask is returned whole", () => {
    const few = [{ id: "a", x: 0, y: 0 }, { id: "b", x: 5, y: 5 }];
    expect(sursDraw(few, 50, () => 0.5).sort()).toEqual(["a", "b"]);
  });

  it("the same random start draws the same sample", () => {
    const cells = Array.from({ length: 40 }, (_, i) => ({
      id: `c${i}`, x: (i * 37) % 100, y: (i * 53) % 100,
    }));
    expect(sursDraw(cells, 10, () => 0.25)).toEqual(sursDraw(cells, 10, () => 0.25));
  });
});

describe("the ceiling, applied by the Restrict press", () => {
  const spread = (tileset, n) => Array.from({ length: n }, (_, i) => ({
    id: `${tileset}-${i}`, x: (i * 37) % 100, y: (i * 53) % 100, field: tileset,
  }));
  const tilesetOf = (field) => field;

  it("keeps at most the ceiling in every tileset, drawn from the gated cells alone", () => {
    const cells = [...spread("A", 12), ...spread("B", 3), ...spread("C", 9)];
    const gated = new Set(cells.filter((c) => c.field !== "C").map((c) => c.id));
    const kept = keptUnderCeiling(cells, gated, 5, tilesetOf, () => 0.5);
    const inA = [...kept].filter((id) => id.startsWith("A-"));
    const inB = [...kept].filter((id) => id.startsWith("B-"));
    expect(inA.length).toBe(5);
    expect(inB.sort()).toEqual(["B-0", "B-1", "B-2"]);
    expect([...kept].every((id) => gated.has(id)), "nothing outside the gates is drawn").toBe(true);
  });

  it("a ceiling nothing reaches keeps the gated cells whole", () => {
    const cells = spread("A", 4);
    const gated = new Set(cells.map((c) => c.id));
    expect([...keptUnderCeiling(cells, gated, 50, tilesetOf, () => 0.5)].sort()).toEqual([...gated].sort());
  });
});
