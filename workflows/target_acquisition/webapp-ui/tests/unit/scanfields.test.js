import { describe, it, expect } from "vitest";
import {
  block, bounds, boxesOverlap, centroid, contains, edges, handles, isPointLike,
  normalise, rotatePoint, segmentHitsBox, tiles, topCentre,
} from "../../src/lib/scanfields.js";
import { centres, DEFAULT_CARRIER, geometry } from "../../src/lib/carriers.js";

const rect = (x, y, w, h, rotation = 0) => ({ type: "rectangle", x, y, w, h, rotation });

describe("a field knows where it is, rotated or not", () => {
  it("holds a point inside a rectangle and refuses one outside", () => {
    const r = rect(0, 0, 100, 50);
    expect(contains(50, 25, r)).toBe(true);
    expect(contains(150, 25, r)).toBe(false);
  });

  it("turns with its rotation rather than testing the box it was drawn in", () => {
    // a 100 x 20 bar turned a quarter turn is tall, not wide
    const r = rect(-50, -10, 100, 20, Math.PI / 2);
    expect(contains(0, 40, r), "along the turned long axis").toBe(true);
    expect(contains(40, 0, r), "across it").toBe(false);
  });

  it("measures an ellipse by its own radii", () => {
    const e = { type: "ellipse", cx: 0, cy: 0, rx: 100, ry: 50, rotation: 0 };
    expect(contains(99, 0, e)).toBe(true);
    expect(contains(0, 51, e)).toBe(false);
  });

  it("a rotated ellipse's box touches where its tangent turns level", () => {
    const e = { type: "ellipse", cx: 0, cy: 0, rx: 100, ry: 50, rotation: Math.PI / 2 };
    const b = bounds(e);
    // the quarter turn swaps the half-widths exactly; the rotated corners of
    // the unturned box would have claimed 100 in both directions
    expect(b.xMax).toBeCloseTo(50, 6);
    expect(b.yMax).toBeCloseTo(100, 6);
  });

  it("a circle arrives as an ellipse, so nothing downstream needs both", () => {
    const c = normalise({ type: "circle", cx: 5, cy: 6, r: 7 });
    expect(c.type).toBe("ellipse");
    expect([c.rx, c.ry]).toEqual([7, 7]);
    expect(contains(11, 6, c)).toBe(true);
  });
});

describe("tiles cover what the field touches, not only what it centres on", () => {
  it("covers a region the frame's size in one tile", () => {
    expect(tiles(rect(0, 0, 100, 100), 1000)).toHaveLength(1);
  });

  it("steps by the frame, so a wider region takes proportionally more", () => {
    const one = tiles(rect(0, 0, 900, 900), 1000).length;
    const four = tiles(rect(0, 0, 1900, 1900), 1000).length;
    expect(one).toBe(1);
    expect(four).toBe(4);
  });

  it("overlap shortens the step, so the same region takes more tiles", () => {
    const plain = tiles(rect(0, 0, 4000, 1000), 1000, 0).length;
    const lapped = tiles(rect(0, 0, 4000, 1000), 1000, 50).length;
    expect(lapped).toBeGreaterThan(plain);
  });

  it("keeps a sliver no tile centre lands in", () => {
    /* A long thin bar between two rows of tile centres is exactly what a
       centres-only test drops, and it is still sample. */
    const sliver = rect(0, 0, 5000, 20);
    const covering = tiles(sliver, 1000);
    expect(covering.length).toBeGreaterThanOrEqual(5);
    for (const t of covering) expect(Math.abs(t.y - 10)).toBeLessThan(1000);
  });

  it("a point is one position and needs no covering", () => {
    expect(tiles({ type: "point", x: 12, y: 34 }, 1000)).toEqual([{ x: 12, y: 34 }]);
    expect(isPointLike("point")).toBe(true);
  });

  it("refuses to tile without a frame, rather than looping forever", () => {
    expect(tiles(rect(0, 0, 1000, 1000), 0)).toEqual([]);
    expect(tiles(rect(0, 0, 1000, 1000), 1000, 100)).toEqual([]);
  });

  it("covers a rotated rectangle over its turned extent", () => {
    const flat = tiles(rect(0, 0, 4000, 500), 1000).length;
    const turned = tiles(rect(0, 0, 4000, 500, Math.PI / 2), 1000).length;
    expect(turned).toBeGreaterThanOrEqual(flat - 1);
  });
});

describe("the grid block is centred on what it is given", () => {
  it("spans (n - 1) pitches, so an odd count sits one on the centre", () => {
    const b = block({ x: 0, y: 0 }, 3, 3, 100, 100);
    expect(b).toHaveLength(9);
    expect(b).toContainEqual({ x: 0, y: 0 });
    expect(Math.min(...b.map((p) => p.x))).toBeCloseTo(-100, 6);
    expect(Math.max(...b.map((p) => p.x))).toBeCloseTo(100, 6);
  });

  it("and an even count straddles it", () => {
    const b = block({ x: 0, y: 0 }, 2, 2, 100, 100);
    expect(b).toHaveLength(4);
    expect(b.some((p) => p.x === 0 && p.y === 0)).toBe(false);
  });

  it("takes its centres from the carrier, gaps and all", () => {
    const areas = centres(DEFAULT_CARRIER);
    const g = geometry(DEFAULT_CARRIER);
    expect(areas).toHaveLength(96);
    // the first well's centre is half a well in from the carrier's zero, and
    // the next is one pitch along — not the carrier width divided by columns,
    // which would ignore the gap and drift by a third of a well at the edge
    expect(areas[0].x).toBeCloseTo(DEFAULT_CARRIER.w / 2, 6);
    expect(areas[1].x - areas[0].x).toBeCloseTo(g.pitchX, 6);
    const evenly = g.width / DEFAULT_CARRIER.cols;
    expect(Math.abs(areas[11].x - (11.5 * evenly))).toBeGreaterThan(1);
  });

  it("puts one block in every area the carrier declares", () => {
    const made = centres(DEFAULT_CARRIER)
      .flatMap((a) => block({ x: a.x * 1000, y: a.y * 1000 }, 3, 3, 2662, 2662));
    expect(made).toHaveLength(96 * 9);
  });
});

describe("the grips a field offers", () => {
  it("gives a rectangle eight, an ellipse four, a polygon one per vertex", () => {
    expect(handles(rect(0, 0, 10, 10))).toHaveLength(8);
    expect(handles({ type: "ellipse", cx: 0, cy: 0, rx: 5, ry: 5 })).toHaveLength(4);
    const poly = { type: "polygon", points: [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 0, y: 1 }] };
    expect(handles(poly)).toHaveLength(3);
    expect(handles(poly)[2].index).toBe(2);
  });

  it("hangs the rotation grip off the highest vertex, not above the centroid", () => {
    const poly = { type: "polygon", points: [{ x: 0, y: 40 }, { x: 30, y: 0 }, { x: 60, y: 40 }] };
    expect(topCentre(poly)).toEqual({ x: 30, y: 0 });
    expect(centroid(poly).y).toBeCloseTo(80 / 3, 6);
  });
});

describe("the pieces the editor leans on", () => {
  it("rotates about a centre", () => {
    const p = rotatePoint(1, 0, 0, 0, Math.PI / 2);
    expect(p.x).toBeCloseTo(0, 6);
    expect(p.y).toBeCloseTo(1, 6);
  });

  it("finds a segment crossing a box it starts and ends outside of", () => {
    expect(segmentHitsBox(-10, 5, 20, 5, 0, 0, 10, 10)).toBe(true);
    expect(segmentHitsBox(-10, 50, 20, 50, 0, 0, 10, 10)).toBe(false);
  });

  it("closes a field's outline, so an edge test sees every side", () => {
    expect(edges(rect(0, 0, 10, 10))).toHaveLength(4);
  });

  it("overlaps boxes that touch", () => {
    expect(boxesOverlap({ xMin: 0, yMin: 0, xMax: 1, yMax: 1 }, { xMin: 1, yMin: 1, xMax: 2, yMax: 2 })).toBe(true);
    expect(boxesOverlap({ xMin: 0, yMin: 0, xMax: 1, yMax: 1 }, { xMin: 2, yMin: 2, xMax: 3, yMax: 3 })).toBe(false);
  });
});
