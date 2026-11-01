/**
 * A protocol: the run's settings, as a file.
 *
 * What a run was told — the carrier, where to look, how to focus, what to
 * image with, how to find the targets and which to take — written once when
 * the run ends and read into a fresh session on another day, so the next
 * sample is run the way this one was. Settings only. Nothing measured is
 * carried: the focus map's heights are this sample's, the detected cells are
 * this sample's, the stage readings the carrier was registered from are this
 * mount's. Every one of those is made again on the next sample, from these
 * settings, which is the point of having them.
 *
 * Pure: every function is a function of the state it is handed. The page
 * owns the state and the bridge the file; this knows which fields are
 * settings. It is this workflow's: which keys of the run are settings is a
 * question about a microscope run, so the file lives beside the run document
 * that names them (`run-document.ts`) and not in the framework, which keeps
 * only the walk of the steps in turn (`page.run.walk`, `page.run.protocol`).
 */

import type { Slot } from "../microscope/recordings.ts";
import type { TaRun } from "../types.ts";
import type { Anchor } from "./alignment.ts";
import type { Carrier } from "./carriers.ts";
import type { Gate } from "./gating.ts";
import type { Field, XY } from "./scanfields.ts";

const PROTOCOL_VERSION = 1;

/** A protocol as written: the run's settings, and nothing measured. A plain
    object type rather than an interface, so it is the JSON record the
    backend lists and saves (`Record<string, unknown>`) as well. */
export type Protocol = {
  version: number;
  session?: { microscope?: string | null; api?: string | null };
  carrier: Carrier;
  anchors: Anchor[];
  fields: Field[];
  overviewPreset: Slot;
  focusPreset: Slot;
  targetType: Slot;
  targetFocusOn: boolean;
  targetFocus: Slot;
  targetZOffsetUm: number;
  /** An older file may carry more: a fixed height, a run to reuse. */
  focus: { strategy: string; metric: string; perField: number; perCarrier: number; points: XY[]; [older: string]: unknown };
  detect: { algo: string; channel: number; diameter: number; cellprob: number; threshold: number; border: number; binning: number };
  gates: Gate[];
  placing: TaRun["placing"];
  testTiles?: { tiles: number[]; of: number };
};

const COMPUTED_AXIS = /^(pca|umap)_/;

/**
 * Why these gates cannot go into a protocol, or null when they can. A PCA
 * axis is fitted to the population at hand and UMAP is drawn anew each run,
 * so a polygon on either selects other objects on the next sample, and on
 * this one once its objects are detected again. Leaving such a gate out
 * would be worse: the protocol would quietly take more than was chosen.
 */
export function whyGatesNotCarried(gates: Gate[]): string | null {
  const computed = gates.filter((g) => COMPUTED_AXIS.test(g.fx) || COMPUTED_AXIS.test(g.fy));
  if (!computed.length) return null;
  return `a gate on ${computed.map((g) => `${g.fx} × ${g.fy}`).join(", ")} cannot go into a protocol: `
    + "PCA and UMAP are fitted anew on every run; gate on measured features instead";
}

/** The settings-only copy of a recording slot: the whole slot is settings. */
const slot = (s: Slot): Slot => JSON.parse(JSON.stringify(s));

/**
 * The run's settings, picked out of the state.
 *
 * A gate on computed axes is refused, with `whyGatesNotCarried`'s reason. The
 * carrier's corners are kept as places on the drawing, without the stage
 * readings taken at them, which belong to the mount they were taken on.
 */
export function protocolFrom(state: TaRun): Protocol {
  const notCarried = whyGatesNotCarried(state.gates);
  if (notCarried) throw new Error(notCarried);
  const f = state.focus;
  const d = state.detect;
  return {
    version: PROTOCOL_VERSION,
    session: {
      microscope: state.session.microscope,
      api: state.session.api,
    },
    carrier: { ...state.carrier },
    anchors: state.anchors.map(({ x, y, at }) => ({ x, y, at })),
    fields: JSON.parse(JSON.stringify(state.fields)),
    overviewPreset: slot(state.overviewPreset),
    focusPreset: slot(state.focusPreset),
    targetType: slot(state.targetType),
    targetFocusOn: !!state.targetFocusOn,
    targetFocus: slot(state.targetFocus),
    targetZOffsetUm: Number(state.targetZOffsetUm) || 0,
    focus: {
      strategy: f.strategy,
      metric: f.metric,
      perField: f.perField,
      perCarrier: f.perCarrier,
      points: f.points.map(({ x, y }) => ({ x, y })),
    },
    detect: {
      algo: d.algo,
      channel: d.channel,
      diameter: d.diameter,
      cellprob: d.cellprob,
      threshold: d.threshold,
      border: d.border,
      binning: d.binning,
    },
    gates: state.gates.map((g) => ({ fx: g.fx, fy: g.fy, vertices: g.vertices.map(([x, y]): [number, number] => [x, y]) })),
    placing: { ...state.placing },
    testTiles: { tiles: [...(state.testTiles ?? [])].sort((a, b) => a - b), of: state.plan.length },
  };
}

/**
 * Whether this protocol can be applied in this session, as a reason when it
 * cannot. A protocol is written on one instrument and its recordings are
 * that instrument's states; applied on another they would name objectives
 * and channels that are not there.
 */
export function protocolFits(state: TaRun, protocol: Protocol): string | null {
  if (protocol.version > PROTOCOL_VERSION) {
    return `written by a newer page (version ${protocol.version})`;
  }
  const from = protocol.session?.microscope;
  const here = state.session.microscope;
  if (from && here && from !== here) {
    return `written on ${from}, this session is on ${here}`;
  }
  /* Only a measured focus map exists. A file asking for another strategy
     (older pages parked "fixed" and "reuse") would skip measuring and send
     the stage to a height nobody measured here. */
  const strategy = protocol.focus?.strategy ?? "plane";
  if (strategy !== "plane") {
    return `it asks for the "${strategy}" focus strategy, which this page does not have; `
      + "only a measured focus map can be used";
  }
  return null;
}

/**
 * The settings put into the state, in place. Everything measured stays as
 * the state had it — fresh, when the caller made it so — because a protocol
 * carries no results and must not invent any.
 */
export function applyProtocol(state: TaRun, protocol: Protocol): TaRun {
  state.carrier = { ...protocol.carrier };
  state.anchors = protocol.anchors.map(({ x, y, at }) => ({ x, y, at }));
  state.fields = JSON.parse(JSON.stringify(protocol.fields));
  /* The readings are NOT brought back (Thom, 2026-09-28): what the
     microscope is set to is read off it in this session, in every step
     that takes a reading -- the overview's, the focussing, the target's and,
     when the switch is on, the target focussing's. Only the switch is kept.
     The file still carries last time's readings, for the record. */
  state.overviewPreset = { ...state.overviewPreset, records: [], active: null };
  state.focusPreset = { ...state.focusPreset, records: [], active: null };
  state.targetType = { ...state.targetType, records: [], active: null };
  state.targetFocusOn = !!protocol.targetFocusOn;
  state.targetFocus = { ...state.targetFocus, records: [], active: null };
  state.targetZOffsetUm = Number(protocol.targetZOffsetUm) || 0;
  /* The strategy is not read from the file: there is one, the measured map,
     and `protocolFits` has refused a file that asks for another. A fixed
     height an older file carries is not read either. */
  Object.assign(state.focus, {
    metric: protocol.focus.metric,
    perField: protocol.focus.perField,
    perCarrier: protocol.focus.perCarrier,
    /* Places to measure, not yet measured: `z: null` is how a point says so. */
    points: protocol.focus.points.map(({ x, y }) => ({ x, y, z: null })),
  });
  /* A file written before the channel could be chosen segmented the first. */
  Object.assign(state.detect, { channel: 0 }, protocol.detect);
  state.gates = protocol.gates.map((g) => ({ fx: g.fx, fy: g.fy, vertices: g.vertices.map(([x, y]): [number, number] => [x, y]) }));
  state.placing = { ...protocol.placing };
  state.testTiles = new Set(protocol.testTiles?.tiles ?? []);
  return state;
}
