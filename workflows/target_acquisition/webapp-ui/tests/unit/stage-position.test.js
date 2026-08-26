/**
 * The stage-position watch: reads `get_xyz` on a clock while the session is
 * open, at once when asked, and never after it was stopped.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EVERY_MS, watchStagePosition } from "../../workflows/target_acquisition/shared/stage-position.js";

const xyz = (x, y, z = 0) => ({ x: { value: x }, y: { value: y }, z: { value: z } });

describe("watchStagePosition", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("reads at once, then every five seconds", async () => {
    let at = xyz(1, 2);
    const backend = { xyz: vi.fn(async () => at) };
    const seen = [];
    const watch = watchStagePosition(backend, (p) => seen.push(p));
    await vi.advanceTimersByTimeAsync(0);
    expect(seen).toEqual([{ x: 1, y: 2, z: 0 }]);
    at = xyz(10, 20, 3);
    await vi.advanceTimersByTimeAsync(EVERY_MS);
    expect(seen).toEqual([{ x: 1, y: 2, z: 0 }, { x: 10, y: 20, z: 3 }]);
    expect(backend.xyz).toHaveBeenCalledTimes(2);
    watch.stop();
  });

  it("refreshes at once after a move, without waiting for the clock", async () => {
    let at = xyz(0, 0);
    const backend = { xyz: vi.fn(async () => at) };
    const seen = [];
    const watch = watchStagePosition(backend, (p) => seen.push(p));
    await vi.advanceTimersByTimeAsync(0);
    at = xyz(500, 0);
    await watch.refresh();
    expect(seen.at(-1)).toEqual({ x: 500, y: 0, z: 0 });
    expect(backend.xyz).toHaveBeenCalledTimes(2);
    watch.stop();
  });

  it("delivers nothing after stop, even from a read that was in flight", async () => {
    let release;
    const backend = { xyz: vi.fn(() => new Promise((resolve) => { release = resolve; })) };
    const seen = [];
    const watch = watchStagePosition(backend, (p) => seen.push(p));
    watch.stop();
    release(xyz(9, 9));
    await vi.advanceTimersByTimeAsync(EVERY_MS * 3);
    expect(seen).toEqual([]);
    expect(backend.xyz).toHaveBeenCalledTimes(1);
  });

  it("reports a failed read and keeps going", async () => {
    let fail = true;
    const backend = { xyz: vi.fn(async () => { if (fail) throw new Error("no answer"); return xyz(4, 4); }) };
    const errors = [];
    const seen = [];
    const watch = watchStagePosition(backend, (p) => seen.push(p), { onError: (e) => errors.push(e.message) });
    await vi.advanceTimersByTimeAsync(0);
    expect(errors).toEqual(["no answer"]);
    fail = false;
    await vi.advanceTimersByTimeAsync(EVERY_MS);
    expect(seen).toEqual([{ x: 4, y: 4, z: 0 }]);
    watch.stop();
  });
});
