/**
 * The area the page lays the stage out on comes from `get_xyz`'s `canvas`:
 * everywhere a picture can show along each axis, in the micrometres the
 * stage counts in. A driver that does not say is told so, in words.
 */

import { describe, expect, it } from "vitest";
import { theCanvasOf } from "./canvas.ts";

const reading = (canvas: Record<string, unknown> = {}) => Object.fromEntries(["x", "y", "z"].map((axis) => [axis, {
  position: 0, unit: "micrometer", actuator_readings: { motoric: 0 },
  ...(canvas[axis] === undefined ? { canvas: [-5, 105] } : canvas[axis] ? { canvas: canvas[axis] } : {}),
}]));

describe("the canvas the page lays the stage out on", () => {
  it("is get_xyz's canvas, axis by axis", () => {
    expect(theCanvasOf(reading({ x: [-32, 132], y: [-10, 90], z: [-2, 102] }))).toEqual({
      x_um: [-32, 132], y_um: [-10, 90], z_um: [-2, 102],
    });
  });

  it("names the axis a driver gave no canvas for", () => {
    expect(() => theCanvasOf(reading({ y: null }))).toThrow(
      /does not say where its pictures can show along y/,
    );
  });

  it("refuses a canvas that is not two numbers, smallest first", () => {
    expect(() => theCanvasOf(reading({ x: [10, -10] }))).toThrow(/along x/);
    expect(() => theCanvasOf(reading({ x: ["a", 1] }))).toThrow(/along x/);
  });

  it("says plainly when there is no reading at all", () => {
    expect(() => theCanvasOf(null)).toThrow(/along x/);
  });
});
