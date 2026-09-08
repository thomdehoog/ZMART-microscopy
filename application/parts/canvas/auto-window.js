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

/**
 * The window the one-press look asks for. The bottom is read off the
 * background: the histogram's first peak from the dark end, since in a
 * fluorescence frame the darkest peak is the background's, and the window
 * opens where that peak has fallen to `tail` of its height. So a frame that
 * is mostly background and a frame that is mostly cells both start just
 * above their own background, which a fixed percentile could not do. The top is set at
 * `brightest` percent of the pixels from the top, so the brightest objects
 * stay inside the window rather than clipping. Null when the histogram
 * cannot say.
 */
export function windowForTheLook(histogram, { tail = 0.05, brightest = 0.3 } = {}) {
  const counts = histogram?.counts ?? [];
  const total = counts.reduce((sum, count) => sum + count, 0);
  if (!counts.length || !total || !(histogram.high > histogram.low)) return null;
  const width = (histogram.high - histogram.low) / counts.length;
  const at = (target) => {
    let seen = 0;
    for (let i = 0; i < counts.length; i += 1) {
      seen += counts[i];
      if (seen >= target) return histogram.low + (i + 0.5) * width;
    }
    return histogram.high;
  };
  const high = at((1 - Math.max(0, Math.min(20, brightest)) / 100) * total);
  /* The background's peak is the first real peak from the dark end, not the
     tallest one: in a frame that is mostly cells the tallest bin is theirs,
     and a window opened above it would crush them. */
  const tallest = Math.max(...counts);
  let peak = 0;
  for (let i = 0; i < counts.length; i += 1) {
    if (counts[i] >= tallest * 0.2 && (i + 1 >= counts.length || counts[i + 1] <= counts[i])) {
      peak = i;
      break;
    }
  }
  let edge = peak;
  while (edge + 1 < counts.length && counts[edge + 1] > counts[peak] * tail) edge += 1;
  const low = histogram.low + (edge + 1) * width;
  if (low < high) return { low, high };
  /* A histogram that is one peak all the way up: fall back to a plain share. */
  const plain = at(0.35 * total);
  return plain < high ? { low: plain, high } : null;
}
