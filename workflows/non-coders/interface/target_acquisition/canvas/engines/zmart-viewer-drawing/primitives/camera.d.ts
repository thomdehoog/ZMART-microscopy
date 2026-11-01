/**
 * Where the view looks, in micrometres, and what of the
 * picture is on screen.
 *
 * The engine counts its position in its own units per axis and its zoom per
 * canonical voxel; a page thinks in micrometres. These are the two worlds'
 * exchange, written once.
 */
import type { RenderViewport } from "neuroglancer/unstable/display_context.js";
import type { Viewer } from "neuroglancer/unstable/viewer.js";
/**
 * Where the view is looking: the position by axis name in micrometres, and
 * both zooms as so many micrometres to a screen pixel (the volume's across the
 * height of its panel, as the engine counts it). Kept by name rather than by
 * axis number so it can be put back on an engine built afresh, whose axes may
 * arrive in another order.
 */
export interface Camera {
    positionUm: Record<string, number>;
    zoomUm: number;
    perspectiveZoomUm: number;
}
/** Where the view is looking now, or null while it has no axes to say it by. */
export declare function captureCamera(viewer: Viewer): Camera | null;
/** Put the view where `camera` says; an axis it does not name stays put. */
export declare function restoreCamera(viewer: Viewer, camera: Camera): void;
/**
 * The drawing areas of the flat panel and of the volume panel, where each is on
 * screen. A panel is told apart by what it draws: one slice, or several.
 */
export declare function panelsOnScreen(viewer: Viewer): {
    flat: RenderViewport | null;
    volume: RenderViewport | null;
};
/**
 * Which part of the picture is on screen, as fractions of its own bounds:
 * `[[top, left], [bottom, right]]`.
 *
 * Given as fractions rather than as voxels because that is the form a server
 * can use without knowing anything about how the view is arranged: "measure
 * the brightness of this share of the picture" means the same whatever the
 * zoom happens to be expressed in. How many of the picture's own units a
 * screen pixel covers is the zoom divided by the engine's factor for that
 * axis, so half the panel's width in units is half its pixels times that.
 *
 * ``null`` where the picture has not said how big it is yet, or where the view
 * is not a flat one: a volume is turned in three dimensions and "which
 * rectangle is on screen" has no honest answer there.
 */
export declare function whatIsOnScreen(viewer: Viewer): [[number, number], [number, number]] | null;
