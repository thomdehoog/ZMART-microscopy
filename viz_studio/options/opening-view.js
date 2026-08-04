/**
 * The view an acquisition opens on, before anybody has said where to look.
 *
 * Shared by every option, the way `gestures.js` and `planes.js` are, and for the
 * same reason: it is not a property of a drawing engine. Where a picture starts
 * is a fact about the run and the box it is being drawn in, and three options
 * answering it differently is three different first impressions of one
 * acquisition.
 *
 * ## The rule
 *
 * **Show all of it.** Centred on the acquisition, and magnified so that the whole
 * of it fits inside the box.
 *
 * ## Why it is written down rather than left to the engines
 *
 * They do not agree, and the disagreement is large enough to change what an
 * operator thinks they are looking at. Viv fits the acquisition to its box.
 * Neuroglancer opens at one voxel to one screen pixel, which on a 1.1 µm
 * light-sheet store is about twenty times closer — the operator lands somewhere
 * inside the specimen at full magnification, with nothing on screen to say where,
 * and has to zoom out before the run means anything.
 *
 * The operator page hid that for a while by opening two engines side by side and
 * putting both on whichever view was reported first. That worked because there
 * were two of them to reconcile. With one viewer and a button to change the
 * engine underneath it, there is nothing to reconcile against — so the rule has
 * to be stated rather than inferred, or the same run opens at two magnifications
 * depending on which engine happens to be drawing.
 *
 * ## Centred on the acquisition, not on the stage
 *
 * A run written some way along the stage would otherwise open looking at the
 * empty room beside it. The centre is therefore measured from where the
 * acquisition says it begins.
 */

/** Below this a magnification stops being a number and starts being a division. */
const THE_SMALLEST_USEFUL_ZOOM = 1e-6;

/**
 * @param {{atUm: {x: number, y: number}, wideUm: number, tallUm: number}} extent
 *   where the acquisition begins on the stage and how much ground it covers.
 * @param {{width: number, height: number}} box the drawing surface, in pixels.
 * @returns {{centre: {x: number, y: number}, zoom: number}|null} the view, in the
 *   units every option speaks — micrometres, and micrometres to the screen pixel
 *   — or nothing when the acquisition has no size to show, in which case the
 *   caller keeps whatever it would have done.
 */
export function theViewThatShowsAllOf(extent, box) {
  const wideUm = extent?.wideUm ?? 0;
  const tallUm = extent?.tallUm ?? 0;
  if (!(wideUm > 0) || !(tallUm > 0)) return null;
  const width = Math.max(box?.width ?? 0, 1);
  const height = Math.max(box?.height ?? 0, 1);
  return {
    centre: {
      x: (extent.atUm?.x ?? 0) + wideUm / 2,
      y: (extent.atUm?.y ?? 0) + tallUm / 2,
    },
    /* The larger of the two ratios, so that the long side is what fits: taking
       the smaller would fit one side and run the other off the edges, which is
       the same failure as not fitting at all. */
    zoom: Math.max(wideUm / width, tallUm / height, THE_SMALLEST_USEFUL_ZOOM),
  };
}
