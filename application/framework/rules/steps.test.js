/* The workflows, as the operator meets them.
 *
 * Everything here reads the folders under `workflows/` — every folder with
 * a `flow.js` is one workflow — through the same `assembleWorkflows` that
 * `framework/window/main.js` uses. That is the point of this suite: for a while the
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
} from "../../framework/rules/steps.js";
import { assembleWorkflows } from "../../framework/rules/finding-workflows.js";
import { connect } from "../../workflows/target_acquisition/steps/connect/step.js";
import { initialScanfields } from "../../workflows/target_acquisition/steps/define_scan_area/step.js";
import { scanOverview } from "../../workflows/target_acquisition/steps/scan_the_overview/step.js";
import { emptySlot, withRecording } from "../../parts/microscope/recordings.js";
import { sampleReading } from "../../parts/microscope/settings.js";

const { WORKFLOWS } = assembleWorkflows(
  import.meta.glob("../../workflows/*/flow.js", { eager: true }),
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

  it("numbers target acquisition straight through, one to nine", () => {
    expect(WORKFLOWS.target_acquisition.steps.map((s) => s.n))
      .toEqual(["1", "2", "3", "4", "5", "6", "7", "8", "9"]);
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
    targetTiles: [],
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

  it("detection never blocks: trying a tile first is offered, not demanded", () => {
    expect(blockedBecause(byId("detect"), run())).toBeNull();
    expect(blockedBecause(byId("detect"), run({ detect: { tested: true } }))).toBeNull();
  });

  it("restriction wants something gated; acquisition wants the tiles laid", () => {
    expect(blockedBecause(byId("select"), run())).toMatch(/nothing gated/);
    expect(blockedBecause(byId("acquire"), run())).toMatch(/add the tiles/);
    expect(blockedBecause(byId("acquire"), run({ gated: new Set([1]) }))).toMatch(/add the tiles/);
    expect(blockedBecause(byId("acquire"), run({ targetTiles: [{ id: 1 }] }))).toBeNull();
  });

  it("acquisition also wants the acquisition type recorded", () => {
    expect(blockedBecause(byId("acquire"),
      run({ targetTiles: [{ id: 1 }], targetType: emptySlot("acquisition") })))
      .toMatch(/acquisition type/);
  });

  it("a step with no rule is always ready", () => {
    expect(blockedBecause(byId("connect"), run())).toBeNull();
    expect(blockedBecause(byId("carrier"), run())).toBeNull();
  });
});

describe("panels follow the step", () => {
  /* What each step is given on screen. Which panels stay once asked for is the
     workflow's own declaration, so the test reads it from there rather than
     naming the canvas: the rule is handed the keys and knows nothing about
     what any of them draws. */
  const staying = (wf) => WORKFLOWS[wf].panels.filter((p) => p.stays).map((p) => p.key);
  const panelsOf = (wf) =>
    Object.fromEntries(WORKFLOWS[wf].steps.map((s, i) =>
      [s.id, panelsFor(WORKFLOWS[wf].steps, i, staying(wf))]));

  it("gives target acquisition the panels the operator sees", () => {
    expect(panelsOf("target_acquisition")).toEqual({
      connect: ["canvas"],
      carrier: ["canvas"],
      scanfields: ["canvas"],
      focus: ["canvas"],
      scan: ["canvas"],
      detect: ["canvas"],
      gate: ["canvas"],
      select: ["canvas"],
      acquire: ["canvas"],
    });
  });

  it("a workflow that declares no panel that stays gives each step its own", () => {
    /* The point of the rule: nothing in it is about a canvas. A run whose
       steps each bring their own panel — a report, a set of forms — keeps
       none of them past the step that asked. */
    const steps = [
      { id: "one", panels: ["form"] },
      { id: "two", panels: [] },
      { id: "three", panels: ["report"] },
    ];
    expect(steps.map((_, i) => panelsFor(steps, i))).toEqual([["form"], [], ["report"]]);
  });

  it("keeps a staying panel from the step that first asks, and not before", () => {
    const steps = [
      { id: "one", panels: [] },
      { id: "two", panels: ["map"] },
      { id: "three", panels: ["notes"] },
    ];
    expect(steps.map((_, i) => panelsFor(steps, i, ["map"])))
      .toEqual([[], ["map"], ["map", "notes"]]);
  });

  it("puts the canvas on stage from the first step of every run", () => {
    for (const wf of ["target_acquisition"]) {
      expect(panelsOf(wf).connect).toContain("canvas");
      expect(panelsOf(wf).carrier).toContain("canvas");
    }
  });

});

describe("workflows compose the catalogue rather than restating it", () => {
  it("offers target acquisition first, then driver configuration", () => {
    expect(Object.keys(WORKFLOWS)).toEqual(["target_acquisition", "zmart_driver_configuration"]);
  });

  /* The five steps of setting a microscope up, in the order the four
     subsystems are published; connect is borrowed from target acquisition. */
  it("walks driver configuration in this order", () => {
    expect(ids("zmart_driver_configuration")).toEqual([
      "connect", "limits", "orientation", "calibration", "origin",
    ]);
  });

  it("a flow may say its own name, when the folder rule would get it wrong", () => {
    expect(WORKFLOWS.zmart_driver_configuration.name).toBe("ZMART driver configuration");
    expect(WORKFLOWS.target_acquisition.name).toBe("Target acquisition");
  });

  it("driver configuration brings its own backend and no canvas", () => {
    const wf = WORKFLOWS.zmart_driver_configuration;
    expect(wf.backend?.kind).toBe("setup");
    expect(wf.panels.map((p) => p.key)).toEqual(["setup"]);
    expect(WORKFLOWS.target_acquisition.backend).toBeNull();
    for (const s of wf.steps) expect(s.panels).toEqual(["setup"]);
  });

  it("every configuring step carries its own channel and its own press", () => {
    for (const s of WORKFLOWS.zmart_driver_configuration.steps.slice(1)) {
      expect(typeof s.channel?.mount, `${s.id} has a channel`).toBe("function");
      expect(s.channel.id).toBe(s.id);
      expect(s.ownButton).toBe(true);
      expect(s.ready({ done: new Set() })).toMatch(/connect/);
      expect(s.ready({ done: new Set(["connect"]) })).toBeNull();
    }
  });

  /* The order an operator walks, spelled out. If a step moves, is dropped, or
     is added, this is where it shows — and because the page reads the same
     declaration, what it shows is what the page will do. */
  it("walks target acquisition in this order", () => {
    expect(ids("target_acquisition")).toEqual([
      "connect", "carrier", "scanfields", "focus",
      "scan", "detect", "gate", "select", "acquire",
    ]);
  });


  it("names every workflow in plain words for the chooser", () => {
    expect(Object.values(WORKFLOWS).map((w) => w.name))
      .toEqual(["Target acquisition", "ZMART driver configuration"]);
    for (const w of Object.values(WORKFLOWS)) expect(w.blurb).toBeTruthy();
  });

  it("shares a step's wording, so a fix reaches every workflow at once", () => {
    for (const wf of ["target_acquisition"]) {
      expect(stepOf(wf, "connect").why).toBe(connect.why);
      expect(stepOf(wf, "scanfields").why).toBe(initialScanfields.why);
    }
  });



  it("every step names panels the page can supply", () => {
    /* Every working step is a channel beside the canvas now, not a panel —
       a step that named one of the old panels here would ask for a tab that
       is gone. */
    const known = new Set(["canvas", "setup"]);
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
      "carrier", "scanfields", "focus", "scan", "detect", "gate", "select", "targets"]);
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

/* What the real run must never carry: the bench (the canvas demonstration,
   since removed) had steps that produced nothing and could be walked past;
   a run is the opposite, every step feeding the next. */
describe("the real run", () => {
  /* A name has to fit the rail, which is a fixed column, and no workflow name
     may be longer than the longest one this page has always carried. That is
     not fussiness about tidiness: the chooser used to take whatever width its
     longest name wanted and push the Restart button beside it off the rail
     altogether, where it could not be pressed. The layout no longer allows
     that, and this keeps the names readable rather than trailing off. */
  it("names every workflow briefly enough for the rail to show it", () => {
    for (const w of Object.values(WORKFLOWS)) {
      expect(w.name.length, `"${w.name}" is too long for the chooser`)
        .toBeLessThanOrEqual(28);
    }
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

