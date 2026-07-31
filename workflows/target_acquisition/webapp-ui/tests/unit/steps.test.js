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
  /* A step that says nothing gets the canvas, because nearly every step happens
     on the stage. A step that says what it wants gets exactly that — see the
     viewer step, whose whole content is a picture and which wants no panel of
     controls beside it. Both halves are checked, because the first used to be
     the only rule and there was then no way to write the second kind of step. */
  it("a step that says nothing gets the canvas", () => {
    for (const wf of Object.keys(WORKFLOWS)) {
      for (const s of WORKFLOWS[wf].steps) {
        if (!s.panels) expect(panelsFor(s)[0]).toBe("canvas");
      }
    }
  });

  it("a step that names its modules gets those and nothing else", () => {
    expect(panelsFor({ id: "x", panels: ["viewer"] })).toEqual(["viewer"]);
    // Naming modules wins over a widget, so a step cannot ask for two things
    // and quietly be given three.
    expect(panelsFor({ id: "x", panels: ["viewer"], widget: "focus" })).toEqual(["viewer"]);
  });

  it("a step with its own widget adds exactly one", () => {
    const byId = (id) => WORKFLOWS.target_acquisition.steps.find((s) => s.id === id);
    expect(panelsFor(byId("focus"))).toEqual(["canvas", "focus"]);
    expect(panelsFor(byId("detect"))).toEqual(["canvas", "detect"]);
    expect(panelsFor(byId("scan"))).toEqual(["canvas"]);
  });
});

describe("workflows compose the catalogue rather than restating it", () => {
  it("offers four", () => {
    expect(Object.keys(WORKFLOWS)).toEqual(
      ["target_acquisition", "overview_only", "focus_check", "viewer_only"]);
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

  /* A step that offers an action has to be able to carry it out, which is what
     this catches: a button with nothing behind it, or work with no way to ask
     for it.

     Not every step offers one, though, and that is not a gap. Some steps are
     finished by doing the thing they are about — the carrier is settled by being
     configured, and the viewer step is a picture to look at — so there is nothing
     left to press and a button would only ask the operator to confirm what they
     have already done. Those steps declare no button and no work, and the frame
     draws no action for them. */
  it("a step that offers an action can carry it out", () => {
    for (const wf of Object.keys(WORKFLOWS)) {
      for (const s of WORKFLOWS[wf].steps) {
        if (!s.button && !s.run) continue;
        expect(typeof s.run, `${wf}/${s.id}`).toBe("function");
        expect(s.button, `${wf}/${s.id}`).toBeTruthy();
      }
    }
  });
});

/* The canvas is being built once and put into workflows afterwards, so the first
   place it goes is a workflow of its own with nothing else in it. That makes it
   something an operator can open and try, in the real window, without an
   acquisition happening around it — and it is deliberately kept out of target
   acquisition, where every question about the picture would become a question
   about the run. */
describe("the viewer stands on its own", () => {
  const steps = WORKFLOWS.viewer_only.steps;

  it("is one step, and only one", () => {
    expect(steps.length).toBe(1);
    expect(steps[0].id).toBe("viewer");
  });

  it("wants the picture and nothing beside it", () => {
    expect(panelsFor(steps[0])).toEqual(["viewer"]);
  });

  it("has nothing to run, because standing on it is the whole of it", () => {
    expect(steps[0].run).toBeUndefined();
    expect(steps[0].button).toBeUndefined();
  });

  it("says in plain words what it is for", () => {
    expect(WORKFLOWS.viewer_only.name).toBe("Viewer on its own");
    expect(steps[0].title).toBe("Look at the run");
    expect(steps[0].why).toMatch(/canvas/);
  });

  it("leaves target acquisition exactly as it was", () => {
    expect(ids("target_acquisition")).not.toContain("viewer");
    for (const s of WORKFLOWS.target_acquisition.steps) expect(s.panels).toBeUndefined();
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
