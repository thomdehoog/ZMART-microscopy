import { describe, it, expect } from "vitest";
import {
  maskLayerName, maskLayersOn, newMaskLayer, replaceMaskLayer,
} from "./mask-layers.js";

describe("a mask layer is named by what it outlines and how it was made", () => {
  it("names the fast detector's masks nuclei and Cellpose's cells", () => {
    expect(maskLayerName("fast")).toBe("nuclei, fast");
    expect(maskLayerName("robust")).toBe("cells, cellpose");
  });

  it("counts a second layer of the same name rather than repeating it", () => {
    const first = newMaskLayer({ algo: "fast", kind: "overview" });
    expect(maskLayerName("fast", [first])).toBe("nuclei, fast 2");
    const second = { ...first, name: "nuclei, fast 2" };
    expect(maskLayerName("fast", [first, second])).toBe("nuclei, fast 3");
  });

  it("gives an unknown detector an honest name instead of a wrong one", () => {
    expect(maskLayerName("stardist")).toBe("objects, stardist");
  });
});

describe("a fresh mask layer", () => {
  it("lies on the picture it was laid on, shown, wearing the dress it was given", () => {
    const layer = newMaskLayer({
      algo: "fast", kind: "overview", dress: { colour: "#ffd400", show: "line", alpha: 0.6 },
    });
    expect(layer.kind).toBe("overview");
    expect(layer.shown).toBe(true);
    expect(layer.objects).toBe(0);
    expect(layer.how).toBe("fast");
    expect(layer.dress).toEqual({ colour: "#ffd400", show: "line", alpha: 0.6 });
  });

  it("wears each object its own colour, filled, at 80 % when given no dress", () => {
    expect(newMaskLayer({ algo: "robust", kind: "targets" }).dress)
      .toEqual({ colour: null, show: "fill", alpha: 0.8 });
  });

  it("gets an id of its own", () => {
    const a = newMaskLayer({ algo: "fast", kind: "overview" });
    const b = newMaskLayer({ algo: "fast", kind: "overview" });
    expect(a.id).not.toBe(b.id);
  });
});

describe("the bar follows the image layer", () => {
  const onOverview = newMaskLayer({ algo: "fast", kind: "overview" });
  const onTargets = newMaskLayer({ algo: "robust", kind: "targets" });
  const layers = [onOverview, onTargets];

  it("offers only the mask layers lying on the picture the row is on", () => {
    expect(maskLayersOn(layers, "overview")).toEqual([onOverview]);
    expect(maskLayersOn(layers, "targets")).toEqual([onTargets]);
    expect(maskLayersOn(layers, "focussing")).toEqual([]);
  });

  it("replaces the layer on a picture when a new detection runs there, and keeps the others", () => {
    const again = newMaskLayer({ algo: "robust", kind: "overview", existing: layers });
    const after = replaceMaskLayer(layers, again);
    expect(after).toEqual([onTargets, again]);
    expect(again.name).toBe("cells, cellpose 2");
  });
});
