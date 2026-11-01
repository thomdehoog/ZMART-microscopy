/**
 * The box under the canvas row for one channel: a histogram, the window's
 * edges on it, Auto and Log, and three sliders -- min, max and opacity --
 * each with a box to type into.
 *
 * The same box serves two kinds of channel. A colour channel of an
 * acquisition, whose head is an eye, a colour swatch and the channel's
 * name; and the one grey channel an acquisition becomes when the picture
 * is drawn in grey, whose head is the acquisition's name. What differs is
 * handed in as a small "model": where the numbers come from and where a
 * change goes. The box itself only draws and listens.
 *
 * On the histogram: the wheel zooms round the pointer, a drag on empty
 * ground pans, a drag on a window edge moves that edge, and a double click
 * shows the whole range again.
 */

/** A stretch of stored counts, from `low` to `high`. */
export interface Span {
  low: number;
  high: number;
}

/** What the box shows of its channel. */
export interface BoxState {
  /** A colour channel's own: whether shown, its colour as drawn and as `#rrggbb`, and its name. */
  visible?: boolean;
  color?: string | null;
  hex?: string | null;
  name?: string;
  /** The grey channel's heading. */
  title?: string;
  axis: Span;
  window: Span;
  weight: number;
  gamma?: number;
  saturate?: number;
  log?: boolean;
  counts?: number[];
  range?: Span | null;
}

/** Where the numbers come from and where a change goes: one channel, as the box is handed it. */
export interface ChannelModel {
  kind: "colour" | "grey";
  label: string;
  unit?: string;
  state(): BoxState | null;
  setVisible?(visible: boolean): void;
  setColour?(hex: string): void;
  setWindow(window: Span): void;
  setAxis(axis: Span | null): void;
  setWeight(weight: number): void;
  setGamma?(gamma: number): void;
  setSaturate?(percent: number): void;
  setLog(on: boolean): void;
  auto(): unknown;
  changed?(): void;
}

export function mountChannelBox(host: HTMLElement, model: ChannelModel): { refresh(): void } {
  host.replaceChildren();
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, className?: string | null, text?: string) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const unit = model.unit ?? "";
  const shown = (value: number) => `${Math.round(value)}${unit}`;
  /* A number typed into a box, with or without its unit; null if it is not
     a number at all. */
  const typed = (box: HTMLInputElement) => {
    const n = Number(String(box.value).replace(unit || "\0", "").replace("%", "").trim());
    return Number.isFinite(n) ? n : null;
  };
  const valueBox = (label: string) => {
    const box = el("input", "canvas-box-value");
    box.type = "text"; box.inputMode = "numeric";
    box.setAttribute("aria-label", label);
    /* Enter takes the number and lets the box go, so it shows the value the
       way it does when nobody is typing in it. */
    box.addEventListener("keydown", (event) => { if (event.key === "Enter") box.blur(); });
    return box;
  };

  /* ---- the head ---- */
  const head = el("div", "canvas-box-head");
  let eye: HTMLButtonElement | null = null, swatch: HTMLLabelElement | null = null;
  let picker: HTMLInputElement | null = null, name: HTMLSpanElement | null = null, title: HTMLSpanElement | null = null;
  if (model.kind === "colour") {
    eye = el("button", "canvas-box-eye");
    eye.type = "button";
    eye.setAttribute("aria-label", `show or hide ${model.label}`);
    eye.title = "Show or hide this channel";
    eye.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z"/><circle cx="8" cy="8" r="2"/><path class="canvas-box-eye-slash" d="M3 13L13 3"/></svg>';
    eye.addEventListener("click", () => { model.setVisible?.(!(model.state()?.visible)); refresh(); model.changed?.(); });
    swatch = el("label", "canvas-box-swatch");
    swatch.title = "Choose this channel's colour";
    const chooser = el("input");
    picker = chooser;
    chooser.type = "color";
    chooser.setAttribute("aria-label", `choose a colour for ${model.label}`);
    chooser.addEventListener("input", () => { model.setColour?.(chooser.value); refresh(); model.changed?.(); });
    swatch.append(chooser);
    name = el("span", "canvas-box-name");
    head.append(eye, swatch, name);
  } else {
    title = el("span", "canvas-box-title");
    head.append(title);
  }

  /* ---- the histogram ---- */
  const plot = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  plot.setAttribute("class", "canvas-box-plot");
  plot.setAttribute("preserveAspectRatio", "none");
  plot.setAttribute("role", "img");
  plot.setAttribute("aria-label", `histogram of ${model.label}`);
  plot.style.cursor = "grab";

  /* ---- under it: the axis's ends, Auto and Log between them ---- */
  const axisRow = el("div", "canvas-box-axis");
  const axisFrom = valueBox(`axis from ${model.label}`);
  const axisTo = valueBox(`axis to ${model.label}`);
  const buttons = el("div", "canvas-box-buttons");
  const auto = el("button", "canvas-box-button", "Auto");
  auto.type = "button";
  auto.title = model.kind === "colour"
    ? "Measure the picture and window this channel to it"
    : "Window every channel off the picture, then show the whole sum";
  const log = el("button", "canvas-box-button", "Log");
  log.type = "button"; log.setAttribute("aria-pressed", "false");
  log.title = "Count the pixels on a logarithmic scale, so faint bars show";
  /* How much Auto saturates, beside it: a colour channel's own number. */
  let saturate: HTMLInputElement | null = null;
  if (model.kind === "colour" && model.setSaturate) {
    saturate = valueBox(`percent ${model.label} saturates`);
    saturate.classList.add("canvas-box-saturate");
    saturate.title = "Percent of pixels Auto saturates at each end";
    buttons.append(auto, saturate, log);
  } else {
    buttons.append(auto, log);
  }
  axisRow.append(axisFrom, buttons, axisTo);

  /* ---- the three sliders ---- */
  const row = (label: string) => {
    const line = el("label", "canvas-box-row");
    line.append(el("span", "canvas-box-label", label));
    const slider = el("input", "zv-range");
    slider.type = "range"; slider.step = "1";
    slider.setAttribute("aria-label", `${label} of ${model.label}`);
    const value = valueBox(`${label} value of ${model.label}`);
    line.append(slider, value);
    return { line, slider, value };
  };
  const lowRow = row("min");
  const highRow = row("max");
  const opacityRow = row("opacity");
  opacityRow.slider.min = "0"; opacityRow.slider.max = "100";
  /* gamma bends the curve between the window's ends; in hundredths, since
     the slider counts whole numbers. */
  const gammaRow = row("gamma");
  gammaRow.slider.min = "10"; gammaRow.slider.max = "400";
  host.append(head, plot, axisRow, lowRow.line, highRow.line, opacityRow.line, gammaRow.line);

  const fill = (slider: HTMLInputElement) => {
    const low = Number(slider.min), high = Number(slider.max);
    slider.style.setProperty("--fill", `${((Number(slider.value) - low) / (high - low || 1)) * 100}%`);
  };

  /* ---- drawing ---- */
  let last: BoxState | null = null;
  function refresh() {
    const state = model.state();
    last = state;
    if (!state) { host.hidden = true; return; }
    host.hidden = false;
    /* Built for the kind of channel this is, above. */
    if (model.kind === "colour") {
      eye!.setAttribute("aria-pressed", String(state.visible));
      swatch!.style.background = state.color ?? "#888";
      if (document.activeElement !== picker && state.hex) picker!.value = state.hex;
      name!.textContent = state.name ?? "";
    } else {
      title!.textContent = state.title ?? "";
    }
    drawTheHistogram(state);
    const axis = state.axis;
    for (const { slider } of [lowRow, highRow]) {
      slider.min = String(Math.floor(axis.low));
      slider.max = String(Math.ceil(axis.high));
    }
    if (document.activeElement !== lowRow.slider) lowRow.slider.value = String(state.window.low);
    if (document.activeElement !== highRow.slider) highRow.slider.value = String(state.window.high);
    if (document.activeElement !== opacityRow.slider) opacityRow.slider.value = String(Math.round(state.weight * 100));
    const gamma = state.gamma !== undefined && Number.isFinite(state.gamma) ? state.gamma : 1;
    if (document.activeElement !== gammaRow.slider) gammaRow.slider.value = String(Math.round(gamma * 100));
    const said: [HTMLInputElement, string][] = [
      [axisFrom, shown(axis.low)], [axisTo, shown(axis.high)],
      [lowRow.value, shown(state.window.low)], [highRow.value, shown(state.window.high)],
      [opacityRow.value, `${Math.round(state.weight * 100)}%`],
      [gammaRow.value, gamma.toFixed(2)],
      ...(saturate ? [[saturate, `${state.saturate ?? 1}%`] as [HTMLInputElement, string]] : []),
    ];
    for (const [box, value] of said) {
      if (document.activeElement !== box) box.value = value;
    }
    for (const { slider } of [lowRow, highRow, opacityRow, gammaRow]) fill(slider);
    log.setAttribute("aria-pressed", String(Boolean(state.log)));
  }

  /* Bars over the histogram's own range; the axis on view is the plot's
     viewBox, so zooming and panning never redraw the bars. */
  const binsOf = (state: BoxState) => Math.max(state.counts?.length ?? 0, 1);
  const xOf = (state: BoxState, value: number) => {
    const range = state.range;
    if (!range || range.high <= range.low) return 0;
    return ((value - range.low) / (range.high - range.low)) * binsOf(state);
  };
  function drawTheHistogram(state: BoxState) {
    while (plot.firstChild) plot.firstChild.remove();
    const counts = state.counts ?? [];
    const from = xOf(state, state.axis.low), to = xOf(state, state.axis.high);
    const width = Math.max(to - from, 1e-6);
    plot.setAttribute("viewBox", `${from} 0 ${width} 24`);
    const range = state.range;
    if (!range || !counts.length) return;
    const peak = Math.max(...counts, 1e-9);
    const bins = counts.length;
    const span = range.high - range.low;
    counts.forEach((count, i) => {
      const share = state.log ? Math.log1p(count * 1e4) / Math.log1p(peak * 1e4) : count / peak;
      const middle = range.low + ((i + 0.5) * span) / bins;
      const inside = middle >= state.window.low && middle <= state.window.high;
      const bar = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      bar.setAttribute("x", String(i)); bar.setAttribute("y", String(24 - share * 22));
      bar.setAttribute("width", "1"); bar.setAttribute("height", String(share * 22));
      bar.setAttribute("fill", "currentColor");
      bar.setAttribute("opacity", inside ? "1" : "0.25");
      plot.append(bar);
    });
    const edgeWidth = width * 0.012;
    for (const edge of [state.window.low, state.window.high]) {
      const line = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      line.setAttribute("x", String(xOf(state, edge) - edgeWidth / 2)); line.setAttribute("y", "0");
      line.setAttribute("width", String(edgeWidth)); line.setAttribute("height", "24");
      line.setAttribute("fill", "#0284c7");
      plot.append(line);
    }
  }

  /* ---- the histogram's handles ---- */
  /* Asked only while there is a state: every handle below returns first when there is none. */
  const valueUnder = (event: MouseEvent, shows: BoxState) => {
    const face = plot.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (event.clientX - face.left) / (face.width || 1)));
    return shows.axis.low + f * (shows.axis.high - shows.axis.low);
  };
  const edgeUnder = (event: MouseEvent): "low" | "high" | null => {
    const shows = last;
    if (!shows) return null;
    const face = plot.getBoundingClientRect();
    const px = (value: number) => face.left + ((value - shows.axis.low) / (shows.axis.high - shows.axis.low || 1)) * face.width;
    if (Math.abs(event.clientX - px(shows.window.low)) <= 6) return "low";
    if (Math.abs(event.clientX - px(shows.window.high)) <= 6) return "high";
    return null;
  };
  const takeWindow = (next: Span) => { model.setWindow(next); refresh(); model.changed?.(); };
  const takeAxis = (next: Span | null) => { model.setAxis(next); refresh(); };
  let held: { edge: "low" | "high" } | { panFrom: number; axisWas: Span } | null = null;
  plot.addEventListener("pointerdown", (event) => {
    if (!last) return;
    const edge = edgeUnder(event);
    held = edge ? { edge } : { panFrom: event.clientX, axisWas: { ...last.axis } };
    plot.setPointerCapture(event.pointerId);
    plot.style.cursor = edge ? "ew-resize" : "grabbing";
  });
  plot.addEventListener("pointermove", (event) => {
    if (!last) return;
    if (!held) { plot.style.cursor = edgeUnder(event) ? "ew-resize" : "grab"; return; }
    const value = valueUnder(event, last);
    if ("edge" in held && held.edge === "low") { takeWindow({ low: Math.min(value, last.window.high - 1), high: last.window.high }); return; }
    if ("edge" in held) { takeWindow({ low: last.window.low, high: Math.max(value, last.window.low + 1) }); return; }
    const face = plot.getBoundingClientRect();
    const width = held.axisWas.high - held.axisWas.low;
    const moved = ((held.panFrom - event.clientX) / (face.width || 1)) * width;
    takeAxis({ low: held.axisWas.low + moved, high: held.axisWas.high + moved });
  });
  for (const done of ["pointerup", "pointercancel"]) {
    plot.addEventListener(done, () => { held = null; plot.style.cursor = "grab"; });
  }
  plot.addEventListener("dblclick", () => takeAxis(null));
  plot.addEventListener("wheel", (event) => {
    if (!last) return;
    event.preventDefault();
    const anchor = valueUnder(event, last);
    const factor = Math.exp(event.deltaY * 0.002);
    takeAxis({ low: anchor - (anchor - last.axis.low) * factor, high: anchor + (last.axis.high - anchor) * factor });
  }, { passive: false });

  /* ---- the boxes and sliders ---- */
  axisFrom.addEventListener("change", () => {
    const v = typed(axisFrom);
    if (v !== null && last) takeAxis({ low: v, high: Math.max(last.axis.high, v + 1) }); else refresh();
  });
  axisTo.addEventListener("change", () => {
    const v = typed(axisTo);
    if (v !== null && last) takeAxis({ low: Math.min(last.axis.low, v - 1), high: v }); else refresh();
  });
  /* The sliders stand only on a box with a state, so `last` is there by the time one moves. */
  lowRow.slider.addEventListener("input", () => {
    const low = Number(lowRow.slider.value);
    takeWindow({ low, high: Math.max(last!.window.high, low + 1) });
  });
  highRow.slider.addEventListener("input", () => {
    const high = Number(highRow.slider.value);
    takeWindow({ low: Math.min(last!.window.low, high - 1), high });
  });
  lowRow.value.addEventListener("change", () => {
    const low = typed(lowRow.value);
    if (low !== null && last) takeWindow({ low, high: Math.max(last.window.high, low + 1) }); else refresh();
  });
  highRow.value.addEventListener("change", () => {
    const high = typed(highRow.value);
    if (high !== null && last) takeWindow({ low: Math.min(last.window.low, high - 1), high }); else refresh();
  });
  const takeWeight = (percent: number) => {
    model.setWeight(Math.max(0, Math.min(100, percent)) / 100);
    refresh(); model.changed?.();
  };
  opacityRow.slider.addEventListener("input", () => takeWeight(Number(opacityRow.slider.value)));
  opacityRow.value.addEventListener("change", () => {
    const v = typed(opacityRow.value);
    if (v !== null) takeWeight(v); else refresh();
  });
  const takeGamma = (gamma: number) => {
    if (!Number.isFinite(gamma) || gamma <= 0) { refresh(); return; }
    model.setGamma?.(Math.max(0.1, Math.min(4, gamma)));
    refresh(); model.changed?.();
  };
  gammaRow.slider.addEventListener("input", () => takeGamma(Number(gammaRow.slider.value) / 100));
  gammaRow.value.addEventListener("change", () => takeGamma(Number(gammaRow.value.value)));
  saturate?.addEventListener("change", () => {
    const v = typed(saturate!);
    if (v !== null) model.setSaturate?.(v); refresh();
  });
  auto.addEventListener("click", async () => {
    auto.disabled = true;
    try { await model.auto(); } finally { auto.disabled = false; }
    refresh(); model.changed?.();
  });
  log.addEventListener("click", () => { model.setLog(!last?.log); refresh(); });

  refresh();
  return { refresh };
}
