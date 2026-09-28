/* A protocol is a run's settings, written to a file and read into a fresh
   session on another day. Settings only: no pictures, no measured heights,
   no test results, nothing the page invents while it works. The test goes
   through a real file, because an object round trip never notices that a
   Set writes as `{}`. */

import { describe, it, expect } from "vitest";
import { mkdtempSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { protocolFrom, applyProtocol, protocolFits } from "./protocol.js";
import { emptySlot, withRecording } from "../../parts/microscope/recordings.js";

const reading = (frame) => ({
  summary: "10x · 2 ch", detail: {}, frameUm: frame, kind: null,
  changeable: { objective: "10x" },
});

const settled = () => ({
  session: { microscope: "mock", api: "mock", configuration: "cfg-1", password: "x" },
  carrier: { kind: "plate", rows: 2, cols: 3, wellMm: 6 },
  anchors: [
    { x: 1, y: 2, at: "A1", stage: { x: 100, y: 200, z: 5 } },
    { x: 3, y: 4, at: "C2" },
  ],
  fields: [{ id: "f1", type: "region", x: 0, y: 0, w: 2, h: 1, overlap: 0.1 }],
  plan: [{ x: 0 }, { x: 1 }, { x: 2 }, { x: 3 }],
  overviewPreset: withRecording(emptySlot("acquisition"), { name: "Overview", reading: reading(800) }),
  focusPreset: withRecording(emptySlot("autofocus"), { name: "AF", reading: reading(800) }),
  targetType: withRecording(emptySlot("acquisition", 1), { name: "Target", reading: reading(128) }),
  targetFocusOn: true,
  targetFocus: withRecording(emptySlot("autofocus", 1), { name: "TF", reading: reading(128) }),
  targetZOffsetUm: -2.5,
  focus: {
    strategy: "plane", metric: "vollath", perField: 2, perCarrier: 4, zFixed: -400,
    points: [{ x: 1, y: 1, z: 12.5, trace: [1, 2, 3] }, { x: 2, y: 2, z: 13 }],
    selected: 1, picked: new Set([0]), hovered: 0, placing: true,
    applied: true, surface: { model: "plane" }, residual: 0.4, worst: 1,
  },
  detect: {
    algo: "fast", diameter: 24, cellprob: 0.5, threshold: 150, border: 5, binning: 2,
    maskShow: "line", maskColour: "#f00", maskAlpha: 0.5, tile: 3, targetTile: 1,
    hovered: 2, tested: true, tried: [1, 2],
  },
  gates: [
    { fx: "area", fy: "mean", vertices: [[0, 0], [1, 0], [1, 1]] },
    { fx: "pca_1", fy: "pca_2", vertices: [[0, 0], [1, 0], [1, 1]] },
    { fx: "umap_1", fy: "area", vertices: [[0, 0], [1, 0], [1, 1]] },
  ],
  gated: new Set(["c1", "c2"]),
  placing: { margin: 2, objectsMax: 20, minimise: false, overlapMin: 0.3 },
  testTiles: new Set([1, 3]),
  cells: new Map([["c1", {}]]),
});

const fresh = () => ({
  session: { microscope: "mock", api: "mock", configuration: "cfg-1", password: "" },
  carrier: {}, anchors: [], fields: [], plan: [],
  overviewPreset: emptySlot("acquisition"), focusPreset: emptySlot("autofocus"),
  targetType: emptySlot("acquisition", 1), targetFocusOn: false, targetFocus: emptySlot("autofocus", 1),
  targetZOffsetUm: 0,
  focus: { strategy: "plane", metric: "brenner", points: [], perField: 1, perCarrier: 4,
    zFixed: 0, selected: 0, picked: new Set(), applied: false, surface: null },
  detect: { algo: "fast", diameter: 30, cellprob: 0, threshold: 100, border: 0, binning: 1,
    maskShow: "fill", tile: 0, tested: false, tried: [] },
  gates: [], gated: new Set(), placing: { margin: 1, objectsMax: 50, minimise: true, overlapMin: 0.2 },
  testTiles: new Set(),
});

const throughAFile = (protocol) => {
  const dir = mkdtempSync(join(tmpdir(), "zmart-protocol-"));
  const path = join(dir, "protocol.json");
  writeFileSync(path, JSON.stringify(protocol, null, 2));
  return JSON.parse(readFileSync(path, "utf8"));
};

describe("a protocol is the run's settings and nothing else", () => {
  const p = throughAFile(protocolFrom(settled()));

  it("carries the settings of every step", () => {
    expect(p.version).toBe(1);
    expect(p.session).toEqual({ microscope: "mock", api: "mock", configuration: "cfg-1" });
    expect(p.carrier).toEqual({ kind: "plate", rows: 2, cols: 3, wellMm: 6 });
    expect(p.fields).toEqual([{ id: "f1", type: "region", x: 0, y: 0, w: 2, h: 1, overlap: 0.1 }]);
    expect(p.overviewPreset.records[0].name).toBe("Overview");
    expect(p.overviewPreset.records[0].changeable).toEqual({ objective: "10x" });
    expect(p.focusPreset.active).toBe("autofocus-1");
    expect(p.targetType.records[0].frameUm).toBe(128);
    expect(p.targetFocusOn).toBe(true);
    expect(p.targetFocus.records[0].name).toBe("TF");
    expect(p.targetZOffsetUm).toBe(-2.5);
    expect(p.focus).toEqual({
      strategy: "plane", metric: "vollath", perField: 2, perCarrier: 4, zFixed: -400,
      points: [{ x: 1, y: 1 }, { x: 2, y: 2 }],
    });
    expect(p.detect).toEqual({ algo: "fast", diameter: 24, cellprob: 0.5, threshold: 150, border: 5, binning: 2 });
    expect(p.placing).toEqual({ margin: 2, objectsMax: 20, minimise: false, overlapMin: 0.3 });
    expect(p.testTiles).toEqual({ tiles: [1, 3], of: 4 });
  });

  it("keeps the carrier's corners but not where the stage stood at them", () => {
    expect(p.anchors).toEqual([{ x: 1, y: 2, at: "A1" }, { x: 3, y: 4, at: "C2" }]);
  });

  it("carries gates on measured features only", () => {
    expect(p.gates).toEqual([{ fx: "area", fy: "mean", vertices: [[0, 0], [1, 0], [1, 1]] }]);
  });

  it("carries no results, no password and nothing the page invents while it works", () => {
    const text = JSON.stringify(p);
    for (const word of ["gated", "cells", "trace", "surface", "residual", "applied", "tested",
      "tried", "hovered", "picked", "maskShow", "password", "stage", "\"z\""]) {
      expect(text, word).not.toContain(word);
    }
  });
});

describe("read into a fresh session, the settings are back", () => {
  const p = throughAFile(protocolFrom(settled()));
  const s = fresh();
  applyProtocol(s, p);

  it("fills every step's settings", () => {
    expect(s.carrier).toEqual({ kind: "plate", rows: 2, cols: 3, wellMm: 6 });
    expect(s.anchors).toEqual([{ x: 1, y: 2, at: "A1" }, { x: 3, y: 4, at: "C2" }]);
    expect(s.fields[0].id).toBe("f1");
    expect(s.targetFocusOn).toBe(true);
    expect(s.targetZOffsetUm).toBe(-2.5);
    expect(s.focus.metric).toBe("vollath");
    expect(s.focus.points).toEqual([{ x: 1, y: 1, z: null }, { x: 2, y: 2, z: null }]);
    expect(s.focus.perField).toBe(2);
    expect(s.detect.threshold).toBe(150);
    expect(s.detect.binning).toBe(2);
    expect(s.gates).toHaveLength(1);
    expect(s.placing.objectsMax).toBe(20);
    expect(s.testTiles).toEqual(new Set([1, 3]));
  });

  it("brings no reading back: each is imported afresh on this session", () => {
    for (const key of ["overviewPreset", "focusPreset", "targetType", "targetFocus"]) {
      expect(s[key].records, key).toEqual([]);
      expect(s[key].active, key).toBeNull();
    }
  });

  it("leaves the fresh session's own state fresh", () => {
    expect(s.focus.applied).toBe(false);
    expect(s.focus.surface).toBeNull();
    expect(s.focus.picked).toEqual(new Set());
    expect(s.detect.tested).toBe(false);
    expect(s.detect.maskShow).toBe("fill");
    expect(s.gated).toEqual(new Set());
    expect(s.session.password).toBe("");
  });

  it("writes the same protocol again, bar the readings it did not bring back", () => {
    const again = protocolFrom({ ...s, plan: [1, 2, 3, 4] });
    for (const key of ["overviewPreset", "focusPreset", "targetType", "targetFocus"]) {
      delete again[key]; delete p[key];
    }
    expect(again).toEqual(p);
  });
});

describe("a protocol belongs to one instrument", () => {
  const p = protocolFrom(settled());

  it("fits the session it was written in", () => {
    expect(protocolFits(fresh(), p)).toBeNull();
  });

  it("is refused on another microscope, and says which", () => {
    const s = fresh();
    s.session.microscope = "stellaris5";
    expect(protocolFits(s, p)).toBe("written on mock, this session is on stellaris5");
  });

  it("is refused from a page that does not know the format", () => {
    expect(protocolFits(fresh(), { ...p, version: 2 })).toBe("written by a newer page (version 2)");
  });
});
