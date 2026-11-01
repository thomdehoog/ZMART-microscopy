/**
 * What a page tells the engine to draw: one description per layer, and the one
 * rule for how layers meet.
 *
 * A page owns its controls -- which channels show, their colours, their
 * windows -- and turns them into these descriptions; the primitives turn the
 * descriptions into the engine's layers (see `sync.ts`). Nothing here touches
 * the engine or the browser, so a plain Node process can check it.
 *
 * The rule (Thom, 2026-10-18): the channels of one place always mix -- their
 * coloured brightnesses are added -- and where two places of one group cover
 * the same ground, the one that came in last covers the other. In a picture
 * already composed into one store, its channels live together and its places
 * were laid down in that order (or averaged, when a page asks for it), so
 * every layer simply adds. Only a channel drawn straight from several stores
 * needs more: `coverPlacesMixChannels` gives each place its own ground to
 * stand on.
 */
/** How the volume is drawn: a projection of the brightest or the dimmest voxel, or accumulated. */
export type VolumeMode = "max" | "on" | "min";
/**
 * One image layer as the engine is told to draw it: neuroglancer's own layer
 * description, plus the few fields the primitives read to know which stores
 * have changed and how a layer is held (neuroglancer ignores those).
 */
export interface EngineLayer {
    type: "image";
    name: string;
    /** Whole addresses, scheme included: the primitives never work one out. */
    source: string[];
    visible?: boolean;
    persistentFlat?: boolean;
    boundaryHeld?: boolean;
    frameCounts?: number[];
    sourceIds?: string[];
    sourceRevisions?: number[];
    sourceGeometryRevisions?: number[];
    localPosition?: number[];
    shader?: string;
    shaderControls?: Record<string, unknown>;
    blend?: "additive" | "default";
    opacity?: number;
    volumeRendering?: VolumeMode;
    volumeRenderingDepthSamples?: number;
    volumeRenderingGain?: number;
}
/**
 * A layer of a kind only one page draws -- an annotation layer, a mask. The
 * primitives build it from its description, hand it its stores as they
 * arrive, put it in its place in the order and show or hide it; every other
 * setting is the page's own, written by the page's hook (see `createViewer`'s
 * `ownSettings`).
 */
export interface PageLayer {
    type: string;
    name: string;
    source: string | string[];
    visible?: boolean;
}
/** One layer of the scene a page asks for. */
export type SceneLayer = EngineLayer | PageLayer;
/** Whether a description is an image layer, the one kind the primitives write settings for. */
export declare function isEngineLayer(layer: SceneLayer): layer is EngineLayer;
/** One channel of one group, drawn from one store or several. */
export interface ChannelRow {
    layer: EngineLayer;
    /**
     * Which place each store shows, in the order of `layer.source`. Stores of
     * different channels that show the same place carry the same name. Left
     * out, each store is its own place, and stores shared between rows (one
     * store holding several channels) are the same place.
     */
    places?: readonly string[];
    /** Where each store's coverage is read, when the page knows which of its ground holds data. */
    coverage?: readonly string[];
}
/**
 * The ground a layer stands on: black wherever its coverage says there is
 * data, covering what lies beneath. One coverage store per image store, so the
 * layer count does not grow with places.
 */
export declare function coverageLayerFor(layer: EngineLayer, coverage: readonly string[], blend: "additive" | "default"): EngineLayer;
/**
 * Whether some of these rows are drawn straight from several stores while the
 * group has more than one channel -- the one case where adding layers would
 * also add overlapping places into a bright seam, and covering would hide every
 * channel but the top one.
 */
export declare function needsAGroundPerPlace(rows: readonly ChannelRow[]): boolean;
/**
 * Draw a group's channels place by place: each place stands on its own
 * black ground, which covers whatever was drawn before it, and its channels
 * are added on top of that ground.
 *
 * Neuroglancer blends a layer's stores one pass at a time with the layer's own
 * blend, so a layer cannot add its channels and cover its places at once.
 * Split by place, it can: the ground covers, the channels add. The places are
 * drawn in the order they first appear in the rows -- the order the stores
 * came in -- so the last one covers. A place's ground is drawn from its
 * coverage store where the page has one, and from its first store otherwise.
 *
 * The cost is layers: one per place for the ground and one per channel and
 * place. A folder the viewer can compose into one picture never comes here.
 *
 * The first place's channels keep their rows' own names, so a row that was
 * drawn from one store and gains a second -- stores arriving one at a time
 * while something is still writing -- keeps the layer it had, with everything fetched for it, and only the new
 * place's layers are built.
 */
export declare function coverPlacesMixChannels(rows: readonly ChannelRow[]): EngineLayer[];
