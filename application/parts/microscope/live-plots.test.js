/**
 * The live backend's multidimensional plot: started, followed until it
 * lands, then its columns asked for by kind. The bridge is a fake `fetch`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { backend } from "../../parts/microscope/live.js";

function bridgePlotting(polls, columns = {}) {
  const calls = [];
  let asked = 0;
  globalThis.fetch = vi.fn(async (url, init) => {
    const route = url.replace(/^http:\/\/[^/]+/, "");
    calls.push([route, init?.body ? JSON.parse(init.body) : null]);
    const answer = (json) => ({ ok: true, json: async () => json });
    if (route === "/api/plots/compute" && init?.method === "POST") return answer({ running: true });
    if (route === "/api/plots/compute") return answer(polls[Math.min(asked++, polls.length - 1)]);
    if (route.startsWith("/api/plots/columns?kind=")) return answer(columns[route.split("=")[1]]);
    if (route === "/api/plots/compute/stop") return answer({ running: true });
    throw new Error(`unexpected ${route}`);
  });
  return calls;
}

describe("the live multidimensional plot", () => {
  const realFetch = globalThis.fetch;
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { vi.useRealTimers(); globalThis.fetch = realFetch; });

  it("follows the plot and hands back every column it wrote, by kind", async () => {
    const pca = { columns: ["pc_1", "pc_2"], ids: ["a", "b"], values: [[1, 2], [3, 4]] };
    const umap = { columns: ["umap_1", "umap_2"], ids: ["a", "b"], values: [[5, 6], [7, 8]] };
    const calls = bridgePlotting([
      { running: true, doing: "computing UMAP over 2 objects" },
      { running: false, error: null, stopped: false, kinds: ["pca", "umap"], objects: 2, took_s: 1.5 },
    ], { pca, umap });
    const said = [];
    const run = backend.computePlot({ kind: "umap", ids: ["a", "b"], onDoing: (s) => said.push(s) });
    for (let i = 0; i < 4; i++) await vi.advanceTimersByTimeAsync(500);
    const out = await run;
    expect(calls[0]).toEqual(["/api/plots/compute", { kind: "umap", ids: ["a", "b"] }]);
    expect(out).toEqual({ stopped: false, objects: 2, seconds: 1.5, columns: [pca, umap] });
    expect(said).toEqual(["computing UMAP over 2 objects", null]);
  });

  it("says the bridge's sentence when the plot failed, and nothing when it was stopped", async () => {
    /* The first answer already ends the plot: real time, nothing to wait out. */
    vi.useRealTimers();
    bridgePlotting([{ running: false, error: "only 2 objects; a plot needs at least 10" }]);
    await expect(backend.computePlot({ kind: "pca" })).rejects.toThrow("at least 10");
    bridgePlotting([{ running: false, error: null, stopped: true, kinds: [] }]);
    await expect(backend.computePlot({ kind: "pca" })).resolves.toMatchObject({ stopped: true, columns: [] });
  });
});
