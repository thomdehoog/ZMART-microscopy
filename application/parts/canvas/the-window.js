/**
 * One brightness window, described the two ways a microscopist describes it.
 *
 * A channel is drawn through a *window*: everything dimmer than its low edge
 * comes out black, everything brighter than its high edge comes out at full
 * strength, and what lies between is spread across the shades in between. That
 * is one setting, and there is only ever one of it.
 *
 * There are two ways of saying where it is, and both are worth having.
 *
 * - **min and max** say where the two edges are, in the numbers the camera
 *   actually produced. This is the exact way, and it is what a store records.
 * - **brightness and contrast** say how bright the middle of the window is and
 *   how tightly it is drawn around that middle. This is the way Fiji, ImageJ
 *   and every microscope's own software have presented it for twenty years,
 *   and it is the pair most people reach for first.
 *
 * They are not two settings. Moving either pair moves the other, because
 * underneath there is only one window. This file is that translation, kept
 * apart from the panel so it can be read and checked on its own; the panel
 * simply asks it what window a control now means and passes that on to the
 * viewer. The arithmetic follows the ZMART viewer's own
 * `viz_studio/frontend/src/LayerPanel.jsx`, so both panels behave the same.
 */

/**
 * Brightness and contrast, as whole numbers out of a hundred, for one window.
 *
 * `track` is the stretch of brightness the sliders are allowed to travel over —
 * in the panel that is the axis the histogram is drawn on, so the numbers mean
 * something in terms of the picture the operator is looking at rather than in
 * terms of what a camera could theoretically produce.
 *
 * **Brightness runs backwards on purpose.** Pulling the window down towards the
 * dark end makes the picture *brighter*, because more of the image then lands
 * above the window and is drawn at full strength. That is how every other image
 * tool behaves, and a slider that went the other way would feel wrong to
 * everybody who has used one.
 *
 * **Contrast counts how tight the window is.** A window as wide as the whole
 * track is nought contrast — every shade in the picture is spread thinly over
 * the screen. A very narrow window is close to a hundred: a small range of
 * brightness fills the whole screen, so small differences become visible.
 */
export function howBrightAndHowTight(window_, track) {
  const across = Math.max(1, track.high - track.low);
  const middle = (window_.low + window_.high) / 2;
  const width = Math.max(1, window_.high - window_.low);
  return {
    brightness: Math.round((1 - (middle - track.low) / across) * 100),
    contrast: Math.round((1 - width / across) * 100),
  };
}

/** A window of the given width, centred on the given brightness. */
function centredOn(centre, width) {
  const half = Math.max(0.5, width / 2);
  return { low: centre - half, high: centre + half };
}

/**
 * The window that a given brightness means, keeping the width it already has.
 *
 * Brightness slides the whole window along the track without changing how wide
 * it is, which is what "the picture is brighter" means: the same range of
 * values is being shown, just a different part of the range.
 */
export function theWindowThisBrightnessMeans(window_, track, brightness) {
  const across = Math.max(1, track.high - track.low);
  const width = Math.max(1, window_.high - window_.low);
  return centredOn(track.low + (1 - brightness / 100) * across, width);
}

/**
 * The window that a given contrast means, keeping the middle it already has.
 *
 * Contrast draws the window in around its middle, so the picture keeps the same
 * overall brightness while small differences within it grow.
 */
export function theWindowThisContrastMeans(window_, track, contrast) {
  const across = Math.max(1, track.high - track.low);
  const middle = (window_.low + window_.high) / 2;
  return centredOn(middle, Math.max(1, (1 - contrast / 100) * across));
}
