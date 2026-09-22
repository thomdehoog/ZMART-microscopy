// @vitest-environment jsdom
/* Which pair the feature plot opens on. The detector's two stand-ins until
   the classical features land; then eccentricity against intensity_mean,
   once. Every measured column is in the pickers, and a pair chosen by
   hand is always kept. */

import { describe, it, expect, beforeAll } from "vitest";
import gate from "./gate.js";

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
});

const cell = (id, features) => ({ id, x: id, y: id, area: 10, intensity: 5, features });
const detected = [cell(1), cell(2)];
const measured = [
  cell(1, { area: 10, intensity_mean: 5, eccentricity: 0.2, solidity: 0.91, perimeter: 30 }),
  cell(2, { area: 12, intensity_mean: 7, eccentricity: 0.6, solidity: 0.85, perimeter: 36 }),
];

const mounted = (cells) => {
  const host = document.createElement("div");
  let current = cells;
  const panel = gate.mount(host, {
    cells: () => current,
    gated: () => new Set(),
    acquired: () => new Set(),
    gates: () => [],
    cap: () => null,
    setGates: () => {},
    showing: () => true,
    sizeCanvas: () => false,
    css: () => "#000",
  });
  const pair = () => [host.querySelector("#gate-fx").value, host.querySelector("#gate-fy").value];
  return { host, pair, land: (cells) => { current = cells; panel.redraw(); } };
};

describe("the plot's pair", () => {
  it("opens on the detector's stand-ins before the features land", () => {
    expect(mounted(detected).pair()).toEqual(["area", "intensity"]);
  });

  it("moves to intensity_mean by eccentricity when they land", () => {
    const plot = mounted(detected);
    plot.land(measured);
    expect(plot.pair()).toEqual(["intensity_mean", "eccentricity"]);
    const offered = [...plot.host.querySelectorAll("#gate-fx option")].map((o) => o.value);
    expect(offered).toContain("solidity");
  });

  it("keeps a pair chosen by hand through every landing after it", () => {
    const plot = mounted(detected);
    plot.land(measured);
    const fx = plot.host.querySelector("#gate-fx");
    fx.value = "solidity";
    fx.dispatchEvent(new Event("change"));
    expect(plot.pair()).toEqual(["solidity", "eccentricity"]);
    plot.land(measured);
    expect(plot.pair()).toEqual(["solidity", "eccentricity"]);
  });

  it("moves once: a pair the operator left alone after the move is not moved again", () => {
    const plot = mounted(measured);
    expect(plot.pair()).toEqual(["intensity_mean", "eccentricity"]);
    plot.land(measured);
    expect(plot.pair()).toEqual(["intensity_mean", "eccentricity"]);
  });
});
