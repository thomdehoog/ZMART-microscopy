/**
 * The seam where the microscope goes — the pretend side of it.
 *
 * Everything above this line — steps, widgets, the framework — talks to a backend
 * and awaits. Nothing above this line knows whether a real stage moved. The
 * live backend (`live.ts`, speaking HTTP to the bridge and through it to the
 * zmart controller) implements this same shape; if wiring the real microscope
 * means editing a widget, the seam leaked. Only this page's own browser tests
 * ask for it, with `?backend=pretend`.
 *
 * This backend fakes the work with timers and the pretend sample, so the page
 * can be developed and tested with no instrument anywhere near it.
 *
 * The verbs, and the two kinds they come in
 * -----------------------------------------
 *
 * **Readouts** ask the instrument how it is set and change nothing.
 * `readSetting` is the whole of recording a preset — the acquisition settings
 * and the focussing preset alike are the instrument's state, read now. On the
 * live side this is one `get_state` through the controller.
 *
 * **Procedures** make the instrument do something. `connect` opens the
 * session, `measureFocus` drives to each point and focuses there,
 * `scanOverview` drives the whole plan. On the live side these move a real
 * stage, which is why they are separate verbs and not part of any readout.
 *
 * `discoverTargets` finds the targets in the scanned fields; on the live side
 * that is the analysis reading the overview's pixels, and here it is invented
 * from the fields the scan was asked for.
 *
 * Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
 * University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
 */

import { MICROSCOPES, THE_MOCK, type ListedInstrument } from "../microscope/instruments.ts";
import { sampleReading } from "../microscope/settings.ts";
import { makeRng } from "../microscope/pretend-sample/rng.ts";
import { sweep } from "../microscope/pretend-sample/sweep.ts";
import { METRIC_KEYS } from "../shared/focus-curves.ts";
import type {
  Backend, CaptureRecord, FocusAsk, FocusPoint, FoundField, ScanPosition, Traces, WrittenProtocol, XyzReading,
} from "./verbs.ts";

/** A pause, for the pretend instrument's timers. */
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const writtenProtocols: WrittenProtocol[] = [];


/** How long a pretend tile test segments for: a moment a hand can reach. */
const TILE_TEST_MS = 1200;

/* The page's frames where there are frames, a timer where there are none:
   the contract suite runs this backend headless, and the pretend scan must
   tick there exactly as it ticks on screen. */
const frame = globalThis.requestAnimationFrame ?? ((tick) => setTimeout(tick, 16));

/* The pretend sample is not flat and not level: a gentle tilt across the
   carrier, the same surface wherever the plan decides to look at it. This is
   the mock's knowledge of the world — the page never computes it, it asks. */
const focusZAt = (x: number, y: number, [w, h]: [number, number]) =>
  -412 + 96 * (x / w - 0.5) + 61 * (y / h - 0.5);

/** Where on the sample a capture is, in the workflow's own label: the same
 *  five fields the bridge composes, so a run reads alike either way. */
const labelFor = (index: number, position: Partial<ScanPosition> = {}) => {
  const pad = (value: number | undefined, width: number) => String(value ?? 0).padStart(width, "0");
  return `K${pad(position.carrier, 2)}_M${pad(position.compartment, 6)}`
    + `_G${pad(position.group, 6)}_P${pad(index, 6)}_V${pad(position.view, 2)}`;
};

/* The positions each kind of scan was asked for, as the bridge keeps each
   scan's records: what discovery is over, once there has been an overview. */
const scanned: Record<string, ScanPosition[]> = {};

/* The operator's hand on the brake, as the bridge keeps it: set by the stop
   verbs, read by the pretend runs between two fields. */
const stopAsked = { scan: false, focus: false, targets: false, acquire: false, plot: false };

/* Every object discovery found, by id: what a plot of every candidate is over. */
let discovered: string[] = [];

export const backend: Backend = {
  /**
   * No pictures: this backend acquires nothing, so there is nothing to fetch.
   *
   * `null` rather than an address that would 404, because the canvas asks this
   * to decide whether to fetch an engine at all — a large thing to load for a
   * scan that does not exist.
   */
  viewOf() {
    return null;
  },

  /** No viewer server on the pretend side; the page draws its rehearsal. */
  async viewerSources() {
    return null;
  },

  /** What can be connected to, as the bridge gives it; no run has gone anywhere yet. */
  async instruments() {
    return { instruments: pretendInstruments(), output_root: null };
  },

  /**
   * Open the session and verify it, one named check at a time.
   *
   * The keys arrive first through `onChecks`, so the window can put every
   * question on screen before any answer exists; each answer then lands
   * through `onCheck(index, value)` as the pretend verification gets to it.
   * Resolves, with the instrument's info, once every check has answered.
   */
  async disconnect() {},

  async connect(session, { onChecks, onCheck } = {}) {
    const status = pretendConnectionStatus(session ?? {});
    const keys = Object.keys(status);
    onChecks?.(keys);
    await Promise.all(keys.map((key, k) =>
      wait(260 * (k + 1)).then(() => onCheck?.(k, status[key]))));
    return { info: await this.info() };
  },

  /** The instrument's account of itself: nothing the page reads. Where the
   *  stage goes and how far its pictures reach are `get_xyz`'s to say. */
  async info() {
    return {};
  },

  /** Where the stage is, per axis in micrometres: the controller's `get_xyz`. */
  async get_xyz() {
    return standingAt(where);
  },

  /**
   * Drive the stage there: the controller's `set_xyz`, answered with where it
   * ended up.
   *
   * The pretend stage moves, and that matters. It stood at one spot before,
   * which made every reading of it identical and hid a whole class of fault —
   * a page that never sees the position change is a page nobody can catch
   * drawing the mark in the wrong place. A move past the end of its travel
   * is refused before anything moves, the way a real driver refuses it, and
   * the stage stays where it was.
   */
  async set_xyz({ x, y, z }) {
    await wait(220);
    const to = { x: x ?? where.x, y: y ?? where.y, z: z ?? where.z };
    for (const axis of ["x", "y", "z"] as const) {
      const [low, high] = TRAVEL_RANGE_UM[axis];
      if (to[axis] < low || to[axis] > high) {
        throw new Error(`${axis} = ${to[axis]} um is outside the stage's travel [${low}, ${high}] um`);
      }
    }
    where = to;
    return standingAt(where);
  },

  /**
   * How a capture on this pretend instrument is triggered, and nothing else.
   *
   * The interface's mock microscope's own menu, said the same way — so the
   * page meets the same shape here as it does through the bridge, and cannot
   * come to rely on a setting only one of them has. Which job runs is the
   * state's (`set_state`), not a capture setting.
   */
  async get_acquisition_settings() {
    await wait(120);
    return { trigger: { options: ["full"], default: "full", active: "full" } };
  },

  /**
   * Change a setting on this pretend instrument, and answer with what stuck.
   *
   * A job it does not have is refused rather than accepted quietly: a capture
   * taken with one would not run, and a page is better told now than at the
   * press. The controller's mock driver refuses the same way.
   *
   * Nothing on the page calls this, by decision. A chooser would be named
   * after one vendor's noun — `job` is LAS X's word, and another instrument
   * has a protocol or an experiment or nothing like it — so the page would
   * have learned one microscope. It is here because the seam mirrors the
   * controller's surface, not this one page's needs.
   */
  async set_state(settings) {
    await wait(160);
    const applied: Record<string, unknown> = {};
    if ("job" in settings) {
      const job = settings.job;
      if (typeof job !== "string" || !JOBS.includes(job)) {
        throw new Error(`unknown job '${job}'; have ${JOBS.join(", ")}`);
      }
      chosenJob = job;
      applied.job = chosenJob;
    }
    return { applied };
  },

  /**
   * A readout, never a procedure: the instrument's state as it is set now,
   * shaped as the reading the window records. Recording a preset is this and
   * nothing more — nothing on the instrument moves.
   *
   * `nth` is the pretend operator's doing: the mock answers with the nth state
   * it knows, as though the optics were changed between readings. The live
   * backend reads what is there and ignores it.
   */
  async readSetting(type, { nth = 0 } = {}) {
    await wait(480);
    return sampleReading(type, nth);
  },

  /**
   * Capture once where the stage is standing, answering as the bridge does:
   * `{success, output}`, the output holding `files` and `planes`.
   *
   * `acquisition_type` is the page's name for the acquisition the capture
   * belongs to. Like a driver, this pretend instrument names every file by it
   * and the label, `{acquisition_type}_{position_label}`, the controller's
   * `"acquisition"` when none is given, and a label taken again gets `_001`,
   * ... so an earlier capture's name is never taken.
   *
   * The names are flat and complete: which acquisition, where on the sample,
   * and which plane of it — so nothing has to be opened to know what it
   * holds. A browser writes no files, so these are paths the rehearsal names
   * and does not make; through the bridge the driver's names are files on disk.
   */
  async acquire({ position_label, acquisition_settings = null, acquisition_type = null }) {
    void acquisition_settings;
    await wait(240);
    const kind = acquisition_type ?? "acquisition";
    const stem = `${kind}_${position_label}`;
    const before = taken.get(stem) ?? 0;
    taken.set(stem, before + 1);
    const free = before ? `${stem}_${String(before).padStart(3, "0")}` : stem;
    const path = `${free}_T000000_C00_Z00000.ome.tiff`;
    return {
      success: true,
      output: {
        position_label,
        acquisition_type: kind,
        files: [path],
        /* Where each plane was taken travels with it, as the real record's
           planes do: the record is the only thing that knows. */
        planes: [{ t: 0, z: 0, c: 0, path, x_um: where.x, y_um: where.y, z_um: where.z }],
      },
    };
  },

  /**
   * Drive to each point, focus there, and report what was found.
   *
   * Every measured point comes back with its height, plus everything the
   * window needs to show its work: the sweep traces for both sharpness
   * metrics (so the chart draws exactly what was measured), where the tissue
   * truly focuses, and the speck of debris the position carries, if any. A
   * height the operator moved by hand is kept — a measurement they overruled
   * is still their answer.
   *
   * `extent` is the carrier's size in micrometres; the pretend sample's tilt
   * is a fraction of the plate, so the mock needs to know how big the plate
   * is. The live backend ignores it — a real sample has its own tilt.
   */
  async measureFocus(points, { metric = "brenner", extent = [1, 1] as [number, number], onPoint, state, beginAt } = {}) {
    void state; // the pretend instrument has no configuration to reapply
    stopAsked.focus = false;
    await wait(200);
    const measured: FocusPoint[] = [];
    for (const [index, p] of points.entries()) {
      /* Between two points, as the bridge stops: what was measured stands.
         The gap is a yield, not a pause — long enough for a stop press to
         land between two points, and short enough that the rehearsal's pace
         stays the pace every budget in the specs was set to. */
      if (stopAsked.focus) return { points: measured, stopped: true };
      if (index) await wait(0);
      measured.push(measureOne(p, index));
      onPoint?.(measured[index], index);
    }
    return { points: measured, stopped: false };

    function measureOne(p: FocusAsk, index: number): FocusPoint {
      const focusZ = focusZAt(p.x, p.y, extent);
      /* Where this search begins. The objective is driven there and swept about
         it, so running the map again from wherever the stage is standing is a
         different act from refining it against what the map already says: the
         second starts every search a micrometre or two from the tissue and the
         first has no idea. Said nothing, the objective arrives near the tissue
         by luck, which is the best a first run can claim. */
      const chosen = beginAt?.(index);
      const startZ = typeof chosen === "number" && Number.isFinite(chosen) ? chosen
        : typeof p.startZ === "number" && Number.isFinite(p.startZ) ? p.startZ : undefined;
      const traces: Traces = Object.fromEntries(METRIC_KEYS.map((key: string) => {
        const sw = sweep({ focusZ, index, metric: key, startZ });
        return [key, { samples: sw.samples }];
      }));
      /* What the point carried in is not what it carries out: `startZ` was an
         instruction for this run, and saying it back would have the next one
         begin where this one did. */
      const { startZ: began, ...was } = p;
      /* Reported as the live backend reports: the curves, and the tallest
         height in the deciding one. Which peak is the tissue is the page's
         rule, applied to every curve whoever measured it -- the mock used to
         choose for itself, so the live path chose differently and a speck of
         dust won a point unflagged. */
      const tallest = traces[metric].samples.reduce((a, q) => (q.s > a.s ? q : a));
      return { ...was, z: p.manual ? p.z ?? null : tallest.z, zAuto: tallest.z, lost: false, traces };
    }
  },

  /** The operator's Interrupt for the focus run, as the bridge offers it. */
  async stopFocusMeasure() {
    stopAsked.focus = true;
    return { stopped: true };
  },

  /**
   * Drive the stage through every position, reporting progress as tiles land.
   *
   * The window's live picture is not fed from here: it watches the run's own
   * store and re-reads it as tiles are saved, which is the same arrangement
   * the real instrument has. This only says how far along the drive is.
   */
  async scanOverview({
    positions, acquisition_type = "overview", ms = 2600, onProgress, state,
    append = false, planned = null,
  }) {
    void state;
    void append;
    void planned;
    stopAsked.scan = false;
    scanned[acquisition_type] = positions;
    const total = positions.length;
    const records: CaptureRecord[] = [];
    const started = performance.now();
    let stopped = false;
    await new Promise<void>((resolve) => {
      const tick = () => {
        /* Between two fields, as the bridge stops: what landed stands. */
        if (stopAsked.scan) { stopped = true; resolve(); return; }
        const t = Math.min(1, (performance.now() - started) / ms);
        const done = Math.round(t * total);
        while (records.length < done) {
          const at = records.length;
          const p = positions[at];
          const stableAt = p.position_index ?? at;
          const path = `${acquisition_type}/${acquisition_type}_pretend_`
            + `${labelFor(stableAt, p)}_T000000_C00_Z00000.ome.tiff`;
          records.push({
            acquisition_type,
            position_label: labelFor(stableAt, p),
            /* One plane per record, saying where it was driven: a record
               with empty planes read fine against the page and undefined
               against anything that looked inside. */
            files: [path],
            planes: [{ t: 0, c: 0, z: 0, path, x_um: p.x, y_um: p.y, z_um: p.z ?? null }],
          });
        }
        const at = records[done - 1]?.planes[0];
        /* The records so far ride along, as the bridge's poll answers them. */
        onProgress?.(done, total, at ? { x: at.x_um, y: at.y_um, z: at.z_um } : null, records);
        if (t < 1) frame(tick);
        else resolve();
      };
      frame(tick);
    });
    /* The same shape the bridge answers with: a record for every position,
       so a page reading a finished run does not have to know which backend
       ran it. */
    return { done: records.length, of: total, records, stopped };
  },

  /** The operator's Interrupt for the scan, as the bridge offers it. */
  async stopScan() {
    stopAsked.scan = true;
    return {};
  },

  /**
   * Take the targets one tile at a time, as the bridge's page-driven run
   * does: a record a tile, in the scan's shape, with the height it was taken
   * at. With `focus` on, the tile is focussed first through the pretend
   * sweep, and the record says which height and why, as the live one does.
   */
  async acquireTargets({
    positions, state = null, append = false, focus = null, ms = 2600, onProgress, onDoing, zOffsetUm = 0,
  }) {
    void state;
    void append;
    stopAsked.acquire = false;
    scanned.targets = positions;
    const records: CaptureRecord[] = [];
    let stopped = false;
    for (const [index, p] of positions.entries()) {
      if (stopAsked.acquire) { stopped = true; break; }
      const say = (phase: string) => onDoing?.(`${phase} target ${index + 1} of ${positions.length}`);
      let z = p.z ?? null;
      let found: { settings: unknown; z_map_um: number | null; z_peak_um: number | null; found: boolean } | null = null;
      if (focus) {
        say("focussing on");
        const { points } = await this.measureFocus([{ x: (p.focusAt ?? p).x, y: (p.focusAt ?? p).y, startZ: z ?? undefined }],
          { metric: focus.metric, extent: focus.extent ?? [1, 1] });
        const [got] = points;
        const peak = got?.zAuto ?? null;
        found = { settings: focus.state ?? null, z_map_um: z, z_peak_um: peak, found: peak !== null && Number.isFinite(peak) };
        if (peak !== null && found.found) z = peak;
      }
      if (z !== null && Number.isFinite(z)) z += zOffsetUm;
      say("imaging");
      await wait(Math.max(60, ms / Math.max(1, positions.length)));
      const stableAt = p.position_index ?? index;
      const path = `targets/targets_pretend_${labelFor(stableAt, p)}_T000000_C00_Z00000.ome.tiff`;
      records.push({
        acquisition_type: "targets",
        position_label: labelFor(stableAt, p),
        files: [path],
        planes: [{ t: 0, c: 0, z: 0, path, x_um: p.x, y_um: p.y, z_um: z }],
        requested_position_um: { x: p.x, y: p.y, z },
        taken: performance.now(),
        focus: found,
      });
      onProgress?.(records.length, positions.length, { x: p.x, y: p.y, z }, records);
    }
    onDoing?.(null);
    return { done: records.length, of: positions.length, records, stopped };
  },

  /**
   * A multidimensional plot, as the bridge answers one: two columns an
   * object by id, invented from the id so the same objects always land in
   * the same place. The objects are the ones discovery found.
   */
  /* Protocols kept for the page's lifetime, the way this backend keeps
     everything: written by a finished run, listed newest first. */
  async protocols() {
    return [...writtenProtocols].reverse();
  },
  async saveProtocol(protocol) {
    writtenProtocols.push({
      id: `target-acquisition_${(writtenProtocols.length + 1).toString(16).padStart(6, "0")}`,
      written: Date.now() / 1000,
      protocol: JSON.parse(JSON.stringify(protocol)),
    });
    return { written: writtenProtocols[writtenProtocols.length - 1].id };
  },
  async saveProtocolAs(protocol, name) {
    writtenProtocols.push({
      id: (name || `saved ${writtenProtocols.length + 1}`), written: Date.now() / 1000, saved: true,
      protocol: JSON.parse(JSON.stringify(protocol)),
    });
    return { written: name, id: name };
  },

  async computePlot({ kind, ids = null, onDoing }) {
    stopAsked.plot = false;
    const over = ids ?? discovered;
    onDoing?.(`computing ${kind === "umap" ? "UMAP" : "principal components"} over ${over.length} objects`);
    await wait(kind === "umap" ? 600 : 150);
    onDoing?.(null);
    if (stopAsked.plot) return { stopped: true, columns: [] };
    const place = (id: unknown, salt: number) => makeRng([...String(id)].reduce((a, c) => a + c.charCodeAt(0), salt))() * 10 - 5;
    const columnsOf = (names: string[], salt: number) => ({
      columns: names, ids: [...over], values: [over.map((id) => place(id, salt)), over.map((id) => place(id, salt + 1))],
    });
    const columns = [columnsOf(["pca_1", "pca_2"], 11)];
    if (kind === "umap") columns.push(columnsOf(["umap_1", "umap_2"], 23));
    return { stopped: false, objects: over.length, seconds: 0.1, columns };
  },

  /** The operator's Interrupt for a plot, as the bridge offers it. */
  async stopPlot() {
    stopAsked.plot = true;
    return { stopped: true };
  },

  /** The operator's Interrupt for the target run, as the bridge offers it. */
  async stopAcquireTargets() {
    stopAsked.acquire = true;
    return { stopped: true };
  },

  /**
   * The targets in the overview's fields -- all of them, or the ones named --
   * each field's reaching `onField` as it is looked at. Invented: a handful of
   * cells per field, the same ones every time, laid inside the field the scan
   * was asked for. The settings are taken and ignored, because there are no
   * pixels here for a diameter to be right or wrong about.
   */
  async discoverTargets({
    fields = null, settings = {}, onField, onDoing, onProgress,
  } = {}) {
    void settings;
    stopAsked.targets = false;
    /* A tile test takes a moment, as the real one takes a minute: long
       enough that a hand can reach it, and the brake is honoured while it
       is being pretended. The whole-population run stays quick. */
    await wait(fields ? TILE_TEST_MS : 150);
    if (stopAsked.targets) return { fields: [], failed: [], stopped: true };
    const positions = scanned.overview ?? [];
    const found: FoundField[] = (fields?.map(Number) ?? positions.map((_, field) => field)).map((field) => {
      const at = positions[field];
      const r = makeRng(4400 + field);
      const frame = at.frameUm ?? 1000;
      const cells = Array.from({ length: 6 + Math.floor(r() * 10) }, (_, n) => {
        const area = 62 + 330 * Math.pow(r(), 1.7);
        return {
          id: `overview_r${String(field).padStart(3, "0")}_c000_obj${String(n + 1).padStart(5, "0")}`,
          field,
          x: at.x + (r() - 0.5) * frame,
          y: at.y + (r() - 0.5) * frame,
          area,
          intensity: 0.2 + 0.7 * r(),
          r: Math.sqrt(area / Math.PI),
        };
      });
      /* The device the field was detected on rides along, as the bridge's
         answer carries it; the pretend one has no card and says so. */
      return { field, position_label: labelFor(field, at), cells, device: "pretend" };
    });
    const gave: FoundField[] = [];
    onProgress?.(0, found.length, { phase: "objects", objects: 0, running: true });
    for (const one of found) {
      if (stopAsked.targets) break;
      await wait(0);
      onDoing?.(`detecting and measuring objects in position ${one.field + 1}`);
      onField?.(one);
      gave.push(one);
      if (!fields) discovered = gave.flatMap((field) => field.cells.map((cell) => cell.id));
      onProgress?.(gave.length, found.length, {
        phase: "objects",
        objects: gave.reduce((sum, field) => sum + field.cells.length, 0),
        running: true,
      });
    }
    onDoing?.(null);
    return { fields: gave, failed: [], stopped: stopAsked.targets };
  },

  /** The operator's Interrupt for discovery, as the bridge offers it. */
  async stopTargets() {
    stopAsked.targets = true;
    return {};
  },
};


/* ==========================================================================
   what this pretend instrument answers about itself
   ========================================================================== */

/** How far this pretend stage travels, in micrometres. */
const TRAVEL_UM = { x: 120_000, y: 80_000 };

/** The list a microscope PC with the Leica installed as "stellaris" would
 *  offer: the interface's mock first, then the controller's list, each with
 *  the connection words its driver's file names, as they are saved. The mock
 *  keeps no configs; the Leica lists the ones it keeps, the most recent first. */
export const pretendInstruments = (): ListedInstrument[] => [
  { name: THE_MOCK, settings: {
    microscope: "mock", api_type: "Mock API", host: "localhost", client: "mock-client", password: null, config: null,
  }, configs: null },
  { name: "stellaris", settings: {
    microscope: "stellaris-y42h93", api_type: "LAS X CAM API - Navigator Expert", host: "localhost",
    client: "PythonClient", password: null, config: null,
  }, configs: ["config_20261026_1952", "config_20260907_0714"] },
];

const pretendConnectionStatus = ({ instrument }: { instrument?: string }): Record<string, string> => ({
  "Microscope reachable": instrument && MICROSCOPES[instrument] ? "in-process" : "127.0.0.1:8895",
  "Credentials accepted": "token valid",
  "API version": (instrument && MICROSCOPES[instrument]?.apiDetail) || "LAS X 4.9",
  "Stage responds": "x 0.0 · y 0.0 · z −412.0 µm",
  "Objectives listed": "5x, 63x",
  "Storage writable": "smart/organoid-screen_a7f3c1/",
});

/** How far each axis travels, `[min, max]` in micrometres. Its pictures are
 *  named, never drawn, so they show no further than the stage goes: the
 *  `canvas` `get_xyz` reports is the travel itself. */
const TRAVEL_RANGE_UM: Record<"x" | "y" | "z", [number, number]> = { x: [0, TRAVEL_UM.x], y: [0, TRAVEL_UM.y], z: [-2_000, 2_000] };


/* How many captures each stem has had, so a second under the same label gets
   `_001` and never takes the first one's name, as a driver never overwrites. */
const taken = new Map<string, number>();


/* The jobs this pretend instrument has stored, and which is chosen. The same
   three the controller's mock driver keeps, so the page meets one instrument
   whichever backend it is talking to. */
const JOBS = ["Overview", "Focussing", "Target", "Target focussing"];
let chosenJob = JOBS[0];

/** Where its stage is parked before anything has driven it: the corner, off
 *  the carrier. */
const pretendPositionUm = () => ({ x: TRAVEL_UM.x * 0.04, y: TRAVEL_UM.y * 0.04, z: -412 });

/* Where it is standing now. The one piece of state this pretend instrument
   keeps between calls, because a stage is the one part of a microscope that
   stays where it was put. */
let where = pretendPositionUm();

/** A position, shaped the way the controller reports one: each axis gives
    its position in micrometres from the origin, the unit, the motor it moves
    by, every motor of the axis with its own raw reading, and the canvas. The
    pretend stage has one motor per axis, and it reads what the axis reads. */
const standingAt = (at: { x: number; y: number; z: number }): XyzReading => {
  const axis = (name: "x" | "y" | "z") => ({
    position: at[name], unit: "micrometer", used_actuator: "motoric", actuator_readings: { motoric: at[name] },
    canvas: [...TRAVEL_RANGE_UM[name]] as [number, number],
  });
  return { x: axis("x"), y: axis("y"), z: axis("z") };
};
