import { describe, expect, it } from "vitest";
import { displayFor, displayQueryFor } from "./display-of.js";

const snapshot = {
  channels: [
    { acquisition: "overview", name: "channel 0",
      requested: { visible: true, effectiveVisible: true, color: "#22c55e", window: { low: 225, high: 3863 } } },
    { acquisition: "overview", name: "channel 1",
      requested: { visible: false, effectiveVisible: false, color: "#d946ef", window: { low: 0, high: 4000 } } },
    { acquisition: "target", name: "channel 0",
      requested: { visible: true, effectiveVisible: true, color: "#22c55e", window: { low: 100, high: 900 } } },
    { acquisition: "overview", name: "something else",
      requested: { visible: true, effectiveVisible: true, color: "#ffffff", window: { low: 0, high: 1 } } },
  ],
};

describe("the display the copies are asked with", () => {
  it("is one entry per channel row of the acquisition, with its window, colour and visibility", () => {
    expect(displayFor(snapshot, "overview")).toEqual([
      { c: 0, visible: true, window: [225, 3863], color: "#22c55e" },
      { c: 1, visible: false, window: [0, 4000], color: "#d946ef" },
    ]);
    expect(displayFor(snapshot, "target")).toEqual([
      { c: 0, visible: true, window: [100, 900], color: "#22c55e" },
    ]);
  });

  it("is what the whole group shows, not only what the row asked: a hidden group hides its rows", () => {
    const hidden = { channels: [{ acquisition: "overview", name: "channel 0",
      requested: { visible: true, effectiveVisible: false, color: "#22c55e", window: { low: 0, high: 10 } } }] };
    expect(displayFor(hidden, "overview")[0].visible).toBe(false);
  });

  it("leaves out a row with no window, and asks for nothing when there is nothing to ask with", () => {
    const bare = { channels: [{ acquisition: "overview", name: "channel 0", requested: { visible: true, color: "#fff", window: null } }] };
    expect(displayFor(bare, "overview")).toEqual([]);
    expect(displayQueryFor(bare, "overview")).toBe("");
    expect(displayQueryFor(null, "overview")).toBe("");
  });

  it("is a query the bridge can read back", () => {
    const query = displayQueryFor(snapshot, "target");
    expect(query.startsWith("?display=")).toBe(true);
    expect(JSON.parse(decodeURIComponent(query.slice("?display=".length))))
      .toEqual([{ c: 0, visible: true, window: [100, 900], color: "#22c55e" }]);
  });
});
