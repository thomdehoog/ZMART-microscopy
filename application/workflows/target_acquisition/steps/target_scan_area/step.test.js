// @vitest-environment jsdom
/* The Add scan areas box: the fourth row is a two-way choice, not a switch.
   "Fewest" is the placing that lets neighbours share a tile; "One per
   target" centres a tile on every target. Exactly one side is chosen. */

import { describe, it, expect } from "vitest";
import { selectionPanel } from "./step.js";

const mounted = (rules = {}) => {
  const set = [];
  let changes = 0;
  const host = document.createElement("div");
  selectionPanel.mount(host, {
    rules: () => ({ margin: 1, objectsMax: 50, minimise: true, overlapMin: 0.2, ...rules }),
    setRule: (key, value) => set.push([key, value]),
    changed: () => { changes += 1; },
    restricted: () => new Set(),
    tiles: () => [],
    plan: () => null,
    recordingSlot: () => {},
  });
  return { host, set, changes: () => changes };
};

describe("Number of tiles", () => {
  it("is a segmented strip on the controls column with Fewest chosen by default", () => {
    const { host } = mounted();
    const row = host.querySelector("#tiles-count").parentElement;
    expect(row.querySelector("label").textContent).toBe("Number of tiles");
    const strip = row.querySelector(".seg");
    const sides = [...strip.querySelectorAll("button[role=radio]")];
    expect(sides.map((b) => b.textContent)).toEqual(["Fewest", "One per target"]);
    expect(sides.map((b) => b.getAttribute("aria-checked"))).toEqual(["true", "false"]);
    expect(host.querySelector("#tiles-minimise")).toBeNull();
  });

  it("shows One per target chosen when the rule is off", () => {
    const { host } = mounted({ minimise: false });
    const sides = [...host.querySelectorAll("#tiles-count button")];
    expect(sides.map((b) => b.getAttribute("aria-checked"))).toEqual(["false", "true"]);
  });

  it("pressing a side sets the rule, says so, and moves the choice", () => {
    const { host, set, changes } = mounted();
    const [fewest, onePer] = host.querySelectorAll("#tiles-count button");
    onePer.click();
    expect(set).toEqual([["minimise", false]]);
    expect(changes()).toBe(1);
    expect([fewest, onePer].map((b) => b.getAttribute("aria-checked"))).toEqual(["false", "true"]);
    fewest.click();
    expect(set).toEqual([["minimise", false], ["minimise", true]]);
    expect(changes()).toBe(2);
    expect([fewest, onePer].map((b) => b.getAttribute("aria-checked"))).toEqual(["true", "false"]);
  });

  it("keeps the three rows above it as they were: a checkbox, words, a number", () => {
    const { host } = mounted();
    for (const id of ["gate-max", "tiles-margin", "overlap-min"]) {
      const line = host.querySelector(`#${id}`).parentElement;
      expect(line.querySelector(`#${id}-on`).type).toBe("checkbox");
      expect(host.querySelector(`#${id}`).type).toBe("number");
    }
  });
});
