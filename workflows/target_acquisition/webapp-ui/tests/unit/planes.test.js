/* Which plane of a stack the viewers look at, and which moment and colour.
 *
 * `viz_studio/options/planes.js` holds one fact — a stack's middle plane is
 * where the specimen is and its first plane is its edge — because two things
 * depend on it and they have to agree: which plane an option opens on, and which
 * plane a display window is measured from.
 *
 * It was found on screen rather than by reading code. The operator page draws
 * two engines side by side; on one light-sheet tile they showed plainly
 * different pictures, because `viv-under` opened at plane 0 while neuroglancer
 * opened in the middle. Rendering both planes out of the file matched each
 * column exactly. The numbers below are that tile: the first plane holds 203 to
 * 503 with a median of 317, the middle plane 609 to 23103 with a median of 1835.
 *
 * It is tested from here because this is where the project's JavaScript test
 * runner lives; the module belongs to the options and is shared by all of them.
 */

import { describe, it, expect } from "vitest";
import { theMiddleOfEveryOtherAxis } from "../../../../../viz_studio/options/planes.js";

describe("which plane of the image is looked at", () => {
  it("takes the middle of a stack, because the first plane is its edge", () => {
    expect(theMiddleOfEveryOtherAxis(["z", "y", "x"], [256, 4608, 2592]))
      .toEqual({ z: 128 });
  });

  it("is not the first plane, which is what drew an empty picture", () => {
    const looking = theMiddleOfEveryOtherAxis(["z", "y", "x"], [256, 4608, 2592]);
    expect(looking.z).not.toBe(0);
  });

  it("takes the first moment and the first colour, not the middle ones", () => {
    expect(theMiddleOfEveryOtherAxis(["t", "c", "z", "y", "x"], [7, 2, 256, 4608, 2592]))
      .toEqual({ t: 0, c: 0, z: 128 });
  });

  it("asks for nothing along the two axes that are on screen", () => {
    const looking = theMiddleOfEveryOtherAxis(["z", "y", "x"], [256, 4608, 2592]);
    expect(looking).not.toHaveProperty("x");
    expect(looking).not.toHaveProperty("y");
  });

  it("is unbothered by an image of two dimensions", () => {
    expect(theMiddleOfEveryOtherAxis(["y", "x"], [4608, 2592])).toEqual({});
  });

  it("says the first plane of a stack one deep, which is also its middle", () => {
    expect(theMiddleOfEveryOtherAxis(["z", "y", "x"], [1, 512, 512])).toEqual({ z: 0 });
  });
});
