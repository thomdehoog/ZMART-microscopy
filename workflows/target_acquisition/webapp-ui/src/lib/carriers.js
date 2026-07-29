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

export const CARRIER_TYPES = [
  {
    id: "slide",
    label: "Slide",
    presets: [
      { label: "Standard (75 × 25 mm)", rows: 1, cols: 1, shape: "rect", w: 75, h: 25, gap: 0, corner: 0.5 },
      { label: "Large (76 × 52 mm)", rows: 1, cols: 1, shape: "rect", w: 76, h: 52, gap: 0, corner: 0.5 },
    ],
  },
  {
    id: "dish",
    label: "Dish",
    presets: [
      { label: "35 mm dish", rows: 1, cols: 1, shape: "round", w: 35, h: 35, gap: 0, corner: 0 },
      { label: "60 mm dish", rows: 1, cols: 1, shape: "round", w: 60, h: 60, gap: 0, corner: 0 },
      { label: "100 mm dish", rows: 1, cols: 1, shape: "round", w: 100, h: 100, gap: 0, corner: 0 },
    ],
  },
  {
    id: "wellplate",
    label: "Wellplate",
    presets: [
      { label: "6-well", rows: 2, cols: 3, shape: "round", w: 34.8, h: 34.8, gap: 4.4, corner: 0 },
      { label: "12-well", rows: 3, cols: 4, shape: "round", w: 22.1, h: 22.1, gap: 3.9, corner: 0 },
      { label: "24-well", rows: 4, cols: 6, shape: "round", w: 15.6, h: 15.6, gap: 3.4, corner: 0 },
      { label: "48-well", rows: 6, cols: 8, shape: "round", w: 11.4, h: 11.4, gap: 1.5, corner: 0 },
      /* Greiner Bio-One, flat bottom. The 9.0 mm pitch is the SLAS footprint
         standard and holds for any 96-well plate. The 6.6 mm is the well
         bottom, not the 6.96 mm rim: the flat of the well is the part an
         objective can reach, which is what this list means by an area. It is
         the diameter Greiner's published 0.34 cm² growth area comes to, so
         the area this panel reports can be checked against the catalogue. */
      { label: "96-well (Greiner)", rows: 8, cols: 12, shape: "round", w: 6.6, h: 6.6, gap: 2.4, corner: 0 },
      { label: "384-well", rows: 16, cols: 24, shape: "round", w: 3.6, h: 3.6, gap: 0.9, corner: 0 },
    ],
  },
  {
    id: "chamber",
    label: "Chamber",
    presets: [
      { label: "1-chamber (ibidi)", rows: 1, cols: 1, shape: "rect", w: 48, h: 24, gap: 0, corner: 2 },
      { label: "2-chamber (ibidi)", rows: 1, cols: 2, shape: "rect", w: 21.3, h: 17.6, gap: 4.8, corner: 1.5 },
      { label: "4-chamber (Nunc)", rows: 2, cols: 2, shape: "rect", w: 20, h: 10, gap: 3, corner: 1.5 },
      { label: "8-chamber (ibidi)", rows: 2, cols: 4, shape: "rect", w: 9.4, h: 10.7, gap: 1, corner: 1 },
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
    gapX: preset.gap,
    gapY: preset.gap,
    cornerRatio: maxR > 0 ? Math.min(corner / maxR, 1) : 0,
  };
}

/**
 * What a run starts on: the plate this lab runs most. Named rather than
 * indexed, so adding a preset above it does not quietly change what every
 * fresh run begins with.
 */
export const DEFAULT_CARRIER = fromPreset(
  "wellplate",
  carrierType("wellplate").presets.find((p) => p.label.startsWith("96-well")),
);

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

/** What to call this shape, from the corner alone. */
export function shapeName({ w, h, cornerRatio }) {
  if (cornerRatio >= 0.99) return w === h ? "Circle" : "Pill";
  return cornerRatio > 0 ? "Rounded rect" : "Rectangle";
}

/** One line for the rail: what was configured, without opening the panel. */
export const describeCarrier = (config) => {
  const g = geometry(config);
  const preset = matchingPreset(config);
  const name = preset >= 0
    ? carrierType(config.type).presets[preset].label
    : `${carrierType(config.type).label} · ${config.rows}×${config.cols}`;
  return `${name} · ${g.width.toFixed(1)} × ${g.height.toFixed(1)} mm`;
};
