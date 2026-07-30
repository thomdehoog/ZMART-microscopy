/**
 * The margin test: a square of image, a hole cut a little larger around it, and
 * a band of nothing in between whose width is the whole measurement.
 *
 * ## What is being asked
 *
 * Two drawing surfaces stacked on top of one another cannot be handed to the
 * screen in the same instant. If the top one follows the mouse while the bottom
 * one draws on its own schedule, the picture slides out from under the outlines
 * drawn over it — and it does so silently, because nothing errors when two
 * pictures disagree about where they are.
 *
 * So: draw a square of real acquired image on the bottom surface, and on the top
 * surface cut a rectangular hole that is a little *larger* than that square and
 * centred on it. What you then see, from the middle outwards, is the image, then
 * a band of the bottom surface's own background showing through the hole, then
 * the top surface framing the lot. The width of that band on each of the four
 * sides is what gets measured.
 *
 * The reason this is a good measurement is that the right answer is "unchanged".
 * A view that has been panned, zoomed and thrown about should give the same four
 * numbers throughout. So there is no scale to interpret and no threshold to
 * argue about: any disagreement between the two surfaces turns into the margins
 * becoming *uneven*, and which way they go says what went wrong.
 *
 *   - One side thick and the opposite side thin means the top surface is drawn
 *     from a position the bottom surface has not reached yet. That is a
 *     follower lagging behind, and it is what a pan produces.
 *   - All four growing or shrinking together means the two disagree about
 *     magnification rather than position.
 *
 * It also survives being run on a machine with no graphics card. Software
 * rendering changes *when* a frame appears, which changes how often we can
 * sample, but a margin that is uneven within a single captured frame is the
 * fault itself and no amount of slowness invents one.
 *
 * ## The three colours, and why they must differ here and must not in the viewer
 *
 * The measurement needs to tell three things apart in a photograph: the acquired
 * image, the bottom surface's background, and the top surface. So they are given
 * three colours that no amount of compression could confuse — near-white,
 * saturated blue, saturated red.
 *
 * **In the finished viewer the background is meant to match the page, so that
 * the seam between the two surfaces cannot be seen at all.** That is the whole
 * point of the arrangement: the operator should never be able to tell there are
 * two surfaces. Making them the same colour here would make the margin
 * invisible and the measurement impossible, which is why they are different —
 * and it is *only* why. Please do not "fix" these colours to match each other.
 * If you do, this test will go on passing while measuring nothing.
 */

// The three colours. Written as plain numbers as well as CSS text because the
// reading half of this test, in Python, has to recognise them in a photograph.
export const IMAGE_IS_NEARLY_WHITE = [255, 255, 255];
export const ENGINE_BACKGROUND_IS_BLUE = "#0000ff";
export const OVERLAY_IS_RED = "rgb(220, 0, 0)";
// A thing the operator drew that is supposed to sit exactly on the edge of an
// imaged tile. Green so it cannot be mistaken for any of the three above.
export const OPERATOR_DRAWING_IS_GREEN = "rgb(0, 220, 0)";

/**
 * How much wider than the square the hole is cut, on each side, in the browser's
 * own pixel units.
 *
 * Measured in *screen* units rather than in specimen units on purpose. Cut in
 * specimen units, the band would honestly grow as the operator zoomed in, and
 * "the margins changed" would then mean two quite different things. Held at a
 * fixed number of screen pixels, the right answer is the same number at every
 * magnification, so a magnification that has drifted shows up immediately as all
 * four margins moving together.
 *
 * Forty is comfortably wider than the drift a real gesture produces, which
 * matters for a reason that is easy to miss: once the drift exceeds the margin,
 * the sheet has covered the edge of the image and the band on that side is gone
 * altogether. There is then nothing left to measure, and a measurement that
 * quietly reported "no band" would be hiding the worst readings rather than the
 * best ones. The reading half of this test says plainly when that has happened.
 */
export const MARGIN_CSS_PX = 40;

/**
 * Where a rectangle of specimen lands on the screen, given a view.
 *
 * A view is three numbers: where the middle of the window is in the specimen's
 * own coordinates (``cx``, ``cy``, in voxels), and how much specimen one screen
 * pixel covers (``scale``, in voxels per pixel). Everything drawn over the image
 * is placed with this one function, so there is exactly one place where the
 * conversion between the operator's coordinates and the screen can be wrong.
 */
export function toScreen(view, size, worldRect) {
  const { cx, cy, scale } = view;
  return {
    left: size.width / 2 + (worldRect.x0 - cx) / scale,
    top: size.height / 2 + (worldRect.y0 - cy) / scale,
    right: size.width / 2 + (worldRect.x1 - cx) / scale,
    bottom: size.height / 2 + (worldRect.y1 - cy) / scale,
  };
}

/** The hole to cut: the square's place on screen, opened out by the margin. */
export function holeFor(view, size, worldRect, margin = MARGIN_CSS_PX) {
  const square = toScreen(view, size, worldRect);
  return {
    left: square.left - margin,
    top: square.top - margin,
    right: square.right + margin,
    bottom: square.bottom + margin,
  };
}

/**
 * The operator's own drawing surface: an opaque sheet with a hole in it.
 *
 * It is a plain two-dimensional canvas rather than anything clever, because that
 * is what the operator's layer really is — a handful of shapes redrawn as often
 * as the mouse moves. The one thing it does carefully is take the screen's pixel
 * density into account: the sheet is made that many times larger in real pixels
 * and then everything is drawn in browser pixel units, so a screen that packs
 * one and a half real pixels into each browser pixel gets a crisp edge rather
 * than a blurred one. Getting that wrong is the classic version of this bug and
 * it is invisible at a density of exactly one.
 */
export class OverlaySheet {
  constructor(canvas) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d");
    this.draws = 0;
    this.lastHole = null;
    this.resize();
  }

  resize() {
    const density = window.devicePixelRatio || 1;
    const width = this.canvas.clientWidth;
    const height = this.canvas.clientHeight;
    this.canvas.width = Math.round(width * density);
    this.canvas.height = Math.round(height * density);
    this.size = { width, height, density };
  }

  /**
   * Draw the sheet once.
   *
   * ``hole`` is the rectangle to leave open, and it is the thing that has to
   * register with the image underneath. ``operatorRect``, when given, is
   * something the operator drew that is meant to sit exactly on the edge of the
   * imaged square — a tile rectangle, in the real viewer. Giving it separately is
   * what lets one of them follow the engine's last drawn frame while the other
   * follows the mouse, which is the compromise this project is weighing up.
   */
  paint(hole, operatorRect = null) {
    const { width, height, density } = this.size;
    const ctx = this.context;
    ctx.setTransform(density, 0, 0, density, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = OVERLAY_IS_RED;
    ctx.fillRect(0, 0, width, height);
    if (hole) {
      // Cleared rather than filled, so that what shows through the hole is
      // whatever surface is underneath — which is the arrangement being tested.
      ctx.clearRect(
        hole.left,
        hole.top,
        hole.right - hole.left,
        hole.bottom - hole.top,
      );
      this.lastHole = { ...hole };
    }
    if (operatorRect) {
      ctx.strokeStyle = OPERATOR_DRAWING_IS_GREEN;
      ctx.lineWidth = 2;
      ctx.strokeRect(
        operatorRect.left,
        operatorRect.top,
        operatorRect.right - operatorRect.left,
        operatorRect.bottom - operatorRect.top,
      );
    }
    this.draws += 1;
  }
}
