/**
 * The grey channel's box: one histogram over the sum of an acquisition's
 * channels, one window, one opacity, Auto and Log.
 *
 * While the picture is grey an acquisition is one channel to the operator,
 * whatever the engine does underneath: this box moves every channel in
 * proportion to how it stood in colour. It is small on purpose -- the
 * colour channels' own boxes keep their histograms for the fine work.
 */

const BARS = 64;

export function mountGreyBox(host, { panel, acquisition, changed }) {
  host.replaceChildren();
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const head = el("div", "grey-box-head");
  head.append(el("span", "grey-box-title", acquisition), el("span", "grey-box-sub", "one grey channel"));
  const plot = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  plot.setAttribute("class", "grey-box-plot");
  plot.setAttribute("preserveAspectRatio", "none");
  plot.setAttribute("viewBox", `0 0 ${BARS} 24`);
  plot.setAttribute("role", "img");
  plot.setAttribute("aria-label", `histogram of the grey ${acquisition}`);
  const row = (label, min, max, step) => {
    const line = el("label", "grey-box-row");
    line.append(el("span", "grey-box-label", label));
    const slider = el("input", "zv-range");
    slider.type = "range"; slider.min = min; slider.max = max; slider.step = step;
    slider.setAttribute("aria-label", `${label} of the grey ${acquisition}`);
    const value = el("output", "grey-box-value");
    line.append(slider, value);
    return { line, slider, value };
  };
  const lowRow = row("min", "0", "100", "1");
  const highRow = row("max", "0", "100", "1");
  const opacityRow = row("opacity", "0", "100", "1");
  const buttons = el("div", "grey-box-buttons");
  const auto = el("button", "grey-box-button", "Auto");
  auto.type = "button"; auto.title = "Window every channel off the picture, then show the whole sum";
  const log = el("button", "grey-box-button", "Log");
  log.type = "button"; log.setAttribute("aria-pressed", "false");
  buttons.append(auto, log);
  host.append(head, plot, buttons, lowRow.line, highRow.line, opacityRow.line);

  const fill = (slider) => {
    const low = Number(slider.min), high = Number(slider.max);
    slider.style.setProperty("--fill", `${((Number(slider.value) - low) / (high - low || 1)) * 100}%`);
  };

  function refresh() {
    const state = panel.composite?.(acquisition);
    if (!state) { host.hidden = true; return; }
    host.hidden = false;
    while (plot.firstChild) plot.firstChild.remove();
    const peak = Math.max(...state.counts, 1e-9);
    state.counts.forEach((count, i) => {
      const share = state.log ? Math.log1p(count * 1e4) / Math.log1p(peak * 1e4) : count / peak;
      const bar = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      const f = (i + 0.5) / BARS;
      bar.setAttribute("x", i); bar.setAttribute("y", 24 - share * 22);
      bar.setAttribute("width", 1); bar.setAttribute("height", share * 22);
      bar.setAttribute("fill", "currentColor");
      bar.setAttribute("opacity", f >= state.a && f <= state.b ? "1" : "0.25");
      plot.append(bar);
    });
    for (const edge of [state.a, state.b]) {
      const line = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      line.setAttribute("x", edge * BARS - 0.4); line.setAttribute("y", 0);
      line.setAttribute("width", 0.8); line.setAttribute("height", 24);
      line.setAttribute("fill", "#0284c7");
      plot.append(line);
    }
    if (document.activeElement !== lowRow.slider) lowRow.slider.value = String(Math.round(state.a * 100));
    if (document.activeElement !== highRow.slider) highRow.slider.value = String(Math.round(state.b * 100));
    if (document.activeElement !== opacityRow.slider) opacityRow.slider.value = String(Math.round(state.s * 100));
    lowRow.value.textContent = `${Math.round(state.a * 100)} %`;
    highRow.value.textContent = `${Math.round(state.b * 100)} %`;
    opacityRow.value.textContent = `${Math.round(state.s * 100)} %`;
    for (const { slider } of [lowRow, highRow, opacityRow]) fill(slider);
    log.setAttribute("aria-pressed", String(Boolean(state.log)));
    head.lastChild.textContent = state.measured
      ? `one grey channel, the sum of ${state.channels}`
      : `one grey channel, the sum of ${state.channels}; press Auto to measure`;
  }

  lowRow.slider.addEventListener("input", () => {
    const a = Number(lowRow.slider.value) / 100;
    const state = panel.composite?.(acquisition);
    panel.setComposite?.(acquisition, { a, b: Math.max(state?.b ?? 1, a + 0.02) });
    refresh(); changed?.();
  });
  highRow.slider.addEventListener("input", () => {
    const b = Number(highRow.slider.value) / 100;
    const state = panel.composite?.(acquisition);
    panel.setComposite?.(acquisition, { b, a: Math.min(state?.a ?? 0, b - 0.02) });
    refresh(); changed?.();
  });
  opacityRow.slider.addEventListener("input", () => {
    panel.setComposite?.(acquisition, { s: Number(opacityRow.slider.value) / 100 });
    refresh(); changed?.();
  });
  auto.addEventListener("click", async () => {
    auto.disabled = true;
    try { await panel.autoComposite?.(acquisition); } finally { auto.disabled = false; }
    refresh(); changed?.();
  });
  log.addEventListener("click", () => {
    const state = panel.composite?.(acquisition);
    panel.setComposite?.(acquisition, { log: !state?.log });
    refresh();
  });
  refresh();
  return { refresh };
}
