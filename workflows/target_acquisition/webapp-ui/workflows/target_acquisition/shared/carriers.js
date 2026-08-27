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
   `starts`  which of its carriers the type opens on. Named, because the list
             is ordered by how many areas a carrier has and the smallest of
             them is rarely the one anybody means: pressing Wellplate and being
             handed a one-well plate is the catalogue's order answering a
             question about what an operator usually mounts.

   Add a vessel by describing it here and the controls follow.

   ── where these figures come from ────────────────────────────────────────
   Every preset below is read out of the carrier library LAS X ships:
   `M5CarrierLibrary.dll`, under `Models.Carrier.*`, which is what the
   microscope's own software draws and plans with. Taking them from there
   rather than from catalogues means this panel and the instrument describe
   the same piece of plastic.

   Leica states a plate size, the centre of the first area, an area size and
   a pitch. This panel states areas and the gaps between them, so the pitch
   becomes a gap: gap = pitch − area. Nothing else is converted.

   They check out. The plates are ANSI/SLAS to the hundredth of a millimetre
   — 9.0 mm pitch on 96, 4.5 on 384, 2.25 on 1536, A1 at 14.38/11.24 — and the
   vendor parts match the vendors: ibidi's µ-Slide 8 well is 10.7 × 9.4 mm,
   which is the 1.0 cm² per well ibidi publishes, and their µ-Dish 35 mm is a
   21 mm circle, which is its 3.5 cm². The EM meshes check against their own
   names: 300 lines to the inch is 25.4/300 = 84.7 µm, against the 83 µm the
   part is made to.

   Two things are deliberately not Leica's:

   The corner radius. Leica declares 5.0 mm for chambers of every size from
   10.5 mm to 45 mm, and 2.0 mm for a 2.9 mm square well — round numbers that
   do not track the part, which makes them a drawing constant rather than a
   measured feature. Left alone they would have made a "square well" plate 69
   per cent round and, because the corner decides how much of an area a square
   frame can reach, quietly taken a millimetre and a half off every chamber
   the run could image. They are capped at a fifth of the shorter side, which
   is about what these parts look like.

   Areas Leica declares no geometry for are left out rather than guessed at:
   the two 30-micron-bottom ibidi dishes are in the library with a name and
   nothing else. */
export const CARRIER_TYPES = [
  {
    id: "slide",
    starts: "75 × 25 mm slide",
    label: "Area",
    grid: false,
    round: false,
    deep: false,
    presets: [
      /* The Convallaria demo slide is a 15 mm circle on 76 × 24 glass, which
         is the entry below. */
      { label: "75 × 25 mm · colour frosted", rows: 1, cols: 1, shape: "rect", w: 57.8, h: 23, gap: 0, corner: 0 },
      { label: "76 × 24 mm · 15 mm circle", rows: 1, cols: 1, shape: "round", w: 15, h: 15, gap: 0, corner: 0 },
      { label: "76 × 24 mm · 20 mm circle", rows: 1, cols: 1, shape: "round", w: 20, h: 20, gap: 0, corner: 0 },
      { label: "76 × 24 mm · 20 × 20 mm cover slip", rows: 1, cols: 1, shape: "rect", w: 20, h: 20, gap: 0, corner: 0 },
      { label: "76 × 24 mm · 50 × 20 mm cover slip", rows: 1, cols: 1, shape: "rect", w: 50, h: 20, gap: 0, corner: 0 },
      { label: "25 × 48 mm slide", rows: 1, cols: 1, shape: "rect", w: 23, h: 46, gap: 0, corner: 0 },
      { label: "46 × 27 mm slide", rows: 1, cols: 1, shape: "rect", w: 44, h: 25, gap: 0, corner: 0 },
      { label: "48 × 28 mm slide", rows: 1, cols: 1, shape: "rect", w: 46, h: 26, gap: 0, corner: 0 },
      { label: "75 × 25 mm slide", rows: 1, cols: 1, shape: "rect", w: 73, h: 23, gap: 0, corner: 0 },
      { label: "75 × 38 mm slide", rows: 1, cols: 1, shape: "rect", w: 73, h: 36, gap: 0, corner: 0 },
      { label: "76 × 24 mm slide", rows: 1, cols: 1, shape: "rect", w: 74, h: 22, gap: 0, corner: 0 },
      { label: "76 × 26 mm slide", rows: 1, cols: 1, shape: "rect", w: 74, h: 24, gap: 0, corner: 0 },
      { label: "76 × 51 mm slide", rows: 1, cols: 1, shape: "rect", w: 74, h: 49, gap: 0, corner: 0 },
      { label: "76 × 52 mm slide", rows: 1, cols: 1, shape: "rect", w: 74, h: 50, gap: 0, corner: 0 },
    ],
  },
  {
    id: "dish",
    starts: "35 mm dish",
    label: "Dish",
    grid: false,
    round: true,
    deep: false,
    presets: [
      { label: "35 mm · ibidi µ-Dish", rows: 1, cols: 1, shape: "round", w: 21, h: 21, gap: 0, corner: 0 },
      { label: "35 mm dish", rows: 1, cols: 1, shape: "round", w: 33, h: 33, gap: 0, corner: 0 },
      { label: "50 mm · ibidi µ-Dish", rows: 1, cols: 1, shape: "round", w: 30, h: 30, gap: 0, corner: 0 },
      { label: "60 mm dish", rows: 1, cols: 1, shape: "round", w: 58, h: 58, gap: 0, corner: 0 },
      { label: "94 mm dish", rows: 1, cols: 1, shape: "round", w: 92, h: 92, gap: 0, corner: 0 },
      { label: "100 mm dish", rows: 1, cols: 1, shape: "round", w: 98, h: 98, gap: 0, corner: 0 },
      { label: "145 mm dish", rows: 1, cols: 1, shape: "round", w: 143, h: 143, gap: 0, corner: 0 },
    ],
  },
  {
    id: "chamber",
    starts: "8-well · ibidi µ-Slide",
    label: "Chamber",
    grid: true,
    round: false,
    deep: false,
    presets: [
      { label: "1-chamber · Nunc Lab-Tek", rows: 1, cols: 1, shape: "rect", w: 45.05, h: 20.45, gap: 0, corner: 1 },
      { label: "1-chamber · Nunc Lab-Tek 177372", rows: 1, cols: 1, shape: "rect", w: 44.87, h: 19.8, gap: 0, corner: 3.96 },
      { label: "2-chamber · Nunc Lab-Tek", rows: 1, cols: 2, shape: "rect", w: 22.4, h: 21.5, gapX: 1.6, gapY: 0, corner: 2 },
      { label: "2-chamber · Nunc Lab-Tek 177380", rows: 1, cols: 2, shape: "rect", w: 19.8, h: 19.8, gapX: 3.9, gapY: 0, corner: 3.96 },
      { label: "2-well · MatTek", rows: 1, cols: 2, shape: "rect", w: 22.2, h: 18.94, gapX: 1.8, gapY: 0, corner: 3 },
      { label: "2-well · ibidi µ-Slide", rows: 1, cols: 2, shape: "rect", w: 23.3, h: 21.2, gapX: 1, gapY: 0, corner: 4.24 },
      { label: "3-well · ibidi removable chamber", rows: 1, cols: 3, shape: "rect", w: 16.5, h: 16.5, gapX: 0.8, gapY: 0, corner: 2 },
      { label: "4-chamber · Nunc Lab-Tek", rows: 1, cols: 4, shape: "rect", w: 10.95, h: 21.1, gapX: 1.2, gapY: 0, corner: 2 },
      { label: "4-chamber · Nunc Lab-Tek 177399", rows: 1, cols: 4, shape: "rect", w: 10.18, h: 19.8, gapX: 1.45, gapY: 0, corner: 2.036 },
      { label: "4-well · MatTek", rows: 1, cols: 4, shape: "rect", w: 10.2, h: 18.94, gapX: 1.8, gapY: 0, corner: 2.04 },
      { label: "4-well · ibidi µ-Slide", rows: 1, cols: 4, shape: "rect", w: 11, h: 21.2, gapX: 1, gapY: 0, corner: 2.2 },
      /* Leica's own IGBMC 8-chamber slide is this part, to the hundredth of a
         millimetre — the library ships both names against one geometry. */
      { label: "8-chamber · Nunc Lab-Tek", rows: 2, cols: 4, shape: "rect", w: 10.5, h: 10.5, gap: 1.08, corner: 2 },
      { label: "8-chamber · Nunc Lab-Tek 177402", rows: 2, cols: 4, shape: "rect", w: 10.5, h: 10.5, gap: 1.08, corner: 2.1 },
      { label: "8-chamber · Nunc Lab-Tek II 154534", rows: 2, cols: 4, shape: "rect", w: 9.1, h: 7.25, gapX: 3.95, gapY: 3.73, corner: 1.45 },
      { label: "8-well · MatTek", rows: 2, cols: 4, shape: "rect", w: 10.2, h: 8.57, gap: 1.8, corner: 1.714 },
      { label: "8-well · ibidi removable chamber", rows: 2, cols: 4, shape: "rect", w: 11.9, h: 7.8, gapX: 1.7, gapY: 1.5, corner: 1.56 },
      { label: "8-well · ibidi µ-Slide", rows: 2, cols: 4, shape: "rect", w: 10.7, h: 9.4, gapX: 1.2, gapY: 1, corner: 1.88 },
      { label: "12-well · ibidi removable chamber", rows: 2, cols: 6, shape: "rect", w: 7.2, h: 7.2, gap: 1.95, corner: 1.44 },
    ],
  },
  {
    id: "wellplate",
    starts: "96-well · Greiner SensoPlate",
    label: "Wellplate",
    grid: true,
    round: false,
    deep: false,
    presets: [
      { label: "1-well · Greiner CELLSTAR", rows: 1, cols: 1, shape: "rect", w: 110, h: 80, gap: 0, corner: 0 },
      { label: "4-well · Greiner CELLSTAR", rows: 1, cols: 4, shape: "rect", w: 28, h: 64, gapX: 2.5, gapY: 0, corner: 0 },
      { label: "6-well · Nunc Nunclon", rows: 2, cols: 3, shape: "round", w: 36, h: 36, gap: 4, corner: 0 },
      { label: "12-well · Greiner CELLSTAR", rows: 3, cols: 4, shape: "round", w: 22.2, h: 22.2, gap: 3.8, corner: 0 },
      { label: "24-well · Greiner CELLSTAR", rows: 4, cols: 6, shape: "round", w: 15.66, h: 15.66, gap: 3.84, corner: 0 },
      { label: "24-well · ibidi µ-Plate", rows: 4, cols: 6, shape: "round", w: 16.28, h: 16.28, gap: 2.62, corner: 0 },
      { label: "48-well · Greiner CELLSTAR", rows: 6, cols: 8, shape: "round", w: 11.37, h: 11.37, gap: 1.63, corner: 0 },
      { label: "96-well · Greiner SensoPlate", rows: 8, cols: 12, shape: "round", w: 6.58, h: 6.58, gap: 2.42, corner: 0 },
      { label: "96-well · Greiner SensoPlate half-area", rows: 8, cols: 12, shape: "round", w: 4.38, h: 4.38, gap: 4.62, corner: 0 },
      { label: "96-well · Matrical square", rows: 8, cols: 12, shape: "rect", w: 7.52, h: 7.52, gap: 1.48, corner: 1.504 },
      { label: "96-well · Whatman", rows: 8, cols: 12, shape: "round", w: 7.26, h: 7.26, gap: 1.74, corner: 0 },
      { label: "96-well · ibidi µ-Plate", rows: 8, cols: 12, shape: "rect", w: 7.48, h: 7.48, gap: 1.57, corner: 1.496 },
      { label: "96-well · ibidi µ-Plate angiogenesis", rows: 8, cols: 12, shape: "round", w: 4, h: 4, gap: 5, corner: 0 },
      { label: "384-well · Greiner SensoPlate", rows: 16, cols: 24, shape: "rect", w: 3.3, h: 3.3, gap: 1.2, corner: 0.66 },
      { label: "384-well · Greiner SensoPlate small volume", rows: 16, cols: 24, shape: "round", w: 1.84, h: 1.84, gap: 2.66, corner: 0 },
      { label: "384-well · Matrical square", rows: 16, cols: 24, shape: "rect", w: 2.9, h: 2.9, gap: 1.6, corner: 0.58 },
      { label: "384-well · ibidi µ-Plate", rows: 16, cols: 24, shape: "rect", w: 3.45, h: 3.45, gap: 1.05, corner: 0.69 },
      { label: "1536-well · Greiner SensoPlate", rows: 32, cols: 48, shape: "rect", w: 1.53, h: 1.53, gap: 0.72, corner: 0 },
      /* Greiner also lists a low-base 1536, which differs in how far the well
         bottom sits below the rim and not at all in the grid above it. */
      { label: "24320-well · Greiner high density", rows: 128, cols: 190, shape: "round", w: 0.26, h: 0.26, gap: 0.3025, corner: 0 },
    ],
  },
];

/* The grids an electron microscope's samples come on, which a light microscope
   is asked to look at first in correlative work. A grid is the same shape as
   everything else here — a lattice of imageable squares — only three orders of
   magnitude smaller: a 300 mesh grid is 58 µm squares on an 83 µm pitch, where
   a 96-well plate is 6.58 mm wells on a 9 mm one.

   The mesh number is lines to the inch, and it checks: 300 mesh is 25.4/300 =
   84.7 µm, against the 83 µm the part is actually made to. The rows and columns
   are how many of that pitch fit across a 3.05 mm grid, which is the diameter
   every one of these is punched to. */
CARRIER_TYPES.push({
  id: "emgrid",
  starts: "200 mesh · EMS",
  label: "EM grid",
  grid: true,
  round: false,
  deep: false,
  presets: [
    { label: "50 mesh · EMS", rows: 6, cols: 6, shape: "rect", w: 0.42, h: 0.42, gap: 0.08, corner: 0 },
    { label: "75 mesh · EMS", rows: 8, cols: 8, shape: "rect", w: 0.285, h: 0.285, gap: 0.055, corner: 0 },
    { label: "100 mesh · EMS", rows: 12, cols: 12, shape: "rect", w: 0.205, h: 0.205, gap: 0.045, corner: 0 },
    { label: "150 mesh · Ted Pella", rows: 18, cols: 18, shape: "rect", w: 0.125, h: 0.125, gap: 0.04, corner: 0 },
      /* Ted Pella's centre-rim 150 is the same mesh with the middle square
         marked, which is a thing to look for rather than a thing to image. */
    { label: "200 mesh · EMS", rows: 24, cols: 24, shape: "rect", w: 0.09, h: 0.09, gap: 0.035, corner: 0 },
    { label: "200 mesh · SPI", rows: 24, cols: 24, shape: "rect", w: 0.095, h: 0.095, gap: 0.03, corner: 0 },
    { label: "300 mesh · SPI", rows: 36, cols: 36, shape: "rect", w: 0.058, h: 0.058, gap: 0.025, corner: 0 },
    { label: "parallel bar 340 µm · EMS", rows: 8, cols: 8, shape: "rect", w: 0.27, h: 0.27, gap: 0.07, corner: 0 },
    { label: "parallel bar 500 µm · EMS", rows: 6, cols: 6, shape: "rect", w: 0.416, h: 0.416, gap: 0.084, corner: 0 },
  ],
});

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
    /* One gap where the two are the same, which is most carriers, and two where
       they are not. A chamber slide's wells are wider apart across the slide
       than they are down it — the ibidi 8-well steps 11.9 mm one way and 10.4
       the other — and a preset that could only say one number had to lie about
       one of them. */
    gapX: preset.gapX ?? preset.gap,
    gapY: preset.gapY ?? preset.gap,
    cornerRatio: maxR > 0 ? Math.min(corner / maxR, 1) : 0,
  };
}

/** The gap a preset means, in each direction. See `fromPreset`. */
const gapsOf = (p) => [p.gapX ?? p.gap, p.gapY ?? p.gap];

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
  carrierType("slide").presets.find((p) => p.label === "75 × 25 mm slide"),
);

/**
 * How deep the carrier is, in millimetres. Zero for every carrier that is an
 * area on a stage — the drawing asks this rather than asking what type it has
 * been handed, so a vessel that gains a depth gains a drawing with no further
 * help.
 */
export const depthMm = (config) => (carrierType(config.type).deep ? config.d : 0);

/* A tenth of a micrometre. Five micrometres was the tolerance while everything
   here was a plate or a slide, and it is far too coarse for an EM grid: a 50
   mesh has 0.42 mm holes and a 500 µm parallel bar has 0.416 mm ones, four
   micrometres apart, and the picker called them the same part. Every figure in
   this file is quoted to four decimals, so an exact match is exact. */
const close = (a, b) => Math.abs(a - b) < 1e-4;

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
    const [gx, gy] = gapsOf(p);
    return p.rows === config.rows && p.cols === config.cols
      && close(p.w, config.w) && close(p.h, config.h)
      && close(p.depth ?? 0, config.d ?? 0)
      && close(gx, config.gapX) && close(gy, config.gapY)
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
