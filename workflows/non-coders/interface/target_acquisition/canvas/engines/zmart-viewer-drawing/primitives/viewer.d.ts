/**
 * The engine itself: made here with its own interface switched off, told here
 * how the view is set, and dropped here with everything it held.
 *
 * Two pages draw with neuroglancer and both turn its interface off: the
 * viewer's own window and the page of ZMART-interface. Each owns its
 * controls and tells the engine the values; this is the engine's side of that,
 * once. What it draws is kept in step by `sync.ts`, which the handle carries.
 */
import "neuroglancer/unstable/util/polyfills.js";
import "neuroglancer/unstable/layer/enabled_frontend_modules.js";
import "neuroglancer/unstable/datasource/enabled_frontend_modules.js";
import "neuroglancer/unstable/kvstore/enabled_frontend_modules.js";
import type { Viewer } from "neuroglancer/unstable/viewer.js";
import "neuroglancer/unstable/ui/default_viewer.css";
import "./chrome.css";
import type { LayerSync, OwnSettings } from "./sync.ts";
/**
 * Who answers the hands of whoever is looking.
 *
 * `"engine"`: the engine's own panels, with exactly the gestures written out
 * below -- drag pans the flat view and turns the volume, the wheel zooms, and
 * the drawing family neuroglancer's annotation tools ride on. `"none"`: every
 * table emptied, for a page that lays its own surface over the engine and
 * moves the view itself.
 */
export type Gestures = "engine" | "none";
/** How a page makes its engine. */
export interface EngineOptions {
    gestures?: Gestures;
    /**
     * The colour of the ground -- the canvas where no data is drawn -- or a way
     * to read it, for a page whose ground follows its theme.
     */
    ground?: string | (() => string);
    /** How the page writes the settings of a layer of its own kind; see `PageLayer`. */
    ownSettings?: OwnSettings;
}
/**
 * The parts of the view that are not layers: which panels, whether the engine
 * draws its own furniture, and whether the flat view's empty ground is left
 * see-through for whatever the page draws beneath it.
 */
export interface ViewSettings {
    layout: string;
    chrome: boolean;
    transparentBackground?: boolean;
}
/** One engine, as a page holds it. Everything it keeps is dropped by `dispose`. */
export interface Engine extends LayerSync {
    viewer: Viewer;
    /** How many stores the page has still to hand the engine; see `feeding.ts`. */
    sourcesStillWaiting(): number;
    /** Set the parts of the view that are not layers. */
    setView(settings: ViewSettings): void;
    /** Paint the ground again, for a page whose ground has just changed. */
    paintTheGround(): void;
    dispose(): void;
}
/**
 * Create the neuroglancer viewer inside ``target`` (an empty element), with
 * every one of neuroglancer's own buttons and panels switched off.
 *
 * It owns the viewer's *lifetime* (create it here, drop it through the returned
 * ``dispose``) but NOT what the viewer *shows*. Which layers, which layout, the
 * brightness, the z-position: all of that comes from the page, through the
 * handle's `syncLayers` and `setView` and through the camera and axes
 * functions beside this file. That split is what lets any page build its
 * controls without touching this function.
 */
export declare function createViewer(target: HTMLElement, { gestures, ground, ownSettings }?: EngineOptions): Engine;
