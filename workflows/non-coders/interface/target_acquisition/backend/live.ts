/**
 * The seam where the microscope goes -- the live side of it.
 *
 * Every verb the page's steps call, as HTTP calls to the bridge, which
 * speaks to the ZMART Controller, which speaks to whichever driver is
 * plugged in: a real microscope's driver on the microscope PC, or the
 * interface's own mock microscope on a machine with no instrument.
 *
 * Everything about the wire lives in this one file: the address, the JSON,
 * and how a failure becomes a thrown Error carrying the bridge's own
 * sentence. Nothing else in the page knows HTTP exists.
 *
 * **This is the backend the page runs on.** Which driver the controller runs
 * behind the bridge -- the mock or a real microscope -- is chosen on the
 * Connect step, and either way every verb goes the whole way through the
 * controller and a driver. The in-browser rehearsal in `pretend.ts` has the
 * same verbs, and is reachable only by `?backend=pretend`, for this page's
 * own browser tests.
 *
 * Every verb goes to this workflow's own Python half, under
 * `/api/target_acquisition/` (`../bridge/__init__.py`): the controller's own
 * -- connecting, the stage, the instrument's settings, a capture -- and the
 * workflow's -- the focus map, the overview scan, finding and taking the
 * targets, the plots and the protocols.
 *
 * Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
 * University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
 */

/* Where the bridge answers is the page's one fact about its own address
   (`framework/window/bridge-address.ts`): the page's own origin on the
   microscope, or `?bridge=http://127.0.0.1:8600` during development, when
   the vite server holds the page instead. */
import { atBridge } from "zmart-interface/api";
import { PENDING, isFailed } from "../microscope/connection-status.ts";
import { findCandidates, pickPeak } from "../shared/focus-curves.ts";
import type {
  Backend, CaptureRecord, Connecting, ControllerAnswer, FocusAsk, FocusPoint, FoundField, Instruments, Opening, Place, PlotColumns,
  PublishedAcquisition,
  Reading, RunProgress, ScanPosition, TargetFocus, TargetPosition, Traces, ViewerStatus, WrittenProtocol, XyzReading,
} from "./verbs.ts";

/** Where this workflow's routes answer on the bridge: every verb below,
    the controller's and the workflow's own, under its folder's name. */
const OURS = "/api/target_acquisition";

/** What a run of this workflow is called on disk: `target-acquisition_<hash>`.
    Sent when connecting, and never changed, so the runs and protocols saved
    before are still found (`bridge/protocols.py` keeps the same name). */
const EXPERIMENT = "target-acquisition";

/** One call to the bridge: JSON in, JSON out, failure as a plain sentence. */
export async function ask<T = Record<string, unknown>>(route: string, payload?: unknown): Promise<T> {
  const body = await request(route, payload);
  if (typeof body.error === "string") throw new Error(body.error);
  /* What each route answers is the bridge's to say; the verbs below name it. */
  return body as T;
}

async function request(route: string, payload?: unknown): Promise<Record<string, unknown>> {
  const answer = await fetch(atBridge(route), payload === undefined
    ? undefined
    : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  const body: Record<string, unknown> = await answer.json().catch(() => ({}));
  if (!answer.ok) {
    throw new Error(typeof body.error === "string" ? body.error : `the bridge answered ${answer.status}`);
  }
  return body;
}

const rest = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * The output inside the controller's answer to `acquire`, or the driver's
 * reason as a plain sentence when the microscope declined. The bridge passes
 * the controller's `{success, output}` on untouched, so the page reads a
 * capture exactly as a Python script does.
 */
function capturedBy(answer: ControllerAnswer<CaptureRecord>): CaptureRecord {
  const output = answer?.output;
  if (answer?.success === true) return output as CaptureRecord;
  const reason = typeof output === "string"
    ? output
    : (output as { reason?: string; message?: string } | null)?.reason
      ?? (output as { message?: string } | null)?.message;
  throw new Error(`the microscope could not capture an image: ${reason ?? "the driver gave no reason"}`);
}

/**
 * Ask again through a rough patch. A poll's dropped fetch is not the run
 * failing: the instrument keeps going whether or not one request lands, and
 * a busy bridge declared a healthy 864-field scan "failed" over one hiccup.
 */
const askedPatiently = async <T>(path: string): Promise<T> => {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await ask<T>(path);
    } catch (why) {
      if (attempt >= 3) throw why;
      await rest(700);
    }
  }
};

/** How often the connection's health is asked for while it is still answering. */
const POLL_MS = 250;

/* The operator's hand on the focus map and on the target run: read by each
   loop before its next drive. */
let targetsStopAsked = false;
let focusStopAsked = false;

export const backend: Backend = {
  /**
   * Where a scan's small pictures can be fetched, or `null` for a backend
   * with none.
   *
   * A microscope writes OME-TIFFs, which a browser cannot open and which are
   * far too heavy to send; the bridge makes one small JPEG per field as it
   * lands and serves them here, for the gallery, the previews, the focus
   * slices and the masks. (The run's picture on the canvas is drawn from the
   * OME-Zarr sources instead; the `tiles.json` beside the JPEGs is the
   * bridge's own note of which copy is which.) The backend answers this
   * rather than the page working it out, because where a run's output is
   * reachable is a fact about the instrument's end.
   */
  viewOf(acquisitionType: string): string | null {
    return atBridge(`${OURS}/view/${acquisitionType}`);
  },

  /** What can be connected to, each with its driver's settings, and where the last run went: from the bridge. */
  async instruments() {
    return ask<Instruments>(`${OURS}/instruments`);
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
  async viewerSources(onStatus?: (status: ViewerStatus) => void): Promise<PublishedAcquisition[] | null> {
    try {
      // A successful status response can contain both available images and a
      // failed acquisition. Its error must not discard the available images.
      const state = await request(`${OURS}/viewer`) as ViewerStatus;
      onStatus?.(state);
      if (Array.isArray(state?.acquisitions) && state.acquisitions.length) {
        return state.acquisitions;
      }
      const all: { url: string; name: string }[] = [];
      for (const sources of Object.values(state?.sources ?? {})) {
        for (const source of sources) all.push({ url: source.url, name: source.name });
      }
      return all.length ? all : null;
    } catch (why) {
      onStatus?.({ error: `Viewer status unavailable: ${why instanceof Error ? why.message : String(why)}` });
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
  async connect(session: Opening | null | undefined, { onChecks, onCheck }: Connecting = {}) {
    /* What the operator typed travels with the connection: the bridge puts
       it over the connection saved for the driver. What a driver does with
       it is the driver's business: a word it does not need, it leaves. */
    await ask(`${OURS}/connect`, {
      instrument: session?.instrument, host: session?.host, client: session?.client, config: session?.config,
      password: session?.password,
      output_root: session?.outputRoot, experiment: EXPERIMENT,
    });
    let keys: string[] | null = null;
    const answered = new Set<string>();
    for (;;) {
      const info = await this.info();
      const status = (info.connection_status ?? {}) as Record<string, string>;
      if (keys === null) {
        keys = Object.keys(status);
        onChecks?.(keys);
      }
      let pending = false;
      let failure: string | null = null;
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

  /** Close the session at the bridge, so the next connect is not refused. */
  async disconnect() {
    await ask(`${OURS}/disconnect`, {});
  },

  /** The driver's account of the session: `get_info` through the controller. */
  async info() {
    return ask<{ connection_status?: Record<string, string>; [more: string]: unknown }>(`${OURS}/info`);
  },

  /** Where the stage is: `get_xyz` through the controller. */
  async get_xyz() {
    return ask<XyzReading>(`${OURS}/xyz`);
  },

  /**
   * Drive the stage there: `set_xyz` through the controller, answering with
   * `get_xyz` afterwards. One route, the method saying which of the two is
   * meant, and the same two names the controller uses.
   */
  async set_xyz({ x, y, z }: Place) {
    return ask<XyzReading>(`${OURS}/xyz`, { x, y, z });
  },

  /**
   * What the instrument offers for a capture, and what is chosen now:
   * `get_acquisition_settings` through the controller. A readout — asking
   * changes nothing — and handed on in the driver's own words, because the
   * same shape goes back to `acquire`.
   */
  async get_acquisition_settings() {
    return ask(`${OURS}/acquisition_settings`);
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
  async set_state(settings: Record<string, unknown>) {
    return ask<{ applied: Record<string, unknown> }>(`${OURS}/state`, settings);
  },

  /**
   * A readout, never a procedure: the instrument's state as it is set now.
   * One `get_state` through the controller, shaped by the bridge into the
   * reading the window records. `nth` is the pretend operator's knob and the
   * live instrument has no use for it: the instrument is read as it stands,
   * set up in its own software -- LAS X, or the mock instrument window.
   */
  async readSetting(type: string, how: { nth?: number } = {}) {
    void how; // the pretend operator's knob: the instrument is read as it stands
    return ask<Reading>(`${OURS}/setting?type=${encodeURIComponent(type)}`);
  },

  /**
   * Capture once where the stage is standing: `acquire` through the
   * controller, answering as the controller does — `{success, output}`, the
   * output's `files` naming every file saved and its `planes` which channel,
   * depth and stage position each picture is. The one place a client learns
   * the paths of the files a run made.
   *
   * `acquisition_type` is the page's own name for the acquisition this
   * capture belongs to (overview, focussing, targets, ...). The bridge hands
   * it to the driver, which puts it in its file names, and gives the driver
   * the run's folder for that acquisition to save in.
   */
  async acquire({ position_label, acquisition_settings = null, acquisition_type = null }: {
    position_label: string; acquisition_settings?: Record<string, unknown> | null; acquisition_type?: string | null;
  }) {
    return ask<ControllerAnswer<CaptureRecord>>(`${OURS}/acquire`, { position_label, acquisition_settings, acquisition_type });
  },

  /**
   * Put one acquired target's frame on top of its neighbours in the
   * targets picture: the chosen one, whose pair the gallery shows.
   */
  async raiseTarget(position_label: string) {
    return ask(`${OURS}/targets/raise`, { position_label });
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
   *
   * `beginAt(index)`, when given, is asked just before each drive where that
   * point's search should begin. It is asked late on purpose: by then the
   * page has read the previous point, so a search can start at the height
   * just found there. A height it gives wins over the point's own `startZ`;
   * no answer leaves `startZ` as it was.
   */
  async measureFocus(points: FocusAsk[], { metric, state = null, onPoint, onDoing, beginAt }: {
    metric?: string; extent?: [number, number]; state?: Record<string, unknown> | null;
    onPoint?(point: FocusPoint, index: number): void; onDoing?(doing: string | null): void;
    beginAt?(index: number): number | null | undefined;
  } = {}) {
    void metric; // which curve decides is the page's rule, applied to what comes back
    focusStopAsked = false;
    if (state) await ask(`${OURS}/state`, state);
    const { labels } = await ask<{ labels: string[] }>(`${OURS}/focus/begin`, { of: points.length });
    const measured: FocusPoint[] = [];
    let stopped = false;
    try {
      for (const [index, point] of points.entries()) {
        if (focusStopAsked) { stopped = true; break; }
        const say = (phase: string) => onDoing?.(`${phase} point ${index + 1} of ${points.length}`);
        /* `startZ` says where to begin this search; without one the stack
           is taken around the height the objective stands at. */
        const { startZ: given, ...asked } = point;
        const chosen = beginAt?.(index);
        const startZ = typeof chosen === "number" && Number.isFinite(chosen) ? chosen : given;
        let landed: FocusPoint;
        try {
          say("driving");
          const at = await ask<XyzReading>(`${OURS}/xyz`, {
            x: point.x, y: point.y, ...(typeof startZ === "number" && Number.isFinite(startZ) ? { z: startZ } : {}),
          });
          say("capturing");
          const record = capturedBy(await ask<ControllerAnswer<CaptureRecord>>(`${OURS}/acquire`, {
            acquisition_type: "focussing", position_label: labels[index],
          }));
          say("scoring");
          landed = await ask<FocusPoint>(`${OURS}/focus/score`, { record, centre: at.z.position, point });
        } catch (why) {
          /* Cut off by the operator's own Interrupt (the bridge put the
             analysis down to reach a scoring that hung): not a point the
             microscope failed, just one not measured. */
          if (focusStopAsked) { stopped = true; break; }
          /* The microscope's own sentence rides on the point, so the row
             can say why: a move it declined is not a search that found no
             peak, and the window has no console to read it in. */
          landed = {
            ...asked, z: null, zAuto: null, lost: true, refused: why instanceof Error ? why.message : String(why),
            traces: null, cost_s: {}, slices: [],
          };
        }
        measured.push(landed);
        onPoint?.(landed, index);
      }
    } finally {
      onDoing?.(null);
      await ask(`${OURS}/focus/end`, { stopped }).catch(() => {});
    }
    return { points: measured, stopped };
  },

  /** The operator's Interrupt for the focus run: the loop above stops before
      its next drive, and returns what was measured. The bridge is asked too,
      because a point whose scoring has hung never reaches "before its next
      drive"; its stop puts the analysis down, and that scoring answers. */
  async stopFocusMeasure() {
    focusStopAsked = true;
    await ask(`${OURS}/focus/stop`, {}).catch(() => {});
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
  }: {
    fields?: string[] | null; settings?: Record<string, unknown>;
    onField?(field: FoundField): void; onDoing?(doing: string | null): void;
    onProgress?(done: number, of: number, how: { phase: unknown; objects: number; running: boolean }): void;
  } = {}) {
    await ask(`${OURS}/targets/discover`, { fields, settings });
    /* The bridge lists fields in the order they land and keeps that order,
       so the fields held here are the cursor: each poll asks only for the
       ones landed since, and a run of hundreds of fields is not carried
       whole three times a second. */
    const landed: FoundField[] = [];
    for (;;) {
      const progress = await askedPatiently<RunProgress & {
        doing?: string; phase?: unknown; objects?: number; fields?: FoundField[]; failed?: string[];
      }>(`${OURS}/targets/discover?since=${landed.length}`);
      onDoing?.(progress.running ? progress.doing ?? null : null);
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
    return ask(`${OURS}/targets/discover/stop`, {});
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
  }: {
    positions: ScanPosition[]; acquisition_type?: string; state?: Record<string, unknown> | null;
    onProgress?(done: number, of: number, at: { x: number; y: number; z: number | null } | null, records: CaptureRecord[]): void;
    append?: boolean; planned?: unknown;
  }) {
    await ask(`${OURS}/scan`, { positions, acquisition_type, state, append, planned });
    /* The records so far, kept here: each poll asks only for the ones that
       landed since, so a long scan is not carried whole three times a second. */
    const records: CaptureRecord[] = [];
    for (;;) {
      const progress = await askedPatiently<RunProgress>(`${OURS}/scan?since=${records.length}`);
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
    return ask(`${OURS}/scan/stop`, {});
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
    positions, state = null, append = false, focus = null, zOffsetUm = 0, onProgress, onDoing,
  }: {
    positions: TargetPosition[];
    state?: Record<string, unknown> | null; append?: boolean;
    focus?: TargetFocus | null; zOffsetUm?: number;
    onProgress?(done: number, of: number, at: { x: number; y: number; z: number | null }, records: CaptureRecord[]): void;
    onDoing?(doing: string | null): void;
  }) {
    targetsStopAsked = false;
    const { labels } = await ask<{ labels: string[] }>(`${OURS}/targets/acquire/begin`, { positions, append });
    if (!focus && state) await ask(`${OURS}/state`, state);
    const records: CaptureRecord[] = [];
    let stopped = false;
    try {
      for (const [index, position] of positions.entries()) {
        if (targetsStopAsked) { stopped = true; break; }
        const say = (phase: string) => onDoing?.(`${phase} target ${index + 1} of ${positions.length}`);
        const { x, y, z: zMap = null, focusAt = null } = position;
        /* The operator's offset rides on whatever height is chosen below:
           the map's, the peak's, or where the objective stood. */
        const lifted = (z: number) => z + zOffsetUm;
        let at: Place = { x, y, ...(typeof zMap === "number" && Number.isFinite(zMap) ? { z: lifted(zMap) } : {}) };
        /* The stack is taken on the object's centre when the page names it,
           which need not be the middle of the tile imaged after it. */
        const focusXY = focusAt ?? { x, y };
        const focusMoves = focusXY.x !== x || focusXY.y !== y;
        let found: { settings: unknown; z_map_um: number | null; z_peak_um: number | null; found: boolean } | null = null;
        /* Where the objective stood for the stack: the height the target is
           taken at when the stack shows no peak, map or no map. */
        let standing: number | null = null;
        if (focus) {
          say("focussing on");
          if (focus.state) await ask(`${OURS}/state`, focus.state);
          /* The stack is taken at the map's own height, without the offset:
             the offset is for the target, and is added once to the height
             chosen from the stack. Taken at the lifted height, a stack with
             no peak lifted the target a second time. */
          const stood = await ask<XyzReading>(`${OURS}/xyz`, {
            x: focusXY.x, y: focusXY.y, ...(typeof zMap === "number" && Number.isFinite(zMap) ? { z: zMap } : {}),
          });
          standing = stood.z.position;
          const stack = capturedBy(await ask<ControllerAnswer<CaptureRecord>>(`${OURS}/acquire`, {
            acquisition_type: "target-focussing", position_label: labels[index], acquisition_settings: null,
          }));
          const scored = await ask<{ traces?: Traces | null }>(`${OURS}/targets/acquire/focus`, {
            record: stack, centre: standing, x: focusXY.x, y: focusXY.y,
          });
          const curve = scored.traces?.[focus.metric];
          const peak = curve?.samples?.length ? pickPeak(findCandidates(curve.samples)) : null;
          found = {
            settings: focus.state ?? null, z_map_um: typeof zMap === "number" && Number.isFinite(zMap) ? zMap : null,
            z_peak_um: peak ? peak.z : null, found: peak !== null,
          };
          if (peak) at = { x, y, z: lifted(peak.z) };
          else if (standing !== null && Number.isFinite(standing)) at = { x, y, z: lifted(standing) };
          if (state) await ask(`${OURS}/state`, state);
        }
        say("imaging");
        /* Already standing there after a stack with no peak: no second drive. */
        const stood = focus && found && !found.found && !focusMoves && !zOffsetUm
          ? { z: { position: standing as number } } : await ask<XyzReading>(`${OURS}/xyz`, at);
        const record = capturedBy(await ask<ControllerAnswer<CaptureRecord>>(`${OURS}/acquire`, {
          acquisition_type: "targets", position_label: labels[index], acquisition_settings: null,
        }));
        const landed = await ask<CaptureRecord>(`${OURS}/targets/acquire/landed`, {
          record, position: { x, y, z: stood.z.position }, focus: found,
        });
        records.push(landed);
        onProgress?.(records.length, positions.length, { x, y, z: stood.z.position }, records);
      }
    } finally {
      onDoing?.(null);
      await ask(`${OURS}/targets/acquire/end`, { stopped }).catch(() => {});
    }
    return { done: records.length, of: positions.length, records, stopped };
  },

  /**
   * The protocols written under this session's output root, newest first,
   * each with its settings inline: the list is short and the files small,
   * so there is nothing to fetch a second time.
   */
  async protocols(instrument: string | null = null) {
    const { protocols } = await ask<{ protocols?: WrittenProtocol[] }>(`${OURS}/protocols`, instrument ? { instrument } : undefined);
    return protocols ?? [];
  },

  /** The run's settings, written as `protocol.json` into the run folder. */
  async saveProtocol(protocol: Record<string, unknown>) {
    return ask(`${OURS}/protocol`, { protocol });
  },

  /** The settings saved by name into this machine's library, under ProgramData. */
  async saveProtocolAs(protocol: Record<string, unknown>, name: string) {
    return ask<{ id: string }>(`${OURS}/protocol/save`, { protocol, name });
  },

  /**
   * A multidimensional plot of the detected population -- `pca` or `umap`
   * -- over the objects named by `ids`, or every candidate when left out.
   * The bridge runs it through the analysis and this follows it until it
   * lands; then every plot it wrote comes back as columns by id
   * (`{columns, ids, values}`), a UMAP bringing the components it stood on.
   */
  async computePlot({ kind, ids = null, onDoing }: {
    kind: string; ids?: unknown[] | null; onDoing?(doing: string | null): void;
  }) {
    await ask(`${OURS}/plots/compute`, { kind, ids });
    for (;;) {
      const progress = await askedPatiently<RunProgress & {
        doing?: string; kinds?: string[]; objects?: number; took_s?: number;
      }>(`${OURS}/plots/compute`);
      onDoing?.(progress.running ? progress.doing ?? null : null);
      if (!progress.running) {
        if (progress.error) throw new Error(progress.error);
        if (progress.stopped) return { stopped: true, columns: [] };
        const columns: PlotColumns[] = [];
        for (const one of progress.kinds ?? []) {
          columns.push(await ask<PlotColumns>(`${OURS}/plots/columns?kind=${encodeURIComponent(one)}`));
        }
        return { stopped: false, objects: progress.objects, seconds: progress.took_s, columns };
      }
      await rest(500);
    }
  },

  /** The operator's Interrupt for a plot: the bridge puts its worker down. */
  async stopPlot() {
    return ask(`${OURS}/plots/compute/stop`, {});
  },

  /** The operator's Interrupt for the target run: the loop above stops
      before its next drive, and returns what was taken. */
  async stopAcquireTargets() {
    targetsStopAsked = true;
    return { stopped: true };
  },
};
