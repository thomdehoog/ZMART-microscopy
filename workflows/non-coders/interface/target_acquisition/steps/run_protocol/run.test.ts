import { describe, it, expect } from "vitest";
import { protocolBlockers } from "./run.ts";
import type { TaPage } from "../../types.ts";

describe("what holds the protocol back", () => {
  it("a gate on computed axes", () => {
    const run = { focus: { applied: true }, plan: [], targetFocusOn: false,
      gates: [{ fx: "umap_1", fy: "umap_2", vertices: [[0, 0], [1, 0], [1, 1]] }] };
    const page = { run, step: () => ({}), indexOfStep: () => 0 } as unknown as TaPage;
    expect(protocolBlockers(page)).toContain("Discover Targets: a gate on umap_1 × umap_2 cannot go into "
      + "a protocol: PCA and UMAP are fitted anew on every run; gate on measured features instead");
  });
});
