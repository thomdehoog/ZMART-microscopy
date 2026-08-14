import { describe, it, expect } from "vitest";
import {
  CARRIER_TYPES, carrierType, fromPreset, matchingPreset, geometry,
  maxRadius, DEFAULT_CARRIER,
  emptyVolume, volumeComplete, withBound, describeCarrier,
} from "../../src/lib/carriers.js";

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

  it("the default is the plate the lab runs most, with that plate's numbers", () => {
    expect(DEFAULT_CARRIER.type).toBe("wellplate");
    const g = geometry(DEFAULT_CARRIER);
    expect(g.areas).toBe(96);
    expect([DEFAULT_CARRIER.rows, DEFAULT_CARRIER.cols]).toEqual([8, 12]);
    // Greiner's flat well bottom, on the SLAS 9 mm pitch
    expect(DEFAULT_CARRIER.w).toBeCloseTo(6.6, 6);
    expect(DEFAULT_CARRIER.h).toBeCloseTo(6.6, 6);
    expect(g.pitchX).toBeCloseTo(9.0, 6);
    expect(g.pitchY).toBeCloseTo(9.0, 6);
    // round: a full corner on a square area is a circle
    expect(DEFAULT_CARRIER.cornerRatio).toBe(1);
    expect(g.corner).toBeCloseTo(3.3, 6);
    // and it comes back to the growth area Greiner publishes, 0.34 cm²
    expect(g.areaMm2).toBeCloseTo(Math.PI * 3.3 ** 2, 6);
    expect(g.areaMm2 / 100).toBeCloseTo(0.34, 2);
  });
});

describe("a volume is recorded, not designed", () => {
  const record = (v, bounds) => bounds.reduce(
    (c, [axis, which, value]) => withBound(c, axis, which, value), v);

  it("starts unknown and completes when all six bounds are recorded", () => {
    let v = emptyVolume();
    expect(volumeComplete(v)).toBe(false);
    v = record(v, [["x", 0, 37.5], ["x", 1, 52.5], ["y", 0, 25.0], ["y", 1, 39.0]]);
    expect(volumeComplete(v), "x and y alone are a footprint, not a volume").toBe(false);
    v = record(v, [["z", 0, 2.6], ["z", 1, 7.4]]);
    expect(volumeComplete(v)).toBe(true);
    // width and height follow from the recorded x and y
    expect(v.w).toBeCloseTo(15.0, 6);
    expect(v.h).toBeCloseTo(14.0, 6);
  });

  it("says its three dimensions in one line", () => {
    const v = record(emptyVolume(),
      [["x", 0, 10], ["x", 1, 25], ["y", 0, 5], ["y", 1, 17], ["z", 0, 2], ["z", 1, 6.5]]);
    expect(describeCarrier(v)).toBe("Volume · 15.0 × 12.0 × 4.5 mm");
  });

  it("does not care which end was recorded first", () => {
    const v = record(emptyVolume(), [["x", 0, 52.5], ["x", 1, 37.5]]);
    expect(v.w).toBeCloseTo(15.0, 6);
  });

  it("every other carrier is always complete", () => {
    expect(volumeComplete(DEFAULT_CARRIER)).toBe(true);
  });
});
