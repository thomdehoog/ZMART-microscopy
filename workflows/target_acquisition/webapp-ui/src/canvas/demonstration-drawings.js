/**
 * What the operator's own two layers draw, in the canvas demonstration.
 *
 * The canvas draws three things stacked one over the other: the application's
 * own drawing beneath, the acquired picture in the middle, and the application's
 * own drawing above. The middle one comes from the run. The outer two are the
 * page's to draw, and these are the two drawings the demonstration puts in them.
 *
 * They are deliberately plain, because they are there to be *seen* rather than
 * to be useful. In a real workflow these two slots hold the things an operator
 * works with — the carrier the sample is mounted in, the positions the
 * microscope will visit, a region being drawn by hand — and when that day comes
 * the drawings should be handed to the canvas by the workflow rather than living
 * here. This file is the demonstration's own, and nothing but the demonstration
 * imports it.
 *
 * ## Why they are drawn in micrometres
 *
 * Both drawings are placed with `project`, which turns a position on the stage
 * in micrometres into a position in the box in screen pixels for the frame being
 * drawn right now. Everything here is therefore anchored to the specimen rather
 * than to the window: pan the picture and the lines travel with it, zoom in and
 * they spread apart. That is the whole property the canvas is being built to
 * have, and drawing this way is how you can watch whether it holds. A drawing
 * placed in screen pixels instead would sit perfectly still and prove nothing.
 *
 * ## The colours are declared here and measured from here
 *
 * The tests photograph the box and count how much of it is each of these
 * colours, importing the numbers below rather than repeating them. So there is
 * one place the colours are written down, and a test cannot quietly go on
 * passing against a colour the page stopped using.
 */

/**
 * The colour of the layer beneath the picture: a clear blue.
 *
 * Chosen to be nothing like a specimen. An acquisition is drawn in white over
 * near-black, so a strong blue cannot be mistaken for the picture, and neither
 * can it be mistaken for the dark ground the microscope has never visited.
 */
export const THE_COLOUR_BENEATH = [30, 80, 190];

/** The colour of the layer above the picture: amber, for the same reason. */
export const THE_COLOUR_ABOVE = [240, 160, 30];

/** Turn one of the colours above into something a drawing context understands. */
const asCss = ([red, green, blue], alpha = 1) =>
  `rgba(${red}, ${green}, ${blue}, ${alpha})`;

/**
 * A round number of micrometres that comes out about `wanted` pixels apart.
 *
 * The lattice below is ruled in micrometres, so at some magnifications a fixed
 * spacing would be a single smudge and at others a single line across the whole
 * window. Choosing 1, 2 or 5 times a power of ten keeps the spacing on screen
 * roughly steady while the number itself stays one an operator can read off —
 * 200 µm rather than 187 µm.
 */
function aRoundSpacing(umPerPixel, wanted) {
  const rough = Math.max(umPerPixel * wanted, 1e-6);
  const power = 10 ** Math.floor(Math.log10(rough));
  for (const step of [1, 2, 5]) {
    if (step * power >= rough) return step * power;
  }
  return 10 * power;
}

/**
 * Rule a lattice across the whole box, every `spacing` micrometres.
 *
 * The lines are placed by asking where each round micrometre lands on screen, so
 * they stay locked to the specimen. Working out which lines are worth drawing
 * from the corners of the box means only the handful on screen are drawn,
 * however far the view has travelled from the stage's zero.
 */
function ruleALattice({ context, width, height, project, unproject }, spacing, lineWidth) {
  const corners = [unproject(0, 0), unproject(width, height)];
  const from = { x: Math.min(corners[0].x, corners[1].x), y: Math.min(corners[0].y, corners[1].y) };
  const to = { x: Math.max(corners[0].x, corners[1].x), y: Math.max(corners[0].y, corners[1].y) };
  /* A guard, not tidiness. If a view ever arrives with a magnification that
     makes the spacing vanishingly small on screen, drawing every line between
     the corners would be hundreds of thousands of them and the page would stop
     answering. Well before that happens the lattice is a solid block anyway, so
     there is nothing lost by giving up on it. */
  if ((to.x - from.x) / spacing > 400 || (to.y - from.y) / spacing > 400) return;

  context.lineWidth = lineWidth;
  context.beginPath();
  for (let x = Math.ceil(from.x / spacing) * spacing; x <= to.x; x += spacing) {
    const top = project(x, from.y);
    const bottom = project(x, to.y);
    context.moveTo(top.x, top.y);
    context.lineTo(bottom.x, bottom.y);
  }
  for (let y = Math.ceil(from.y / spacing) * spacing; y <= to.y; y += spacing) {
    const left = project(from.x, y);
    const right = project(to.x, y);
    context.moveTo(left.x, left.y);
    context.lineTo(right.x, right.y);
  }
  context.stroke();
}

/**
 * The layer beneath the picture: a flat wash of blue with a lattice ruled on it.
 *
 * The wash covers the whole box, so wherever the picture does not reach — which
 * is most of the stage, most of the time — the blue is what an operator sees.
 * That is exactly the arrangement the engines differ on, and it is why this
 * drawing is a flat colour rather than something prettier: whether it is there
 * at all has to be obvious at a glance and countable in a photograph.
 *
 * The lattice on top of the wash is there so you can tell a layer that is
 * genuinely beneath the picture from a coloured box painted behind the whole
 * canvas. Pan the view and the lattice travels with the specimen.
 */
export function theGroundBeneath(frame) {
  const { context, width, height, zoom } = frame;
  context.fillStyle = asCss(THE_COLOUR_BENEATH);
  context.fillRect(0, 0, width, height);
  /* Ruled finer than the drawing above, and that is the point rather than a
     preference. If the two lattices were spaced the same they would land on the
     same lines and one would hide the other, so with both layers on you could
     not tell whether you were looking at one drawing or two. */
  context.strokeStyle = "rgba(255, 255, 255, 0.30)";
  ruleALattice(frame, aRoundSpacing(zoom, 55), 1);
}

/**
 * The layer above the picture: an amber lattice, with the stage's zero marked.
 *
 * This stands in for the things an operator really draws over an acquisition —
 * the carrier, the positions the microscope will visit, a region marked out by
 * hand. It is drawn in open lines rather than filled shapes because a drawing
 * above the picture that covered the picture would be no use to anybody.
 *
 * The stage's zero is marked because it is the one position on the stage that
 * means something without a run to give it meaning, and having a landmark makes
 * it easy to see that the drawing and the picture move together.
 */
export function theOperatorsMarks(frame) {
  const { context, zoom, project } = frame;
  const spacing = aRoundSpacing(zoom, 130);

  /* Wide enough to be unmistakable, and no wider. This drawing sits over the
     acquisition, so every pixel it takes is a pixel of specimen an operator
     cannot see; four across is enough to read as a deliberate line and to be
     counted in a photograph, and it leaves the picture underneath legible. */
  context.strokeStyle = asCss(THE_COLOUR_ABOVE);
  ruleALattice(frame, spacing, 4);

  // The stage's zero: a ring, and the round spacing written beside it so that
  // what the lattice measures is on screen rather than left to be guessed.
  const zero = project(0, 0);
  context.beginPath();
  context.arc(zero.x, zero.y, 9, 0, Math.PI * 2);
  context.lineWidth = 3;
  context.stroke();
  context.fillStyle = asCss(THE_COLOUR_ABOVE);
  context.font = "600 12px ui-monospace, monospace";
  context.fillText(`0, 0 µm · lattice every ${spacing} µm`, zero.x + 14, zero.y + 4);
}
