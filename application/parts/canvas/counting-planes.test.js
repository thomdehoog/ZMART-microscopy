/**
 * Counting planes, and reading a depth back the way a microscopist counts it.
 *
 * The panel's depth slider used only ever to write: it moved the picture, and
 * showed whatever it had last been set to. Moving through the stack any other
 * way — the scroll wheel, a step of the workflow, the viewer opening itself on
 * a plane — left the number beside the handle saying something that was no
 * longer true. Fixing that means reading the depth back out of the viewer and
 * drawing the control from the answer, and this is the arithmetic that turns
 * that answer into something worth reading.
 *
 * What the panel does with it needs a browser and is checked in
 * `application/the-depth-slider-follows.spec.js`. What is checked here is the
 * arithmetic on its own, including the two edges that come out of how a real
 * engine describes a real stack.
 */

import { describe, expect, it } from "vitest";
import {
  theDepthReads, theNextPlaneAfter, thePlanesIn,
} from "./counting-planes.js";

/** A focussing sweep: forty-eight planes, five micrometres apart. */
const aSweep = (atUm) => ({ lowUm: 0, highUm: 235, stepUm: 5, atUm });

describe("how many planes a depth holds", () => {
  it("counts both ends of the sweep, not just the gaps between them", () => {
    /* Forty-seven steps of five micrometres, and forty-eight planes. Counting
       the gaps rather than the planes is the classic way to be one out, and on
       screen it shows as a stack whose last plane is unreachable. */
    expect(thePlanesIn(aSweep(0)).count).toBe(48);
  });

  it("counts the first plane as plane one, the way an operator does", () => {
    expect(thePlanesIn(aSweep(0)).at).toBe(1);
    expect(thePlanesIn(aSweep(55)).at).toBe(12);
    expect(thePlanesIn(aSweep(235)).at).toBe(48);
  });

  it("says there is no stack when there is only one plane", () => {
    /* A flat capture is not a stack, and a control drawn for it would be a
       control that cannot move. */
    expect(thePlanesIn({ lowUm: 0, highUm: 0, stepUm: 5, atUm: 0 })).toBe(null);
  });

  it("says there is no stack when the viewer will not answer at all", () => {
    expect(thePlanesIn(null)).toBe(null);
    expect(thePlanesIn(undefined)).toBe(null);
  });

  it("refuses a step of nought rather than dividing by it", () => {
    /* Without this the count comes back as Infinity, and the readout says
       "plane 1 / Infinity" — which looks like a bug in the microscope rather
       than a viewer that had nothing to say. */
    expect(thePlanesIn({ lowUm: 0, highUm: 235, stepUm: 0, atUm: 0 })).toBe(null);
  });

  it("holds the plane number inside the stack when the view sits just outside it", () => {
    /* This is not hypothetical. Neuroglancer puts its bounds at voxel edges, so
       a view nobody has touched can stand half a plane below the first one, and
       the honest reading of that is still "plane 1". */
    expect(thePlanesIn(aSweep(-2.5)).at).toBe(1);
    expect(thePlanesIn(aSweep(240)).at).toBe(48);
  });
});

describe("the line of text beside the slider", () => {
  it("gives the plane number and the height together", () => {
    /* Both numbers earn their place: the plane number is what the operator
       counts in, and the micrometres are what the run was written in. */
    expect(theDepthReads(aSweep(55))).toBe("plane 12 / 48 · 55 µm");
  });

  it("says nothing at all when there is no stack", () => {
    expect(theDepthReads(null)).toBe(null);
  });
});

describe("stepping a stack along, the way a film is played", () => {
  it("moves one plane forward", () => {
    expect(theNextPlaneAfter(aSweep(55))).toBe(60);
  });

  it("wraps round to the first plane rather than stopping on the last", () => {
    /* A sweep that stops on its final frame looks exactly like one that has
       stalled, and telling those two apart from across a room is impossible. */
    expect(theNextPlaneAfter(aSweep(235))).toBe(0);
  });

  it("has nowhere to go when there is no stack", () => {
    expect(theNextPlaneAfter(null)).toBe(null);
  });
});
