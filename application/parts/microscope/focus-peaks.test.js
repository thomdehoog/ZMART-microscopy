/** Reading a focus curve: the peaks in it, and which one is the tissue. */

import { describe, it, expect } from "vitest";
import { findCandidates, pickPeak, MIN_TISSUE_WIDTH_UM } from "./focus-peaks.js";
import { sweep, debrisAt, METRIC_KEYS } from "./pretend-sample/sweep.js";

const FOCUS_Z = -412;

/** An index the generator gives a speck to, and one it does not. */
const withDebris = [...Array(40).keys()].find((i) => debrisAt(i));
const withoutDebris = [...Array(40).keys()].find((i) => !debrisAt(i));

/** The peaks of a swept curve, found the way the page finds them. */
const peaksOf = (index, metric = "brenner") =>
  findCandidates(sweep({ focusZ: FOCUS_Z, index, metric }).samples);

describe("finding the peaks", () => {
  it("peaks near the true focus when nothing is in the way", () => {
    for (const metric of METRIC_KEYS) {
      expect(Math.abs(pickPeak(peaksOf(withoutDebris, metric)).z - FOCUS_Z)).toBeLessThan(3);
    }
  });

  it("refines the peak between samples rather than snapping to one", () => {
    const asym = Array.from({ length: 21 }, (_, i) => ({ z: i, s: Math.exp(-((i - 10.4) ** 2) / 40) }));
    const [c] = findCandidates(asym);
    expect(c.z).toBeGreaterThan(10);
    expect(c.z).toBeLessThan(11);
    expect(c.z).not.toBe(10);
  });

  it("never returns empty, even for a flat curve", () => {
    const flat = Array.from({ length: 21 }, (_, i) => ({ z: i, s: 0.5 }));
    expect(findCandidates(flat)).toHaveLength(1);
  });
});

describe("debris is the failure the rule exists for", () => {
  it("a speck adds a second, narrower peak", () => {
    const candidates = peaksOf(withDebris);
    expect(candidates.length).toBeGreaterThan(1);
    expect(candidates.some((c) => c.narrow)).toBe(true);
  });

  it("the speck out-scores the tissue — a plain argmax walks into it", () => {
    const tallest = peaksOf(withDebris).reduce((a, b) => (b.s > a.s ? b : a));
    expect(tallest.narrow, "if this ever fails the mock stopped modelling the bug").toBe(true);
  });

  it("pickPeak refuses it and takes the tissue instead", () => {
    const chosen = pickPeak(peaksOf(withDebris));
    expect(chosen.narrow).toBe(false);
    expect(chosen.width).toBeGreaterThanOrEqual(MIN_TISSUE_WIDTH_UM);
    expect(Math.abs(chosen.z - FOCUS_Z)).toBeLessThan(4);
  });

  it("still answers when every peak is narrow, but flags it", () => {
    const spike = Array.from({ length: 21 }, (_, i) => ({ z: i, s: i === 10 ? 1 : 0.02 }));
    expect(pickPeak(findCandidates(spike)).narrow).toBe(true);
  });
});
