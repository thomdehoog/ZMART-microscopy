/**
 * The stage-position watch: reads `get_xyz` on a clock while the session is
 * open, at once when asked, and never after it was stopped.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EVERY_MS, PATIENCE_MS, watchStagePosition }
  from "../../../workflows/target_acquisition/shared/stage-position.js";

const xyz = (x, y, z = 0) => ({ x: { value: x }, y: { value: y }, z: { value: z } });

describe("watchStagePosition", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("reads at once, then every five seconds", async () => {
    let at = xyz(1, 2);
    const backend = { get_xyz: vi.fn(async () => at) };
    const seen = [];
    const watch = watchStagePosition(backend, (p) => seen.push(p));
    await vi.advanceTimersByTimeAsync(0);
    expect(seen).toEqual([{ x: 1, y: 2, z: 0 }]);
    at = xyz(10, 20, 3);
    await vi.advanceTimersByTimeAsync(EVERY_MS);
    expect(seen).toEqual([{ x: 1, y: 2, z: 0 }, { x: 10, y: 20, z: 3 }]);
    expect(backend.get_xyz).toHaveBeenCalledTimes(2);
    watch.stop();
  });

  it("refreshes at once after a move, without waiting for the clock", async () => {
    let at = xyz(0, 0);
    const backend = { get_xyz: vi.fn(async () => at) };
    const seen = [];
    const watch = watchStagePosition(backend, (p) => seen.push(p));
    await vi.advanceTimersByTimeAsync(0);
    at = xyz(500, 0);
    await watch.refresh();
    expect(seen.at(-1)).toEqual({ x: 500, y: 0, z: 0 });
    expect(backend.get_xyz).toHaveBeenCalledTimes(2);
    watch.stop();
  });

  it("delivers nothing after stop, even from a read that was in flight", async () => {
    let release;
    const backend = { get_xyz: vi.fn(() => new Promise((resolve) => { release = resolve; })) };
    const seen = [];
    const watch = watchStagePosition(backend, (p) => seen.push(p));
    watch.stop();
    release(xyz(9, 9));
    await vi.advanceTimersByTimeAsync(EVERY_MS * 3);
    expect(seen).toEqual([]);
    expect(backend.get_xyz).toHaveBeenCalledTimes(1);
  });

  /* The two below are the same fault seen twice, and it is a fault only a
     real instrument shows: a CAM read that never comes back. The pretend
     backend answers instantly, so the page looked well on it and the mark
     froze on the microscope — exactly the difference between the two
     backends that the page is supposed not to have. */

  it("gives up on a read that never answers, and goes on watching", async () => {
    let answered = 0;
    const backend = {
      get_xyz: vi.fn(() => (answered++ === 0
        ? new Promise(() => {})            // the read that hangs
        : Promise.resolve(xyz(7, 8, 9)))),
    };
    const seen = [];
    const errors = [];
    const watch = watchStagePosition(backend, (p) => seen.push(p), {
      onError: (e) => errors.push(e.message),
    });
    await vi.advanceTimersByTimeAsync(PATIENCE_MS + 1);
    expect(errors.length).toBe(1);
    /* And the next turn of the clock reads again rather than handing back the
       answer that never came. */
    await vi.advanceTimersByTimeAsync(EVERY_MS);
    expect(seen).toEqual([{ x: 7, y: 8, z: 9 }]);
    watch.stop();
  });

  it("refreshes with a read of its own while one is hanging", async () => {
    let hang = true;
    const backend = {
      get_xyz: vi.fn(() => (hang
        ? new Promise(() => {})
        : Promise.resolve(xyz(500, 600)))),
    };
    const seen = [];
    const watch = watchStagePosition(backend, (p) => seen.push(p));
    await vi.advanceTimersByTimeAsync(0);
    expect(seen).toEqual([]);                    // the first read is hanging

    /* Snapping an alignment point asks where the stage is now. Handed the
       hanging read instead, it waits for an answer that never comes and the
       point is tied to nothing. */
    hang = false;
    const at = await watch.refresh();
    expect(at).toEqual({ x: 500, y: 600, z: 0 });
    watch.stop();
  });

  it("reports a failed read and keeps going", async () => {
    let fail = true;
    const backend = { get_xyz: vi.fn(async () => { if (fail) throw new Error("no answer"); return xyz(4, 4); }) };
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
