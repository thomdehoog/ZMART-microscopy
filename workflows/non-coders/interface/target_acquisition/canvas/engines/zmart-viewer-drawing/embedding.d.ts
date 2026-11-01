export function viewKey(view: any): any;
export function viewChoices(layers: any): {
    id: any;
    acquisition: any;
    label: any;
    keys: string[];
}[];
export function selectedViews(layers: any, requested?: {}): any;
export function inSelectedView(spec: any, selected: any): boolean;
/** Keep the last complete framebuffer during an explicitly requested Z change.
 * No extra reads or timer: the normal chunk arrivals schedule the next draw.
 * Call cancel before changing XY framing or the layer composition.
 */
export function holdCompleteSlice(sliceView: any, changed?: () => void): {
    readonly pending: boolean;
    request(): void;
    cancel(): void;
    dispose(): void;
};
/**
 * @param {object} layer the engine's layer
 * @param {object | null} [viewer] the viewer whose depth the layer follows, or null to hold it
 * @param {((value: any) => object) | null} [makeTransform] the engine's own coordinate transform, made from a default one
 */
export function keepDepthLocal(layer: object, viewer?: object | null, makeTransform?: ((value: any) => object) | null): void;
export function refreshGeometry(source: any, chunkManager: any, refreshed: any, forgotten: any, { replaceHeld }?: {
    replaceHeld?: boolean | undefined;
}): Promise<void>;
export const EMBEDDING_API_VERSION: 1;
export namespace VIEW_LABELS {
    let slice: string;
    let top: string;
    let min: string;
    let max: string;
    let sum: string;
}
export function geometryRefreshPending(source: any): boolean;
