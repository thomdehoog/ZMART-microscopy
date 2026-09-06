/**
 * The sliders under the picture: there only when the picture has more than
 * one plane, or more than one moment, and driving the engine when moved.
 */
import { describe, expect, it } from "vitest";
import { mountTheAxes } from "./axes.js";

/* Enough of an element for the sliders: what is read and written on it. */
function anElement() {
  const listeners = {};
  return {
    hidden: false, value: "", min: "", max: "", step: "", textContent: "", attributes: {},
    style: { setProperty() {} },
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(kind, fn) { listeners[kind] = fn; },
    fire(kind) { listeners[kind]?.(); },
  };
}
function theParts() {
  return {
    axes: anElement(), axisZ: anElement(), plane: anElement(), planePlay: anElement(), planeReadout: anElement(),
    axisT: anElement(), moment: anElement(), momentPlay: anElement(), momentReadout: anElement(),
  };
}
function pressed(button) { return button.attributes?.["aria-pressed"]; }
const settle = () => new Promise((resolve) => setTimeout(resolve, 30));

describe("the sliders under the picture", () => {
  it("show nothing for a flat, single-moment picture, or no picture at all", () => {
    const parts = theParts();
    const axes = mountTheAxes(parts, { picture: () => null, watchEveryMs: 0 });
    axes.refresh();
    expect(parts.axes.hidden).toBe(true);
    const flat = { theDepthItCanShow: () => null, theMomentsItCanShow: () => null };
    mountTheAxes(parts, { picture: () => flat, watchEveryMs: 0 }).refresh();
    expect(parts.axes.hidden).toBe(true);
    expect(parts.axisZ.hidden).toBe(true);
    expect(parts.axisT.hidden).toBe(true);
  });

  it("offers Z for a stack, sized in micrometres and starting where the picture is", () => {
    const parts = theParts();
    const stack = {
      theDepthItCanShow: () => ({ lowUm: 0, highUm: 20, stepUm: 1, atUm: 7 }),
      theMomentsItCanShow: () => null,
    };
    mountTheAxes(parts, { picture: () => stack, watchEveryMs: 0 }).refresh();
    expect(parts.axes.hidden).toBe(false);
    expect(parts.axisZ.hidden).toBe(false);
    expect(parts.axisT.hidden).toBe(true);
    expect([parts.plane.min, parts.plane.max, parts.plane.step, parts.plane.value]).toEqual(["0", "20", "1", "7"]);
    expect(parts.planeReadout.textContent).toBe("7 µm · plane 8 of 21");
  });

  it("offers T for a timelapse, counted in moments from the first", () => {
    const parts = theParts();
    const timelapse = {
      theDepthItCanShow: () => null,
      theMomentsItCanShow: () => ({ many: 12, at: 3 }),
    };
    mountTheAxes(parts, { picture: () => timelapse, watchEveryMs: 0 }).refresh();
    expect(parts.axisZ.hidden).toBe(true);
    expect(parts.axisT.hidden).toBe(false);
    expect([parts.moment.min, parts.moment.max, parts.moment.value]).toEqual(["0", "11", "3"]);
    expect(parts.momentReadout.textContent).toBe("moment 4 of 12");
  });

  it("moves the picture when a slider is moved, and says where it went", async () => {
    const parts = theParts();
    const went = { plane: [], moment: [] };
    const both = {
      theDepthItCanShow: () => ({ lowUm: 0, highUm: 10, stepUm: 2, atUm: 0 }),
      theMomentsItCanShow: () => ({ many: 5, at: 0 }),
      setPlane: (um) => went.plane.push(um),
      setMoment: (t) => went.moment.push(t),
    };
    mountTheAxes(parts, { picture: () => both, watchEveryMs: 0 }).refresh();
    expect(parts.axes.hidden).toBe(false);
    parts.plane.value = "6";
    parts.plane.fire("input");
    await settle();
    expect(went.plane).toEqual([6]);
    expect(parts.planeReadout.textContent).toBe("6 µm · plane 4 of 6");
    parts.moment.value = "4";
    parts.moment.fire("input");
    await settle();
    expect(went.moment).toEqual([4]);
    expect(parts.momentReadout.textContent).toBe("moment 5 of 5");
  });

  it("notices for itself when the picture learns its depth, without being told", async () => {
    const parts = theParts();
    let depth = null;
    const viewer = { theDepthItCanShow: () => depth, theMomentsItCanShow: () => null };
    const axes = mountTheAxes(parts, { picture: () => viewer, watchEveryMs: 5 });
    axes.refresh();
    expect(parts.axes.hidden).toBe(true);
    depth = { lowUm: 0, highUm: 68, stepUm: 1, atUm: 34 };
    await settle();
    expect(parts.axisZ.hidden).toBe(false);
    expect(parts.planeReadout.textContent).toBe("34 µm · plane 35 of 69");
    axes.stop();
  });

  it("plays through the moments by itself, round to the start, and pauses when pressed again", async () => {
    const parts = theParts();
    const went = [];
    const timelapse = {
      theDepthItCanShow: () => null,
      theMomentsItCanShow: () => ({ many: 3, at: 0 }),
      setMoment: (t) => went.push(t),
    };
    /* Slower than a frame, so no step is coalesced away and every moment
       reaches the engine. */
    const axes = mountTheAxes(parts, { picture: () => timelapse, watchEveryMs: 0, playEveryMs: { plane: 25, moment: 25 } });
    axes.refresh();
    parts.momentPlay.fire("click");
    expect(pressed(parts.momentPlay)).toBe("true");
    await new Promise((resolve) => setTimeout(resolve, 140));
    parts.momentPlay.fire("click");
    expect(pressed(parts.momentPlay)).toBe("false");
    await settle();
    /* It walked 1, 2, then round to 0 and on: every moment was shown. */
    expect(new Set(went)).toEqual(new Set([0, 1, 2]));
    expect(went.length).toBeGreaterThan(3);
    const shown = went.length;
    await settle();
    expect(went.length, "paused, it walks no further").toBe(shown);
    /* Z has its own; playing T did not touch it. */
    expect(pressed(parts.planePlay)).toBe("false");
    axes.stop();
  });

  it("goes away again when the picture closes or flattens", () => {
    const parts = theParts();
    let viewer = { theDepthItCanShow: () => ({ lowUm: 0, highUm: 4, stepUm: 1, atUm: 0 }), theMomentsItCanShow: () => null };
    const axes = mountTheAxes(parts, { picture: () => viewer, watchEveryMs: 0 });
    axes.refresh();
    expect(parts.axes.hidden).toBe(false);
    viewer = null;
    axes.refresh();
    expect(parts.axes.hidden).toBe(true);
  });
});
