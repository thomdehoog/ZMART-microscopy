/**
 * The viewer's own controls, on the left: the acquisitions and their channels.
 *
 * The workflow's step panels keep the right-hand side; what the *picture*
 * offers — which acquisitions are open, which colours of light each recorded,
 * and an eye per channel — stands on the left, the same side the ZMART
 * viewer's own window puts it at this microscope.
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

/** One flat row list, matching the engine's own numbering. */
async function theRows(acquisitions) {
  const rows = [];
  for (const acquisition of acquisitions) {
    const described = (await theStoresDescription(acquisition.url))?.omero?.channels;
    const channels = Array.isArray(described) && described.length
      ? described.map((channel, at) => ({
        name: channel?.label || `channel ${at + 1}`,
        color: typeof channel?.color === "string" ? `#${channel.color}` : null,
      }))
      : [{ name: acquisition.name, color: null }];
    for (const channel of channels) rows.push({ ...channel, acquisition: acquisition.name });
  }
  return rows;
}

/**
 * Mount the panel into `host` and wire its eyes to `viewer.setChannel`.
 * Returns `{ destroy }`. `host` is the box the canvas hangs in; the panel
 * stands over its left edge and folds away to a sliver on its own button.
 */
export async function mountViewerPanel(host, { viewer, acquisitions, css }) {
  const rows = await theRows(acquisitions);

  const panel = document.createElement("div");
  panel.className = "viewer-panel";
  panel.style.cssText = [
    "position:absolute", "left:0", "top:0", "bottom:0", "z-index:6",
    "display:flex", "flex-direction:column", "gap:2px",
    "width:200px", "max-width:45%", "overflow-y:auto", "padding:8px",
    "font-size:12px", "box-sizing:border-box",
    `background:${css?.("--panel") || "rgba(20,24,28,0.85)"}`,
    "border-right:1px solid rgba(128,128,128,0.25)",
  ].join(";");

  const fold = document.createElement("button");
  fold.type = "button";
  fold.textContent = "◂ picture";
  fold.title = "fold the picture's controls away";
  fold.style.cssText = "align-self:flex-start;font-size:11px;margin-bottom:4px;";
  let folded = false;
  fold.addEventListener("click", () => {
    folded = !folded;
    fold.textContent = folded ? "▸" : "◂ picture";
    for (const child of panel.children) {
      if (child !== fold) child.hidden = folded;
    }
    panel.style.width = folded ? "auto" : "200px";
  });
  panel.append(fold);

  let heading = null;
  rows.forEach((row, index) => {
    if (row.acquisition !== heading) {
      heading = row.acquisition;
      const title = document.createElement("div");
      title.textContent = heading;
      title.style.cssText = "font-weight:600;margin-top:6px;opacity:0.9;";
      panel.append(title);
    }
    const line = document.createElement("label");
    line.style.cssText = "display:flex;align-items:center;gap:6px;cursor:pointer;";
    const eye = document.createElement("input");
    eye.type = "checkbox";
    eye.checked = true;
    eye.addEventListener("change", () => viewer.setChannel(index, { visible: eye.checked }));
    const swatch = document.createElement("span");
    swatch.style.cssText = [
      "display:inline-block", "width:10px", "height:10px", "border-radius:2px",
      `background:${row.color ?? "#cccccc"}`,
    ].join(";");
    const name = document.createElement("span");
    name.textContent = row.name;
    line.append(eye, swatch, name);
    panel.append(line);
  });

  host.append(panel);
  /* Left where a test can reach it, the way the picture itself is. */
  window.__viewerPanel = panel;
  return {
    destroy() {
      panel.remove();
      if (window.__viewerPanel === panel) window.__viewerPanel = null;
    },
  };
}
