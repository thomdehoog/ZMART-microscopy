/**
 * What target acquisition's backend verbs take and answer.
 *
 * The live backend (`live.ts`) and the in-browser rehearsal (`pretend.ts`)
 * have the same verbs, and the promises both keep (`backend-contract.ts`)
 * are about these shapes. Most of them are the ZMART Controller's own --
 * a stage reading, a capture record -- carried through the bridge as JSON;
 * the rest are this workflow's runs, as its Python half reports them.
 *
 * Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
 * University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
 */

import type { ChannelSpec } from "../canvas/engines/neuroglancer-under/viewer.ts";
import type { ListedInstrument } from "../microscope/instruments.ts";
import type { Reading } from "../microscope/settings.ts";
import type { Sample } from "../microscope/pretend-sample/sweep.ts";


/** A stretch along one axis, `[min, max]` in micrometres. */
export type Span = [number, number];

/** One axis as `get_xyz` reports it. */
interface AxisReading {
  position: number;
  unit: string;
  /** The motor this axis moved by: one of `actuator_readings`. */
  used_actuator: string;
  actuator_readings: Record<string, number>;
  canvas: Span;
}

/** Where the stage is, per axis, as `get_xyz` reports it; `busy` while a run holds the instrument. */
export interface XyzReading {
  x: AxisReading;
  y: AxisReading;
  z: AxisReading;
  busy?: boolean;
}

/** A place on the stage, in micrometres; an axis left out stays where it is. */
export interface Place {
  x?: number | null;
  y?: number | null;
  z?: number | null;
}

/** One picture a capture saved: which time point, plane and channel, and where it was taken. */
interface Plane {
  t: number;
  z: number;
  c: number;
  path: string;
  x_um: number;
  y_um: number;
  /** Null where nothing said what height the field was taken at. */
  z_um: number | null;
}

/** What a capture wrote, as the controller's `acquire` answers it, and what the workflow files on it. */
export interface CaptureRecord {
  position_label: string;
  acquisition_type?: string;
  files: string[];
  planes: Plane[];
  position?: { x: number; y: number; z: number };
  [more: string]: unknown;
}

/** The controller's two-part answer. */
export interface ControllerAnswer<T> {
  success: boolean;
  output: T | string | { reason?: string; message?: string } | null;
}

/** One sharpness curve, by measure. */
export type Traces = Record<string, { samples: Sample[] }>;

/** A focus point as asked for: where, where its search begins, and a height the operator set by hand. */
export interface FocusAsk {
  x: number;
  y: number;
  z?: number | null;
  startZ?: number;
  manual?: boolean;
  [more: string]: unknown;
}

/** A focus point as a map keeps it: placed, and once measured, what was found there. */
export interface FocusSpot {
  x: number;
  y: number;
  z: number | null;
  zAuto?: number | null;
  startZ?: number;
  lost?: boolean;
  refused?: string;
  manual?: boolean;
  stale?: boolean;
  traces?: Traces | null;
  cost_s?: Record<string, number>;
  slices?: unknown[];
  [more: string]: unknown;
}

/** A focus point as measured: the spot, with its curves. */
export interface FocusPoint extends FocusSpot {
  traces: Traces | null;
}

/** A scan's or a target run's progress, as the poll reads it. */
export interface RunProgress<R = CaptureRecord> {
  running: boolean;
  done: number;
  of: number;
  error?: string | null;
  stopped?: boolean;
  records?: R[];
  [more: string]: unknown;
}

/** One object found in a field: its id, its field, where it is, and what was measured of it. */
export interface FoundObject {
  id: string;
  field: number;
  x: number;
  y: number;
  features?: Record<string, number>;
  area?: number;
  intensity?: number;
  [more: string]: unknown;
}

/** One field's targets, as discovery files them. */
export interface FoundField {
  field: number;
  position_label?: string;
  cells: FoundObject[];
  device?: string;
  [more: string]: unknown;
}

/** A plot's columns by id, as the analysis wrote them. */
export interface PlotColumns {
  columns?: string[];
  ids?: unknown[];
  values?: unknown[];
  [more: string]: unknown;
}

/** A protocol written on this machine. */
export interface WrittenProtocol {
  id: string;
  protocol: Record<string, unknown>;
  [more: string]: unknown;
}

/**
 * An acquisition as ZMART Viewer lists it. A published one names its stores
 * on its channels and not always beside itself, so it may have no `url`: the
 * page works out what to draw from it, and leaves out what has nothing to draw.
 */
export interface PublishedAcquisition {
  name: string;
  url?: string;
  channels?: ChannelSpec[];
  opaque?: boolean;
  embeddingUrl?: string;
  [more: string]: unknown;
}

/** What ZMART Viewer holds of this run, and how far each acquisition is published. */
export interface ViewerStatus {
  acquisitions?: PublishedAcquisition[];
  sources?: Record<string, { url: string; name: string }[]>;
  publications?: Record<string, { acquired?: number; published?: number; state?: string }>;
  error?: string;
  [more: string]: unknown;
}

/** The connection's checks, as the window shows them while they answer. */
export interface Connecting {
  onChecks?(keys: string[]): void;
  onCheck?(index: number, value: string): void;
}

/** What can be connected to, and the folder the last run went to (at first `--output-root`). */
export interface Instruments {
  instruments: ListedInstrument[];
  output_root: string | null;
}

/** What the session is opened with: the chosen name, and what the operator typed. */
export interface Opening {
  instrument?: string;
  password?: string;
  host?: string;
  client?: string;
  config?: string;
  outputRoot?: string;
  [more: string]: unknown;
}

export type { Reading };

/** What the window shows while a run goes: a sentence, or nothing when it is over. */
type Doing = (doing: string | null) => void;

/** A field to scan: where, and where it sits on the carrier as the plan names it. */
export interface ScanPosition {
  x: number;
  y: number;
  z?: number | null;
  position_index?: number;
  carrier?: number;
  compartment?: number;
  group?: number;
  view?: number;
  frameUm?: number;
  [more: string]: unknown;
}

/** A target to take: where, the height the map gives, and where its focus is sought. */
export interface TargetPosition extends ScanPosition {
  focusAt?: { x: number; y: number } | null;
}

/** The focussing asked for before each target: its recording's state, and the measure that decides. */
export interface TargetFocus {
  state?: Record<string, unknown> | null;
  metric: string;
  /** The carrier's size, which the pretend sample's tilt is a fraction of. */
  extent?: [number, number];
}

/**
 * Every verb target acquisition's steps call. `live.ts` answers each over
 * the bridge, `pretend.ts` in the browser; one interface, so the two cannot
 * drift apart without the type checker saying where.
 */
export interface Backend {
  viewOf(acquisitionType: string): string | null;
  viewerSources(onStatus?: (status: ViewerStatus) => void): Promise<PublishedAcquisition[] | null>;
  instruments(): Promise<Instruments>;
  connect(session: Opening | null | undefined, connecting?: Connecting): Promise<{ info: Record<string, unknown> }>;
  disconnect(): Promise<void>;
  info(): Promise<Record<string, unknown>>;
  get_xyz(): Promise<XyzReading>;
  set_xyz(place: Place): Promise<XyzReading>;
  get_acquisition_settings(): Promise<Record<string, unknown>>;
  set_state(settings: Record<string, unknown>): Promise<{ applied: Record<string, unknown> }>;
  readSetting(type: string, how?: { nth?: number }): Promise<Reading>;
  acquire(asked: {
    position_label: string; acquisition_settings?: Record<string, unknown> | null; acquisition_type?: string | null;
  }): Promise<ControllerAnswer<CaptureRecord>>;
  raiseTarget?(position_label: string): Promise<unknown>;
  measureFocus(points: FocusAsk[], how?: {
    metric?: string; extent?: [number, number]; state?: Record<string, unknown> | null;
    onPoint?(point: FocusPoint, index: number): void; onDoing?: Doing;
    beginAt?(index: number): number | null | undefined;
  }): Promise<{ points: FocusPoint[]; stopped: boolean }>;
  stopFocusMeasure(): Promise<{ stopped: boolean }>;
  discoverTargets(how?: {
    fields?: string[] | null; settings?: Record<string, unknown>;
    onField?(field: FoundField): void; onDoing?: Doing;
    onProgress?(done: number, of: number, how: { phase: unknown; objects: number; running: boolean }): void;
  }): Promise<{ fields: FoundField[]; failed: unknown[]; stopped: boolean }>;
  stopTargets(): Promise<unknown>;
  scanOverview(how: {
    positions: ScanPosition[]; acquisition_type?: string; state?: Record<string, unknown> | null;
    onProgress?(done: number, of: number, at: { x: number; y: number; z: number | null } | null, records: CaptureRecord[]): void;
    append?: boolean; planned?: unknown; ms?: number;
  }): Promise<{ done: number; of: number; records: CaptureRecord[]; stopped: boolean }>;
  stopScan(): Promise<unknown>;
  acquireTargets(how: {
    positions: TargetPosition[]; state?: Record<string, unknown> | null; append?: boolean;
    focus?: TargetFocus | null; zOffsetUm?: number; ms?: number;
    onProgress?(done: number, of: number, at: { x: number; y: number; z: number | null }, records: CaptureRecord[]): void;
    onDoing?: Doing;
  }): Promise<{ done: number; of: number; records: CaptureRecord[]; stopped: boolean }>;
  stopAcquireTargets(): Promise<{ stopped: boolean }>;
  protocols(instrument?: string | null): Promise<WrittenProtocol[]>;
  saveProtocol(protocol: Record<string, unknown>): Promise<unknown>;
  saveProtocolAs(protocol: Record<string, unknown>, name: string): Promise<{ id: string }>;
  computePlot(how: { kind: string; ids?: unknown[] | null; onDoing?: Doing }): Promise<{
    stopped: boolean; columns: PlotColumns[]; objects?: number; seconds?: number;
  }>;
  stopPlot(): Promise<unknown>;
}
