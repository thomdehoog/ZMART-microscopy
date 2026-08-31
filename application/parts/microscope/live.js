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

import { PENDING, isFailed } from "./connection-status.js";

/** One call to the bridge: JSON in, JSON out, failure as a plain sentence. */
async function ask(route, payload) {
  const answer = await fetch(`${WHERE}${route}`, payload === undefined
    ? undefined
    : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  const body = await answer.json().catch(() => ({}));
  if (!answer.ok || body.error) {
    throw new Error(body.error ?? `the bridge answered ${answer.status}`);
  }
  return body;
}

const rest = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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

  /** What can be connected to: `get_instruments` through the bridge. */
  async instruments() {
    return (await ask("/api/instruments")).instruments;
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
      connection: { ...session?.connection, password: session?.password },
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
   * Nothing on the page calls this, by decision. A chooser would be named
   * after one vendor's noun — `job` is LAS X's word, and another instrument
   * has a protocol or an experiment or nothing like it — so the page would
   * have learned one microscope. It is here because the seam mirrors the
   * controller's surface, not this one page's needs.
   */
  async set_state(settings) {
    return ask("/api/state", settings);
  },

  /**
   * A readout, never a procedure: the instrument's state as it is set now.
   * One `get_state` through the controller, shaped by the bridge into the
   * reading the window records. `nth` is the pretend operator's knob and the
   * live instrument has no use for it.
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
   * Drive to each point and focus there. The bridge runs the autofocus
   * procedure per position and reports the heights; the sweep traces the
   * pretend backend charts are the mock's own knowledge, so live points come
   * back without them and the chart stays empty until the driver can report
   * real sweeps.
   */
  async measureFocus(points, { metric, state = null, onPoint, onDoing } = {}) {
    await ask("/api/focus/measure", { points, metric, state });
    let shown = 0;
    for (;;) {
      const progress = await askedPatiently("/api/focus/measure");
      /* The bridge's own sentence about the phase under way, gone when it is. */
      onDoing?.(progress.running ? progress.doing : null);
      for (; shown < progress.points.length; shown++) onPoint?.(progress.points[shown], shown);
      if (progress.error) throw new Error(progress.error);
      if (!progress.running) {
        /* `stopped` is the operator's own hand, never a failure: the points
           measured before the press stand, and the caller says so. */
        return { points: progress.points, stopped: !!progress.stopped };
      }
      await rest(300);
    }
  },

  /** The operator's Interrupt for the focus run: the bridge stops between
      two points, and the poll above ends with what was measured. */
  async stopFocusMeasure() {
    return ask("/api/focus/measure/stop", {});
  },

  /**
   * Find the targets in the overview's fields -- all of them, or the ones
   * named in `fields` -- and follow the search as the scan is followed: the
   * bridge detects in a background thread, this polls, and each field's
   * targets reach `onField(field)` as they are found.
   */
  async discoverTargets({ fields = null, settings = {}, onField, onDoing } = {}) {
    await ask("/api/targets/discover", { fields, settings });
    let shown = 0;
    for (;;) {
      const progress = await askedPatiently("/api/targets/discover");
      onDoing?.(progress.running ? progress.doing : null);
      for (; shown < progress.fields.length; shown++) onField?.(progress.fields[shown]);
      if (progress.error) throw new Error(progress.error);
      if (!progress.running) {
        return { fields: progress.fields, stopped: !!progress.stopped };
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
  async scanOverview({ positions, acquisition_type = "overview", state = null, onProgress } = {}) {
    await ask("/api/scan", { positions, acquisition_type, state });
    for (;;) {
      const progress = await askedPatiently("/api/scan");
      /* Where the scan stood when it answered -- the last record's own plane,
         which is the only account of the stage that is already in hand. */
      const plane = progress.records?.[progress.done - 1]?.planes?.[0];
      onProgress?.(progress.done, progress.of,
        plane ? { x: plane.x_um, y: plane.y_um, z: plane.z_um } : null);
      if (progress.error) throw new Error(progress.error);
      if (!progress.running) {
        /* The records come back with the run: what each capture wrote and
           where. Nothing else can reconstruct them, so a run that ended
           without them is a run nobody can account for. `stopped` rides
           along -- the operator's own hand is not a failure. */
        return {
          done: progress.done, of: progress.of, records: progress.records,
          stopped: !!progress.stopped,
        };
      }
      await rest(300);
    }
  },

  /** The operator's Interrupt for the scan: the bridge stops between two
      fields, and the poll above ends with what was captured. */
  async stopScan() {
    return ask("/api/scan/stop", {});
  },
};
