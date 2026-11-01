export function lutShader(stops: any, name?: string): string;
export function hexColour(rgb: any): string;
/**
 * @param {boolean} volumetric
 * @param {string | null} [lut] a colour map's name, or null for the flat colour
 * @param {boolean} [opaque]
 * @param {{ gamma?: boolean }} [options]
 * @returns {string}
 */
export function shaderFor(volumetric: boolean, lut?: string | null, opaque?: boolean, { gamma }?: {
    gamma?: boolean;
}): string;
/**
 * @param {{ low: number, high: number } | null | undefined} window_
 * @param {boolean} volumetric
 * @param {number} weight
 * @param {readonly number[] | null | undefined} colour
 * @param {string | null} [lut]
 * @param {number} [attenuation]
 * @param {number | null} [gamma]
 * @returns {Record<string, unknown> | undefined}
 */
export function shaderControlsFor(window_: {
    low: number;
    high: number;
} | null | undefined, volumetric: boolean, weight: number, colour: readonly number[] | null | undefined, lut?: string | null, attenuation?: number, gamma?: number | null): Record<string, unknown> | undefined;
export namespace LOOKUP_TABLES {
    let viridis: number[][];
    let magma: number[][];
    let fire: number[][];
    let ice: number[][];
}
export const LOOKUP_TABLE_NAMES: string[];
/**
 * Black wherever a coverage store says something was acquired, and nothing
 * elsewhere: the ground under a position whose acquired part is known.
 */
export const COVERAGE_SHADER: string;
/**
 * Black over everything a store holds: the ground under a position when only
 * its extent is known.
 */
export const GROUND_SHADER: "void main() { emitRGBA(vec4(0.0, 0.0, 0.0, 1.0)); }";
