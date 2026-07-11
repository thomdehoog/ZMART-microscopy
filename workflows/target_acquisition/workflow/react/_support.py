"""Shared plumbing for the React-based notebook widgets.

The React widgets are built on `anywidget <https://anywidget.dev>`_: each
widget is a small React app running in the browser cell, kept in sync with
Python through *traits* (shared state that either side can change) and
*messages* (small one-off packets either side sends). Python streams fresh
data by sending one message per new tile / point / image pair — the kernel
flushes those immediately, which is what makes the widgets update in real
time while the microscope works. The full picture also lives in a trait,
refreshed whenever a browser view asks for it (a ``sync`` message on
mount), so a re-opened notebook tab shows everything.

Why messages for streaming instead of growing a trait: a trait update
always resends the WHOLE value. Appending tile 25 to a trait list would
retransmit tiles 1–24 as well — megabytes per update, growing with the
square of the tile count — and that can stall the very channel the
operator is watching mid-run. One message per new item keeps the traffic
proportional to the data. (``workflow/react/PROTOCOL.md`` documents the
exact traits and messages of every widget, for embedding them outside
Jupyter later.)

Images travel as PNG data URLs. The React runtime itself is loaded from
the esm.sh CDN, so the *browser* needs internet access the first time a
widget renders (the kernel does not); when it cannot be loaded, the cell
shows a plain-language note pointing at the offline matplotlib notebook
instead of staying blank.
"""

from __future__ import annotations

import base64
import io
from typing import Any

# One hex colour per entry of the matplotlib viewer's CHANNEL_COLORS, in the
# same cycling order, so a channel wears the same colour in both notebooks.
CHANNEL_HEX = (
    "#ffffff",  # white
    "#00ff00",  # lime
    "#ff00ff",  # magenta
    "#00ffff",  # cyan
    "#ffff00",  # yellow
    "#ff0000",  # red
    "#0000ff",  # blue
)


def require_anywidget() -> None:
    """A friendly error when the optional anywidget dependency is missing."""
    try:
        import anywidget  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "the React widgets need the 'anywidget' package — install it with "
            "'pip install anywidget' (it is listed in environment.yml and "
            "requirements.txt), then restart the notebook kernel."
        ) from exc


def shrink_to_budget(array: Any, budget_px: int) -> Any:
    """Return ``array`` (2-D or RGB) strided down to at most ``budget_px`` pixels.

    Display copies travel to the browser as PNGs; a full-resolution
    2048x2048 image would make a single update megabytes. Striding keeps
    every n-th pixel — crude but honest (no smoothing that could invent
    detail), and the physical extent metadata stays exact.
    """
    import math

    h, w = array.shape[0], array.shape[1]
    step = max(1, math.ceil(math.sqrt(h * w / budget_px)))
    return array[::step, ::step] if step > 1 else array


def png_data_url(array: Any) -> str:
    """Encode an image array as a ``data:image/png`` URL for a trait.

    A 2-D array is shown grayscale, stretched over its own min..max (the
    same auto-scaling matplotlib's ``imshow`` applies); a float RGB array
    in 0..1 (the channel composite) is encoded as-is.
    """
    import numpy as np
    from PIL import Image

    arr = np.asarray(array)
    if arr.ndim == 2:
        lo, hi = float(arr.min()), float(arr.max())
        span = hi - lo if hi > lo else 1.0
        arr = ((arr.astype(np.float32) - lo) / span * 255.0).astype(np.uint8)
        image = Image.fromarray(arr, mode="L")
    else:
        image = Image.fromarray((np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8), mode="RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def heatmap_data_url(mesh: Any) -> str:
    """Encode a 2-D value grid as a viridis-coloured PNG data URL."""
    import numpy as np
    from matplotlib import colormaps

    mesh = np.asarray(mesh, dtype=float)
    lo, hi = float(mesh.min()), float(mesh.max())
    span = hi - lo if hi > lo else 1.0
    rgba = colormaps["viridis"]((mesh - lo) / span)
    return png_data_url(rgba[:, :, :3])


# JavaScript shared by every widget: React from the CDN (with a visible
# offline fallback), hooks that bind React state to anywidget traits and
# streamed messages, and the house style. Concatenated in front of each
# widget's own code to form its ESM module.
REACT_PRELUDE = """
// React comes from the CDN. Loading it dynamically (instead of a static
// import) means an offline browser gets a readable note in the cell
// below, not a silently blank widget.
let React = null, createRoot = null, loadError = null;
try {
  React = await import("https://esm.sh/react@18.3.1");
  ({ createRoot } = await import("https://esm.sh/react-dom@18.3.1/client"));
} catch (err) {
  loadError = err;
}
const h = React ? React.createElement : null;

// Bind a React state to an anywidget trait (either side can change it).
function useTrait(model, name) {
  const [value, setValue] = React.useState(model.get(name));
  React.useEffect(() => {
    const cb = () => setValue(model.get(name));
    model.on(`change:${name}`, cb);
    return () => model.off(`change:${name}`, cb);
  }, [model, name]);
  return [value, (v) => { model.set(name, v); model.save_changes(); }];
}

// Streamed lists: the trait holds the full snapshot (refreshed when we ask
// for a "sync"); one custom message per NEW item keeps mid-run traffic
// proportional to the data instead of resending everything already shown.
function useStream(model, traitName, messageType) {
  const [items, setItems] = React.useState(model.get(traitName) || []);
  React.useEffect(() => {
    const onTrait = () => setItems(model.get(traitName) || []);
    const onMsg = (msg) => {
      if (!msg || msg.type !== messageType) return;
      setItems((prev) => {
        const next = prev.slice();
        next[msg.index] = msg.entry;
        return next;
      });
    };
    model.on(`change:${traitName}`, onTrait);
    model.on("msg:custom", onMsg);
    model.send({ type: "sync" });  // a fresh view asks for the full picture
    return () => {
      model.off(`change:${traitName}`, onTrait);
      model.off("msg:custom", onMsg);
    };
  }, [model, traitName, messageType]);
  // Messages can arrive before the snapshot fills the gaps; skip the holes.
  return items.filter((it) => it !== undefined && it !== null);
}

// A number input that commits on blur or Enter — not on every keystroke,
// which would re-render (and retransmit) the whole widget mid-typing.
function NumBox({ value, onCommit, width = 52 }) {
  const [text, setText] = React.useState(String(value));
  React.useEffect(() => { setText(String(value)); }, [value]);
  const commit = () => {
    const v = parseFloat(text);
    if (Number.isFinite(v)) onCommit(v); else setText(String(value));
  };
  return h("input", { style: { ...inp, width }, value: text,
    onChange: (e) => setText(e.target.value),
    onBlur: commit,
    onKeyDown: (e) => { if (e.key === "Enter") { commit(); e.target.blur(); } } });
}

// React attaches wheel listeners passively, so e.preventDefault() inside a
// JSX onWheel cannot stop the page from scrolling. A native non-passive
// listener can.
function useWheel(ref, handler) {
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const cb = (e) => { e.preventDefault(); handler(e); };
    el.addEventListener("wheel", cb, { passive: false });
    return () => el.removeEventListener("wheel", cb);
  });
}

const T = {
  bg: "#0f172a", panel: "#1e293b", edge: "#334155", ink: "#e2e8f0",
  dim: "#94a3b8", accent: "#38bdf8", good: "#4ade80", bad: "#f87171",
};
const card = {
  background: T.panel, border: `1px solid ${T.edge}`, borderRadius: 12,
  padding: 12, color: T.ink,
  fontFamily: "system-ui, -apple-system, sans-serif", fontSize: 13,
};
const btn = (disabled) => ({
  background: disabled ? T.edge : T.accent, color: disabled ? T.dim : "#082f49",
  border: "none", borderRadius: 8, padding: "7px 16px", fontWeight: 600,
  cursor: disabled ? "default" : "pointer", transition: "all 0.15s",
});
const inp = {
  background: T.bg, color: T.ink, border: `1px solid ${T.edge}`,
  borderRadius: 6, padding: "4px 8px", width: 72,
};
const pill = (text) => h("span", {style: {
  background: T.bg, border: `1px solid ${T.edge}`, borderRadius: 999,
  padding: "3px 10px", color: T.dim, fontSize: 12 }}, text);

function mount(App) {
  return {
    render({ model, el }) {
      if (!React) {
        el.innerHTML = "";
        const note = document.createElement("div");
        note.style.cssText = "padding:12px;border:1px solid #b45309;" +
          "border-radius:10px;background:#78350f;color:#fef3c7;" +
          "font:13px system-ui;max-width:640px";
        note.textContent =
          "This widget could not load React from the internet (esm.sh). " +
          "The React notebook needs internet access IN THE BROWSER the " +
          "first time a widget renders. Working offline? Open " +
          "zmart_microscopy_v4.ipynb instead - the matplotlib edition of " +
          "the exact same workflow." + (loadError ? " (" + loadError + ")" : "");
        el.appendChild(note);
        return () => {};
      }
      const root = createRoot(el);
      root.render(h(App, { model }));
      return () => root.unmount();
    },
  };
}
"""
