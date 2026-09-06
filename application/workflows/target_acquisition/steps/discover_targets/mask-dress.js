/**
 * How a field's mask is worn on a picture.
 *
 * A detection mask arrives as one picture per field, every object in a
 * colour of its own. What the operator sees of it is a matter of dress:
 * filled or outline only, each object's own colour or one colour for all,
 * and how strongly it sits on the image. The tile test and the canvas both
 * dress a mask through this one function, so the two never disagree about
 * what "Line" or "yellow" looks like.
 *
 * Opacity is not applied here: it is the drawing's `globalAlpha`, set where
 * the dressed mask is painted, so one dressed mask serves every opacity.
 */

/**
 * Dress a mask picture, at `size` pixels square.
 *
 * `colour` is a `#rrggbb` string for one colour over every object, or null
 * to keep each object's own. `mode` is "fill" or "line"; anything else is
 * treated as fill, so a tile test's "off" cannot leave the canvas blank.
 */
export function dressTheMask(mask, { size, colour = null, mode = "fill" }) {
  const cv = document.createElement("canvas");
  cv.width = size;
  cv.height = size;
  const paint = cv.getContext("2d");
  /* Honest pixels: a mask shown larger than it was made keeps its own
     blocks rather than a smoothed guess at an edge nobody drew. */
  paint.imageSmoothingEnabled = false;
  paint.drawImage(mask, 0, 0, size, size);
  if (colour) {
    /* One colour laid through the mask's own shape: the fill lands only
       where the mask has pixels, and keeps their transparency. */
    paint.globalCompositeOperation = "source-in";
    paint.fillStyle = colour;
    paint.fillRect(0, 0, size, size);
    paint.globalCompositeOperation = "source-over";
  }
  if (mode === "line") {
    /* The rim is the mask minus its own eroded self. Erode first --
       destination-in against four shifted copies keeps only the pixels
       covered from every direction, the interior -- then punch that
       interior out of the full mask. Punching with shifted copies directly
       erased the rim too: every edge pixel is covered by the copy shifted
       into its object, and four directions cover them all. */
    const eroded = document.createElement("canvas");
    eroded.width = size;
    eroded.height = size;
    const ep = eroded.getContext("2d");
    ep.drawImage(cv, 0, 0);
    ep.globalCompositeOperation = "destination-in";
    for (const [dx, dy] of [[2, 0], [-2, 0], [0, 2], [0, -2]]) {
      ep.drawImage(cv, dx, dy);
    }
    paint.globalCompositeOperation = "destination-out";
    paint.drawImage(eroded, 0, 0);
    paint.globalCompositeOperation = "source-over";
  }
  return cv;
}

/** The colours a mask can be worn in: null is each object's own. */
export const MASK_COLOURS = [
  null, "#ffffff", "#ffd400", "#00e5ff", "#ff3fd1", "#3dff6a", "#ff4444", "#4c8dff",
];

/** How "each object its own colour" is shown on a swatch. */
export const MASK_RAINBOW =
  "conic-gradient(#ff5c7a, #ffb340, #ffe066, #6be585, #4fd1ff, #8f7bff, #ff5c7a)";
