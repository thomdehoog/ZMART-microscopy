// @vitest-environment jsdom
/* A step may have a sentence to say under the active reading, in the
   warning ink: the slot draws it when the step hands one back, and nothing
   when it hands back null. */

import { describe, it, expect } from "vitest";
import { renderRecordingSlot } from "./recording-slot.js";

const aSlot = (job) => ({
  type: "autofocus", seq: 1, active: "autofocus-1",
  records: [{
    id: "autofocus-1", name: "Focussing 1", summary: "20x · 256 × 256 µm",
    detail: [], frameUm: 256, kind: null, changeable: { job },
  }],
});

const rendered = (job, warn) => {
  const host = document.createElement("div");
  host.id = "focus-preset";
  renderRecordingSlot(host, {
    label: "Focussing configuration", unnamed: true,
    takes: "Import focussing configuration", retakes: "Update",
    slot: () => aSlot(job), setSlot: () => {}, running: () => false,
    readSetting: () => Promise.resolve(null), changed: () => {},
    warn,
  });
  return host;
};

const sameAsOverview = (overview) => (record) =>
  record.changeable?.job === overview
    ? `Same job as the overview (${overview}). Select the focussing job in LAS X and press Update.`
    : null;

describe("a warning under the active reading", () => {
  it("is said when the focussing reading came off the overview's job", () => {
    const host = rendered("Overview", sameAsOverview("Overview"));
    expect(host.querySelector(".rec-warn").textContent)
      .toBe("⚠ Same job as the overview (Overview). Select the focussing job in LAS X and press Update.");
  });

  it("is not there when the reading came off another job", () => {
    const host = rendered("AF Job", sameAsOverview("Overview"));
    expect(host.querySelector(".rec-warn")).toBeNull();
  });
});
