/**
 * The slider under the picture: there only when the picture has more than
 * one moment, and driving the engine when moved.
 */
import { describe, expect, it } from "vitest";
import { mountTheAxes } from "./axes.js";

/* Enough of an element for the slider: what is read and written on it. */
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
  return { axes: anElement(), axisT: anElement(), moment: anElement(), momentPlay: anElement(), momentReadout: anElement() };
}
function pressed(button) { return button.attributes?.["aria-pressed"]; }
const settle = () => new Promise((resolve) => setTimeout(resolve, 30));

describe("the slider under the picture", () => {
  it("shows nothing for a single-moment picture, or no picture at all", () => {
    const parts = theParts();
    const axes = mountTheAxes(parts, { picture: () => null, watchEveryMs: 0 });
    axes.refresh();
    expect(parts.axes.hidden).toBe(true);
    const still = { theMomentsItCanShow: () => null };
    mountTheAxes(parts, { picture: () => still, watchEveryMs: 0 }).refresh();
    expect(parts.axes.hidden).toBe(true);
    expect(parts.axisT.hidden).toBe(true);
  });

  it("offers T for a timelapse, counted in moments from the first", () => {
    const parts = theParts();
    const timelapse = { theMomentsItCanShow: () => ({ many: 12, at: 3 }) };
    mountTheAxes(parts, { picture: () => timelapse, watchEveryMs: 0 }).refresh();
    expect(parts.axes.hidden).toBe(false);
    expect(parts.axisT.hidden).toBe(false);
    expect([parts.moment.min, parts.moment.max, parts.moment.value]).toEqual(["0", "11", "3"]);
    expect(parts.momentReadout.textContent).toBe("moment 4 of 12");
  });

  it("moves the picture when the slider is moved, and says where it went", async () => {
    const parts = theParts();
    const went = [];
    const timelapse = { theMomentsItCanShow: () => ({ many: 5, at: 0 }), setMoment: (t) => went.push(t) };
    mountTheAxes(parts, { picture: () => timelapse, watchEveryMs: 0 }).refresh();
    parts.moment.value = "4";
    parts.moment.fire("input");
    await settle();
    expect(went).toEqual([4]);
    expect(parts.momentReadout.textContent).toBe("moment 5 of 5");
  });

  it("notices for itself when the picture learns its length, without being told", async () => {
    const parts = theParts();
    let moments = null;
    const viewer = { theMomentsItCanShow: () => moments };
    const axes = mountTheAxes(parts, { picture: () => viewer, watchEveryMs: 5 });
    axes.refresh();
    expect(parts.axes.hidden).toBe(true);
    moments = { many: 9, at: 2 };
    await settle();
    expect(parts.axisT.hidden).toBe(false);
    expect(parts.momentReadout.textContent).toBe("moment 3 of 9");
    axes.stop();
  });

  it("plays through the moments by itself, round to the start, and pauses when pressed again", async () => {
    const parts = theParts();
    const went = [];
    const timelapse = { theMomentsItCanShow: () => ({ many: 3, at: 0 }), setMoment: (t) => went.push(t) };
    /* Slower than a frame, so no step is coalesced away and every moment
       reaches the engine. */
    const axes = mountTheAxes(parts, { picture: () => timelapse, watchEveryMs: 0, playEveryMs: 25 });
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
    axes.stop();
  });

  it("goes away again when the picture closes or stands still", () => {
    const parts = theParts();
    let viewer = { theMomentsItCanShow: () => ({ many: 4, at: 0 }) };
    const axes = mountTheAxes(parts, { picture: () => viewer, watchEveryMs: 0 });
    axes.refresh();
    expect(parts.axes.hidden).toBe(false);
    viewer = null;
    axes.refresh();
    expect(parts.axes.hidden).toBe(true);
  });
});
