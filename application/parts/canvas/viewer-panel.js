/**
 * The viewer's own controls: the acquisitions and their channels.
 *
 * A white column of its own, standing to the right of the canvas and to the
 * left of whatever step panel the workflow is showing — the same dress and
 * the same side the ZMART viewer's own window wears at this microscope. It
 * folds to a slim vertical bar on its own button, so the picture can have
 * the room back without losing the way in.
 *
 * The rows are read from each store's own description (the `omero` block the
 * run writers fill in), enumerated exactly the way the engine enumerates its
 * rows — one per channel, acquisitions in order — so the flat index handed to
 * `viewer.setChannel(index, …)` names the same row on both sides. A store
 * that describes nothing stands as one row named after its acquisition,
 * which is also what the engine draws for it.
 *
 * Deliberately lean: names, colours and eyes. The histogram, the windows and
 * the rest of the viewer's furniture can grow here once these are worth more
 * than they cost.
 */

/** The store's description, read where either generation of the format keeps
    it — the same two spellings the engine tries, unwrapped the same way. */
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

/** One flat row list, matching the engine's own numbering. Each row carries
    its acquisition's source address and its channel index within it, which
    is what the measuring server wants to hear. */
async function theRows(acquisitions) {
  const rows = [];
  for (const acquisition of acquisitions) {
    const described = (await theStoresDescription(acquisition.url))?.omero?.channels;
    const channels = Array.isArray(described) && described.length
      ? described.map((channel, at) => ({
        name: channel?.label || `channel ${at + 1}`,
        color: typeof channel?.color === "string" ? `#${channel.color}` : null,
        within: at,
      }))
      : [{ name: acquisition.name, color: null, within: 0 }];
    for (const channel of channels) {
      rows.push({ ...channel, acquisition: acquisition.name, source: acquisition.url });
    }
  }
  return rows;
}

/** Ask the viewer's server about one channel's brightness: the histogram and
    a window it would choose itself. `null` when it will not say. */
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

/**
 * Mount the panel and wire its eyes to `viewer.setChannel`. Returns
 * `{ destroy }`. `near` is any element inside the canvas's own box; the
 * panel stands as a flex column of the same row, directly to the canvas's
 * right, so the step panels keep their own side untouched.
 */
export async function mountViewerPanel(near, { viewer, acquisitions }) {
  const rows = await theRows(acquisitions);

  const body = near?.closest?.(".canvas-body");
  const plotHost = body?.querySelector(".plot-host");

  const panel = document.createElement("aside");
  panel.className = "viewer-panel";
  panel.style.cssText = [
    "flex:0 0 auto", "width:200px", "overflow-y:auto", "box-sizing:border-box",
    "display:flex", "flex-direction:column", "gap:2px", "padding:10px 12px",
    "background:#ffffff", "color:#1f2937", "font-size:12px",
    "border-left:1px solid #e5e7eb",
  ].join(";");

  const open = document.createElement("div");
  open.style.cssText = "display:flex;flex-direction:column;gap:2px;";

  const fold = document.createElement("button");
  fold.type = "button";
  fold.textContent = "◂";
  fold.title = "fold the picture's controls away";
  fold.style.cssText = [
    "align-self:flex-end", "border:1px solid #e5e7eb", "background:#ffffff",
    "color:#6b7280", "border-radius:4px", "cursor:pointer", "font-size:11px",
    "padding:1px 6px", "margin-bottom:4px",
  ].join(";");
  let folded = false;
  fold.addEventListener("click", () => {
    folded = !folded;
    /* The display is set directly, not through `hidden`: the box carries an
       inline `display:flex`, which wins over the attribute's own none. */
    open.style.display = folded ? "none" : "flex";
    fold.textContent = folded ? "▸" : "◂";
    fold.title = folded ? "open the picture's controls" : "fold the picture's controls away";
    /* Folded, the panel is a slim vertical bar: the way back in, and no
       more. The engine notices the canvas's new size through its own
       resize watcher. */
    panel.style.width = folded ? "26px" : "200px";
    panel.style.padding = folded ? "6px 2px" : "10px 12px";
    fold.style.alignSelf = folded ? "center" : "flex-end";
  });
  panel.append(fold, open);

  /* -- display settings: one set of controls, for the channel picked out
     below, the way the viewer's own window arranges it. The histogram and
     the starting window come from the viewer's server, measured from the
     pixels themselves. -- */
  const settings = document.createElement("div");
  settings.style.cssText = "display:flex;flex-direction:column;gap:4px;margin-bottom:4px;";
  const settingsTitle = document.createElement("div");
  settingsTitle.textContent = "display settings";
  settingsTitle.style.cssText = [
    "font-weight:600", "font-size:11px", "letter-spacing:0.04em",
    "text-transform:uppercase", "color:#6b7280",
  ].join(";");
  const chosenName = document.createElement("div");
  chosenName.style.cssText = "font-size:11px;color:#9ca3af;";
  chosenName.textContent = "pick a channel below";
  const plot = document.createElement("canvas");
  plot.width = 176; plot.height = 54;
  plot.style.cssText = "width:176px;height:54px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:3px;";
  const blackSlider = document.createElement("input");
  const whiteSlider = document.createElement("input");
  for (const slider of [blackSlider, whiteSlider]) {
    slider.type = "range";
    slider.disabled = true;
    slider.style.cssText = "width:176px;margin:0;";
  }
  const sliderNote = document.createElement("div");
  sliderNote.style.cssText = "font-size:10px;color:#9ca3af;display:flex;justify-content:space-between;width:176px;";
  settings.append(settingsTitle, chosenName, plot, blackSlider, whiteSlider, sliderNote);

  let chosen = null;           // the flat row index being adjusted
  let shape = null;            // the chosen channel's measured histogram

  function drawTheHistogram() {
    const paint = plot.getContext("2d");
    paint.clearRect(0, 0, plot.width, plot.height);
    if (!shape) return;
    const counts = shape.counts ?? [];
    const most = Math.max(1, ...counts);
    const wide = plot.width / Math.max(1, counts.length);
    /* The chosen window shaded behind the bars, so the sliders can be read
       against the distribution they are cutting. */
    const span = shape.high - shape.low || 1;
    const x0 = ((Number(blackSlider.value) - shape.low) / span) * plot.width;
    const x1 = ((Number(whiteSlider.value) - shape.low) / span) * plot.width;
    paint.fillStyle = "#e0ecff";
    paint.fillRect(x0, 0, Math.max(1, x1 - x0), plot.height);
    paint.fillStyle = "#6b7280";
    counts.forEach((count, at) => {
      const h = (Math.log1p(count) / Math.log1p(most)) * (plot.height - 2);
      paint.fillRect(at * wide, plot.height - h, Math.max(1, wide - 0.5), h);
    });
  }

  function applyTheWindow() {
    if (chosen === null) return;
    let low = Number(blackSlider.value);
    let high = Number(whiteSlider.value);
    if (high <= low) { high = low + 1; whiteSlider.value = String(high); }
    viewer.setChannel(chosen, { window: { low, high } });
    sliderNote.textContent = "";
    sliderNote.append(
      Object.assign(document.createElement("span"), { textContent: Math.round(low) }),
      Object.assign(document.createElement("span"), { textContent: Math.round(high) }),
    );
    drawTheHistogram();
  }
  blackSlider.addEventListener("input", applyTheWindow);
  whiteSlider.addEventListener("input", applyTheWindow);

  async function chooseRow(index, row, line) {
    chosen = index;
    chosenName.textContent = `${row.acquisition} · ${row.name}`;
    for (const other of open.querySelectorAll("[data-channel-row]")) {
      other.style.background = "";
    }
    line.style.background = "#eff6ff";
    shape = null;
    drawTheHistogram();
    const answer = await measured(row);
    if (chosen !== index) return;
    if (!answer) { chosenName.textContent += " · could not be measured"; return; }
    shape = answer.histogram;
    for (const slider of [blackSlider, whiteSlider]) {
      slider.min = String(Math.floor(shape.low));
      slider.max = String(Math.ceil(shape.high));
      slider.step = "1";
      slider.disabled = false;
    }
    const first = answer.window ?? shape.autoWindow ?? { low: shape.low, high: shape.high };
    blackSlider.value = String(Math.floor(first.low));
    whiteSlider.value = String(Math.ceil(first.high));
    applyTheWindow();
  }

  open.append(settings);

  let heading = null;
  rows.forEach((row, index) => {
    if (row.acquisition !== heading) {
      heading = row.acquisition;
      const title = document.createElement("div");
      title.textContent = heading;
      title.style.cssText = [
        "font-weight:600", "font-size:11px", "letter-spacing:0.04em",
        "text-transform:uppercase", "color:#6b7280", "margin:8px 0 2px",
      ].join(";");
      open.append(title);
    }
    const line = document.createElement("div");
    line.dataset.channelRow = "1";
    line.style.cssText =
      "display:flex;align-items:center;gap:7px;cursor:pointer;padding:2px 4px;border-radius:3px;";
    const eye = document.createElement("input");
    eye.type = "checkbox";
    eye.checked = true;
    eye.style.cssText = "margin:0;";
    eye.addEventListener("click", (press) => press.stopPropagation());
    eye.addEventListener("change", () => viewer.setChannel(index, { visible: eye.checked }));
    /* The colour is the operator's to change, the way the viewer offers it. */
    const swatch = document.createElement("input");
    swatch.type = "color";
    swatch.value = row.color ?? "#ffffff";
    swatch.style.cssText = [
      "width:16px", "height:16px", "padding:0", "border:1px solid #d1d5db",
      "border-radius:3px", "background:none", "cursor:pointer",
    ].join(";");
    swatch.addEventListener("click", (press) => press.stopPropagation());
    swatch.addEventListener("input", () => {
      const hex = swatch.value.replace("#", "");
      viewer.setChannel(index, {
        colour: [0, 2, 4].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255),
      });
    });
    const name = document.createElement("span");
    name.textContent = row.name;
    /* A press on the row picks the channel out for the display settings
       above — one set of controls, adjusted one channel at a time. */
    line.addEventListener("click", () => chooseRow(index, row, line));
    line.append(eye, swatch, name);
    open.append(line);
  });

  /* -- what the picture as a whole offers: the master switch, the stack's
     depth, and the volume, each only when the engine says it is there. -- */
  const pictureRow = document.createElement("label");
  pictureRow.style.cssText =
    "display:flex;align-items:center;gap:7px;cursor:pointer;padding:6px 4px 2px;margin-top:6px;border-top:1px solid #e5e7eb;";
  const pictureEye = document.createElement("input");
  pictureEye.type = "checkbox";
  pictureEye.checked = true;
  pictureEye.style.cssText = "margin:0;";
  pictureEye.addEventListener("change", () => viewer.showPicture?.(pictureEye.checked));
  pictureRow.append(pictureEye, Object.assign(document.createElement("span"), {
    textContent: "picture",
  }));
  open.append(pictureRow);

  const depth = viewer.theDepthItCanShow?.();
  if (depth && depth.highUm > depth.lowUm) {
    const depthTitle = document.createElement("div");
    depthTitle.textContent = "depth (z)";
    depthTitle.style.cssText =
      "font-weight:600;font-size:11px;letter-spacing:0.04em;text-transform:uppercase;color:#6b7280;margin:8px 0 2px;";
    const depthSlider = document.createElement("input");
    depthSlider.type = "range";
    depthSlider.min = String(depth.lowUm);
    depthSlider.max = String(depth.highUm);
    depthSlider.step = String(depth.stepUm || 1);
    depthSlider.value = String(depth.atUm ?? depth.lowUm);
    depthSlider.style.cssText = "width:176px;margin:0;";
    const depthNote = document.createElement("div");
    depthNote.style.cssText = "font-size:10px;color:#9ca3af;";
    depthNote.textContent = `${Math.round(Number(depthSlider.value))} µm`;
    depthSlider.addEventListener("input", () => {
      viewer.setPlane?.(Number(depthSlider.value));
      depthNote.textContent = `${Math.round(Number(depthSlider.value))} µm`;
    });
    open.append(depthTitle, depthSlider, depthNote);

    if (viewer.canShowVolume) {
      const volume = document.createElement("label");
      volume.style.cssText = "display:flex;align-items:center;gap:7px;cursor:pointer;padding:2px 4px;";
      const wants = document.createElement("input");
      wants.type = "checkbox";
      wants.style.cssText = "margin:0;";
      wants.addEventListener("change", () => viewer.showVolume?.(wants.checked));
      volume.append(wants, Object.assign(document.createElement("span"), {
        textContent: "draw the stack as a volume",
      }));
      open.append(volume);
    }
  }
  /* The first channel starts picked out, so the histogram is not an empty
     box waiting for a click nobody was told to make. */
  const firstLine = open.querySelector("[data-channel-row]");
  if (rows.length && firstLine) chooseRow(0, rows[0], firstLine);

  if (plotHost) plotHost.after(panel);
  else (body ?? near)?.append(panel);
  /* Left where a test can reach it, the way the picture itself is. */
  window.__viewerPanel = panel;
  return {
    destroy() {
      panel.remove();
      if (window.__viewerPanel === panel) window.__viewerPanel = null;
    },
  };
}
