import { describe, it, expect } from "vitest";
import {
  block, bounds, boxesOverlap, centroid, contains, edges, handles, isPointLike,
  normalise, rotatePoint, segmentHitsBox, sharePoints, snapSpan, tiles,
  topCentre, withoutTrailingDuplicate,
} from "../../workflows/target_acquisition/shared/scanfields.js";
import { carrierType, centres, fromPreset, geometry } from "../../workflows/target_acquisition/shared/carriers.js";

/* The plate, named rather than taken from whatever a fresh run happens to
   start on: these are about a grid of areas with gaps between them, which is
   what a plate is and what the default carrier is not. */
const PLATE = fromPreset("wellplate",
  carrierType("wellplate").presets.find((p) => p.label.startsWith("96-well")));

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
    const areas = centres(PLATE);
    const g = geometry(PLATE);
    expect(areas).toHaveLength(96);
    // the first well's centre is half a well in from the carrier's zero, and
    // the next is one pitch along — not the carrier width divided by columns,
    // which would ignore the gap and drift by a third of a well at the edge
    expect(areas[0].x).toBeCloseTo(PLATE.w / 2, 6);
    expect(areas[1].x - areas[0].x).toBeCloseTo(g.pitchX, 6);
    const evenly = g.width / PLATE.cols;
    expect(Math.abs(areas[11].x - (11.5 * evenly))).toBeGreaterThan(1);
  });

  it("puts one block in every area the carrier declares", () => {
    const made = centres(PLATE)
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
  /* What a double-click leaves behind: the press that finishes the outline
     placed a vertex too, so the last two land in the same spot. */
  it("drops a vertex the double-click repeated, and keeps one that moved", () => {
    const three = [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }];
    expect(withoutTrailingDuplicate([...three, { x: 10.5, y: 10.2 }], 4)).toEqual(three);
    const moved = [...three, { x: 14, y: 10 }];
    expect(withoutTrailingDuplicate(moved, 4)).toEqual(moved);
  });

  it("leaves a list too short to have a duplicate alone", () => {
    expect(withoutTrailingDuplicate([], 4)).toEqual([]);
    expect(withoutTrailingDuplicate([{ x: 1, y: 1 }], 4)).toEqual([{ x: 1, y: 1 }]);
  });

  /* The threshold is in the points' own units, so the caller converts screen
     pixels at the current zoom rather than fixing a distance in micrometres. */
  it("takes the same pair as the same place or not, by the threshold given", () => {
    const pts = [{ x: 0, y: 0 }, { x: 5, y: 0 }, { x: 5, y: 3 }, { x: 5, y: 3.5 }];
    expect(withoutTrailingDuplicate(pts, 1)).toHaveLength(3);
    expect(withoutTrailingDuplicate(pts, 0.1)).toHaveLength(4);
  });
});


describe("a region is sized in whole frames", () => {
  const FRAME = 1331;

  it("takes the frames that fit inside what was drawn, and no more", () => {
    // 2.9 frames drawn comes back as 2: the third would reach past the hand
    expect(snapSpan(FRAME * 2.9, FRAME)).toBeCloseTo(FRAME * 2, 6);
    expect(snapSpan(FRAME * 3.01, FRAME)).toBeCloseTo(FRAME * 3, 6);
  });

  it("leaves a size that is already whole frames exactly where it is", () => {
    expect(snapSpan(FRAME * 4, FRAME)).toBeCloseTo(FRAME * 4, 6);
  });

  it("never goes below one frame, however small the drag", () => {
    expect(snapSpan(10, FRAME)).toBe(FRAME);
    expect(snapSpan(0, FRAME)).toBe(FRAME);
  });

  it("counts in steps when the frames overlap, since that is what is stepped", () => {
    /* At 50% overlap a frame advances half its width, so three frames span
       two: 2 comes back whole, and 1.4 comes back as the single frame that
       fits — a second would reach 1.5, past the hand. */
    expect(snapSpan(FRAME * 2, FRAME, 50)).toBeCloseTo(FRAME * 2, 6);
    expect(snapSpan(FRAME * 1.4, FRAME, 50)).toBeCloseTo(FRAME, 6);
  });

  it("is what the tiles then fill, edge to edge", () => {
    const w = snapSpan(9000, FRAME), h = snapSpan(6000, FRAME);
    const f = { id: "f", type: "rectangle", rotation: 0, x: 4000, y: 3000, w, h };
    const laid = tiles(f, FRAME, 0);
    const half = FRAME / 2;
    expect(Math.min(...laid.map((t) => t.x)) - half).toBeCloseTo(f.x, 6);
    expect(Math.max(...laid.map((t) => t.x)) + half).toBeCloseTo(f.x + w, 6);
    expect(Math.min(...laid.map((t) => t.y)) - half).toBeCloseTo(f.y, 6);
    expect(Math.max(...laid.map((t) => t.y)) + half).toBeCloseTo(f.y + h, 6);
  });
});


describe("focus points take an equal share of the field each", () => {
  /* A field of 6 x 4 positions, 100 µm apart: the numbers are easy to read
     back, and the shape is wide enough that a good split cuts it into columns
     before it cuts it into rows. */
  const grid = [];
  for (let row = 0; row < 4; row++) {
    for (let col = 0; col < 6; col++) grid.push({ x: col * 100, y: row * 100 });
  }

  it("one point sits in the middle, not in a corner", () => {
    const [only] = sharePoints(grid, 1);
    expect(only.x).toBeGreaterThan(0);
    expect(only.x).toBeLessThan(500);
    expect(only.y).toBeGreaterThan(0);
    expect(only.y).toBeLessThan(300);
  });

  it("two points split the long way, and neither is on the rim", () => {
    const two = sharePoints(grid, 2);
    expect(two).toHaveLength(2);
    const xs = two.map((t) => t.x).sort((a, b) => a - b);
    expect(xs[0]).toBeGreaterThan(0);
    expect(xs[1]).toBeLessThan(500);
    // and they are a long way apart: this is a spread, not a pair of neighbours
    expect(xs[1] - xs[0]).toBeGreaterThanOrEqual(200);
  });

  it("four points come one from each quarter", () => {
    const four = sharePoints(grid, 4);
    expect(four).toHaveLength(4);
    const quarters = new Set(four.map((t) => `${t.x < 250 ? "l" : "r"}${t.y < 150 ? "t" : "b"}`));
    expect(quarters.size, "one to a quarter").toBe(4);
  });

  it("never picks the same position twice", () => {
    for (const n of [2, 3, 5, 7]) {
      const picked = sharePoints(grid, n);
      expect(new Set(picked.map((t) => `${t.x},${t.y}`)).size, `${n} points`)
        .toBe(picked.length);
    }
  });

  it("asks for more than there are and gets what there is", () => {
    expect(sharePoints(grid, 99)).toHaveLength(grid.length);
  });

  it("answers the same way twice, so a map does not shift under a rerun", () => {
    expect(sharePoints(grid, 5)).toEqual(sharePoints(grid, 5));
  });

  /* Nine frames, three by three, and six points asked for. Six over nine is
     the case that shows whether the ground is being measured or only the
     positions' centres: with the centres alone, three points end up owning two
     frames each and settle on the seam between them while the top row is left
     with nothing — a true fixed point of Lloyd's, for nine dots. What a frame
     covers is a square of sample, so the six shares should come out as two rows
     of three, each row a quarter of the way in from its end. */
  it("shares out the ground a frame covers, not the point at its middle", () => {
    const nine = [];
    for (let row = 0; row < 3; row++) {
      for (let col = 0; col < 3; col++) {
        nine.push({ x: col * 100, y: row * 100, frameUm: 100 });
      }
    }
    const six = sharePoints(nine, 6);
    expect(six).toHaveLength(6);

    // two rows of three, and neither row on a seam between frames
    const rows = [...new Set(six.map((p) => Math.round(p.y / 5) * 5))].sort((a, b) => a - b);
    expect(rows, `six points at ${six.map((p) => p.y.toFixed(0)).join(", ")}`)
      .toHaveLength(2);
    for (const y of rows) {
      expect(six.filter((p) => Math.abs(p.y - y) < 3), "three to a row").toHaveLength(3);
      for (const seam of [50, 150]) {
        expect(Math.abs(y - seam), `a row at ${y.toFixed(0)} sits on the seam at ${seam}`)
          .toBeGreaterThan(20);
      }
    }
    // a quarter of the way in from each end of the block, which spans -50..250
    expect(rows[0]).toBeGreaterThan(0);
    expect(rows[0]).toBeLessThan(50);
    expect(rows[1]).toBeGreaterThan(150);
    expect(rows[1]).toBeLessThan(200);

    // and three columns, spread the same way
    const cols = [...new Set(six.map((p) => Math.round(p.x / 5) * 5))].sort((a, b) => a - b);
    expect(cols).toHaveLength(3);
  });

  /* Seven over the same nine frames. An odd share has to go somewhere, and the
     one place a block cannot afford to leave empty is its own middle: rows of
     three, two and two put the spare share along the top and left a hole
     through the centre of the block that nothing spoke for. */
  it("keeps a share in the middle when the number does not divide evenly", () => {
    const nine = [];
    for (let row = 0; row < 3; row++) {
      for (let col = 0; col < 3; col++) {
        nine.push({ x: col * 100, y: row * 100, frameUm: 100 });
      }
    }
    const seven = sharePoints(nine, 7);
    expect(seven).toHaveLength(7);
    const middle = Math.min(...seven.map((p) => Math.hypot(p.x - 100, p.y - 100)));
    expect(middle, `the nearest to the middle is ${middle.toFixed(0)} away`)
      .toBeLessThan(50);
  });

  /* Five over the same nine frames. How many rows to deal the shares in is not
     something a formula can be trusted with: three rows of two, one and two —
     the four corners with one in the middle — covers a square block more evenly
     than two rows of three and two, and measurably so. */
  it("puts one in the middle of five, which two rows of shares cannot", () => {
    const nine = [];
    for (let row = 0; row < 3; row++) {
      for (let col = 0; col < 3; col++) {
        nine.push({ x: col * 100, y: row * 100, frameUm: 100 });
      }
    }
    const five = sharePoints(nine, 5);
    expect(five).toHaveLength(5);

    const middle = five.filter((p) => Math.hypot(p.x - 100, p.y - 100) < 30);
    expect(middle, `five at ${five.map((p) => `${p.x.toFixed(0)},${p.y.toFixed(0)}`).join("  ")}`)
      .toHaveLength(1);
    // and the other four are the corners of the block, one to a quarter
    const corners = new Set(five.filter((p) => !middle.includes(p))
      .map((p) => `${p.x < 100 ? "l" : "r"}${p.y < 100 ? "t" : "b"}`));
    expect(corners.size, "one to each corner").toBe(4);
  });

  it("stays inside the ground the positions cover", () => {
    /* A focus point is a place the stage is driven to, not a frame the run
       images, so it need not sit on a position — but it must be somewhere the
       sample is, which for a filled rectangle is inside its extent. */
    for (const p of sharePoints(grid, 6)) {
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.x).toBeLessThanOrEqual(500);
      expect(p.y).toBeGreaterThanOrEqual(0);
      expect(p.y).toBeLessThanOrEqual(300);
    }
  });
});


describe("the points settle into the shape, not into its bounding box", () => {
  /* A triangle of positions: a wide bottom row narrowing to a single position
     at the top, which is the case equal rectangular shares get wrong — a share
     cut from the corner of the box holds almost nothing. */
  const triangle = [];
  for (let row = 0; row < 5; row++) {
    const wide = 9 - row * 2;
    for (let col = 0; col < wide; col++) {
      triangle.push({ x: (col + row) * 100, y: row * 100 });
    }
  }

  /** How far each position is from the nearest point measured, at worst. */
  const worstDistance = (points) => Math.max(...triangle.map((t) =>
    Math.min(...points.map((p) => Math.hypot(t.x - p.x, t.y - p.y)))));

  it("gives every point a share of the positions to stand for", () => {
    const points = sharePoints(triangle, 4);
    const held = points.map(() => 0);
    for (const t of triangle) {
      let best = 0, bestD = Infinity;
      points.forEach((p, i) => {
        const d = Math.hypot(t.x - p.x, t.y - p.y);
        if (d < bestD) { best = i; bestD = d; }
      });
      held[best] += 1;
    }
    for (const n of held) expect(n, "no point stands for nothing").toBeGreaterThan(0);
  });

  it("leaves no position far from the nearest point", () => {
    // the triangle is 900 wide and 400 tall; four points settled into it put
    // nothing further than a third of its width from one
    expect(worstDistance(sharePoints(triangle, 4))).toBeLessThan(300);
  });

  it("has settled: measuring again moves nothing", () => {
    const once = sharePoints(triangle, 4);
    expect(sharePoints(triangle, 4)).toEqual(once);
  });

  it("hands back as many places as asked for, all different", () => {
    const points = sharePoints(triangle, 6);
    expect(new Set(points.map((t) => `${t.x},${t.y}`)).size).toBe(6);
    // and each of them has positions of its own around it, nowhere off the shape
    for (const p of points) {
      const near = Math.min(...triangle.map((t) => Math.hypot(t.x - p.x, t.y - p.y)));
      expect(near, "no point stranded away from the sample").toBeLessThan(150);
    }
  });
});
