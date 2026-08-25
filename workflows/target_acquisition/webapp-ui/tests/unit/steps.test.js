/* The workflows, as the operator meets them.
 *
 * Everything here reads the folders under `src/workflows/` — every folder with
 * a `flow.js` is one workflow — through the same `assembleWorkflows` that
 * `src/frame/window/main.js` uses. That is the point of this suite: for a while the
 * workflows were declared twice, once here and once inside `main.js`, and
 * these tests went green against a list the page did not offer while the page
 * offered a list no test had ever seen. Neither half looked wrong on its own.
 *
 * So when a step is added, removed or reworded below, the page changes with it —
 * and if it does not, something has gone back to being written down twice.
 */

import { describe, it, expect } from "vitest";
import {
  numbered, firstIncomplete, isReachable, blockedBecause, panelsFor,
} from "../../src/frame/steps.js";
import { assembleWorkflows } from "../../src/frame/finding-workflows.js";
import { connect } from "../../src/workflows/target_acquisition/steps/1_connect/step.js";
import { initialScanfields } from "../../src/workflows/target_acquisition/steps/3_define_scan_area/step.js";
import { scanOverview } from "../../src/workflows/target_acquisition/steps/5_scan_the_overview/step.js";
import { mockBackend } from "../../src/workflows/target_acquisition/microscope/mock.js";
import { emptySlot, withRecording } from "../../src/workflows/target_acquisition/microscope/recordings.js";
import { sampleReading } from "../../src/workflows/target_acquisition/microscope/microscopes.js";

const { WORKFLOWS } = assembleWorkflows(
  import.meta.glob("../../src/workflows/*/flow.js", { eager: true }),
);

const ids = (wf) => WORKFLOWS[wf].steps.map((s) => s.id);
const stepOf = (wf, id) => WORKFLOWS[wf].steps.find((s) => s.id === id);

describe("numbering is derived, so reordering costs nothing", () => {
  it("numbers by position", () => {
    expect(numbered([{ id: "a" }, { id: "b" }, { id: "c" }]).map((s) => s.n))
      .toEqual(["1", "2", "3"]);
  });

  it("lets sub-steps opt out and does not reuse their number", () => {
    const out = numbered([{ id: "a" }, { id: "b", n: "2a" }, { id: "c", n: "2b" }, { id: "d" }]);
    expect(out.map((s) => s.n)).toEqual(["1", "2a", "2b", "3"]);
  });

  it("numbers target acquisition straight through, one to eight", () => {
    expect(WORKFLOWS.target_acquisition.steps.map((s) => s.n))
      .toEqual(["1", "2", "3", "4", "5", "6", "7", "8"]);
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
    // every step of a real run waits for the one before it
    expect(firstIncomplete(steps, new Set(["connect", "carrier"]))).toBe(2);
    expect(firstIncomplete(steps, new Set())).toBe(0);
  });

  /* A step that only shows the operator something produces nothing, so there is
     nothing for the steps after it to wait for and it says so. Without this a
     workflow made of such steps would be stuck on its first one for ever: the
     operator has no way to finish a step there is nothing to finish. */
  it("a step that holds nothing up lets the run walk straight past it", () => {
    const shown = [
      { id: "look", nothingWaitsOnThis: true },
      { id: "look-again", nothingWaitsOnThis: true },
      { id: "act" },
      { id: "after" },
    ];
    expect(firstIncomplete(shown, new Set())).toBe(2);
    expect(isReachable(shown, new Set(), 0)).toBe(true);
    expect(isReachable(shown, new Set(), 1)).toBe(true);
    expect(isReachable(shown, new Set(), 2)).toBe(true);
    // and it does not open the gate for what comes after the step that does act
    expect(isReachable(shown, new Set(), 3)).toBe(false);
  });
});

describe("readiness belongs to the step, not the frame", () => {
  /* These are the rules an operator actually meets: the greyed-out button and
     the short phrase beside it saying what is still missing. The frame only
     asks; each step answers for itself. */
  const byId = (id) => stepOf("target_acquisition", id);
  /* Real slots, read the way the panel reads them: a hand-made stand-in with
     the right shape is how a gate went on asking for a field the recordings
     stopped having while this suite stayed green. */
  const recorded = (type) => withRecording(emptySlot(type), {
    name: "overview",
    reading: sampleReading(type, 0),
  });
  /* A run standing on the focus step with a point or two down. The points are
     what the button measures, so the rules about them are rules about a run
     that has some. */
  const run = (over = {}) => ({
    focus: { strategy: "plane", points: [1] },
    focusPreset: recorded("autofocus"),
    detect: { tested: false },
    gated: new Set(),
    targetType: recorded("acquisition"),
    ...over,
  });

  /* The press stays where it is with nothing to measure and says what it waits
     for. It used to vanish instead, which made clearing the points look like it
     had broken the step. */
  it("with no points, the press says what it waits for", () => {
    expect(blockedBecause(byId("focus"), run({
      focus: { strategy: "plane", points: [] },
    }))).toMatch(/no points to measure/);
  });

  it("the focus strategy wants its focussing preset recorded first", () => {
    expect(blockedBecause(byId("focus"), run({
      focus: { strategy: "plane", points: [1, 2, 3] },
      focusPreset: emptySlot("autofocus"),
    }))).toMatch(/focussing preset/);
  });

  it("detection wants a tile tested first", () => {
    expect(blockedBecause(byId("detect"), run())).toMatch(/one tile/);
    expect(blockedBecause(byId("detect"), run({ detect: { tested: true } }))).toBeNull();
  });

  it("refinement and acquisition want something gated", () => {
    expect(blockedBecause(byId("select"), run())).toMatch(/nothing gated/);
    expect(blockedBecause(byId("acquire"), run())).toMatch(/nothing gated/);
    expect(blockedBecause(byId("acquire"), run({ gated: new Set([1]) }))).toBeNull();
  });

  it("acquisition also wants the acquisition type recorded", () => {
    expect(blockedBecause(byId("acquire"),
      run({ gated: new Set([1]), targetType: emptySlot("acquisition") })))
      .toMatch(/acquisition type/);
  });

  it("a step with no rule is always ready", () => {
    expect(blockedBecause(byId("connect"), run())).toBeNull();
    expect(blockedBecause(byId("carrier"), run())).toBeNull();
  });
});

describe("panels follow the step", () => {
  /* What each step is given on screen. The canvas is the microscope's own
     limits drawn to scale, and it is there from the first step: every step
     keeps the picture on the left and its own controls in the channel. */
  const panelsOf = (wf) =>
    Object.fromEntries(WORKFLOWS[wf].steps.map((s, i) => [s.id, panelsFor(WORKFLOWS[wf].steps, i)]));

  it("gives target acquisition the panels the operator sees", () => {
    expect(panelsOf("target_acquisition")).toEqual({
      connect: ["canvas"],
      carrier: ["canvas"],
      scanfields: ["canvas"],
      focus: ["canvas"],
      scan: ["canvas"],
      detect: ["canvas"],
      select: ["canvas"],
      acquire: ["canvas"],
    });
  });

  it("puts the canvas on stage from the first step of every run", () => {
    for (const wf of ["target_acquisition", "overview_only", "focus_surface_check"]) {
      expect(panelsOf(wf).connect).toContain("canvas");
      expect(panelsOf(wf).carrier).toContain("canvas");
    }
  });

  it("gives the whole window to a step in a workflow that never asks for the canvas", () => {
    expect(panelsOf("canvas_demonstration")).toEqual({
      "canvas-picture": ["viewer-canvas"],
    });
  });
});

describe("workflows compose the catalogue rather than restating it", () => {
  it("offers four", () => {
    expect(Object.keys(WORKFLOWS)).toEqual(
      ["target_acquisition", "canvas_demonstration", "focus_surface_check", "overview_only"]);
  });

  /* The order an operator walks, spelled out. If a step moves, is dropped, or
     is added, this is where it shows — and because the page reads the same
     declaration, what it shows is what the page will do. */
  it("walks target acquisition in this order", () => {
    expect(ids("target_acquisition")).toEqual([
      "connect", "carrier", "scanfields", "focus",
      "scan", "detect", "select", "acquire",
    ]);
  });

  it("walks the shorter runs in this order", () => {
    expect(ids("overview_only")).toEqual([
      "connect", "carrier", "scanfields", "scan", "save"]);
    expect(ids("focus_surface_check")).toEqual([
      "connect", "carrier", "scanfields", "focus", "save"]);
  });

  it("names every workflow in plain words for the chooser", () => {
    expect(Object.values(WORKFLOWS).map((w) => w.name)).toEqual([
      "Target acquisition", "Canvas demonstration", "Focus surface check",
      "Overview only"]);
    for (const w of Object.values(WORKFLOWS)) expect(w.blurb).toBeTruthy();
  });

  it("shares a step's wording, so a fix reaches every workflow at once", () => {
    for (const wf of ["target_acquisition", "overview_only", "focus_surface_check"]) {
      expect(stepOf(wf, "connect").why).toBe(connect.why);
      expect(stepOf(wf, "scanfields").why).toBe(initialScanfields.why);
    }
  });

  /* A workflow may explain a shared step in its own terms — a calibration run
     is not saving what an imaging run saves — but it may not quietly change
     what the step does while it is at it. */
  it("lets a workflow reword a step without changing what it does", () => {
    const here = stepOf("target_acquisition", "scan");
    const there = stepOf("overview_only", "scan");
    expect(there.why).not.toBe(here.why);
    expect(there.mode).toBe(here.mode);
    expect(there.btn).toBe(here.btn);
    expect(there.panels).toEqual(here.panels);
    expect(there.mode).toBe(scanOverview.mode);
  });

  it("overview only never asks for an analysis panel", () => {
    expect(ids("overview_only")).not.toContain("select");
    for (const s of WORKFLOWS.overview_only.steps) {
      expect(s.panels).not.toContain("analysis");
    }
  });

  it("every step names panels the page can supply", () => {
    /* Every working step is a channel beside the canvas now, not a panel —
       a step that named one of the old panels here would ask for a tab that
       is gone. */
    const known = new Set(["canvas", "viewer-canvas"]);
    for (const wf of Object.keys(WORKFLOWS)) {
      for (const s of WORKFLOWS[wf].steps) {
        for (const p of s.panels ?? []) expect(known.has(p), `${s.id} -> ${p}`).toBe(true);
      }
    }
  });

  /* `mode` is how a step says which piece of work the page should carry out for
     it. A mode nobody recognises is a silent failure: the button still appears,
     the step still completes, and nothing happens in between. */
  it("every step names work the page knows how to do, or none", () => {
    const known = new Set([
      "carrier", "scanfields", "focus", "scan", "detect", "select", "targets"]);
    for (const wf of Object.keys(WORKFLOWS)) {
      for (const s of WORKFLOWS[wf].steps) {
        if (s.mode) expect(known.has(s.mode), `${s.id} -> ${s.mode}`).toBe(true);
      }
    }
  });

  /* A step that offers an action has to have something behind it. Not every step
     does, and that is not a gap: some are finished by doing the thing they are
     about — the carrier is settled by being configured, the scan fields by being
     drawn, the viewer by being looked at — so a button would only ask the
     operator to confirm what they have already done. */
  it("a step that offers a button has work behind it", () => {
    for (const wf of Object.keys(WORKFLOWS)) {
      for (const s of WORKFLOWS[wf].steps) {
        if (!s.btn) continue;
        expect(s.mode ?? s.id, `${wf}/${s.id}`).toBeTruthy();
        expect(typeof s.ms, `${wf}/${s.id} says how long it takes`).toBe("number");
      }
    }
  });
});

/* The canvas is being built once and put into workflows afterwards, so the first
   place it goes is a workflow of its own with nothing else in it. That makes it
   something an operator can open and try, in the real window, without an
   acquisition happening around it — and it is deliberately kept out of target
   acquisition, where every question about the picture would become a question
   about the run.

   It has two steps, one per drawing engine, and the point of nearly everything
   below is that neither of them can affect the other. */
describe("the canvas demonstration", () => {
  const steps = WORKFLOWS.canvas_demonstration.steps;

  /* One step, not one per engine. The engines are compared inside it, by the row
     of buttons above the picture, which keeps the view where it is as the engine
     changes — a closer comparison than two pictures that were never guaranteed to
     be looking at the same place. */
  it("is one step, with the engines compared inside it", () => {
    expect(ids("canvas_demonstration")).toEqual(["canvas-picture"]);
  });

  it("wants a picture and nothing beside it", () => {
    expect(panelsFor(steps, 0)).toEqual(["viewer-canvas"]);
  });

  it("has nothing to run, because standing on a step is the whole of it", () => {
    for (const s of steps) {
      expect(s.btn).toBeUndefined();
      expect(s.mode).toBeUndefined();
    }
  });

  /* The one that matters most. Neither step produces anything, so neither can be
     waiting on the other, and the operator may open either one first. Without
     this the second step would be greyed out for ever, because the first can
     never be marked as finished — there is nothing to finish. */
  it("lets the operator open it having done nothing", () => {
    expect(isReachable(steps, new Set(), 0)).toBe(true);
  });

  it("says in plain words that it is a demonstration rather than a run", () => {
    expect(WORKFLOWS.canvas_demonstration.name).toMatch(/demonstration/i);
    expect(WORKFLOWS.canvas_demonstration.blurb).toMatch(/not a run/i);
  });

  /* A name has to fit the rail, which is a fixed column, and no workflow name
     may be longer than the longest one this page has always carried. That is
     not fussiness about tidiness: the chooser used to take whatever width its
     longest name wanted and push the Restart button beside it off the rail
     altogether, where it could not be pressed. The layout no longer allows
     that, and this keeps the names readable rather than trailing off. */
  it("names every workflow briefly enough for the rail to show it", () => {
    for (const w of Object.values(WORKFLOWS)) {
      expect(w.name.length, `"${w.name}" is too long for the chooser`)
        .toBeLessThanOrEqual(22);
    }
  });

  /* The step names no engine, and that is the point of there being one of them.
     A step called after an engine is a promise that the engine is what the step
     is for; here the step is the picture, and which engine draws it is a button
     above it that can be changed without losing the view. */
  it("names no engine, because the engine is chosen inside the step", () => {
    expect(steps[0].title).not.toMatch(/viv|neuroglancer/i);
  });

  it("leaves target acquisition exactly as it was", () => {
    for (const s of WORKFLOWS.target_acquisition.steps) {
      expect(s.id).not.toMatch(/^canvas-/);
      expect(s.panels.some((p) => p.startsWith("viewer"))).toBe(false);
      /* And nothing in a real run may skip its place in the queue: every step
         of an acquisition produces something the next one needs. The flag that
         lets a step be walked past belongs to the bench, where a step only
         shows you something — a placeholder in a real run wearing it is an
         empty stop in the rail, which is how the one there was got dropped. */
      expect(s.nothingWaitsOnThis).toBeUndefined();
    }
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
