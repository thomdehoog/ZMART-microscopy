/**
 * What the operator's own hand draws — the same code in every option.
 *
 * This is the part that decides whether comparing three viewers is fair. Each
 * option calls the page's drawing function at the moment that option considers
 * correct, and the page hands over the *same* function every time. It receives
 * the view to draw against and knows nothing whatever about what is underneath
 * it: no engine, no canvas of the engine's, no zoom of anybody's private kind.
 * If the three options then look different, the difference is the engine.
 *
 * Everything here is placed in micrometres and turned into screen pixels by the
 * `project` function the option supplies, so there is exactly one place where
 * the conversion can be wrong, and it is not in this file.
 *
 * There are two drawings, because the page is asked two different questions.
 *
 * **The carrier** is what an operator actually sees: the outline of the plate or
 * slide, the wells in it, and the rectangles of the tiles they laid out,
 * coloured by how each one is getting on. It is the drawing the comparison is
 * really about.
 *
 * **The margin probe** is a measuring instrument rather than a picture. It is a
 * plain sheet with a rectangular hole cut a little larger than a known square of
 * image, so that the band of background showing between the two can be measured
 * on all four sides. Its whole virtue is that the right answer is "unchanged":
 * there is no threshold to argue over, because any disagreement between the two
 * layers turns into the band going uneven. `viz_studio/tests/margins.py` reads
 * it back out of a photograph.
 */

// The colours the margin probe is drawn in, and why they are what they are.
//
// The measurement has to tell four things apart in a photograph of the screen:
// the image, the background behind it, the sheet on top, and something the
// operator drew that is meant to sit exactly on the edge of an imaged tile. So
// they are given four colours nothing could confuse — near-white, saturated
// blue, saturated red, saturated green.
//
// **In the finished viewer the background is meant to match the page**, so that
// the seam between the two drawing surfaces cannot be seen at all. That is the
// whole point of the arrangement. They differ here only so the band can be seen
// and measured. Please do not tidy them into agreement: this check would go on
// passing while measuring nothing.
export const SHEET_IS_RED = "rgb(220, 0, 0)";
export const OPERATOR_DRAWING_IS_GREEN = "rgb(0, 220, 0)";

/**
 * How much wider than the imaged square the hole is cut, on each side, in the
 * browser's own pixels.
 *
 * Measured in screen units rather than in specimen units on purpose. Cut in
 * specimen units the band would honestly grow as the operator zoomed in, and
 * "the margins changed" would then mean two different things. Held at a fixed
 * number of screen pixels the right answer is the same number at every
 * magnification, so a magnification that has drifted shows up at once as all
 * four margins moving together.
 *
 * Forty is comfortably wider than the drift a real gesture produces, and that
 * matters: once the drift exceeds the margin the sheet has covered the edge of
 * the image and there is nothing left to measure on that side. The reading half
 * says plainly when that has happened rather than reporting it as zero.
 */
export const MARGIN_CSS_PX = 40;

/**
 * Turn a rectangle given in micrometres into its place on the screen.
 *
 * `region` is `{x0, y0, x1, y1}` in micrometres; `project` is the function the
 * option handed to the drawing.
 */
function onScreen(project, region) {
  const low = project(region.x0, region.y0);
  const high = project(region.x1, region.y1);
  return {
    left: low.x,
    top: low.y,
    right: high.x,
    bottom: high.y,
    width: high.x - low.x,
    height: high.y - low.y,
  };
}

/**
 * The operator's real drawing: a carrier, the tiles on it, and what is selected.
 *
 * `scene` describes what to draw, all in micrometres:
 *
 * - `carrier`  `{x0, y0, x1, y1}` — the outline of the plate or slide
 * - `wells`    a list of `{x, y, r}` circles drawn inside it
 * - `tiles`    a list of `{x0, y0, x1, y1, state}`, where `state` is one of
 *              `planned`, `acquiring` or `done`
 * - `selected` the index of the tile the operator is working with, or `null`
 * - `background` the page colour, so the sheet matches it exactly
 *
 * The order things are drawn in is not arbitrary. The carrier and the tiles are
 * painted first and then the ground that really holds picture is cleared away,
 * letting the image show through from the engine's canvas underneath. Anything
 * the operator is actively working with sits on top of everything and is painted
 * last, after the clearing, so it is never hidden by the picture.
 *
 * One thing to know before copying this order into a real viewer. It puts the
 * planned tiles *below* the acquisition, because a tile rectangle is cleared away
 * wherever picture was written — and `LAYERS.md` has since been corrected to put
 * the plan above the picture, on the evidence that an operator most wants to see
 * a tile's outline at the moment that tile has just been imaged. Drawing the tile
 * outlines again after the holes are cut would follow the corrected order. It has
 * deliberately not been changed here, because these measurements were taken with
 * the drawing as it stands and the readings would no longer describe the same
 * page.
 */
export function drawTheCarrier({ context, width, height, project, coverage }, scene) {
  const { background = "#101014", tiles = [], wells = [], carrier = null } = scene;

  // The sheet itself, in the page's own colour. Everywhere it is left standing
  // is somewhere the operator sees their own drawing rather than the picture.
  context.fillStyle = background;
  context.fillRect(0, 0, width, height);

  if (carrier) {
    const box = onScreen(project, carrier);
    context.strokeStyle = "rgba(200, 208, 220, 0.85)";
    context.lineWidth = 2;
    context.strokeRect(box.left, box.top, box.width, box.height);
  }

  context.strokeStyle = "rgba(150, 160, 180, 0.55)";
  context.lineWidth = 1;
  for (const well of wells) {
    const middle = project(well.x, well.y);
    const edge = project(well.x + well.r, well.y);
    context.beginPath();
    context.arc(middle.x, middle.y, Math.abs(edge.x - middle.x), 0, Math.PI * 2);
    context.stroke();
  }

  // The tiles the operator laid out, coloured by how each is getting on. This is
  // the thing that changes every few seconds during a run and must never touch
  // the disk, which is most of why it belongs to the application rather than to
  // the engine.
  const fills = {
    planned: "rgba(120, 130, 160, 0.30)",
    acquiring: "rgba(240, 190, 90, 0.45)",
    done: "rgba(110, 200, 150, 0.30)",
  };
  for (const tile of tiles) {
    const box = onScreen(project, tile);
    context.fillStyle = fills[tile.state] || fills.planned;
    context.fillRect(box.left, box.top, box.width, box.height);
    context.strokeStyle = "rgba(210, 220, 235, 0.5)";
    context.lineWidth = 1;
    context.strokeRect(box.left, box.top, box.width, box.height);
  }

  // Now cut the holes: the ground the run has actually imaged, taken from the
  // record the writer kept beside the data. This is the only reason that record
  // is worth keeping for a viewer — the image itself cannot say, because a piece
  // nobody has written reads back as zeros exactly like a piece of genuinely
  // dark specimen.
  //
  // With no record, nothing is cleared and the picture does not show at all.
  // That is the honest behaviour rather than a failure to handle a case: a run
  // that kept no record has not told us where its picture is, and guessing would
  // mean covering the operator's plan with black rectangles for ground the
  // microscope has never visited.
  for (const region of imagedRegions(coverage)) {
    const box = onScreen(project, region);
    context.clearRect(box.left, box.top, box.width, box.height);
  }

  // And last, the things the operator is touching, which sit above everything
  // including the picture.
  if (scene.selected != null && tiles[scene.selected]) {
    const box = onScreen(project, tiles[scene.selected]);
    context.strokeStyle = "rgb(255, 214, 102)";
    context.lineWidth = 3;
    context.strokeRect(box.left, box.top, box.width, box.height);
  }
}

/**
 * The measuring instrument: a sheet with one hole cut a little larger than a
 * known square of image.
 *
 * `square` is the imaged rectangle in micrometres. `nudge`, when given, moves
 * the hole sideways by that many browser pixels — nought in every real
 * measurement, and set only to show that the check can fail. A check that has
 * never been seen to fail is not evidence of anything.
 *
 * `alsoDrawTheTileEdge` draws a thin rectangle exactly on the edge of the imaged
 * square, which is where a tile rectangle belongs. It is what the measurement of
 * the compromise arrangement reads: how far the operator's own drawing sits from
 * the edge of the picture it is supposed to be sitting on.
 */
export function drawTheMarginProbe(
  { context, width, height, project },
  { square, nudge = 0, alsoDrawTheTileEdge = false },
) {
  const box = onScreen(project, square);
  context.fillStyle = SHEET_IS_RED;
  context.fillRect(0, 0, width, height);
  // Cleared rather than filled, so that what shows through is whatever the
  // option put underneath — which is the arrangement being measured.
  context.clearRect(
    box.left - MARGIN_CSS_PX + nudge,
    box.top - MARGIN_CSS_PX,
    box.width + 2 * MARGIN_CSS_PX,
    box.height + 2 * MARGIN_CSS_PX,
  );
  if (alsoDrawTheTileEdge) {
    context.strokeStyle = OPERATOR_DRAWING_IS_GREEN;
    context.lineWidth = 2;
    context.strokeRect(box.left, box.top, box.width, box.height);
  }
  return {
    left: box.left - MARGIN_CSS_PX + nudge,
    top: box.top - MARGIN_CSS_PX,
    right: box.right + MARGIN_CSS_PX + nudge,
    bottom: box.bottom + MARGIN_CSS_PX,
  };
}

/**
 * The imaged rectangles, in micrometres, out of a coverage record.
 *
 * The record counts in voxels of the full-resolution image, because that is what
 * the writer knows; everything above this line counts in micrometres. The
 * conversion happens once, here, using the voxel size the record carries.
 */
export function imagedRegions(coverage) {
  if (!coverage || !coverage.regions) return [];
  const um = coverage.voxel_size_um || { x: 1, y: 1 };
  return coverage.regions.map((region) => ({
    x0: region.x[0] * um.x,
    x1: region.x[1] * um.x,
    y0: region.y[0] * um.y,
    y1: region.y[1] * um.y,
  }));
}
