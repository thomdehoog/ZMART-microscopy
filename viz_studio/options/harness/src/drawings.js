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
 * There are four drawings here, because the page is asked several different
 * questions.
 *
 * **The carrier** is what an operator sees in the arrangement the measurements
 * were taken in: one sheet above the picture, holding the outline of the plate or
 * slide, the wells in it, and the rectangles of the tiles they laid out, with
 * holes cut wherever the run has imaged so the picture shows through.
 *
 * **The ground beneath** and **the tiles on top** are the same scene taken apart
 * into two of the three layers `viz_studio/THE_CANVAS.md` describes. The carrier
 * and its wells belong *underneath* the acquisition, because they are fixed for
 * the run and the picture should cover them; the tiles the operator is working
 * with belong *above* it, because the moment a tile has just been imaged is
 * exactly the moment its outline matters most. Drawn this way there is no sheet
 * and there are no holes: the picture simply sits between the two.
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
 * The bottom layer: the ground the acquired picture is laid on.
 *
 * This is the application's own drawing, and it belongs *beneath* the picture
 * rather than above it. What goes here is everything that is settled before the
 * run starts and stays settled while it runs — the outline of the plate or slide,
 * the wells in it, and a pattern that makes the empty room read as room rather
 * than as a viewer that has failed to load. A tile the operator is dragging does
 * not belong here; that lives on the top layer, where nothing can cover it.
 *
 * Everything is placed in micrometres and drawn through `project`, exactly as the
 * top layer is, so the ground, the picture and the operator's marks all pan and
 * zoom together and none of them has to be lined up by hand.
 *
 * The grid is ruled in micrometres rather than in screen pixels on purpose. Ruled
 * in screen pixels it would slide about underneath the specimen as the view
 * moved, which looks wrong immediately and is the clearest possible sign that a
 * layer is not sharing the coordinate system after all.
 *
 * **Whether an operator can see any of this depends on the engine in the middle
 * layer**, and the honest answer differs between the three options. Ask the
 * viewer: `viewer.drawsUnder` says whether this drawing really ends up beneath
 * the picture, and `viewer.drawsUnderBecause` says in a sentence why. Nothing
 * here changes either way — the page draws the same shapes whichever engine is
 * underneath, which is what makes the comparison worth looking at.
 */
export function drawTheGroundBeneath({ context, project }, scene) {
  const { carrier = null, wells = [] } = scene;
  if (!carrier) return;
  const box = onScreen(project, carrier);

  // The carrier itself, as a filled shape rather than an outline, because the
  // point of a bottom layer is that there is something *there* for the picture to
  // sit on. A deep, unsaturated colour, so that the acquisition drawn over it
  // stays the brightest thing in the window.
  context.fillStyle = "rgb(18, 42, 48)";
  context.fillRect(box.left, box.top, box.width, box.height);

  // A grid ruled across the carrier, twelve squares wide, so that its lines are
  // an easy size to see at the magnification an operator opens on.
  const step = (carrier.x1 - carrier.x0) / 12;
  context.save();
  context.beginPath();
  context.rect(box.left, box.top, box.width, box.height);
  context.clip();
  context.strokeStyle = "rgba(90, 170, 180, 0.35)";
  context.lineWidth = 1;
  for (let x = carrier.x0; x <= carrier.x1 + step / 2; x += step) {
    const from = project(x, carrier.y0);
    const to = project(x, carrier.y1);
    context.beginPath();
    context.moveTo(from.x, from.y);
    context.lineTo(to.x, to.y);
    context.stroke();
  }
  for (let y = carrier.y0; y <= carrier.y1 + step / 2; y += step) {
    const from = project(carrier.x0, y);
    const to = project(carrier.x1, y);
    context.beginPath();
    context.moveTo(from.x, from.y);
    context.lineTo(to.x, to.y);
    context.stroke();
  }
  context.restore();

  // The wells, and then the outline of the carrier last so that it is not cut
  // into by the grid lines running up to it.
  context.strokeStyle = "rgba(120, 200, 210, 0.7)";
  context.lineWidth = 1;
  for (const well of wells) {
    const middle = project(well.x, well.y);
    const edge = project(well.x + well.r, well.y);
    context.beginPath();
    context.arc(middle.x, middle.y, Math.abs(edge.x - middle.x), 0, Math.PI * 2);
    context.stroke();
  }
  context.strokeStyle = "rgb(150, 220, 230)";
  context.lineWidth = 2;
  context.strokeRect(box.left, box.top, box.width, box.height);
}

/**
 * The top layer, in the three-layer arrangement: only the things the operator is
 * working with.
 *
 * The tile rectangles and whichever one is selected, and nothing else. There is
 * no sheet and there are no holes cut in anything, because in this arrangement
 * the picture is already underneath: it shows wherever it was written, without
 * anybody having to say where that is. Everything drawn here sits over the
 * picture, which is where a tile outline belongs — an operator most wants to see
 * the square they laid out at the moment its picture has just landed inside it.
 *
 * Compare `drawTheCarrier` above, which packs all of this into one sheet with
 * holes cut in it. That is what an engine that cannot show anything beneath its
 * canvas obliges an application to do, and the difference between the two is
 * worth seeing side by side.
 */
export function drawTheTilesOnTop({ context, project }, scene) {
  const { tiles = [] } = scene;
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
  if (scene.selected != null && tiles[scene.selected]) {
    const box = onScreen(project, tiles[scene.selected]);
    context.strokeStyle = "rgb(255, 214, 102)";
    context.lineWidth = 3;
    context.strokeRect(box.left, box.top, box.width, box.height);
  }
}

/**
 * How thick the ring drawn beneath the picture is, in the browser's own pixels.
 *
 * Only wide enough to be found reliably in a photograph. It matters that the
 * ring stays *inside* the rectangle the engine is given to draw in: an engine
 * that cannot show anything beneath its canvas must then show none of this ring
 * at all, and the reading comes out as "there was nothing of the bottom layer on
 * screen to measure", which is the honest answer. A ring drawn wide enough to
 * spill outside the engine's rectangle would be seen around the edge of it and
 * would be measured as though the engine had let it through, which would be
 * quite untrue. The engine is given sixty-four browser pixels of slack around
 * the imaged ground, and the outside of this ring falls at fifty-six.
 */
export const RING_CSS_PX = 16;

/**
 * The measuring instrument for the **bottom** layer: a rectangle of colour
 * framing the imaged square, drawn underneath the picture.
 *
 * It asks the same question as the margin probe above and is read by the same
 * program, `viz_studio/tests/margins.py`, without a line of change. The shapes
 * are arranged so that a cut across the photograph meets the same four things in
 * the same order: the ring, then a band of background, then the picture, then a
 * band of background, then the ring again. If the layer beneath and the picture
 * are lined up, the two bands are equal and stay equal however the view is
 * panned, zoomed or thrown about. If they come apart, one side goes thick and
 * the other thin, by exactly as much.
 *
 * `square` is the imaged rectangle in micrometres. `nudge` moves the ring
 * sideways by that many browser pixels — nought in every real measurement, and
 * set only to show that the reading can go the other way. A check that has never
 * been seen to fail is not evidence of anything.
 */
export function drawTheMarginRingBeneath({ context, project }, { square, nudge = 0 }) {
  const box = onScreen(project, square);
  const inner = MARGIN_CSS_PX;
  const outer = MARGIN_CSS_PX + RING_CSS_PX;
  context.fillStyle = SHEET_IS_RED;
  context.fillRect(
    box.left - outer + nudge,
    box.top - outer,
    box.width + 2 * outer,
    box.height + 2 * outer,
  );
  // Cleared rather than filled, so that what shows inside the ring is the page's
  // own colour and the picture the engine draws over it — which is the whole
  // arrangement being measured.
  context.clearRect(
    box.left - inner + nudge,
    box.top - inner,
    box.width + 2 * inner,
    box.height + 2 * inner,
  );
}

/**
 * Fill a whole slot with one flat colour.
 *
 * Not a picture of anything — this is what the measurement of the bottom layer
 * paints, and it is deliberately the dullest possible drawing. One saturated
 * colour covering the window can be counted in a photograph without any
 * judgement about what counts as a line or an outline, so the reading is "what
 * share of the window is this colour" and nothing more.
 *
 * It is used for both slots in turn, which is the whole of the check that the
 * reading means what it says: the same colour, the same drawing function, put in
 * the other slot, must fill the window in every option.
 */
export function fillTheSlot({ context, width, height }, colour) {
  context.fillStyle = colour;
  context.fillRect(0, 0, width, height);
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
