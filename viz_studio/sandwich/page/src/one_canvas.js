/**
 * The control: both layers inside one canvas, drawn in one pass from one view.
 *
 * This is the other arrangement on the table — the acquired image as a layer
 * *inside* the canvas the application owns, rather than in a second canvas
 * underneath it. Registration there is exact by construction: there is one view
 * to be drawn from and one turn in which to draw, so the picture and the
 * outlines over it cannot possibly disagree.
 *
 * That is exactly why it is worth measuring. **This arrangement must come out at
 * zero.** If the same measurement, the same photographs and the same gestures
 * find drift here, then the drift is the measurement's own and every number
 * taken on the two-canvas arrangement is worthless. It is the same discipline as
 * deliberately breaking a test to prove it can fail, applied to the instrument
 * rather than to the thing being measured.
 *
 * The image drawn here is the acquired square itself, read back out of the store
 * this project's writer produced and served as a picture. It is not being read
 * through the same reader the real Option A would use — whether that reader can
 * read what we write was settled separately, and is written up in
 * `viz_studio/DRAWING_ENGINES.md`. What is being reproduced here is the property
 * that matters to *this* question: one canvas, one view, one pass.
 */

import { Deck, OrthographicView } from "@deck.gl/core";
import { BitmapLayer, SolidPolygonLayer } from "@deck.gl/layers";
import { MARGIN_CSS_PX, OVERLAY_IS_RED } from "./margin_probe.js";

const RED = [220, 0, 0, 255];
const BLUE = [0, 0, 255, 255];

/**
 * Build the single-canvas arrangement.
 *
 * ``worldRect`` is where the acquired square sits in the specimen's coordinates,
 * and ``imageUrl`` is a picture of that square. ``getView`` is asked for the
 * current view every time something is redrawn, so that the image and the sheet
 * over it are laid out from one reading of it rather than two.
 */
export function startOneCanvas(canvas, { worldRect, imageUrl }) {
  const deck = new Deck({
    canvas,
    views: [new OrthographicView({ flipY: true })],
    controller: false,
    // The background showing around the image, and the third of the three
    // colours the margin test needs to tell apart. It is a colour of its own
    // only so that the margin can be seen; see `margin_probe.js`.
    parameters: { clearColor: [0, 0, 1, 1] },
    initialViewState: { target: [0, 0, 0], zoom: 0 },
  });

  let lastHole = null;

  const draw = (view, size) => {
    // Everything below is worked out from this one reading of the view. That is
    // the whole of what makes this arrangement exact, and it is why the reading
    // is taken once here rather than inside each layer.
    const zoom = -Math.log2(view.scale);
    const marginInWorld = MARGIN_CSS_PX * view.scale;
    const hole = {
      x0: worldRect.x0 - marginInWorld,
      y0: worldRect.y0 - marginInWorld,
      x1: worldRect.x1 + marginInWorld,
      y1: worldRect.y1 + marginInWorld,
    };
    // The sheet has to cover the window whatever the view, so its outer edge is
    // taken generously wide rather than fitted exactly.
    const reach = Math.max(size.width, size.height) * view.scale;
    const outside = {
      x0: view.cx - reach,
      y0: view.cy - reach,
      x1: view.cx + reach,
      y1: view.cy + reach,
    };
    deck.setProps({
      viewState: { target: [view.cx, view.cy, 0], zoom },
      layers: [
        new SolidPolygonLayer({
          id: "background",
          // The background the acquisition sits on, drawn as the bottom layer
          // rather than as the canvas's clear colour. It has to be a layer here
          // because everything in this arrangement must go through the one
          // drawing pass — a background painted by anything else would be a
          // second surface, which is the very thing this control exists not to
          // have. It is a colour of its own only so the margin can be seen; see
          // `margin_probe.js`.
          data: [
            {
              polygon: [
                [outside.x0, outside.y0],
                [outside.x1, outside.y0],
                [outside.x1, outside.y1],
                [outside.x0, outside.y1],
              ],
            },
          ],
          getPolygon: (d) => d.polygon,
          getFillColor: BLUE,
          filled: true,
        }),
        new BitmapLayer({
          id: "acquisition",
          image: imageUrl,
          bounds: [worldRect.x0, worldRect.y1, worldRect.x1, worldRect.y0],
        }),
        new SolidPolygonLayer({
          id: "operator-sheet",
          data: [
            {
              // An outer ring with a second ring inside it is how a shape with a
              // hole in it is described. The hole is where the acquisition shows
              // through, and its edges are the thing that has to register.
              polygon: [
                [
                  [outside.x0, outside.y0],
                  [outside.x1, outside.y0],
                  [outside.x1, outside.y1],
                  [outside.x0, outside.y1],
                ],
                [
                  [hole.x0, hole.y0],
                  [hole.x1, hole.y0],
                  [hole.x1, hole.y1],
                  [hole.x0, hole.y1],
                ],
              ],
            },
          ],
          getPolygon: (d) => d.polygon,
          getFillColor: RED,
          filled: true,
        }),
      ],
    });
    lastHole = {
      left: size.width / 2 + (hole.x0 - view.cx) / view.scale,
      top: size.height / 2 + (hole.y0 - view.cy) / view.scale,
      right: size.width / 2 + (hole.x1 - view.cx) / view.scale,
      bottom: size.height / 2 + (hole.y1 - view.cy) / view.scale,
    };
  };

  return { deck, draw, holeNow: () => lastHole, colour: OVERLAY_IS_RED };
}
