/**
 * The live backend's discovery poll: every field the bridge lists reaches
 * `onField` once, whatever order the bridge lists them in and however the
 * list is reordered between two polls. The bridge is a fake `fetch`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { backend } from "../../parts/microscope/live.js";

/** A bridge whose discovery answers walk through `polls`, one per GET. */
function bridgeDiscovering(polls) {
  let asked = 0;
  globalThis.fetch = vi.fn(async (url, init) => {
    if (url.endsWith("/api/targets/discover") && init?.method === "POST") {
      return { ok: true, json: async () => ({ running: true }) };
    }
    if (url.endsWith("/api/targets/discover")) {
      const answer = polls[Math.min(asked, polls.length - 1)];
      asked += 1;
      return { ok: true, json: async () => answer };
    }
    throw new Error(`unexpected ${url}`);
  });
}

describe("the live discovery poll", () => {
  const realFetch = globalThis.fetch;
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { vi.useRealTimers(); globalThis.fetch = realFetch; });

  it("hands every field over once, by its number, not by its place in a list that is reordered", async () => {
    /* Fields land in the engine's order and the bridge sorts its list into
       the sample's order before finalizing; one poll may even catch the list
       empty mid-sort. A cursor by position missed the field that landed
       last, and it only appeared when everything was over. */
    bridgeDiscovering([
      { running: true, done: 1, of: 3, phase: "objects", fields: [{ field: 2 }] },
      { running: true, done: 2, of: 3, phase: "objects", fields: [{ field: 2 }, { field: 0 }] },
      { running: true, done: 3, of: 3, phase: "objects", fields: [] },
      { running: true, done: 3, of: 3, phase: "finalizing", fields: [{ field: 0 }, { field: 1 }, { field: 2 }] },
      { running: false, done: 3, of: 3, phase: "complete", fields: [{ field: 0 }, { field: 1 }, { field: 2 }] },
    ]);
    const seen = [];
    const run = backend.discoverTargets({ settings: {}, onField: (field) => seen.push(field.field) });
    for (let i = 0; i < 6; i++) await vi.advanceTimersByTimeAsync(300);
    const out = await run;
    expect(seen).toEqual([2, 0, 1]);
    expect(out.fields.map((one) => one.field)).toEqual([0, 1, 2]);
  });
});
