/**
 * Handing the engine its stores a few at a time, across the whole scene.
 *
 * Each layer has its own queue of stores still to hand over; there is one budget
 * and one loop for all of them, which offers the stores a group at a time and lets
 * each group be read before offering the next. Why, and what this does not do, is
 * set out above `keepHandingOver`. Keeping the layers themselves in step is
 * `sync.ts`, which queues the stores here.
 *
 * One budget per engine (Thom, 2026-10-18): `makeFeeding` holds every queue, the
 * group in flight and the loop, and is made with its engine and dropped with it.
 * Nothing lives in a module variable, so two engines on one page each keep
 * their own.
 */
import type { UserLayer } from "neuroglancer/unstable/layer/index.js";
import type { LayerDataSource } from "neuroglancer/unstable/layer/layer_data_source.js";
/** One engine's feeding: its queues, its one budget and its one loop. */
export interface Feeding {
    /** How many stores are offered at a time, across the whole scene. */
    howManyAtATime(): number;
    queueStores(layer: UserLayer, urls: readonly string[]): void;
    alreadyBeingRead(sources: readonly LayerDataSource[]): void;
    stopFeeding(layer: UserLayer): void;
    keepHandingOver(): Promise<void>;
    sourcesStillWaiting(layers: Iterable<UserLayer | null | undefined>): number;
    /** Stop waiting on anything, for an engine going away. */
    dispose(): void;
}
/** Make the feeding for one engine. Everything it holds dies with it. */
export declare function makeFeeding(): Feeding;
