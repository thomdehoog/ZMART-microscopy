/**
 * The window Auto asks for, read off a histogram at a chosen saturation.
 *
 * The viewer measures the region on screen and answers with a histogram and
 * a window at one percent set aside at each end. That one percent is often
 * too little: a few bright objects holding a real percent of the pixels
 * put the top of the window inside them, and everything dim is crushed
 * into the bottom. So the operator says how much to saturate, and the
 * window is read off the same histogram at that share -- ImageJ's
 * "saturated pixels", which microscopists know.
 *
 * `saturate` is the percent set aside at each end. Null when the histogram
 * cannot say: no counts, or a single value.
 */
export function windowFromHistogram(histogram, saturate) {
  const counts = histogram?.counts ?? [];
  const total = counts.reduce((sum, count) => sum + count, 0);
  if (!counts.length || !total || !(histogram.high > histogram.low)) return null;
  const share = Math.max(0, Math.min(49, Number(saturate) || 0)) / 100;
  const width = (histogram.high - histogram.low) / counts.length;
  const at = (target) => {
    let seen = 0;
    for (let i = 0; i < counts.length; i += 1) {
      seen += counts[i];
      if (seen >= target) return histogram.low + (i + 0.5) * width;
    }
    return histogram.high;
  };
  const low = at(share * total);
  const high = at((1 - share) * total);
  return high > low ? { low, high } : null;
}
