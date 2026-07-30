import { describe, it, expect } from "vitest";
import {
  numbered, firstIncomplete, isReachable, blockedBecause, panelsFor,
} from "../../src/frame/steps.js";
import { WORKFLOWS } from "../../src/workflows/index.js";
import { mockBackend } from "../../src/backend/mock.js";

const ids = (wf) => WORKFLOWS[wf].steps.map((s) => s.id);

describe("numbering is derived, so reordering costs nothing", () => {
  it("numbers by position", () => {
    expect(numbered([{ id: "a" }, { id: "b" }, { id: "c" }]).map((s) => s.n))
      .toEqual(["1", "2", "3"]);
  });

  it("lets sub-steps opt out and does not reuse their number", () => {
    const out = numbered([{ id: "a" }, { id: "b", n: "2a" }, { id: "c", n: "2b" }, { id: "d" }]);
    expect(out.map((s) => s.n)).toEqual(["1", "2a", "2b", "3"]);
  });

  it("gives target acquisition ten numbers across eleven rows", () => {
    const ns = WORKFLOWS.target_acquisition.steps.map((s) => s.n);
    expect(ns).toEqual(["1", "2", "3a", "3b", "4", "5", "6", "7", "8", "9", "10"]);
  });
});

describe("ordering", () => {
  const steps = WORKFLOWS.target_acquisition.steps;

  it("only the next unfinished step is reachable", () => {
    const done = new Set(["connect"]);
    expect(isReachable(steps, done, 0)).toBe(true);
    expect(isReachable(steps, done, 1)).toBe(true);
    expect(isReachable(steps, done, 2)).toBe(false);
  });

  it("finds the first gap, not the last completed step", () => {
    expect(firstIncomplete(steps, new Set(["connect", "origin"]))).toBe(2);
    expect(firstIncomplete(steps, new Set())).toBe(0);
  });
});

describe("readiness belongs to the step, not the frame", () => {
  const byId = (id) => WORKFLOWS.target_acquisition.steps.find((s) => s.id === id);
  const run = (over = {}) => ({
    running: null, focus: { strategy: "plane", points: [] },
    detect: { tested: false }, gated: new Set(), ...over,
  });

  it("focus wants three points", () => {
    expect(blockedBecause(byId("focus"), run())).toMatch(/at least 3/);
    expect(blockedBecause(byId("focus"), run({
      focus: { strategy: "plane", points: [1, 2, 3] },
    }))).toBeNull();
  });

  it("a fixed height needs no points at all", () => {
    expect(blockedBecause(byId("focus"), run({
      focus: { strategy: "fixed", points: [] },
    }))).toBeNull();
  });

  it("detection wants a tile tested first", () => {
    expect(blockedBecause(byId("detect"), run())).toMatch(/one tile/);
    expect(blockedBecause(byId("detect"), run({ detect: { tested: true } }))).toBeNull();
  });

  it("selection and acquisition want something gated", () => {
    expect(blockedBecause(byId("select"), run())).toMatch(/nothing gated/);
    expect(blockedBecause(byId("acquire"), run({ gated: new Set([1]) }))).toBeNull();
  });

  it("a step with no rule is always ready", () => {
    expect(blockedBecause(byId("connect"), run())).toBeNull();
  });

  it("nothing runs while something else is", () => {
    expect(blockedBecause(byId("connect"), run({ running: "focus" }))).toMatch(/another step/);
  });
});

describe("panels follow the step", () => {
  it("the canvas is always there", () => {
    for (const wf of Object.keys(WORKFLOWS)) {
      for (const s of WORKFLOWS[wf].steps) expect(panelsFor(s)[0]).toBe("canvas");
    }
  });

  it("a step with its own widget adds exactly one", () => {
    const byId = (id) => WORKFLOWS.target_acquisition.steps.find((s) => s.id === id);
    expect(panelsFor(byId("focus"))).toEqual(["canvas", "focus"]);
    expect(panelsFor(byId("detect"))).toEqual(["canvas", "detect"]);
    expect(panelsFor(byId("scan"))).toEqual(["canvas"]);
  });
});

describe("workflows compose the catalogue rather than restating it", () => {
  it("offers three", () => {
    expect(Object.keys(WORKFLOWS)).toEqual(
      ["target_acquisition", "overview_only", "focus_check"]);
  });

  it("shares steps by identity, so a fix reaches every workflow", () => {
    const a = WORKFLOWS.target_acquisition.steps.find((s) => s.id === "connect");
    const b = WORKFLOWS.overview_only.steps.find((s) => s.id === "connect");
    expect(a.why).toBe(b.why);
    expect(a.run).toBe(b.run);
  });

  it("overview only never asks for an analysis panel", () => {
    expect(ids("overview_only")).not.toContain("select");
    for (const s of WORKFLOWS.overview_only.steps) expect(s.widget).toBeFalsy();
  });

  it("every step names a widget the registry can supply, or none", () => {
    const known = new Set(["canvas", "focus", "detect", "analysis", "gallery"]);
    for (const wf of Object.keys(WORKFLOWS)) {
      for (const s of WORKFLOWS[wf].steps) {
        if (s.widget) expect(known.has(s.widget), `${s.id} -> ${s.widget}`).toBe(true);
      }
    }
  });

  it("every step can actually run: it has a button and a run function", () => {
    for (const wf of Object.keys(WORKFLOWS)) {
      for (const s of WORKFLOWS[wf].steps) {
        expect(typeof s.run, `${wf}/${s.id}`).toBe("function");
        expect(s.button, `${wf}/${s.id}`).toBeTruthy();
      }
    }
  });
});

describe("the scan step reports both a count and a picture", () => {
  const scan = WORKFLOWS.target_acquisition.steps.find((s) => s.id === "scan");

  /* Nothing on disk announces a saved tile — the images are declared at their
     full size before any of them exists — so the picture only learns that there
     is more to see when the step says so. This is that wiring, and it is worth a
     test because it is invisible: everything still looks right if the picture is
     never told, right up until the operator watches a scan and nothing appears. */
  it("tells the picture on every position the scan reports", async () => {
    const seen = [];
    const looks = [];
    await scan.run({
      backend: {
        async scanOverview({ onProgress }) {
          onProgress(1, 3); onProgress(2, 3); onProgress(3, 3);
          return "3 / 3 tiles";
        },
      },
      update: (patch, note) => seen.push([patch.tiles, note]),
      note: () => {},
      picture: { tileMayHaveLanded: () => looks.push(true) },
    });

    expect(seen).toEqual([[1, "1 / 3 tiles"], [2, "2 / 3 tiles"], [3, "3 / 3 tiles"]]);
    expect(looks.length, "one for each position saved").toBe(3);
  });

  it("runs perfectly well with no picture to tell, which is the usual case", async () => {
    const notes = [];
    await scan.run({
      backend: {
        async scanOverview({ onProgress }) { onProgress(1, 1); return "1 / 1 tiles"; },
      },
      update: () => {},
      note: (text) => notes.push(text),
    });
    expect(notes).toEqual(["1 / 1 tiles"]);
  });
});

describe("the backend seam", () => {
  it("detection uses one rule for a tile and for the sample", () => {
    const settings = { algo: "cellpose", diameter: 18, cellprob: 0 };
    const cell = { r: 7, area: 154, intensity: 0.8 };
    expect(mockBackend.detects(settings, cell)).toBe(true);
    expect(mockBackend.detects({ ...settings, diameter: 60 }, cell)).toBe(false);
  });

  it("a dimmer cell falls out as cell probability rises", () => {
    const cell = { r: 7, area: 154, intensity: 0.5 };
    expect(mockBackend.detects({ algo: "cellpose", diameter: 18, cellprob: 0 }, cell)).toBe(true);
    expect(mockBackend.detects({ algo: "cellpose", diameter: 18, cellprob: 4 }, cell)).toBe(false);
  });

  it("threshold detection is size and brightness, nothing else", () => {
    const settings = { algo: "threshold", thresh: 0.4, minArea: 100 };
    expect(mockBackend.detects(settings, { area: 200, intensity: 0.5, r: 8 })).toBe(true);
    expect(mockBackend.detects(settings, { area: 50, intensity: 0.5, r: 4 })).toBe(false);
    expect(mockBackend.detects(settings, { area: 200, intensity: 0.2, r: 8 })).toBe(false);
  });
});
