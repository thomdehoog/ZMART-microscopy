/* What window an acquisition should open at, when nobody has said.
 *
 * `viz_studio/options/brightness.js` answers that by reading the picture rather
 * than guessing at the camera, and what is checked here is the part of it that
 * needs no store and no server: what window it makes of a patch of pixels. Which
 * plane that patch comes from is the other half and is `planes.test.js`, because
 * the answer is shared with the options themselves. It is tested from here
 * because this is where the project's JavaScript test runner lives; the module
 * belongs to the options and is shared by all of them.
 *
 * The fault guarded below was live, and it was found on a real light-sheet tile
 * rather than by reading the code. It drew a picture that looked broken while
 * every part of the viewer reported itself content — which is why what is
 * asserted here is the number that reaches the screen, and why it is paired with
 * what the old rule gave, so that a test which can no longer fail would say so.
 *
 * The measurements are from
 * `mesoSPIM_transfer_20260626_1700/…/Mag5_Tile0_Ch488_FltEmpty…ome.zarr`:
 * background around 1750, hot pixels to 65535, and a first plane holding 203 to
 * 503 where the middle plane holds 609 to 23103.
 */

import { describe, it, expect } from "vitest";
import {
  theWindowThesePixelsAskFor,
} from "../../../viz_studio/options/brightness.js";

/** A plane like the real one: tissue around 1750, and a few pixels saturated. */
function aTileWithHotPixels({ hot = 4 } = {}) {
  const values = new Uint16Array(10_000);
  for (let at = 0; at < values.length; at += 1) values[at] = 1_700 + (at % 120);
  for (let at = 0; at < hot; at += 1) values[at * 977] = 65_535;
  return values;
}

describe("the window a patch of pixels asks for", () => {
  it("is not stretched by a handful of saturated pixels", () => {
    const window = theWindowThesePixelsAskFor(aTileWithHotPixels());
    expect(window.high).toBeLessThan(2_000);
    expect(window.low).toBeGreaterThan(1_600);
  });

  it("puts the tissue in the middle of the screen rather than at the bottom", () => {
    const values = aTileWithHotPixels();
    const window = theWindowThesePixelsAskFor(values);
    const middle = 1_760;
    const grey = ((middle - window.low) / (window.high - window.low)) * 255;
    expect(grey).toBeGreaterThan(40);
    expect(grey).toBeLessThan(215);
  });

  it("would have been ruined by the smallest and largest value, as it was", () => {
    const values = aTileWithHotPixels();
    const wasLow = Math.min(...values);
    const wasHigh = Math.max(...values);
    const grey = ((1_760 - wasLow) / (wasHigh - wasLow)) * 255;
    expect(wasHigh).toBe(65_535);
    expect(grey).toBeLessThan(1);
  });

  it("says nothing at all about a picture holding one value", () => {
    expect(theWindowThesePixelsAskFor(new Uint16Array(64).fill(300))).toBeNull();
  });

  it("still answers when nearly every pixel is the same, using what is left", () => {
    const values = new Uint16Array(1_000).fill(200);
    values[0] = 4_000;
    const window = theWindowThesePixelsAskFor(values);
    expect(window).not.toBeNull();
    expect(window.high).toBeGreaterThan(window.low);
  });
});

