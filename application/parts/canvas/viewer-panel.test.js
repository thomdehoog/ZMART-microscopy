import { describe, expect, it, vi } from "vitest";

import { luminanceOf, viewerRowsFor } from "./viewer-panel.js";


describe("Smart Viewer rows at the operator boundary", () => {
  it("keeps nine fields behind three channel controls", async () => {
    const sources = Array.from(
      { length: 9 },
      (_, at) => `http://127.0.0.1:8848/data/7/overview_P${String(at).padStart(6, "0")}.ome.zarr/|zarr3:`,
    );
    const acquisitions = [{
      name: "overview",
      url: sources[0],
      channels: [0, 1, 2].map((channel) => ({
        name: `channel ${channel}`,
        colour: [0, channel / 2, 1],
        window: { low: 192, high: 2575 },
        channelIndex: channel,
        sources,
      })),
    }];
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    const rows = await viewerRowsFor(acquisitions);

    expect(rows).toHaveLength(3);
    expect(rows.map((row) => row.name)).toEqual(["channel 0", "channel 1", "channel 2"]);
    expect(rows.every((row) => row.acquisition === "overview")).toBe(true);
    expect(rows.every((row) => row.sources.length === 9)).toBe(true);
    expect(rows.every((row) => row.source === sources[0])).toBe(true);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});

describe("grey is each colour's share of the light", () => {
  it("weighs a colour as a desaturation does, so three greys add to what the colours read as", () => {
    expect(luminanceOf([1, 1, 1])).toBeCloseTo(1, 6);
    expect(luminanceOf([0, 1, 0.4])).toBeCloseTo(0.744, 3);   // the palette's green
    expect(luminanceOf([1, 0.2, 1])).toBeCloseTo(0.428, 3);   // magenta
    expect(luminanceOf([0.2, 0.8, 1])).toBeCloseTo(0.687, 3); // cyan
    /* The three palette colours together stay under white: a pixel bright
       in all three does not clip the way three whites did. */
    expect(luminanceOf([0, 1, 0.4]) + luminanceOf([1, 0.2, 1]) + luminanceOf([0.2, 0.8, 1]))
      .toBeLessThan(2);
  });
});
