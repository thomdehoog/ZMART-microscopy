import { describe, it, expect } from "vitest";
import {
  emptySlot, withRecording, withoutRecording, withActive,
  activeRecording, nextName, nextReadingIndex,
} from "../../parts/microscope/recordings.js";
import { sampleReading } from "../../parts/microscope/settings.js";

/** Set the instrument up, name it, record it — what the panel's button does. */
const record = (slot, name = "") => withRecording(slot, {
  name,
  reading: sampleReading(slot.type, nextReadingIndex(slot)),
});

describe("a slot holds one reading of the instrument", () => {
  it("starts with nothing recorded and nothing active", () => {
    const slot = emptySlot("acquisition");
    expect(slot.records).toEqual([]);
    expect(activeRecording(slot)).toBe(null);
  });

  it("recording again replaces what was there", () => {
    const slot = record(record(emptySlot("acquisition"), "overview"), "hires");
    expect(slot.records.map((r) => r.name)).toEqual(["Hires"]);
  });

  it("reads the instrument as it is set now, so a re-recording differs", () => {
    const first = record(emptySlot("acquisition"), "overview");
    expect(first.records[0].summary).toBe("HC PL APO 20x / 0.75 NA dry, 676 × 676 µm");
    expect(first.records[0].frameUm).toBe(676);
    /* The pretend operator changed the objective in between: the second
       reading comes back as the instrument now stands, not as it stood. */
    const again = record(first, "hires");
    expect(again.records[0].summary).toBe("HC PL APO 63x / 1.40 NA oil, 102 × 102 µm");
    expect(again.records[0].frameUm).toBe(102);
  });

  it("gives an unnamed recording a name counted over every reading taken", () => {
    const slot = record(record(emptySlot("autofocus")));
    expect(slot.records.map((r) => r.name)).toEqual(["Default 2"]);
    expect(nextName(slot)).toBe("Default 3");
  });

  it("carries the detail behind the summary, so the row can unfold", () => {
    const [only] = record(emptySlot("autofocus"), "coarse").records;
    expect(only.detail.map(([label]) => label)).toContain("Metric");
  });

  it("keeps acquisition channels as data rather than parsing the detail rows later", () => {
    const [only] = record(emptySlot("acquisition"), "overview").records;
    expect(only.channelCount).toBe(2);
    expect(only.channels.map((channel) => channel.label)).toEqual(["DAPI", "GFP"]);
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

  it("carries the offset along as readings are taken", () => {
    const slot = record(emptySlot("acquisition", 1), "hires");
    expect(slot.records[0].summary).toBe("HC PL APO 63x / 1.40 NA oil, 102 × 102 µm");
    expect(nextReadingIndex(slot)).toBe(2);
  });
});

describe("the recording held is the one the step is taken with", () => {
  it("activates what was just recorded, since recording is done in order to use it", () => {
    const slot = record(emptySlot("acquisition"), "overview");
    expect(activeRecording(slot).name).toBe("Overview");
  });

  it("refuses to activate what is not in the slot", () => {
    const slot = record(emptySlot("acquisition"), "overview");
    expect(withActive(slot, "nothing-like-it")).toEqual(slot);
  });
});

describe("forgetting and replacing", () => {
  it("empties out, active and all, when the recording is forgotten", () => {
    const slot = record(emptySlot("acquisition"), "overview");
    const left = withoutRecording(slot, slot.active);
    expect(left.records).toEqual([]);
    expect(activeRecording(left)).toBe(null);
  });

  /* The id is how the rest of the run notices the reading changed: a focus
     map measured under the old preset must not quietly claim to belong to
     the new one. */
  it("never hands a replaced recording's id to the next one", () => {
    const slot = record(emptySlot("acquisition"), "overview");
    const again = record(slot, "overview");
    expect(again.records[0].id).not.toBe(slot.records[0].id);
  });

  it("never hands a forgotten recording's id to the next one either", () => {
    const slot = record(emptySlot("acquisition"), "overview");
    const gone = withoutRecording(slot, slot.records[0].id);
    const again = record(gone, "overview");
    expect(again.records[0].id).not.toBe(slot.records[0].id);
  });
});
