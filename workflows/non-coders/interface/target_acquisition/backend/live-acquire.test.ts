/**
 * The live backend's target run: the page's own loop, one tile at a time,
 * with a focussing stack first when the operator asked for one. The bridge
 * is a fake `fetch` that records what it was asked, in order.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { backend } from "./live.ts";
import { aBridge, ok, theFirstTo } from "../testing/fake-bridge.ts";

/* A curve with one clear peak at 12 µm, as the bridge's scorer answers. */
const curveAt = (peak: number) => ({
  samples: [-4, -2, 0, 2, 4].map((dz) => ({ z: peak + dz, s: 1 - Math.abs(dz) / 5 })),
});

/** A bridge that answers every route of the run and keeps the calls. */
function bridgeTakingTargets({ peak = 12, curve = true, declining = false, standsAt = null as number | null } = {}) {
  let landed = 0;
  const answer = ok;
  const { calls } = aBridge((route, body) => {
    if (route === "/api/target_acquisition/targets/acquire/begin") {
      return answer({ running: true, labels: body.positions.map((_: unknown, i: number) => `L${i}`) });
    }
    /* Where the stage says it stood: where it was sent, or a height of its own. */
    if (route === "/api/target_acquisition/xyz") {
      return answer({ x: { position: body.x }, y: { position: body.y }, z: { position: standsAt ?? body.z ?? 0 } });
    }
    if (route === "/api/target_acquisition/state") return answer({ applied: body });
    if (route === "/api/target_acquisition/acquire") {
      if (declining) return answer({ success: false, output: { reason: "the laser is off", files: [], planes: [] } });
      return answer({ success: true, output: { position_label: body.position_label } });
    }
    if (route === "/api/target_acquisition/targets/acquire/focus") {
      return answer({ z: curve ? peak : null, lost: !curve, traces: curve ? { brenner: curveAt(peak) } : null });
    }
    if (route === "/api/target_acquisition/targets/acquire/landed") { landed += 1; return answer({ ...body.record, taken: landed }); }
    if (route === "/api/target_acquisition/targets/acquire/end") return answer({ running: false });
    throw new Error(`unexpected ${route}`);
  });
  return calls;
}

const positions = [{ x: 10, y: 20, z: 5, position_index: 0 }, { x: 30, y: 40, z: 6, position_index: 1 }];

describe("the live target run", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it("drives, captures and lands each tile, applying the target job once", async () => {
    const calls = bridgeTakingTargets();
    const seen: unknown[][] = [];
    const out = await backend.acquireTargets({
      positions, state: { job: "Target" },
      onProgress: (done, of, at, records) => seen.push([done, of, at?.z, records.length]),
    });
    expect(calls.map(([route]) => route)).toEqual([
      "/api/target_acquisition/targets/acquire/begin", "/api/target_acquisition/state",
      "/api/target_acquisition/xyz", "/api/target_acquisition/acquire", "/api/target_acquisition/targets/acquire/landed",
      "/api/target_acquisition/xyz", "/api/target_acquisition/acquire", "/api/target_acquisition/targets/acquire/landed",
      "/api/target_acquisition/targets/acquire/end",
    ]);
    expect(calls[0][1]).toEqual({ positions, append: false });
    expect(calls[2][1]).toEqual({ x: 10, y: 20, z: 5 });
    expect(calls[3][1]).toEqual({ acquisition_type: "targets", position_label: "L0", acquisition_settings: null });
    expect(calls[4][1].position).toEqual({ x: 10, y: 20, z: 5 });
    expect(calls[4][1].focus).toBeNull();
    expect(seen).toEqual([[1, 2, 5, 1], [2, 2, 6, 2]]);
    expect(out.done).toBe(2);
    expect(out.records.map((r) => r.position_label)).toEqual(["L0", "L1"]);
    expect(out.stopped).toBe(false);
  });

  it("focusses first when asked: the stack under the focussing job, the target at the peak", async () => {
    const calls = bridgeTakingTargets({ peak: 12 });
    const said: (string | null)[] = [];
    await backend.acquireTargets({
      positions: positions.slice(0, 1), state: { job: "Target" },
      focus: { state: { job: "Focussing" }, metric: "brenner" },
      onDoing: (sentence) => said.push(sentence),
    });
    expect(calls.map(([route]) => route)).toEqual([
      "/api/target_acquisition/targets/acquire/begin",
      "/api/target_acquisition/state", "/api/target_acquisition/xyz", "/api/target_acquisition/acquire", "/api/target_acquisition/targets/acquire/focus",
      "/api/target_acquisition/state", "/api/target_acquisition/xyz", "/api/target_acquisition/acquire", "/api/target_acquisition/targets/acquire/landed",
      "/api/target_acquisition/targets/acquire/end",
    ]);
    expect(calls[1][1]).toEqual({ job: "Focussing" });
    expect(calls[3][1]).toEqual({ acquisition_type: "target-focussing", position_label: "L0", acquisition_settings: null });
    expect(calls[4][1]).toMatchObject({ centre: 5, x: 10, y: 20 });
    /* The target job first, then the drive to the peak the page chose from
       the curve by the map's own rule: a job switch may move the optics,
       and the height is set after it. */
    expect(calls[5][1]).toEqual({ job: "Target" });
    expect(calls[6][1]).toEqual({ x: 10, y: 20, z: 12 });
    expect(calls[8][1].position.z).toBe(12);
    expect(calls[8][1].focus).toEqual({ settings: { job: "Focussing" }, z_map_um: 5, z_peak_um: 12, found: true });
    expect(said).toEqual(["focussing on target 1 of 1", "imaging target 1 of 1", null]);
  });

  it("takes the stack on the object's centre, then images the tile", async () => {
    const calls = bridgeTakingTargets({ peak: 12 });
    await backend.acquireTargets({
      positions: [{ ...positions[0], focusAt: { x: 14, y: 23 } }], state: { job: "Target" },
      focus: { state: { job: "Focussing" }, metric: "brenner" },
    });
    const drives = calls.filter(([route]) => route === "/api/target_acquisition/xyz").map(([, body]) => body);
    expect(drives).toEqual([{ x: 14, y: 23, z: 5 }, { x: 10, y: 20, z: 12 }]);
    const scored = theFirstTo(calls, "/api/target_acquisition/targets/acquire/focus");
    expect(scored).toMatchObject({ x: 14, y: 23 });
  });

  it("drives back to the tile at the stack's height when a stack off-centre shows no peak", async () => {
    const calls = bridgeTakingTargets({ curve: false });
    await backend.acquireTargets({
      positions: [{ ...positions[0], focusAt: { x: 14, y: 23 } }], state: { job: "Target" },
      focus: { state: { job: "Focussing" }, metric: "brenner" },
    });
    const drives = calls.filter(([route]) => route === "/api/target_acquisition/xyz").map(([, body]) => body);
    expect(drives).toEqual([{ x: 14, y: 23, z: 5 }, { x: 10, y: 20, z: 5 }]);
  });

  it("images at the map's height when the stack shows no peak, and says so", async () => {
    const calls = bridgeTakingTargets({ curve: false });
    await backend.acquireTargets({
      positions: positions.slice(0, 1), state: { job: "Target" },
      focus: { state: { job: "Focussing" }, metric: "brenner" },
    });
    const drives = calls.filter(([route]) => route === "/api/target_acquisition/xyz").map(([, body]) => body.z);
    expect(drives).toEqual([5]);
    const landed = theFirstTo(calls, "/api/target_acquisition/targets/acquire/landed");
    expect(landed.position.z).toBe(5);
    expect(landed.focus).toEqual({ settings: { job: "Focussing" }, z_map_um: 5, z_peak_um: null, found: false });
  });

  it("lands at the height the stage stood at when there is no map and no peak", async () => {
    /* A tile with no height from the map is driven to at the objective's
       standing height; a stack there with no peak leaves it there, and the
       record carries that height, not nothing. */
    const calls = bridgeTakingTargets({ curve: false, standsAt: 33 });
    await backend.acquireTargets({
      positions: [{ x: 10, y: 20, position_index: 0 }], state: { job: "Target" },
      focus: { state: { job: "Focussing" }, metric: "brenner" },
    });
    const landed = theFirstTo(calls, "/api/target_acquisition/targets/acquire/landed");
    expect(landed.position.z).toBe(33);
    expect(landed.focus).toEqual({ settings: { job: "Focussing" }, z_map_um: null, z_peak_um: null, found: false });
  });

  /* The operator's z offset is added once, to the height chosen for the
     target. The stack itself is taken at the map's own height: it was taken
     at the lifted height, and when it showed no peak the target was lifted a
     second time from there (map 100, offset 5: the target at 110). */
  it("adds the offset once when the stack shows no peak", async () => {
    const calls = bridgeTakingTargets({ curve: false });
    await backend.acquireTargets({
      positions: [{ x: 10, y: 20, z: 100, position_index: 0 }], state: { job: "Target" },
      focus: { state: { job: "Focussing" }, metric: "brenner" }, zOffsetUm: 5,
    });
    const drives = calls.filter(([route]) => route === "/api/target_acquisition/xyz").map(([, body]) => body.z);
    expect(drives).toEqual([100, 105]);
    const landed = theFirstTo(calls, "/api/target_acquisition/targets/acquire/landed");
    expect(landed.position.z).toBe(105);
  });

  it("adds the offset once to the peak, and takes the stack at the map's height", async () => {
    const calls = bridgeTakingTargets({ peak: 12 });
    await backend.acquireTargets({
      positions: positions.slice(0, 1), state: { job: "Target" },
      focus: { state: { job: "Focussing" }, metric: "brenner" }, zOffsetUm: 5,
    });
    const drives = calls.filter(([route]) => route === "/api/target_acquisition/xyz").map(([, body]) => body.z);
    expect(drives).toEqual([5, 17]);
    expect(theFirstTo(calls, "/api/target_acquisition/targets/acquire/focus")).toMatchObject({ centre: 5 });
  });

  it("adds the offset to the map's height when there is no focussing", async () => {
    const calls = bridgeTakingTargets();
    await backend.acquireTargets({ positions: positions.slice(0, 1), state: null, zOffsetUm: 5 });
    const drives = calls.filter(([route]) => route === "/api/target_acquisition/xyz").map(([, body]) => body.z);
    expect(drives).toEqual([10]);
  });

  it("lands the capture's output, not the controller's envelope around it", async () => {
    const calls = bridgeTakingTargets();
    await backend.acquireTargets({ positions: positions.slice(0, 1), state: null });
    const landed = theFirstTo(calls, "/api/target_acquisition/targets/acquire/landed");
    expect(landed.record).toEqual({ position_label: "L0" });
  });

  it("stops the run with the driver's reason when the microscope declines a capture", async () => {
    const calls = bridgeTakingTargets({ declining: true });
    await expect(backend.acquireTargets({ positions, state: null }))
      .rejects.toThrow("the microscope could not capture an image: the laser is off");
    expect(calls.some(([route]) => route === "/api/target_acquisition/targets/acquire/landed")).toBe(false);
    expect(calls.at(-1)?.[0]).toBe("/api/target_acquisition/targets/acquire/end");
  });

  it("stops after the tile in hand, and ends the run as stopped", async () => {
    const calls = bridgeTakingTargets();
    const run = backend.acquireTargets({
      positions, state: null,
      onProgress: (done) => { if (done === 1) backend.stopAcquireTargets(); },
    });
    const out = await run;
    expect(out.done).toBe(1);
    expect(out.stopped).toBe(true);
    expect(calls.filter(([route]) => route === "/api/target_acquisition/acquire")).toHaveLength(1);
    expect(calls.at(-1)).toEqual(["/api/target_acquisition/targets/acquire/end", { stopped: true }]);
  });
});
