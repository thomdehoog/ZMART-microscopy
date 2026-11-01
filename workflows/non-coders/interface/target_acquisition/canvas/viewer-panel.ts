/**
 * The picture's display settings: this page's own controls for what the
 * engine draws.
 *
 * They are dressed like the ZMART viewer's own panel, so an operator meets one
 * look in both: the 264px bar with its 14px fold strip, the card-on-panel
 * grounds, the eye glyph, the swatch that opens a palette, the 60px histogram
 * with dimmed out-of-window bars and two accent edge lines the hand can drag,
 * the min/max sliders with typed value boxes, and opacity per channel. The
 * likeness is a choice, not a tie: this page decides its controls, and tells
 * the engine the values -- colour, window, opacity -- it should draw with.
 *
 * The rows are enumerated exactly the way the engine enumerates its own —
 * one per channel, acquisitions in order — so the flat index handed to
 * `viewer.setChannel(index, …)` names the same row on both sides.
 */

import type { PanelSnapshot } from "./display-of.ts";
import type { Acquisition } from "./engines/neuroglancer-under/viewer.ts";

/** A colour as three numbers from 0 to 1. */
type Rgb = number[];

/** A stretch of stored counts. */
interface Span {
  low: number;
  high: number;
}

/** A histogram the viewer measured: counts in equal bins from `low` to `high`, and the window it would open on. */
interface Measured {
  low: number;
  high: number;
  counts: number[];
  autoWindow?: Span;
}

/** One channel row of the panel, numbered the way the engine numbers its own. */
export interface PanelRow {
  acquisition: string;
  name: string;
  color: string | null;
  colour: Rgb | null;
  window: Span | null;
  within: number;
  source: string;
  sources: string[];
  histogram: Measured | null;
  range: Span | null;
  visible: boolean;
  weight: number;
  gamma?: number;
  saturate?: number;
  log?: boolean;
  axis?: Span | null;
  grey?: boolean;
  colorInColour?: string | null;
  colourInColour?: Rgb | null;
  colourWindow?: Span | null;
  colourWeight?: number;
}

/** What the panel remembers of a channel across remounts. */
type Remembered = Partial<Omit<PanelRow, "acquisition" | "name" | "within" | "source" | "sources" | "range">>;

/** The operator's requested state, which outlives any one panel. */
export interface PanelState {
  acquisitions: Map<string, boolean>;
  channels: Map<string, Remembered | boolean>;
  collapsed: Map<string, boolean>;
  selectedKey: string | null;
  lastMismatch: { at: string; rows: unknown[] } | null;
}

/** One channel as the engine reports it holds it, for the panel to hold it to what was asked. */
interface EngineRow {
  visible?: boolean;
  weight?: number;
  window?: Span | null;
  sources?: { error?: unknown; lower?: unknown; upper?: unknown }[];
  [more: string]: unknown;
}

/** What the panel asks of the engine underneath. */
export interface PanelViewer {
  setChannel(index: number, change: { visible?: boolean; colour?: Rgb; window?: Span; weight?: number; gamma?: number }): void;
  measurementBox?(index: number): [[number, number], [number, number]] | null;
  layersForMeasurement?(): EngineRow[];
}

/** What a measurement by the viewer's server came to. */
type Measurement =
  | { ok: true; answer: { histogram: Measured; window: Span; [more: string]: unknown } }
  | { ok: false; message?: string; empty?: boolean; aborted?: boolean };

/** The grey channel an acquisition collapses to: its window as shares of each member's, its opacity as a factor. */
interface Composite {
  a: number;
  b: number;
  s: number;
  log: boolean;
}

/** One channel as a chip in the canvas's row shows it. */
interface ChannelChip {
  index: number;
  name: string;
  color: string;
  visible: boolean;
  chosen: boolean;
}

/** A change to one channel, as the box under the canvas row asks for it. */
interface ChannelAct {
  window?: Span;
  axis?: Span | null;
  weight?: number;
  log?: boolean;
  gamma?: number;
  saturate?: number;
  colour?: string | Rgb;
}

/**
 * The panel as the page reaches it: the element, and what it answers.
 * The page reads it through the picture (`page.thePicture.panel()`), the
 * tests through `window.__viewerPanel`; nothing here exposes neuroglancer.
 */
export interface ViewerPanelElement extends HTMLElement {
  snapshot: () => PanelSnapshot;
  sourcesChanged: (next: Acquisition[]) => Promise<boolean>;
  showAcquisition: (name: string, on: boolean) => void;
  drawInGrey: (name: string, grey: boolean) => void;
  acquisitions: () => { name: string; shown: boolean; channels: number }[];
  channelsOf: (name: string) => ChannelChip[];
  setChannelVisible: (index: number, on: boolean) => void;
  chooseRow: (index: number) => void;
  acquisitionShown: (name: string) => boolean;
  onChanged: (hook: () => void) => () => boolean;
  composite: (name: string) => (Composite & { counts: number[]; measured: number; channels: number }) | null;
  setComposite: (name: string, next: Partial<Composite>) => void;
  autoComposite: (name: string) => Promise<void>;
  acquisitionGrey: (name: string) => boolean;
  channelBox: (index: number) => {
    name: string; color: string | null; hex: string; visible: boolean; counts: number[]; range: Span | null;
    window: Span; axis: Span; weight: number; log: boolean; gamma: number; saturate: number; measured: boolean;
  } | null;
  channelAct: (index: number, next: ChannelAct) => void;
  gammaOf: (name: string) => number;
  setGammaOf: (name: string, gamma: number) => void;
  makeItLook: (names?: string[] | null) => Promise<void>;
  autoChannel: (index: number) => Promise<void>;
  lendSettingsCard: (into: HTMLElement) => void;
  reclaimSettingsCard: () => void;
  requestedState: PanelState;
  /** How the picture may be drawn, and how it is: put on the panel by the scan step's watcher. */
  viewModes?: (acquisition: string | null) => string[];
  viewMode?: () => string;
}

/** What `mountViewerPanel` answers. */
export interface MountedPanel {
  element: ViewerPanelElement;
  snapshot: () => PanelSnapshot;
  sourcesChanged: (next: Acquisition[]) => Promise<boolean>;
  showAcquisition: (name: string, on: boolean) => void;
  drawInGrey(name: string, grey: boolean): void;
  destroy(): void;
}

declare global {
  interface Window {
    /** The canvas's display panel, while one is mounted. */
    __viewerPanel?: ViewerPanelElement | null;
  }
}

/** A slider, dressed: it can be asked to fill its track again. */
type Dressed = HTMLInputElement & { refill: () => void };

/* The viewer's light dress, inlined from its `theme.css` — the operator page
   has no dark mode, so only the light values travel. */
const INK = {
  pageBg: "#e7eaee", cardBg: "#f7f8fa", inputBg: "#ffffff",
  panelBorder: "#c7cdd6", controlBorder: "#b6bec9", subtleBorder: "#dce0e6",
  textBright: "#10161f", textPrimary: "#26303c", textMuted: "#5a6675",
  textFaint: "#67727f", accent: "#2563cf", chosenGround: "#dde8f7",
  ghost: "rgba(0, 0, 0, 0.05)", sliderTrack: "#c2c9d2",
};

/* The colours a channel can be given here: the same few the ZMART viewer
   offers, green and magenta first because they read best on dark ground and
   stay legible to a colour-blind eye. This page's choice, kept here. */
const PALETTE = [
  { name: "green", rgb: [0.0, 1.0, 0.4] },
  { name: "magenta", rgb: [1.0, 0.2, 1.0] },
  { name: "cyan", rgb: [0.2, 0.8, 1.0] },
  { name: "amber", rgb: [1.0, 0.75, 0.1] },
  { name: "blue", rgb: [0.3, 0.45, 1.0] },
  { name: "red", rgb: [1.0, 0.15, 0.15] },
  { name: "grey", rgb: null },
];
const cssOf = (rgb: Rgb | null | undefined): string =>
  rgb ? `rgb(${rgb.map((v) => Math.round(v * 255)).join(",")})` : "#d8dee6";
/**
 * A colour's share of the light: the luminance the eye reads it at, by the
 * weights a desaturation uses (Rec. 709). Grey draws each channel at this
 * level rather than white, so the channels added together read as the
 * coloured picture desaturated would -- three whites added clipped a
 * quarter of a three-channel field, and the operator saw it.
 */
export const luminanceOf = ([r, g, b]: Rgb): number => 0.2126 * r + 0.7152 * g + 0.0722 * b;
const hexOf = (rgb: Rgb | null | undefined): string => rgb
  ? `#${rgb.map((value) => Math.round(Math.min(1, Math.max(0, value)) * 255)
    .toString(16).padStart(2, "0")).join("")}`
  : "#ffffff";
const rgbOf = (hex: string): Rgb => {
  const value = parseInt(hex.replace("#", ""), 16);
  return [(value >> 16 & 255) / 255, (value >> 8 & 255) / 255, (value & 255) / 255];
};

/* The 15% rule: the window's edges are drawn at 15% and 85% of the axis. */
const WINDOW_SITS_FROM = 0.15;

const font = (weight: number, size: number) => `${weight} ${size}px/1 system-ui, sans-serif`;

/* The viewer's filled slider skin, said once per page. */
const SLIDER_CSS = `
.zv-range { -webkit-appearance:none; appearance:none; background:transparent; height:16px; padding:0; width:100%; cursor:pointer; }
.zv-range::-webkit-slider-runnable-track { height:4px; border-radius:2px;
  background: linear-gradient(to right, ${INK.accent} var(--fill, 0%), ${INK.sliderTrack} var(--fill, 0%)); }
.zv-range::-webkit-slider-thumb { -webkit-appearance:none; width:14px; height:14px; margin-top:-5px; border-radius:50%; border:none; background:${INK.accent}; }
.zv-range:disabled { opacity:.45; cursor:default; }`;

function dressed(input: HTMLInputElement): Dressed {
  const slider = input as Dressed;
  const fill = () => {
    const low = Number(slider.min), high = Number(slider.max);
    const share = high > low ? (Number(slider.value) - low) / (high - low) : 0;
    slider.style.setProperty("--fill", `${Math.min(1, Math.max(0, share)) * 100}%`);
  };
  slider.classList.add("zv-range");
  slider.addEventListener("input", fill);
  slider.refill = fill;
  fill();
  return slider;
}

/** The store's description, read where either generation of the format keeps it. */
async function theStoresDescription(url: string): Promise<any> {
  const bar = url.indexOf("|");
  const address = (bar < 0 ? url : url.slice(0, bar)).replace(/\/+$/, "");
  const spellings: [string, (doc: any) => any][] = [
    [".zattrs", (doc) => doc],
    ["zarr.json", (doc) => doc?.attributes?.ome ?? doc?.attributes ?? doc],
  ];
  for (const [file, unwrap] of spellings) {
    try {
      const answer = await fetch(`${address}/${file}`, { cache: "no-store" });
      if (answer.ok) return unwrap(await answer.json());
    } catch {
      // one of the two spellings is expected to be missing
    }
  }
  return null;
}

/** One flat row list, matching the engine's own numbering.
 *
 * Smart Viewer has already classified and measured its rows.  When those are
 * present on `acquisition.channels`, use them directly and, crucially, keep
 * each row's spatial `sources` together.  Reading every store as though it
 * were a new acquisition is the 9 × 3 = 27 bug this adapter exists to prevent.
 */
export async function viewerRowsFor(acquisitions: Acquisition[]): Promise<PanelRow[]> {
  const rows: PanelRow[] = [];
  for (const acquisition of acquisitions) {
    const offered = Array.isArray(acquisition.channels) && acquisition.channels.length
      ? acquisition.channels
      : null;
    const described = offered
      ? null
      : (await theStoresDescription(acquisition.url))?.omero?.channels;
    const channels: Omit<PanelRow, "acquisition">[] = offered
      ? offered.map((channel, at) => ({
        name: channel.name || `channel ${at}`,
        color: Array.isArray(channel.colour)
          ? cssOf(channel.colour)
          : (channel.color as string | undefined) ?? null,
        colour: Array.isArray(channel.colour) ? channel.colour : null,
        window: channel.window ?? null,
        within: Array.isArray(channel.localPosition)
          ? channel.localPosition[0]
          : channel.channelIndex ?? at,
        source: (channel.sources ?? [channel.source ?? acquisition.url])[0],
        sources: channel.sources ?? [channel.source ?? acquisition.url],
        histogram: (channel.histogram as Measured | undefined) ?? null,
        range: (channel.range as Span | undefined) ?? null,
        visible: channel.visible !== false,
        weight: channel.weight ?? 1,
      }))
      : Array.isArray(described) && described.length
        ? described.map((channel: any, at: number) => ({
          name: channel?.label || `channel ${at + 1}`,
          color: typeof channel?.color === "string" ? `#${channel.color}` : null,
          colour: typeof channel?.color === "string"
            ? [0, 2, 4].map((from) => parseInt(channel.color.slice(from, from + 2), 16) / 255)
            : null,
          window: channel?.window && Number.isFinite(channel.window.start)
            ? { low: channel.window.start, high: channel.window.end }
            : null,
          within: at,
          source: acquisition.url,
          sources: [acquisition.url],
          histogram: null,
          range: null,
          visible: true,
          weight: 1,
        }))
        : [{
          name: acquisition.name,
          color: null,
          colour: null,
          window: null,
          within: 0,
          source: acquisition.url,
          sources: [acquisition.url],
          histogram: null,
          range: null,
          visible: true,
          weight: 1,
        }];
    for (const channel of channels) {
      rows.push({
        ...channel,
        acquisition: acquisition.name,
      });
    }
  }
  return rows;
}

/** Ask the real Viewer server about one channel without inventing a fallback. */
import { windowFromHistogram, windowForTheLook } from "./auto-window.ts";

/**
 * The colours the one-press look dresses the channels in, by their order
 * within an acquisition: the same order gives the same colour in every
 * acquisition, so the overview and the target frame read as one picture --
 * a one-channel target scan wears the overview's first colour rather than
 * a colour of its own. Cyan and magenta add to white where they overlap
 * and stay apart everywhere else; further channels take the remaining
 * well-separated hues.
 */
const LOOK_COLOURS = [
  [0.2, 0.85, 1.0],   // cyan
  [1.0, 0.25, 0.9],   // magenta
  [1.0, 0.85, 0.15],  // yellow
  [0.25, 1.0, 0.35],  // green
  [1.0, 0.35, 0.2],   // orange-red
  [0.45, 0.5, 1.0],   // blue
];

async function measureViewerRow(row: PanelRow, {
  signal = null,
  box = [[0, 0], [1, 1]],
}: { signal?: AbortSignal | null; box?: [[number, number], [number, number]] } = {}): Promise<Measurement> {
  try {
    const origin = new URL(row.source).origin;
    const answer = await fetch(`${origin}/api/measure`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal,
      body: JSON.stringify({
        source: row.source, sources: row.sources, channel: row.within, box,
      }),
    });
    if (!answer.ok) {
      return { ok: false, message: `Measurement failed (${answer.status}).` };
    }
    const body = await answer.json().catch(() => null);
    if (!body?.histogram || body.empty || !body.window) {
      return { ok: false, empty: true, message: "No imaged pixels are visible to measure." };
    }
    return { ok: true, answer: body };
  } catch (error) {
    if ((error as Error | null)?.name === "AbortError") return { ok: false, aborted: true };
    return { ok: false, message: "Measurement failed; the current window was kept." };
  }
}

/** A channel identity that survives source growth and panel remounting. */
const viewerChannelKey = (row: Pick<PanelRow, "acquisition" | "within" | "name">): string =>
  `${row.acquisition}\u0000${row.within}\u0000${row.name}`;

/**
 * Smart Operator's requested panel state.
 *
 * The engine is deliberately absent. This object records what the operator
 * asked for and can be handed to a replacement panel or Viewer without making
 * either of them the owner of the controls.
 *
 * @public — the browser specs take it by the page's address, which knip
 * cannot follow (`workflows/target_acquisition/testing/page-addresses.test.ts` holds them to it).
 */
export function createViewerPanelState(): PanelState {
  return {
    acquisitions: new Map(),
    channels: new Map(),
    collapsed: new Map(),
    selectedKey: null,
    lastMismatch: null,
  };
}

function completePanelState(given: Partial<PanelState> | null | undefined): PanelState {
  const state = (given ?? createViewerPanelState()) as PanelState;
  state.acquisitions ??= new Map();
  state.channels ??= new Map();
  state.collapsed ??= new Map();
  state.selectedKey ??= null;
  state.lastMismatch ??= null;
  return state;
}

function rememberedChannel(state: PanelState, row: PanelRow): Remembered {
  const saved = state.channels.get(viewerChannelKey(row));
  /* Visibility-only maps were used by the cleanup before the rest of the
     panel became persistent. Accept them so a running session upgrades rather
     than forgetting the eyes the operator already set. */
  const remembered: Remembered = typeof saved === "boolean" ? { visible: saved } : (saved ?? {});
  /* Older running panels remembered the temporary grey RGB triplet but not
     that it was temporary. On remount that made the button say "colour"
     while another press merely greyed an already-grey acquisition again.
     A coloured fresh channel paired with an achromatic remembered one is the
     recoverable signature of that state. */
  const isGrey = (colour: Rgb | null | undefined) => Array.isArray(colour) && colour.length >= 3
    && Math.abs(colour[0] - colour[1]) < 1e-9
    && Math.abs(colour[1] - colour[2]) < 1e-9;
  const legacyGrey = remembered.grey === undefined
    && isGrey(remembered.colour)
    && Array.isArray(row.colour)
    && !isGrey(row.colour);
  const grey = remembered.grey ?? legacyGrey;
  return {
    visible: remembered.visible ?? row.visible,
    color: remembered.color ?? row.color,
    colour: remembered.colour ?? row.colour,
    window: remembered.window ?? row.window,
    weight: remembered.weight ?? row.weight ?? 1,
    gamma: remembered.gamma ?? row.gamma ?? 1,
    saturate: remembered.saturate ?? row.saturate ?? 1,
    log: remembered.log ?? false,
    axis: remembered.axis ?? null,
    histogram: remembered.histogram ?? row.histogram,
    grey,
    colorInColour: remembered.colorInColour ?? (grey ? row.color : null),
    colourInColour: remembered.colourInColour ?? (grey ? row.colour : null),
  };
}

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, style?: string | null, text?: string) => {
  const made = document.createElement(tag);
  if (style) made.style.cssText = style;
  if (text !== undefined) made.textContent = text;
  return made;
};

const HEADING = `font:${font(600, 11)};letter-spacing:.08em;text-transform:uppercase;color:${INK.textFaint};padding:0 12px 5px;`;
const CARD = `border-top:1px solid ${INK.panelBorder};border-bottom:1px solid ${INK.panelBorder};padding:8px 0 12px;margin-bottom:12px;background:${INK.cardBg};flex-shrink:0;`;

/** The eye glyph: shown or hidden, drawn as the viewer draws it. */
function anEye(open: boolean): SVGSVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.style.cssText = "width:14px;height:14px;display:block;";
  svg.innerHTML =
    '<path d="M1 8s2.6-4.2 7-4.2S15 8 15 8s-2.6 4.2-7 4.2S1 8 1 8z" fill="none" stroke="currentColor" stroke-width="1.3"/>'
    + '<circle cx="8" cy="8" r="1.9" fill="currentColor"/>'
    + (open ? "" : '<path d="M2.5 13.5L13.5 2.5" stroke="currentColor" stroke-width="1.3"/>');
  return svg;
}

/**
 * Mount the panel and wire it to the engine handle. Returns `{ destroy }`.
 * `near` is any element inside the canvas's own box; the panel stands as a
 * column of the same grid row, directly to the canvas's right -- or, given
 * `into`, fills that element instead: the page's own column for the display
 * settings, a tab away from the step's channel, where the tab is the fold
 * and the column is the width.
 */
export async function mountViewerPanel(near: HTMLElement | null, {
  viewer,
  acquisitions,
  into = null,
  requestedState = null,
  changed = null,
  /* Kept for callers from the first cleanup checkpoint. */
  requestedVisibility = null,
}: {
  viewer: PanelViewer;
  acquisitions: Acquisition[];
  into?: HTMLElement | null;
  requestedState?: Partial<PanelState> | null;
  changed?: (() => void) | null;
  requestedVisibility?: Partial<PanelState> | null;
}): Promise<MountedPanel> {
  const rows = await viewerRowsFor(acquisitions);
  /* Source/config growth may replace this DOM, never the operator's choices.
     Acquisition and channel visibility are deliberately separate: hiding a
     group must not erase which channels return when the group is shown again. */
  const panelState = completePanelState(requestedState ?? requestedVisibility);
  const rememberedGroups = panelState.acquisitions;
  const rememberedChannels = panelState.channels;
  let visibilityReady = false;
  let observationTimer: ReturnType<typeof setInterval> | null = null;
  let changedTimer: ReturnType<typeof setTimeout> | null = null;
  /* A slider can produce dozens of inputs in one gesture. The canvas should
     follow all of them immediately, while consumers of rendered JPEG copies
     need only the settled display request. */
  const changedHooks = new Set<() => void>();
  const displayChangedSoon = () => {
    for (const hook of changedHooks) { try { hook(); } catch { /* a hook's own business */ } }
    if (typeof changed !== "function") return;
    if (changedTimer !== null) clearTimeout(changedTimer);
    changedTimer = setTimeout(() => {
      changedTimer = null;
      changed?.();
    }, 80);
  };
  rows.forEach((row) => {
    Object.assign(row, rememberedChannel(panelState, row));
    rememberedChannels.set(viewerChannelKey(row), rememberedChannel(panelState, row));
  });

  if (!document.getElementById("zv-slider-skin")) {
    const skin = document.createElement("style");
    skin.id = "zv-slider-skin";
    skin.textContent = SLIDER_CSS;
    document.head.append(skin);
  }

  const body = near?.closest?.(".canvas-body");
  const plotHost = body?.querySelector<HTMLElement>(".plot-host");

  /* The strip and the bar, the viewer's own arrangement: the 14px fold strip
     stands between the picture and the bar and stays when the bar goes. */
  /* The element, and below, what it answers: the page reaches both through it. */
  const panel = el("aside", "display:flex;flex-direction:row;min-height:0;overflow:hidden;") as ViewerPanelElement;
  panel.className = "viewer-panel";

  const fold = el("button", [
    "align-self:stretch", "width:14px", "border:none",
    `border-left:1px solid ${INK.panelBorder}`, `border-right:1px solid ${INK.panelBorder}`,
    `background:${INK.cardBg}`, `color:${INK.textMuted}`,
    `font:${font(400, 12)}`, "cursor:pointer", "padding:0",
  ].join(";"), "›");
  fold.type = "button";
  fold.title = "Fold the controls away";

  const bar = el("div", [
    "width:264px", "flex-shrink:0", "display:flex", "flex-direction:column",
    "min-height:0", "overflow-y:auto", `background:${INK.pageBg}`,
    "padding:12px 0 0", `font:${font(400, 13)}`, `color:${INK.textPrimary}`,
  ].join(";"));
  bar.style.lineHeight = "1.4";
  panel.append(fold, bar);

  /* Standing in the page's own column, the panel wears the page's boxes:
     a heading over a white card, like every step's controls. On its own
     beside the picture it keeps the viewer's grey cards. */
  const inPage = !!into;
  if (inPage) {
    fold.hidden = true;
    bar.style.background = "transparent";
    /* The channel's own margin around its boxes, as `.side-pad-around` gives
       every other step's. */
    bar.style.padding = "var(--box-gap) 14px 0";
    bar.style.gap = "var(--box-gap)";
  }
  function aCard(title: string) {
    if (!inPage) {
      const card = el("div", CARD);
      card.append(el("div", HEADING, title));
      return { card, body: card };
    }
    const card = el("div", "");
    card.className = "side-group";
    const head = el("div", "", title);
    head.className = "side-group-title";
    const body = el("div", "");
    body.className = "side-group-body";
    card.append(head, body);
    return { card, body };
  }

  let folded = false;
  fold.addEventListener("click", () => {
    folded = !folded;
    bar.style.display = folded ? "none" : "flex";
    fold.textContent = folded ? "‹" : "›";
    fold.title = folded ? "Show the controls" : "Fold the controls away";
  });

  /* ---- channel settings (built first, filled by the selection) ---- */
  const { card: settingsCard, body: settings } = aCard("channel settings");
  const chosenHead = el("div", "display:flex;flex-direction:column;gap:3px;padding:5px 12px 6px;");
  const chosenGroup = el("div", [
    `font:${font(600, 12)}`, `color:${INK.textPrimary}`, "letter-spacing:.02em",
    "overflow:hidden", "text-overflow:ellipsis", "white-space:nowrap",
  ].join(";"));
  const chosenLine = el("div", [
    "display:flex", "align-items:center", "gap:8px", "min-width:0",
    `background:${INK.chosenGround}`, "border-radius:3px", "padding:4px 6px",
    `font:${font(600, 12)}`, `color:${INK.textBright}`,
  ].join(";"));
  chosenHead.append(chosenGroup, chosenLine);

  const plotWrap = el("div", "padding:1px 12px 4px;");
  const plot = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  plot.setAttribute("preserveAspectRatio", "none");
  plot.style.cssText = [
    "display:block", "width:100%", "height:84px", `color:${INK.textBright}`,
    `background:${INK.inputBg}`, `border:1px solid ${INK.subtleBorder}`,
    "border-radius:3px", "touch-action:none",
  ].join(";");
  plotWrap.append(plot);

  const measurementNotice = el("div", [
    "display:none", "margin:0 12px 5px", "padding:4px 6px",
    `border:1px solid ${INK.controlBorder}`, "border-radius:3px",
    `background:${INK.inputBg}`, `color:${INK.textMuted}`,
    `font:${font(400, 10)}`, "line-height:1.35",
  ].join(";"));
  measurementNotice.setAttribute("role", "status");
  measurementNotice.dataset.measurementState = "idle";

  /* The value under the pointer is read by assistive technology only; it
     takes no room under the histogram, so the axis boxes sit right below. */
  const histogramValue = el("output", "position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);", "");
  histogramValue.setAttribute("aria-label", "histogram value");

  const valueInput = (label: string) => {
    const input = el("input", [
      "width:54px", "height:24px", "box-sizing:border-box",
      `background:${INK.inputBg}`, `border:1px solid ${INK.subtleBorder}`,
      "border-radius:3px", `color:${INK.textPrimary}`, `font:${font(400, 10)}`,
      "font-variant-numeric:tabular-nums", "text-align:right", "padding:1px 3px",
    ].join(";"));
    input.type = "text";
    input.inputMode = "numeric";
    input.setAttribute("aria-label", label);
    return input;
  };

  const axisRow = el("div", "display:flex;align-items:center;justify-content:space-between;gap:6px;padding:6px 12px 14px;");
  const axisLow = valueInput("axis from");
  const autoButton = el("button", [
    "width:54px", "height:24px", "padding:0", `border:1px solid ${INK.controlBorder}`,
    "border-radius:3px", `background:${INK.ghost}`, `color:${INK.textPrimary}`,
    `font:${font(600, 11)}`, "cursor:pointer",
  ].join(";"), "Auto");
  const logButton = autoButton.cloneNode(false) as HTMLButtonElement;
  logButton.textContent = "Log";
  for (const button of [autoButton, logButton]) button.type = "button";
  autoButton.setAttribute("aria-label", "auto contrast");
  logButton.setAttribute("aria-label", "logarithmic counts");
  logButton.setAttribute("aria-pressed", "false");
  const axisButtons = el("span", "display:flex;align-items:center;gap:4px;");
  /* How much Auto saturates: the percent of pixels set aside at each end.
     One is the viewer's own; a sample with a few bright objects wants five
     or ten, so the faint structure between them gets the window. */
  const saturateBox = valueInput("saturate");
  saturateBox.title = "Percent of pixels Auto saturates at each end";
  saturateBox.style.width = "40px";
  axisButtons.append(autoButton, saturateBox, logButton);
  const axisHigh = valueInput("axis to");
  axisRow.append(axisLow, axisButtons, axisHigh);

  const controlRow = (label: string) => {
    const line = el("label",
      `display:grid;grid-template-columns:58px 1fr 58px;gap:6px;align-items:center;padding:2px 12px;font-size:10px;color:${INK.textMuted};`);
    line.append(el("span", "", label));
    const slider = dressed(el("input"));
    slider.type = "range";
    slider.disabled = true;
    const box = valueInput(`${label} value`);
    box.disabled = true;
    line.append(slider, box);
    return { line, slider, box };
  };
  const minRow = controlRow("min");
  const maxRow = controlRow("max");
  const opacityRow = controlRow("opacity");
  opacityRow.slider.min = "0"; opacityRow.slider.max = "1"; opacityRow.slider.step = "0.01";
  opacityRow.slider.value = "1";
  /* gamma bends the curve between the window's ends; one is straight. */
  const gammaRow = controlRow("gamma");
  gammaRow.slider.min = "0.1"; gammaRow.slider.max = "4"; gammaRow.slider.step = "0.01";
  gammaRow.slider.value = "1";
  settings.append(
    chosenHead, plotWrap, measurementNotice, histogramValue, axisRow,
    minRow.line, maxRow.line, opacityRow.line, gammaRow.line,
  );

  /* ---- the state the settings act on ---- */
  let chosen: number | null = null;   // the flat row index picked out
  let shape: Measured | null = null;    // its measured histogram {low, high, counts, autoWindow}
  let logScale = false;
  let measurementGeneration = 0;
  let measurementController: AbortController | null = null;
  let measurementTimer: ReturnType<typeof setTimeout> | null = null;
  const actionRevision = new Map<string, number>();

  const remember = (row: PanelRow) => {
    rememberedChannels.set(viewerChannelKey(row), {
      visible: row.visible,
      color: row.color,
      colour: row.colour,
      window: row.window,
      weight: row.weight,
      gamma: row.gamma ?? 1,
      saturate: row.saturate ?? 1,
      log: row.log ?? false,
      axis: row.axis ?? null,
      histogram: row.histogram ?? null,
      grey: row.grey ?? false,
      colorInColour: row.colorInColour ?? null,
      colourInColour: row.colourInColour ?? null,
    });
  };

  const windowOf = (row: PanelRow): Span => row.window
    ?? (shape?.autoWindow && chosen !== null && rows[chosen] === row ? shape.autoWindow : null)
    ?? { low: 0, high: 65535 };

  const imageRange = (row: PanelRow): Span => {
    const declared = row.range;
    if (declared && Number.isFinite(declared.high) && declared.high > (declared.low ?? 0)) {
      return { low: declared.low ?? 0, high: declared.high };
    }
    const window_ = windowOf(row);
    return {
      low: Math.min(0, shape?.low ?? window_.low),
      high: Math.max(65535, shape?.high ?? window_.high),
    };
  };

  function restingAxis(row: PanelRow): Span {
    /* The window aims to sit at 15%..85% of the drawn axis. The image range
       is the wall; an axis must not describe brightness the source cannot hold. */
    const window_ = windowOf(row);
    const across = (window_.high - window_.low) / (1 - 2 * WINDOW_SITS_FROM) || 1;
    const beyond = across * WINDOW_SITS_FROM;
    const bounds = imageRange(row);
    return {
      low: Math.floor(Math.max(bounds.low, window_.low - beyond)),
      high: Math.ceil(Math.min(bounds.high, window_.high + beyond)),
    };
  }

  function theAxis(row: PanelRow): Span {
    return row.axis ?? restingAxis(row);
  }

  function heldAxis(row: PanelRow, next: Span): Span {
    const bounds = imageRange(row);
    const total = bounds.high - bounds.low;
    const width = Math.min(Math.max(next.high - next.low, total / 256), total);
    const low = Math.min(Math.max(next.low, bounds.low), bounds.high - width);
    return { low, high: low + width };
  }

  function setTheAxis(row: PanelRow, next: Span | null) {
    markOperatorAction(row);
    row.axis = next ? heldAxis(row, next) : null;
    remember(row);
    refreshControls();
  }

  const sayMeasurement = (state: string, message = "") => {
    measurementNotice.dataset.measurementState = state;
    measurementNotice.textContent = message;
    measurementNotice.style.display = message ? "block" : "none";
    measurementNotice.style.color = state === "failed" ? "#a51d2d" : INK.textMuted;
  };

  const cancelMeasurement = () => {
    measurementGeneration += 1;
    measurementController?.abort();
    measurementController = null;
    if (measurementTimer) clearTimeout(measurementTimer);
    measurementTimer = null;
  };

  const markOperatorAction = (row: PanelRow) => {
    const key = viewerChannelKey(row);
    actionRevision.set(key, (actionRevision.get(key) ?? 0) + 1);
    cancelMeasurement();
    sayMeasurement("idle");
  };

  function drawTheHistogram() {
    while (plot.firstChild) plot.firstChild.remove();
    if (chosen === null) return;
    const row = rows[chosen];
    const window_ = windowOf(row);
    const counts = shape?.counts ?? [];
    plot.setAttribute("viewBox", `0 0 ${Math.max(counts.length, 1)} 24`);
    const axis = theAxis(row);
    const span = axis.high - axis.low || 1;
    const at = (value: number) =>
      Math.min(Math.max((value - axis.low) / span, 0), 1) * Math.max(counts.length, 1);
    const measured = shape;
    if (measured && counts.length) {
      const bins = measured.high - measured.low || 1;
      const brightnessOf = (index: number) => measured.low + ((index + 0.5) * bins) / counts.length;
      const peak = Math.max(...counts, 1);
      counts.forEach((count, index) => {
        const share = logScale ? Math.log1p(count) / Math.log1p(peak) : count / peak;
        const height = share * 22;
        const inside = brightnessOf(index) >= window_.low && brightnessOf(index) <= window_.high;
        const starts = at(measured.low + (index * bins) / counts.length);
        const ends = at(measured.low + ((index + 1) * bins) / counts.length);
        const barEl = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        barEl.setAttribute("x", String(starts));
        barEl.setAttribute("y", String(24 - height));
        barEl.setAttribute("width", String(Math.max(ends - starts, 0.0001)));
        barEl.setAttribute("height", String(height));
        barEl.setAttribute("fill", "currentColor");
        barEl.setAttribute("opacity", inside ? "1" : "0.25");
        plot.append(barEl);
      });
    }
    /* The edge bars are 0.8 of a bin wide, so they are only drawn against a
       real histogram — against an empty one bin they would fill the box. */
    if (!counts.length) return;
    for (const edge of [window_.low, window_.high]) {
      const x = at(edge);
      if (x <= 0 || x >= counts.length) continue;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      line.setAttribute("x", String(x));
      line.setAttribute("y", "0");
      line.setAttribute("width", "0.8");
      line.setAttribute("height", "24");
      line.setAttribute("fill", INK.accent);
      plot.append(line);
    }
  }

  function refreshControls() {
    if (chosen === null) return;
    const row = rows[chosen];
    plot.setAttribute("role", "img");
    plot.setAttribute("aria-label", `histogram ${row.name}`);
    minRow.slider.setAttribute("aria-label", `min ${row.name}`);
    maxRow.slider.setAttribute("aria-label", `max ${row.name}`);
    opacityRow.slider.setAttribute("aria-label", `opacity ${row.name}`);
    gammaRow.slider.setAttribute("aria-label", `gamma ${row.name}`);
    saturateBox.setAttribute("aria-label", `saturate ${row.name}`);
    autoButton.setAttribute("aria-label", `auto contrast ${row.name}`);
    logButton.setAttribute("aria-label", logScale ? "plain counts" : "logarithmic counts");
    axisLow.setAttribute("aria-label", `axis from ${row.name}`);
    axisHigh.setAttribute("aria-label", `axis to ${row.name}`);
    minRow.box.setAttribute("aria-label", `min value ${row.name}`);
    maxRow.box.setAttribute("aria-label", `max value ${row.name}`);
    opacityRow.box.setAttribute("aria-label", `opacity value ${row.name}`);
    const window_ = windowOf(row);
    const axis = theAxis(row);
    for (const { slider } of [minRow, maxRow]) {
      slider.min = String(Math.floor(axis.low));
      slider.max = String(Math.ceil(axis.high));
      slider.step = "1";
      slider.disabled = false;
    }
    minRow.slider.value = String(Math.floor(window_.low));
    maxRow.slider.value = String(Math.ceil(window_.high));
    const said: [HTMLInputElement, number | string][] = [
      [axisLow, Math.round(axis.low)],
      [axisHigh, Math.round(axis.high)],
      [minRow.box, Math.floor(window_.low)],
      [maxRow.box, Math.ceil(window_.high)],
      [opacityRow.box, `${Math.round(row.weight * 100)}%`],
    ];
    for (const [input, value] of said) {
      input.disabled = false;
      if (document.activeElement !== input) input.value = String(value);
    }
    opacityRow.slider.disabled = false;
    opacityRow.slider.value = String(row.weight);
    gammaRow.slider.disabled = false;
    gammaRow.box.disabled = false;
    gammaRow.slider.value = String(row.gamma ?? 1);
    gammaRow.box.value = (row.gamma ?? 1).toFixed(2);
    if (document.activeElement !== saturateBox) saturateBox.value = `${row.saturate ?? 1}%`;
    for (const { slider } of [minRow, maxRow, opacityRow]) slider.refill();
    drawTheHistogram();
  }

  function takeTheWindow(next: Span, { operator = true, reframe = false } = {}) {
    if (chosen === null) return;
    const row = rows[chosen];
    if (operator) {
      if (!row.axis) row.axis = theAxis(row);
      markOperatorAction(row);
    }
    const bounds = imageRange(row);
    const low = Math.min(
      Math.max(next.low, bounds.low),
      Math.min(next.high, bounds.high) - 1,
    );
    row.window = {
      low,
      high: Math.max(Math.min(next.high, bounds.high), low + 1),
    };
    if (reframe) row.axis = null;
    remember(row);
    viewer.setChannel(chosen, { window: row.window });
    refreshControls();
    displayChangedSoon();
  }

  /* The sliders stand disabled until a row is chosen. */
  minRow.slider.addEventListener("input", () => takeTheWindow({
    low: Number(minRow.slider.value), high: windowOf(rows[chosen!]).high,
  }));
  maxRow.slider.addEventListener("input", () => takeTheWindow({
    low: windowOf(rows[chosen!]).low, high: Number(maxRow.slider.value),
  }));
  opacityRow.slider.addEventListener("input", () => {
    if (chosen === null) return;
    const row = rows[chosen];
    row.weight = Number(opacityRow.slider.value);
    remember(row);
    viewer.setChannel(chosen, { weight: row.weight });
    opacityRow.box.value = `${Math.round(row.weight * 100)}%`;
  });
  const takeTheGamma = (index: number, gamma: number) => {
    const row = rows[index];
    if (!row) return;
    row.gamma = Math.max(0.1, Math.min(4, gamma));
    remember(row);
    viewer.setChannel(index, { gamma: row.gamma });
    if (index === chosen) {
      gammaRow.slider.value = String(row.gamma);
      gammaRow.box.value = row.gamma.toFixed(2);
    }
    displayChangedSoon();
  };
  gammaRow.slider.addEventListener("input", () => {
    if (chosen !== null) takeTheGamma(chosen, Number(gammaRow.slider.value));
  });
  gammaRow.box.addEventListener("change", () => {
    const value = Number(gammaRow.box.value);
    if (chosen !== null && Number.isFinite(value) && value > 0) takeTheGamma(chosen, value);
    else refreshControls();
  });
  const takeTheSaturation = (index: number, percent: number) => {
    const row = rows[index];
    if (!row) return;
    row.saturate = Math.max(0.01, Math.min(20, percent));
    remember(row);
    if (index === chosen) saturateBox.value = `${row.saturate}%`;
  };
  saturateBox.addEventListener("change", () => {
    const value = Number(saturateBox.value.replace("%", ""));
    if (chosen !== null && Number.isFinite(value)) takeTheSaturation(chosen, value);
    else refreshControls();
  });

  const commitOnLeaving = (input: HTMLInputElement, take: (value: number) => void) => {
    const commit = () => {
      const value = Number(input.value.replace("%", ""));
      if (Number.isFinite(value)) take(value);
      refreshControls();
    };
    input.addEventListener("focus", () => input.select());
    input.addEventListener("blur", commit);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") input.blur();
      if (event.key === "Escape") {
        refreshControls();
        input.blur();
      }
    });
  };
  commitOnLeaving(axisLow, (value) => {
    if (chosen === null) return;
    const row = rows[chosen];
    const axis = theAxis(row);
    setTheAxis(row, { low: Math.min(value, axis.high - 1), high: axis.high });
  });
  commitOnLeaving(axisHigh, (value) => {
    if (chosen === null) return;
    const row = rows[chosen];
    const axis = theAxis(row);
    setTheAxis(row, { low: axis.low, high: Math.max(value, axis.low + 1) });
  });
  commitOnLeaving(minRow.box, (value) => {
    if (chosen === null) return;
    takeTheWindow({ low: value, high: windowOf(rows[chosen]).high });
  });
  commitOnLeaving(maxRow.box, (value) => {
    if (chosen === null) return;
    takeTheWindow({ low: windowOf(rows[chosen]).low, high: value });
  });
  commitOnLeaving(opacityRow.box, (value) => {
    if (chosen === null) return;
    const row = rows[chosen];
    row.weight = Math.min(1, Math.max(0, value / 100));
    remember(row);
    viewer.setChannel(chosen, { weight: row.weight });
  });

  /**
   * A window for every channel that has none yet, measured off the picture
   * the way Auto measures the chosen one. Without it a channel opened on
   * its full data range drew next to black, and a three-colour acquisition
   * showed on the canvas as whichever one channel had been measured.
   * Sequential, so the viewer's server answers one at a time; a row the
   * operator has since windowed by hand is left alone.
   */
  let windowingEveryChannel = false;
  let disposed = false;
  async function windowEveryChannel() {
    if (windowingEveryChannel) return;
    windowingEveryChannel = true;
    try {
      for (const [index, row] of rows.entries()) {
        if (row.window || !row.source) continue;
        const result = await measureViewerRow(row, {
          box: viewer.measurementBox?.(index) ?? [[0, 0], [1, 1]],
        });
        if (disposed) return;
        if (!result?.ok || !result.answer?.window || row.window) continue;
        const { low, high } = result.answer.window;
        if (!Number.isFinite(low) || !Number.isFinite(high)) continue;
        row.histogram = result.answer.histogram ?? row.histogram;
        row.window = { low, high: Math.max(high, low + 1) };
        remember(row);
        viewer.setChannel(index, { window: row.window });
        if (chosen === index) {
          shape = row.histogram;
          refreshControls();
        }
      }
    } finally {
      windowingEveryChannel = false;
    }
  }

  async function requestMeasurement(index: number, { auto = false, debounce = 0 } = {}): Promise<Measurement | null> {
    cancelMeasurement();
    const generation = measurementGeneration;
    const row = rows[index];
    const key = viewerChannelKey(row);
    const revision = actionRevision.get(key) ?? 0;
    const controller = new AbortController();
    measurementController = controller;
    sayMeasurement("measuring", "Measuring with Smart Viewer…");
    if (debounce) {
      await new Promise<void>((resolve) => {
        measurementTimer = setTimeout(resolve, debounce);
        controller.signal.addEventListener("abort", () => resolve(), { once: true });
      });
      measurementTimer = null;
    }
    if (controller.signal.aborted || generation !== measurementGeneration) return null;
    const result = await measureViewerRow(row, {
      signal: controller.signal,
      box: viewer.measurementBox?.(index) ?? [[0, 0], [1, 1]],
    });
    if (controller.signal.aborted
        || generation !== measurementGeneration
        || chosen !== index
        || (actionRevision.get(key) ?? 0) !== revision) {
      return null;
    }
    measurementController = null;
    if (!result.ok) {
      if (!result.aborted) sayMeasurement("failed", result.message);
      return result;
    }
    shape = result.answer.histogram;
    row.histogram = shape;
    if (auto) {
      /* At the saturation the operator chose: the viewer's own window sets
         one percent aside, and any other share is read off its histogram. */
      const asked = (row.saturate ?? 1) === 1
        ? result.answer.window
        : (windowFromHistogram(shape, row.saturate) ?? result.answer.window);
      takeTheWindow(asked, { operator: false, reframe: true });
    } else if (!row.window && result.answer.window) {
      takeTheWindow(result.answer.window, { operator: false, reframe: true });
    } else {
      remember(row);
      refreshControls();
      /* The histogram is news too: whoever draws this channel elsewhere,
         the box under the canvas row for one, should hear of it. */
      displayChangedSoon();
    }
    sayMeasurement("ready", "Smart Viewer measurement ready.");
    return result;
  }

  logButton.addEventListener("click", () => {
    logScale = !logScale;
    if (chosen !== null) {
      rows[chosen].log = logScale;
      remember(rows[chosen]);
    }
    logButton.style.background = logScale ? INK.accent : INK.ghost;
    logButton.style.color = logScale ? "#fff" : INK.textPrimary;
    logButton.setAttribute("aria-pressed", logScale ? "true" : "false");
    refreshControls();
  });
  autoButton.addEventListener("click", () => {
    if (chosen !== null) requestMeasurement(chosen, { auto: true });
  });

  /* Window edges drag; the remaining histogram surface pans its brightness
     axis. The two actions share the Viewer 0.2 six-pixel edge hit zone. */
  let held: { bar: "low" | "high" } | { panFrom: number; axisWas: Span } | null = null;
  /* Asked only while a row is chosen: every handle below returns first when none is. */
  const valueUnder = (event: MouseEvent) => {
    const face = plot.getBoundingClientRect();
    const axis = theAxis(rows[chosen!]);
    const share = Math.min(1, Math.max(0, (event.clientX - face.left) / face.width));
    return axis.low + share * (axis.high - axis.low);
  };
  const barUnder = (event: MouseEvent): "low" | "high" | null => {
    if (!shape || chosen === null) return null;
    const window_ = windowOf(rows[chosen]);
    const face = plot.getBoundingClientRect();
    const axis = theAxis(rows[chosen]);
    const grace = (6 / face.width) * (axis.high - axis.low);
    const value = valueUnder(event);
    if (Math.abs(value - window_.low) <= grace) return "low";
    if (Math.abs(value - window_.high) <= grace) return "high";
    return null;
  };
  const showValueUnder = (event: MouseEvent) => {
    if (!shape?.counts?.length) {
      histogramValue.textContent = `value ${Math.round(valueUnder(event))}`;
      return;
    }
    const value = valueUnder(event);
    const share = (value - shape.low) / ((shape.high - shape.low) || 1);
    const at = Math.min(shape.counts.length - 1, Math.max(0, Math.floor(share * shape.counts.length)));
    const count = value >= shape.low && value <= shape.high ? shape.counts[at] : 0;
    histogramValue.textContent = `value ${Math.round(value)} · ${count} pixels`;
  };
  plot.addEventListener("pointerdown", (event) => {
    if (chosen === null || !shape) return;
    const axis = theAxis(rows[chosen]);
    const bar = barUnder(event);
    held = bar
      ? { bar }
      : { panFrom: event.clientX, axisWas: { low: axis.low, high: axis.high } };
    plot.setPointerCapture(event.pointerId);
    plot.style.cursor = bar ? "ew-resize" : "grabbing";
  });
  plot.addEventListener("pointermove", (event) => {
    if (chosen === null) return;
    showValueUnder(event);
    const window_ = windowOf(rows[chosen]);
    if (!held) {
      plot.style.cursor = barUnder(event) ? "ew-resize" : "grab";
      return;
    }
    if ("bar" in held) {
      const value = valueUnder(event);
      takeTheWindow(held.bar === "low"
        ? { low: Math.min(value, window_.high - 1), high: window_.high }
        : { low: window_.low, high: Math.max(value, window_.low + 1) });
      return;
    }
    const face = plot.getBoundingClientRect();
    const width = held.axisWas.high - held.axisWas.low;
    const moved = ((held.panFrom - event.clientX) / face.width) * width;
    setTheAxis(rows[chosen], {
      low: held.axisWas.low + moved,
      high: held.axisWas.high + moved,
    });
  });
  for (const done of ["pointerup", "pointercancel"]) {
    plot.addEventListener(done, () => {
      held = null;
      plot.style.cursor = "grab";
    });
  }
  plot.addEventListener("pointerleave", () => {
    if (!held) histogramValue.textContent = "";
  });
  plot.addEventListener("dblclick", () => {
    if (chosen !== null) setTheAxis(rows[chosen], null);
  });
  plot.addEventListener("wheel", (event) => {
    if (chosen === null || !shape) return;
    event.preventDefault();
    const row = rows[chosen];
    const axis = theAxis(row);
    const face = plot.getBoundingClientRect();
    const fraction = Math.min(1, Math.max(0, (event.clientX - face.left) / face.width));
    const anchor = axis.low + fraction * (axis.high - axis.low);
    const factor = Math.exp(event.deltaY * 0.002);
    setTheAxis(row, {
      low: anchor - (anchor - axis.low) * factor,
      high: anchor + (axis.high - anchor) * factor,
    });
  }, { passive: false });

  /* ---- the data card: groups, eyes, swatches, names ---- */
  const { card: dataCard, body: data } = aCard("acquired images");
  const engineNotice = el("div", [
    "display:none", "margin:0 12px 8px", "padding:5px 7px",
    `border:1px solid ${INK.controlBorder}`, "border-radius:4px",
    `background:${INK.inputBg}`, `color:${INK.textMuted}`,
    `font:${font(400, 10)}`, "line-height:1.35",
  ].join(";"));
  engineNotice.setAttribute("role", "status");
  engineNotice.dataset.engineState = "agrees";
  data.append(engineNotice);

  let chooserOpen: HTMLElement | null = null;
  const closeChooser = () => { chooserOpen?.remove(); chooserOpen = null; };
  const closeChooserOnOutsidePress = (event: Event) => {
    if (chooserOpen?.contains(event.target as Node | null)) return;
    closeChooser();
  };
  document.addEventListener("pointerdown", closeChooserOnOutsidePress, true);

  const swatches = rows.map(() => new Set<HTMLElement>());
  const channelEyes = rows.map(() => new Set<HTMLElement>());

  const paintSwatches = (index: number) => {
    for (const swatch of swatches[index] ?? []) {
      swatch.style.background = rows[index].color ?? cssOf(null);
    }
  };

  const paintChannelEyes = (index: number) => {
    const row = rows[index];
    for (const eye of channelEyes[index] ?? []) {
      eye.replaceChildren(anEye(row.visible));
      eye.style.opacity = row.visible ? "1" : "0.4";
      eye.title = row.visible ? "Hide this channel" : "Show this channel";
      eye.setAttribute("aria-pressed", row.visible ? "true" : "false");
    }
  };

  const setChannelVisible = (index: number, visible: boolean) => {
    const row = rows[index];
    row.visible = visible;
    remember(row);
    paintChannelEyes(index);
    if (visibilityReady) {
      viewer.setChannel(index, {
        visible: groupShown.get(row.acquisition) !== false && row.visible,
      });
    }
    displayChangedSoon();
  };

  function aChannelEye(index: number, { chosenControl = false } = {}) {
    const row = rows[index];
    const eye = el("button",
      `background:none;border:none;color:${INK.textPrimary};cursor:pointer;padding:0;`);
    eye.type = "button";
    eye.setAttribute("aria-label", chosenControl
      ? "toggle the chosen channel"
      : `toggle ${row.name}`);
    eye.addEventListener("click", (press) => {
      press.stopPropagation();
      setChannelVisible(index, !row.visible);
    });
    channelEyes[index].add(eye);
    paintChannelEyes(index);
    return eye;
  }

  function aSwatch(index: number, row: PanelRow) {
    const swatch = el("button", [
      "width:13px", "height:13px", "border-radius:3px",
      `border:1px solid ${INK.controlBorder}`, "display:inline-block",
      "flex-shrink:0", "padding:0", "cursor:pointer", "appearance:none",
      `background:${row.color ?? cssOf(null)}`,
    ].join(";"));
    swatch.type = "button";
    swatch.setAttribute("aria-label", `colour ${row.name}`);
    swatch.title = "Choose this channel's colour";
    swatches[index].add(swatch);
    swatch.addEventListener("pointerdown", (press) => press.stopPropagation());
    swatch.addEventListener("click", (press) => {
      press.stopPropagation();
      closeChooser();
      const face = swatch.getBoundingClientRect();
      const list = el("div", [
        "position:fixed", `left:${face.right + 6}px`, `top:${face.top - 4}px`,
        "z-index:40", "min-width:116px", `background:${INK.cardBg}`,
        `border:1px solid ${INK.panelBorder}`, "border-radius:6px",
        "padding:4px", "box-shadow:0 2px 10px rgba(25,35,50,0.22)",
        "display:flex", "flex-direction:column", "gap:2px",
      ].join(";"));
      const custom = el("label", [
        "position:relative", "display:flex", "align-items:center", "gap:7px",
        "cursor:pointer", "padding:3px 6px", "border-radius:3px",
        `font:${font(400, 12)}`, `color:${INK.textPrimary}`,
      ].join(";"));
      custom.append(
        el("span", `display:inline-block;width:22px;height:11px;border-radius:2px;border:1px solid ${INK.controlBorder};background:transparent;`),
        el("span", "", "custom"),
      );
      const picker = el("input", "position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer;");
      picker.type = "color";
      picker.value = hexOf(row.colour);
      picker.setAttribute("aria-label", `choose a colour for ${row.name}`);
      picker.addEventListener("input", () => {
        row.colour = rgbOf(picker.value);
        row.color = cssOf(row.colour);
        /* A colour chosen by hand is a colour: the row leaves grey. */
        row.grey = false;
        remember(row);
        paintSwatches(index);
        viewer.setChannel(index, { colour: row.colour });
        displayChangedSoon();
        closeChooser();
      });
      custom.append(picker);
      list.append(custom);
      for (const choice of PALETTE) {
        const entry = el("button",
          `display:flex;align-items:center;gap:7px;border:none;background:none;cursor:pointer;padding:3px 6px;border-radius:3px;font:${font(400, 12)};color:${INK.textPrimary};text-align:left;`);
        entry.type = "button";
        entry.setAttribute("aria-label", `${choice.name} for ${row.name}`);
        entry.append(
          el("span", `display:inline-block;width:22px;height:11px;border-radius:2px;border:1px solid ${INK.controlBorder};background:${cssOf(choice.rgb)};`),
          el("span", "", choice.name),
        );
        entry.addEventListener("pointerdown", (press) => press.stopPropagation());
        entry.addEventListener("click", () => {
          const rgb = choice.rgb ?? [0.847, 0.871, 0.902];
          row.color = cssOf(choice.rgb);
          row.colour = rgb;
          /* A colour chosen by hand is a colour: the row leaves grey. */
          row.grey = false;
          remember(row);
          paintSwatches(index);
          viewer.setChannel(index, { colour: rgb });
          displayChangedSoon();
          closeChooser();
        });
        list.append(entry);
      }
      document.body.append(list);
      chooserOpen = list;
    });
    return swatch;
  }

  const rowLines: HTMLElement[] = [];
  const groupShown = new Map<string, boolean>();
  /* Each acquisition's eye, by name, for the page to press: walking to the
     overview scan puts the focus stack away. */
  const groupSwitches = new Map<string, (on: boolean) => void>();
  const greySwitches = new Map<string, (grey: boolean) => void>();
  /* The one grey channel each acquisition collapses to while grey is on:
     its window as shares a and b of every member's colour window, its
     opacity as a factor s on every member's colour weight. */
  const composites = new Map<string, Composite>();
  const compositeMembers = new Map<string, { one: PanelRow; at: number }[]>();
  /* Whether each acquisition is drawn in grey now, beside the switch that
     changes it, so the canvas's own Grayscale press can say which way it
     will go. */
  const greyStates = new Map<string, () => { grey: boolean; visible: boolean }>();
  let heading: string | null = null;
  let groupBox: HTMLElement | null = null;
  rows.forEach((row, index) => {
    if (row.acquisition !== heading) {
      heading = row.acquisition;
      const groupName = heading;
      const group = el("div", "");
      const head = el("div", "display:flex;align-items:center;gap:6px;padding:5px 12px 3px;");
      const disclosure = el("button", [
        "background:none", "border:none", `color:${INK.textMuted}`,
        "cursor:pointer", "font-size:10px", "padding:0", "width:10px",
      ].join(";"));
      disclosure.type = "button";
      const groupEye = el("button",
        `background:none;border:none;color:${INK.textPrimary};cursor:pointer;padding:0;`);
      groupEye.type = "button";
      const initiallyOn = rememberedGroups.get(groupName) ?? true;
      groupShown.set(groupName, initiallyOn);
      groupEye.dataset.on = initiallyOn ? "1" : "0";
      groupEye.dataset.acquisition = groupName;
      groupEye.setAttribute("aria-label", `toggle group ${groupName}`);
      groupEye.setAttribute("aria-pressed", initiallyOn ? "true" : "false");
      groupEye.append(anEye(initiallyOn));
      groupEye.style.opacity = initiallyOn ? "1" : "0.4";
      groupEye.title = initiallyOn ? "Hide this acquisition" : "Show this acquisition";
      const members = rows.map((one, at) => ({ one, at }))
        .filter(({ one }) => one.acquisition === groupName);
      const showTheGroup = (on: boolean) => {
        groupEye.dataset.on = on ? "1" : "0";
        groupShown.set(groupName, on);
        rememberedGroups.set(groupName, on);
        groupEye.replaceChildren(anEye(on));
        groupEye.setAttribute("aria-pressed", on ? "true" : "false");
        groupEye.style.opacity = on ? "1" : "0.4";
        groupEye.title = on ? "Hide this acquisition" : "Show this acquisition";
        if (visibilityReady) {
          for (const { one, at } of members) {
            viewer.setChannel(at, { visible: on && one.visible });
          }
        }
        displayChangedSoon();
      };
      groupEye.addEventListener("click", () => showTheGroup(groupEye.dataset.on !== "1"));
      groupSwitches.set(groupName, showTheGroup);
      /* Colour or grey for the whole acquisition: grey draws every channel
         in its own colour's luminance, so the sample reads as one picture
         and as bright as its colours desaturated; colour gives each channel
         its own back. The rows' colours change for real -- the copies drawn
         from them and the reconciliation with the engine follow -- and the
         colours they had wait on the rows for the way back. */
      const greyPick = el("button", [
        "background:none", `border:1px solid ${INK.controlBorder}`, "border-radius:3px",
        `color:${INK.textMuted}`, "cursor:pointer", `font:${font(500, 10)}`,
        "padding:1px 5px", "letter-spacing:.02em",
      ].join(";"));
      greyPick.type = "button";
      greyPick.dataset.acquisitionGrey = groupName;
      const sayTheColours = () => {
        const grey = members.every(({ one }) => one.grey);
        greyPick.textContent = grey ? "grey" : "colour";
        greyPick.setAttribute("aria-pressed", grey ? "true" : "false");
        greyPick.title = grey ? "Give the channels their colours back" : "Draw this acquisition in grey";
      };
      /* Grey collapses the acquisition to one channel: every member is
         drawn in grey and the engine adds them, which is the weighted sum
         of the channels as they stand in colour. So the colour
         configuration -- each member's window and weight -- is frozen when
         grey goes on, and one control over the sum moves all of them in
         proportion: a window as a share of each member's own, an opacity
         as a factor on each member's weight. Colour restores them all. */
      const drawInGrey = (grey: boolean) => {
        for (const { one, at } of members) {
          if (grey && !one.grey) {
            one.colourInColour = one.colour;
            one.colorInColour = one.color;
            one.colourWindow = one.window ? { ...one.window } : null;
            one.colourWeight = one.weight;
            const share = Array.isArray(one.colour) ? luminanceOf(one.colour) : 1;
            one.colour = [share, share, share];
            one.color = cssOf(one.colour);
          } else if (!grey && one.grey) {
            one.colour = one.colourInColour ?? one.colour;
            one.color = one.colorInColour ?? one.color;
            if (one.colourWindow) one.window = { ...one.colourWindow };
            if (one.colourWeight !== undefined && Number.isFinite(one.colourWeight)) one.weight = one.colourWeight;
            viewer.setChannel(at, { window: one.window ?? undefined, weight: one.weight });
          }
          one.grey = grey;
          remember(one);
          paintSwatches(at);
          viewer.setChannel(at, { colour: one.colour ?? undefined });
        }
        if (grey) composites.set(groupName, { a: 0, b: 1, s: 1, log: false });
        else composites.delete(groupName);
        if (chosen !== null && members.some(({ at }) => at === chosen)) refreshControls();
        sayTheColours();
        displayChangedSoon();
      };
      compositeMembers.set(groupName, members);
      greyPick.addEventListener("click", () => drawInGrey(!members.every(({ one }) => one.grey)));
      greySwitches.set(groupName, drawInGrey);
      /* Judged on what is on show: an acquisition hidden by its eye does
         not decide whether the picture looks grey. */
      greyStates.set(groupName, () => ({
        grey: members.every(({ one }) => one.grey),
        visible: members.some(({ one }) => one.visible !== false),
      }));
      sayTheColours();
      head.append(disclosure, groupEye, el("span",
        `flex:1;font:${font(600, 12)};letter-spacing:.02em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;`,
        groupName), greyPick);
      const thisGroupBox = el("div", `padding-left:8px;border-left:2px solid ${INK.subtleBorder};margin-left:16px;`);
      groupBox = thisGroupBox;
      const showMembers = (show: boolean) => {
        panelState.collapsed.set(groupName, !show);
        thisGroupBox.style.display = show ? "block" : "none";
        disclosure.textContent = show ? "▾" : "▸";
        disclosure.setAttribute("aria-label", `${show ? "collapse" : "expand"} ${groupName}`);
        disclosure.setAttribute("aria-expanded", show ? "true" : "false");
      };
      disclosure.addEventListener("click", () => {
        showMembers(thisGroupBox.style.display === "none");
      });
      group.append(head, thisGroupBox);
      /* Listed top-down as they are drawn: the acquisition over the others
         stands first, the overview under them all stands last. */
      data.prepend(group);
      showMembers(panelState.collapsed.get(groupName) !== true);
    }
    const line = el("div",
      "position:relative;padding:1px 0;cursor:pointer;margin-right:12px;border-radius:3px;");
    line.dataset.channelRow = row.name;
    const inner = el("div", "display:flex;align-items:center;gap:8px;padding:5px 12px;");
    inner.append(aChannelEye(index), aSwatch(index, row), el("span",
      "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;", row.name));
    line.append(inner);
    line.addEventListener("click", () => chooseRow(index));
    rowLines.push(line);
    groupBox!.append(line);
  });
  const observedRows = () => viewer.layersForMeasurement?.() ?? null;
  const effectiveVisibility = (row: PanelRow) =>
    groupShown.get(row.acquisition) !== false && row.visible;
  const sameWindow = (a: Span | null, b: Span | null | undefined) => !a || (!!b
    && Math.abs(a.low - b.low) < 0.01
    && Math.abs(a.high - b.high) < 0.01);

  const applyRequested = (index: number) => {
    const row = rows[index];
    viewer.setChannel(index, {
      visible: effectiveVisibility(row),
      colour: row.colour ?? undefined,
      window: row.window ?? undefined,
      weight: row.weight,
    });
  };

  const readyEngineRows = (): EngineRow[] | null => {
    const standing = observedRows();
    if (standing === null) return [];
    const ready = standing.length === rows.length
      && standing.every((engineRow, index) =>
        (engineRow.sources?.length ?? 0) === rows[index].sources.length
        && (engineRow.sources ?? []).every((source) => source.error
          || (Array.isArray(source.lower) && Array.isArray(source.upper))));
    return ready ? standing : null;
  };

  /**
   * Read the engine without adopting its values. A mismatch is named, then
   * Smart Operator's requested state is reapplied through the adapter.
   */
  const refreshObserved = () => {
    const standing = readyEngineRows();
    if (standing === null) return false;
    if (!visibilityReady) {
      visibilityReady = true;
      rows.forEach((_row, index) => applyRequested(index));
      windowEveryChannel();
      return true;
    }
    if (!standing.length && !viewer.layersForMeasurement) return true;
    const mismatches: unknown[] = [];
    standing.forEach((seen, index) => {
      const row = rows[index];
      const wanted = {
        visible: effectiveVisibility(row),
        window: row.window,
        weight: row.weight,
      };
      if (seen.visible !== wanted.visible
          || (seen.weight !== undefined && Number.isFinite(seen.weight) && Math.abs(seen.weight - wanted.weight) > 0.001)
          || !sameWindow(wanted.window, seen.window)) {
        mismatches.push({
          key: viewerChannelKey(row),
          requested: wanted,
          observed: { visible: seen.visible, window: seen.window, weight: seen.weight },
        });
        applyRequested(index);
      }
    });
    if (mismatches.length) {
      panelState.lastMismatch = { at: new Date().toISOString(), rows: mismatches };
      engineNotice.dataset.engineState = "reconciling";
      engineNotice.style.display = "block";
      engineNotice.textContent = `Viewer state differed for ${mismatches.length} channel${mismatches.length === 1 ? "" : "s"}; restoring the Operator settings.`;
    } else {
      engineNotice.dataset.engineState = "agrees";
      engineNotice.style.display = "none";
      engineNotice.textContent = "";
    }
    return true;
  };

  refreshObserved();
  observationTimer = setInterval(refreshObserved, 100);

  const panelSnapshot = (): PanelSnapshot => {
    const standing = observedRows() ?? [];
    return {
      selectedKey: panelState.selectedKey,
      lastMismatch: panelState.lastMismatch,
      measurement: {
        state: measurementNotice.dataset.measurementState,
        message: measurementNotice.textContent,
      },
      acquisitions: Object.fromEntries(
        [...groupShown].map(([name, visible]) => [name, {
          visible,
          collapsed: panelState.collapsed.get(name) === true,
        }]),
      ),
      channels: rows.map((row, index) => ({
        key: viewerChannelKey(row),
        acquisition: row.acquisition,
        name: row.name,
        requested: {
          visible: row.visible,
          effectiveVisible: effectiveVisibility(row),
          color: row.color,
          colour: row.colour,
          opacity: row.weight,
          window: row.window,
          log: row.log ?? false,
          axis: row.axis ?? null,
        },
        observed: standing[index] ? {
          visible: standing[index].visible,
          opacity: standing[index].weight,
          window: standing[index].window,
          sources: standing[index].sources,
        } : null,
      })),
    };
  };

  const sourcesChanged = async (nextAcquisitions: Acquisition[]) => {
    const next = await viewerRowsFor(nextAcquisitions);
    if (next.length !== rows.length
        || next.some((row, index) => viewerChannelKey(row) !== viewerChannelKey(rows[index]))) {
      return false;
    }
    next.forEach((fresh, index) => {
      rows[index].source = fresh.source;
      rows[index].sources = fresh.sources;
      rows[index].range = fresh.range ?? rows[index].range;
      rows[index].histogram = fresh.histogram ?? rows[index].histogram;
      remember(rows[index]);
    });
    if (chosen !== null) {
      shape = rows[chosen].histogram ?? shape;
      refreshControls();
    }
    refreshObserved();
    return true;
  };

  function chooseRow(index: number) {
    cancelMeasurement();
    chosen = index;
    const row = rows[index];
    panelState.selectedKey = viewerChannelKey(row);
    logScale = row.log ?? false;
    logButton.style.background = logScale ? INK.accent : INK.ghost;
    logButton.style.color = logScale ? "#fff" : INK.textPrimary;
    logButton.setAttribute("aria-pressed", logScale ? "true" : "false");
    rowLines.forEach((line, at) => {
      line.style.background = at === index ? INK.chosenGround : "";
      if (at === index) line.setAttribute("aria-current", "true");
      else line.removeAttribute("aria-current");
    });
    chosenGroup.textContent = row.acquisition;
    chosenLine.replaceChildren(
      aChannelEye(index, { chosenControl: true }),
      aSwatch(index, row),
      el("span", "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;", row.name),
    );
    shape = row.histogram ?? null;
    sayMeasurement("idle");
    refreshControls();
    requestMeasurement(index, { debounce: 120 });
  }

  /* ---- the picture as a whole ----
     The eyes on the acquisitions switch the picture on and off. The way
     through a stack, and along a timelapse, is not here: those two sliders
     lie under the picture itself, across its whole width, where the
     canvas shows them only while there is a plane or a moment to choose. */
  const { card: wholeCard, body: whole } = aCard("picture");
  wholeCard.hidden = !whole.childElementCount;

  bar.append(dataCard, settingsCard, wholeCard);
  if (into) {
    fold.hidden = true;
    bar.style.width = "100%";
    into.append(panel);
  } else if (plotHost) plotHost.after(panel);
  else (body ?? near)?.append(panel);
  /* Left where a test can reach both requested and observed state, the way
     the picture itself is. These methods do not expose Neuroglancer. */
  panel.snapshot = panelSnapshot;
  panel.sourcesChanged = sourcesChanged;
  panel.showAcquisition = (name, on) => {
    rememberedGroups.set(name, on);
    groupSwitches.get(name)?.(on);
  };
  panel.drawInGrey = (name, grey) => greySwitches.get(name)?.(grey);
  /* What the canvas's own row needs of the panel: the acquisitions and their
     channels as they stand, the three things a chip does -- show or hide a
     channel, choose it, show or hide its acquisition -- and a way to hear
     that something changed so the row can redraw. */
  panel.acquisitions = () => [...groupShown.keys()].map((name) => ({
    name, shown: groupShown.get(name) !== false,
    channels: rows.filter((row) => row.acquisition === name).length,
  }));
  panel.channelsOf = (name) => rows
    .map((row, index) => ({ row, index }))
    .filter(({ row }) => row.acquisition === name)
    .map(({ row, index }) => ({
      index, name: row.name, color: row.color ?? cssOf(null), visible: row.visible,
      chosen: chosen === index,
    }));
  panel.setChannelVisible = (index, on) => { if (rows[index]) setChannelVisible(index, on); };
  panel.chooseRow = (index) => { if (rows[index]) chooseRow(index); };
  panel.acquisitionShown = (name) => groupShown.get(name) !== false;
  panel.onChanged = (fn) => { changedHooks.add(fn); return () => changedHooks.delete(fn); };
  /* The chosen channel's box -- its histogram, window and opacity -- can
     stand under the canvas's own row for a while: lent to a card there and
     taken back into the column when the card closes. One box, one truth. */
  /* The grey channel: what it stands at, its histogram over the sum, and
     the three things that move it -- the window, the opacity, Auto. */
  const applyComposite = (name: string) => {
    const state = composites.get(name);
    const members = compositeMembers.get(name);
    if (!state || !members) return;
    for (const { one, at } of members) {
      const base = one.colourWindow ?? windowOf(one);
      const span = base.high - base.low || 1;
      const low = base.low + state.a * span;
      one.window = { low, high: Math.max(base.low + state.b * span, low + 1) };
      one.weight = Math.min(1, Math.max(0, (one.colourWeight ?? 1) * state.s));
      remember(one);
      viewer.setChannel(at, { window: one.window, weight: one.weight });
      if (chosen === at) refreshControls();
    }
    displayChangedSoon();
  };
  panel.composite = (name) => {
    const state = composites.get(name);
    const members = compositeMembers.get(name);
    if (!state || !members) return null;
    /* One histogram over the sum: each member's counts laid along the
       share of its own colour window, each member weighed by its total so
       a bright channel and a faint one count alike. */
    const bins: number[] = new Array(64).fill(0);
    let measured = 0;
    for (const { one } of members) {
      const shape = one.histogram;
      if (!shape?.counts?.length) continue;
      measured += 1;
      const base = one.colourWindow ?? windowOf(one);
      const span = base.high - base.low || 1;
      const total = shape.counts.reduce((sum, c) => sum + c, 0) || 1;
      const width = (shape.high - shape.low) || 1;
      shape.counts.forEach((count, i) => {
        const brightness = shape.low + ((i + 0.5) * width) / shape.counts.length;
        const f = Math.min(1, Math.max(0, (brightness - base.low) / span));
        bins[Math.min(63, Math.floor(f * 64))] += count / total;
      });
    }
    return { ...state, counts: bins, measured, channels: members.length };
  };
  panel.setComposite = (name, next) => {
    const state = composites.get(name);
    if (!state) return;
    Object.assign(state, next);
    state.a = Math.min(Math.max(state.a, 0), 0.98);
    state.b = Math.max(Math.min(state.b, 1), state.a + 0.02);
    applyComposite(name);
  };
  panel.autoComposite = async (name) => {
    const members = compositeMembers.get(name);
    if (!members || !composites.get(name)) return;
    for (const { one, at } of members) {
      if (!one.source) continue;
      const result = await measureViewerRow(one, { box: viewer.measurementBox?.(at) ?? [[0, 0], [1, 1]] });
      if (!result.ok || !result.answer?.window) continue;
      const { low, high } = result.answer.window;
      one.histogram = result.answer.histogram ?? one.histogram;
      one.colourWindow = { low, high: Math.max(high, low + 1) };
    }
    if (!composites.get(name)) return;
    Object.assign(composites.get(name)!, { a: 0, b: 1 });
    applyComposite(name);
  };
  panel.acquisitionGrey = (name) => Boolean(greyStates.get(name)?.().grey);

  /* One colour channel, for the box under the canvas row: what it looks
     like now, a way to change it, and Auto. The same window, axis and
     opacity the column's own box acts on, so the two never disagree. */
  panel.channelBox = (index) => {
    const row = rows[index];
    if (!row) return null;
    const hist = row.histogram;
    return {
      name: row.name, color: row.color, hex: hexOf(row.colour), visible: row.visible !== false,
      counts: hist?.counts ?? [], range: hist ? { low: hist.low, high: hist.high } : null,
      window: { ...windowOf(row) }, axis: { ...theAxis(row) },
      weight: Number.isFinite(row.weight) ? row.weight : 1, log: Boolean(row.log),
      gamma: row.gamma !== undefined && Number.isFinite(row.gamma) ? row.gamma : 1,
      saturate: row.saturate !== undefined && Number.isFinite(row.saturate) ? row.saturate : 1,
      measured: Boolean(hist?.counts?.length),
    };
  };
  panel.channelAct = (index, next) => {
    const row = rows[index];
    if (!row) return;
    if (chosen !== index) chooseRow(index);
    if (next.window) takeTheWindow(next.window);
    if ("axis" in next) setTheAxis(row, next.axis ?? null);
    if (next.weight !== undefined && Number.isFinite(next.weight)) {
      row.weight = Math.max(0, Math.min(1, next.weight));
      remember(row);
      viewer.setChannel(index, { weight: row.weight });
      refreshControls();
      displayChangedSoon();
    }
    if (typeof next.log === "boolean" && next.log !== logScale) logButton.click();
    if (next.gamma !== undefined && Number.isFinite(next.gamma)) takeTheGamma(index, next.gamma);
    if (next.saturate !== undefined && Number.isFinite(next.saturate)) takeTheSaturation(index, next.saturate);
    if (next.colour) {
      /* A colour typed as `#rrggbb`, or the look's own three numbers. */
      row.colour = typeof next.colour === "string" ? rgbOf(next.colour) : next.colour;
      row.color = cssOf(row.colour);
      row.grey = false;
      remember(row);
      paintSwatches(index);
      viewer.setChannel(index, { colour: row.colour });
      displayChangedSoon();
    }
  };
  /* The grey acquisition is one channel to the operator, so its gamma is
     every member's, set together and read off the first. */
  panel.gammaOf = (name) => compositeMembers.get(name)?.[0]?.one?.gamma ?? 1;
  panel.setGammaOf = (name, gamma) => {
    for (const { at } of compositeMembers.get(name) ?? []) takeTheGamma(at, gamma);
  };
  /**
   * The one-press look for the acquisitions named: every channel measured,
   * its window set with the background under it and the brightest objects
   * inside it, a gamma that lifts the mid-tones without flattening the
   * peaks, and one colour per channel position, the same in every
   * acquisition. Nothing the operator set is asked about: the press is the
   * request, and every control can be moved again afterwards.
   */
  panel.makeItLook = async (names) => {
    const wanted = names?.length ? names : [...groupShown.keys()];
    for (const name of wanted) {
      const members = rows
        .map((row, index) => ({ row, index }))
        .filter(({ row }) => row.acquisition === name);
      const palette = LOOK_COLOURS;
      for (const [position, { row, index }] of members.entries()) {
        const result = await measureViewerRow(row, {
          box: viewer.measurementBox?.(index) ?? [[0, 0], [1, 1]],
        });
        const window_ = result.ok
          ? (windowForTheLook(result.answer.histogram) ?? result.answer.window)
          : null;
        if (result.ok) row.histogram = result.answer.histogram;
        panel.channelAct(index, {
          ...(window_ ? { window: window_ } : {}),
          gamma: 0.85,
          weight: 1,
          colour: palette[position % palette.length],
        });
        if (!row.visible) setChannelVisible(index, true);
      }
    }
    displayChangedSoon();
  };
  panel.autoChannel = async (index) => {
    if (!rows[index]) return;
    if (chosen !== index) chooseRow(index);
    await requestMeasurement(index, { auto: true });
    displayChangedSoon();
  };
  panel.lendSettingsCard = (into) => { into.append(settingsCard); };
  panel.reclaimSettingsCard = () => { if (settingsCard.parentElement !== bar) bar.insertBefore(settingsCard, wholeCard); };
  panel.requestedState = panelState;
  window.__viewerPanel = panel;
  if (rows.length) {
    const remembered = rows.findIndex(
      (row) => viewerChannelKey(row) === panelState.selectedKey,
    );
    chooseRow(remembered >= 0 ? remembered : 0);
  }
  return {
    element: panel,
    snapshot: panelSnapshot,
    sourcesChanged,
    /** Show or hide one acquisition, as its eye would. */
    showAcquisition: panel.showAcquisition,
    /** Draw one acquisition in grey, or in its colours, as its switch would. */
    drawInGrey(name, grey) { greySwitches.get(name)?.(grey); },
    destroy() {
      disposed = true;
      cancelMeasurement();
      if (observationTimer) clearInterval(observationTimer);
      if (changedTimer !== null) clearTimeout(changedTimer);
      closeChooser();
      document.removeEventListener("pointerdown", closeChooserOnOutsidePress, true);
      panel.remove();
      if (window.__viewerPanel === panel) window.__viewerPanel = null;
    },
  };
}
