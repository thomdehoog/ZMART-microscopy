/**
 * Scan fields: the shapes a run is told to image, and the tiles that cover them.
 *
 * Pure. No DOM, no app state, micrometres from the carrier's own zero
 * throughout — the same frame the carrier's areas are in, so a field and the
 * well it was drawn inside cannot disagree about where either of them is.
 *
 * A field is one of five geometries. A point is a single position; a rectangle,
 * triangle, ellipse or polygon is a region, and what the run actually visits is
 * the tiles covering it. Tiling is the only interesting part: a region is
 * covered by whatever the chosen preset's frame is, stepped by that frame less
 * its overlap, and a tile is kept when the region touches it at all rather than
 * only when its centre lands inside — a thin sliver or a sharp vertex is still
 * sample, and a grid that samples only centres drops both.
 */

/** Rotate (px, py) about (cx, cy). Fields carry an angle; the maths does not. */
export function rotatePoint(px, py, cx, cy, angle) {
  const cos = Math.cos(angle), sin = Math.sin(angle);
  return {
    x: cx + (px - cx) * cos - (py - cy) * sin,
    y: cy + (px - cx) * sin + (py - cy) * cos,
  };
}

const POINT_LIKE = new Set(["point"]);
export const isPointLike = (type) => POINT_LIKE.has(type);

/**
 * A circle is an ellipse with equal radii, so it becomes one on the way in.
 * One rounded geometry rather than two means no handle, editor or rotation
 * needs a circle-shaped special case — and a template that names a circle
 * still loads.
 */
export function normalise(field) {
  if (field.type !== "circle") return field;
  const { r, ...rest } = field;
  return { ...rest, type: "ellipse", rx: r, ry: r, rotation: field.rotation || 0 };
}

export function centroid(f) {
  if (f.type === "rectangle") return { x: f.x + f.w / 2, y: f.y + f.h / 2 };
  if (f.type === "ellipse") return { x: f.cx, y: f.cy };
  if (f.points?.length) {
    return {
      x: f.points.reduce((s, p) => s + p.x, 0) / f.points.length,
      y: f.points.reduce((s, p) => s + p.y, 0) / f.points.length,
    };
  }
  return { x: f.x ?? 0, y: f.y ?? 0 };
}

/** Where the rotation grip hangs from: the topmost point of the shape. */
export function topCentre(f) {
  if (f.type === "rectangle") return { x: f.x + f.w / 2, y: f.y };
  if (f.type === "ellipse") return { x: f.cx, y: f.cy - f.ry };
  if (f.points?.length) {
    // the actual highest vertex, not a phantom point above the centroid
    return f.points.reduce((top, p) => (p.y < top.y ? p : top), f.points[0]);
  }
  return { x: 0, y: 0 };
}

export function contains(x, y, f) {
  if (f.type === "rectangle") {
    const c = centroid(f), p = rotatePoint(x, y, c.x, c.y, -(f.rotation || 0));
    return p.x >= f.x && p.x <= f.x + f.w && p.y >= f.y && p.y <= f.y + f.h;
  }
  if (f.type === "ellipse") {
    const p = rotatePoint(x, y, f.cx, f.cy, -(f.rotation || 0));
    const a = (p.x - f.cx) / f.rx, b = (p.y - f.cy) / f.ry;
    return a * a + b * b <= 1;
  }
  if (f.points?.length >= 3) {
    const c = centroid(f), p = rotatePoint(x, y, c.x, c.y, -(f.rotation || 0));
    let inside = false;
    const pts = f.points, n = pts.length;
    for (let i = 0, j = n - 1; i < n; j = i++) {
      if ((pts[i].y > p.y) !== (pts[j].y > p.y)
        && p.x < ((pts[j].x - pts[i].x) * (p.y - pts[i].y)) / (pts[j].y - pts[i].y) + pts[i].x) {
        inside = !inside;
      }
    }
    return inside;
  }
  return false;
}

/** Slab clip: does the segment cross the axis-aligned box at all? */
export function segmentHitsBox(x1, y1, x2, y2, bx, by, bw, bh) {
  let tMin = 0, tMax = 1;
  const d = [x2 - x1, y2 - y1];
  const lo = [bx, by], hi = [bx + bw, by + bh], from = [x1, y1];
  for (let k = 0; k < 2; k++) {
    if (Math.abs(d[k]) < 1e-10) {
      if (from[k] < lo[k] || from[k] > hi[k]) return false;
      continue;
    }
    let t1 = (lo[k] - from[k]) / d[k], t2 = (hi[k] - from[k]) / d[k];
    if (t1 > t2) [t1, t2] = [t2, t1];
    tMin = Math.max(tMin, t1);
    tMax = Math.min(tMax, t2);
    if (tMin > tMax) return false;
  }
  return true;
}

const ELLIPSE_SEGMENTS = 24;

/** The field's outline in world space, as segments. Rotation is baked in. */
export function edges(f) {
  const rot = f.rotation || 0;
  const ring = (pts) => pts.map((p, i) => {
    const q = pts[(i + 1) % pts.length];
    return [p.x, p.y, q.x, q.y];
  });

  if (f.points?.length >= 3) {
    const c = centroid(f);
    return ring(rot ? f.points.map((p) => rotatePoint(p.x, p.y, c.x, c.y, rot)) : f.points);
  }
  if (f.type === "rectangle") {
    const { x, y, w, h } = f;
    const corners = [{ x, y }, { x: x + w, y }, { x: x + w, y: y + h }, { x, y: y + h }];
    const c = centroid(f);
    return ring(rot ? corners.map((p) => rotatePoint(p.x, p.y, c.x, c.y, rot)) : corners);
  }
  if (f.type === "ellipse") {
    const pts = Array.from({ length: ELLIPSE_SEGMENTS }, (_, i) => {
      const a = (i / ELLIPSE_SEGMENTS) * Math.PI * 2;
      const p = { x: f.cx + f.rx * Math.cos(a), y: f.cy + f.ry * Math.sin(a) };
      return rot ? rotatePoint(p.x, p.y, f.cx, f.cy, rot) : p;
    });
    return ring(pts);
  }
  return [];
}

/** The axis-aligned box a field occupies, rotation included. */
export function bounds(f) {
  const box = (pts) => ({
    xMin: Math.min(...pts.map((p) => p.x)), yMin: Math.min(...pts.map((p) => p.y)),
    xMax: Math.max(...pts.map((p) => p.x)), yMax: Math.max(...pts.map((p) => p.y)),
  });
  const rot = f.rotation || 0;

  if (f.type === "rectangle") {
    const { x, y, w, h } = f;
    const corners = [{ x, y }, { x: x + w, y }, { x: x + w, y: y + h }, { x, y: y + h }];
    if (!rot) return { xMin: x, yMin: y, xMax: x + w, yMax: y + h };
    const c = centroid(f);
    return box(corners.map((p) => rotatePoint(p.x, p.y, c.x, c.y, rot)));
  }
  if (f.type === "ellipse") {
    if (!rot) {
      return { xMin: f.cx - f.rx, yMin: f.cy - f.ry, xMax: f.cx + f.rx, yMax: f.cy + f.ry };
    }
    /* A rotated ellipse's extent is not its rotated corners: the box touches
       where the tangent turns level, which these half-widths give exactly. */
    const cos = Math.cos(rot), sin = Math.sin(rot);
    const hw = Math.sqrt(f.rx * f.rx * cos * cos + f.ry * f.ry * sin * sin);
    const hh = Math.sqrt(f.rx * f.rx * sin * sin + f.ry * f.ry * cos * cos);
    return { xMin: f.cx - hw, yMin: f.cy - hh, xMax: f.cx + hw, yMax: f.cy + hh };
  }
  if (f.points?.length) {
    const c = centroid(f);
    return box(rot ? f.points.map((p) => rotatePoint(p.x, p.y, c.x, c.y, rot)) : f.points);
  }
  if (isPointLike(f.type)) return { xMin: f.x, yMin: f.y, xMax: f.x, yMax: f.y };
  return { xMin: 0, yMin: 0, xMax: 0, yMax: 0 };
}

export const boxesOverlap = (a, b) =>
  a.xMin <= b.xMax && a.xMax >= b.xMin && a.yMin <= b.yMax && a.yMax >= b.yMin;

/**
 * The tile centres covering a field.
 *
 * A point is one position and needs no covering. A region is stepped by the
 * frame less its overlap, centred on the field's own box so the cover is
 * symmetric rather than growing off one corner, and a tile is kept when the
 * field touches it at all: centre inside, or a corner inside, or an edge
 * crossing it. The last test is what keeps a sliver or a sharp vertex, which
 * sampling centres alone silently drops.
 */
export function tiles(field, frameUm, overlapPct = 0, limit = null) {
  if (isPointLike(field.type)) return [{ x: field.x, y: field.y }];
  if (!frameUm || frameUm <= 0) return [];
  const step = frameUm * (1 - overlapPct / 100);
  if (step <= 0) return [];

  const bb = bounds(field);
  if (!Number.isFinite(bb.xMin)) return [];

  const run = (min, max, lo, hi) => raster(min, max, frameUm, step, lo, hi);
  const xs = run(bb.xMin, bb.xMax, limit?.xMin ?? null, limit?.xMax ?? null);
  const ys = run(bb.yMin, bb.yMax, limit?.yMin ?? null, limit?.yMax ?? null);
  const outline = edges(field);

  const out = [];
  for (const ty of ys) {
    for (const tx of xs) if (covers(field, tx, ty, frameUm, outline)) out.push({ x: tx, y: ty });
  }
  return out;
}

/**
 * Where the frames go along one axis: their centres, evenly stepped.
 *
 * `lo` and `hi` are the edges a frame may not cross — the imageable square of
 * the area the field is in — and null when nothing is in the way. What is
 * covered is the field's own span narrowed to that, and the run is laid over
 * exactly that much:
 *
 * * The step never changes. It is the overlap the operator asked for, and a
 *   run that spent it to make the ends come out even would be answering a
 *   question nobody asked.
 * * Clipped at one end, the run starts flush against that edge, so the plan
 *   fills right into the corner instead of leaving a bare margin.
 * * Clipped at neither, the run sits centred on the field, which is where a
 *   plan with nothing in its way has always been laid.
 * * A run that will not fit between the edges is cut to what does fit, from
 *   the near edge out.
 */
function raster(min, max, frameUm, step, lo, hi) {
  const half = frameUm / 2;
  const from = lo === null ? min : Math.max(min, lo);
  const to = hi === null ? max : Math.min(max, hi);
  if (to - from < 0) return [];

  /* One tile already covers its own frame, so only what is left over needs
     stepping: n − 1 steps plus one frame reaches the far edge exactly. Counting
     the whole span in steps and adding one buys a row and a column nothing is
     in — invisible on a big region, and a 2 × 2 cover of a field smaller than
     a single frame. */
  let n = Math.max(1, Math.ceil((to - from - frameUm) / step) + 1);
  const cLo = lo === null ? -Infinity : lo + half;
  const cHi = hi === null ? Infinity : hi - half;
  if (cHi < cLo) return [];
  // as many as the edges leave room for, when they leave room for fewer
  n = Math.min(n, Math.floor((cHi - cLo) / step) + 1);

  /* Flush against whichever edge did the clipping, so the plan fills right up
     to the border rather than sitting a fraction of a frame short of it. Only
     a run with nothing in its way is centred on the field, which is where a
     plan has always been laid when the area is not the limit. */
  const clippedLow = lo !== null && min < lo;
  const clippedHigh = hi !== null && max > hi;
  const centred = (from + to) / 2 - ((n - 1) / 2) * step;
  const start = clippedLow || !clippedHigh
    ? Math.min(Math.max(centred, cLo), cHi - (n - 1) * step)
    : cHi - (n - 1) * step;
  return Array.from({ length: n }, (_, i) => start + i * step);
}

/**
 * The span a whole number of frames covers, without reaching past `size`.
 *
 * A region is drawn in frames, so that its edge and the tiles inside it land
 * on the same line: no strip of it left unimaged, and nothing imaged outside
 * it. Rounded down rather than up — the shape shrinks to what fits inside what
 * was drawn — except that one frame is the floor, since there is no such thing
 * as imaging less than the objective sees at once.
 */
export function snapSpan(size, frameUm, overlapPct = 0) {
  const step = frameUm * (1 - overlapPct / 100);
  if (!(frameUm > 0) || step <= 0) return size;
  // a hair of tolerance, or a size that is exactly n frames comes back n − 1
  const n = Math.max(1, Math.floor((size - frameUm) / step + 1e-9) + 1);
  return (n - 1) * step + frameUm;
}

/**
 * Whether a frame centred there takes in any part of the field.
 *
 * Asked once per tile while a plan is laid, and again by anything that moves a
 * lattice afterwards: a tile that has been slid off the shape it was laid for
 * is imaging something nobody drew, and it is this question that says so.
 *
 * `outline` is the field's edges, which the caller may already have; the
 * corners of the frame catch a field bigger than the frame, and the edge test
 * catches one smaller that passes between them.
 */
export function covers(field, x, y, frameUm, outline = edges(field)) {
  const half = frameUm / 2;
  return contains(x, y, field)
    || contains(x - half, y - half, field) || contains(x + half, y - half, field)
    || contains(x - half, y + half, field) || contains(x + half, y + half, field)
    || outline.some((e) => segmentHitsBox(e[0], e[1], e[2], e[3], x - half, y - half, frameUm, frameUm));
}

/**
 * The grips a selected field offers, in its own unrotated space. The caller
 * rotates them about the centroid, so this stays a statement about the shape
 * rather than about how it is being displayed.
 */
export function handles(f) {
  if (f.type === "rectangle") {
    const { x, y, w, h } = f;
    return [
      { id: "tl", x, y }, { id: "tr", x: x + w, y },
      { id: "bl", x, y: y + h }, { id: "br", x: x + w, y: y + h },
      { id: "t", x: x + w / 2, y }, { id: "b", x: x + w / 2, y: y + h },
      { id: "l", x, y: y + h / 2 }, { id: "r", x: x + w, y: y + h / 2 },
    ];
  }
  if (f.type === "ellipse") {
    return [
      { id: "t", x: f.cx, y: f.cy - f.ry }, { id: "b", x: f.cx, y: f.cy + f.ry },
      { id: "l", x: f.cx - f.rx, y: f.cy }, { id: "r", x: f.cx + f.rx, y: f.cy },
    ];
  }
  if (f.points?.length) return f.points.map((p, i) => ({ id: `pt${i}`, x: p.x, y: p.y, index: i }));
  return [];
}

/**
 * A vertex list with its last point removed when it repeats the one before it.
 *
 * What a double-click leaves behind: the press that finishes an outline is the
 * same press that placed its last vertex, so the second half of the gesture
 * lands a second vertex within a pixel or two of the first. Carried into the
 * region that is a zero-length edge — an invisible grip sitting on top of
 * another, found later by whoever tries to drag one of them.
 *
 * `nearer` is in the same units as the points, so the caller decides what
 * counts as the same place: a few screen pixels converted at the current zoom,
 * rather than a distance in micrometres that means different things at
 * different scales.
 */
export function withoutTrailingDuplicate(points, nearer) {
  if (points.length < 2) return points;
  const [a, b] = [points[points.length - 1], points[points.length - 2]];
  return Math.hypot(a.x - b.x, a.y - b.y) < nearer ? points.slice(0, -1) : points;
}

/**
 * A block of positions centred on a point.
 *
 * What the grid mode places in every area the carrier declares: the span is
 * (n − 1) pitches across, so an odd count sits one position exactly on the
 * area's centre and an even one straddles it. Pitch is floored at the frame by
 * the caller — positions may be spread apart, never made to overlap.
 */
export function block(centre, rows, cols, pitchX, pitchY) {
  const x0 = centre.x - ((cols - 1) * pitchX) / 2;
  const y0 = centre.y - ((rows - 1) * pitchY) / 2;
  const out = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) out.push({ x: x0 + c * pitchX, y: y0 + r * pitchY });
  }
  return out;
}
