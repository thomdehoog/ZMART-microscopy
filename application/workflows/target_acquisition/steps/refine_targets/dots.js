/**
 * Dots stamped straight into pixels, for a plot of the whole population.
 *
 * The feature plot once drew an arc per cell on every frame. At half a
 * million cells that took seconds, and a hand dragging a gate redraws
 * every frame. Stamping the population once into a picture, and drawing
 * that picture after, makes a frame cost the same whatever the crowd. The
 * look is the arcs': a translucent disc per cell that builds up where cells
 * overlap, and for the chosen a solid disc ringed in the screen's colour.
 *
 * Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
 * University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
 */

/**
 * Stamp a disc at every `[x, y]` of `points` into `data`, the RGBA bytes
 * of a `width` × `height` picture. `radius` is in pixels; `alpha` is laid
 * over what is there already, so overlapping dots build up. A `ring` of
 * `{width, rgb}` is laid around the disc, opaque, under the disc.
 */
export function stampDots(data, width, height, points, { radius, rgb, alpha, ring = null }) {
  const outer = ring ? radius + ring.width : radius;
  const reach = Math.ceil(outer);
  /* The disc's footprint once, as offsets: which pixels around a centre
     are inside the disc, and which in the ring. */
  const inDisc = [], inRing = [];
  for (let dy = -reach; dy <= reach; dy++) {
    for (let dx = -reach; dx <= reach; dx++) {
      const d = Math.hypot(dx, dy);
      if (d <= radius) inDisc.push([dx, dy]);
      else if (ring && d <= outer) inRing.push([dx, dy]);
    }
  }
  const lay = (x, y, [r, g, b], a) => {
    if (x < 0 || y < 0 || x >= width || y >= height) return;
    const p = (y * width + x) * 4;
    const was = data[p + 3] / 255;
    const now = a + was * (1 - a);
    /* The ink is laid over what is there, the way a translucent arc is. */
    if (now > 0) {
      data[p] = Math.round((r * a + data[p] * was * (1 - a)) / now);
      data[p + 1] = Math.round((g * a + data[p + 1] * was * (1 - a)) / now);
      data[p + 2] = Math.round((b * a + data[p + 2] * was * (1 - a)) / now);
    }
    data[p + 3] = Math.round(now * 255);
  };
  for (const [px, py] of points) {
    const x = Math.round(px), y = Math.round(py);
    if (ring) for (const [dx, dy] of inRing) lay(x + dx, y + dy, ring.rgb, 1);
    for (const [dx, dy] of inDisc) lay(x + dx, y + dy, rgb, alpha);
  }
}

/** A css colour, `#rrggbb` or `rgb(a)(...)`, as its three bytes. */
export function rgbOf(colour) {
  const s = String(colour).trim();
  if (s.startsWith("#")) {
    const hex = s.length === 4 ? s.slice(1).split("").map((c) => c + c).join("") : s.slice(1, 7);
    return [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
  }
  const parts = s.match(/[\d.]+/g) ?? [];
  return parts.slice(0, 3).map((n) => Math.round(Number(n)));
}
