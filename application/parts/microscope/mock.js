/**
 * The seam where the microscope goes — the pretend side of it.
 *
 * Everything above this line — steps, widgets, the framework — talks to a backend
 * and awaits. Nothing above this line knows whether a real stage moved. The
 * live backend (`live.js`, speaking HTTP to the bridge and through it to the
 * zmart controller) implements this same shape; if wiring the real microscope
 * means editing a widget, the seam leaked.
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
 * The seam stops at the overview scan for now: discovery, refinement and
 * acquisition of targets are still rehearsed inside the window, and their
 * verbs arrive here when that work starts.
 */

import { APIS } from "./instruments.js";
import { sampleReading } from "./settings.js";
import { makeRng } from "./pretend-sample/rng.js";
import { METRICS, METRIC_KEYS, sweep } from "./pretend-sample/sweep.js";

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/* The pretend sample is not flat and not level: a gentle tilt across the
   carrier, the same surface wherever the plan decides to look at it. This is
   the mock's knowledge of the world — the page never computes it, it asks. */
const focusZAt = (x, y, [w, h]) =>
  -412 + 96 * (x / w - 0.5) + 61 * (y / h - 0.5);

export const backend = {
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

  /** What can be connected to: the registry's entries, as the controller lists them. */
  async instruments() {
    return pretendInstruments();
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
    const status = pretendConnectionStatus(session);
    const keys = Object.keys(status);
    onChecks?.(keys);
    await Promise.all(keys.map((key, k) =>
      wait(260 * (k + 1)).then(() => onCheck?.(k, status[key]))));
    return { info: await this.info() };
  },

  /** The instrument's account of itself: here, the pretend canvas. */
  async info() {
    return { canvas: pretendCanvas() };
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
   * drawing the mark in the wrong place. It also stops at the ends of its
   * travel, because a real one does, and the answer is what it did rather
   * than what it was asked.
   */
  async set_xyz({ x, y, z }) {
    await wait(220);
    where = {
      x: withinTravel(x ?? where.x, TRAVEL_UM.x),
      y: withinTravel(y ?? where.y, TRAVEL_UM.y),
      z: z ?? where.z,
    };
    return standingAt(where);
  },

  /**
   * What this pretend instrument offers for a capture, and what is chosen now.
   *
   * The controller's mock driver's own menu, said the same way — so the page
   * meets the same shape here as it does through the bridge, and cannot come
   * to rely on a setting only one of them has.
   */
  async get_acquisition_options() {
    await wait(120);
    return {
      job: { options: [...JOBS], active: chosenJob },
      backlash_correction: { options: [true, false], active: true },
      format: { options: ["ome-tiff", "ome-zarr"], active: "ome-tiff" },
      procedure: { options: ["direct", "tiled"], active: "direct" },
    };
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
    const applied = {};
    if ("job" in settings) {
      if (!JOBS.includes(settings.job)) {
        throw new Error(`unknown job '${settings.job}'; have ${JOBS.join(", ")}`);
      }
      chosenJob = settings.job;
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
   * Capture once where the stage is standing, answering with the record.
   *
   * The names are the convention's, flat and complete: what the capture was,
   * which capture it was, where on the sample, and which plane of it — so
   * nothing has to be opened to know what it holds. A browser writes no
   * files, so these are paths the rehearsal names and does not make; through
   * the bridge the same names are files on disk.
   */
  async acquire({ acquisition_type, position_label, options = null }) {
    await wait(240);
    const hash6 = makeRng(where.x + where.y + captures++)()
      .toString(36).slice(2, 8).padEnd(6, "0");
    const path = `${acquisition_type}/${acquisition_type}_${hash6}_`
      + `${position_label}_T000000_C00_Z00000.ome.tiff`;
    return {
      acquisition_type,
      acquisition_hash: hash6,
      position_label,
      format: options?.format ?? "ome-tiff",
      position: { ...where },
      images: [path],
      planes: [{ t: 0, z: 0, c: 0, path }],
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
  async measureFocus(points, { metric, extent, onPoint }) {
    await wait(200);
    const measured = points.map((p, index) => {
      const focusZ = focusZAt(p.x, p.y, extent);
      /* Where this search begins. The objective is driven there and swept about
         it, so running the map again from wherever the stage is standing is a
         different act from refining it against what the map already says: the
         second starts every search a micrometre or two from the tissue and the
         first has no idea. Said nothing, the objective arrives near the tissue
         by luck, which is the best a first run can claim. */
      const startZ = Number.isFinite(p.startZ) ? p.startZ : undefined;
      const traces = Object.fromEntries(METRIC_KEYS.map((key) => {
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
      return { ...was, z: p.manual ? p.z : tallest.z, zAuto: tallest.z, lost: false, traces };
    });
    measured.forEach((point, index) => onPoint?.(point, index));
    return { points: measured };
  },

  /**
   * Drive the stage through every position, reporting progress as tiles land.
   *
   * The window's live picture is not fed from here: it watches the run's own
   * store and re-reads it as tiles are saved, which is the same arrangement
   * the real instrument has. This only says how far along the drive is.
   */
  async scanOverview({ positions, acquisition_type = "overview", ms = 2600, onProgress }) {
    const total = positions.length;
    const records = [];
    const started = performance.now();
    await new Promise((resolve) => {
      const tick = () => {
        const t = Math.min(1, (performance.now() - started) / ms);
        const done = Math.round(t * total);
        while (records.length < done) {
          const at = records.length;
          records.push({
            acquisition_type,
            position_label: labelFor(at, positions[at]),
            images: [], planes: [],
          });
        }
        onProgress?.(done, total);
        if (t < 1) requestAnimationFrame(tick);
        else resolve();
      };
      requestAnimationFrame(tick);
    });
    /* The same shape the bridge answers with: a record for every position,
       so a page reading a finished run does not have to know which backend
       ran it. */
    return { done: total, of: total, records };
  },
};

/* What METRICS looks like is display metadata the window shares (labels,
   colours); re-exported so the page reads it through the seam rather than
   reaching into the pretend sample. */
export { METRICS, METRIC_KEYS };

/* A deterministic random stream for the window's rehearsal drawings (the
   pretend image textures in previews). Re-exported for the same reason. */
export { makeRng };


/* ==========================================================================
   what this pretend instrument answers about itself
   ========================================================================== */

/** How far this pretend stage travels, in micrometres. */
const TRAVEL_UM = { x: 120_000, y: 80_000 };

/** The two drivers the controller registers on a machine with both. */
export const pretendInstruments = () => [
  { vendor: "mock", microscope: "mock-scope", api: "mock-api", client: "mock-client" },
  { vendor: "leica", microscope: "stellaris5-y42h93", api: "navigator-expert", client: "PythonClient" },
];

export const pretendConnectionStatus = ({ connection }) => ({
  "Microscope reachable": connection?.api === "navigator-expert" ? "127.0.0.1:8895" : "in-process",
  "Credentials accepted": "token valid",
  "API version": APIS[connection?.api]?.detail ?? "unknown",
  "Stage responds": "x 0.0 · y 0.0 · z −412.0 µm",
  "Objectives listed": "5x, 63x",
  "Storage writable": "smart/organoid-screen_a7f3c1/",
});

/** Its canvas: the travel a page draws to scale. */
const pretendCanvas = () => ({ x_um: [0, TRAVEL_UM.x], y_um: [0, TRAVEL_UM.y] });

/** Where on the sample a capture is, in the workflow's own label: the same
 *  five fields the bridge composes, so a run reads alike either way. */
const labelFor = (index, position = {}) => {
  const pad = (value, width) => String(value ?? 0).padStart(width, "0");
  return `K${pad(position.carrier, 2)}_M${pad(position.compartment, 6)}`
    + `_G${pad(position.group, 6)}_P${pad(index, 6)}_V${pad(position.view, 2)}`;
};

/* How many captures this instrument has taken, so two at one place still get
   names of their own — which is what the hash is for on a real one. */
let captures = 0;

/* The jobs this pretend instrument has stored, and which is chosen. The same
   three the controller's mock driver keeps, so the page meets one instrument
   whichever backend it is talking to. */
const JOBS = ["Overview", "HiRes", "Survey"];
let chosenJob = JOBS[0];

/** Where its stage is parked before anything has driven it: the corner, off
 *  the carrier. */
const pretendPositionUm = () => ({ x: TRAVEL_UM.x * 0.04, y: TRAVEL_UM.y * 0.04, z: -412 });

/* Where it is standing now. The one piece of state this pretend instrument
   keeps between calls, because a stage is the one part of a microscope that
   stays where it was put. */
let where = pretendPositionUm();

/** No further than the stage goes, which is what a real one answers with. */
const withinTravel = (v, span) => Math.max(0, Math.min(span, v));

/** A position, shaped the way the controller reports one. */
const standingAt = ({ x, y, z }) => ({
  x: { value: x, unit: "um" },
  y: { value: y, unit: "um" },
  z: { value: z, unit: "um" },
});
