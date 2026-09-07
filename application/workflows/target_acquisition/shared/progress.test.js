// @vitest-environment jsdom
/* One run's story: a bar that fills as things land and sweeps while busy,
   and one line under it -- what is being done at the left, the arithmetic
   at the right. Shared by detection and acquisition, so the words are
   pinned once. */

import { describe, it, expect } from "vitest";
import { progressBox } from "./progress.js";

const box = () => {
  let t = 0;
  const built = progressBox("Acquisition progress", { now: () => t });
  return { ...built, tick: (ms) => { t += ms; } };
};
const words = (b) => [b.doing.textContent, b.count.textContent];
const bar = (b) => b.group.querySelector(".progress-bar");
const fill = (b) => b.group.querySelector(".progress-fill").style.width;

describe("a progress box", () => {
  it("is hidden until the run starts, then sweeps with nothing counted", () => {
    const b = box();
    expect(b.group.style.display).toBe("none");
    b.say({ start: true, doing: "starting the workers…" });
    expect(b.group.style.display).toBe("");
    expect(words(b)).toEqual(["starting the workers…", ""]);
    expect(bar(b).classList.contains("busy")).toBe(true);
    expect(fill(b)).toBe("0%");
  });

  it("projects the time left from the pace measured since the start", () => {
    const b = box();
    b.say({ start: true });
    b.tick(12 * 6_000);
    b.say({ done: 12, of: 40, doing: "tile 12 · c0347" });
    expect(words(b)).toEqual(["tile 12 · c0347", "12 of 40 · ≈ 2 min 48 s left"]);
    expect(fill(b)).toBe("30%");
    expect(bar(b).classList.contains("busy")).toBe(true);
  });

  it("ends full and still, with the run's own last words", () => {
    const b = box();
    b.say({ start: true });
    b.tick(1_000);
    b.say({ done: 40, of: 40, doing: "tile 40 · c9001" });
    expect(words(b)[1]).toBe("40 of 40");
    b.say({ ended: true, note: "40 pairs acquired" });
    expect(words(b)).toEqual(["40 pairs acquired", "40 of 40"]);
    expect(bar(b).classList.contains("busy")).toBe(false);
    expect(fill(b)).toBe("100%");
  });

  it("stopped by hand keeps the count where it stopped", () => {
    const b = box();
    b.say({ start: true });
    b.tick(1_000);
    b.say({ done: 12, of: 40, doing: "tile 12 · c0347" });
    b.say({ ended: true, note: "stopped by hand" });
    expect(words(b)).toEqual(["stopped by hand", "12 of 40"]);
    expect(bar(b).classList.contains("busy")).toBe(false);
  });

  it("keeps sweeping through a whole-population phase after every field landed", () => {
    const b = box();
    b.say({ start: true });
    b.tick(1_000);
    b.say({ done: 9, of: 9, phase: "umap", running: true, objects: 4054 });
    expect(words(b)[1]).toBe("9 of 9 · 4054 objects");
    expect(bar(b).classList.contains("busy")).toBe(true);
  });
});
