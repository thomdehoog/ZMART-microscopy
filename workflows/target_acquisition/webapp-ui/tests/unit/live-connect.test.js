/**
 * The live backend's connect: it opens the session through the bridge and
 * then watches the driver's own connection checks answer, by polling
 * `get_info().connection_status` until nothing is pending. The bridge is a
 * fake `fetch` here; what is pinned is the contract the page relies on —
 * keys first, each answer once, resolve when done, reject naming a failure.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PENDING } from "../../workflows/target_acquisition/microscope/connection-status.js";
import { backend } from "../../workflows/target_acquisition/microscope/live.js";

/** A bridge whose `get_info` answers walk through `statuses`, one per poll. */
function bridgeAnswering(statuses) {
  let polls = 0;
  const calls = [];
  globalThis.fetch = vi.fn(async (url) => {
    calls.push(url);
    if (url.endsWith("/api/connect")) {
      return { ok: true, json: async () => ({ context: {}, info: {} }) };
    }
    if (url.endsWith("/api/info")) {
      const status = statuses[Math.min(polls, statuses.length - 1)];
      polls += 1;
      return { ok: true, json: async () => ({ connection_status: status, canvas: { x_um: [0, 10], y_um: [0, 5] } }) };
    }
    throw new Error(`unexpected ${url}`);
  });
  return calls;
}

describe("the live connect", () => {
  const realFetch = globalThis.fetch;
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { vi.useRealTimers(); globalThis.fetch = realFetch; });

  it("puts the keys up first, answers each once, and resolves with the info when none is pending", async () => {
    const calls = bridgeAnswering([
      { driver: "mock", client: PENDING, stage: PENDING },
      { driver: "mock", client: "mock-client", stage: PENDING },
      { driver: "mock", client: "mock-client", stage: "x 0 · y 0" },
    ]);
    const seen = { keys: null, answers: [] };
    const done = backend.connect({ instrument: "mock" }, {
      onChecks: (keys) => { seen.keys = keys; },
      onCheck: (k, value) => { seen.answers.push([k, value]); },
    });
    await vi.runAllTimersAsync();
    const { info } = await done;
    expect(seen.keys).toEqual(["driver", "client", "stage"]);
    expect(seen.answers).toEqual([[0, "mock"], [1, "mock-client"], [2, "x 0 · y 0"]]);
    expect(info.canvas).toEqual({ x_um: [0, 10], y_um: [0, 5] });
    expect(calls.filter((u) => u.endsWith("/api/info"))).toHaveLength(3);
  });

  it("rejects naming the check that failed, after showing it", async () => {
    bridgeAnswering([
      { driver: "mock", storage: PENDING },
      { driver: "mock", storage: "failed — not writable" },
    ]);
    const answers = [];
    const done = backend.connect({ instrument: "mock" }, { onCheck: (k, v) => answers.push([k, v]) });
    const outcome = done.catch((why) => why);
    await vi.runAllTimersAsync();
    const why = await outcome;
    expect(why).toBeInstanceOf(Error);
    expect(why.message).toBe("storage: failed — not writable");
    expect(answers).toEqual([[0, "mock"], [1, "failed — not writable"]]);
  });

  it("asks the bridge for info and xyz by their routes", async () => {
    const calls = bridgeAnswering([{ driver: "mock" }]);
    globalThis.fetch.mockImplementationOnce(async (url) => {
      calls.push(url);
      return { ok: true, json: async () => ({ x: { value: 1 }, y: { value: 2 }, z: { value: 3 } }) };
    });
    const xyz = await backend.getXyz();
    expect(xyz.x.value).toBe(1);
    expect(calls.at(-1)).toMatch(/\/api\/xyz$/);
  });

  it("drives the stage through the same route, as a post", async () => {
    const calls = bridgeAnswering([{ driver: "mock" }]);
    let sent = null;
    globalThis.fetch.mockImplementationOnce(async (url, how) => {
      calls.push(url);
      sent = { method: how?.method, body: JSON.parse(how?.body ?? "null") };
      return { ok: true, json: async () => ({ x: { value: 900 }, y: { value: 800 }, z: { value: 7 } }) };
    });
    /* The controller's two verbs on one noun: `get_xyz` reads it, `set_xyz`
       drives it, and the method is what says which. */
    const at = await backend.setXyz({ x: 900, y: 800, z: 7 });
    expect(calls.at(-1)).toMatch(/\/api\/xyz$/);
    expect(sent.method).toBe("POST");
    expect(sent.body).toEqual({ x: 900, y: 800, z: 7 });
    /* Answered with where the stage ended up, not with what was asked for. */
    expect(at.x.value).toBe(900);
  });
});
