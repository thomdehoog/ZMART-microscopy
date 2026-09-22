/**
 * The live backend's discovery poll: every field the bridge lists reaches
 * `onField` once, whatever order the bridge lists them in and however the
 * list is reordered between two polls. The bridge is a fake `fetch`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { backend } from "../../parts/microscope/live.js";

/** A bridge whose discovery walks through `polls`, one state per GET, and
    answers each with only the fields past the `since` the page asked. */
function bridgeDiscovering(polls) {
  let asked = 0;
  const askedSince = [];
  globalThis.fetch = vi.fn(async (url, init) => {
    if (url.endsWith("/api/targets/discover") && init?.method === "POST") {
      return { ok: true, json: async () => ({ running: true }) };
    }
    if (url.includes("/api/targets/discover?since=")) {
      const since = Number(url.split("since=")[1]);
      askedSince.push(since);
      const state = polls[Math.min(asked, polls.length - 1)];
      asked += 1;
      return { ok: true, json: async () => ({ ...state, fields: state.fields.slice(since) }) };
    }
    throw new Error(`unexpected ${url}`);
  });
  return askedSince;
}

describe("the live discovery poll", () => {
  const realFetch = globalThis.fetch;
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { vi.useRealTimers(); globalThis.fetch = realFetch; });

  it("asks only for the fields it does not hold yet, and hands each over once", async () => {
    /* Fields land in the engine's order and the bridge keeps that order,
       so the number held is the cursor. A poll that carried every field
       found so far was 900 MB at three hundred fields, three times a
       second. The answer at the end is what the page collected. */
    const askedSince = bridgeDiscovering([
      { running: true, done: 1, of: 3, phase: "objects", fields: [{ field: 2 }] },
      { running: true, done: 2, of: 3, phase: "objects", fields: [{ field: 2 }, { field: 0 }] },
      { running: true, done: 2, of: 3, phase: "objects", fields: [{ field: 2 }, { field: 0 }] },
      { running: false, done: 3, of: 3, phase: "complete", fields: [{ field: 2 }, { field: 0 }, { field: 1 }] },
    ]);
    const seen = [];
    const run = backend.discoverTargets({ settings: {}, onField: (field) => seen.push(field.field) });
    for (let i = 0; i < 5; i++) await vi.advanceTimersByTimeAsync(300);
    const out = await run;
    expect(askedSince).toEqual([0, 1, 2, 2]);
    expect(seen).toEqual([2, 0, 1]);
    expect(out.fields.map((one) => one.field)).toEqual([2, 0, 1]);
  });
});
