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
 * Pure: every function is a function of the state it is handed. The shell
 * owns the state and the file; this knows which fields are settings.
 */

export const PROTOCOL_VERSION = 1;

const AUTOMATABLE_GATE = /^(?!pca_|umap_)/;

/** The settings-only copy of a recording slot: the whole slot is settings. */
const slot = (s) => JSON.parse(JSON.stringify(s));

/**
 * The run's settings, picked out of the state.
 *
 * Gates on computed axes are left out: a PCA axis is fitted to the population
 * at hand and UMAP is drawn anew each run, so a polygon on either means
 * nothing on the next sample. The carrier's corners are kept as places on the
 * drawing, without the stage readings taken at them, which belong to the
 * mount they were taken on.
 */
export function protocolFrom(state) {
  const f = state.focus;
  const d = state.detect;
  return {
    version: PROTOCOL_VERSION,
    session: {
      microscope: state.session.microscope,
      api: state.session.api,
      configuration: state.session.configuration,
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
      zFixed: f.zFixed,
      points: f.points.map(({ x, y }) => ({ x, y })),
    },
    detect: {
      algo: d.algo,
      diameter: d.diameter,
      cellprob: d.cellprob,
      threshold: d.threshold,
      border: d.border,
      binning: d.binning,
    },
    gates: state.gates
      .filter((g) => AUTOMATABLE_GATE.test(g.fx) && AUTOMATABLE_GATE.test(g.fy))
      .map((g) => ({ fx: g.fx, fy: g.fy, vertices: g.vertices.map(([x, y]) => [x, y]) })),
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
export function protocolFits(state, protocol) {
  if (protocol.version > PROTOCOL_VERSION) {
    return `written by a newer page (version ${protocol.version})`;
  }
  const from = protocol.session?.microscope;
  const here = state.session.microscope;
  if (from && here && from !== here) {
    return `written on ${from}, this session is on ${here}`;
  }
  return null;
}

/**
 * The settings put into the state, in place. Everything measured stays as
 * the state had it — fresh, when the caller made it so — because a protocol
 * carries no results and must not invent any.
 */
export function applyProtocol(state, protocol) {
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
  Object.assign(state.focus, {
    strategy: protocol.focus.strategy,
    metric: protocol.focus.metric,
    perField: protocol.focus.perField,
    perCarrier: protocol.focus.perCarrier,
    zFixed: protocol.focus.zFixed,
    /* Places to measure, not yet measured: `z: null` is how a point says so. */
    points: protocol.focus.points.map(({ x, y }) => ({ x, y, z: null })),
  });
  Object.assign(state.detect, protocol.detect);
  state.gates = protocol.gates.map((g) => ({ fx: g.fx, fy: g.fy, vertices: g.vertices.map(([x, y]) => [x, y]) }));
  state.placing = { ...protocol.placing };
  state.testTiles = new Set(protocol.testTiles?.tiles ?? []);
  return state;
}
