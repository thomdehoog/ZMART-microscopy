/* Where the specimen is, as against where the run declared room for it.
 *
 * The arithmetic only, which is the half that can be checked without a store:
 * given a copy of an image, where is the bright material? Reading the copy is
 * the other half and needs a server.
 *
 * It exists because a view opened on the middle of the declared ground, and on a
 * real biopsy that was 250 µm from the specimen in depth. Flat, that is an
 * opening view an operator corrects with one drag. In a volume it is the point
 * the specimen turns about, and a thing turning about a point outside itself
 * swings instead of rotating — which is how it was noticed.
 */

import { describe, it, expect } from "vitest";
import {
  theMiddleOfWhatWasImaged,
} from "../../../../../viz_studio/options/where-the-specimen-is.js";

/** A stack with the bright material deliberately off the geometric middle. */
function aStackWithTheSpecimenLow({ planes = 10, height = 8, width = 8 } = {}) {
  const values = new Uint16Array(planes * height * width).fill(200);
  const put = (z, y, x, value) => { values[(z * height + y) * width + x] = value; };
  // A blob around plane 7 of 10, and right of centre across.
  for (const z of [6, 7, 8]) {
    for (const y of [4, 5]) {
      for (const x of [5, 6]) put(z, y, x, 4000);
    }
  }
  return { values, sizes: [planes, height, width] };
}

describe("the middle of what was imaged", () => {
  it("finds the specimen rather than the middle of the room", () => {
    const { values, sizes } = aStackWithTheSpecimenLow();
    const [z, y, x] = theMiddleOfWhatWasImaged(values, sizes);
    expect(z).toBeCloseTo(7, 1);
    expect(y).toBeCloseTo(4.5, 1);
    expect(x).toBeCloseTo(5.5, 1);
  });

  it("is not the geometric middle, which is the whole point", () => {
    const { values, sizes } = aStackWithTheSpecimenLow();
    const [z] = theMiddleOfWhatWasImaged(values, sizes);
    const declaredMiddle = (sizes[0] - 1) / 2;
    expect(Math.abs(z - declaredMiddle)).toBeGreaterThan(2);
  });

  it("is not dragged back to the middle by the background, however much there is", () => {
    const small = aStackWithTheSpecimenLow({ planes: 10 });
    const roomy = aStackWithTheSpecimenLow({ planes: 40 });
    /* The same specimen in four times the declared room. Weighed without a floor
       the answer would move towards the middle of whichever room it was put in;
       it does not move at all. */
    expect(theMiddleOfWhatWasImaged(small.values, small.sizes)[0])
      .toBeCloseTo(theMiddleOfWhatWasImaged(roomy.values, roomy.sizes)[0], 1);
  });

  it("says nothing about a picture with no specimen in it", () => {
    const flat = new Uint16Array(512).fill(300);
    expect(theMiddleOfWhatWasImaged(flat, [8, 8, 8])).toBeNull();
  });

  it("says nothing rather than throwing when handed nothing", () => {
    expect(theMiddleOfWhatWasImaged(null, [4, 4])).toBeNull();
    expect(theMiddleOfWhatWasImaged(new Uint16Array(4), null)).toBeNull();
  });

  it("works along however many axes the copy has", () => {
    const values = new Uint16Array(4 * 6).fill(100);
    values[3 * 6 + 5] = 9000;
    const [a, b] = theMiddleOfWhatWasImaged(values, [4, 6]);
    expect(a).toBeCloseTo(3, 1);
    expect(b).toBeCloseTo(5, 1);
  });
});
