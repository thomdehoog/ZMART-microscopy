/**
 * The live backend's connect: it opens the session through the bridge and
 * then watches the driver's own connection checks answer, by polling
 * `get_info().connection_status` until nothing is pending. The bridge is a
 * fake `fetch` here; what is pinned is the contract the page relies on —
 * keys first, each answer once, resolve when done, reject naming a failure.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PENDING } from "../microscope/connection-status.ts";
import { backend } from "./live.ts";
import { aBridge, ok } from "../testing/fake-bridge.ts";

/** A bridge whose `get_info` answers walk through `statuses`, one per poll;
    its stage answers a read at 1, 2, 3 and a drive where it was sent. */
function bridgeAnswering(statuses: Record<string, string>[]) {
  let polls = 0;
  const sent: { method?: string; body: unknown }[] = [];
  const { calls } = aBridge((route, body, url, init) => {
    if (route === "/api/target_acquisition/connect") return ok({ context: {}, info: {} });
    if (route === "/api/target_acquisition/info") {
      const status = statuses[Math.min(polls, statuses.length - 1)];
      polls += 1;
      return ok({ connection_status: status, setup: { saving: { done: true, says: "D:/runs" } } });
    }
    if (route === "/api/target_acquisition/xyz" && !body) return ok({ x: { position: 1 }, y: { position: 2 }, z: { position: 3 } });
    if (route === "/api/target_acquisition/xyz") {
      sent.push({ method: init?.method, body });
      return ok({ x: { position: body.x }, y: { position: body.y }, z: { position: body.z } });
    }
    throw new Error(`unexpected ${url}`);
  });
  return { calls, sent };
}

describe("the live connect", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("puts the keys up first, answers each once, and resolves with the info when none is pending", async () => {
    const { calls } = bridgeAnswering([
      { driver: "mock", client: PENDING, stage: PENDING },
      { driver: "mock", client: "mock-client", stage: PENDING },
      { driver: "mock", client: "mock-client", stage: "x 0 · y 0" },
    ]);
    const seen: { keys: string[] | null; answers: [number, string][] } = { keys: null, answers: [] };
    const done = backend.connect({ instrument: "mock" }, {
      onChecks: (keys) => { seen.keys = keys; },
      onCheck: (k, value) => { seen.answers.push([k, value]); },
    });
    await vi.runAllTimersAsync();
    const { info } = await done;
    expect(seen.keys).toEqual(["driver", "client", "stage"]);
    expect(seen.answers).toEqual([[0, "mock"], [1, "mock-client"], [2, "x 0 · y 0"]]);
    expect(info).toMatchObject({ setup: { saving: { says: "D:/runs" } } });
    expect(calls.filter(([route]) => route === "/api/target_acquisition/info")).toHaveLength(3);
  });

  it("rejects naming the check that failed, after showing it", async () => {
    bridgeAnswering([
      { driver: "mock", storage: PENDING },
      { driver: "mock", storage: "failed — not writable" },
    ]);
    const answers: [number, string][] = [];
    const done = backend.connect({ instrument: "mock" }, { onCheck: (k, v) => answers.push([k, v]) });
    const outcome = done.catch((why: unknown) => why);
    await vi.runAllTimersAsync();
    const why = await outcome;
    expect(why).toBeInstanceOf(Error);
    expect((why as Error).message).toBe("storage: failed — not writable");
    expect(answers).toEqual([[0, "mock"], [1, "failed — not writable"]]);
  });

  it("hands the bridge what the operator typed: host, client, config, password and the output folder", async () => {
    const { calls } = bridgeAnswering([{ driver: "mock" }]);
    const done = backend.connect({
      instrument: "stellaris", host: "10.0.0.9", client: "zmart", config: "C:/scope/setup.xml", password: "hunter2",
      outputRoot: "D:/runs",
    });
    await vi.runAllTimersAsync();
    await done;
    expect(calls[0]).toEqual(["/api/target_acquisition/connect", {
      instrument: "stellaris", host: "10.0.0.9", client: "zmart", config: "C:/scope/setup.xml", password: "hunter2",
      output_root: "D:/runs", experiment: "target-acquisition",
    }]);
  });

  it("lists the instruments as the bridge does: each with its settings, and where the runs went last", async () => {
    const answer = {
      instruments: [{ name: "stellaris", settings: { host: "10.0.0.5", password: null } }],
      output_root: "D:/runs",
    };
    aBridge(() => ok(answer));
    expect(await backend.instruments()).toEqual(answer);
  });

  it("asks the bridge for info and xyz by their routes", async () => {
    const { calls } = bridgeAnswering([{ driver: "mock" }]);
    const xyz = await backend.get_xyz();
    expect(xyz.x.position).toBe(1);
    expect(calls.at(-1)?.[0]).toBe("/api/target_acquisition/xyz");
  });

  it("drives the stage through the same route, as a post", async () => {
    const { calls, sent } = bridgeAnswering([{ driver: "mock" }]);
    /* The controller's two verbs on one noun: `get_xyz` reads it, `set_xyz`
       drives it, and the method is what says which. */
    const at = await backend.set_xyz({ x: 900, y: 800, z: 7 });
    expect(calls.at(-1)?.[0]).toBe("/api/target_acquisition/xyz");
    expect(sent).toEqual([{ method: "POST", body: { x: 900, y: 800, z: 7 } }]);
    /* Answered with where the stage ended up, not with what was asked for. */
    expect(at.x.position).toBe(900);
  });
});
