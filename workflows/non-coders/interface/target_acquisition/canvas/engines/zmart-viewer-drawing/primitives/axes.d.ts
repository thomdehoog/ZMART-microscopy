/**
 * The axes: which ones are drawn, where along one the view stands, and how to
 * step it.
 *
 * An image says what each of its axes measures. Some are distances --
 * depth, height, width -- and some are not: which moment this is,
 * or which colour of light was recorded. Only the first kind belongs on
 * screen; the others are stepped. Which is which is read from the units an
 * image declares, never guessed from names.
 */
import type { Viewer } from "neuroglancer/unstable/viewer.js";
/**
 * Draw the axes that measure distance, and keep drawing them as the picture's
 * axes change. Returns a function that stops keeping them.
 *
 * Left alone, the engine takes the first three axes the image declares, in the
 * order they were written. For an image of a single moment those happen to be
 * depth, height and width and everything looks right -- which is exactly what
 * made this hard to see. Add a time axis at the front, as every image over
 * time has, and the engine draws time against depth and pins width, so the
 * picture is nowhere on screen. Nothing reports a fault; the picture is simply black.
 */
export declare function keepSpatialAxes(viewer: Viewer): () => void;
/**
 * Hand the engine the axes measured in metres, width first and depth last.
 *
 * "m" is the only unit that measures distance across a picture; seconds do
 * not, and an axis with no unit does not. The *order* matters as much: the
 * engine decides what goes across the window, what down it and what into the
 * screen from this order and the panel layout together, and the layout a page
 * asks for (`xy`) expects width, height, depth. An OME-Zarr image lists its
 * distance axes slowest-changing first -- depth, height, width -- so they are
 * reversed. The other way round, the picture was a mirror image of the
 * data and nothing said so (the viewer's
 * `tests/test_the_picture_is_not_mirrored.py` measures it).
 *
 * An image declaring fewer than two such axes is left alone: replacing a
 * possibly-odd view with a certainly-wrong one is not an improvement.
 */
export declare function pinTheAxesThatMeasureDistance(viewer: Viewer): void;
/** One axis of the picture: where it can be stepped, and where the view stands. */
export interface AxisReading {
    index: number;
    /** The first and last step there is room for. */
    min: number;
    max: number;
    value: number;
    /** How many micrometres one step is. */
    unitUm: number;
}
/**
 * Read one named axis: where it can be stepped, and where the view stands on
 * it. Null when the picture has no such axis -- the normal answer for `t` on
 * anything not recorded over time.
 *
 * The engine describes an axis by the real-valued extent the data covers, and
 * says separately whether a whole step sits *on* an integer coordinate or half
 * way between two. Both conventions occur, and a step has to land exactly on
 * the planes that exist -- one too few and the last plane of every stack is
 * unreachable, one too many and the view runs off the end of the data. When
 * centres are on integers the extent comes back shifted by half a step (a
 * 48-plane stack reads -0.5 to 47.5), so the steps are the integers inside it;
 * otherwise they are the half-integers inside it.
 */
export declare function readTheAxis(viewer: Viewer | null, name: string): AxisReading | null;
/** Move the view along one axis to `value`, leaving every other axis where it is. */
export declare function moveAlong(viewer: Viewer, index: number, value: number): void;
/**
 * Open a picture over time at its first moment rather than half way through.
 *
 * The engine opens every axis in the middle, which is right for depth and
 * wrong for time: a recording is watched from the beginning, and a store still
 * being written declares room for moments not yet written, so its middle is a
 * black screen with the data sitting unseen at the start. The time axis is
 * the one measured in seconds.
 */
export declare function startTimeAtTheFirstMoment(viewer: Viewer): void;
