import { describe, it, expect } from "vitest";
import { sweep, scoreAt, debrisAt, SWEEP_N }
  from "../../../parts/microscope/pretend-sample/sweep.js";

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
});

describe("debris is the failure worth modelling", () => {
  it("a speck is put in some fields and not others, always the same ones", () => {
    expect(sweep({ focusZ: FOCUS_Z, index: withDebris, metric: "brenner" }).hasDebris).toBe(true);
    expect(sweep({ focusZ: FOCUS_Z, index: withoutDebris, metric: "brenner" }).hasDebris).toBe(false);
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
