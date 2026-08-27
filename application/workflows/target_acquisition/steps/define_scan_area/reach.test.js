/* How far a drawn field may go.
 *
 * The carrier used to be the edge: a region was pushed back the moment it
 * crossed the plate. But the plate is not what limits imaging — the stage is.
 * An operator drawing a strip that runs off the edge of a slide is asking for
 * the ground beyond it, and the stage can reach it; a well plate sitting in
 * the middle of a 120 x 80 mm travel has a hand's width of reachable stage all
 * round it that the drawing was refusing to enter.
 *
 * What must still hold is the other edge: a field outside the stage's travel
 * is a position the instrument cannot drive to, and nothing downstream would
 * notice — the plan would simply contain tiles that never arrive.
 */

import { describe, it, expect } from "vitest";
import { pushedBackIntoReach }
  from "../../../../workflows/target_acquisition/steps/define_scan_area/scanfield-editor.js";

/* The stage, in the carrier's own micrometres: a 120 x 80 mm travel with a
   75 x 25 mm slide centred in it, so the carrier's zero is 22.5 mm right and
   27.5 mm down from the corner of the travel. */
const reach = { xMin: -22_500, xMax: 97_500, yMin: -27_500, yMax: 52_500 };

const rect = (x, y, w = 4_000, h = 4_000) =>
  ({ id: "f", type: "rectangle", rotation: 0, x, y, w, h });

describe("how far a field may be drawn", () => {
  it("leaves a field that runs off the carrier where it was put", () => {
    /* Well past the left edge of the slide, and well inside the stage. */
    const drawn = rect(-10_000, 5_000);
    expect(pushedBackIntoReach(drawn, reach)).toBe(drawn);
  });

  it("leaves one past the far corner of the carrier alone too", () => {
    const drawn = rect(80_000, 40_000);
    expect(pushedBackIntoReach(drawn, reach)).toBe(drawn);
  });

  it("pushes a field back whole when it crosses the edge of travel", () => {
    /* Pushed, not trimmed: the shape somebody drew is the statement, and
       clipping it would quietly change what gets imaged. */
    const moved = pushedBackIntoReach(rect(-30_000, 0), reach);
    expect(moved.x).toBe(reach.xMin);
    expect(moved.w).toBe(4_000);
  });

  it("pushes it back from the far edge by exactly what hangs over", () => {
    const moved = pushedBackIntoReach(rect(96_000, 51_000), reach);
    expect(moved.x).toBe(reach.xMax - 4_000);
    expect(moved.y).toBe(reach.yMax - 4_000);
  });

  it("holds an ellipse to the same edges, by its own bounds", () => {
    /* An ellipse is a centre and two radii, where a rectangle is a corner and
       two spans — so it is `cx`/`cy` that move, and what has to clear the edge
       is its own bounding box. */
    const drawn = { id: "e", type: "ellipse", rotation: 0, cx: -25_000, cy: 0, rx: 2_000, ry: 2_000 };
    const moved = pushedBackIntoReach(drawn, reach);
    expect(moved.cx).toBe(reach.xMin + 2_000);
  });
});
