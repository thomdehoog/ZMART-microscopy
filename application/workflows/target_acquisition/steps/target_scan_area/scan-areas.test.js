import { describe, expect, it } from "vitest";
import { coveredBy, objectReachUm, overlapShare, planScanAreas } from "./scan-areas.js";

/* An object as the detector reports it: area in µm² on the cell, area and
   the fitted ellipse's axes in pixels among its features. At 1 µm per pixel
   an object of 100 px² with a major axis of 20 px reaches 10 µm. */
const object = (id, x, y, { major = 20, areaPx = 100, pixelUm = 1 } = {}) => ({
  id, x, y, area: areaPx * pixelUm * pixelUm,
  features: { area: areaPx, axis_major_length: major },
});

describe("what an object reaches", () => {
  it("is half its fitted major axis, in micrometres from its own pixel size", () => {
    expect(objectReachUm(object("a", 0, 0))).toBe(10);
    expect(objectReachUm(object("a", 0, 0, { pixelUm: 2 }))).toBe(20);
  });

  it("falls back to a disc of its area when no ellipse was fitted", () => {
    const bare = { id: "a", x: 0, y: 0, area: Math.PI * 25, features: {} };
    expect(objectReachUm(bare)).toBeCloseTo(5, 6);
  });

  it("is covered when it lies inside the area with its margin whole", () => {
    const o = object("a", 0, 0);
    // reach 10, margin 100 % -> 20 must fit either side of the centre
    expect(coveredBy(o, { x: 0, y: 0 }, 100, 1)).toBe(true);
    expect(coveredBy(o, { x: 30, y: 0 }, 100, 1)).toBe(true);
    expect(coveredBy(o, { x: 31, y: 0 }, 100, 1)).toBe(false);
    expect(coveredBy(o, { x: 40, y: 0 }, 100, 0)).toBe(true);
  });
});

describe("the share of one frame another covers", () => {
  it("is the intersection over the frame", () => {
    expect(overlapShare({ x: 0, y: 0 }, { x: 0, y: 0 }, 100)).toBe(1);
    expect(overlapShare({ x: 0, y: 0 }, { x: 50, y: 0 }, 100)).toBe(0.5);
    expect(overlapShare({ x: 0, y: 0 }, { x: 100, y: 0 }, 100)).toBe(0);
  });
});

describe("placing scan areas", () => {
  it("takes neighbours into one area when they fit, and covers every one", () => {
    const targets = [object("a", 0, 0), object("b", 30, 0), object("c", 300, 0)];
    const { placed, uncovered } = planScanAreas(targets, 100, { margin: 1 });
    expect(placed).toHaveLength(2);
    expect(placed[0].covers.sort()).toEqual(["a", "b"]);
    expect(placed[0].x).toBe(15);
    expect(placed[1].covers).toEqual(["c"]);
    expect(uncovered).toEqual([]);
  });

  it("leaves an area out when it would overlap a placed one past the maximum", () => {
    const targets = [object("a", 0, 0), object("b", 70, 0)];
    const { placed, uncovered, leftOut } = planScanAreas(targets, 100, { margin: 1, overlap: { max: 0.2 } });
    expect(placed.map((one) => one.id)).toEqual(["a"]);
    expect(leftOut).toEqual(["b"]);
    expect(uncovered).toEqual(["b"]);
  });

  it("stops at the maximum when the areas are preferred, and places on when coverage is", () => {
    const targets = [object("a", 0, 0), object("b", 300, 0), object("c", 600, 0)];
    const stopped = planScanAreas(targets, 100, { areas: { max: 2 }, prefer: "areas" });
    expect(stopped.placed).toHaveLength(2);
    expect(stopped.uncovered).toEqual(["c"]);
    expect(stopped.notes[0]).toMatch(/stopped at 2/);
    const covered = planScanAreas(targets, 100, { areas: { max: 2 }, prefer: "coverage" });
    expect(covered.placed).toHaveLength(3);
    expect(covered.notes[0]).toMatch(/past the maximum of 2/);
  });

  it("says when the minimum cannot be reached, and when an object outgrows a frame", () => {
    const targets = [object("a", 0, 0), object("big", 500, 0, { major: 200 })];
    const { placed, uncovered, notes } = planScanAreas(targets, 100, { margin: 1, areas: { min: 3 } });
    expect(placed).toHaveLength(1);
    expect(uncovered).toEqual(["big"]);
    expect(notes.join(" ")).toMatch(/under the minimum of 3/);
    expect(notes.join(" ")).toMatch(/larger than a frame/);
  });

  it("joins into one scan stepped by the minimum overlap", () => {
    const targets = [object("a", 0, 0), object("b", 150, 0), object("c", 300, 0)];
    const { placed, uncovered } = planScanAreas(targets, 100, {
      margin: 0, overlap: { min: 0.5, join: true },
    });
    // 50 µm steps from x = -10 across to 310: six areas, adjacent ones
    // overlapping by half, the whole extent one piece
    expect(placed).toHaveLength(6);
    for (let i = 1; i < placed.length; i++) {
      expect(placed[i].x - placed[i - 1].x).toBeCloseTo(50, 6);
    }
    expect(uncovered).toEqual([]);
  });
});

describe("the edges of placing", () => {
  it("no targets is an empty plan with nothing to say", () => {
    expect(planScanAreas([], 100, { margin: 1 })).toEqual({ placed: [], uncovered: [], leftOut: [], notes: [] });
    expect(planScanAreas([], 100, { overlap: { min: 0.5, join: true } }).placed).toEqual([]);
  });

  it("no frame places nothing and says why", () => {
    const { placed, uncovered, notes } = planScanAreas([object("a", 0, 0)], 0, {});
    expect(placed).toEqual([]);
    expect(uncovered).toEqual(["a"]);
    expect(notes[0]).toMatch(/import the target acquisition settings/);
  });

  it("one target gets one area centred on it", () => {
    const { placed } = planScanAreas([object("a", 12, -7)], 100, { margin: 1 });
    expect(placed).toHaveLength(1);
    expect(placed[0]).toMatchObject({ id: "a", x: 12, y: -7, frameUm: 100, covers: ["a"] });
  });

  it("an object that exactly fills the frame with its margin is still placed", () => {
    // reach 10, margin 400 % -> 50 either side: exactly the frame
    const { placed, uncovered } = planScanAreas([object("a", 0, 0)], 100, { margin: 4 });
    expect(placed).toHaveLength(1);
    expect(uncovered).toEqual([]);
  });

  it("a margin below nought counts as nought", () => {
    const strict = planScanAreas([object("a", 0, 0), object("b", 60, 0)], 100, { margin: -5 });
    const plain = planScanAreas([object("a", 0, 0), object("b", 60, 0)], 100, { margin: 0 });
    expect(strict.placed).toEqual(plain.placed);
  });

  it("two objects on one spot share one area", () => {
    const { placed, uncovered } = planScanAreas([object("a", 5, 5), object("b", 5, 5)], 100, { margin: 1 });
    expect(placed).toHaveLength(1);
    expect(placed[0].covers.sort()).toEqual(["a", "b"]);
    expect(uncovered).toEqual([]);
  });

  it("nudging never lets the anchor out of its own area", () => {
    // neighbours pulling in every direction; each placed area still holds its anchor
    const ring = [object("a", 0, 0), ...[0, 60, 120, 180, 240, 300].map((deg, i) =>
      object(`n${i}`, 45 * Math.cos((deg * Math.PI) / 180), 45 * Math.sin((deg * Math.PI) / 180)))];
    const { placed, uncovered } = planScanAreas(ring, 100, { margin: 1 });
    for (const area of placed) {
      const anchor = ring.find((one) => one.id === area.id);
      expect(coveredBy(anchor, area, 100, 1), `${area.id} holds its anchor`).toBe(true);
    }
    expect(uncovered).toEqual([]);
  });

  it("a maximum overlap of one refuses nothing, of nought refuses any overlap but allows touching", () => {
    // a and b too far apart to share an area; c too far from b to share one,
    // yet its own area would overlap b's by a tenth
    const targets = [object("a", 0, 0), object("b", 100, 0), object("c", 190, 0)];
    expect(planScanAreas(targets, 100, { margin: 0, overlap: { max: 1 } }).leftOut).toEqual([]);
    const strict = planScanAreas(targets, 100, { margin: 0, overlap: { max: 0 } });
    // a's area (-50..50) and b's (50..150) touch: share nought, allowed
    expect(strict.placed.map((one) => one.id)).toEqual(["a", "b"]);
    expect(strict.leftOut).toEqual(["c"]);
    expect(strict.uncovered).toEqual(["c"]);
  });

  it("a maximum of nought areas stops at once when areas are preferred, and ignores itself for coverage", () => {
    const targets = [object("a", 0, 0), object("b", 300, 0)];
    const stopped = planScanAreas(targets, 100, { areas: { max: 0 }, prefer: "areas" });
    expect(stopped.placed).toEqual([]);
    expect(stopped.uncovered).toEqual(["a", "b"]);
    const covered = planScanAreas(targets, 100, { areas: { max: 0 }, prefer: "coverage" });
    expect(covered.placed).toHaveLength(2);
  });

  it("the overlap maximum still holds when coverage is preferred past the area maximum", () => {
    const targets = [object("a", 0, 0), object("b", 300, 0), object("c", 310, 0, { major: 2 })];
    // c sits 10 from b: b's area (nudged over both) covers c already, so nothing overlaps
    const plan = planScanAreas(targets, 100, { margin: 0, areas: { max: 1 }, prefer: "coverage", overlap: { max: 0 } });
    expect(plan.placed).toHaveLength(2);
    expect(plan.uncovered).toEqual([]);
  });

  it("a joined scan with a minimum overlap of one still ends", () => {
    const { placed } = planScanAreas([object("a", 0, 0), object("b", 200, 0)], 100, { margin: 0, overlap: { min: 1, join: true } });
    expect(placed.length).toBeGreaterThan(0);
    expect(placed.length).toBeLessThan(100);
  });

  it("a joined scan says which objects its tiles cannot hold whole", () => {
    const { placed, uncovered, notes } = planScanAreas([object("big", 0, 0, { major: 200 })], 100, { margin: 0, overlap: { min: 0, join: true } });
    expect(placed.length).toBeGreaterThan(0);
    expect(uncovered).toEqual(["big"]);
    expect(notes.join(" ")).toMatch(/not held whole/);
  });

  it("objects of different pixel sizes reach in micrometres alike", () => {
    const fine = object("fine", 0, 0, { pixelUm: 0.5 });   // 20 px major at 0.5 -> 5 µm
    const coarse = object("coarse", 0, 0, { pixelUm: 2 }); // 20 px major at 2 -> 20 µm
    expect(objectReachUm(fine)).toBe(5);
    expect(objectReachUm(coarse)).toBe(20);
  });
});
