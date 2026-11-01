/**
 * Which stores have committed something new, and what the engine remembers
 * about one store.
 *
 * Pure decisions, kept free of the engine and the browser so a plain Node
 * process can check them as well as the real page.
 */
/** A source's revision, by its stable identity, with the address it is read from. */
export type SourceRevisions = Map<string, {
    url: string;
    revision: number | undefined;
}>;
/** The revisions last applied, by identity and by address alike. */
export type RememberedRevisions = Map<string, number | undefined>;
/** Pair each stable source identity and URL with its separately carried revision. */
export declare function sourceRevisionsFor(urls: readonly string[], sourceIds: readonly (string | undefined)[] | null | undefined, sourceRevisions: readonly number[] | null | undefined): SourceRevisions;
/** Select only sources whose valid committed revision moved strictly forwards. */
export declare function advancingSourceRevisions(previous: RememberedRevisions | null | undefined, current: SourceRevisions): [string, {
    url: string;
    revision: number | undefined;
}][];
/** Remember both identity and stable URL, allowing either to match the next pass. */
export declare function rememberedSourceRevisions(current: SourceRevisions): RememberedRevisions;
/**
 * Identify memoized metadata and decoded holders for exactly one stable source.
 *
 * The source address ends at its store folder, including a trailing slash, so a
 * similarly prefixed neighbour cannot match. Returning keys rather than mutating
 * the map keeps this policy independently testable.
 */
export declare function memoEntriesForStableSource(questions: Iterable<string>, url: string): {
    metadata: string[];
    decoded: string[];
};
