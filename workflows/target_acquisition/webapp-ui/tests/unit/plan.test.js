import { describe, it, expect } from "vitest";
import { plan } from "../../workflows/target_acquisition/steps/3_define_scan_area/scanfield-editor.js";
import {
  carrierType, fromPreset, nearestArea, scanBox,
} from "../../workflows/target_acquisition/shared/carriers.js";

/* A 96-well plate: wells 6.6 mm across, 9 mm apart, the first centred on
   (3.3, 3.3) mm and the second on (12.3, 3.3). Fields are in micrometres from
   the carrier's own zero, which is what the editor hands the plan. */
const plate = fromPreset("wellplate",
  carrierType("wellplate").presets.find((p) => p.label.startsWith("96-well")));
const hires = { id: "p", frameUm: 102 };
const overview = { id: "p", frameUm: 2662 };

/** Which well each tile of the plan landed in, as row.col strings. */
const wells = (tiles) => new Set(tiles.map((t) => {
  const a = nearestArea(plate, t.x / 1000, t.y / 1000);
  return `${a.row}.${a.col}`;
}));

/** A rectangle in micrometres, given its two corners in millimetres. */
const strip = (x0, x1) => ({
  id: "f1", type: "rectangle", rotation: 0,
  x: x0 * 1000, y: 2.8 * 1000, w: (x1 - x0) * 1000, h: 1000,
});

describe("a field is imaged in one area, the one it covers most", () => {
  it("takes the well the outline mostly lies in, not both it reaches", () => {
    /* Across the first well and a little way into the second: 5.6 mm of the
       outline lies in the first, 4.0 mm in the second. */
    const tiles = plan([strip(1.0, 13.0)], hires, plate);
    expect(tiles.length).toBeGreaterThan(0);
    expect(wells(tiles)).toEqual(new Set(["0.0"]));
  });

  it("and the other well when the outline mostly lies there", () => {
    const tiles = plan([strip(5.5, 15.0)], hires, plate);
    expect(wells(tiles)).toEqual(new Set(["0.1"]));
  });

  it("counts each field on its own, so two fields can be two wells", () => {
    const a = { ...strip(1.0, 13.0), id: "a" };
    const b = { ...strip(5.5, 15.0), id: "b" };
    expect(wells(plan([a, b], hires, plate))).toEqual(new Set(["0.0", "0.1"]));
  });

  it("images nothing at all for an outline that fits in no well", () => {
    // the plastic between the first two wells, and narrower than a 5x frame
    expect(plan([strip(7.2, 8.4)], overview, plate)).toEqual([]);
  });

  it("holds every tile inside the well it chose", () => {
    for (const t of plan([strip(1.0, 13.0)], hires, plate)) {
      const a = nearestArea(plate, t.x / 1000, t.y / 1000);
      expect(Math.hypot(t.x / 1000 - a.x, t.y / 1000 - a.y)).toBeLessThan(3.3);
    }
  });
});

describe("a region is covered right into its corners", () => {
  /* A slide: one area 75 x 25 mm with square corners, so the edges are exact
     numbers and what a tile does at a boundary is easy to state. */
  const slide = fromPreset("slide",
    carrierType("slide").presets.find((p) => p.label.startsWith("Standard")));
  const tenx = { id: "p", frameUm: 1331 };
  const corner = {
    id: "f", type: "rectangle", rotation: 0, x: 0, y: 0, w: 10000, h: 8000,
  };

  it("pushes the whole lattice in rather than dropping the edge tiles", () => {
    const tiles = plan([corner], tenx, slide);
    const half = tenx.frameUm / 2;
    const left = Math.min(...tiles.map((t) => t.x));
    const top = Math.min(...tiles.map((t) => t.y));
    // the outermost frames sit flush with the edge of what can be imaged,
    // which on a slide is its rectangle with the soft corners cut back
    const edgeX = (37.5 - scanBox(slide).halfW) * 1000;
    const edgeY = (12.5 - scanBox(slide).halfH) * 1000;
    expect(left).toBeCloseTo(edgeX + half, 2);
    expect(top).toBeCloseTo(edgeY + half, 2);
  });

  it("keeps the step it was given, so the overlap does not change", () => {
    const tiles = plan([corner], tenx, slide);
    const step = (axis) => {
      const line = [...new Set(tiles.map((t) => Math.round(t[axis])))].sort((a, b) => a - b);
      return line.slice(1).map((v, i) => v - line[i]);
    };
    // one step, the preset's frame, between every pair of neighbours
    for (const gap of [...step("x"), ...step("y")]) expect(gap).toBe(tenx.frameUm);
  });

  it("keeps every frame inside the area", () => {
    const half = tenx.frameUm / 2;
    const box = scanBox(slide);
    for (const t of plan([corner], tenx, slide)) {
      expect(Math.abs(t.x / 1000 - 37.5) + half / 1000).toBeLessThanOrEqual(box.halfW);
      expect(Math.abs(t.y / 1000 - 12.5) + half / 1000).toBeLessThanOrEqual(box.halfH);
    }
  });

  it("covers the outline it was drawn as, corner included", () => {
    const half = tenx.frameUm / 2;
    const tiles = plan([corner], tenx, slide);
    expect(Math.max(...tiles.map((t) => t.x)) + half).toBeGreaterThanOrEqual(corner.w);
    expect(Math.max(...tiles.map((t) => t.y)) + half).toBeGreaterThanOrEqual(corner.h);
  });

  it("counts a position visited twice once", () => {
    const tiles = plan([corner], tenx, slide);
    const spots = new Set(tiles.map((t) => `${t.x}.${t.y}`));
    expect(spots.size).toBe(tiles.length);
  });
});

describe("a position is not slid anywhere: it fits where it was put or it is not in the plan", () => {
  const slide = fromPreset("slide",
    carrierType("slide").presets.find((p) => p.label.startsWith("Standard")));
  const at = (xMm, yMm) => ({ id: "p1", type: "point", x: xMm * 1000, y: yMm * 1000 });

  it("keeps one whose frame fits", () => {
    expect(plan([at(10, 10)], overview, slide)).toHaveLength(1);
  });

  it("drops one pressed into the corner, where the frame would hang over", () => {
    expect(plan([at(0.1, 0.1)], overview, slide)).toEqual([]);
  });
});

describe("no frame is laid that takes in none of the region", () => {
  const slide = fromPreset("slide",
    carrierType("slide").presets.find((p) => p.label.startsWith("Standard")));
  const tenx = { id: "p", frameUm: 1331 };

  /** Whether a frame there overlaps the box the field occupies, at all. */
  const meets = (t, f, frameUm) => {
    const half = frameUm / 2;
    return t.x + half > f.x && t.x - half < f.x + f.w
      && t.y + half > f.y && t.y - half < f.y + f.h;
  };

  const cases = {
    "well clear of every edge": { x: 20000, y: 8000, w: 7600, h: 5200 },
    "over the edge of the area": { x: -3000, y: 6000, w: 9000, h: 6000 },
    "in the corner of the area": { x: 0, y: 0, w: 10000, h: 8000 },
    "narrower than one frame": { x: 30000, y: 9000, w: 700, h: 4000 },
  };

  for (const [what, box] of Object.entries(cases)) {
    it(`holds for a region ${what}`, () => {
      const f = { id: "f", type: "rectangle", rotation: 0, ...box };
      const laid = plan([f], tenx, slide);
      expect(laid.length).toBeGreaterThan(0);
      for (const t of laid) expect(meets(t, f, tenx.frameUm)).toBe(true);
    });
  }
});
