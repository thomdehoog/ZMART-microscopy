/* What a store's own description says about why a strict reader will not open it.
 *
 * `viz_studio/options/what-a-reader-refuses.js` exists because the strict engine
 * does not say. Handed a store it will not accept, neuroglancer never finishes
 * opening — no error, no rejected promise — so the page can only wait, give up,
 * and report a silence. An operator reads "not ready after twenty-five seconds"
 * and cannot tell whether their data or this software is at fault.
 *
 * Both faults below were met on one 75 GB skin biopsy from another laboratory
 * that Viv drew perfectly and neuroglancer would not open at all. Each was enough
 * on its own, and separating them meant building stores that differed in exactly
 * one thing. The point of the checker is that nobody has to do that again.
 *
 * The tests that matter most here are the quiet ones: everything measured to be
 * harmless must stay unreported, because a checker that guesses sends whoever
 * reads it to the wrong place.
 */

import { describe, it, expect } from "vitest";
import {
  whyAReaderMayRefuse,
} from "../../../../../viz_studio/options/what-a-reader-refuses.js";

/** A description with nothing wrong with it, to vary one thing at a time. */
const soundEnough = () => ({
  multiscales: [{
    version: "0.4",
    axes: [
      { name: "t", type: "time", unit: "millisecond" },
      { name: "c", type: "channel" },
      { name: "z", type: "space", unit: "micrometer" },
      { name: "y", type: "space", unit: "micrometer" },
      { name: "x", type: "space", unit: "micrometer" },
    ],
    datasets: [{ path: "0" }],
  }],
});

describe("what a strict reader will refuse", () => {
  it("says nothing about a description that is sound", () => {
    expect(whyAReaderMayRefuse(soundEnough())).toEqual([]);
  });

  it("names an axis measured in um, and what the format asks for instead", () => {
    const described = soundEnough();
    for (const axis of described.multiscales[0].axes) {
      if (axis.type === "space") axis.unit = "um";
    }
    const [said] = whyAReaderMayRefuse(described);
    expect(said).toContain('"um"');
    expect(said).toContain('"micrometer"');
  });

  it("says it once however many axes are spelled that way", () => {
    const described = soundEnough();
    for (const axis of described.multiscales[0].axes) {
      if (axis.type === "space") axis.unit = "um";
    }
    expect(whyAReaderMayRefuse(described)).toHaveLength(1);
  });

  it("names a channel whose display window was written as nothing", () => {
    const described = soundEnough();
    described.omero = { channels: [
      { label: "561 nm", color: "00FF00", window: null },
      { label: "638 nm", color: "FF00FF", window: null },
    ] };
    const [said] = whyAReaderMayRefuse(described);
    expect(said).toContain("display window");
  });

  it("accepts a channel that leaves the window out, which readers do", () => {
    const described = soundEnough();
    described.omero = { channels: [{ label: "561 nm", color: "00FF00" }] };
    expect(whyAReaderMayRefuse(described)).toEqual([]);
  });

  it("reports both when both are wrong, since either alone is enough", () => {
    const described = soundEnough();
    described.multiscales[0].axes[2].unit = "um";
    described.omero = { channels: [{ label: "561 nm", window: null }] };
    expect(whyAReaderMayRefuse(described)).toHaveLength(2);
  });

  it("stays quiet about everything measured to be harmless", () => {
    const described = soundEnough();
    described.multiscales[0].name = "/";
    for (const axis of described.multiscales[0].axes) axis.discrete = false;
    described.omero = { channels: [
      { label: "561 nm", color: "00FF00", window: { start: 0, end: 4095 } },
    ] };
    expect(whyAReaderMayRefuse(described)).toEqual([]);
  });

  it("says nothing rather than throwing when handed nothing at all", () => {
    expect(whyAReaderMayRefuse(null)).toEqual([]);
    expect(whyAReaderMayRefuse({})).toEqual([]);
    expect(whyAReaderMayRefuse({ multiscales: [{}] })).toEqual([]);
  });
});
