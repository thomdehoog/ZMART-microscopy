/**
 * The live backend's target run: the page's own loop, one tile at a time,
 * with a focussing stack first when the operator asked for one. The bridge
 * is a fake `fetch` that records what it was asked, in order.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { backend } from "../../parts/microscope/live.js";

/* A curve with one clear peak at 12 µm, as the bridge's scorer answers. */
const curveAt = (peak) => ({
  samples: [-4, -2, 0, 2, 4].map((dz) => ({ z: peak + dz, s: 1 - Math.abs(dz) / 5 })),
});

/** A bridge that answers every route of the run and keeps the calls. */
function bridgeTakingTargets({ peak = 12, curve = true } = {}) {
  const calls = [];
  let landed = 0;
  globalThis.fetch = vi.fn(async (url, init) => {
    const route = url.replace(/^http:\/\/[^/]+/, "");
    const body = init?.body ? JSON.parse(init.body) : null;
    calls.push([route, body]);
    const answer = (json) => ({ ok: true, json: async () => json });
    if (route === "/api/targets/acquire/begin") {
      return answer({ running: true, labels: body.positions.map((_, i) => `L${i}`) });
    }
    if (route === "/api/xyz") return answer({ x: { value: body.x }, y: { value: body.y }, z: { value: body.z ?? 0 } });
    if (route === "/api/state") return answer({ applied: body });
    if (route === "/api/acquire") return answer({ acquisition_type: body.acquisition_type, position_label: body.position_label });
    if (route === "/api/targets/acquire/focus") {
      return answer({ z: curve ? peak : null, lost: !curve, traces: curve ? { brenner: curveAt(peak) } : null });
    }
    if (route === "/api/targets/acquire/landed") { landed += 1; return answer({ ...body.record, taken: landed }); }
    if (route === "/api/targets/acquire/end") return answer({ running: false });
    throw new Error(`unexpected ${route}`);
  });
  return calls;
}

const positions = [{ x: 10, y: 20, z: 5, position_index: 0 }, { x: 30, y: 40, z: 6, position_index: 1 }];

describe("the live target run", () => {
  const realFetch = globalThis.fetch;
  afterEach(() => { globalThis.fetch = realFetch; });

  it("drives, captures and lands each tile, applying the target job once", async () => {
    const calls = bridgeTakingTargets();
    const seen = [];
    const out = await backend.acquireTargets({
      positions, state: { job: "Target" },
      onProgress: (done, of, at, records) => seen.push([done, of, at?.z, records.length]),
    });
    expect(calls.map(([route]) => route)).toEqual([
      "/api/targets/acquire/begin", "/api/state",
      "/api/xyz", "/api/acquire", "/api/targets/acquire/landed",
      "/api/xyz", "/api/acquire", "/api/targets/acquire/landed",
      "/api/targets/acquire/end",
    ]);
    expect(calls[0][1]).toEqual({ positions, append: false });
    expect(calls[2][1]).toEqual({ x: 10, y: 20, z: 5 });
    expect(calls[3][1]).toEqual({ acquisition_type: "targets", position_label: "L0", options: null });
    expect(calls[4][1].position).toEqual({ x: 10, y: 20, z: 5 });
    expect(calls[4][1].focus).toBeNull();
    expect(seen).toEqual([[1, 2, 5, 1], [2, 2, 6, 2]]);
    expect(out.done).toBe(2);
    expect(out.records.map((r) => r.position_label)).toEqual(["L0", "L1"]);
    expect(out.stopped).toBe(false);
  });

  it("focusses first when asked: the stack under the focussing job, the target at the peak", async () => {
    const calls = bridgeTakingTargets({ peak: 12 });
    const said = [];
    await backend.acquireTargets({
      positions: positions.slice(0, 1), state: { job: "Target" },
      focus: { state: { job: "Focussing" }, metric: "brenner" },
      onDoing: (sentence) => said.push(sentence),
    });
    expect(calls.map(([route]) => route)).toEqual([
      "/api/targets/acquire/begin",
      "/api/state", "/api/xyz", "/api/acquire", "/api/targets/acquire/focus",
      "/api/state", "/api/xyz", "/api/acquire", "/api/targets/acquire/landed",
      "/api/targets/acquire/end",
    ]);
    expect(calls[1][1]).toEqual({ job: "Focussing" });
    expect(calls[3][1]).toEqual({ acquisition_type: "target_focussing", position_label: "L0", options: null });
    expect(calls[4][1]).toMatchObject({ centre: 5, x: 10, y: 20 });
    /* The target job first, then the drive to the peak the page chose from
       the curve by the map's own rule: a job switch may move the optics,
       and the height is set after it. */
    expect(calls[5][1]).toEqual({ job: "Target" });
    expect(calls[6][1]).toEqual({ x: 10, y: 20, z: 12 });
    expect(calls[8][1].position.z).toBe(12);
    expect(calls[8][1].focus).toEqual({ job: "Focussing", z_map_um: 5, z_peak_um: 12, found: true });
    expect(said).toEqual(["focussing on target 1 of 1", "imaging target 1 of 1", null]);
  });

  it("images at the map's height when the stack shows no peak, and says so", async () => {
    const calls = bridgeTakingTargets({ curve: false });
    await backend.acquireTargets({
      positions: positions.slice(0, 1), state: { job: "Target" },
      focus: { state: { job: "Focussing" }, metric: "brenner" },
    });
    const drives = calls.filter(([route]) => route === "/api/xyz").map(([, body]) => body.z);
    expect(drives).toEqual([5]);
    const landed = calls.find(([route]) => route === "/api/targets/acquire/landed")[1];
    expect(landed.position.z).toBe(5);
    expect(landed.focus).toEqual({ job: "Focussing", z_map_um: 5, z_peak_um: null, found: false });
  });

  it("lands at the height the stage stood at when there is no map and no peak", async () => {
    /* A tile with no height from the map is driven to at the objective's
       standing height; a stack there with no peak leaves it there, and the
       record carries that height, not nothing. */
    const calls = bridgeTakingTargets({ curve: false });
    globalThis.fetch = ((inner) => async (url, init) => {
      if (url.endsWith("/api/xyz")) {
        const body = JSON.parse(init.body);
        calls.push(["/api/xyz", body]);
        return { ok: true, json: async () => ({ x: { value: body.x }, y: { value: body.y }, z: { value: 33 } }) };
      }
      return inner(url, init);
    })(globalThis.fetch);
    await backend.acquireTargets({
      positions: [{ x: 10, y: 20, position_index: 0 }], state: { job: "Target" },
      focus: { state: { job: "Focussing" }, metric: "brenner" },
    });
    const landed = calls.find(([route]) => route === "/api/targets/acquire/landed")[1];
    expect(landed.position.z).toBe(33);
    expect(landed.focus).toEqual({ job: "Focussing", z_map_um: null, z_peak_um: null, found: false });
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
    expect(calls.filter(([route]) => route === "/api/acquire")).toHaveLength(1);
    expect(calls.at(-1)).toEqual(["/api/targets/acquire/end", { stopped: true }]);
  });
});
