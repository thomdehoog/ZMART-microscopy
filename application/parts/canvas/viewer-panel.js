/**
 * The viewer's own controls, ported from the ZMART viewer's sidebar.
 *
 * The structure, the dress and the behaviour follow the viewer's
 * `app/page/src/LayerPanel.jsx` (its `data` and `channel settings` cards) as
 * closely as a vanilla port can: the 264px bar with its 14px fold strip, the
 * card-on-panel grounds, the eye glyph, the swatch that opens a palette, the
 * 60px histogram with dimmed out-of-window bars and two accent edge lines the
 * hand can drag, the min/max sliders with typed value boxes, and opacity per
 * channel. Where this file and that one disagree, that one is right.
 *
 * The rows are enumerated exactly the way the engine enumerates its own —
 * one per channel, acquisitions in order — so the flat index handed to
 * `viewer.setChannel(index, …)` names the same row on both sides.
 */

/* The viewer's light dress, inlined from its `theme.css` — the operator page
   has no dark mode, so only the light values travel. */
const INK = {
  pageBg: "#e7eaee", cardBg: "#f7f8fa", inputBg: "#ffffff",
  panelBorder: "#c7cdd6", controlBorder: "#b6bec9", subtleBorder: "#dce0e6",
  textBright: "#10161f", textPrimary: "#26303c", textMuted: "#5a6675",
  textFaint: "#67727f", accent: "#2563cf", chosenGround: "#dde8f7",
  ghost: "rgba(0, 0, 0, 0.05)", sliderTrack: "#c2c9d2",
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
      });
    }
  }
  return rows;
}

/** Ask the viewer's server about one channel: its histogram and a window it
    would choose itself. `null` when it will not say. */
async function measured(row) {
  try {
    const origin = new URL(row.source).origin;
    const answer = await fetch(`${origin}/api/measure`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: row.source, channel: row.within, box: [[0, 0], [1, 1]],
      }),
    });
    if (!answer.ok) return null;
    const body = await answer.json();
    return body?.histogram ? body : null;
  } catch {
    return null;
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

/**
 * Mount the panel and wire it to the engine handle. Returns `{ destroy }`.
 * `near` is any element inside the canvas's own box; the panel stands as a
 * column of the same grid row, directly to the canvas's right.
 */
export async function mountViewerPanel(near, { viewer, acquisitions }) {
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
  const logButton = autoButton.cloneNode(false);
  logButton.textContent = "Log";
  for (const button of [autoButton, logButton]) button.type = "button";
  buttonRow.append(autoButton, logButton);

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
    return { line, slider, box };
  };
  const minRow = controlRow("min");
  const maxRow = controlRow("max");
  const opacityRow = controlRow("opacity");
  opacityRow.slider.min = "0"; opacityRow.slider.max = "1"; opacityRow.slider.step = "0.01";
  opacityRow.slider.value = "1";
  settings.append(chosenHead, plotWrap, buttonRow, minRow.line, maxRow.line, opacityRow.line);

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
    minRow.slider.value = String(Math.floor(window_.low));
    maxRow.slider.value = String(Math.ceil(window_.high));
    minRow.box.textContent = String(Math.floor(window_.low));
    maxRow.box.textContent = String(Math.ceil(window_.high));
    opacityRow.slider.disabled = false;
    opacityRow.slider.value = String(row.weight);
    opacityRow.box.textContent = `${Math.round(row.weight * 100)}%`;
    for (const { slider } of [minRow, maxRow, opacityRow]) slider.refill();
    drawTheHistogram();
  }

  function takeTheWindow(next) {
    if (chosen === null) return;
    const row = rows[chosen];
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
  opacityRow.slider.addEventListener("input", () => {
    if (chosen === null) return;
    rows[chosen].weight = Number(opacityRow.slider.value);
    viewer.setChannel(chosen, { weight: rows[chosen].weight });
    opacityRow.box.textContent = `${Math.round(rows[chosen].weight * 100)}%`;
  });
  logButton.addEventListener("click", () => {
    logScale = !logScale;
    logButton.style.background = logScale ? INK.accent : INK.ghost;
    logButton.style.color = logScale ? "#fff" : INK.textPrimary;
    drawTheHistogram();
  });
  autoButton.addEventListener("click", async () => {
    if (chosen === null) return;
    const row = rows[chosen];
    const answer = await measured(row);
    if (answer?.histogram) shape = answer.histogram;
    const wanted = answer?.window ?? shape?.autoWindow;
    if (wanted) takeTheWindow(wanted);
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

  function aSwatch(index, row) {
    const swatch = el("button", [
      "width:13px", "height:13px", "border-radius:3px",
      `border:1px solid ${INK.controlBorder}`, "display:inline-block",
      "flex-shrink:0", "padding:0", "cursor:pointer", "appearance:none",
      `background:${row.color ?? cssOf(null)}`,
    ].join(";"));
    swatch.type = "button";
    swatch.title = "Choose this channel's colour";
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
      for (const choice of PALETTE) {
        const entry = el("button",
          `display:flex;align-items:center;gap:7px;border:none;background:none;cursor:pointer;padding:3px 6px;border-radius:3px;font:${font(400, 12)};color:${INK.textPrimary};text-align:left;`);
        entry.type = "button";
        entry.append(
          el("span", `display:inline-block;width:22px;height:11px;border-radius:2px;border:1px solid ${INK.controlBorder};background:${cssOf(choice.rgb)};`),
          el("span", "", choice.name),
        );
        entry.addEventListener("pointerdown", (press) => press.stopPropagation());
        entry.addEventListener("click", () => {
          const rgb = choice.rgb ?? [0.847, 0.871, 0.902];
          row.color = cssOf(choice.rgb);
          swatch.style.background = row.color;
          viewer.setChannel(index, { colour: rgb });
          closeChooser();
        });
        list.append(entry);
      }
      document.body.append(list);
      chooserOpen = list;
    });
    return swatch;
  }

  const rowLines = [];
  /* Each row's eye, so the panel can be brought back into agreement with the
     picture whenever the two might have parted — see `refresh`. */
  const eyes = new Map();
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
      groupEye.append(anEye(true));
      groupEye.title = "Hide this acquisition";
      const members = rows.map((one, at) => ({ one, at }))
        .filter(({ one }) => one.acquisition === heading);
      groupEye.addEventListener("click", () => {
        const on = groupEye.dataset.on !== "1";
        groupEye.dataset.on = on ? "1" : "0";
        groupEye.replaceChildren(anEye(on));
        groupEye.style.opacity = on ? "1" : "0.4";
        groupEye.title = on ? "Hide this acquisition" : "Show this acquisition";
        for (const { one, at } of members) {
          viewer.setChannel(at, { visible: on && one.visible });
        }
      });
      head.append(groupEye, el("span",
        `flex:1;font:${font(600, 12)};letter-spacing:.02em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;`,
        heading));
      groupBox = el("div", `padding-left:8px;border-left:2px solid ${INK.subtleBorder};margin-left:16px;`);
      group.append(head, groupBox);
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
    refreshControls();
    const answer = await measured(row);
    if (chosen !== index || !answer) return;
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

  const depth = viewer.theDepthItCanShow?.();
  if (depth && depth.highUm > depth.lowUm) {
    const depthLine = el("label",
      `display:grid;grid-template-columns:58px 1fr 58px;gap:6px;align-items:center;padding:2px 12px;font-size:10px;color:${INK.textMuted};`);
    depthLine.append(el("span", "", "depth (z)"));
    const depthSlider = dressed(el("input"));
    depthSlider.type = "range";
    depthSlider.min = String(depth.lowUm);
    depthSlider.max = String(depth.highUm);
    depthSlider.step = String(depth.stepUm || 1);
    depthSlider.value = String(depth.atUm ?? depth.lowUm);
    const depthBox = el("span",
      `text-align:right;font-variant-numeric:tabular-nums;color:${INK.textPrimary};font-size:11px;`,
      `${Math.round(Number(depthSlider.value))} µm`);
    depthSlider.addEventListener("input", () => {
      viewer.setPlane?.(Number(depthSlider.value));
      depthBox.textContent = `${Math.round(Number(depthSlider.value))} µm`;
    });
    depthLine.append(depthSlider, depthBox);
    whole.append(depthLine);
    if (viewer.canShowVolume) {
      const volumeLine = el("label",
        "display:flex;align-items:center;gap:8px;cursor:pointer;padding:5px 12px;");
      const wants = el("input");
      wants.type = "checkbox";
      wants.style.cssText = "margin:0;";
      wants.addEventListener("change", () => viewer.showVolume?.(wants.checked));
      volumeLine.append(wants, el("span", "", "draw the stack as a volume"));
      whole.append(volumeLine);
    }
  }

  bar.append(data, settings, whole);
  if (plotHost) plotHost.after(panel);
  else (body ?? near)?.append(panel);
  /* Left where a test can reach it, the way the picture itself is. */
  window.__viewerPanel = panel;
  if (rows.length) chooseRow(0);
  return {
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
      const standing = viewer.layersForMeasurement?.();
      if (!standing) return;
      standing.forEach((row, at) => {
        const eye = eyes.get(at);
        if (!eye) return;
        const shown = row.visible !== false;
        if (rows[at]) rows[at].visible = shown;
        dressTheEye(eye, shown);
      });
    },
    destroy() {
      closeChooser();
      document.removeEventListener("pointerdown", closeChooser, true);
      panel.remove();
      if (window.__viewerPanel === panel) window.__viewerPanel = null;
    },
  };
}

/**
 * Draw an eye as open or closed, and say so to a reader who cannot see it.
 *
 * One place, used when a row is built and whenever the panel is brought back
 * into agreement with the picture, so an eye cannot say one thing while the
 * channel does another.
 */
function dressTheEye(eye, shown) {
  eye.replaceChildren(anEye(shown));
  eye.style.opacity = shown ? "1" : "0.4";
  eye.title = shown ? "Hide this channel" : "Show this channel";
  eye.setAttribute("aria-pressed", String(!shown));
}
