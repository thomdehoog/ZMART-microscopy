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
 * `n` of these positions, one from each equal share of the ground they cover.
 *
 * A focus map wants its points spread over the field and away from its edges:
 * the surface is fitted through them, so three heights measured along one edge
 * describe that edge and guess at the rest, and a height read at the very rim
 * is the one most likely to be off the sample. So the field is divided into
 * `n` shares of equal area and the position nearest the middle of each share
 * is taken. The middle of a share is inset from the field's edge by half a
 * share, which is as far apart as `n` points can be while every part of the
 * field still has one speaking for it.
 *
 * Shares are dealt as rows of cells, the way a treemap is laid out rather than
 * as a rigid grid: the number of rows is chosen so the cells come out as square
 * as the field allows, and a row that gets one more cell than another is that
 * much taller, so every cell is the same area whatever number was asked for.
 * Five shares of a wide field are three over two, not five thin strips.
 *
 * Equal shares of the extent are the right answer for a tileset shaped like
 * its own bounding box, and a rough one for a triangle, an ellipse or anything
 * hand-drawn, where a share can be half empty and its middle lands off to one
 * side of what the share actually holds. So the split is only the seed: the
 * points are then settled by relaxing them into the positions themselves —
 * every position goes to the point nearest it, each point moves to the
 * position nearest the middle of what it took, and this repeats until nothing
 * moves. That is Lloyd's algorithm, and the outcome is what is wanted: each
 * point standing in the middle of its own share of the sample.
 *
 * Seeded rather than scattered, and a fixed number of passes, so the same
 * tileset always gives the same map — a map that shuffled itself on a rerun
 * would move points a surface had already been measured through.
 *
 * What comes back are places, not positions. A focus point is somewhere the
 * stage is driven to and a height is read, and nothing says that has to be the
 * middle of a frame the run will image — tying them to frame centres was the
 * grid speaking through a question that is not about the grid, and it showed:
 * three points on a triangle came out in a row, because that was where the
 * frames were rather than where the sample is.
 *
 * And what is shared out is the ground, not the frames' middles. A frame covers
 * a square of sample; standing for it by the dot at its centre made the sample
 * nine dots instead of a filled block, and Lloyd's settles a set of dots
 * faithfully: six points over three by three frames came to rest as three
 * points owning two frames apiece — sitting on the seam between them — and
 * three owning one, leaving the top row of the block with nothing. A true fixed
 * point for nine dots, and the wrong answer for the sample they cover.
 */
export function sharePoints(tiles, n) {
  const want = Math.max(1, Math.round(n));
  if (!tiles.length) return [];
  // as many asked for as there are positions, or more: one on each, nothing
  // left to settle
  if (tiles.length <= want) return tiles.map((t) => ({ x: t.x, y: t.y }));

  /* How many rows to deal the shares in is the one thing a formula cannot be
     trusted with. Five shares of a square block are two, one and two — the four
     corners with one in the middle — where a row count taken from the square
     root gives three and two, which covers the same ground less evenly. So the
     likely counts are laid, settled and measured, and the tightest is kept.
     Three of them, either side of the square root, because the answer is never
     far from it and each one costs a settling. */
  const ground = groundOf(tiles);
  const likely = Math.max(1, Math.round(Math.sqrt(want * heightOf(ground) / widthOf(ground))));
  const tries = [...new Set([likely - 1, likely, likely + 1])]
    .filter((rows) => rows >= 1 && rows <= want)
    .map((rows) => settle(ground, seedCells(ground, want, rows)));
  const best = tries.reduce((a, b) => (spreadCost(ground, b) < spreadCost(ground, a) ? b : a));
  return looseInTheirShares(ground, tiles, best);
}


/**
 * Where in its share each point actually stands.
 *
 * The middle of a share is the best single place to stand for the ground around
 * it — and it is the same place in every share. On a plate of identical wells
 * that means every point comes out at the same spot in its own well: the same
 * tile, the same corner of it, six times over. A map made of one place measured
 * six times is not a map of the plate, and a sample has no reason to be flat in
 * exactly the spot the arithmetic picked.
 *
 * So each point is let off the middle by a step of its own. The step is taken
 * from where the point stands, so a tileset still gives the same map every time
 * it is laid — a map that shuffled itself on a rerun would be a map of nothing —
 * and it is scaled to the share, so a point with a well to itself moves further
 * than one packed in beside others. Then it is put back on the nearest ground
 * it can actually be imaged at, because a focus point off the covered ground is
 * not a measurement.
 */
function looseInTheirShares(ground, tiles, points) {
  const mine = points.map(() => []);
  for (const g of ground) mine[nearestOf(points, g.x, g.y)].push(g);

  return points.map((p, i) => {
    const share = mine[i].length ? mine[i] : ground;
    /* Where the arithmetic seated it, on ground the run images. */
    const seat = imagedAt(tiles, p) ? p : nearestPlace(share, p);

    /* And how far it may wander from there: to the edge of the ground lying
       within one frame of the seat, and no further.

       Not to the edge of its share, which was the first answer and the wrong
       one. A share is as big as the ground it owns, and on a plate that ground
       is a scatter of wells with a great deal of glass between them — a share
       reaching across three wells let a point step into the next one, which
       undid the very spread it had just been placed for. Measured on a
       ninety-six-well plate, twelve points that had settled into a tidy four by
       three came back scattered over six columns with two of them side by side.
       Within a frame of the seat there is only the tileset the seat stands in,
       so the wandering happens where it costs nothing. */
    const reach = frameAt(tiles, seat);
    const around = share.filter((g) =>
      Math.abs(g.x - seat.x) <= reach && Math.abs(g.y - seat.y) <= reach);
    if (around.length < 2) return seat;

    const [ax, ay] = stepFrom(seat.x, seat.y);
    const want = {
      x: seat.x + (ax * 2 - 1) * (widthOf(around) / 2),
      y: seat.y + (ay * 2 - 1) * (heightOf(around) / 2),
    };
    return imagedAt(tiles, want) ? want : nearestPlace(around, want);
  });
}

/** How wide the frame is that covers this spot — the nearest one, if none does. */
function frameAt(tiles, p) {
  let best = tiles[0], bestD = Infinity;
  for (const t of tiles) {
    const half = (t.frameUm ?? 0) / 2;
    if (half > 0 && Math.abs(t.x - p.x) <= half && Math.abs(t.y - p.y) <= half) return t.frameUm;
    const d = (t.x - p.x) ** 2 + (t.y - p.y) ** 2;
    if (d < bestD) { bestD = d; best = t; }
  }
  return best?.frameUm ?? 0;
}

/**
 * Two numbers between 0 and 1, from a place.
 *
 * A point's step has to be its own — two points a well apart must not be nudged
 * the same way, or the plate is back to being measured at one spot — and it has
 * to be the same every time the same map is laid. Both come out of the place
 * itself rather than a counter or a clock.
 */
function stepFrom(x, y) {
  let h = Math.imul(Math.round(x) ^ 0x9e3779b9, 0x85ebca6b);
  h = Math.imul((h ^ (h >>> 13)) + Math.round(y), 0xc2b2ae35);
  h ^= h >>> 16;
  let k = Math.imul(h ^ 0x27d4eb2f, 0x165667b1);
  k ^= k >>> 15;
  return [(h >>> 0) / 4294967296, (k >>> 0) / 4294967296];
}

/**
 * Is this spot inside a frame the run will image?
 *
 * A point that shares out ground it does not stand on is not a measurement: the
 * stage is driven there and a height is read off whatever is under the
 * objective, so it has to be somewhere the run actually looks.
 */
function imagedAt(tiles, p) {
  return tiles.some((t) => {
    const half = (t.frameUm ?? 0) / 2;
    return half > 0 && Math.abs(t.x - p.x) <= half && Math.abs(t.y - p.y) <= half;
  });
}

/**
 * The nearest place on the ground, for a point that came to rest off it.
 *
 * Settling shares out the ground the frames cover, and the middle of a share is
 * not always on it: a share straddling two tilesets in one well has its centroid
 * in the gap between them, where there is no frame and nothing to focus on. The
 * ground is made of points inside frames, so the nearest of them is both the
 * closest the settled answer can be honoured and somewhere the run will image.
 */
function nearestPlace(ground, p) {
  let best = ground[0], bestD = Infinity;
  for (const g of ground) {
    const d = (g.x - p.x) ** 2 + (g.y - p.y) ** 2;
    if (d < bestD) { bestD = d; best = g; }
  }
  return { x: best.x, y: best.y };
}

/** How far a set of places reaches, across and down. */
const widthOf = (places) =>
  (Math.max(...places.map((p) => p.x)) - Math.min(...places.map((p) => p.x))) || 1;
const heightOf = (places) =>
  (Math.max(...places.map((p) => p.y)) - Math.min(...places.map((p) => p.y))) || 1;

/**
 * How well a set of points stands for the ground: every place goes to the point
 * nearest it, and this is the sum of those distances squared. Lower is a tighter
 * arrangement — every part of the sample nearer to something measured.
 */
function spreadCost(ground, points) {
  return ground.reduce((sum, g) => {
    const p = points[nearestOf(points, g.x, g.y)];
    return sum + (g.x - p.x) ** 2 + (g.y - p.y) ** 2;
  }, 0);
}

/* How finely a frame is sampled across, at most: four to a side, which is
   enough for the middle of a share to land where the eye says it should and
   cheap enough to settle three seedings of. */
const ACROSS_A_FRAME = 4;

/**
 * The sample a tileset covers, as places to share out: every frame spread into
 * a small lattice of points across the ground it images.
 *
 * Coarsened for a big tileset, where the frames are already a fine enough
 * description of the ground on their own and the count is what costs — the
 * lumpiness this cures only shows when there are few frames to a point.
 */
function groundOf(tiles) {
  const across = Math.max(1, Math.min(ACROSS_A_FRAME,
    Math.floor(Math.sqrt(4096 / tiles.length))));
  if (across === 1) return tiles.map((t) => ({ x: t.x, y: t.y }));

  const out = [];
  for (const t of tiles) {
    const frame = t.frameUm ?? 0;
    if (!frame) { out.push({ x: t.x, y: t.y }); continue; }
    const step = frame / across;
    const first = -frame / 2 + step / 2;
    for (let row = 0; row < across; row++) {
      for (let col = 0; col < across; col++) {
        out.push({ x: t.x + first + col * step, y: t.y + first + row * step });
      }
    }
  }
  return out;
}

/**
 * Seeds at the middles of `n` equal shares of the ground the positions cover.
 *
 * Rows of cells rather than a rigid grid: a row holding one more cell than
 * another is that much taller, so every cell is the same area whatever number
 * was asked for. How many rows to deal them in is the caller's to say, since
 * which count covers the ground best is something only the settling shows.
 *
 * A number that does not divide evenly leaves shares over, and they are dealt
 * outwards from the middle in pairs — the middle row first when one is left
 * over, then the pair either side of it, and so on. Dealt from the top instead,
 * seven over a square block came out three, two, two, with a hole through the
 * middle of the block that nothing stood for, and eight came out three, three,
 * two, which is lopsided for no reason. Dealt this way the rows read the same
 * from either end, whatever the number.
 */
function seedCells(tiles, n, howMany) {
  const xs = tiles.map((t) => t.x), ys = tiles.map((t) => t.y);
  const xMin = Math.min(...xs), yMin = Math.min(...ys);
  const width = widthOf(tiles), height = heightOf(tiles);
  const rows = Math.min(n, Math.max(1, howMany));
  const base = Math.floor(n / rows), extra = n % rows;
  const takesOneMore = dealtFromTheMiddle(rows, extra);

  const seeds = [];
  let top = yMin;
  for (let r = 0; r < rows; r++) {
    const cells = base + (takesOneMore.has(r) ? 1 : 0);
    const tall = (height * cells) / n, wide = width / cells;
    for (let i = 0; i < cells; i++) {
      seeds.push({ x: xMin + (i + 0.5) * wide, y: top + tall / 2 });
    }
    top += tall;
  }
  return seeds;
}

/**
 * Which rows take one of the shares left over, dealt outwards from the middle:
 * the middle row first when the number left over is odd, then the pair either
 * side of it, and so on. What comes back reads the same from either end.
 */
function dealtFromTheMiddle(rows, extra) {
  const middle = (rows - 1) / 2;
  const order = [...Array(rows).keys()]
    .sort((a, b) => Math.abs(a - middle) - Math.abs(b - middle) || a - b);

  const taken = new Set();
  for (const row of order) {
    const left = extra - taken.size;
    if (left <= 0) break;
    if (taken.has(row)) continue;
    const mirror = rows - 1 - row;

    /* The middle row of an odd number of rows is its own mirror, so it can only
       take the odd one out: while an even number is left to give, pairs come
       first and it is passed over. Seven shares of a square block are two,
       three, two that way, and eight are three, two, three. */
    if (row === mirror) {
      if (left % 2 === 1) taken.add(row);
      continue;
    }
    taken.add(row);
    // and its mirror, unless this was the last share to give, where an even
    // number of rows leaves nothing symmetrical to do
    if (left >= 2) taken.add(mirror);
  }
  return taken;
}

/**
 * Lloyd's algorithm over the positions: each position belongs to the point
 * nearest it, and each point moves to the middle of what belongs to it.
 * Repeated until nothing moves — which on a tileset shaped like its bounding
 * box happens at once, and on a triangle takes a pass or two.
 *
 * A point left standing for nothing is moved to the position furthest from
 * every other point, where it will earn a share on the next pass: a point
 * measuring nowhere is a measurement thrown away.
 *
 * Capped at a dozen passes, and stopped once the step is smaller than half a
 * micrometre — below that it is moving the point by less than the stage can be
 * told to go, and a map that never settles is worse than one that stopped
 * short.
 */
function settle(tiles, seeds, passes = 12) {
  let points = seeds;
  for (let pass = 0; pass < passes; pass++) {
    const mine = points.map(() => []);
    for (const t of tiles) mine[nearestOf(points, t.x, t.y)].push(t);

    const moved = points.map((p, i) => {
      const held = mine[i];
      if (!held.length) return farthestFrom(tiles, points);
      return {
        x: held.reduce((a, t) => a + t.x, 0) / held.length,
        y: held.reduce((a, t) => a + t.y, 0) / held.length,
      };
    });

    if (moved.every((p, i) => Math.hypot(p.x - points[i].x, p.y - points[i].y) < 0.5)) {
      return moved;
    }
    points = moved;
  }
  return points;
}

/** Which of these points is nearest that spot. */
function nearestOf(points, x, y) {
  let best = 0, bestD = Infinity;
  points.forEach((p, i) => {
    const d = Math.hypot(p.x - x, p.y - y);
    if (d < bestD) { best = i; bestD = d; }
  });
  return best;
}

/**
 * Somewhere for a point that ended up standing for nothing: the position in
 * the crowd that is furthest from the point speaking for it. That splits the
 * busiest share rather than sending the spare point to an outer corner, which
 * is where "furthest from everything" always lands.
 */
function farthestFrom(tiles, points) {
  let best = tiles[0], bestD = -1;
  for (const t of tiles) {
    const near = points[nearestOf(points, t.x, t.y)];
    const d = Math.hypot(t.x - near.x, t.y - near.y);
    if (d > bestD) { best = t; bestD = d; }
  }
  return { x: best.x, y: best.y };
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
