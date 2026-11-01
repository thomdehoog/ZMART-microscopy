/**
 * Where pictures can show: the area the page lays the stage out on.
 *
 * The controller's `get_xyz` reports, per axis, `canvas`: everywhere a
 * picture can show along that axis. A picture taken at the edge of the
 * stage's travel still shows half a field beyond it, so the canvas is the
 * travel widened by half the widest field (x, y) and half the deepest stack
 * (z). The page and the viewer lay the specimen area out from it before the
 * first picture, so nothing has to grow or shift once pictures arrive. The
 * driver works it out; the page only reads it. The travel itself stays inside
 * the driver, which refuses a move past it before anything moves.
 *
 * Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
 * University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
 */

/** A stretch along one axis, `[min, max]` in micrometres. */
type Span = [number, number];

/** Where pictures can show, per axis. */
export interface PictureArea {
  x_um: Span;
  y_um: Span;
  z_um: Span;
}

const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/**
 * `{ x_um, y_um, z_um }`, each `[min, max]` in micrometres, from one
 * `get_xyz` reading. Throws a sentence the operator can act on when the
 * driver gives no usable canvas on an axis: drawing an area somebody guessed
 * would put pictures where they were not taken.
 */
export function theCanvasOf(reading: Partial<Record<"x" | "y" | "z", { canvas?: unknown }>> | null | undefined): PictureArea {
  const area: Partial<PictureArea> = {};
  for (const axis of ["x", "y", "z"] as const) {
    const canvas = reading?.[axis]?.canvas;
    if (!Array.isArray(canvas) || canvas.length !== 2
        || !canvas.every(isNumber) || canvas[0] > canvas[1]) {
      throw new Error(
        `the microscope's driver does not say where its pictures can show along ${axis} `
        + "(get_xyz gives no usable 'canvas'), so the stage cannot be laid out; "
        + "the driver needs updating to the controller's current contract",
      );
    }
    area[`${axis}_um`] = [canvas[0], canvas[1]];
  }
  return area as PictureArea;
}
