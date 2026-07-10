"""Shared plumbing for the React-based notebook widgets.

The React widgets are built on `anywidget <https://anywidget.dev>`_: each
widget is a small React app running in the browser cell, kept in sync with
Python through *traits* (shared state that either side can change) and
*messages* (button presses the browser sends to Python). Python streams
fresh data by updating traits mid-loop — the kernel flushes those updates
to the browser immediately, which is what makes the widgets update in real
time while the microscope works.

Images travel as PNG data URLs inside traits. The React runtime itself is
loaded from the esm.sh CDN, so the *browser* needs internet access the
first time a widget renders (the kernel does not).
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


# JavaScript shared by every widget: React from the CDN, a hook that binds a
# React state to an anywidget trait, and the house style. Concatenated in
# front of each widget's own code to form its ESM module.
REACT_PRELUDE = """
import * as React from "https://esm.sh/react@18.3.1";
import { createRoot } from "https://esm.sh/react-dom@18.3.1/client";
const h = React.createElement;

function useTrait(model, name) {
  const [value, setValue] = React.useState(model.get(name));
  React.useEffect(() => {
    const cb = () => setValue(model.get(name));
    model.on(`change:${name}`, cb);
    return () => model.off(`change:${name}`, cb);
  }, [model, name]);
  return [value, (v) => { model.set(name, v); model.save_changes(); }];
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
      const root = createRoot(el);
      root.render(h(App, { model }));
      return () => root.unmount();
    },
  };
}
"""
