import { describe, it, expect } from "vitest";
import { plan } from "./scanfield-editor.ts";
import {
  carrierType, centres, fromPreset, nearestArea, type Preset,
} from "../../shared/carriers.ts";
import type { PlanTile } from "../../shared/run-document.ts";
import { block, type Field, type PointField, type RectangleField } from "../../shared/scanfields.ts";

/** A catalogue part of this type, by the label it is listed under. */
const part = (type: string, named: (label: string) => boolean): Preset =>
  carrierType(type).presets.find((p) => named(p.label))!;

/** A rectangle, as a field the plan is handed. */
type Region = Field & RectangleField;

/** The two axes a tile is placed along. */
type Axis = "x" | "y";

/* A 96-well plate: wells 6.6 mm across, 9 mm apart, the first centred on
   (3.3, 3.3) mm and the second on (12.3, 3.3). Fields are in micrometres from
   the carrier's own zero, which is what the editor hands the plan. */
const plate = fromPreset("wellplate", part("wellplate", (l) => l.startsWith("96-well")));
const hires = { id: "p", frameUm: 102 };
const overview = { id: "p", frameUm: 2662 };

/** Which well each tile of the plan landed in, as row.col strings. */
const wells = (tiles: PlanTile[]) => new Set(tiles.map((t) => {
  const a = nearestArea(plate, t.x / 1000, t.y / 1000);
  return `${a.row}.${a.col}`;
}));

/** A rectangle in micrometres, given its two corners in millimetres. */
const strip = (x0: number, x1: number): Region => ({
  id: "f1", type: "rectangle", rotation: 0,
  x: x0 * 1000, y: 2.8 * 1000, w: (x1 - x0) * 1000, h: 1000,
});

describe("a region is covered as it was drawn", () => {
  /* The carrier does not crop a tileset either. A region drawn clear of every
     well — on the plastic between them, or off the plate and out over the
     reachable stage beyond it — used to come back with nothing at all: the
     plan asked which area held it, found none, and dropped the field. But an
     outline is a statement about a piece of ground, and the stage can drive
     there; a plate is not what decides whether something can be imaged.

     A hand-placed position is still seated into a well, which is the other
     rule and stays: one position dropped on the plastic is a mistake, where a
     region drawn there is somebody covering what they drew around. */
  it("covers a region drawn clear of every well", () => {
    /* Above the top row of wells, on the plastic. */
    const off: Region = {
      id: "f1", type: "rectangle", rotation: 0,
      x: 1_000, y: 0, w: 6_000, h: 800,
    };
    const tiles = plan([off], hires, plate);
    expect(tiles.length).toBeGreaterThan(0);
    for (const t of tiles) {
      expect(t.x).toBeGreaterThanOrEqual(off.x);
      expect(t.x).toBeLessThanOrEqual(off.x + off.w);
    }
  });

  it("keeps such a region as a tileset of its own", () => {
    const off: Region = {
      id: "f9", type: "rectangle", rotation: 0,
      x: 1_000, y: 0, w: 6_000, h: 800,
    };
    expect(new Set(plan([off], hires, plate).map((t) => t.tileset)))
      .toEqual(new Set(["field-f9"]));
  });

  /* An outline is a statement about a piece of sample, and covering it is
     answering that statement. It used to be narrowed to the one well it lay in
     most and clipped to that well's edge, which meant a region drawn across two
     wells came back as most of one — a plan quietly smaller than the thing
     somebody had drawn around. */
  it("reaches both wells when the outline does", () => {
    /* Across the first well and a little way into the second: 5.6 mm of the
       outline lies in the first, 4.0 mm in the second. */
    const tiles = plan([strip(1.0, 13.0)], hires, plate);
    expect(tiles.length).toBeGreaterThan(0);
    expect(wells(tiles)).toEqual(new Set(["0.0", "0.1"]));
  });

  it("counts each field on its own, so two fields can be two wells", () => {
    const a = { ...strip(1.0, 13.0), id: "a" };
    const b = { ...strip(5.5, 15.0), id: "b" };
    expect(wells(plan([a, b], hires, plate))).toEqual(new Set(["0.0", "0.1"]));
  });

  it("covers an outline that fits in no well, rather than nothing at all", () => {
    /* The plastic between the first two wells, and narrower than a 5x frame.
       This used to come back empty: the plan asked which well held the outline,
       found none, and dropped it. The carrier is not what decides whether
       ground can be imaged — the stage is — so what was drawn is covered. */
    const tiles = plan([strip(7.2, 8.4)], overview, plate);
    expect(tiles.length).toBeGreaterThan(0);
    expect(new Set(tiles.map((t) => t.tileset))).toEqual(new Set(["field-f1"]));
  });

  it("lets a frame reach past the rim rather than leaving a hole at the edge", () => {
    /* A well is 3.3 mm from middle to rim. Some tile of a strip drawn across
       two of them stands further out than that, because the strip does — and
       the part of the sample inside that frame is what the operator asked to
       image. Dropping it left the covered ground short of its own outline at
       exactly the edges somebody had drawn around something. */
    const out = plan([strip(1.0, 13.0)], hires, plate)
      .map((t) => {
        const a = nearestArea(plate, t.x / 1000, t.y / 1000);
        return Math.hypot(t.x / 1000 - a.x, t.y / 1000 - a.y);
      });
    expect(Math.max(...out)).toBeGreaterThan(3.3);
  });
});

describe("a region is covered right into its corners", () => {
  /* A slide: one area 75 x 25 mm with square corners, so the edges are exact
     numbers and what a tile does at a boundary is easy to state. */
  const slide = fromPreset("slide", part("slide", (l) => l === "75 × 25 mm slide"));
  const tenx = { id: "p", frameUm: 1331 };
  const corner: Region = {
    id: "f", type: "rectangle", rotation: 0, x: 0, y: 0, w: 10000, h: 8000,
  };

  it("centres the lattice on the region, not on the area", () => {
    /* The lattice used to be pushed inside the carrier's imageable box and
       laid flush against whichever edge had clipped it. It is laid on the
       outline now, so what hangs over is the same on both sides — which is
       what makes the cover symmetric about the thing that was drawn. */
    const tiles = plan([corner], tenx, slide);
    const mid = (axis: Axis) => {
      const all = tiles.map((t) => t[axis]);
      return (Math.min(...all) + Math.max(...all)) / 2;
    };
    expect(mid("x")).toBeCloseTo(corner.x + corner.w / 2, 2);
    expect(mid("y")).toBeCloseTo(corner.y + corner.h / 2, 2);
  });

  it("keeps the step it was given, so the overlap does not change", () => {
    const tiles = plan([corner], tenx, slide);
    const step = (axis: Axis) => {
      const line = [...new Set(tiles.map((t) => Math.round(t[axis])))].sort((a, b) => a - b);
      return line.slice(1).map((v, i) => v - line[i]);
    };
    // one step, the preset's frame, between every pair of neighbours
    for (const gap of [...step("x"), ...step("y")]) expect(gap).toBe(tenx.frameUm);
  });

  it("covers the region edge to edge, and no edge is left short", () => {
    /* What the cover has to be true of is the outline, not the carrier: every
       part of the region falls inside some frame, corners included. */
    const tiles = plan([corner], tenx, slide);
    const half = tenx.frameUm / 2;
    const reach = (axis: Axis) => {
      const all = tiles.map((t) => t[axis]);
      return [Math.min(...all) - half, Math.max(...all) + half];
    };
    const [x0, x1] = reach("x");
    const [y0, y1] = reach("y");
    expect(x0).toBeLessThanOrEqual(corner.x);
    expect(x1).toBeGreaterThanOrEqual(corner.x + corner.w);
    expect(y0).toBeLessThanOrEqual(corner.y);
    expect(y1).toBeGreaterThanOrEqual(corner.y + corner.h);
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
  const slide = fromPreset("slide", part("slide", (l) => l === "75 × 25 mm slide"));
  const at = (xMm: number, yMm: number): Field & PointField =>
    ({ id: "p1", type: "point", x: xMm * 1000, y: yMm * 1000 });

  it("keeps one whose frame fits", () => {
    expect(plan([at(10, 10)], overview, slide)).toHaveLength(1);
  });

  it("drops one pressed into the corner, where the frame would hang over", () => {
    expect(plan([at(0.1, 0.1)], overview, slide)).toEqual([]);
  });
});

describe("a grid keeps the block it was asked for in every well", () => {
  /* What `Add grid` lays: rows by columns at the pitch asked for, centred on
     every well. Five by four at 1024 µm with a 1024 µm frame is a block 4 mm
     by 5 mm, wider than a 96-well plate's 6.6 mm well is square — its outer
     positions reach past the rim. They used to be dropped there, and every
     well came back with a ragged block of twelve. */
  const mock = { id: "p", frameUm: 1024 };
  const grid = (): Field[] => centres(plate).flatMap((a, w) =>
    block({ x: a.x * 1000, y: a.y * 1000 }, 5, 4, 1024, 1024)
      .map((p, i): Field => ({ id: `g${w}.${i}`, type: "point", source: "grid", ...p })));

  it("keeps all twenty positions in every well", () => {
    const tiles = plan(grid(), mock, plate);
    expect(tiles).toHaveLength(96 * 20);
    const perWell = new Map<number, number>();
    for (const t of tiles) perWell.set(t.compartment, (perWell.get(t.compartment) ?? 0) + 1);
    expect(perWell.size).toBe(96);
    for (const n of perWell.values()) expect(n).toBe(20);
  });

  it("numbers a position past the rim with the well it was laid in", () => {
    /* One well's block is one tileset, edge positions included: B3 is the
       fifteenth well and the fifteenth tileset. */
    const tiles = plan(grid(), mock, plate).filter((t) => String(t.fieldId).startsWith("g14."));
    expect(tiles).toHaveLength(20);
    for (const t of tiles) {
      expect(t.compartment).toBe(15);
      expect(t.group).toBe(15);
      expect(t.tileset).toBe("area-1.2");
    }
  });

  it("still drops a position placed by hand whose frame hangs over the rim", () => {
    /* The same spot as A1's grid corner position, put there by hand. */
    const [a1] = centres(plate);
    const [corner] = block({ x: a1.x * 1000, y: a1.y * 1000 }, 5, 4, 1024, 1024);
    expect(plan([{ id: "p", type: "point", ...corner }], mock, plate)).toEqual([]);
  });
});

describe("no frame is laid that takes in none of the region", () => {
  const slide = fromPreset("slide", part("slide", (l) => l === "75 × 25 mm slide"));
  const tenx = { id: "p", frameUm: 1331 };

  /** Whether a frame there overlaps the box the field occupies, at all. */
  const meets = (t: PlanTile, f: Region, frameUm: number) => {
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
      const f: Region = { id: "f", type: "rectangle", rotation: 0, ...box };
      const laid = plan([f], tenx, slide);
      expect(laid.length).toBeGreaterThan(0);
      for (const t of laid) expect(meets(t, f, tenx.frameUm)).toBe(true);
    });
  }
});

describe("every position says where on the plate it is", () => {
  /* The numbers a filename is built from. A position that cannot say which
     well and which tileset it belongs to becomes a file nobody can place, so
     the plan carries them: it is the one thing that knows both. */

  it("numbers the compartment a position was imaged in", () => {
    /* Two strips, one in each of the first two wells of the top row. */
    const first = { ...strip(1.0, 5.0), id: "a" };
    const second = { ...strip(10.0, 14.0), id: "b" };
    const tiles = plan([first, second], hires, plate);
    const seen = new Map<PlanTile["fieldId"], number>();
    for (const t of tiles) seen.set(t.fieldId, t.compartment);
    expect(seen.get("a")).toBe(1);          // row 0, column 0
    expect(seen.get("b")).toBe(2);          // row 0, column 1
  });

  it("numbers each tileset, so one well's two regions are two", () => {
    const first = { ...strip(1.0, 3.0), id: "a" };
    const second = { ...strip(4.0, 6.0), id: "b" };
    const groups = new Set(plan([first, second], hires, plate).map((t) => t.group));
    expect(groups).toEqual(new Set([1, 2]));
  });

  it("says zero for a region on no well at all", () => {
    /* Zero is honest about not knowing; inventing a compartment would put a
       file in a well nobody imaged. */
    const off: Region = { id: "f", type: "rectangle", rotation: 0,
                  x: 1_000, y: 0, w: 6_000, h: 800 };
    for (const t of plan([off], hires, plate)) expect(t.compartment).toBe(0);
  });
});

