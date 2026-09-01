/**
 * The viewer's own controls, ported from the ZMART viewer's sidebar.
 *
 * The structure, the dress and the behaviour follow the viewer's
 * `app/page/src/LayerPanel.jsx` (its `data` and `channel settings` cards) as
 * closely as a vanilla port can: the 264px bar with its 14px fold strip, the
 * card-on-panel grounds, the eye glyph, the swatch that opens a palette, the
 * 60px histogram with dimmed out-of-window bars and two accent edge lines the
 * hand can drag, the min/max sliders with typed value boxes, the brightness and
 * contrast pair beside them, and opacity per channel. Where this file and that
 * one disagree, that one is right.
 *
 * Two habits run through the whole file and are worth knowing before reading
 * any of it. **Nothing here is remembered that the viewer can be asked.** Every
 * control is redrawn from what the picture says it is really doing, because a
 * control that keeps its own account of the picture will one day be
 * photographed saying the opposite of what an operator can see — which is
 * exactly how an eye stayed open on a channel nobody was drawing, and how the
 * depth slider went on showing a plane the picture had left. And **anything
 * that fails says so on the screen**, because a panel that swallows a failure
 * looks precisely like a panel that is still working on it.
 *
 * The rows are enumerated exactly the way the engine enumerates its own —
 * one per channel, acquisitions in order — so the flat index handed to
 * `viewer.setChannel(index, …)` names the same row on both sides.
 */

import {
  theDepthReads, theNextPlaneAfter, thePlanesIn,
} from "./counting-planes.js";
import {
  howBrightAndHowTight,
  theWindowThisBrightnessMeans,
  theWindowThisContrastMeans,
} from "./the-window.js";

/* The viewer's light dress, inlined from its `theme.css` — the operator page
   has no dark mode, so only the light values travel. */
const INK = {
  pageBg: "#e7eaee", cardBg: "#f7f8fa", inputBg: "#ffffff",
  panelBorder: "#c7cdd6", controlBorder: "#b6bec9", subtleBorder: "#dce0e6",
  textBright: "#10161f", textPrimary: "#26303c", textMuted: "#5a6675",
  textFaint: "#67727f", accent: "#2563cf", chosenGround: "#dde8f7",
  ghost: "rgba(0, 0, 0, 0.05)", sliderTrack: "#c2c9d2",
  /* The standalone viewer's red for a notice, brought over into the light
     dress the operator page wears: the same warning, legible on a pale
     ground rather than on a dark one. */
  troubleInk: "#9e2b25", troubleGround: "#fbeceb", troubleBorder: "#e6bdb9",
};

/* The viewer's palette, verbatim (`LayerPanel.jsx` PALETTE + css()). */
const PALETTE = [
  { name: "green", rgb: [0.0, 1.0, 0.4] },
  { name: "magenta", rgb: [1.0, 0.2, 1.0] },
  { name: "cyan", rgb: [0.2, 0.8, 1.0] },
  { name: "amber", rgb: [1.0, 0.75, 0.1] },
  { name: "blue", rgb: [0.3, 0.45, 1.0] },
  { name: "red", rgb: [1.0, 0.15, 0.15] },
  { name: "grey", rgb: null },
];
const cssOf = (rgb) =>
  rgb ? `rgb(${rgb.map((v) => Math.round(v * 255)).join(",")})` : "#d8dee6";

/* A word or two saying what each colour map looks like, and a strip of the map
   itself for the swatch.

   The names are the ones everybody uses, and they mean nothing at all until you
   have seen one. A biologist meeting this list for the first time should not
   have to try all four to find out which is which, so each is described in
   plain colours as well as named. This is the ZMART viewer's own
   `LUT_DESCRIPTIONS` (`LayerPanel.jsx`), with the little gradient added because
   a picture of a colour map beats a description of one.

   Which maps are actually on offer is the *engine's* answer, asked for through
   `lutsItCanDraw` — this table only says how to describe one. A map the engine
   offers and this table has never heard of is still offered, plainly. */
const COLOUR_MAP_HINTS = {
  viridis: {
    says: "blue → green → yellow",
    strip: "linear-gradient(to right,#440154,#31688e,#35b779,#fde725)",
  },
  magma: {
    says: "black → purple → cream",
    strip: "linear-gradient(to right,#000004,#711f81,#f0605d,#fcfdbf)",
  },
  fire: {
    says: "black → red → white",
    strip: "linear-gradient(to right,#000000,#991a00,#ffa600,#fffee6)",
  },
  ice: {
    says: "black → blue → white",
    strip: "linear-gradient(to right,#00001a,#0066b3,#66ccff,#ffffff)",
  },
};

/* The 15% rule: the window's edges are drawn at 15% and 85% of the axis. */
const WINDOW_SITS_FROM = 0.15;

const font = (weight, size) => `${weight} ${size}px/1 system-ui, sans-serif`;

/* The viewer's filled slider skin, said once per page. */
const SLIDER_CSS = `
.zv-range { -webkit-appearance:none; appearance:none; background:transparent; height:16px; padding:0; width:100%; cursor:pointer; }
.zv-range::-webkit-slider-runnable-track { height:4px; border-radius:2px;
  background: linear-gradient(to right, ${INK.accent} var(--fill, 0%), ${INK.sliderTrack} var(--fill, 0%)); }
.zv-range::-webkit-slider-thumb { -webkit-appearance:none; width:14px; height:14px; margin-top:-5px; border-radius:50%; border:none; background:${INK.accent}; }
.zv-range:disabled { opacity:.45; cursor:default; }`;

function dressed(slider) {
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
async function theStoresDescription(url) {
  const bar = url.indexOf("|");
  const address = (bar < 0 ? url : url.slice(0, bar)).replace(/\/+$/, "");
  for (const [file, unwrap] of [
    [".zattrs", (doc) => doc],
    ["zarr.json", (doc) => doc?.attributes?.ome ?? doc?.attributes ?? doc],
  ]) {
    try {
      const answer = await fetch(`${address}/${file}`, { cache: "no-store" });
      if (answer.ok) return unwrap(await answer.json());
    } catch {
      // one of the two spellings is expected to be missing
    }
  }
  return null;
}

/** One flat row list, matching the engine's own numbering. */
async function theRows(acquisitions) {
  const rows = [];
  for (const acquisition of acquisitions) {
    const described = (await theStoresDescription(acquisition.url))?.omero?.channels;
    const channels = Array.isArray(described) && described.length
      ? described.map((channel, at) => ({
        name: channel?.label || `channel ${at + 1}`,
        color: typeof channel?.color === "string" ? `#${channel.color}` : null,
        window: channel?.window && Number.isFinite(channel.window.start)
          ? { low: channel.window.start, high: channel.window.end }
          : null,
        within: at,
      }))
      : [{ name: acquisition.name, color: null, window: null, within: 0 }];
    for (const channel of channels) {
      rows.push({
        ...channel,
        acquisition: acquisition.name,
        source: acquisition.url,
        visible: true,
        weight: 1,
        /* Which colour map this channel is painted through, or nothing at all
           for the flat colour it starts in. */
        lut: null,
        /* The window the run itself declared, kept whole and never written
           over. `window` above is the live one and moves with every drag of a
           handle, so within a moment of the operator taking hold of anything
           the original would otherwise be gone for the rest of the session —
           and "put it back the way the acquisition opened" is the request
           somebody who has pulled the handles about makes most often. A copy
           rather than the same object, so moving one cannot move the other. */
        asWritten: channel.window ? { ...channel.window } : null,
      });
    }
  }
  return rows;
}

/* How long the panel is willing to wait for a measurement before saying so.

   A promise that never settles looks exactly like loading: the histogram is
   blank, the sliders sit still, and the natural reading is "it is working on
   it". That has cost this project days more than once, so anything here that
   waits is given a way to refuse. Fifteen seconds is generous for a
   measurement that ordinarily takes well under one, and short enough that
   nobody sits looking at a blank box wondering. */
const A_MEASUREMENT_MAY_TAKE_MS = 15_000;

/**
 * Ask the viewer's server about one channel: its histogram, and a window it
 * would choose itself.
 *
 * Always answers. Either `{ histogram, window }`, or `{ trouble }` — one plain
 * sentence saying what was asked for and what came back, which the panel puts
 * on the screen.
 *
 * That sentence is the whole point of this function's shape. It used to swallow
 * every failure and hand back nothing, so a channel whose measurement never
 * arrived showed an empty histogram and two sliders sitting at their fallback
 * range of nought to sixty-five thousand, with nothing anywhere to say why.
 * Something had gone wrong and the window merely looked quiet — which is
 * exactly the failure this whole piece of work has been about.
 */
async function measured(row) {
  let where;
  try {
    where = `${new URL(row.source).origin}/api/measure`;
  } catch {
    return { trouble: `This channel's address, ${row.source}, is not one the panel can ask about.` };
  }
  const giveUp = new AbortController();
  const waited = setTimeout(() => giveUp.abort(), A_MEASUREMENT_MAY_TAKE_MS);
  try {
    const answer = await fetch(where, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: row.source, channel: row.within, box: [[0, 0], [1, 1]],
      }),
      signal: giveUp.signal,
    });
    if (!answer.ok) {
      return { trouble: `Asked ${where} to measure this channel; it answered ${answer.status}.` };
    }
    const body = await answer.json();
    if (!body?.histogram) {
      return { trouble: `Asked ${where} to measure this channel; it answered without a histogram.` };
    }
    return { histogram: body.histogram, window: body.window };
  } catch (why) {
    if (why?.name === "AbortError") {
      return {
        trouble: `Asked ${where} to measure this channel; nothing came back within `
          + `${Math.round(A_MEASUREMENT_MAY_TAKE_MS / 1000)} seconds.`,
      };
    }
    return { trouble: `Could not reach ${where} to measure this channel: ${why?.message ?? why}.` };
  } finally {
    clearTimeout(waited);
  }
}

const el = (tag, style, text) => {
  const made = document.createElement(tag);
  if (style) made.style.cssText = style;
  if (text !== undefined) made.textContent = text;
  return made;
};

const HEADING = `font:${font(600, 11)};letter-spacing:.08em;text-transform:uppercase;color:${INK.textFaint};padding:0 12px 5px;`;
const CARD = `border-top:1px solid ${INK.panelBorder};border-bottom:1px solid ${INK.panelBorder};padding:8px 0 12px;margin-bottom:12px;background:${INK.cardBg};flex-shrink:0;`;

/** The viewer's eye, verbatim proportions. */
function anEye(open) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.style.cssText = "width:14px;height:14px;display:block;";
  svg.innerHTML =
    '<path d="M1 8s2.6-4.2 7-4.2S15 8 15 8s-2.6 4.2-7 4.2S1 8 1 8z" fill="none" stroke="currentColor" stroke-width="1.3"/>'
    + '<circle cx="8" cy="8" r="1.9" fill="currentColor"/>'
    + (open ? "" : '<path d="M2.5 13.5L13.5 2.5" stroke="currentColor" stroke-width="1.3"/>');
  return svg;
}

/* How long the picture rests on each step while an axis is being played.
   Slow enough to see what is there, fast enough that a stack reads as movement
   rather than as a slideshow — a little over seven steps a second, which is the
   rate the ZMART viewer settled on (`AxisSlider.jsx`). */
const A_STEP_RESTS_FOR_MS = 140;

/** The triangle and the two bars a play button wears. */
function aPlayGlyph(playing) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.style.cssText = "width:11px;height:11px;display:block;";
  svg.innerHTML = playing
    ? '<rect x="3.5" y="3" width="3.5" height="10" fill="currentColor"/>'
      + '<rect x="9" y="3" width="3.5" height="10" fill="currentColor"/>'
    : '<path d="M4 2.5L13 8L4 13.5Z" fill="currentColor"/>';
  return svg;
}

/**
 * One line for moving along an axis: a name, a play button, a slider, a reading.
 *
 * Both the depth of a stack and the moments of a timelapse are the same control
 * with different words on it, so it is built once here. The line knows nothing
 * about micrometres or moments: it is handed where the axis runs from and to,
 * where the picture is on it, and what the reading beside it should say, and it
 * draws that. Whoever mounts it decides what all of those mean.
 *
 * The handle it gives back is small on purpose:
 *
 * - `show(axis)` draws the line, or hides it entirely when there is no axis.
 *   Hiding rather than disabling is deliberate — a run with a single plane is
 *   not a run whose depth control is broken, and a greyed-out slider says the
 *   second thing.
 * - `onMove(tell)` — the operator has moved the handle, in the axis's own units.
 * - `playsWith(step)` — how to take one step. It answers `false` when the axis
 *   has gone away, and the playing then stops itself.
 * - `stopPlaying()` — for when the panel is taken down.
 */
function anAxisControl(label, playTitle) {
  const line = el("label",
    `display:none;grid-template-columns:52px 18px 1fr 96px;gap:6px;align-items:center;padding:2px 12px;font-size:10px;color:${INK.textMuted};`);
  line.dataset.control = label;
  line.append(el("span", "", label));

  const play = el("button",
    `background:none;border:none;color:${INK.textPrimary};cursor:pointer;padding:0;display:flex;align-items:center;justify-content:center;`);
  play.type = "button";
  const slider = dressed(el("input"));
  slider.type = "range";
  const box = el("span",
    `text-align:right;font-variant-numeric:tabular-nums;color:${INK.textPrimary};font-size:11px;`);
  line.append(play, slider, box);

  /* True while the operator has hold of the handle. The picture answers back
     while a drag is going on — every move writes to the viewer, and every
     movement of the viewer brings us round here again — and writing a value
     back underneath a hand that is still holding it makes the handle stutter
     and jump. So while it is held, the reading is refreshed and the handle is
     left where the hand has put it. */
  let held = false;
  slider.addEventListener("pointerdown", () => { held = true; });
  for (const letGo of ["pointerup", "pointercancel"]) {
    slider.addEventListener(letGo, () => { held = false; });
  }

  let timer = null;
  let takeAStep = null;

  function dressThePlayButton(playing) {
    play.replaceChildren(aPlayGlyph(playing));
    play.title = playing ? "Stop" : playTitle;
    /* Said in words as well as drawn, so a check and a screen reader can both
       tell what it is doing. */
    play.dataset.playing = playing ? "1" : "0";
    play.setAttribute("aria-pressed", String(playing));
  }
  dressThePlayButton(false);

  function stopPlaying() {
    if (timer === null) return;
    clearInterval(timer);
    timer = null;
    dressThePlayButton(false);
  }

  play.addEventListener("click", (press) => {
    press.preventDefault();
    press.stopPropagation();
    if (timer !== null || !takeAStep) {
      stopPlaying();
      return;
    }
    dressThePlayButton(true);
    timer = setInterval(() => {
      /* The step says whether the axis is still there. Playing an axis the
         picture no longer has would be a control quietly doing nothing. */
      if (!takeAStep()) stopPlaying();
    }, A_STEP_RESTS_FOR_MS);
  });

  return {
    line,
    show(axis) {
      if (!axis) {
        line.style.display = "none";
        stopPlaying();
        return;
      }
      line.style.display = "grid";
      slider.min = String(axis.low);
      slider.max = String(axis.high);
      slider.step = String(axis.step);
      if (!held) slider.value = String(axis.at);
      box.textContent = axis.reads;
      slider.refill();
    },
    onMove(tell) {
      slider.addEventListener("input", () => tell(Number(slider.value)));
    },
    playsWith(step) {
      takeAStep = step;
    },
    stopPlaying,
  };
}

/**
 * Mount the panel and wire it to the engine handle.
 *
 * `near` is any element inside the canvas's own box; the panel stands as a
 * column of the same grid row, directly to the canvas's right.
 *
 * `startOn` is which channel the settings should be pointed at, given as
 * `{ acquisition, name }` — what `theChannelInHand()` on the returned handle
 * gives back. It is there for the moment this panel is built again because the
 * run has landed a new kind of acquisition: without it the settings jump back
 * to the first channel of the first acquisition, and an operator part-way
 * through setting up a colour finds themselves adjusting something else. A
 * channel that is no longer there is simply not found, and the first row is
 * chosen as before.
 *
 * Names rather than row numbers, and that is the whole point of this argument.
 * A row number stays a perfectly valid number when the list is rebuilt and
 * quietly refers to whatever now occupies that slot, so the sliders go on
 * working while adjusting a channel nobody is looking at. A name that is no
 * longer in the list simply is not found, which is a thing the panel can see
 * and act on.
 */
export async function mountViewerPanel(
  near, { viewer, acquisitions, startOn = null },
) {
  const rows = await theRows(acquisitions);

  if (!document.getElementById("zv-slider-skin")) {
    const skin = document.createElement("style");
    skin.id = "zv-slider-skin";
    skin.textContent = SLIDER_CSS;
    document.head.append(skin);
  }

  const body = near?.closest?.(".canvas-body");
  const plotHost = body?.querySelector(".plot-host");

  /* The strip and the bar, the viewer's own arrangement: the 14px fold strip
     stands between the picture and the bar and stays when the bar goes. */
  const panel = el("aside", "display:flex;flex-direction:row;min-height:0;overflow:hidden;");
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

  let folded = false;
  fold.addEventListener("click", () => {
    folded = !folded;
    bar.style.display = folded ? "none" : "flex";
    fold.textContent = folded ? "‹" : "›";
    fold.title = folded ? "Show the controls" : "Fold the controls away";
  });

  /* ---- channel settings (built first, filled by the selection) ---- */
  const settings = el("div", CARD);
  settings.append(el("div", HEADING, "channel settings"));
  const chosenHead = el("div", "display:flex;flex-direction:column;gap:3px;padding:5px 12px 6px;");
  const chosenLine = el("div", [
    "display:flex", "align-items:center", "gap:8px", "min-width:0",
    `background:${INK.chosenGround}`, "border-radius:3px", "padding:4px 6px",
    `font:${font(600, 12)}`, `color:${INK.textBright}`,
  ].join(";"), "pick a channel below");
  chosenHead.append(chosenLine);

  /* Where the panel says a measurement did not work. It stands directly above
     the histogram, because the empty histogram is the thing it is explaining,
     and it is empty and out of the way until there is something to say. */
  const trouble = el("div", [
    "display:none", "margin:0 12px 6px", "padding:6px 8px",
    `border:1px solid ${INK.troubleBorder}`, "border-radius:4px",
    `background:${INK.troubleGround}`, `color:${INK.troubleInk}`,
    `font:${font(400, 11)}`, "line-height:1.35",
  ].join(";"));
  trouble.setAttribute("role", "alert");
  trouble.dataset.trouble = "0";

  /** Say what went wrong, or take the notice away when nothing has. */
  function sayTheTrouble(saying) {
    trouble.textContent = saying ?? "";
    trouble.style.display = saying ? "block" : "none";
    trouble.dataset.trouble = saying ? "1" : "0";
  }

  const plotWrap = el("div", "padding:1px 12px 4px;");
  const plot = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  plot.setAttribute("preserveAspectRatio", "none");
  plot.style.cssText = [
    "display:block", "width:100%", "height:60px", `color:${INK.textBright}`,
    `background:${INK.inputBg}`, `border:1px solid ${INK.subtleBorder}`,
    "border-radius:3px", "touch-action:none",
  ].join(";");
  plotWrap.append(plot);

  const buttonRow = el("div", "display:flex;gap:6px;justify-content:center;padding:2px 12px;");
  const autoButton = el("button", [
    "height:24px", "padding:0 10px", `border:1px solid ${INK.controlBorder}`,
    "border-radius:4px", `background:${INK.ghost}`, `color:${INK.textPrimary}`,
    `font:${font(600, 11)}`, "cursor:pointer",
  ].join(";"), "Auto");
  /* *Auto* and *Reset* answer different questions and neither replaces the
     other. *Auto* re-reads the brightness actually present in this channel and
     picks a window from it. *Reset* puts back the window the run was written
     with — what the operator saw at the moment the images opened. Somebody who
     has dragged the handles about and lost their picture wants the second far
     more often than a fresh measurement. */
  const resetButton = autoButton.cloneNode(false);
  resetButton.textContent = "Reset";
  resetButton.title = "Put back the window this run was written with";
  const logButton = autoButton.cloneNode(false);
  logButton.textContent = "Log";
  for (const button of [autoButton, resetButton, logButton]) button.type = "button";
  autoButton.title = "Set the window from the brightness measured in this channel";
  buttonRow.append(autoButton, resetButton, logButton);

  const controlRow = (label) => {
    const line = el("label",
      `display:grid;grid-template-columns:58px 1fr 58px;gap:6px;align-items:center;padding:2px 12px;font-size:10px;color:${INK.textMuted};`);
    line.append(el("span", "", label));
    const slider = dressed(el("input"));
    slider.type = "range";
    slider.disabled = true;
    const box = el("span",
      `text-align:right;font-variant-numeric:tabular-nums;color:${INK.textPrimary};font-size:11px;`);
    line.append(slider, box);
    /* Named in the page itself, so a check — or anything else reading the
       panel — can reach exactly the control it means rather than the first one
       whose words happen to start the same way. */
    line.dataset.control = label;
    /* Every one of these controls describes the same window, so every one of
       them is redrawn whenever the window moves — including, a moment later,
       the one the operator still has hold of. Writing a value back underneath
       a hand that is mid-drag makes the handle stutter and jump, so a held
       handle is left where the hand has put it and only its reading is
       refreshed. */
    const row = { line, slider, box, held: false };
    slider.addEventListener("pointerdown", () => { row.held = true; });
    for (const letGo of ["pointerup", "pointercancel"]) {
      slider.addEventListener(letGo, () => { row.held = false; });
    }
    return row;
  };
  const minRow = controlRow("min");
  const maxRow = controlRow("max");
  /* The same one window, said the way a microscopist says it. *min* and *max*
     give where the window's two edges are; *brightness* and *contrast* give how
     bright its middle is and how tightly it is drawn around that middle. There
     is only ever one window underneath, so moving either pair moves the other —
     which is why all four are redrawn together in `refreshControls`. The
     arithmetic is in `the-window.js`. */
  const brightnessRow = controlRow("brightness");
  const contrastRow = controlRow("contrast");
  for (const row of [brightnessRow, contrastRow]) {
    row.slider.min = "0";
    row.slider.step = "1";
  }
  /* Brightness may go all the way to a hundred; contrast stops at ninety-nine,
     because a contrast of a hundred would be a window of no width at all and
     every value in the picture would land on the same shade. The picture goes
     flat and nothing on screen says why. */
  brightnessRow.slider.max = "100";
  contrastRow.slider.max = "99";
  brightnessRow.line.title =
    "Slides the whole window along without changing how wide it is";
  contrastRow.line.title =
    "Draws the window in around its middle, so a smaller range of brightness fills the screen";
  const opacityRow = controlRow("opacity");
  opacityRow.slider.min = "0"; opacityRow.slider.max = "1"; opacityRow.slider.step = "0.01";
  opacityRow.slider.value = "1";
  settings.append(chosenHead, trouble, plotWrap, buttonRow,
    minRow.line, maxRow.line, brightnessRow.line, contrastRow.line, opacityRow.line);

  /* ---- the state the settings act on ---- */
  let chosen = null;   // the flat row index picked out
  let shape = null;    // its measured histogram {low, high, counts, autoWindow}
  let logScale = false;

  const windowOf = (row) => row.window
    ?? (shape?.autoWindow && chosen !== null && rows[chosen] === row ? shape.autoWindow : null)
    ?? { low: 0, high: 65535 };

  function theAxis(row) {
    /* The window sits at 15%..85% of the drawn axis, clamped to what was
       measured — the viewer's own framing. */
    const window_ = windowOf(row);
    const across = (window_.high - window_.low) / (1 - 2 * WINDOW_SITS_FROM) || 1;
    const beyond = across * WINDOW_SITS_FROM;
    const bounds = shape ? { low: shape.low, high: shape.high } : null;
    return {
      low: bounds ? Math.max(Math.min(bounds.low, window_.low), window_.low - beyond) : window_.low - beyond,
      high: bounds ? Math.min(Math.max(bounds.high, window_.high), window_.high + beyond) : window_.high + beyond,
    };
  }

  /**
   * How far brightness and contrast are allowed to travel.
   *
   * Deliberately *not* the axis the histogram is drawn on. That axis follows
   * the window — it is what keeps the window's edges at 15% and 85% of the
   * picture, which is right for the histogram — and a brightness worked out
   * against a track that moves with the window is always the same number,
   * because the window sits in the same place on it whatever it does. Read
   * back, such a slider would spring straight to the middle every time it was
   * let go of.
   *
   * So the travel is taken from the spread of brightness the server actually
   * measured, with a fifth of that spread of room at either end, and it falls
   * back to the whole of what a sixteen-bit camera can produce when nothing has
   * been measured yet. The window in use is always inside it, so a *Reset* to a
   * window outside the measured spread widens the track rather than stranding a
   * handle off the end of it.
   *
   * This is the ZMART viewer's own `contrastRange` (`LayerPanel.jsx`), for the
   * reason given there: nought to sixty-five thousand made the sliders very
   * nearly unusable on real data, where a whole acquisition lives in a few
   * hundred counts near the bottom of the range.
   */
  function theTrack(row) {
    const window_ = windowOf(row);
    /* The best account of where this channel's brightness actually lives, in
       the order they are worth having. A measurement of the pixels is the
       truest. Failing that, the window the run itself declared: a run that
       says "show this between two hundred and three thousand" has told us
       roughly where its signal is, which is far better than assuming nothing.
       Only with neither is the whole of a sixteen-bit camera's range used, and
       that is a poor track — measured on a real acquisition, the useful part
       of it was about two pixels of travel. */
    const measured = shape && Number.isFinite(shape.low) && shape.high > shape.low
      ? { low: shape.low, high: shape.high }
      : null;
    const declared = row.asWritten && row.asWritten.high > row.asWritten.low
      ? row.asWritten
      : null;
    const spread = measured ?? declared;
    let low = 0;
    let high = 65535;
    if (spread) {
      const room = (spread.high - spread.low) * 0.2;
      low = Math.max(theLowestThisChannelCanGo(row), Math.floor(spread.low - room));
      high = Math.ceil(spread.high + room);
    }
    return {
      low: Math.min(low, Math.floor(window_.low)),
      high: Math.max(high, Math.ceil(window_.high), low + 1),
    };
  }

  /**
   * How far down the *track* the two feel controls travel over may reach.
   *
   * Nought for an ordinary camera, which cannot produce a count below it:
   * there is no point offering travel over brightnesses that cannot occur. But
   * a run is allowed to say otherwise — a store written from something other
   * than a photon count may declare a window starting below nought, and that
   * is the run speaking about its own data, so it is believed.
   */
  function theLowestThisChannelCanGo(row) {
    return Math.min(0, row.asWritten?.low ?? 0);
  }

  function drawTheHistogram() {
    while (plot.firstChild) plot.firstChild.remove();
    if (chosen === null) return;
    const row = rows[chosen];
    const window_ = windowOf(row);
    const counts = shape?.counts ?? [];
    plot.setAttribute("viewBox", `0 0 ${Math.max(counts.length, 1)} 24`);
    const axis = theAxis(row);
    const span = axis.high - axis.low || 1;
    const at = (value) =>
      Math.min(Math.max((value - axis.low) / span, 0), 1) * Math.max(counts.length, 1);
    if (shape && counts.length) {
      const bins = shape.high - shape.low || 1;
      const brightnessOf = (index) => shape.low + ((index + 0.5) * bins) / counts.length;
      const peak = Math.max(...counts, 1);
      counts.forEach((count, index) => {
        const share = logScale ? Math.log1p(count) / Math.log1p(peak) : count / peak;
        const height = share * 22;
        const inside = brightnessOf(index) >= window_.low && brightnessOf(index) <= window_.high;
        const starts = at(shape.low + (index * bins) / counts.length);
        const ends = at(shape.low + ((index + 1) * bins) / counts.length);
        const barEl = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        barEl.setAttribute("x", starts);
        barEl.setAttribute("y", 24 - height);
        barEl.setAttribute("width", Math.max(ends - starts, 0.0001));
        barEl.setAttribute("height", height);
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
      line.setAttribute("x", x);
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
    const window_ = windowOf(row);
    const axis = theAxis(row);
    for (const { slider } of [minRow, maxRow]) {
      slider.min = String(Math.floor(axis.low));
      slider.max = String(Math.ceil(axis.high));
      slider.step = "1";
      slider.disabled = false;
    }
    if (!minRow.held) minRow.slider.value = String(Math.floor(window_.low));
    if (!maxRow.held) maxRow.slider.value = String(Math.ceil(window_.high));
    minRow.box.textContent = String(Math.floor(window_.low));
    maxRow.box.textContent = String(Math.ceil(window_.high));
    /* Read back out of the one window rather than remembered, so taking hold of
       a histogram edge — or of *min*, or of *Reset* — moves the brightness and
       contrast numbers too. All four controls describe the same thing and each
       has to show what that thing now is. */
    const feel = howBrightAndHowTight(window_, theTrack(row));
    for (const [control, value] of [
      [brightnessRow, feel.brightness], [contrastRow, feel.contrast],
    ]) {
      control.slider.disabled = false;
      if (!control.held) {
        control.slider.value = String(Math.min(Number(control.slider.max),
          Math.max(Number(control.slider.min), value)));
      }
      control.box.textContent = String(value);
    }
    opacityRow.slider.disabled = false;
    if (!opacityRow.held) opacityRow.slider.value = String(row.weight);
    opacityRow.box.textContent = `${Math.round(row.weight * 100)}%`;
    /* Greyed out on a channel whose store declared no window: there is nothing
       to go back to, and a button that can be pressed and does nothing is worse
       than one that plainly says it has nothing to offer. */
    resetButton.disabled = !row.asWritten;
    resetButton.style.opacity = row.asWritten ? "1" : "0.45";
    resetButton.style.cursor = row.asWritten ? "pointer" : "default";
    resetButton.title = row.asWritten
      ? "Put back the window this run was written with"
      : "This run declared no window for this channel, so there is none to go back to";
    for (const { slider } of
      [minRow, maxRow, brightnessRow, contrastRow, opacityRow]) slider.refill();
    drawTheHistogram();
  }

  function takeTheWindow(next) {
    if (chosen === null) return;
    const row = rows[chosen];
    /* Deliberately not clamped at nought, tempting though it is. A window edge
       below the darkest value a camera can produce clips nothing and changes
       the picture not at all — but forcing it back up would change the
       window's *width*, and the width is what the contrast reading is made of.
       All four controls have to go on describing one window, and a quiet
       clamp here is how three of them would start disagreeing with the
       fourth at the ends of their travel. */
    const low = Math.min(next.low, next.high - 1);
    row.window = { low, high: Math.max(next.high, low + 1) };
    viewer.setChannel(chosen, { window: row.window });
    refreshControls();
  }

  minRow.slider.addEventListener("input", () => takeTheWindow({
    low: Number(minRow.slider.value), high: windowOf(rows[chosen]).high,
  }));
  maxRow.slider.addEventListener("input", () => takeTheWindow({
    low: windowOf(rows[chosen]).low, high: Number(maxRow.slider.value),
  }));
  /* Both of these funnel into the same `takeTheWindow` the two edges use, so
     nothing outside this panel needs to know that these controls exist: the
     viewer is told about a window, exactly as before. */
  brightnessRow.slider.addEventListener("input", () => {
    if (chosen === null) return;
    const row = rows[chosen];
    takeTheWindow(theWindowThisBrightnessMeans(
      windowOf(row), theTrack(row), Number(brightnessRow.slider.value)));
  });
  contrastRow.slider.addEventListener("input", () => {
    if (chosen === null) return;
    const row = rows[chosen];
    takeTheWindow(theWindowThisContrastMeans(
      windowOf(row), theTrack(row), Number(contrastRow.slider.value)));
  });
  opacityRow.slider.addEventListener("input", () => {
    if (chosen === null) return;
    rows[chosen].weight = Number(opacityRow.slider.value);
    sendTheWeightFor(chosen);
    opacityRow.box.textContent = `${Math.round(rows[chosen].weight * 100)}%`;
  });
  logButton.addEventListener("click", () => {
    logScale = !logScale;
    logButton.style.background = logScale ? INK.accent : INK.ghost;
    logButton.style.color = logScale ? "#fff" : INK.textPrimary;
    drawTheHistogram();
  });
  resetButton.addEventListener("click", () => {
    if (chosen === null) return;
    const original = rows[chosen].asWritten;
    if (original) takeTheWindow({ ...original });
  });
  autoButton.addEventListener("click", async () => {
    if (chosen === null) return;
    const row = rows[chosen];
    const answer = await measured(row);
    sayTheTrouble(answer.trouble);
    if (answer.histogram) shape = answer.histogram;
    const wanted = answer.window ?? shape?.autoWindow;
    if (wanted) takeTheWindow(wanted);
    else refreshControls();
  });

  /* The window's edges can be taken hold of on the histogram itself, with
     the viewer's six pixels of grace. */
  let held = null;
  const valueUnder = (event) => {
    const face = plot.getBoundingClientRect();
    const axis = theAxis(rows[chosen]);
    const share = Math.min(1, Math.max(0, (event.clientX - face.left) / face.width));
    return axis.low + share * (axis.high - axis.low);
  };
  plot.addEventListener("pointerdown", (event) => {
    if (chosen === null || !shape) return;
    const window_ = windowOf(rows[chosen]);
    const face = plot.getBoundingClientRect();
    const axis = theAxis(rows[chosen]);
    const grace = (6 / face.width) * (axis.high - axis.low);
    const pressed = valueUnder(event);
    if (Math.abs(pressed - window_.low) <= grace) held = "low";
    else if (Math.abs(pressed - window_.high) <= grace) held = "high";
    else return;
    plot.setPointerCapture(event.pointerId);
  });
  plot.addEventListener("pointermove", (event) => {
    if (chosen === null) return;
    const window_ = windowOf(rows[chosen]);
    if (!held) {
      if (!shape) return;
      const face = plot.getBoundingClientRect();
      const axis = theAxis(rows[chosen]);
      const grace = (6 / face.width) * (axis.high - axis.low);
      const over = valueUnder(event);
      const overBar = Math.abs(over - window_.low) <= grace
        || Math.abs(over - window_.high) <= grace;
      plot.style.cursor = overBar ? "ew-resize" : "default";
      return;
    }
    const value = valueUnder(event);
    takeTheWindow(held === "low"
      ? { low: Math.min(value, window_.high - 1), high: window_.high }
      : { low: window_.low, high: Math.max(value, window_.low + 1) });
  });
  for (const done of ["pointerup", "pointercancel"]) {
    plot.addEventListener(done, () => { held = null; });
  }

  /* ---- the data card: groups, eyes, swatches, names ---- */
  const data = el("div", CARD);
  data.append(el("div", HEADING, "data"));

  let chooserOpen = null;
  const closeChooser = () => { chooserOpen?.remove(); chooserOpen = null; };
  document.addEventListener("pointerdown", closeChooser, true);

  /* The colour maps this particular engine can actually paint through. Asked
     for rather than assumed, so nobody is offered a choice that would do
     nothing: an engine with none leaves this empty and the swatch offers flat
     colours alone, exactly as it always did. */
  const colourMapsOnOffer = Array.isArray(viewer.lutsItCanDraw)
    ? viewer.lutsItCanDraw
    : [];

  /** How a colour map is shown: a strip of it if we know one, else a plain box. */
  const stripFor = (name) =>
    COLOUR_MAP_HINTS[name]?.strip ?? cssOf(null);

  function aSwatch(index, row) {
    const swatch = el("button", [
      "width:13px", "height:13px", "border-radius:3px",
      `border:1px solid ${INK.controlBorder}`, "display:inline-block",
      "flex-shrink:0", "padding:0", "cursor:pointer", "appearance:none",
    ].join(";"));
    swatch.type = "button";
    swatch.addEventListener("pointerdown", (press) => press.stopPropagation());

    /* The swatch shows what the channel is really painted in — a flat colour as
       a block, a colour map as a strip of the map itself. A row painted through
       viridis whose swatch still showed a flat green would be the same small
       untruth as an eye left open on a hidden channel. */
    const dressTheSwatch = () => {
      swatch.style.background = row.lut ? stripFor(row.lut) : (row.color ?? cssOf(null));
      swatch.title = row.lut
        ? `Painted through ${row.lut}. Click to choose another colour`
        : "Choose this channel's colour";
      swatch.dataset.lut = row.lut ?? "";
    };
    dressTheSwatch();

    swatch.addEventListener("click", (press) => {
      press.stopPropagation();
      closeChooser();
      const face = swatch.getBoundingClientRect();
      const list = el("div", [
        "position:fixed", "left:0", "top:0", "visibility:hidden",
        "z-index:40", "min-width:116px", `background:${INK.cardBg}`,
        `border:1px solid ${INK.panelBorder}`, "border-radius:6px",
        "padding:4px", "box-shadow:0 2px 10px rgba(25,35,50,0.22)",
        "display:flex", "flex-direction:column", "gap:2px",
        "max-height:70vh", "overflow-y:auto",
      ].join(";"));

      /** One line of the chooser: a sample of the colour, and what it is called. */
      const anEntry = (sample, name, note, chosen) => {
        const entry = el("button",
          `display:flex;align-items:center;gap:7px;border:none;cursor:pointer;padding:3px 6px;border-radius:3px;font:${font(400, 12)};color:${INK.textPrimary};text-align:left;background:${chosen ? INK.chosenGround : "none"};`);
        entry.type = "button";
        entry.append(
          el("span", `display:inline-block;width:22px;height:11px;flex-shrink:0;border-radius:2px;border:1px solid ${INK.controlBorder};background:${sample};`),
          el("span", "", name),
        );
        if (note) {
          entry.append(el("span",
            `color:${INK.textFaint};font-size:10px;white-space:nowrap;`, note));
        }
        entry.addEventListener("pointerdown", (press2) => press2.stopPropagation());
        list.append(entry);
        return entry;
      };

      for (const choice of PALETTE) {
        const entry = anEntry(cssOf(choice.rgb), choice.name, null,
          !row.lut && row.color === cssOf(choice.rgb));
        entry.addEventListener("click", () => {
          const rgb = choice.rgb ?? [0.847, 0.871, 0.902];
          row.color = cssOf(choice.rgb);
          row.lut = null;
          dressTheSwatch();
          /* Both together: choosing a flat colour is also a request to stop
             painting through a colour map, and sending only the colour would
             leave the map on with the new colour quietly ignored. */
          viewer.setChannel(index, { colour: rgb, lut: null });
          closeChooser();
        });
      }

      if (colourMapsOnOffer.length) {
        /* A colour map paints one channel in a run of colours rather than one
           flat colour, which on a single channel usually reads far more detail:
           the whole range of hue carries the brightness instead of the
           brightness carrying itself. */
        list.append(el("div",
          `margin:4px 6px 2px;padding-top:4px;border-top:1px solid ${INK.subtleBorder};font:${font(600, 10)};letter-spacing:.06em;text-transform:uppercase;color:${INK.textFaint};`,
          "colour maps"));
        for (const name of colourMapsOnOffer) {
          const entry = anEntry(stripFor(name), name,
            COLOUR_MAP_HINTS[name]?.says, row.lut === name);
          entry.addEventListener("click", () => {
            row.lut = name;
            dressTheSwatch();
            viewer.setChannel(index, { lut: name });
            closeChooser();
          });
        }
      }

      document.body.append(list);
      /* And now it is put where it can be read. The bar stands against the
         right-hand edge of the window, so a list that always opened to the
         right of the swatch would hang off the screen — which is what happened
         the moment the colour maps arrived and made the entries wider than the
         plain colour names had been. So it goes to the right where there is
         room and to the left where there is not, and is kept on screen at the
         bottom the same way. Measured after it is in the page rather than
         guessed at, because how wide it turns out to be depends on how many
         maps this engine offered and what they are called. */
      const room = list.getBoundingClientRect();
      const margin = 8;
      const toTheRight = face.right + 6;
      const left = toTheRight + room.width > window.innerWidth - margin
        ? Math.max(margin, face.left - room.width - 6)
        : toTheRight;
      const top = Math.max(margin, Math.min(
        face.top - 4, window.innerHeight - room.height - margin,
      ));
      list.style.left = `${left}px`;
      list.style.top = `${top}px`;
      list.style.visibility = "visible";
      chooserOpen = list;
    });
    return swatch;
  }

  const rowLines = [];
  /* Each row's eye, and each acquisition heading's, so the panel can be
     brought back into agreement with the picture whenever the two might have
     parted — see `refresh`. */
  const eyes = new Map();
  const groupEyes = [];
  /* Each acquisition by name: which rows belong to it, how brightly it is
     drawn as a whole, and whether its channels are folded away. */
  const groupsByName = new Map();

  /**
   * Tell the viewer how brightly one channel should be drawn.
   *
   * Two numbers meet here and neither belongs to the other. A channel has its
   * own opacity, set on the row's slider, and the acquisition it belongs to has
   * one of its own, which dims all of its channels together. What the viewer
   * needs is the two multiplied — and it is worked out in this one place so the
   * two can never fall out of step, which is what happens when a group slider
   * writes a weight that the next touch of a channel slider quietly overwrites.
   */
  function sendTheWeightFor(index) {
    const row = rows[index];
    if (!row) return;
    const group = groupsByName.get(row.acquisition);
    viewer.setChannel(index, { weight: row.weight * (group?.weight ?? 1) });
  }
  let heading = null;
  let groupBox = null;
  rows.forEach((row, index) => {
    if (row.acquisition !== heading) {
      heading = row.acquisition;
      const group = el("div", `border-bottom:1px solid ${INK.subtleBorder};`);
      const head = el("div", "display:flex;align-items:center;gap:6px;padding:5px 12px 3px;");
      const groupEye = el("button",
        `background:none;border:none;color:${INK.textPrimary};cursor:pointer;padding:0;`);
      groupEye.type = "button";
      groupEye.dataset.on = "1";
      groupEye.dataset.acquisition = heading;
      dressTheEye(groupEye, true, "acquisition");
      const members = rows.map((one, at) => ({ one, at }))
        .filter(({ one }) => one.acquisition === heading);
      /* Kept so that `refresh` can bring this eye back into agreement with
         the picture too. A whole acquisition turned off from elsewhere used
         to leave its heading's eye wide open, which is the same untruth as
         a channel's and rather more visible. */
      groupEyes.push({ eye: groupEye, members });
      /* Everything this acquisition holds as a whole: which rows are its own,
         whether it is being shown, how brightly it is drawn, and whether its
         channels are folded away in the bar. */
      const standing = { members, shown: true, weight: 1, folded: false };
      groupsByName.set(heading, standing);
      groupEye.addEventListener("click", () => {
        const on = groupEye.dataset.on !== "1";
        groupEye.dataset.on = on ? "1" : "0";
        standing.shown = on;
        dressTheEye(groupEye, on, "acquisition");
        for (const { one, at } of members) {
          /* A channel the operator had already turned off stays off when the
             acquisition is shown again: turning a whole acquisition back on
             is not a request to undo every choice made inside it. */
          viewer.setChannel(at, { visible: on && one.visible !== false });
        }
      });
      /* Folding an acquisition's channels away. A run with three acquisitions
         and several colours each fills the whole bar, and most of the time an
         operator is working in one of them. The fold is about the bar and
         nothing else: what is drawn is untouched by it, which is why the
         channel count stays beside the heading — a folded group still has to
         say how much is inside it. */
      const disclose = el("button",
        `background:none;border:none;color:${INK.textMuted};cursor:pointer;padding:0;width:10px;font:${font(400, 10)};line-height:1;`,
        "▾");
      disclose.type = "button";
      const count = el("span",
        `font:${font(400, 10)};color:${INK.textFaint};font-variant-numeric:tabular-nums;`,
        String(members.length));
      head.append(disclose, groupEye, el("span",
        `flex:1;font:${font(600, 12)};letter-spacing:.02em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;`,
        heading), count);
      groupBox = el("div", `padding-left:8px;border-left:2px solid ${INK.subtleBorder};margin-left:16px;`);

      /* How brightly this whole acquisition is drawn.

         It needs nothing at all from the engine: it multiplies into the weight
         the panel already sends for each channel, so an acquisition dims as a
         whole while the balance of colours the operator chose inside it stays
         exactly as they set it. That matters — a focussing sweep taken down to
         a fifth so the overview beneath it can be read must not also flatten
         the difference between its own two colours. */
      const groupOpacity = el("label",
        `display:flex;align-items:center;gap:6px;padding:0 12px 4px 26px;font:${font(400, 10)};color:${INK.textMuted};`);
      const groupWeight = dressed(el("input"));
      groupWeight.type = "range";
      groupWeight.min = "0";
      groupWeight.max = "1";
      groupWeight.step = "0.01";
      groupWeight.value = "1";
      groupWeight.title = "How brightly this whole acquisition is drawn";
      const groupWeightBox = el("span",
        `width:32px;text-align:right;font-variant-numeric:tabular-nums;color:${INK.textPrimary};`,
        "100%");
      groupOpacity.append(el("span", "", "opacity"), groupWeight, groupWeightBox);
      groupOpacity.dataset.control = "acquisition opacity";
      groupOpacity.dataset.acquisition = heading;

      groupWeight.addEventListener("input", () => {
        standing.weight = Number(groupWeight.value);
        groupWeightBox.textContent = `${Math.round(standing.weight * 100)}%`;
        for (const { at } of members) sendTheWeightFor(at);
      });

      const folding = groupBox;
      disclose.title = "Fold this acquisition's channels away";
      disclose.setAttribute("aria-expanded", "true");
      disclose.dataset.folded = "0";
      disclose.addEventListener("click", (press) => {
        press.stopPropagation();
        standing.folded = !standing.folded;
        folding.style.display = standing.folded ? "none" : "";
        disclose.textContent = standing.folded ? "▸" : "▾";
        disclose.dataset.folded = standing.folded ? "1" : "0";
        disclose.setAttribute("aria-expanded", String(!standing.folded));
        disclose.title = standing.folded
          ? "Show this acquisition's channels"
          : "Fold this acquisition's channels away";
      });

      group.append(head, groupOpacity, groupBox);
      data.append(group);
    }
    const line = el("div",
      "position:relative;padding:1px 0;cursor:pointer;margin-right:12px;border-radius:3px;");
    const inner = el("div", "display:flex;align-items:center;gap:8px;padding:5px 12px;");
    const eye = el("button",
      `background:none;border:none;color:${INK.textPrimary};cursor:pointer;padding:0;`);
    eye.type = "button";
    /* Drawn from what the row actually is, not from a hopeful `true`.
       An eye that always opens is a panel that says a channel is being
       drawn when it is not: a row turned off from anywhere but this button
       — by the page, or by a row that opened hidden — kept an open eye, and
       an operator reading the panel was told the opposite of the truth
       about their own picture. `dressTheEye` is also what `refresh` below
       calls, so the two can never drift apart. */
    dressTheEye(eye, row.visible !== false);
    /* Which row this eye belongs to, said in the page itself. The eyes stand
       in the order heading, channels, heading, channels, so counting them to
       find a particular channel only works when every acquisition happens to
       have the same number of colours — and a check that quietly depends on
       that is a check that stops meaning anything the moment a run records two
       colours instead of one. */
    eye.dataset.row = String(index);
    eyes.set(index, eye);
    eye.addEventListener("click", (press) => {
      press.stopPropagation();
      row.visible = !row.visible;
      dressTheEye(eye, row.visible);
      viewer.setChannel(index, { visible: row.visible });
    });
    inner.append(eye, aSwatch(index, row), el("span",
      "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;", row.name));
    line.append(inner);
    line.addEventListener("click", () => chooseRow(index));
    rowLines.push(line);
    groupBox.append(line);
  });

  /** What names a channel, in a way that survives the list being rebuilt. */
  const theNameOf = (row) => ({ acquisition: row.acquisition, name: row.name });

  /** Which row that name is now, or `-1` when this run no longer has it. */
  function theRowNamed(named) {
    if (!named) return -1;
    return rows.findIndex((row) => row.acquisition === named.acquisition
      && row.name === named.name);
  }

  async function chooseRow(index) {
    chosen = index;
    const row = rows[index];
    rowLines.forEach((line, at) => {
      line.style.background = at === index ? INK.chosenGround : "";
    });
    chosenLine.replaceChildren(
      el("span", `font:${font(600, 12)};color:${INK.textPrimary};`, row.acquisition),
      el("span", "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;", row.name),
    );
    shape = null;
    sayTheTrouble(null);
    refreshControls();
    const answer = await measured(row);
    /* The operator may well have picked another channel while this was in the
       air, and an answer about the channel they have left would be worse than
       no answer at all. */
    if (chosen !== index) return;
    sayTheTrouble(answer.trouble);
    if (answer.trouble) return;
    shape = answer.histogram;
    if (!row.window && answer.window) row.window = answer.window;
    refreshControls();
  }

  /* ---- the picture as a whole: master switch, depth, volume ---- */
  const whole = el("div", CARD);
  whole.append(el("div", HEADING, "picture"));
  const pictureLine = el("label",
    "display:flex;align-items:center;gap:8px;cursor:pointer;padding:5px 12px;");
  const pictureEye = el("input");
  pictureEye.type = "checkbox";
  pictureEye.checked = true;
  pictureEye.style.cssText = "margin:0;";
  pictureEye.addEventListener("change", () => viewer.showPicture?.(pictureEye.checked));
  pictureLine.append(pictureEye, el("span", "", "draw the picture"));
  whole.append(pictureLine);

  /* Moving through the stack, and through time.
     Both controls are built whether or not there is anything yet to move
     through, and each is hidden until there is. A run gains depth part-way
     through — the first focussing sweep lands and suddenly there is somewhere
     to go — and a live acquisition that keeps going is a timelapse whether or
     not anybody called it one. A panel that decided once, at the moment it was
     mounted, would leave an operator with no way through a stack that is
     plainly on their screen. */
  const stepping = anAxisControl("depth (z)", "Play the stack");
  const timeStepping = anAxisControl("time (t)", "Play the timelapse");
  whole.append(stepping.line, timeStepping.line);

  const volumeLine = el("label",
    "display:flex;align-items:center;gap:8px;cursor:pointer;padding:5px 12px;");
  const wantsAVolume = el("input");
  wantsAVolume.type = "checkbox";
  wantsAVolume.style.cssText = "margin:0;";
  wantsAVolume.addEventListener("change", () => viewer.showVolume?.(wantsAVolume.checked));
  volumeLine.append(wantsAVolume, el("span", "", "draw the stack as a volume"));
  whole.append(volumeLine);

  /**
   * Draw both controls from what the picture is really showing.
   *
   * Everything here is read back out of the viewer rather than remembered.
   * That is the whole point of these controls: the depth slider used only to
   * write, so moving through the stack any other way — the scroll wheel, a
   * step of the workflow, the viewer opening itself on a plane — left it
   * showing where it had last put the operator, which is not where the picture
   * was.
   */
  function showWhereThePictureIs() {
    const depth = viewer.theDepthItCanShow?.();
    const stack = thePlanesIn(depth);
    stepping.show(stack && {
      low: depth.lowUm, high: depth.highUm, step: depth.stepUm || 1,
      at: depth.atUm ?? depth.lowUm, reads: theDepthReads(depth),
    });
    /* A volume is a way of looking at a stack, so the offer goes away with the
       stack, and so does whatever was asked for. */
    volumeLine.style.display = stack && viewer.canShowVolume ? "flex" : "none";

    /* And the moments. A run with one moment shows no time control at all,
       rather than a slider that cannot move — which is the whole difference
       between "this is not a timelapse" and "this control is broken". */
    const moments = viewer.theMomentsItCanShow?.();
    timeStepping.show(moments?.count > 1 && {
      low: 0, high: moments.count - 1, step: 1, at: moments.at ?? 0,
      reads: `moment ${(moments.at ?? 0) + 1} / ${moments.count}`,
    });
  }

  stepping.onMove((to) => {
    viewer.setPlane?.(to);
    /* And then read back, so the number beside the handle is the picture's
       answer rather than the handle's request. A viewer that rounded the ask
       to its nearest plane says so here instead of being contradicted. */
    showWhereThePictureIs();
  });
  timeStepping.onMove((to) => {
    viewer.setMoment?.(Math.round(to));
    showWhereThePictureIs();
  });

  /* Playing.
     Looking through a stack or a timelapse by hand is a poor way to see
     movement, and movement is often the whole point — a specimen drifting, a
     marker brightening. Each of these walks one step at a time and wraps round
     at the end, so it loops rather than stopping on the last frame and looking
     as though it has stalled.

     Each step reads where the picture is now and works out the next from that,
     rather than counting on its own. So a stack being played that somebody
     scrolls, or that the workflow moves, carries on from where the picture
     actually got to. And if the axis goes away underneath it — a run swapping
     its acquisitions, a stack that is no longer a stack — the playing stops
     itself, because a play button quietly stepping something that is not there
     is a control saying it is doing something it is not. */
  stepping.playsWith(() => {
    const depth = viewer.theDepthItCanShow?.();
    const next = theNextPlaneAfter(depth);
    if (next === null) return false;
    viewer.setPlane?.(next);
    showWhereThePictureIs();
    return true;
  });
  timeStepping.playsWith(() => {
    const moments = viewer.theMomentsItCanShow?.();
    if (!(moments?.count > 1)) return false;
    const now = moments.at ?? 0;
    viewer.setMoment?.(now + 1 >= moments.count ? 0 : now + 1);
    showWhereThePictureIs();
    return true;
  });

  showWhereThePictureIs();

  bar.append(data, settings, whole);
  if (plotHost) plotHost.after(panel);
  else (body ?? near)?.append(panel);
  /* Left where a test can reach it, the way the picture itself is. */
  window.__viewerPanel = panel;
  /* Pointed back at the channel the operator was working on where that channel
     is still here, and at the first row otherwise. */
  const asked = theRowNamed(startOn);
  if (rows.length) chooseRow(asked >= 0 ? asked : 0);

  /* Everything the panel has asked to be told about, and how to stop being
     told. Kept as one list because there is more than one now, and a panel
     that lets go of some of its listeners and not others leaves the viewer
     calling back into a bar that is no longer on the screen. */
  const stopListening = [];

  const panelHandle = {
    /**
     * Bring the panel back into agreement with the picture.
     *
     * The panel and the viewer both hold an opinion about which channels are
     * being drawn, and the panel's is only ever right because it was the one
     * that changed it. Anything else that turns a row off — a page, a test,
     * a step of the workflow — leaves the panel saying the opposite of what
     * the operator can see. So the viewer is asked what it is really doing
     * and the eyes are drawn from the answer.
     */
    refresh() {
      const onScreen = viewer.layersForMeasurement?.();
      if (!onScreen) return;
      onScreen.forEach((row, at) => {
        const eye = eyes.get(at);
        if (!eye) return;
        const shown = row.visible !== false;
        /* The eye is drawn from what the picture is really doing, always.
           What is *remembered* is a different question, and getting the two
           mixed up cost this panel a real fault: while an acquisition was
           hidden, every one of its channels was recorded as one the operator
           had turned off, so showing the acquisition again brought nothing
           back — the heading's eye opened over a picture that stayed dark.
           So the operator's own choice for a channel is only taken from the
           screen while its acquisition is being shown at all. */
        const group = rows[at] && groupsByName.get(rows[at].acquisition);
        if (rows[at] && group?.shown !== false) rows[at].visible = shown;
        dressTheEye(eye, shown);
      });
      /* An acquisition's own eye is open while any of its channels is being
         drawn: the heading says whether there is anything of this
         acquisition on screen, which is the question it is there to answer. */
      for (const { eye, members } of groupEyes) {
        const anyShown = members.some(
          ({ at }) => onScreen[at] && onScreen[at].visible !== false,
        );
        eye.dataset.on = anyShown ? "1" : "0";
        dressTheEye(eye, anyShown, "acquisition");
      }
    },
    /**
     * Which channel the settings are pointed at, by name.
     *
     * Handed back so that whoever mounts this panel can point the next one at
     * the same channel when the list is built again — which happens whenever
     * the run lands a new kind of acquisition, often in the middle of a scan.
     * `null` when nothing is chosen.
     */
    theChannelInHand() {
      return chosen === null || !rows[chosen] ? null : theNameOf(rows[chosen]);
    },

    destroy() {
      /* Anything still playing is stopped first. A timer stepping a viewer
         through a stack after the bar that started it has left the page is a
         picture moving with nothing on screen saying why. */
      stepping.stopPlaying();
      timeStepping.stopPlaying();
      for (const stop of stopListening) stop();
      stopListening.length = 0;
      closeChooser();
      document.removeEventListener("pointerdown", closeChooser, true);
      panel.remove();
      if (window.__viewerPanel === panel) window.__viewerPanel = null;
    },
  };

  /* And the panel listens, so it never has to be told by hand. An eye that
     follows only when somebody remembers to ask is an eye that will one day
     be photographed saying the wrong thing — which is exactly how a channel
     that had been switched off went on showing an open eye. A viewer that
     offers no such announcement simply keeps the panel as it was, and
     `refresh` can still be called. */
  const stopHearingAboutChannels =
    viewer.whenChannelsChange?.(() => panelHandle.refresh());
  if (stopHearingAboutChannels) stopListening.push(stopHearingAboutChannels);

  /* And the panel listens for the picture moving, for exactly the same reason.
     The depth slider used only ever to write, so the scroll wheel, a step of
     the workflow, or the viewer settling on a plane of its own all left it
     showing a number that was no longer true. A viewer that offers no such
     announcement simply keeps the control as it was. */
  const stopHearingAboutTheView =
    viewer.whenTheViewMoves?.(() => showWhereThePictureIs());
  if (stopHearingAboutTheView) stopListening.push(stopHearingAboutTheView);

  return panelHandle;
}

/**
 * Draw an eye as open or closed, and say so to a reader who cannot see it.
 *
 * One place, used when a row is built and whenever the panel is brought back
 * into agreement with the picture, so an eye cannot say one thing while the
 * channel does another.
 */
function dressTheEye(eye, shown, what = "channel") {
  eye.replaceChildren(anEye(shown));
  eye.style.opacity = shown ? "1" : "0.4";
  eye.title = shown ? `Hide this ${what}` : `Show this ${what}`;
  /* Said in words as well as drawn, so the state can be read by a test and
     by somebody using a screen reader rather than only seen. */
  eye.dataset.shown = shown ? "1" : "0";
  eye.setAttribute("aria-pressed", String(!shown));
}
