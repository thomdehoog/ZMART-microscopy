/**
 * Keeping the engine's picture in step with a page's scene, without rebuilding it.
 *
 * A page and the engine hold the same information in two different shapes.
 * A page thinks in groups and channels; the engine thinks in a flat list of
 * layers. Something has to carry changes from one to the other, and this
 * is that something.
 *
 * The obvious way to do it is to hand Neuroglancer a fresh description of the
 * whole scene every time anything changes, and let it sort out the difference.
 * Neuroglancer offers exactly that call, and we used it. It turns out not to work
 * the way the name suggests: `restoreState` does not compare the new description
 * against the old one. It throws every existing layer away and builds the lot
 * again from scratch. So nudging one contrast slider was quietly demolishing and
 * rebuilding every layer on screen.
 *
 * Three things go wrong when that happens, and they get worse as the data gets
 * bigger:
 *
 * 1. Anything drawn on a layer is lost. A drawn annotation lives inside its
 *    layer, and the rebuilt layer is a new, empty one — so the drawing disappears
 *    from the image while the page's list beside it still claims it is there.
 * 2. The pieces of image already fetched are dropped and asked for again. They
 *    are kept in a shared cache that survives for a moment after the last layer
 *    lets go of them, so a fast enough rebuild often catches them still warm and
 *    nothing is refetched. That is luck, not design, and on several hundred
 *    gigabytes of stores — where a rebuild can easily land while pieces are still
 *    in flight — it is luck that runs out.
 * 3. Everything the engine had worked out about the scene has to be worked out
 *    again: which copy of the image to draw, how the layers line up in space, which
 *    shader programs to compile. None of it changed.
 *
 * So this module does the comparing itself. It looks at what the engine currently
 * has, works out the smallest set of changes that would turn it into what the
 * page is asking for, and makes only those. A layer is built only when it is
 * genuinely new, and thrown away only when it has genuinely gone. Everything else
 * — brightness, colour, opacity, whether a channel is showing, what order the
 * groups are drawn in — is written straight onto the layer that is
 * already there, which is what Neuroglancer expects and is fast enough to do on
 * every drag of a slider.
 */
import type { UserLayer } from "neuroglancer/unstable/layer/index.js";
import type { Viewer } from "neuroglancer/unstable/viewer.js";
import type { PageLayer, SceneLayer } from "./description.ts";
import type { Feeding } from "./feeding.ts";
/** What one sync pass refreshed, for the tests to read: the cost of a refresh, counted. */
export interface SourceRefreshing {
    passes: number;
    sources: string[];
    metadataEntries: number;
    decodedEntries: number;
}
/** How many times the engine has been told to let go, and how many sources it asked the last time. */
export interface LettingGo {
    times: number;
    asked: number;
}
/**
 * How a page writes the settings of a layer of its own kind -- one the
 * primitives build and order but know nothing else about.
 */
export type OwnSettings = (layer: UserLayer, description: PageLayer) => void;
/** One engine's way of keeping its layers in step with a page's scene. */
export interface LayerSync {
    syncLayers(specs: SceneLayer[], options?: {
        reread?: boolean;
    }): number;
    letGoOfDecodedPieces(): number;
    sourceRefreshing: SourceRefreshing;
    lettingGo: LettingGo;
}
/**
 * Make the layer keeping for one engine: everything it remembers about the
 * layers, and its counters, live here and die with the engine.
 */
export declare function makeLayerSync(viewer: Viewer, feeding: Feeding, ownSettings?: OwnSettings): LayerSync;
