/**
 * Reading a focus curve: which heights are peaks, and which one to take.
 *
 * A backend measures sharpness and hands back a curve. What counts as a peak
 * in it, and which peak is the tissue rather than a speck of dust, is one
 * rule and it is the same rule whoever measured — so it lives here, beside
 * the seam, rather than in either backend or in the step that draws it.
 */

/** Tissue stays sharp over microns. Anything narrower than this is not tissue. */
export const MIN_TISSUE_WIDTH_UM = 4.5;

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
