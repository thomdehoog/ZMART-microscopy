"""Shared plumbing for the React-based notebook widgets.

The React widgets are built on `anywidget <https://anywidget.dev>`_: each
widget is a small React app running in the browser cell, kept in sync with
Python through *traits* (named values either side can change) and
*messages* (small one-off packets either side sends). Python streams fresh
data by sending one message per new tile / point / image pair — the kernel
flushes those immediately, which is what makes the widgets update in real
time while the microscope works. Metadata lives in a trait; whenever a
browser view asks for the full picture (a ``sync`` message on mount), Python
replays the images as bounded binary messages so a re-opened tab catches up
without one enormous base64 trait.

Why messages for streaming instead of growing a trait: a trait update
always resends the WHOLE value. Appending tile 25 to a trait list would
retransmit tiles 1–24 as well — megabytes per update, growing with the
square of the tile count — and that can stall the very channel the
operator is watching mid-run. One message per new item keeps the traffic
proportional to the data, and the image pixels ride along as a *binary
buffer* (raw PNG bytes) rather than base64 text — about a quarter smaller
on the wire, with no encode/decode work on either side.
(``workflow/react/PROTOCOL.md`` documents the exact traits and messages of
every widget, for embedding them outside Jupyter later.)

React itself is **vendored**: the official MIT-licensed production builds
of react and react-dom 18.3.1 ship inside this package (``vendor/``) and
are evaluated into a private scope in the browser — no CDN, no internet
requirement, no third-party code fetched into a page whose buttons drive a
real microscope, and no clash with the notebook front end's own React.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
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

# A colour-vision-friendly alternative (after Okabe & Ito): these hues stay
# distinguishable with the common forms of colour blindness. Pass
# ``palette="colorblind"`` to the React overview viewer to use it.
CHANNEL_HEX_COLORBLIND = (
    "#ffffff",  # white
    "#e69f00",  # orange
    "#56b4e9",  # sky blue
    "#009e73",  # bluish green
    "#f0e442",  # yellow
    "#d55e00",  # vermillion
    "#cc79a7",  # reddish purple
)

_VENDOR = Path(__file__).resolve().parent / "vendor"


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


def png_bytes(array: Any) -> bytes:
    """Encode an image array as raw PNG bytes (for a binary message buffer).

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
    return buffer.getvalue()


def png_to_data_url(png: bytes) -> str:
    """Wrap raw PNG bytes as a ``data:image/png`` URL for small trait images."""
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def png_data_url_ranged(array: Any, display_range: tuple[float, float] | None) -> str:
    """Encode a 2-D crop using a FIXED display window instead of min..max.

    Auto-stretching every crop over its own min..max makes the same cell
    look wildly different from one panel to the next. Passing the viewer's
    channel display window keeps every view of a cell consistent with the
    map it was cut from. ``None`` (or a degenerate window) falls back to
    the min..max stretch.
    """
    import numpy as np

    arr = np.asarray(array)
    if display_range is None or arr.ndim != 2:
        return png_data_url(arr)
    lo, hi = float(display_range[0]), float(display_range[1])
    if not (hi > lo):
        return png_data_url(arr)
    scaled = np.clip((arr.astype(np.float32) - lo) / (hi - lo), 0.0, 1.0)
    from PIL import Image

    image = Image.fromarray((scaled * 255.0).astype(np.uint8), mode="L")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return png_to_data_url(buffer.getvalue())


def png_data_url(array: Any) -> str:
    """Encode an image array straight to a ``data:image/png`` URL."""
    return png_to_data_url(png_bytes(array))


def heatmap_data_url(mesh: Any) -> str:
    """Encode a 2-D value grid as a viridis-coloured PNG data URL."""
    import numpy as np
    from matplotlib import colormaps

    mesh = np.asarray(mesh, dtype=float)
    lo, hi = float(mesh.min()), float(mesh.max())
    span = hi - lo if hi > lo else 1.0
    rgba = colormaps["viridis"]((mesh - lo) / span)
    return png_data_url(rgba[:, :, :3])


def _vendored(name: str) -> str:
    return (_VENDOR / name).read_text(encoding="utf-8")


def _vendored_react_js() -> str:
    """The vendored React runtime, evaluated into a private scope.

    Each UMD build runs inside a function whose ``window``/``self``/
    ``globalThis`` parameters shadow the real page globals with a private
    object, so React attaches itself THERE — never to the notebook page,
    which runs its own (different) React. ``.call(scope, ...)`` also pins
    ``this`` to the same private object, which is what the UMD wrapper
    actually reads.
    """
    shadow = "window, self, globalThis, module, exports, define"
    call = (
        ".call(__zmartVendor, __zmartVendor, __zmartVendor, __zmartVendor,"
        " undefined, undefined, undefined);"
    )
    return (
        "// Vendored react + react-dom 18.3.1 (MIT, see vendor/LICENSE in the\n"
        "// Python package). Evaluated into a private scope: no CDN, works\n"
        "// fully offline, and cannot clash with the page's own React.\n"
        "//\n"
        "// The private scope DELEGATES reads of the browser environment to the\n"
        "// real window (react-dom checks window.document at load time to know\n"
        "// it is in a browser, and uses timers/rAF), but WRITES — React\n"
        "// attaching itself as window.React — land on the private object and\n"
        "// never touch the page, which runs its own, different React.\n"
        "const __zmartVendor = {};\n"
        'if (typeof window !== "undefined") {\n'
        "  __zmartVendor.document = window.document;\n"
        "  __zmartVendor.navigator = window.navigator;\n"
        "  __zmartVendor.location = window.location;\n"
        "  __zmartVendor.performance = window.performance;\n"
        "  // react-dom also reaches for DOM constructors through its window\n"
        "  // (e.g. `x instanceof window.HTMLIFrameElement` while saving the\n"
        "  // text selection before EVERY commit) — without these on the\n"
        "  // private scope, the very first render dies and the widget shows\n"
        "  // an empty cell.\n"
        '  for (const cls of ["HTMLIFrameElement", "Element", "Node", "Event"]) {\n'
        "    if (window[cls] !== undefined) { __zmartVendor[cls] = window[cls]; }\n"
        "  }\n"
        '  for (const fn of ["addEventListener", "removeEventListener",\n'
        '                    "dispatchEvent", "requestAnimationFrame",\n'
        '                    "cancelAnimationFrame", "setTimeout",\n'
        '                    "clearTimeout", "setInterval", "clearInterval",\n'
        '                    "getSelection", "matchMedia"]) {\n'
        '    if (typeof window[fn] === "function") {\n'
        "      __zmartVendor[fn] = window[fn].bind(window);\n"
        "    }\n"
        "  }\n"
        "}\n"
        f"(function({shadow}) {{\n" + _vendored("react.production.min.js") + f"\n}}){call}\n"
        f"(function({shadow}) {{\n" + _vendored("react-dom.production.min.js") + f"\n}}){call}\n"
        "const React = __zmartVendor.React;\n"
        "const createRoot = (el) => __zmartVendor.ReactDOM.createRoot(el);\n"
    )


# JavaScript shared by every widget: the vendored React runtime, hooks that
# bind React state to anywidget traits and streamed messages, and the house
# style. Concatenated in front of each widget's own code to form its ESM
# module.
REACT_PRELUDE = (
    _vendored_react_js()
    + """
const h = React.createElement;

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

// Streamed lists: the trait holds metadata; one custom message per NEW item
// keeps mid-run traffic proportional to the data. A "sync" catch-up is a
// reset followed by the same bounded binary messages.
// Image pixels arrive as binary buffers (raw PNG); the entry's
// "buffer_keys" say which fields they fill. Snapshot catch-up uses the same
// bounded messages, preceded by "<kind>:reset", instead of one enormous
// base64 trait. Object URLs are owned per entry/key so replacing an index
// revokes the displaced URL immediately.
function useStream(model, traitName, messageType) {
  const [items, setItems] = React.useState(model.get(traitName) || []);
  const urls = React.useRef(new Map());
  React.useEffect(() => {
    const revokeAll = () => {
      urls.current.forEach((u) => URL.revokeObjectURL(u));
      urls.current.clear();
    };
    const onMsg = (msg, buffers) => {
      if (!msg) return;
      if (msg.type === `${messageType}:reset`) {
        if (msg.preserve) {
          const length = Number.isInteger(msg.length) && msg.length >= 0 ? msg.length : 0;
          urls.current.forEach((url, owner) => {
            if (Number(owner.split(":", 1)[0]) >= length) {
              URL.revokeObjectURL(url);
              urls.current.delete(owner);
            }
          });
          setItems((prev) => prev.slice(0, length));
        } else {
          revokeAll();
          setItems([]);
        }
        return;
      }
      if (msg.type !== messageType) return;
      const entry = { ...msg.entry };
      (msg.buffer_keys || []).forEach((key, k) => {
        const view = buffers && buffers[k];
        // A zero-length buffer means either "no image" or a failed replay.
        // Keep an existing URL when there is one; otherwise leave the field
        // empty rather than minting a broken URL to an empty blob.
        const owner = `${msg.index}:${key}`;
        const old = urls.current.get(owner);
        if (!view || !view.byteLength) {
          if (old) entry[key] = old;
          return;
        }
        if (old) URL.revokeObjectURL(old);
        const url = URL.createObjectURL(new Blob([view], { type: "image/png" }));
        urls.current.set(owner, url);
        entry[key] = url;
      });
      setItems((prev) => {
        const next = prev.slice();
        next[msg.index] = entry;
        return next;
      });
    };
    model.on("msg:custom", onMsg);
    model.send({ type: "sync" });  // a fresh view asks for the full picture
    return () => {
      model.off("msg:custom", onMsg);
      revokeAll();
    };
  }, [model, traitName, messageType]);
  // Messages can arrive before the snapshot fills the gaps; skip the holes.
  return items.filter((it) => it !== undefined && it !== null);
}

// A number input that commits on blur or Enter — not on every keystroke,
// which would re-render (and retransmit) the whole widget mid-typing.
function NumBox({ value, onCommit, width = 52, disabled = false }) {
  const [text, setText] = React.useState(String(value));
  React.useEffect(() => { setText(String(value)); }, [value]);
  const commit = () => {
    if (disabled) return;
    const v = parseFloat(text);
    if (Number.isFinite(v)) onCommit(v); else setText(String(value));
  };
  return h("input", { style: { ...inp, width }, value: text, disabled,
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

// One light, neutral palette for every widget: white cards that sit
// naturally on a light notebook or the web page. The image viewports
// themselves (the overview map, the focus map) stay black — microscopy
// images read best on black regardless of the page around them.
const T = {
  bg: "#f1f5f9", panel: "#ffffff", edge: "#cbd5e1", ink: "#0f172a",
  dim: "#64748b", accent: "#0284c7", good: "#16a34a", bad: "#dc2626",
  warn: "#d97706",
};
const card = {
  background: T.panel, border: `1px solid ${T.edge}`, borderRadius: 12,
  padding: 12, color: T.ink,
  fontFamily: "system-ui, -apple-system, sans-serif", fontSize: 13,
};
const btn = (disabled) => ({
  background: disabled ? T.edge : T.accent, color: disabled ? T.dim : "#ffffff",
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
      const root = createRoot(el);
      root.render(h(App, { model }));
      return () => root.unmount();
    },
  };
}
"""
)
