/**
 * Simulating an autofocus z-sweep, and choosing a peak from it.
 *
 * Pure: give it the true focus height at a position and it hands back the
 * sharpness curve a microscope would have measured, plus every candidate peak
 * in it. No DOM, no app state.
 *
 * The reason this exists as its own module is the failure it models. A speck
 * of debris is a hard edge in a single plane, so it out-scores the tissue and
 * over a far narrower range — which is how an autofocus ends up focused on
 * dust. Rejecting peaks too narrow to be tissue is the defence, and keeping
 * the rejected ones in the result is what lets the UI show its work.
 */

import { makeRng } from "./rng.js";

export const METRICS = {
  brenner: {
    label: "Gradient-based", short: "Gradient-based", token: "--m-brenner",
    width: 9.0, bias: 0.0, skew: 0.16, noise: 0.045, speckGain: 1.0,
  },
  dct: {
    label: "Entropy-based", short: "Entropy-based", token: "--m-dct",
    width: 6.2, bias: -0.7, skew: 0.03, noise: 0.028, speckGain: 0.72,
  },
};

export const METRIC_KEYS = Object.keys(METRICS);

export const SWEEP_N = 61;
export const SWEEP_HALF_UM = 34;

/** Whether this position happens to have a speck in the field, and what it is. */
export function debrisAt(index) {
  const r = makeRng(770 + index * 613);
  if (r() > 0.45) return null;
  return {
    offset: (r() < 0.5 ? -1 : 1) * (9 + 13 * r()),
    amp: 1.12 + 0.34 * r(),
    width: 0.55 + 0.45 * r(),
  };
}

/**
 * The sharpness curve at one position.
 *
 * @param focusZ  where the tissue is actually in focus, µm
 * @param index   which point this is — fixes the noise and the debris
 * @param metric  a key of METRICS
 * @param startZ  where the search begins, µm: the objective is driven there and
 *                swept about it. Left out, it arrives somewhere near the tissue
 *                already, which is the best a first run can be said to do.
 */
export function sweep({ focusZ, index, metric, startZ }) {
  const m = METRICS[metric];
  const centre = focusZ + m.bias;
  /* A sweep is taken about where the objective started, not about where the
     answer turns out to be. That is what makes the starting height worth
     choosing: a search begun far from the tissue comes back without having
     seen it, which is the difference between running the map again from
     wherever the stage is standing and refining it from what the map says. */
  const guess = startZ ?? focusZ - 6 + 12 * (((index * 37) % 11) / 10);
  const r = makeRng(1000 + index * 91 + metric.length * 17);
  const speck = debrisAt(index);

  const samples = [];
  for (let i = 0; i < SWEEP_N; i++) {
    const z = guess - SWEEP_HALF_UM + (2 * SWEEP_HALF_UM * i) / (SWEEP_N - 1);
    const d = z - centre;
    const core = Math.exp(-(d * d) / (2 * m.width * m.width));
    const tail = m.skew
      * Math.exp(-(d * d) / (2 * (m.width * 3) * (m.width * 3)))
      * (d > 0 ? 1 : 0.35);
    let s = core + tail;
    if (speck) {
      const ds = z - (centre + speck.offset);
      const sw = speck.width + m.width * 0.05;   // a coarse metric smears it out
      s += speck.amp * m.speckGain * Math.exp(-(ds * ds) / (2 * sw * sw));
    }
    samples.push({ z, s: Math.max(0.02, s + m.noise * (r() - 0.5)) });
  }
  return { samples, hasDebris: !!speck };
}


/** Read the curve between its samples — used by the draggable height marker. */
export function scoreAt(samples, z) {
  if (z <= samples[0].z) return samples[0].s;
  const last = samples[samples.length - 1];
  if (z >= last.z) return last.s;
  for (let i = 1; i < samples.length; i++) {
    if (z <= samples[i].z) {
      const a = samples[i - 1], b = samples[i];
      return a.s + ((b.s - a.s) * (z - a.z)) / (b.z - a.z);
    }
  }
  return last.s;
}
