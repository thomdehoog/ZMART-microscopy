/**
 * A seeded generator, because a mock that looks different on every load is
 * impossible to test and impossible to talk about. Every synthetic value in
 * this app traces back to one of these.
 */
export function makeRng(seed) {
  let s = seed >>> 0;
  return () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296);
}
