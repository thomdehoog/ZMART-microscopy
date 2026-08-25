/**
 * What a sample can be mounted in, and the geometry that follows from it.
 *
 * Pure: no DOM, no app state, millimetres throughout. A carrier is a grid of
 * imageable areas, and every carrier this lab uses is that same shape — a
 * slide is a one-by-one grid, a 384-well plate is sixteen by twenty-four. So
 * there is one description rather than a type per vessel, and the presets are
 * starting points for it rather than a closed list.
 *
 * The corner is stored as a ratio of the largest radius the area could take,
 * not as millimetres. That is what lets a well stay round while its diameter
 * changes, and a chamber keep its softened corner while it is resized —
 * storing millimetres would turn either into something else the moment a
 * dimension moved.
 */

/* Each type declares three things about itself, and the panel is built from
   them rather than from a list of its own about which type is which:

   `grid`    whether the carrier is more than one area — rows, columns and the
             pitch between them. An area and a dish are one area, and a row of
             controls saying so is a row of ones to read past.
   `round`   whether an area is a circle, which makes it one diameter rather
             than a width and a height, and leaves no corner to choose.
   `deep`    whether the carrier has a depth as well as a width and a height.
             One vessel does, and it is the only one the stage travels through
             rather than across.

   Add a vessel by describing it here and the controls follow. */
export const CARRIER_TYPES = [
  {
    id: "slide",
    label: "Area",
    grid: false,
    round: false,
    deep: false,
    presets: [
      /* Square-cornered: an area is a rectangle of sample, and the soft corner
         a glass slide happens to have is not part of what can be imaged in
         it — carried here it pulled the imageable rectangle in at every edge
         for a shape nobody was working to. */
      { label: "Standard (75 × 25 mm)", rows: 1, cols: 1, shape: "rect", w: 75, h: 25, gap: 0, corner: 0 },
      { label: "Large (76 × 52 mm)", rows: 1, cols: 1, shape: "rect", w: 76, h: 52, gap: 0, corner: 0 },
    ],
  },
  {
    id: "dish",
    label: "Dish",
    grid: false,
    round: true,
    deep: false,
    presets: [
      { label: "35 mm dish", rows: 1, cols: 1, shape: "round", w: 35, h: 35, gap: 0, corner: 0 },
      { label: "60 mm dish", rows: 1, cols: 1, shape: "round", w: 60, h: 60, gap: 0, corner: 0 },
      { label: "100 mm dish", rows: 1, cols: 1, shape: "round", w: 100, h: 100, gap: 0, corner: 0 },
    ],
  },
  {
    id: "chamber",
    label: "Chamber",
    grid: true,
    round: false,
    deep: false,
    presets: [
      { label: "1-chamber (ibidi)", rows: 1, cols: 1, shape: "rect", w: 48, h: 24, gap: 0, corner: 2 },
      { label: "2-chamber (ibidi)", rows: 1, cols: 2, shape: "rect", w: 21.3, h: 17.6, gap: 4.8, corner: 1.5 },
      { label: "4-chamber (Nunc)", rows: 2, cols: 2, shape: "rect", w: 20, h: 10, gap: 3, corner: 1.5 },
      { label: "8-chamber (ibidi)", rows: 2, cols: 4, shape: "rect", w: 9.4, h: 10.7, gap: 1, corner: 1 },
    ],
  },
  {
    id: "wellplate",
    label: "Wellplate",
    grid: true,
    round: false,
    deep: false,
    presets: [
      { label: "6-well", rows: 2, cols: 3, shape: "round", w: 34.8, h: 34.8, gap: 4.4, corner: 0 },
      { label: "12-well", rows: 3, cols: 4, shape: "round", w: 22.1, h: 22.1, gap: 3.9, corner: 0 },
      { label: "24-well", rows: 4, cols: 6, shape: "round", w: 15.6, h: 15.6, gap: 3.4, corner: 0 },
      { label: "48-well", rows: 6, cols: 8, shape: "round", w: 11.4, h: 11.4, gap: 1.5, corner: 0 },
      /* Greiner Bio-One CELLSTAR, flat bottom, chimney well (655086 / 655090).
         The 9.0 mm pitch is the ANSI/SLAS footprint standard and holds for any
         96-well plate.

         The 6.6 mm is derived, not quoted: it is the diameter Greiner's
         published growth area of 0.34 cm² per well comes to. Greiner publishes
         the growth area and not a well diameter, and the growth area is the
         flat of the well — which is both the part an objective can reach and
         what this list means by an area. Deriving it that way leaves the area
         this panel reports checkable against the catalogue page.

         Do not "correct" this to a figure off another vendor's drawing. A
         Corning flat-bottom 96 is 6.86 mm at the rim and 6.35 mm at the flat,
         which is a different plate; matching it here would quietly describe
         a plate this lab does not run. */
      { label: "96-well", rows: 8, cols: 12, shape: "round", w: 6.6, h: 6.6, gap: 2.4, corner: 0 },
      { label: "384-well", rows: 16, cols: 24, shape: "round", w: 3.6, h: 3.6, gap: 0.9, corner: 0 },
    ],
  },
];

export const carrierType = (id) => CARRIER_TYPES.find((t) => t.id === id);

/** The largest corner radius an area of this size could carry: a full round. */
export const maxRadius = ({ w, h }) => Math.min(w, h) / 2;

/** A preset is a description of a carrier; this is the working copy of one. */
export function fromPreset(typeId, preset) {
  const maxR = maxRadius(preset);
  const corner = preset.shape === "round" ? maxR : preset.corner;
  return {
    type: typeId,
    rows: preset.rows,
    cols: preset.cols,
    w: preset.w,
    h: preset.h,
    /* Depth is a size like the other two and is carried by every carrier, so
       that nothing downstream has to ask what type it is holding before it can
       read one. It is zero for everything that is an area on a stage. */
    d: preset.depth ?? 0,
    gapX: preset.gap,
    gapY: preset.gap,
    cornerRatio: maxR > 0 ? Math.min(corner / maxR, 1) : 0,
  };
}

/**
 * What a run starts on: one plain area, the simplest thing a sample can be
 * mounted on and the one that assumes least about what is being run. A plate
 * was the default for a while, and a plate is a strong claim — eight by twelve
 * wells laid across the stage before the operator has said anything — where an
 * area is the claim that there is a sample somewhere.
 *
 * Named rather than indexed, so adding a preset above it does not quietly
 * change what every fresh run begins with.
 */
export const DEFAULT_CARRIER = fromPreset(
  "slide",
  carrierType("slide").presets.find((p) => p.label.startsWith("Standard")),
);

/**
 * How deep the carrier is, in millimetres. Zero for every carrier that is an
 * area on a stage — the drawing asks this rather than asking what type it has
 * been handed, so a vessel that gains a depth gains a drawing with no further
 * help.
 */
export const depthMm = (config) => (carrierType(config.type).deep ? config.d : 0);

const close = (a, b) => Math.abs(a - b) < 0.005;

/**
 * Which preset of this type the configuration still is, or -1 once it has been
 * edited away from all of them. The dropdown reads "Custom" from that, so an
 * edited carrier never claims to be a catalogue part it no longer matches.
 */
export function matchingPreset(config) {
  const { presets } = carrierType(config.type);
  return presets.findIndex((p) => {
    const ratio = maxRadius(p) > 0
      ? Math.min((p.shape === "round" ? maxRadius(p) : p.corner) / maxRadius(p), 1)
      : 0;
    return p.rows === config.rows && p.cols === config.cols
      && close(p.w, config.w) && close(p.h, config.h)
      && close(p.depth ?? 0, config.d ?? 0)
      && close(p.gap, config.gapX) && close(p.gap, config.gapY)
      && close(ratio, config.cornerRatio);
  });
}

/** Everything the panel and the canvas both need, derived rather than stored. */
export function geometry(config) {
  const { rows, cols, w, h, gapX, gapY, cornerRatio } = config;
  const pitchX = w + gapX;
  const pitchY = h + gapY;
  const corner = cornerRatio * maxRadius(config);
  return {
    pitchX,
    pitchY,
    corner,
    width: cols * pitchX - gapX,
    height: rows * pitchY - gapY,
    areas: rows * cols,
    /* A rounded rectangle loses the four corners it cut away: each is a square
       minus its quarter-circle, so the whole loss is r²(4 − π). */
    areaMm2: w * h - corner * corner * (4 - Math.PI),
  };
}

/**
 * The centre of every imageable area, in millimetres from the carrier's own
 * zero, row-major.
 *
 * One owner for where an area is. The canvas draws the carrier from this and
 * anything placing positions inside it reads the same list, so a scan field
 * and the well it is meant to be in cannot disagree. Centres rather than
 * corners because that is what a position is placed relative to — dividing the
 * carrier's width evenly would land them off by half a gap at every edge.
 */
export function centres(config) {
  const { rows, cols } = config;
  const out = [];
  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) out.push(centreOf(config, row, col));
  }
  return out;
}

/** Where one area sits. The one place the answer is worked out. */
function centreOf(config, row, col) {
  const { w, h } = config;
  const { pitchX, pitchY } = geometry(config);
  return { row, col, x: col * pitchX + w / 2, y: row * pitchY + h / 2 };
}

/**
 * The area nearest a point, whether or not the point is in it. Rounded to the
 * grid rather than searched, so a plate of a thousand wells costs what one
 * does, and clamped to the plate so a point off the edge belongs to the area
 * at that edge.
 */
export function nearestArea(config, x, y) {
  const { rows, cols, w, h } = config;
  const { pitchX, pitchY } = geometry(config);
  const col = Math.min(cols - 1, Math.max(0, Math.round((x - w / 2) / pitchX)));
  const row = Math.min(rows - 1, Math.max(0, Math.round((y - h / 2) / pitchY)));
  return centreOf(config, row, col);
}

/**
 * The rectangle inside an area that a run actually images — square-cornered,
 * whatever shape the area is.
 *
 * A well is round and a plan is not. Tiles laid to the edge of a circle come
 * out as a rounded blob: an outline nobody drew, no two rows the same length,
 * and a picture whose shape says something about the plastic rather than about
 * the sample. What an operator means by "this well" is the square of it that
 * can be imaged, so that square is what the plan is held to.
 *
 * It is the area's own rectangle with the corner arcs cut back to their
 * chords: exact at both ends of the range, giving the whole rectangle when
 * there is no corner to cut and the inscribed square when the area is a
 * circle.
 */
export function scanBox(config) {
  const { w, h } = config;
  const { corner } = geometry(config);
  const cut = corner - corner / Math.SQRT2;
  return { halfW: w / 2 - cut, halfH: h / 2 - cut };
}

/** Whether a point is over the imageable square of an area. */
export function insideArea(config, x, y) {
  const a = nearestArea(config, x, y);
  const { halfW, halfH } = scanBox(config);
  return Math.abs(x - a.x) <= halfW && Math.abs(y - a.y) <= halfH;
}

/**
 * Whether a frame that wide, centred there, lies wholly inside one area.
 *
 * This is the rule the whole plan is held to: what the objective sees is a
 * square of sample, and a square that hangs over the edge of the imageable
 * square is a square of plastic.
 */
export function frameFitsArea(config, x, y, frame) {
  const a = nearestArea(config, x, y);
  const { halfW, halfH } = scanBox(config);
  const half = frame / 2;
  return Math.abs(x - a.x) + half <= halfW && Math.abs(y - a.y) + half <= halfH;
}

/**
 * The nearest place that frame can sit, moving straight in towards the middle
 * of the area it is nearest — null when it cannot sit there at all, which is
 * what a frame wider than the well itself means.
 *
 * Straight in rather than to the closest edge point, because a position that
 * would not fit where it was put should end up in the middle of the well the
 * operator was aiming at, not skating along its rim.
 */
export function frameSeat(config, x, y, frame) {
  if (frameFitsArea(config, x, y, frame)) return { x, y };
  const a = nearestArea(config, x, y);
  if (!frameFitsArea(config, a.x, a.y, frame)) return null;
  let lo = 0, hi = 1;
  for (let i = 0; i < 24; i++) {
    const t = (lo + hi) / 2;
    if (frameFitsArea(config, x + (a.x - x) * t, y + (a.y - y) * t, frame)) hi = t;
    else lo = t;
  }
  return { x: x + (a.x - x) * hi, y: y + (a.y - y) * hi };
}

/** One line for the run: what was configured, without opening the panel. */
export const describeCarrier = (config) => {
  const g = geometry(config);
  const preset = matchingPreset(config);
  const name = preset >= 0
    ? carrierType(config.type).presets[preset].label
    : `${carrierType(config.type).label} · ${config.rows}×${config.cols}`;
  return `${name} · ${g.width.toFixed(1)} × ${g.height.toFixed(1)} mm`;
};
