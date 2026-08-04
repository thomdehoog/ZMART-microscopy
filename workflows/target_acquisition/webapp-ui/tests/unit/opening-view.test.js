/* Where a run opens, before anybody has said where to look.
 *
 * `viz_studio/options/opening-view.js` holds the rule — show all of it, centred
 * — because the engines do not agree on their own and the disagreement is large:
 * Viv fits the acquisition to the box, neuroglancer opens at one voxel to one
 * screen pixel, which on a 1.1 µm store is about twenty times closer.
 *
 * That was invisible while the page drew two engines side by side and put both
 * on whichever view arrived first. It became visible the moment the page went
 * back to one viewer with a button to change the engine underneath it, which is
 * what these tests are here to stop happening again.
 */

import { describe, it, expect } from "vitest";
import {
  theViewThatShowsAllOf,
} from "../../../../../viz_studio/options/opening-view.js";

/** The light-sheet tile these numbers come from: 2592 × 4608 voxels at 1.1 µm. */
const A_REAL_TILE = { atUm: { x: 29_000, y: 69_500 }, wideUm: 2851.2, tallUm: 5068.8 };
const A_REAL_BOX = { width: 1160, height: 769 };

describe("the view that shows all of an acquisition", () => {
  it("centres on the run rather than on the stage's zero", () => {
    const view = theViewThatShowsAllOf(A_REAL_TILE, A_REAL_BOX);
    expect(view.centre.x).toBeCloseTo(29_000 + 2851.2 / 2, 3);
    expect(view.centre.y).toBeCloseTo(69_500 + 5068.8 / 2, 3);
  });

  it("fits the long side, so nothing runs off the edge", () => {
    const view = theViewThatShowsAllOf(A_REAL_TILE, A_REAL_BOX);
    expect(A_REAL_TILE.wideUm / view.zoom).toBeLessThanOrEqual(A_REAL_BOX.width + 1e-6);
    expect(A_REAL_TILE.tallUm / view.zoom).toBeLessThanOrEqual(A_REAL_BOX.height + 1e-6);
  });

  it("leaves one side of the box filled, so it fits rather than merely shrinks", () => {
    const view = theViewThatShowsAllOf(A_REAL_TILE, A_REAL_BOX);
    const filled = Math.max(
      A_REAL_TILE.wideUm / view.zoom / A_REAL_BOX.width,
      A_REAL_TILE.tallUm / view.zoom / A_REAL_BOX.height,
    );
    expect(filled).toBeCloseTo(1, 6);
  });

  it("is far coarser than one voxel to one pixel, which is the fault it fixes", () => {
    const view = theViewThatShowsAllOf(A_REAL_TILE, A_REAL_BOX);
    const oneVoxelToOnePixel = 1.1;
    expect(view.zoom).toBeGreaterThan(oneVoxelToOnePixel * 4);
  });

  it("says nothing about an acquisition with no size, rather than dividing by it", () => {
    expect(theViewThatShowsAllOf({ atUm: { x: 0, y: 0 }, wideUm: 0, tallUm: 0 }, A_REAL_BOX))
      .toBeNull();
    expect(theViewThatShowsAllOf(null, A_REAL_BOX)).toBeNull();
  });

  it("survives a box that has not been measured yet", () => {
    const view = theViewThatShowsAllOf(A_REAL_TILE, { width: 0, height: 0 });
    expect(Number.isFinite(view.zoom)).toBe(true);
    expect(view.zoom).toBeGreaterThan(0);
  });
});
