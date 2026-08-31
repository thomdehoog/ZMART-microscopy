/**
 * The gating rules, pinned as behavior — Thom's dictated design:
 * a gate is one polygon on one feature pair; one polygon per plot; gates
 * accumulate in a list; the selection is the intersection of them all; a
 * plot shows its own pair's gate or none.
 */

import { describe, expect, it } from "vitest";
import {
  cellFeature, cellsInAllGates, featureNames, gateForPair, insidePolygon,
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
});
