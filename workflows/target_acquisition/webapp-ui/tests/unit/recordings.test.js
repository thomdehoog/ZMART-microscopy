import { describe, it, expect } from "vitest";
import {
  emptySlot, withRecording, withoutRecording, withActive,
  activeRecording, nextName, nextReadingIndex,
} from "../../src/lib/recordings.js";
import { sampleReading } from "../../src/lib/microscopes.js";

/** Set the instrument up, name it, record it — what the panel's button does. */
const record = (slot, name = "") => withRecording(slot, {
  name,
  reading: sampleReading(slot.type, nextReadingIndex(slot)),
});

describe("a slot accumulates what was read off the instrument", () => {
  it("starts with nothing recorded and nothing active", () => {
    const slot = emptySlot("acquisition");
    expect(slot.records).toEqual([]);
    expect(activeRecording(slot)).toBe(null);
  });

  it("adds a reading to what is there rather than replacing it", () => {
    const slot = record(record(emptySlot("acquisition"), "overview"), "hires");
    expect(slot.records.map((r) => r.name)).toEqual(["Overview", "Hires"]);
  });

  it("reads the instrument as it is set now, so two recordings differ", () => {
    const slot = record(record(emptySlot("acquisition"), "overview"), "hires");
    const [overview, hires] = slot.records;
    expect(overview.summary).toBe("5x / 0.15 NA dry · 2 channels");
    expect(overview.frameUm).toBe(2662);
    expect(hires.summary).toBe("63x / 1.40 NA oil · 2 channels");
    expect(hires.frameUm).toBe(102);
  });

  it("gives an unnamed recording a name of its own, counted from what is there", () => {
    const slot = record(record(emptySlot("autofocus")));
    expect(slot.records.map((r) => r.name)).toEqual(["Default 1", "Default 2"]);
    expect(nextName(slot)).toBe("Default 3");
  });

  it("carries the detail behind the summary, so the row can unfold", () => {
    const [only] = record(emptySlot("autofocus"), "coarse").records;
    expect(only.detail.map(([label]) => label)).toContain("Metric");
  });

  it("leaves the slot it was handed alone", () => {
    const slot = emptySlot("acquisition");
    record(slot, "overview");
    expect(slot.records).toEqual([]);
  });
});

describe("which state of the instrument a slot starts from", () => {
  it("reads the first one it knows unless told otherwise", () => {
    expect(nextReadingIndex(emptySlot("acquisition"))).toBe(0);
  });

  it("carries the offset along as recordings accumulate", () => {
    const slot = record(emptySlot("acquisition", 1), "hires");
    expect(slot.records[0].summary).toBe("63x / 1.40 NA oil · 2 channels");
    expect(nextReadingIndex(slot)).toBe(2);
  });
});

describe("one of them is active, and that is what the step is taken with", () => {
  it("activates the newest, since recording is done in order to use it", () => {
    const slot = record(record(emptySlot("acquisition"), "overview"), "hires");
    expect(activeRecording(slot).name).toBe("Hires");
  });

  it("activates another that was recorded earlier", () => {
    const slot = record(record(emptySlot("acquisition"), "overview"), "hires");
    const back = withActive(slot, slot.records[0].id);
    expect(activeRecording(back).name).toBe("Overview");
    expect(back.records).toHaveLength(2);
  });

  it("refuses to activate what is not in the slot", () => {
    const slot = record(emptySlot("acquisition"), "overview");
    expect(withActive(slot, "nothing-like-it")).toEqual(slot);
  });
});

describe("forgetting one leaves the rest", () => {
  it("drops only the one named", () => {
    const slot = record(record(emptySlot("acquisition"), "overview"), "hires");
    const left = withoutRecording(slot, slot.records[0].id);
    expect(left.records.map((r) => r.name)).toEqual(["Hires"]);
  });

  it("activates what is left when the active one goes", () => {
    const slot = record(record(emptySlot("acquisition"), "overview"), "hires");
    const left = withoutRecording(slot, slot.active);
    expect(activeRecording(left).name).toBe("Overview");
  });

  it("leaves the active one alone when another goes", () => {
    const slot = record(record(emptySlot("acquisition"), "overview"), "hires");
    const left = withoutRecording(slot, slot.records[0].id);
    expect(activeRecording(left).name).toBe("Hires");
  });

  it("empties out, active and all, when the last one is forgotten", () => {
    const slot = record(emptySlot("acquisition"), "overview");
    const left = withoutRecording(slot, slot.active);
    expect(left.records).toEqual([]);
    expect(activeRecording(left)).toBe(null);
  });

  it("never hands a forgotten recording's name to the next one", () => {
    const slot = record(emptySlot("acquisition"), "overview");
    const gone = withoutRecording(slot, slot.records[0].id);
    const again = record(gone, "overview");
    expect(again.records[0].id).not.toBe(slot.records[0].id);
  });
});
