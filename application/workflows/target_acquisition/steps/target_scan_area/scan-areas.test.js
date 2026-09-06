import { describe, expect, it } from "vitest";
import {
  coveredBy, coveredByTiles, objectReachUm, overlapShare, planScanAreas,
  repeatedOverlap,
} from "./scan-areas.js";

/* An object as the detector reports it: area in µm² on the cell, area and
   the fitted ellipse's axes in pixels among its features. At 1 µm per pixel
   an object of 100 px² with a major axis of 20 px reaches 10 µm. */
const object = (id, x, y, { major = 20, areaPx = 100, pixelUm = 1 } = {}) => ({
  id, x, y, area: areaPx * pixelUm * pixelUm,
  features: { area: areaPx, axis_major_length: major },
});

/* An independent coverage oracle. It neither reads `tile.covers` nor calls a
   planner coverage helper: target and tile edges partition the requested
   footprint into cells, and every cell must lie in a real tile rectangle. */
const oracleReach = (target, margin) => {
  const px = Number(target.features?.area);
  const um = Number(target.area);
  const pixelUm = px > 0 && um > 0 ? Math.sqrt(um / px) : 1;
  const major = Number(target.features?.axis_major_length);
  const own = Number.isFinite(major) && major > 0
    ? major * pixelUm / 2
    : um > 0 ? Math.sqrt(um / Math.PI) : 0;
  return own * (1 + Math.max(0, Number(margin) || 0));
};

const oracleCovered = (target, tiles, frameUm, margin) => {
  const reach = oracleReach(target, margin);
  const wanted = {
    x0: target.x - reach, x1: target.x + reach,
    y0: target.y - reach, y1: target.y + reach,
  };
  const rectangles = tiles.map((tile) => {
    const half = (tile.frameUm ?? frameUm) / 2;
    return { x0: tile.x - half, x1: tile.x + half, y0: tile.y - half, y1: tile.y + half };
  }).filter((tile) => tile.x1 >= wanted.x0 && tile.x0 <= wanted.x1
    && tile.y1 >= wanted.y0 && tile.y0 <= wanted.y1);
  if (reach <= 1e-9) return rectangles.some((tile) =>
    tile.x0 <= target.x && tile.x1 >= target.x
    && tile.y0 <= target.y && tile.y1 >= target.y);
  const edges = (lo, hi, starts, ends) => [...new Set([
    lo, hi,
    ...starts.map((value) => Math.max(lo, value)),
    ...ends.map((value) => Math.min(hi, value)),
  ])].filter((value) => value >= lo && value <= hi).sort((a, b) => a - b);
  const xs = edges(wanted.x0, wanted.x1,
    rectangles.map((tile) => tile.x0), rectangles.map((tile) => tile.x1));
  const ys = edges(wanted.y0, wanted.y1,
    rectangles.map((tile) => tile.y0), rectangles.map((tile) => tile.y1));
  for (let ix = 1; ix < xs.length; ix++) for (let iy = 1; iy < ys.length; iy++) {
    if (xs[ix] - xs[ix - 1] <= 1e-9 || ys[iy] - ys[iy - 1] <= 1e-9) continue;
    const x = (xs[ix] + xs[ix - 1]) / 2;
    const y = (ys[iy] + ys[iy - 1]) / 2;
    if (!rectangles.some((tile) => tile.x0 <= x && tile.x1 >= x
      && tile.y0 <= y && tile.y1 >= y)) return false;
  }
  return rectangles.length > 0;
};

/* Independent bounded minimum-set-cover oracle for ordinary targets. */
const oracleMinimumCount = (targets, frameUm, margin) => {
  const half = frameUm / 2;
  const ranges = targets.map((target) => {
    const slack = half - oracleReach(target, margin);
    return { x0: target.x - slack, x1: target.x + slack,
      y0: target.y - slack, y1: target.y + slack };
  });
  const xs = [...new Set(ranges.flatMap((range) => [range.x0, range.x1]))];
  const ys = [...new Set(ranges.flatMap((range) => [range.y0, range.y1]))];
  const masks = [...new Set(xs.flatMap((x) => ys.map((y) => ranges.reduce(
    (mask, range, i) => mask | (x >= range.x0 && x <= range.x1
      && y >= range.y0 && y <= range.y1 ? (1 << i) : 0), 0))))].filter(Boolean);
  const full = (1 << targets.length) - 1;
  let reached = new Set([0]);
  for (let count = 1; count <= targets.length; count++) {
    reached = new Set([...reached].flatMap((mask) => masks.map((candidate) => mask | candidate)));
    if (reached.has(full)) return count;
  }
  return Infinity;
};

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

  it("requires the actual union of a stitched tileset to cover the footprint", () => {
    const target = object("large", 0, 0, { major: 120 });
    const covered = [-40, 40].flatMap((x) => [-40, 40].map((y) => ({ x, y, frameUm: 100 })));
    const displaced = [10, 90].flatMap((x) => [10, 90].map((y) => ({ x, y, frameUm: 100 })));
    expect(coveredByTiles(target, covered, 100, 0)).toBe(true);
    expect(coveredByTiles(target, displaced, 100, 0)).toBe(false);
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

  it("with minimising off, centres one tile on every target, neighbours or not", () => {
    const targets = [object("a", 0, 0), object("b", 30, 0), object("c", 600, 0)];
    const plain = planScanAreas(targets, 100, { margin: 0, minimise: false });
    expect(plain.placed.map((tile) => [tile.x, tile.y])).toEqual([[0, 0], [30, 0], [600, 0]]);
    expect(plain.placed.map((tile) => tile.key)).toEqual(["a#0", "b#0", "c#0"]);
    expect(plain.uncovered).toEqual([]);
    const fewest = planScanAreas(targets, 100, { margin: 0 });
    expect(fewest.placed).toHaveLength(2);
  });

  it("with minimising off, a target larger than a frame still gets its stitched raster", () => {
    const big = object("big", 0, 0, { major: 120 });
    const plain = planScanAreas([big, object("small", 400, 0)], 100, { margin: 0, overlap: { min: 0.2 }, minimise: false });
    const forBig = plain.placed.filter((tile) => tile.targetId === "big");
    expect(forBig.length).toBeGreaterThan(1);
    expect(plain.placed.filter((tile) => tile.targetId === "small")).toHaveLength(1);
    expect(plain.uncovered).toEqual([]);
  });

  it("minimises the tile count instead of accepting a suboptimal greedy cover", () => {
    /* The most crowded first tile leaves three isolated choices. A different
       three-tile cover exists, and is the minimum. This exact arrangement is
       a regression for the former greedy-only planner, which used four. */
    const points = [
      [51, 210], [126, 82], [131, 89], [69, 128],
      [95, 31], [103, 68], [79, 70], [166, 65],
    ];
    const targets = points.map(([x, y], i) => object(String(i), x, y));
    const { placed, uncovered } = planScanAreas(targets, 100, { margin: 0 });
    expect(placed).toHaveLength(3);
    expect(new Set(placed.flatMap((area) => area.covers))).toEqual(
      new Set(targets.map((target) => target.id)));
    expect(uncovered).toEqual([]);
  });

  it("covers a target larger than one frame with Step 3's fixed stitching overlap", () => {
    const target = object("big", 0, 0, { major: 120 });
    const { placed, uncovered } = planScanAreas([target], 100, {
      margin: 0, overlap: { min: 0.2 },
    });
    expect(placed).toHaveLength(4);
    expect(uncovered).toEqual([]);
    expect(new Set(placed.map((tile) => tile.targetId))).toEqual(new Set(["big"]));
    const xs = [...new Set(placed.map((tile) => tile.x))].sort((a, b) => a - b);
    const ys = [...new Set(placed.map((tile) => tile.y))].sort((a, b) => a - b);
    expect(xs).toEqual([-40, 40]);
    expect(ys).toEqual([-40, 40]);
    expect(xs[1] - xs[0]).toBeCloseTo(80, 6);
    expect(ys[1] - ys[0]).toBeCloseTo(80, 6);
    expect(coveredByTiles(target, placed, 100, 0)).toBe(true);
    expect(placed.flatMap((tile) => tile.completes)).toEqual(["big"]);
  });

  it("gives every tile of a large target its own acquisition key", () => {
    const target = object("big", 0, 0, { major: 140 });
    const { placed } = planScanAreas([target], 128, {
      margin: 1, overlap: { min: 0.2 },
    });
    expect(placed).toHaveLength(9);
    expect(new Set(placed.map((tile) => tile.key)).size).toBe(placed.length);
    expect(placed.map((tile) => tile.key)).toEqual(
      placed.map((_, index) => `big#${index}`));
  });

  it("shares one stitching lattice between overlapping large targets", () => {
    const targets = [
      object("a", 0, 0, { major: 120 }),
      object("b", 20, 0, { major: 120 }),
    ];
    const { placed, uncovered } = planScanAreas(targets, 100, {
      margin: 0, overlap: { min: 0.2 },
    });
    expect(placed).toHaveLength(4);
    expect(new Set(placed.flatMap((tile) => tile.covers))).toEqual(new Set(["a", "b"]));
    expect(uncovered).toEqual([]);
  });

  it("does not add a separate tile for a small target inside a stitched block", () => {
    const targets = [
      object("large", 0, 0, { major: 120 }),
      object("small", 45, 0),
    ];
    const { placed, uncovered } = planScanAreas(targets, 100, {
      margin: 0, overlap: { min: 0.2 },
    });
    expect(placed).toHaveLength(4);
    expect(new Set(placed.flatMap((tile) => tile.covers))).toContain("small");
    expect(uncovered).toEqual([]);
  });

  it("does not let a chain of ordinary margins enlarge a stitched raster", () => {
    const large = object("large", 0, 0, { major: 120 });
    const ordinary = [65, 85, 105, 125, 145]
      .map((x, i) => object(`small-${i}`, x, 0));
    const { placed, uncovered } = planScanAreas([large, ...ordinary], 100, {
      margin: 0, overlap: { min: 0.2 },
    });
    /* Four tiles are the large target's 2 x 2 stitched block. One ordinary
       tile contains the remaining small targets; their touching footprints
       do not extend the raster into a third stitched column. */
    expect(placed).toHaveLength(5);
    expect(uncovered).toEqual([]);
    expect(coveredByTiles(large, placed, 100, 0)).toBe(true);
    ordinary.forEach((target) => expect(coveredByTiles(target, placed, 100, 0)).toBe(true));
  });

});

describe("stitching belongs to one multi-tile target", () => {
  it("does not force two independently placed areas to reacquire more ground", () => {
    const targets = [object("a", 0, 0), object("b", 95, 0)];
    const { placed, notes } = planScanAreas(targets, 100, { margin: 0, overlap: { min: 0.2 } });
    expect(placed).toHaveLength(2);
    expect(overlapShare(placed[0], placed[1], 100)).toBe(0);
    expect(notes).toEqual([]);
  });

  it("minimises repeated ground after choosing a minimum-count cover", () => {
    const targets = [0, 60, 120].map((x, i) => object(String(i), x, 0));
    const { placed, uncovered } = planScanAreas(targets, 128, { margin: 0 });
    expect(placed).toHaveLength(2);
    expect(uncovered).toEqual([]);
    expect(repeatedOverlap(placed, [], 128)).toBe(0);
  });

  it("tests joint diagonal seats when one-axis moves cannot reduce overlap", () => {
    const targets = [[81, 57], [61, 142], [171, 44], [154, 126]]
      .map(([x, y], i) => object(String(i), x, y));
    const { placed, uncovered } = planScanAreas(targets, 100, { margin: 0 });
    expect(placed).toHaveLength(3);
    expect(uncovered).toEqual([]);
    expect(repeatedOverlap(placed, [], 100)).toBeLessThanOrEqual(70 + 1e-9);
  });

  it("never trades union coverage for less repeated ground", () => {
    const targets = [[119, 9], [63, 170], [26, 40], [109, 51], [191, 36], [94, 92]]
      .map(([x, y], i) => object(String(i), x, y));
    const plan = planScanAreas(targets, 100, { margin: 0 });
    expect(plan.uncovered).toEqual([]);
    targets.forEach((target) =>
      expect(oracleCovered(target, plan.placed, 100, 0), target.id).toBe(true));
  });

  it("minimises true repeated area in a multi-tile cluster", () => {
    const targets = [[78, 17], [46, 97], [176, 171], [148, 111], [90, 3], [104, 55], [152, 217]]
      .map(([x, y], i) => object(String(i), x, y));
    const plan = planScanAreas(targets, 100, { margin: 0 });
    expect(plan.uncovered).toEqual([]);
    expect(repeatedOverlap(plan.placed, [], 100)).toBeLessThanOrEqual(64 + 1e-9);
  });

  it("areas that do not meet are left where they are", () => {
    const targets = [object("a", 0, 0), object("b", 300, 0)];
    const { placed } = planScanAreas(targets, 100, { margin: 0, overlap: { min: 0.2 } });
    expect(placed.map((one) => one.x)).toEqual([0, 300]);
  });

  it("an internal stitching overlap is not refused by the external maximum", () => {
    const target = object("big", 0, 0, { major: 120 });
    const { placed, uncovered } = planScanAreas([target], 100, {
      margin: 0, overlap: { min: 0.5, max: 0.2 },
    });
    expect(placed).toHaveLength(4);
    expect(uncovered).toEqual([]);
  });
});

describe("the edges of placing", () => {
  it("no targets is an empty plan with nothing to say", () => {
    expect(planScanAreas([], 100, { margin: 1 })).toEqual({ placed: [], uncovered: [], leftOut: [], notes: [] });
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

  it("an explicitly switched-off margin adds no ring", () => {
    const target = object("a", 0, 0);
    expect(planScanAreas([target], 20, { margin: null }).placed).toHaveLength(1);
    const withDefaultMargin = planScanAreas([target], 20, {});
    expect(withDefaultMargin.placed.length).toBeGreaterThan(1);
    expect(withDefaultMargin.uncovered).toEqual([]);
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

  it("objects of different pixel sizes reach in micrometres alike", () => {
    const fine = object("fine", 0, 0, { pixelUm: 0.5 });   // 20 px major at 0.5 -> 5 µm
    const coarse = object("coarse", 0, 0, { pixelUm: 2 }); // 20 px major at 2 -> 20 µm
    expect(objectReachUm(fine)).toBe(5);
    expect(objectReachUm(coarse)).toBe(20);
  });
});

describe("independent geometry acceptance", () => {
  const large = (id, x, y, major = 120) => object(id, x, y, { major });
  const bare = (id, x, y) => ({ id, x, y, area: Math.PI * 25, features: {} });
  const zero = { id: "zero", x: 17, y: -23, area: 0, features: {} };
  const cases = [
    ["margin switched off", [object("a", 0, 0), object("b", 60, 0)], 100, { margin: null }],
    ["no margin", [object("a", 0, 0), object("b", 95, 0)], 100, { margin: 0 }],
    ["one-target-size margin", [object("a", 0, 0), object("b", 70, 20)], 100, { margin: 1 }],
    ["two-target-size margin", [object("a", 0, 0), object("b", 140, 30)], 128, { margin: 2 }],
    ["negative coordinates", [object("a", -180, -40), object("b", -120, -40)], 100, { margin: 1 }],
    ["duplicate positions", [object("a", 5, 5), object("b", 5, 5)], 100, { margin: 1 }],
    ["missing ellipse", [bare("bare", 0, 0), object("b", 55, 0)], 100, { margin: 1 }],
    ["zero-size target", [zero], 100, { margin: 2 }],
    ["exact one-frame fit", [object("fit", 0, 0, { major: 50 })], 100, { margin: 1 }],
    ["epsilon over one frame", [object("over", 0, 0, { major: 50.01 })], 100, { margin: 1, overlap: { min: 0.2 } }],
    ["one large target at zero overlap", [large("big", 0, 0)], 100, { margin: 0, overlap: { min: 0 } }],
    ["one large target at twenty-percent overlap", [large("big", 0, 0)], 100, { margin: 0, overlap: { min: 0.2 } }],
    ["one large target at ninety-percent overlap", [large("big", 0, 0)], 100, { margin: 0, overlap: { min: 0.9 } }],
    ["overlapping large targets", [large("a", 0, 0), large("b", 20, 0)], 100, { margin: 0, overlap: { min: 0.2 } }],
    ["ordinary chain beside a large target", [large("big", 0, 0), ...[65, 85, 105, 125, 145].map((x, i) => object(`s${i}`, x, 0))], 100, { margin: 0, overlap: { min: 0.2 } }],
  ];

  it.each(cases.flatMap(([name, targets, frameUm, rules]) => [
    [name, targets, frameUm, rules],
    [`${name}, reversed input`, [...targets].reverse(), frameUm, rules],
    [`${name}, one tile per target`, targets, frameUm, { ...rules, minimise: false }],
  ]))("agrees with the tile rectangles for %s", (_name, targets, frameUm, rules) => {
    const plan = planScanAreas(targets, frameUm, rules);
    const margin = rules.margin === null ? 0 : rules.margin ?? 1;
    const missing = targets.filter((target) =>
      !oracleCovered(target, plan.placed, frameUm, margin)).map((target) => target.id).sort();
    expect([...plan.uncovered].sort()).toEqual(missing);
  });

  it.each([
    ["a line", [object("a", 0, 0), object("b", 60, 0), object("c", 120, 0)]],
    ["two clusters", [object("a", 0, 0), object("b", 40, 0), object("c", 300, 0)]],
    ["a square", [[0, 0], [60, 0], [0, 60], [60, 60]].map(([x, y], i) => object(String(i), x, y))],
    ["the former greedy counterexample", [
      [51, 210], [126, 82], [131, 89], [69, 128],
      [95, 31], [103, 68], [79, 70], [166, 65],
    ].map(([x, y], i) => object(String(i), x, y))],
  ])("matches an exhaustive minimum set cover for %s", (_name, targets) => {
    const plan = planScanAreas(targets, 100, { margin: 0 });
    expect(plan.placed).toHaveLength(oracleMinimumCount(targets, 100, 0));
  });
});
