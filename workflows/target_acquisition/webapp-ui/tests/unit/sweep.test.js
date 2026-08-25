import { describe, it, expect } from "vitest";
import {
  sweep, findCandidates, pickPeak, scoreAt, debrisAt,
  METRIC_KEYS, MIN_TISSUE_WIDTH_UM, SWEEP_N,
} from "../../src/frame/lib/sweep.js";

const FOCUS_Z = -412;

/** An index the generator gives a speck to, and one it does not. */
const withDebris = [...Array(40).keys()].find((i) => debrisAt(i));
const withoutDebris = [...Array(40).keys()].find((i) => !debrisAt(i));

describe("the sweep is a sweep", () => {
  it("returns the sampled curve, in order", () => {
    const { samples } = sweep({ focusZ: FOCUS_Z, index: withoutDebris, metric: "brenner" });
    expect(samples).toHaveLength(SWEEP_N);
    for (let i = 1; i < samples.length; i++) expect(samples[i].z).toBeGreaterThan(samples[i - 1].z);
  });

  it("is deterministic — the same point twice gives the same curve", () => {
    const a = sweep({ focusZ: FOCUS_Z, index: 3, metric: "brenner" });
    const b = sweep({ focusZ: FOCUS_Z, index: 3, metric: "brenner" });
    expect(a.samples).toEqual(b.samples);
  });

  it("peaks near the true focus when nothing is in the way", () => {
    for (const metric of METRIC_KEYS) {
      const { candidates } = sweep({ focusZ: FOCUS_Z, index: withoutDebris, metric });
      expect(Math.abs(pickPeak(candidates).z - FOCUS_Z)).toBeLessThan(3);
    }
  });
});

describe("debris is the failure worth modelling", () => {
  it("a speck adds a second, narrower candidate", () => {
    const { candidates, hasDebris } = sweep({ focusZ: FOCUS_Z, index: withDebris, metric: "brenner" });
    expect(hasDebris).toBe(true);
    expect(candidates.length).toBeGreaterThan(1);
    expect(candidates.some((c) => c.narrow)).toBe(true);
  });

  it("the speck out-scores the tissue — a plain argmax walks into it", () => {
    const { candidates } = sweep({ focusZ: FOCUS_Z, index: withDebris, metric: "brenner" });
    const tallest = candidates.reduce((a, b) => (b.s > a.s ? b : a));
    expect(tallest.narrow, "if this ever fails the mock stopped modelling the bug").toBe(true);
  });

  it("pickPeak refuses it and takes the tissue instead", () => {
    const { candidates } = sweep({ focusZ: FOCUS_Z, index: withDebris, metric: "brenner" });
    const chosen = pickPeak(candidates);
    expect(chosen.narrow).toBe(false);
    expect(chosen.width).toBeGreaterThanOrEqual(MIN_TISSUE_WIDTH_UM);
    expect(Math.abs(chosen.z - FOCUS_Z)).toBeLessThan(4);
  });

  it("still answers when every candidate is narrow, but flags it", () => {
    const spike = Array.from({ length: 21 }, (_, i) => ({ z: i, s: i === 10 ? 1 : 0.02 }));
    const chosen = pickPeak(findCandidates(spike));
    expect(chosen.narrow).toBe(true);
  });
});

describe("candidates", () => {
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

describe("scoreAt reads between the samples", () => {
  const samples = [{ z: 0, s: 0 }, { z: 10, s: 1 }, { z: 20, s: 0 }];

  it("interpolates linearly", () => {
    expect(scoreAt(samples, 5)).toBeCloseTo(0.5, 9);
    expect(scoreAt(samples, 15)).toBeCloseTo(0.5, 9);
  });

  it("clamps outside the swept range", () => {
    expect(scoreAt(samples, -100)).toBe(0);
    expect(scoreAt(samples, 100)).toBe(0);
  });
});
