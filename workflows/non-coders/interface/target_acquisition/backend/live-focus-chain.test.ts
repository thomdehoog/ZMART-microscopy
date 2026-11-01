/**
 * The live backend's focus map, point after point: each search can begin at
 * the height the page found at the point before. The bridge is a fake
 * `fetch` that records where each point was driven.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { backend } from "./live.ts";
import { aBridge, ok, refused, type Answer, type Parsed } from "../testing/fake-bridge.ts";

/** A bridge that finds the tissue 10 µm below wherever each stack began.
    `first` may answer a route before it does, for a bridge that refuses or hangs. */
function bridgeMeasuringFocus(first: (route: string) => Answer | Promise<Answer | undefined> | undefined = () => undefined) {
  const drives: Parsed[] = [];
  const { calls } = aBridge(async (route, body) => {
    const instead = await first(route);
    if (instead) return instead;
    if (route === "/api/target_acquisition/focus/begin") {
      return ok({ labels: Array.from({ length: body.of }, (_, i) => `P${i}`) });
    }
    if (route === "/api/target_acquisition/xyz") {
      drives.push(body);
      return ok({ x: { position: body.x }, y: { position: body.y }, z: { position: body.z ?? 0 } });
    }
    if (route === "/api/target_acquisition/acquire") return ok({ success: true, output: { position_label: body.position_label } });
    if (route === "/api/target_acquisition/focus/score") {
      return ok({ ...body.point, z: body.centre - 10, zAuto: body.centre - 10, lost: false });
    }
    if (route === "/api/target_acquisition/focus/end") return ok({});
    throw new Error(`unexpected ${route}`);
  });
  return { drives, calls };
}

describe("the live focus map", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it("begins each search where beginAt says, over the point's own startZ", async () => {
    const { drives } = bridgeMeasuringFocus();
    const found: (number | null)[] = [];
    await backend.measureFocus(
      [{ x: 1, y: 1, startZ: -50 }, { x: 2, y: 2, startZ: -50 }, { x: 3, y: 3, startZ: -50 }],
      {
        metric: "brenner",
        onPoint: (point) => found.push(point.z),
        beginAt: (index) => (index ? found[index - 1] : undefined),
      },
    );
    /* The first point has nothing before it and keeps its own start; each
       later one starts at the height the one before it found. */
    expect(drives.map((d) => d.z)).toEqual([-50, -60, -70]);
  });

  it("keeps the microscope's own sentence on a point it would not drive to", async () => {
    /* The review of 10 October, finding 6: the reason went to the console,
       which the window does not show, and the point then read as a search
       that found no peak. */
    bridgeMeasuringFocus((route) => (route === "/api/target_acquisition/xyz"
      ? refused(409, { error: "the stage cannot go beyond its travel" })
      : undefined));
    const { points } = await backend.measureFocus([{ x: 1, y: 1 }], { metric: "brenner" });
    expect(points[0]).toMatchObject({ lost: true, z: null, refused: "the stage cannot go beyond its travel" });
  });

  it("reaches a scoring that hangs: the bridge is asked to stop, and the cut point is not kept", async () => {
    /* The review of 10 October, finding 16. The bridge's stop puts the
       analysis down, which makes the hung score answer with an error; that
       point was cut off by the operator's own hand, so it is not a "lost"
       point with the microscope's reason, it is simply not measured. */
    let release: (() => void) | null = null;
    const { calls } = bridgeMeasuringFocus(async (route) => {
      if (route === "/api/target_acquisition/focus/score") {
        await new Promise<void>((resolve) => { release = resolve; });
        return refused(500, { error: "Engine has been shut down" });
      }
      if (route === "/api/target_acquisition/focus/stop") {
        release?.();
        return ok({ running: true });
      }
      return undefined;
    });
    const asked = () => calls.map(([route]) => route);
    const run = backend.measureFocus([{ x: 1, y: 1 }, { x: 2, y: 2 }], { metric: "brenner" });
    while (!release) await new Promise((resolve) => setTimeout(resolve, 1));
    await backend.stopFocusMeasure();
    const { points, stopped } = await run;
    expect(asked()).toContain("/api/target_acquisition/focus/stop");
    expect(stopped).toBe(true);
    expect(points).toEqual([]);
    expect(asked().filter((route) => route === "/api/target_acquisition/xyz")).toHaveLength(1);
  });

  it("keeps the point's own startZ when beginAt has no answer", async () => {
    const { drives } = bridgeMeasuringFocus();
    await backend.measureFocus([{ x: 1, y: 1, startZ: -50 }, { x: 2, y: 2 }], {
      metric: "brenner", beginAt: () => undefined,
    });
    expect(drives[0].z).toBe(-50);
    expect("z" in drives[1]).toBe(false);
  });
});
