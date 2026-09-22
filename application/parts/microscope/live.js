/**
 * The seam where the microscope goes — the live side of it.
 *
 * The same shape as `mock.js`, implemented as HTTP calls to the bridge
 * (`workflow/webapp/bridge.py`), which speaks to the zmart controller, which
 * speaks to whichever driver is plugged in — the Leica driver on the
 * microscope PC (real LAS X or its simulator, the same driver either way),
 * or the controller's own mock driver on a machine with no instrument.
 *
 * Everything about the wire lives in this one file: the address, the JSON,
 * and how a failure becomes a thrown Error carrying the bridge's own
 * sentence. Nothing else in the page knows HTTP exists.
 *
 * **This is the backend the page runs on.** Open it and it speaks to the
 * bridge; which driver the controller runs behind that — the mock or the
 * Leica — is chosen on the Connect step, and either way every verb goes the
 * whole way through the controller and a driver. The in-browser rehearsal in
 * `mock.js` is reachable only by `?backend=pretend`, and only this page's own
 * browser tests ask for it.
 *
 * The live path deliberately stops at the overview scan, as the bridge does.
 */

/* Where the bridge answers. Empty means the page's own origin — the way it is
   on the microscope, where one Python process serves the page and the bridge
   together. `?bridge=http://127.0.0.1:8600` points elsewhere during
   development, when the vite server holds the page instead. */
const WHERE =
  new URLSearchParams(globalThis.location?.search ?? "").get("bridge") ?? "";

/** A bridge route as an address the page can fetch or put in an `img`: the
    route itself on the microscope, prefixed with the bridge's origin when
    the dev server holds the page. Pictures the bridge serves need this as
    much as the JSON calls do -- an `img` asks the page's own origin
    otherwise, and the dev server answers with the page. */
export const atBridge = (route) => `${WHERE}${route}`;

import { findCandidates, pickPeak } from "./focus-peaks.js";
import { PENDING, isFailed } from "./connection-status.js";

/** One call to the bridge: JSON in, JSON out, failure as a plain sentence.
    Exported for the setup side (`setup.js`), which speaks to the same bridge
    on routes of its own. */
export async function ask(route, payload) {
  const body = await request(route, payload);
  if (body.error) throw new Error(body.error);
  return body;
}

async function request(route, payload) {
  const answer = await fetch(atBridge(route), payload === undefined
    ? undefined
    : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  const body = await answer.json().catch(() => ({}));
  if (!answer.ok) {
    throw new Error(body.error ?? `the bridge answered ${answer.status}`);
  }
  return body;
}

const rest = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/* The operator's hand on the focus map: read by the loop before each drive. */
let targetsStopAsked = false;
let focusStopAsked = false;

/**
 * Ask again through a rough patch. A poll's dropped fetch is not the run
 * failing: the instrument keeps going whether or not one request lands, and
 * a busy bridge declared a healthy 864-field scan "failed" over one hiccup.
 */
const askedPatiently = async (path) => {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await ask(path);
    } catch (why) {
      if (attempt >= 3) throw why;
      await rest(700);
    }
  }
};

/** How often the connection's health is asked for while it is still answering. */
export const POLL_MS = 250;

export const backend = {
  /**
   * Where a scan's pictures can be fetched, or `null` for a backend with none.
   *
   * A microscope writes OME-TIFFs, which a browser cannot open and which are
   * far too heavy to send; the bridge makes one small JPEG per field as it
   * lands and serves them here, with a `tiles.json` beside them saying where
   * each belongs. The backend answers this rather than the page working it
   * out, because where a run's output is reachable is a fact about the
   * instrument's end and nothing the page could know.
   */
  viewOf(acquisitionType) {
    return `${WHERE}/view/${acquisitionType}`;
  },

  /**
   * Put one acquired target's frame on top of its neighbours in the
   * targets picture: the chosen one, whose pair the gallery shows.
   */
  async raiseTarget(position_label) {
    return ask("/api/targets/raise", { position_label });
  },

  /** What can be connected to: `get_instruments` through the bridge. */
  async instruments() {
    return (await ask("/api/instruments")).instruments;
  },

  /** The configurations a machine keeps, newest first, without connecting:
      `get_configurations` through the bridge. A session stands on one. */
  async configurations(connection) {
    return (await ask("/api/configurations", { connection })).configurations;
  },

  /**
   * The OME-Zarr pictures of this run, in Smart Viewer's own grouping: one
   * entry per acquisition, one channel entry per Viewer layer, and every
   * spatial store retained in that channel's `sources` list.  This shape is
   * load-bearing — nine fields of a three-channel overview are three channel
   * controls backed by nine sources, not twenty-seven controls.
   *
   * `null` while the Viewer is not up or holds nothing yet; the page then
   * falls back to the JPEG copies, so a machine without the Viewer installed
   * draws exactly as it always has.  The `sources` fallback keeps this page
   * able to speak to an older bridge during a rolling update.
   */
  async viewerSources(onStatus) {
    try {
      // A successful status response can contain both available images and a
      // failed acquisition. Its error must not discard the available images.
      const state = await request("/api/viewer");
      onStatus?.(state);
      if (Array.isArray(state?.acquisitions) && state.acquisitions.length) {
        return state.acquisitions;
      }
      const all = [];
      for (const sources of Object.values(state?.sources ?? {})) {
        for (const source of sources) all.push({ url: source.url, name: source.name });
      }
      return all.length ? all : null;
    } catch (why) {
      onStatus?.({ error: `Viewer status unavailable: ${why.message}` });
      return null;
    }
  },

  /**
   * Open the session through the bridge, then watch the driver's own
   * connection checks answer.
   *
   * The driver reports its health in `get_info().connection_status`: ordered
   * keys, each `"pending"` until answered, a value beginning `failed` when a
   * check failed. This polls that until nothing is pending. The keys go out
   * through `onChecks` on the first read, so the window can put every
   * question on screen before any answer exists; each answer lands through
   * `onCheck(index, value)` once, as it turns up. Resolves with the driver's
   * info once every check has answered; rejects, naming the check, when one
   * has failed.
   */
  async connect(session, { onChecks, onCheck } = {}) {
    /* The password travels with the connection: a gate that demanded it and
       then discarded it authenticated nothing. What a driver does with it is
       the driver's business. */
    await ask("/api/connect", {
      connection: { ...session?.connection, password: session?.password, configuration: session?.configuration },
    });
    let keys = null;
    const answered = new Set();
    for (;;) {
      const info = await this.info();
      const status = info.connection_status ?? {};
      if (keys === null) {
        keys = Object.keys(status);
        onChecks?.(keys);
      }
      let pending = false;
      let failure = null;
      keys.forEach((key, k) => {
        const value = status[key];
        if (value === PENDING) { pending = true; return; }
        if (!answered.has(key)) {
          answered.add(key);
          onCheck?.(k, value);
          if (isFailed(value)) failure ??= `${key}: ${value}`;
        }
      });
      if (failure) throw new Error(failure);
      if (!pending) return { info };
      await rest(POLL_MS);
    }
  },

  /** The driver's account of the session: `get_info` through the controller. */
  /** Close the session at the bridge, so the next connect is not refused. */
  async disconnect() {
    await ask("/api/disconnect", {});
  },

  async info() {
    return ask("/api/info");
  },

  /** Where the stage is: `get_xyz` through the controller. */
  async get_xyz() {
    return ask("/api/xyz");
  },

  /**
   * Drive the stage there: `set_xyz` through the controller, answering with
   * `get_xyz` afterwards. One route, the method saying which of the two is
   * meant, and the same two names the controller uses.
   */
  async set_xyz({ x, y, z }) {
    return ask("/api/xyz", { x, y, z });
  },

  /**
   * What the instrument offers for a capture, and what is chosen now:
   * `get_acquisition_options` through the controller. A readout — asking
   * changes nothing — and handed on in the driver's own words, because the
   * same shape goes back to `acquire`.
   */
  async get_acquisition_options() {
    return ask("/api/acquisition_options");
  },

  /**
   * Change settings on the instrument: `set_state` through the controller,
   * answering with what the driver says it applied — which is not always what
   * was asked, since a value it will not take is the driver's to refuse.
   *
   * Nothing on the page calls this, by decision: the page reads what it is
   * told and leaves the choosing to the software that authors the recipes.
   * It is here because the seam mirrors the controller's surface.
   */
  async set_state(settings) {
    return ask("/api/state", settings);
  },

  /**
   * A readout, never a procedure: the instrument's state as it is set now.
   * One `get_state` through the controller, shaped by the bridge into the
   * reading the window records. `nth` is the pretend operator's knob and the
   * live instrument has no use for it: the instrument is read as it stands,
   * set up in its own software -- LAS X, or the mock instrument window.
   */
  async readSetting(type) {
    return ask(`/api/setting?type=${encodeURIComponent(type)}`);
  },

  /**
   * Capture once where the stage is standing: `acquire` through the
   * controller, answering with the driver's record — what it wrote, and
   * where. The one place a client learns the paths of the files a run made.
   */
  async acquire({ acquisition_type, position_label, options = null }) {
    return ask("/api/acquire", { acquisition_type, position_label, options });
  },

  /**
   * Measure the focus map, one stack at a time, from here. Every command
   * is a question the bridge answers before the next is asked: drive to
   * the point, and the answer comes when the stage is there; take a stack,
   * and the answer is the record once the instrument has taken it; score
   * it, and the answer is the height with its curves. Between two answers
   * the page decides, and a stop is its own decision, made before the next
   * drive. The bridge runs nothing on its own; it keeps a ledger of the
   * points scored, for a page that reopens.
   *
   * `state` is the focussing recording, applied once before the run so
   * every stack is taken with the same job. A point whose drive or capture
   * fails is a LOST point, reported with no height, and the map goes on.
   */
  async measureFocus(points, { metric, state = null, onPoint, onDoing } = {}) {
    void metric; // which curve decides is the page's rule, applied to what comes back
    focusStopAsked = false;
    if (state) await ask("/api/state", state);
    const { labels } = await ask("/api/focus/begin", { of: points.length });
    const measured = [];
    let stopped = false;
    try {
      for (const [index, point] of points.entries()) {
        if (focusStopAsked) { stopped = true; break; }
        const say = (phase) => onDoing?.(`${phase} point ${index + 1} of ${points.length}`);
        /* `startZ` says where to begin this search; without one the stack
           is taken around the height the objective stands at. */
        const { startZ, ...asked } = point;
        let landed;
        try {
          say("driving");
          const at = await ask("/api/xyz", {
            x: point.x, y: point.y, ...(Number.isFinite(startZ) ? { z: startZ } : {}),
          });
          say("capturing");
          const record = await ask("/api/acquire", {
            acquisition_type: "focussing", position_label: labels[index],
          });
          say("scoring");
          landed = await ask("/api/focus/score", { record, centre: at.z.value, point });
        } catch (why) {
          console.warn(`focus point ${index + 1} is lost: ${why.message}`);
          landed = { ...asked, z: null, zAuto: null, lost: true, traces: null, cost_s: {}, slices: [] };
        }
        measured.push(landed);
        onPoint?.(landed, index);
      }
    } finally {
      onDoing?.(null);
      await ask("/api/focus/end", { stopped }).catch(() => {});
    }
    return { points: measured, stopped };
  },

  /** The operator's Interrupt for the focus run: the loop above stops before
      its next drive, and returns what was measured. */
  async stopFocusMeasure() {
    focusStopAsked = true;
    return { stopped: true };
  },

  /**
   * Find the targets in the overview's fields -- all of them, or the ones
   * named in `fields` -- and follow the search as the scan is followed: the
   * bridge detects in a background thread, this polls, and each field's
   * targets reach `onField(field)` as they are found.
   */
  async discoverTargets({
    fields = null, settings = {}, onField, onDoing, onProgress,
  } = {}) {
    await ask("/api/targets/discover", { fields, settings });
    /* The bridge lists fields in the order they land and keeps that order,
       so the fields held here are the cursor: each poll asks only for the
       ones landed since, and a run of hundreds of fields is not carried
       whole three times a second. */
    const landed = [];
    for (;;) {
      const progress = await askedPatiently(`/api/targets/discover?since=${landed.length}`);
      onDoing?.(progress.running ? progress.doing : null);
      onProgress?.(progress.done, progress.of, {
        phase: progress.phase,
        objects: progress.objects ?? 0,
        running: !!progress.running,
      });
      for (const one of progress.fields ?? []) {
        landed.push(one);
        onField?.(one);
      }
      if (progress.error) throw new Error(progress.error);
      if (!progress.running) {
        return {
          fields: landed,
          failed: progress.failed ?? [],
          stopped: !!progress.stopped,
        };
      }
      await rest(300);
    }
  },

  /** The operator's Interrupt for discovery: the bridge stops the search --
      putting the field in hand down with it, because an analysis field
      re-runs from its checkpoint -- and the poll above ends with what was
      found. */
  async stopTargets() {
    return ask("/api/targets/discover/stop", {});
  },

  /**
   * Start the overview scan and follow it by asking, not by being told: the
   * bridge drives the stage in a background thread, and this polls its
   * progress until the drive is over. The window's live picture watches the
   * run's own store, exactly as it does on the pretend side.
   */
  async scanOverview({
    positions, acquisition_type = "overview", state = null, onProgress,
    append = false, planned = null,
  } = {}) {
    await ask("/api/scan", { positions, acquisition_type, state, append, planned });
    /* The records so far, kept here: each poll asks only for the ones that
       landed since, so a long scan is not carried whole three times a second. */
    const records = [];
    for (;;) {
      const progress = await askedPatiently(`/api/scan?since=${records.length}`);
      records.push(...(progress.records ?? []));
      /* Where the scan stood when it answered -- the last record's own plane,
         which is the only account of the stage that is already in hand. */
      const plane = records[progress.done - 1]?.planes?.[0];
      /* The records so far ride along: each one names the picture the bridge
         has already made of it, so the page can print a field the moment it
         lands rather than when the run answers. */
      onProgress?.(progress.done, progress.of,
        plane ? { x: plane.x_um, y: plane.y_um, z: plane.z_um } : null, records);
      if (progress.error) throw new Error(progress.error);
      if (!progress.running) {
        /* The records come back with the run: what each capture wrote and
           where. Nothing else can reconstruct them, so a run that ended
           without them is a run nobody can account for. `stopped` rides
           along -- the operator's own hand is not a failure. */
        return { done: progress.done, of: progress.of, records, stopped: !!progress.stopped };
      }
      await rest(300);
    }
  },

  /** The operator's Interrupt for the scan: the bridge stops between two
      fields, and the poll above ends with what was captured. */
  async stopScan() {
    return ask("/api/scan/stop", {});
  },

  /**
   * Take the targets, one tile at a time, from here -- the focus map's
   * shape: every command is a question the bridge answers before the next
   * is asked, the page decides between two answers, and a stop is its own
   * decision, made before the next drive. The bridge runs nothing on its
   * own; it files each landed target and keeps a ledger for a page that
   * reopens.
   *
   * `state` is the target acquisition recording, `focus` the focussing the
   * operator asked for before each target -- `{state, metric}`, its own
   * recording and the sharpness score that decides -- or null. With it, a
   * tile is driven to at the map's height, a stack taken under the
   * focussing job, the peak chosen here by the map's own rule, and the
   * target taken at that height under the target job. A stack with no peak
   * leaves the target at the map's height, and the record says so.
   */
  async acquireTargets({
    positions, state = null, append = false, focus = null, onProgress, onDoing,
  } = {}) {
    targetsStopAsked = false;
    const { labels } = await ask("/api/targets/acquire/begin", { positions, append });
    if (!focus && state) await ask("/api/state", state);
    const records = [];
    let stopped = false;
    try {
      for (const [index, position] of positions.entries()) {
        if (targetsStopAsked) { stopped = true; break; }
        const say = (phase) => onDoing?.(`${phase} target ${index + 1} of ${positions.length}`);
        const { x, y, z: zMap = null } = position;
        let at = { x, y, ...(Number.isFinite(zMap) ? { z: zMap } : {}) };
        let found = null;
        /* Where the objective stood for the stack: the height the target is
           taken at when the stack shows no peak, map or no map. */
        let standing = null;
        if (focus) {
          say("focussing on");
          if (focus.state) await ask("/api/state", focus.state);
          const stood = await ask("/api/xyz", at);
          standing = stood.z.value;
          const stack = await ask("/api/acquire", {
            acquisition_type: "target_focussing", position_label: labels[index], options: null,
          });
          const scored = await ask("/api/targets/acquire/focus", {
            record: stack, centre: standing, x, y,
          });
          const curve = scored.traces?.[focus.metric];
          const peak = curve?.samples?.length ? pickPeak(findCandidates(curve.samples)) : null;
          found = {
            job: focus.state?.job ?? null, z_map_um: Number.isFinite(zMap) ? zMap : null,
            z_peak_um: peak ? peak.z : null, found: peak !== null,
          };
          if (peak) at = { x, y, z: peak.z };
          if (state) await ask("/api/state", state);
        }
        say("imaging");
        /* Already standing there after a stack with no peak: no second drive. */
        const stood = focus && !found.found ? { z: { value: standing } } : await ask("/api/xyz", at);
        const record = await ask("/api/acquire", {
          acquisition_type: "targets", position_label: labels[index], options: null,
        });
        const landed = await ask("/api/targets/acquire/landed", {
          record, position: { x, y, z: stood.z.value }, focus: found,
        });
        records.push(landed);
        onProgress?.(records.length, positions.length, { x, y, z: stood.z.value }, records);
      }
    } finally {
      onDoing?.(null);
      await ask("/api/targets/acquire/end", { stopped }).catch(() => {});
    }
    return { done: records.length, of: positions.length, records, stopped };
  },

  /**
   * A multidimensional plot of the detected population -- `pca` or `umap`
   * -- over the objects named by `ids`, or every candidate when left out.
   * The bridge runs it through the analysis and this follows it until it
   * lands; then every plot it wrote comes back as columns by id
   * (`{columns, ids, values}`), a UMAP bringing the components it stood on.
   */
  async computePlot({ kind, ids = null, onDoing } = {}) {
    await ask("/api/plots/compute", { kind, ids });
    for (;;) {
      const progress = await askedPatiently("/api/plots/compute");
      onDoing?.(progress.running ? progress.doing : null);
      if (!progress.running) {
        if (progress.error) throw new Error(progress.error);
        if (progress.stopped) return { stopped: true, columns: [] };
        const columns = [];
        for (const one of progress.kinds ?? []) {
          columns.push(await ask(`/api/plots/columns?kind=${encodeURIComponent(one)}`));
        }
        return { stopped: false, objects: progress.objects, seconds: progress.took_s, columns };
      }
      await rest(500);
    }
  },

  /** The operator's Interrupt for a plot: the bridge puts its worker down. */
  async stopPlot() {
    return ask("/api/plots/compute/stop", {});
  },

  /** The operator's Interrupt for the target run: the loop above stops
      before its next drive, and returns what was taken. */
  async stopAcquireTargets() {
    targetsStopAsked = true;
    return { stopped: true };
  },
};
