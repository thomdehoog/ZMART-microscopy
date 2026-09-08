/**
 * The colour scale of a fitted focus surface: what height a colour means.
 *
 * Absolute: the same colour difference means the same micrometres on every
 * run. From 15 % to 85 % of the ramp is `spanUm` (70 µm), centred on the
 * median of the measured points; whatever the surface reaches beyond that
 * is not clipped, since the outer 15 % at each end stretches to the
 * surface's own extreme on that side. The median rather than the mean, so
 * one lost or wild point does not shift the colours of all the others.
 *
 * The legend shows only the slice of the ramp the map reaches, between
 * `min` and `max`, so a flat plate shows a narrow slice and says so.
 */
export function zColourScale(sampled, measured, { spanUm = 70, band = [0.15, 0.85] } = {}) {
  const finite = (xs) => xs.map(Number).filter(Number.isFinite);
  const samples = finite(sampled);
  const heights = finite(measured);
  if (!samples.length) return { min: 0, max: 0, spread: 0, t: () => 0 };
  const centre = median(heights.length ? heights : samples);
  const innerLo = centre - spanUm / 2;
  const innerHi = centre + spanUm / 2;
  const min = Math.min(...samples);
  const max = Math.max(...samples);
  const lo = Math.min(innerLo, min);
  const hi = Math.max(innerHi, max);
  const [tLo, tHi] = band;
  const t = (z) => {
    if (!Number.isFinite(z)) return 0;
    if (z <= innerLo) return lo < innerLo ? tLo * (z - lo) / (innerLo - lo) : tLo;
    if (z >= innerHi) return hi > innerHi ? tHi + (1 - tHi) * (z - innerHi) / (hi - innerHi) : tHi;
    return tLo + (tHi - tLo) * (z - innerLo) / spanUm;
  };
  return { min, max, spread: max - min, t };
}

function median(xs) {
  const sorted = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}
