/* Where a carrier is registered from.
 *
 * `anchorsUm` picks the four places an operator drives to and snaps, and the
 * whole value of the four is in where they are relative to each other. Both
 * rules checked here were written after seeing the marks on screen and finding
 * them in places nobody can register from:
 *
 *   - they were measured from `scanBox`, which insets an area by its rounded
 *     corner so a square frame never overhangs the glass. Right for planning
 *     tiles, wrong for a mark: on a round well the inset is nearly a third of
 *     the radius, so every mark floated well inside the line it names.
 *
 *   - ties were broken towards the middle of the carrier, which on an even
 *     number of rows or columns is no tie-break at all: on a two-chamber slide
 *     three of the four marks landed on the same chamber. Marks bunched on one
 *     area pin where the carrier is without pinning how it is turned.
 *
 * Both are invisible to a test that only checks four marks came back, so what
 * is asserted is the geometry: which area each mark chose, and the distance
 * from the mark to that area's edge.
 */

import { describe, it, expect } from "vitest";
import { anchorsUm, howManyAnchorsFit }
  from "../../workflows/target_acquisition/steps/2_define_carrier/carrier-panel.js";
import { carrierType, centres, fromPreset, geometry }
  from "../../workflows/target_acquisition/shared/carriers.js";

const MM_UM = 1000;

/* The mark's own area: the nearest one, in both axes at once. Matching on the
   single axis the mark is centred in is not enough — every area in a column
   shares that centre line, and the first of them is rarely the right one. */
const areaUnder = (config, mark) => centres(config).reduce((best, a) => {
  const far = (c) => (c.x * MM_UM - mark.x) ** 2 + (c.y * MM_UM - mark.y) ** 2;
  return far(a) < far(best) ? a : best;
});

const by = (marks) => Object.fromEntries(marks.map((m) => [m.at, m]));

/* The ibidi 8-chamber, taken from the presets rather than written out here:
   two rows deep and four columns across, so every outermost row and column is
   a tie. It is the shape that showed the bunching on screen. Built through
   `fromPreset` because that is the only thing that turns a preset into the
   config the rest of the code reads — a hand-written one silently produces
   NaN pitches and no areas at all. */
const preset = (typeId, label) =>
  fromPreset(typeId, carrierType(typeId).presets.find((p) => p.label === label));
const eightChambers = preset("chamber", "8-chamber (ibidi)");

describe("the four alignment points", () => {
  it("sits each mark on the edge of its area, not inside it", () => {
    const config = eightChambers;
    for (const mark of anchorsUm(config)) {
      const area = areaUnder(config, mark);
      const half = mark.at === "left" || mark.at === "right" ? config.w / 2 : config.h / 2;
      const across = mark.at === "left" || mark.at === "right"
        ? mark.x - area.x * MM_UM
        : mark.y - area.y * MM_UM;
      expect(Math.abs(across)).toBeCloseTo(half * MM_UM, 6);
    }
  });

  it("leans each mark a quarter turn on, so the four land on four areas", () => {
    const m = by(anchorsUm(eightChambers));
    const chose = (k) => areaUnder(eightChambers, m[k]);
    const [top, right, bottom, left] = ["top", "right", "bottom", "left"].map(chose);

    expect(top.x).toBeLessThan(right.x);       // top leans left
    expect(right.y).toBeLessThan(bottom.y);    // right leans up
    expect(bottom.x).toBeGreaterThan(left.x);  // bottom leans right
    expect(left.y).toBeGreaterThan(top.y);     // left leans down

    const areas = [top, right, bottom, left].map((a) => `${a.x},${a.y}`);
    expect(new Set(areas).size).toBe(4);
  });

  it("faces the marks across the carrier, whichever areas they chose", () => {
    const m = by(anchorsUm(eightChambers));
    expect(m.left.x).toBeLessThan(m.right.x);
    expect(m.top.y).toBeLessThan(m.bottom.y);
  });
});

/* Where the carrier ends up once all four have been driven to.
 *
 * Each snap records "this place on the drawing is that place on the stage",
 * and the four are averaged into one offset. That leaves the carrier centred
 * on the middle of the four places the operator drove to — but only because
 * the marks are laid out symmetrically about the carrier's own centre. The
 * tie-break that spreads them decides that symmetry, so it is checked here
 * over every preset rather than assumed from the two that were looked at on
 * screen. A carrier whose marks lean to one side would come out of alignment
 * sitting to that side of where it really is.
 */
describe("what the four leave behind", () => {
  const everyPreset = ["chamber", "wellplate", "dish", "area"]
    .flatMap((type) => (carrierType(type)?.presets ?? [])
      .filter((p) => p.label !== "Custom")
      .map((p) => [`${type} · ${p.label}`, fromPreset(type, p)]));

  it.each(everyPreset)("centres %s on the middle of its own marks", (_name, config) => {
    const marks = anchorsUm(config);
    const g = geometry(config);
    const mean = (f) => marks.reduce((sum, m) => sum + f(m), 0) / marks.length;
    expect(mean((m) => m.x)).toBeCloseTo((g.width / 2) * MM_UM, 6);
    expect(mean((m) => m.y)).toBeCloseTo((g.height / 2) * MM_UM, 6);
  });
});

/* How many there are is the operator's to say. Four is what a carrier is laid
   with unasked, and the rest are handed out the same way — a mark from each
   side in turn — so that asking for more spreads them round the carrier
   instead of gathering them down one edge of it.
 */
describe("as many points as were asked for", () => {
  const sixWell = preset("wellplate", carrierType("wellplate").presets[0].label);

  it("lays four when nobody says otherwise", () => {
    expect(anchorsUm(sixWell)).toHaveLength(4);
  });

  it.each([2, 3, 4, 5, 8])("lays %i when %i are asked for", (n) => {
    expect(anchorsUm(sixWell, n)).toHaveLength(n);
  });

  it("stops at what the carrier has borders for", () => {
    const most = howManyAnchorsFit(sixWell);
    expect(anchorsUm(sixWell, 99)).toHaveLength(most);
    /* Three columns and two rows: two areas stand on the left line and two on
       the right, three along the top and three along the bottom. */
    expect(most).toBe(10);
  });

  it("keeps every extra point on a border too", () => {
    for (const mark of anchorsUm(sixWell, 8)) {
      const area = areaUnder(sixWell, mark);
      const half = mark.at === "left" || mark.at === "right" ? sixWell.w / 2 : sixWell.h / 2;
      const across = mark.at === "left" || mark.at === "right"
        ? mark.x - area.x * MM_UM
        : mark.y - area.y * MM_UM;
      expect(Math.abs(across)).toBeCloseTo(half * MM_UM, 6);
    }
  });

  it("hands them out a side at a time, so eight are two to a side", () => {
    const sides = anchorsUm(sixWell, 8).map((m) => m.at);
    for (const side of ["left", "right", "top", "bottom"]) {
      expect(sides.filter((s) => s === side)).toHaveLength(2);
    }
  });

  it("never lays the same point twice", () => {
    const marks = anchorsUm(sixWell, howManyAnchorsFit(sixWell));
    expect(new Set(marks.map((m) => `${m.x},${m.y}`)).size).toBe(marks.length);
  });
});
