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
import { anchorsUm } from "../../workflows/target_acquisition/steps/2_define_carrier/carrier-panel.js";
import { carrierType, centres, fromPreset }
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
