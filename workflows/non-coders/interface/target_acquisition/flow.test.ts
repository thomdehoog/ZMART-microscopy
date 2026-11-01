/* Target acquisition's steps, as the operator meets them.

   The flow is assembled the way the page assembles it, through the
   framework's `assembleWorkflows`, and these tests read what came out: the
   steps in order, what each waits for, the panels it stands on, and the
   words it says. When a step is added, removed or reworded, the page changes
   with it, and this is where it shows. */

import { describe, it, expect } from "vitest";
import {
  firstIncomplete, isReachable, blockedBecause, panelsFor, editedAt, staleSteps,
} from "zmart-interface/framework/rules/steps.ts";
import { assembleWorkflows } from "zmart-interface/framework/rules/finding-workflows.ts";
import { freshRun, startOver } from "zmart-interface/framework/window/run-state.ts";
import { emptySlot, withRecording } from "./microscope/recordings.ts";
import { sampleReading } from "./microscope/settings.ts";
import * as threeSteps from "zmart-interface/framework/fixtures/three_steps/flow.ts";
import * as targetAcquisition from "./flow.ts";
import type { Page, Run } from "zmart-interface/api";
import type { TheRun } from "zmart-interface/framework/types.ts";

/* The readiness rules read the run; none of the ones asked about here reads
   the page as well, so none is handed one. */
const NO_PAGE = undefined as unknown as Page;

const { WORKFLOWS } = assembleWorkflows({ "target_acquisition/flow.js": targetAcquisition });

const ids = (wf: string) => WORKFLOWS[wf].steps.map((s) => s.id);
const stepOf = (wf: string, id: string) => WORKFLOWS[wf].steps.find((s) => s.id === id);

describe("numbering", () => {
  it("numbers target acquisition straight through, one to ten", () => {
    expect(WORKFLOWS.target_acquisition.steps.map((s) => s.n))
      .toEqual(["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]);
  });
});

/* A step that was settled once and then had something before it changed is
   done but stale: orange on the rail, asking to be confirmed or run again.
   Editing a step stales every done step after it and leaves the edited step
   green — the operator just settled it. */
describe("editing a step stales the ones after it", () => {
  const steps = WORKFLOWS.target_acquisition.steps;
  const all = new Set(steps.map((s) => s.id));

  it("stales every done step after the edited one, not the edited one", () => {
    const stale = editedAt(steps, all, new Set(), "scanfields");
    expect([...stale]).toEqual(["focus", "scan", "detect", "gate", "select", "acquire", "protocol"]);
  });

  it("leaves steps that are not done alone", () => {
    const done = new Set(["connect", "carrier", "scanfields", "focus"]);
    expect([...editedAt(steps, done, new Set(), "carrier")]).toEqual(["scanfields", "focus"]);
  });

  it("keeps what was already stale", () => {
    const stale = editedAt(steps, all, new Set(["acquire"]), "gate");
    expect([...stale].sort()).toEqual(["acquire", "protocol", "select"]);
  });

  it("editing the edited step again unstales it", () => {
    const stale = editedAt(steps, all, new Set(["focus", "scan"]), "focus");
    expect(stale.has("focus")).toBe(false);
    expect(stale.has("scan")).toBe(true);
  });

  it("names the stale steps in rail order", () => {
    const stale = new Set(["acquire", "focus", "connect"]);
    expect(staleSteps(steps, all, stale).map((s) => s.id)).toEqual(["connect", "focus", "acquire"]);
  });

  it("a step that is not done is never stale, whatever the set says", () => {
    expect(staleSteps(steps, new Set(["connect"]), new Set(["focus"]))).toEqual([]);
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
    expect(firstIncomplete(steps, new Set(["connect", "carrier"]))).toBe(2);
    expect(firstIncomplete(steps, new Set())).toBe(0);
  });

  it("names the step that runs the others", () => {
    expect(WORKFLOWS.target_acquisition.steps.filter((s) => s.walks).map((s) => s.id)).toEqual(["protocol"]);
  });
});

describe("readiness belongs to the step, not the frame", () => {
  /* These are the rules an operator actually meets: the greyed-out button and
     the short phrase beside it saying what is still missing. The frame only
     asks; each step answers for itself. */
  const byId = (id: string) => stepOf("target_acquisition", id);
  /* Real slots, read the way the panel reads them: a hand-made stand-in with
     the right shape is how a gate went on asking for a field the recordings
     stopped having while this suite stayed green. */
  const recorded = (type: string) => withRecording(emptySlot(type), {
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
  }) as unknown as Run; // only the keys these rules read, standing in for the whole document

  /* The press stays where it is with nothing to measure and says what it waits
     for. It used to vanish instead, which made clearing the points look like it
     had broken the step. */
  it("with no points, the press says what it waits for", () => {
    expect(blockedBecause(byId("focus"), run({
      focus: { strategy: "plane", points: [] },
    }), NO_PAGE)).toMatch(/no points to measure/);
  });

  it("the focus strategy wants its focussing preset recorded first", () => {
    expect(blockedBecause(byId("focus"), run({
      focus: { strategy: "plane", points: [1, 2, 3] },
      focusPreset: emptySlot("autofocus"),
    }), NO_PAGE)).toMatch(/focussing preset/);
  });

  it("detection never blocks: trying a tile first is offered, not demanded", () => {
    expect(blockedBecause(byId("detect"), run(), NO_PAGE)).toBeNull();
    expect(blockedBecause(byId("detect"), run({ detect: { tested: true } }), NO_PAGE)).toBeNull();
  });

  it("restriction wants something gated; acquisition wants the tiles laid", () => {
    /* Two different answers: no objects on this sample at all, and objects
       that no gate lets through. */
    expect(blockedBecause(byId("select"), run(), NO_PAGE)).toMatch(/detect objects/);
    expect(blockedBecause(byId("select"), run({ cells: new Map([[1, {}]]) }), NO_PAGE)).toMatch(/nothing gated/);
    expect(blockedBecause(byId("acquire"), run(), NO_PAGE)).toMatch(/add the tiles/);
    expect(blockedBecause(byId("acquire"), run({ gated: new Set([1]) }), NO_PAGE)).toMatch(/add the tiles/);
    expect(blockedBecause(byId("acquire"), run({ targetTiles: [{ id: 1 }] }), NO_PAGE)).toBeNull();
  });

  it("acquisition also wants the acquisition type recorded", () => {
    expect(blockedBecause(byId("acquire"),
      run({ targetTiles: [{ id: 1 }], targetType: emptySlot("acquisition") }), NO_PAGE))
      .toMatch(/acquisition type/);
  });

  it("a step with no rule is always ready", () => {
    expect(blockedBecause(byId("connect"), run(), NO_PAGE)).toBeNull();
    expect(blockedBecause(byId("carrier"), run(), NO_PAGE)).toBeNull();
  });
});

describe("panels follow the step", () => {
  const staying = (wf: string) => WORKFLOWS[wf].panels.filter((p) => p.stays).map((p) => p.key);
  const panelsOf = (wf: string) =>
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
      protocol: ["canvas"],
    });
  });

  it("puts the canvas on stage from the first step of every run", () => {
    for (const wf of ["target_acquisition"]) {
      expect(panelsOf(wf).connect).toContain("canvas");
      expect(panelsOf(wf).carrier).toContain("canvas");
    }
  });
});

describe("workflows compose the catalogue rather than restating it", () => {
  it("offers target acquisition, named from its folder", () => {
    expect(Object.keys(WORKFLOWS)).toEqual(["target_acquisition"]);
    expect(WORKFLOWS.target_acquisition.name).toBe("Target acquisition");
  });

  /* The order an operator walks, spelled out. If a step moves, is dropped, or
     is added, this is where it shows — and because the page reads the same
     declaration, what it shows is what the page will do. */
  it("walks target acquisition in this order", () => {
    expect(ids("target_acquisition")).toEqual([
      "connect", "carrier", "scanfields", "focus",
      "scan", "detect", "gate", "select", "acquire", "protocol",
    ]);
  });

  it("names every workflow in plain words for the chooser", () => {
    expect(Object.values(WORKFLOWS).map((w) => w.name))
      .toEqual(["Target acquisition"]);
    for (const w of Object.values(WORKFLOWS)) expect(w.blurb).toBeTruthy();
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
      "carrier", "scanfields", "focus", "scan", "detect", "gate", "select", "targets", "protocol"]);
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
  it("leaves target acquisition exactly as it was", () => {
    for (const s of WORKFLOWS.target_acquisition.steps) {
      expect(s.id).not.toMatch(/^canvas-/);
      expect(s.panels!.some((p: string) => p.startsWith("viewer"))).toBe(false);
      /* And nothing in a real run may skip its place in the queue: every step
         of an acquisition produces something the next one needs. The flag that
         lets a step be walked past belongs to the bench, where a step only
         shows you something — a placeholder in a real run wearing it is an
         empty stop in the rail, which is how the one there was got dropped. */
      expect(s.nothingWaitsOnThis).toBeUndefined();
    }
  });
});

/* A run of target acquisition holds its own keys beside the framework's, and
   loses them when another workflow is chosen. */
const NO_BACKEND = Object.freeze({});
const A_MICROSCOPES_KEYS = ["session", "instruments", "carrier", "focus", "plan", "cells", "acquired"];

/* The framework's run, with the few of this workflow's keys these tests write. */
type Held = TheRun & { carrier: Record<string, unknown>; cells: Map<unknown, unknown>; session: { password: string } };
const aRun = () => freshRun({ workflow: "target_acquisition", backend: NO_BACKEND, flow: targetAcquisition }) as Held;

describe("a run of target acquisition", () => {
  it("holds target acquisition's keys when that is the workflow", () => {
    const run = aRun();
    for (const key of A_MICROSCOPES_KEYS) expect(run, key).toHaveProperty(key);
  });

  it("takes the previous workflow's keys off the document when another is chosen", () => {
    const run = aRun();
    run.carrier.kind = "slide"; run.cells.set(1, {});
    run.wf = "three_steps";
    startOver(run, NO_BACKEND, threeSteps);
    for (const key of A_MICROSCOPES_KEYS) expect(run, key).not.toHaveProperty(key);
    expect(run.counted).toBe(0);
    expect(run.wf).toBe("three_steps");
  });

  it("lays a kept key afresh when another workflow took it off the document in between", () => {
    const run = aRun();
    run.session.password = "hunter2";
    run.wf = "three_steps";
    startOver(run, NO_BACKEND, threeSteps);
    expect(run).not.toHaveProperty("session");
    run.wf = "target_acquisition";
    startOver(run, NO_BACKEND, targetAcquisition);
    expect(run.session).toBeDefined();
    expect(run.session.password).not.toBe("hunter2");
    expect(run.instruments).toEqual([]);
  });

  it("keeps target acquisition's session and instruments, as before", () => {
    const run = aRun();
    run.session.password = "hunter2"; run.instruments = [{ key: "mock" }]; run.carrier.kind = "slide";
    startOver(run, NO_BACKEND, targetAcquisition);
    expect(run.session.password).toBe("hunter2");
    expect(run.instruments).toEqual([{ key: "mock" }]);
    expect(run.carrier.kind).not.toBe("slide");
  });
});
