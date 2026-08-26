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
    label: "Brenner gradient", short: "Brenner", token: "--m-brenner",
    width: 9.0, bias: 0.0, skew: 0.16, noise: 0.045, speckGain: 1.0,
  },
  dct: {
    label: "DCT energy", short: "DCT", token: "--m-dct",
    width: 6.2, bias: -0.7, skew: 0.03, noise: 0.028, speckGain: 0.72,
  },
};

export const METRIC_KEYS = Object.keys(METRICS);

export const SWEEP_N = 61;
export const SWEEP_HALF_UM = 34;

/** Tissue stays sharp over microns. Anything narrower than this is not tissue. */
export const MIN_TISSUE_WIDTH_UM = 4.5;

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
  return { samples, candidates: findCandidates(samples), hasDebris: !!speck };
}

/**
 * Every local maximum, refined by a parabola through its three samples, with
 * the half-height width that tells tissue from a speck.
 */
export function findCandidates(samples) {
  const stepUm = samples[1].z - samples[0].z;
  const floor = Math.min(...samples.map((q) => q.s));
  const out = [];

  for (let i = 1; i < samples.length - 1; i++) {
    if (!(samples[i].s >= samples[i - 1].s && samples[i].s > samples[i + 1].s)) continue;
    const [p0, p1, p2] = [samples[i - 1], samples[i], samples[i + 1]];
    const denom = p0.s - 2 * p1.s + p2.s;
    const shift = Math.abs(denom) < 1e-6 ? 0 : (0.5 * (p0.s - p2.s)) / denom;
    const z = p1.z + shift * stepUm;
    const s = p1.s - 0.25 * (p0.s - p2.s) * shift;
    if (s - floor < 0.12) continue;                 // noise, not a peak

    const half = floor + (s - floor) / 2;
    let lo = p1.z, hi = p1.z;
    for (let k = i; k >= 0 && samples[k].s > half; k--) lo = samples[k].z;
    for (let k = i; k < samples.length && samples[k].s > half; k++) hi = samples[k].z;
    const width = Math.max(stepUm, hi - lo);

    out.push({ z, s, width, used: [p0, p1, p2], narrow: width < MIN_TISSUE_WIDTH_UM });
  }

  if (!out.length) {
    let bi = 0;
    samples.forEach((p, i) => { if (p.s > samples[bi].s) bi = i; });
    const p1 = samples[Math.max(1, Math.min(samples.length - 2, bi))];
    out.push({ z: p1.z, s: p1.s, width: stepUm, used: [p1, p1, p1], narrow: false });
  }
  return out;
}

/**
 * One rule, not a menu of them: the tallest peak that is wide enough to be
 * tissue. If nothing qualifies the tallest wins anyway and is flagged
 * `narrow`, because refusing to answer helps nobody — but the caller, and the
 * operator, get to see that it is suspect.
 */
export function pickPeak(candidates) {
  /* Nothing rose anywhere in the sweep, so there is nothing to pick. Reachable
     once a search can be told where to begin: start it far enough from the
     tissue and the objective travels its whole range without ever seeing it. */
  if (!candidates.length) return null;
  const wide = candidates.filter((c) => !c.narrow);
  return (wide.length ? wide : candidates).reduce((a, b) => (b.s > a.s ? b : a));
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
