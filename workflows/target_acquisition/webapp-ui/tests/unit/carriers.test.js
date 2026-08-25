import { describe, it, expect } from "vitest";
import {
  CARRIER_TYPES, carrierType, fromPreset, matchingPreset, geometry,
  maxRadius, DEFAULT_CARRIER,
  depthMm, describeCarrier,
  centres, nearestArea, frameFitsArea, frameSeat, insideArea, scanBox,
} from "../../workflows/target_acquisition/shared/carriers.js";

const preset = (typeId, label) =>
  carrierType(typeId).presets.find((p) => p.label.startsWith(label));

describe("a carrier is a grid, whatever it is called", () => {
  it("measures a 96-well plate the way the catalogue does", () => {
    const g = geometry(fromPreset("wellplate", preset("wellplate", "96-well")));
    // 12 columns of 6.6 mm with 2.4 mm between them, and the gap is not
    // counted after the last one
    expect(g.width).toBeCloseTo(12 * 9.0 - 2.4, 6);
    expect(g.height).toBeCloseTo(8 * 9.0 - 2.4, 6);
    expect(g.areas).toBe(96);
    expect(g.pitchX).toBeCloseTo(9.0, 6);
  });

  it("a slide is a one-by-one grid and no gap is involved", () => {
    const g = geometry(fromPreset("slide", preset("slide", "Standard")));
    expect([g.width, g.height]).toEqual([75, 25]);
    expect(g.areas).toBe(1);
  });
});

describe("the corner is a ratio, so a well stays round when resized", () => {
  it("reads a round preset as a full corner", () => {
    expect(fromPreset("dish", preset("dish", "35 mm")).cornerRatio).toBe(1);
  });

  it("and keeps it round at another diameter", () => {
    const c = { ...fromPreset("dish", preset("dish", "35 mm")), w: 12, h: 12 };
    expect(geometry(c).corner).toBeCloseTo(6, 6);
  });

  it("a chamber's softened corner survives a resize as a proportion", () => {
    const p = preset("chamber", "4-chamber");
    const c = fromPreset("chamber", p);
    // 1.5 mm on a 20 x 10 area, whose largest possible radius is 5
    expect(c.cornerRatio).toBeCloseTo(0.3, 6);
    expect(geometry({ ...c, w: 40, h: 20 }).corner).toBeCloseTo(3, 6);
  });

  it("a full round loses the corners a square would have kept", () => {
    const round = geometry({ rows: 1, cols: 1, w: 10, h: 10, gapX: 0, gapY: 0, cornerRatio: 1 });
    expect(round.areaMm2).toBeCloseTo(Math.PI * 25, 6);
    const square = geometry({ rows: 1, cols: 1, w: 10, h: 10, gapX: 0, gapY: 0, cornerRatio: 0 });
    expect(square.areaMm2).toBeCloseTo(100, 6);
  });

  it("the largest corner an area can take is half its short side", () => {
    expect(maxRadius({ w: 20, h: 10 })).toBe(5);
  });
});

describe("a configuration knows whether it is still a catalogue part", () => {
  it("recognises the preset it came from", () => {
    for (const type of CARRIER_TYPES) {
      type.presets.forEach((p, i) => {
        expect(matchingPreset(fromPreset(type.id, p)), `${type.id}/${p.label}`).toBe(i);
      });
    }
  });

  it("and stops claiming to be one once it is edited", () => {
    const c = fromPreset("wellplate", preset("wellplate", "24-well"));
    expect(matchingPreset({ ...c, cols: 7 })).toBe(-1);
    expect(matchingPreset({ ...c, w: c.w + 1 })).toBe(-1);
  });

  it("the default is one plain area, which assumes least about the run", () => {
    expect(DEFAULT_CARRIER.type).toBe("slide");
    const g = geometry(DEFAULT_CARRIER);
    expect(g.areas).toBe(1);
    expect([g.width, g.height]).toEqual([75, 25]);
  });

  it("and the plate this lab runs most is still in the catalogue, unchanged", () => {
    const plate = fromPreset("wellplate", preset("wellplate", "96-well"));
    const g = geometry(plate);
    expect(g.areas).toBe(96);
    expect([plate.rows, plate.cols]).toEqual([8, 12]);
    // Greiner's flat well bottom, on the SLAS 9 mm pitch
    expect(plate.w).toBeCloseTo(6.6, 6);
    expect(plate.h).toBeCloseTo(6.6, 6);
    expect(g.pitchX).toBeCloseTo(9.0, 6);
    expect(g.pitchY).toBeCloseTo(9.0, 6);
    // round: a full corner on a square area is a circle
    expect(plate.cornerRatio).toBe(1);
    expect(g.corner).toBeCloseTo(3.3, 6);
    // and it comes back to the growth area Greiner publishes, 0.34 cm²
    expect(g.areaMm2).toBeCloseTo(Math.PI * 3.3 ** 2, 6);
  });
});

describe("depth is asked for only where a carrier has one", () => {
  it("reports none for every carrier on offer, none of them being deep", () => {
    for (const type of CARRIER_TYPES) {
      expect(depthMm(fromPreset(type.id, type.presets[0])), type.id).toBe(0);
    }
  });

  it("says an area's two dimensions in one line", () => {
    expect(describeCarrier(fromPreset("slide", carrierType("slide").presets[0])))
      .toBe("Standard (75 × 25 mm) · 75.0 × 25.0 mm");
  });
});

describe("a type declares what it has, and the panel follows it", () => {
  it("every type offers at least one default to select", () => {
    for (const type of CARRIER_TYPES) {
      expect(type.presets.length, type.id).toBeGreaterThan(0);
    }
  });

  it("only the many-area carriers are grids, and they are the same two", () => {
    expect(CARRIER_TYPES.filter((t) => t.grid).map((t) => t.id))
      .toEqual(["chamber", "wellplate"]);
  });

  it("a dish is round, so it is one diameter and no corner to choose", () => {
    expect(carrierType("dish").round).toBe(true);
    expect(CARRIER_TYPES.filter((t) => t.round).map((t) => t.id)).toEqual(["dish"]);
    const d = fromPreset("dish", carrierType("dish").presets[0]);
    expect(d.w).toBe(d.h);
    expect(d.cornerRatio).toBe(1);
  });

  it("no carrier on offer declares a depth", () => {
    expect(CARRIER_TYPES.filter((t) => t.deep)).toEqual([]);
  });
});


describe("what the objective sees has to be inside an area", () => {
  /* A 96-well plate: wells 6.6 mm across, round, 9 mm apart. The overview
     preset sees 2.662 mm of sample at a time. */
  const plate = fromPreset("wellplate",
    carrierType("wellplate").presets.find((p) => p.label.startsWith("96-well")));
  const FRAME = 2.662;
  const well = centres(plate)[0];

  it("a frame in the middle of a well fits", () => {
    expect(frameFitsArea(plate, well.x, well.y, FRAME)).toBe(true);
  });

  it("the same frame near the rim does not, because its corners are on plastic", () => {
    expect(frameFitsArea(plate, well.x + 2.0, well.y, FRAME)).toBe(false);
  });

  it("nor does one on the plastic between two wells", () => {
    expect(frameFitsArea(plate, well.x + 4.5, well.y, FRAME)).toBe(false);
  });

  it("the well nearest a point is the one it would be imaged in", () => {
    const next = centres(plate).find((c) => c.row === 0 && c.col === 1);
    expect(nearestArea(plate, well.x + 5.0, well.y).col).toBe(next.col);
    expect(nearestArea(plate, well.x + 4.0, well.y).col).toBe(well.col);
  });

  it("a point off the edge of the plate belongs to the area at that edge", () => {
    expect(nearestArea(plate, -50, -50)).toMatchObject({ row: 0, col: 0 });
  });

  it("images a square of a round well, not the whole circle", () => {
    /* The imageable square of a 6.6 mm well is 3.3 x sqrt(2) across, so its
       edge is 2.333 mm from the middle — a frame reaching past that is over
       the part of the well a squared-off plan does not cover. */
    const { halfW, halfH } = scanBox(plate);
    expect(halfW).toBeCloseTo(3.3 / Math.SQRT2, 6);
    expect(halfH).toBeCloseTo(3.3 / Math.SQRT2, 6);
    expect(insideArea(plate, well.x + 2.2, well.y)).toBe(true);
    expect(insideArea(plate, well.x + 2.5, well.y)).toBe(false);
    // and the circle's own edge, which a rounded plan would have reached
    expect(insideArea(plate, well.x + 3.2, well.y)).toBe(false);
  });

  it("cuts a softened corner back to its chord, and nothing more", () => {
    // a chamber, which really is softened at the corners
    const chamber = fromPreset("chamber",
      carrierType("chamber").presets.find((p) => p.label.startsWith("1-chamber")));
    const { corner } = geometry(chamber);
    const cut = corner - corner / Math.SQRT2;
    expect(scanBox(chamber).halfW).toBeCloseTo(48 / 2 - cut, 9);
    expect(scanBox(chamber).halfH).toBeCloseTo(24 / 2 - cut, 9);
  });

  it("images an area to its own edges, having no corners to cut", () => {
    const slide = fromPreset("slide",
      carrierType("slide").presets.find((p) => p.label.startsWith("Standard")));
    expect(scanBox(slide)).toEqual({ halfW: 37.5, halfH: 12.5 });
  });

  it("seats a frame that does not fit by sliding it in towards the middle", () => {
    const seat = frameSeat(plate, well.x + 2.6, well.y, FRAME);
    expect(frameFitsArea(plate, seat.x, seat.y, FRAME)).toBe(true);
    // straight in: same y, and no further in than it had to come
    expect(seat.y).toBeCloseTo(well.y, 6);
    expect(seat.x - well.x).toBeCloseTo(scanBox(plate).halfW - FRAME / 2, 3);
  });

  it("leaves a frame that already fits exactly where it is", () => {
    expect(frameSeat(plate, well.x + 0.5, well.y, FRAME)).toEqual({
      x: well.x + 0.5, y: well.y,
    });
  });

  it("moves one dropped on the plastic into the well it was nearest", () => {
    const seat = frameSeat(plate, well.x + 4.5, well.y, FRAME);
    expect(frameFitsArea(plate, seat.x, seat.y, FRAME)).toBe(true);
  });

  it("has nowhere to seat a frame wider than the well", () => {
    expect(frameSeat(plate, well.x, well.y, 8)).toBe(null);
  });

  it("holds a slide to its one area, corners and all", () => {
    const slide = fromPreset("slide",
      carrierType("slide").presets.find((p) => p.label.startsWith("Standard")));
    expect(frameFitsArea(slide, 37.5, 12.5, FRAME)).toBe(true);
    expect(frameFitsArea(slide, 0.5, 12.5, FRAME)).toBe(false);
    // in from the left edge by the corner it was cut back to, plus half a frame
    const edge = 37.5 - scanBox(slide).halfW;
    expect(frameSeat(slide, 0.5, 12.5, FRAME).x).toBeCloseTo(edge + FRAME / 2, 3);
  });
});
