/* The plot's population and selection are stamped into pixels once and
   drawn as pictures after that: an arc per cell per frame took seconds at
   half a million cells, and a drag redraws every frame. The stamping is
   pure, so it is pinned here on a tiny picture. */

import { describe, it, expect } from "vitest";
import { stampDots, rgbOf } from "./dots.js";

const at = (data, w, x, y) => Array.from(data.slice((y * w + x) * 4, (y * w + x) * 4 + 4));

describe("stamping dots", () => {
  it("lays a disc of the ink at every point, at the alpha asked", () => {
    const w = 9, h = 9;
    const data = new Uint8ClampedArray(w * h * 4);
    stampDots(data, w, h, [[4, 4]], { radius: 1.5, rgb: [10, 20, 30], alpha: 0.5 });
    expect(at(data, w, 4, 4)).toEqual([10, 20, 30, 128]);
    expect(at(data, w, 5, 4)).toEqual([10, 20, 30, 128]);
    expect(at(data, w, 7, 4), "outside the disc").toEqual([0, 0, 0, 0]);
  });

  it("builds up where dots overlap, the way translucent arcs did", () => {
    const w = 5, h = 5;
    const data = new Uint8ClampedArray(w * h * 4);
    stampDots(data, w, h, [[2, 2], [2, 2]], { radius: 0.5, rgb: [0, 0, 255], alpha: 0.5 });
    /* Half over half is three quarters; the byte in between rounds it up one. */
    expect(at(data, w, 2, 2)[3]).toBe(192);
  });

  it("rings a disc in a second ink when asked, and clips at the edge", () => {
    const w = 7, h = 7;
    const data = new Uint8ClampedArray(w * h * 4);
    stampDots(data, w, h, [[0, 3]], {
      radius: 1.5, rgb: [0, 200, 0], alpha: 1, ring: { width: 1, rgb: [255, 255, 255] },
    });
    expect(at(data, w, 0, 3)).toEqual([0, 200, 0, 255]);
    expect(at(data, w, 2, 3), "the ring").toEqual([255, 255, 255, 255]);
    expect(at(data, w, 3, 3)).toEqual([0, 0, 0, 0]);
  });

  it("reads a css colour into bytes", () => {
    expect(rgbOf("#0a141e")).toEqual([10, 20, 30]);
    expect(rgbOf("rgb(1, 2, 3)")).toEqual([1, 2, 3]);
    expect(rgbOf("rgba(1, 2, 3, 0.5)")).toEqual([1, 2, 3]);
  });
});
