/**
 * The physical colour domain for a fitted focus surface.
 *
 * A narrow plate must not consume the whole palette: below 100 µm the slope
 * is fixed at one palette per 100 µm and the unused range is shared equally
 * around the measured values. Wider plates keep their full measured range.
 */
export function zColourDomain(low, high, minimumSpanUm = 100) {
  const lo = Number(low);
  const hi = Number(high);
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, minimumSpanUm];
  const measuredLo = Math.min(lo, hi);
  const measuredHi = Math.max(lo, hi);
  const measuredSpan = measuredHi - measuredLo;
  if (measuredSpan >= minimumSpanUm) return [measuredLo, measuredHi];
  const middle = (measuredLo + measuredHi) / 2;
  return [middle - minimumSpanUm / 2, middle + minimumSpanUm / 2];
}
