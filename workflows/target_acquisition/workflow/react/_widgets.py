"""The four v4 review steps as React apps inside notebook cells.

Same workflow, same data, same safety paths as the matplotlib widgets in
``workflow/`` — only the front end differs: each widget here is a React
app rendered in the browser, talking to Python over anywidget traits and
messages. All hardware work still runs in Python through the controller
session (the browser can only *ask*; Python moves the stage), and all
image mathematics is shared with the matplotlib widgets so both notebooks
show identical pictures.

Live updates come for free with this design: Python pushes a trait update
after every saved tile / measured point / acquired pair, and the browser
re-renders that instant, while the microscope keeps working.
"""

from __future__ import annotations

import time
from typing import Any

from ._support import (
    CHANNEL_HEX,
    REACT_PRELUDE,
    heatmap_data_url,
    png_data_url,
    require_anywidget,
)

require_anywidget()

import anywidget  # noqa: E402
import traitlets  # noqa: E402

from .._acquisition_widget import pair_images  # noqa: E402
from .._discovery_widget import _feature_value, _numeric_features, crop_for_target  # noqa: E402
from .._focus_run import measure_focus  # noqa: E402
from .._focus_surface import fit_focus_surface  # noqa: E402
from .._overview_widget import _load_overview_channels, composite_channels  # noqa: E402
from .._records import record_channel_paths  # noqa: E402
from ..steps import acquire_targets  # noqa: E402

# Ignore button messages arriving within this window after a run finishes —
# clicks queued in the browser while Python was busy would otherwise start
# a second hardware run the moment the first completes.
_QUEUED_CLICK_WINDOW_S = 2.0


class _ZmartWidget(anywidget.AnyWidget):
    """Base: routes anywidget messages to ``handle_message`` (testable)."""

    status = traitlets.Unicode("").tag(sync=True)
    busy = traitlets.Bool(False).tag(sync=True)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._last_run_ended: float | None = None
        self.on_msg(lambda _widget, content, _buffers: self.handle_message(content))

    def handle_message(self, content: dict) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def _debounced(self) -> bool:
        """True when a queued click should be ignored (and says so)."""
        if (
            self._last_run_ended is not None
            and time.monotonic() - self._last_run_ended < _QUEUED_CLICK_WINDOW_S
        ):
            self.status = "ignored a click queued during the previous run"
            return True
        return False

    def _run_guarded(self, action) -> None:
        """Run one hardware action with busy/error bookkeeping."""
        if self.busy:
            self.status = "a run is already in progress"
            return
        self.busy = True
        try:
            action()
        except Exception as exc:  # noqa: BLE001 -- shown to the operator, not lost
            self.status = f"failed: {exc}"
        finally:
            self.busy = False
            self._last_run_ended = time.monotonic()


# ---------------------------------------------------------------------------
# 1 · Overview mosaic
# ---------------------------------------------------------------------------


class OverviewViewerReact(_ZmartWidget):
    """The overview tiles on one zoomable map — as a React app.

    Same behaviour as :class:`~.._overview_widget.OverviewViewer`: tiles sit
    at their real frame positions, channels blend as an additive overlay,
    and the side panel adjusts one channel at a time (colour swatch cycles
    the palette, the eye toggles visibility, min/max set the display
    range). Drag to pan, scroll to zoom. Stream tiles in live by passing
    :meth:`add_acquisition` as ``run_overview``'s ``on_record``.
    """

    tiles = traitlets.List().tag(sync=True)
    channels = traitlets.List().tag(sync=True)

    _esm = REACT_PRELUDE + """
function App({ model }) {
  const [tiles] = useTrait(model, "tiles");
  const [channels, setChannels] = useTrait(model, "channels");
  const [status] = useTrait(model, "status");
  const view = React.useRef({ scale: 1, tx: 0, ty: 0, fitted: 0 });
  const [, bump] = React.useReducer((n) => n + 1, 0);
  const box = React.useRef(null);
  const W = 640, H = 520;

  if (tiles.length && view.current.fitted !== tiles.length) {
    const xs = tiles.flatMap((t) => [t.x0, t.x0 + t.w]);
    const ys = tiles.flatMap((t) => [t.y0, t.y0 + t.h]);
    const spanX = Math.max(...xs) - Math.min(...xs);
    const spanY = Math.max(...ys) - Math.min(...ys);
    const fit = Math.min(W / spanX, H / spanY) * 0.95;
    view.current = { scale: fit, tx: W / 2 - (Math.min(...xs) + spanX / 2) * fit,
                     ty: H / 2 - (Math.min(...ys) + spanY / 2) * fit,
                     fitted: tiles.length };
  }

  const onWheel = (e) => {
    e.preventDefault();
    const f = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    const r = box.current.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const v = view.current;
    view.current = { ...v, scale: v.scale * f, tx: mx - (mx - v.tx) * f, ty: my - (my - v.ty) * f };
    bump();
  };
  const drag = React.useRef(null);
  const onDown = (e) => { drag.current = { x: e.clientX, y: e.clientY }; };
  const onMove = (e) => {
    if (!drag.current) return;
    const v = view.current;
    view.current = { ...v, tx: v.tx + e.clientX - drag.current.x, ty: v.ty + e.clientY - drag.current.y };
    drag.current = { x: e.clientX, y: e.clientY };
    bump();
  };

  const setCh = (i, patch) =>
    setChannels(channels.map((c, k) => (k === i ? { ...c, ...patch } : c)));

  return h("div", { style: { ...card, display: "flex", gap: 12 } },
    h("div", {
        ref: box, onWheel, onPointerDown: onDown, onPointerMove: onMove,
        onPointerUp: () => (drag.current = null), onPointerLeave: () => (drag.current = null),
        style: { width: W, height: H, background: "#000", borderRadius: 10,
                 overflow: "hidden", position: "relative", cursor: "grab", flex: "none" } },
      tiles.map((t, i) => {
        const v = view.current;
        return h("img", { key: i, src: t.src, draggable: false, style: {
          position: "absolute", left: t.x0 * v.scale + v.tx, top: t.y0 * v.scale + v.ty,
          width: t.w * v.scale, height: t.h * v.scale, imageRendering: "pixelated" } });
      }),
      h("div", { style: { position: "absolute", left: 10, bottom: 8 } },
        pill(`${tiles.length} tile(s) — drag to pan, scroll to zoom`))),
    h("div", { style: { width: 230 } },
      h("div", { style: { fontWeight: 700, marginBottom: 8 } }, "channels"),
      channels.map((c, i) => h("div", { key: i, style: {
          display: "flex", alignItems: "center", gap: 6, marginBottom: 8,
          background: T.bg, borderRadius: 8, padding: 6 } },
        h("button", { title: "cycle colour",
          onClick: () => setCh(i, { color: c.palette[(c.palette.indexOf(c.color) + 1) % c.palette.length] }),
          style: { width: 22, height: 22, borderRadius: 6, border: `1px solid ${T.edge}`,
                   background: c.color, cursor: "pointer" } }),
        h("button", { title: "show / hide",
          onClick: () => setCh(i, { visible: !c.visible }),
          style: { ...btn(false), padding: "2px 8px",
                   background: c.visible ? T.accent : T.edge } }, c.visible ? "on" : "off"),
        h("span", { style: { color: T.dim, width: 30 } }, `ch ${i}`),
        h("input", { style: { ...inp, width: 52 }, type: "number", value: Math.round(c.lo),
          onChange: (e) => setCh(i, { lo: +e.target.value }) }),
        h("input", { style: { ...inp, width: 52 }, type: "number", value: Math.round(c.hi),
          onChange: (e) => setCh(i, { hi: +e.target.value }) }))),
      h("div", { style: { color: T.dim, marginTop: 8, fontSize: 12 } }, status)));
}
export default mount(App);
"""

    # Tiles travel to the browser as PNGs inside a trait, so each one is
    # kept under a fixed pixel budget — a full-resolution 2048x2048 tile
    # would make every trait update megabytes and stall the comm channel.
    _PER_TILE_PIXEL_BUDGET = 1_500_000

    def __init__(
        self, overviews: list[dict] | None = None, *, downsample: int | None = None
    ) -> None:
        super().__init__()
        self._fixed_downsample = None if downsample is None else max(1, int(downsample))
        self.downsample = self._fixed_downsample or 1
        self.overviews: list[dict] = []
        self._stacks: list[Any] = []
        self.n_channels: int | None = None
        self.observe(self._on_channels_changed, names="channels")
        for overview in overviews or []:
            self.add_tile(overview)

    # --- growing the map (live) -------------------------------------------

    def add_acquisition(self, index: int, position: dict, record: dict) -> dict:
        """``on_record`` hook for :func:`~..steps.run_overview` — live tiles."""
        from ..discovery import read_overview_geometry

        paths = record_channel_paths(record, context=f"overview record {index}")
        geometry = read_overview_geometry(paths[0])
        overview = {
            "image_path": paths[0],
            "channel_paths": paths,
            "center_frame_um": (float(position["x"]), float(position["y"])),
            "pixel_size_um": geometry["pixel_size_um"],
            "image_size_px": geometry["image_size_px"],
            "label": index,
        }
        self.add_tile(overview)
        return overview

    def _step_for(self, overview: dict) -> int:
        """The display downsample for one tile (explicit, or budget-driven)."""
        import math

        if self._fixed_downsample is not None:
            return self._fixed_downsample
        h, w = overview["image_size_px"]
        return max(1, math.ceil(math.sqrt(int(h) * int(w) / self._PER_TILE_PIXEL_BUDGET)))

    def add_tile(self, overview: dict) -> None:
        self.downsample = self._step_for(overview)
        stack = _load_overview_channels(overview, step=self.downsample)
        if self.n_channels is None:
            self.n_channels = stack.shape[0]
            self._init_channels(stack)
        elif stack.shape[0] != self.n_channels:
            raise ValueError(
                f"tiles disagree on channel count: {sorted({self.n_channels, stack.shape[0]})}"
            )
        self.overviews.append(overview)
        self._stacks.append(stack)
        self.tiles = self.tiles + [self._tile_entry(overview, stack)]
        self.status = f"{len(self.overviews)} tile(s) on the map"

    def reload(self) -> None:
        """Re-read every tile from disk (after the simulation hijack)."""
        self._stacks = [
            _load_overview_channels(o, step=self._step_for(o)) for o in self.overviews
        ]
        self._retile()

    def _init_channels(self, stack: Any) -> None:
        import numpy as np

        channels = []
        for c in range(self.n_channels):
            values = stack[c].ravel()
            full_lo, full_hi = float(values.min()), float(values.max())
            lo, hi = (float(v) for v in np.percentile(values, (1.0, 99.5)))
            if hi - lo < 1e-9:
                lo, hi = min(0.0, full_lo), max(full_hi, full_lo + 1.0)
            channels.append(
                {
                    "color": CHANNEL_HEX[c % len(CHANNEL_HEX)],
                    "palette": list(CHANNEL_HEX),
                    "visible": True,
                    "lo": lo,
                    "hi": hi,
                }
            )
        self.channels = channels

    def _channel_states(self) -> list[dict]:
        """The shared-compositor shape of the channel traits."""
        return [
            {"color": c["color"], "visible": c["visible"], "range": (c["lo"], c["hi"])}
            for c in self.channels
        ]

    def _tile_entry(self, overview: dict, stack: Any) -> dict:
        cx, cy = overview["center_frame_um"]
        h_px, w_px = overview["image_size_px"]
        ps = float(overview["pixel_size_um"])
        w_um, h_um = w_px * ps, h_px * ps
        return {
            "src": png_data_url(composite_channels(stack, self._channel_states())),
            "x0": cx - w_um / 2.0,
            "y0": cy - h_um / 2.0,
            "w": w_um,
            "h": h_um,
            "label": overview.get("label"),
        }

    def _retile(self) -> None:
        self.tiles = [
            self._tile_entry(o, s) for o, s in zip(self.overviews, self._stacks, strict=True)
        ]

    def _on_channels_changed(self, _change: Any) -> None:
        if self._stacks:
            self._retile()

    def handle_message(self, content: dict) -> None:
        # The viewer has no hardware actions; nothing arrives here today.
        self.status = f"unknown message: {content.get('type')}"


# ---------------------------------------------------------------------------
# 2 · Focus picker
# ---------------------------------------------------------------------------


class FocusPickerReact(_ZmartWidget):
    """Pick focus points, measure them, and watch the map grow — React app.

    Click the map to add a point; click a point to remove it; **Measure**
    autofocuses at every point through the controller session, and the
    fitted surface streams in as a heatmap, refining after every measured
    point. ``require_focus()`` hands the surface to the rest of the run,
    exactly like the matplotlib picker.
    """

    squares = traitlets.List().tag(sync=True)
    points = traitlets.List().tag(sync=True)
    measured = traitlets.List().tag(sync=True)
    heatmap = traitlets.Dict().tag(sync=True)

    _esm = REACT_PRELUDE + """
function App({ model }) {
  const [squares] = useTrait(model, "squares");
  const [points, setPoints] = useTrait(model, "points");
  const [measured] = useTrait(model, "measured");
  const [heatmap] = useTrait(model, "heatmap");
  const [busy] = useTrait(model, "busy");
  const [status] = useTrait(model, "status");
  const W = 620, H = 470, pad = 40;

  const xs = [...squares.map((s) => s.x), ...points.map((p) => p.x), 0];
  const ys = [...squares.map((s) => s.y), ...points.map((p) => p.y), 0];
  const lo = (v) => Math.min(...v), hi = (v) => Math.max(...v);
  const spanX = Math.max(hi(xs) - lo(xs), 1), spanY = Math.max(hi(ys) - lo(ys), 1);
  const s = Math.min((W - 2 * pad) / spanX, (H - 2 * pad) / spanY);
  const X = (x) => pad + (x - lo(xs)) * s + ((W - 2 * pad) - spanX * s) / 2;
  const Y = (y) => pad + (y - lo(ys)) * s + ((H - 2 * pad) - spanY * s) / 2;
  const toUm = (e, svg) => {
    const r = svg.getBoundingClientRect();
    return { x: (e.clientX - r.left - (X(0) - 0 * s)) / s + 0, y: (e.clientY - r.top - Y(0)) / s };
  };

  return h("div", { style: { ...card, width: W + 24 } },
    h("div", { style: { display: "flex", alignItems: "center", gap: 10, marginBottom: 8 } },
      h("button", { style: btn(busy), disabled: busy,
        onClick: () => model.send({ type: "measure" }) },
        busy ? "measuring..." : "Measure focus"),
      pill(`${points.length} point(s)`),
      h("span", { style: { color: T.dim, fontSize: 12 } }, status)),
    h("svg", {
        width: W, height: H,
        style: { background: "#000", borderRadius: 10, cursor: "crosshair" },
        onClick: (e) => {
          if (busy) return;
          const svg = e.currentTarget;
          const um = toUm(e, svg);
          setPoints([...points, { x: um.x, y: um.y }]);
        } },
      heatmap.src ? h("image", { href: heatmap.src, x: X(heatmap.x0), y: Y(heatmap.y0),
        width: heatmap.w * s, height: heatmap.h * s, preserveAspectRatio: "none",
        opacity: 0.9 }) : null,
      squares.map((q, i) => h("rect", { key: `s${i}`, x: X(q.x) - 7, y: Y(q.y) - 7,
        width: 14, height: 14, fill: "none", stroke: T.accent, strokeWidth: 1.5 })),
      points.map((p, i) => {
        const m = measured[i];
        return h("g", { key: `p${i}`, style: { cursor: "pointer" },
            onClick: (e) => { e.stopPropagation(); if (!busy) setPoints(points.filter((_, k) => k !== i)); } },
          h("circle", { cx: X(p.x), cy: Y(p.y), r: 7, fill: m ? T.good : T.bad,
            stroke: "#000", strokeWidth: 1.5 }),
          m ? h("text", { x: X(p.x) + 10, y: Y(p.y) - 8, fill: T.ink, fontSize: 11 },
            m.z_um.toFixed(1)) : null);
      })),
    h("div", { style: { color: T.dim, fontSize: 12, marginTop: 6 } },
      "click: add a focus point · click a point: remove it · squares: overview positions"));
}
export default mount(App);
"""

    def __init__(
        self,
        session: Any,
        positions: list[dict] | None = None,
        *,
        af_job: str | None = None,
        start_z: float | None = None,
        seed: bool = True,
    ) -> None:
        super().__init__()
        self.session = session
        self.af_job = af_job
        self.start_z = start_z
        self.squares = [{"x": float(p["x"]), "y": float(p["y"])} for p in (positions or [])]
        self.focus: Any = None
        self._measured_points: list[dict] | None = None
        if seed:
            self.points = self._seed_from_lasx()
        self.observe(self._on_points_edited, names="points")
        self.status = "pick focus points, then press Measure"

    def _seed_from_lasx(self) -> list[dict]:
        if "get_focus_points" not in self.session.get_procedures():
            return []
        result = self.session.run_procedure({"name": "get_focus_points"})
        return [
            {"x": float(p["x"]), "y": float(p["y"])} for p in (result.get("positions") or [])
        ]

    def _on_points_edited(self, _change: Any) -> None:
        if self._measured_points is not None and self.points != self._measured_points:
            self._invalidate()

    def _invalidate(self) -> None:
        self.focus = None
        self.measured = []
        self.heatmap = {}
        self._measured_points = None

    def handle_message(self, content: dict) -> None:
        if content.get("type") != "measure":
            self.status = f"unknown message: {content.get('type')}"
            return
        if self._debounced():
            return
        self._run_guarded(self._measure)

    def _measure(self) -> None:
        if not self.points:
            raise RuntimeError("no focus points are picked yet — click the map first")
        points = [dict(p) for p in self.points]
        self._invalidate()
        collected: list[dict] = []

        def _show_fresh_point(measurement: dict) -> None:
            collected.append(measurement)
            self.measured = list(collected)
            self.focus = fit_focus_surface(self.measured)
            self.heatmap = self._render_heatmap()
            self.status = f"measuring... {len(collected)} of {len(points)} points"

        measure_focus(
            self.session, points, af_job=self.af_job, start_z=self.start_z,
            on_point=_show_fresh_point,
        )
        self._measured_points = points
        self.status = f"focus surface fitted ({self.focus.model}, {len(points)} pts)"

    def _render_heatmap(self) -> dict:
        import numpy as np

        xs = [m["x_um"] for m in self.measured] + [q["x"] for q in self.squares]
        ys = [m["y_um"] for m in self.measured] + [q["y"] for q in self.squares]

        def _span(values):
            lo, hi = float(min(values)), float(max(values))
            return (lo - 1.0, hi + 1.0) if hi - lo < 1e-9 else (lo, hi)

        x_lo, x_hi = _span(xs)
        y_lo, y_hi = _span(ys)
        gx, gy = np.meshgrid(np.linspace(x_lo, x_hi, 60), np.linspace(y_lo, y_hi, 60))
        mesh = np.asarray(self.focus.z_at(gx, gy), dtype=float).reshape(gx.shape)
        return {
            "src": heatmap_data_url(mesh),
            "x0": x_lo, "y0": y_lo, "w": x_hi - x_lo, "h": y_hi - y_lo,
        }

    def require_focus(self) -> Any:
        """The fitted focus surface; a clear error when measuring was skipped."""
        if self.focus is None or self._measured_points != self.points:
            raise RuntimeError(
                "the current focus points have not been measured — press "
                "'Measure focus' before continuing."
            )
        return self.focus


# ---------------------------------------------------------------------------
# 3 · Target explorer
# ---------------------------------------------------------------------------


class TargetExplorerReact(_ZmartWidget):
    """Scatter, gate, and inspect the discovered cells — as a React app.

    Feature dropdowns choose the axes; min/max inputs threshold the current
    axes; dragging on the plot draws a lasso; hovering a dot shows that
    cell's image crop. ``explorer.gated`` is the live gate the acquisition
    step samples from — identical semantics to the matplotlib explorer
    (thresholds AND lasso; switching axes clears the lasso).
    """

    features = traitlets.List().tag(sync=True)
    x_feature = traitlets.Unicode().tag(sync=True)
    y_feature = traitlets.Unicode().tag(sync=True)
    dots = traitlets.List().tag(sync=True)
    gate = traitlets.Dict().tag(sync=True)
    gated_mask = traitlets.List().tag(sync=True)
    hover = traitlets.Dict().tag(sync=True)

    _esm = REACT_PRELUDE + """
function App({ model }) {
  const [features] = useTrait(model, "features");
  const [xf, setXf] = useTrait(model, "x_feature");
  const [yf, setYf] = useTrait(model, "y_feature");
  const [dots] = useTrait(model, "dots");
  const [gate, setGate] = useTrait(model, "gate");
  const [mask] = useTrait(model, "gated_mask");
  const [hover] = useTrait(model, "hover");
  const [status] = useTrait(model, "status");
  const W = 460, H = 360, pad = 42;

  const fx = dots.map((d) => d.fx), fy = dots.map((d) => d.fy);
  const lox = Math.min(...fx), hix = Math.max(...fx);
  const loy = Math.min(...fy), hiy = Math.max(...fy);
  const sx = (hix - lox) || 1, sy = (hiy - loy) || 1;
  const X = (v) => pad + ((v - lox) / sx) * (W - 2 * pad);
  const Y = (v) => H - pad - ((v - loy) / sy) * (H - 2 * pad);
  const toData = (e, svg) => {
    const r = svg.getBoundingClientRect();
    return [lox + ((e.clientX - r.left - pad) / (W - 2 * pad)) * sx,
            loy + ((H - pad - (e.clientY - r.top)) / (H - 2 * pad)) * sy];
  };
  const lasso = React.useRef(null);
  const [trail, setTrail] = React.useState([]);

  const select = (value, onChange) => h("select", {
      value, onChange: (e) => onChange(e.target.value),
      style: { ...inp, width: 130 } },
    features.map((f) => h("option", { key: f, value: f }, f)));

  const rng = gate.x || [lox, hix], rngY = gate.y || [loy, hiy];
  const setRange = (axis, i, v) => {
    const next = { ...gate, [axis]: [...(gate[axis] || (axis === "x" ? [lox, hix] : [loy, hiy]))] };
    next[axis][i] = +v;
    setGate(next);
  };

  return h("div", { style: { ...card, display: "flex", gap: 12 } },
    h("div", null,
      h("div", { style: { display: "flex", gap: 8, marginBottom: 8, alignItems: "center" } },
        h("span", { style: { color: T.dim } }, "x"), select(xf, setXf),
        h("span", { style: { color: T.dim } }, "y"), select(yf, setYf),
        h("button", { style: { ...btn(false), padding: "4px 10px" },
          onClick: () => setGate({ ...gate, lasso: null }) }, "clear lasso")),
      h("svg", { width: W, height: H,
          style: { background: T.bg, borderRadius: 10, touchAction: "none" },
          onPointerDown: (e) => { lasso.current = [toData(e, e.currentTarget)]; setTrail(lasso.current); },
          onPointerMove: (e) => {
            if (!lasso.current) return;
            lasso.current = [...lasso.current, toData(e, e.currentTarget)];
            setTrail(lasso.current);
          },
          onPointerUp: () => {
            if (lasso.current && lasso.current.length >= 3) setGate({ ...gate, lasso: lasso.current });
            lasso.current = null; setTrail([]);
          } },
        h("line", { x1: pad, y1: H - pad, x2: W - pad, y2: H - pad, stroke: T.edge }),
        h("line", { x1: pad, y1: pad, x2: pad, y2: H - pad, stroke: T.edge }),
        h("text", { x: W / 2, y: H - 8, fill: T.dim, fontSize: 11, textAnchor: "middle" }, xf),
        h("text", { x: 12, y: H / 2, fill: T.dim, fontSize: 11, transform: `rotate(-90 12 ${H / 2})`,
          textAnchor: "middle" }, yf),
        trail.length ? h("polyline", {
          points: trail.map(([a, b]) => `${X(a)},${Y(b)}`).join(" "),
          fill: "rgba(56,189,248,0.15)", stroke: T.accent, strokeDasharray: "4 3" }) : null,
        (gate.lasso || []).length ? h("polygon", {
          points: gate.lasso.map(([a, b]) => `${X(a)},${Y(b)}`).join(" "),
          fill: "rgba(56,189,248,0.10)", stroke: T.accent, strokeDasharray: "4 3" }) : null,
        dots.map((d, i) => h("circle", { key: i, cx: X(d.fx), cy: Y(d.fy), r: 5,
          fill: mask[i] ? T.accent : T.edge, style: { transition: "fill 0.2s" },
          onMouseEnter: () => model.send({ type: "hover", index: i }) }))),
      h("div", { style: { display: "flex", gap: 6, marginTop: 8, alignItems: "center", fontSize: 12 } },
        h("span", { style: { color: T.dim } }, xf),
        h("input", { style: inp, type: "number", value: rng[0], onChange: (e) => setRange("x", 0, e.target.value) }),
        h("input", { style: inp, type: "number", value: rng[1], onChange: (e) => setRange("x", 1, e.target.value) }),
        h("span", { style: { color: T.dim } }, yf),
        h("input", { style: inp, type: "number", value: rngY[0], onChange: (e) => setRange("y", 0, e.target.value) }),
        h("input", { style: inp, type: "number", value: rngY[1], onChange: (e) => setRange("y", 1, e.target.value) }))),
    h("div", { style: { width: 190 } },
      h("div", { style: { fontWeight: 700, marginBottom: 6 } },
        `${mask.filter(Boolean).length} / ${dots.length} in the gate`),
      hover.src
        ? h("div", null,
            h("img", { src: hover.src, style: { width: 180, borderRadius: 8,
              imageRendering: "pixelated", border: `1px solid ${T.edge}` } }),
            h("div", { style: { color: T.dim, fontSize: 12, marginTop: 4 } }, hover.title))
        : h("div", { style: { color: T.dim, fontSize: 12 } }, "hover a point to see the cell"),
      h("div", { style: { color: T.dim, fontSize: 12, marginTop: 10 } }, status)));
}
export default mount(App);
"""

    def __init__(
        self,
        targets: list[dict],
        overviews: list[dict] | None = None,
        *,
        crop_um: float = 60.0,
    ) -> None:
        if not targets:
            raise ValueError("no targets to explore — run target discovery first")
        super().__init__()
        self.targets = targets
        self.overviews = {i: o for i, o in enumerate(overviews or [])}
        self.crop_um = float(crop_um)
        self.features = _numeric_features(targets)
        self.x_feature = self.features[0]
        self.y_feature = self.features[1] if len(self.features) > 1 else self.features[0]
        self.observe(self._on_axes_changed, names=["x_feature", "y_feature"])
        self.observe(self._on_gate_changed, names="gate")
        self._recompute(reset_gate=True)

    @property
    def gated(self) -> list[dict]:
        """The targets inside the gate — what the acquisition step samples."""
        return [t for t, keep in zip(self.targets, self.gated_mask, strict=True) if keep]

    def _on_axes_changed(self, _change: Any) -> None:
        # A lasso drawn in the old feature space would gate nonsense in the
        # new one, so switching axes clears the whole gate (like matplotlib).
        self._recompute(reset_gate=True)

    def _on_gate_changed(self, _change: Any) -> None:
        self._recompute(reset_gate=False)

    def _recompute(self, *, reset_gate: bool) -> None:
        dots = [
            {
                "fx": _feature_value(t, self.x_feature),
                "fy": _feature_value(t, self.y_feature),
            }
            for t in self.targets
        ]
        self.dots = dots
        if reset_gate:
            self.gate = {}
        mask = []
        x_range = (self.gate or {}).get("x")
        y_range = (self.gate or {}).get("y")
        lasso = (self.gate or {}).get("lasso")
        path = None
        if lasso and len(lasso) >= 3:
            from matplotlib.path import Path as MplPath

            path = MplPath(lasso)
        for dot in dots:
            keep = True
            if x_range:
                keep &= x_range[0] <= dot["fx"] <= x_range[1]
            if y_range:
                keep &= y_range[0] <= dot["fy"] <= y_range[1]
            if keep and path is not None:
                keep = bool(path.contains_point((dot["fx"], dot["fy"])))
            mask.append(bool(keep))
        self.gated_mask = mask
        self.status = "thresholds AND lasso gate together"

    def handle_message(self, content: dict) -> None:
        if content.get("type") != "hover":
            self.status = f"unknown message: {content.get('type')}"
            return
        # The index comes from the browser: validate it rather than trusting it.
        try:
            index = int(content.get("index"))
        except (TypeError, ValueError):
            return
        if not 0 <= index < len(self.targets):
            return
        crop = crop_for_target(self.targets[index], self.overviews, crop_um=self.crop_um)
        source = self.targets[index].get("source") or {}
        self.hover = {
            "index": index,
            "src": "" if crop is None else png_data_url(crop),
            "title": f"target {index} (tile {source.get('naming_p', '?')})",
        }


# ---------------------------------------------------------------------------
# 4 · Acquisition gallery
# ---------------------------------------------------------------------------


class AcquisitionGalleryReact(_ZmartWidget):
    """Acquire N random gated targets and review same-scale pairs — React app.

    Type a count and press **Acquire**: Python samples the explorer's live
    gate, drives the microscope through the same gated target-capture path
    as the scripts, and each overview/target pair fades into the gallery
    the moment it is saved. ``picked`` / ``records`` commit only when the
    whole run succeeds, exactly like the matplotlib gallery.
    """

    rows = traitlets.List().tag(sync=True)
    gate_count = traitlets.Int(0).tag(sync=True)
    default_count = traitlets.Int(5).tag(sync=True)

    _esm = REACT_PRELUDE + """
function App({ model }) {
  const [rows] = useTrait(model, "rows");
  const [busy] = useTrait(model, "busy");
  const [status] = useTrait(model, "status");
  const [gateCount] = useTrait(model, "gate_count");
  const [defaultCount] = useTrait(model, "default_count");
  const [count, setCount] = React.useState(String(defaultCount));

  return h("div", { style: { ...card, width: 700 } },
    h("style", null, "@keyframes zin { from { opacity: 0; transform: translateY(8px);} to { opacity: 1; transform: none;} }"),
    h("div", { style: { display: "flex", gap: 10, alignItems: "center", marginBottom: 10 } },
      h("span", { style: { color: T.dim } }, "how many"),
      h("input", { style: inp, value: count, onChange: (e) => setCount(e.target.value) }),
      h("button", { style: btn(busy), disabled: busy,
        onClick: () => model.send({ type: "acquire", count }) },
        busy ? "acquiring..." : "Acquire"),
      pill(`${gateCount} in the gate`),
      h("span", { style: { color: T.dim, fontSize: 12 } }, status)),
    rows.map((r, i) => h("div", { key: i, style: {
        display: "flex", gap: 10, marginBottom: 10, animation: "zin 0.35s ease" } },
      [["low", r.low_title], ["high", r.high_title]].map(([side, title]) =>
        h("div", { key: side, style: { flex: 1 } },
          h("img", { src: r[side + "_src"], style: { width: "100%", borderRadius: 10,
            imageRendering: "pixelated", border: `1px solid ${T.edge}` } }),
          h("div", { style: { color: T.dim, fontSize: 12, marginTop: 2 } }, title))))));
}
export default mount(App);
"""

    def __init__(
        self,
        session: Any,
        source: Any,
        overviews: list[dict] | None = None,
        *,
        state: dict | None = None,
        focus: Any = None,
        options: dict | None = None,
        after_acquire: Any = None,
        default_count: int = 5,
        seed: int | None = None,
    ) -> None:
        import random

        super().__init__()
        self.session = session
        self.source = source
        self.overviews = {i: o for i, o in enumerate(overviews or [])}
        self.state = state
        self.focus = focus
        self.options = options
        self.after_acquire = after_acquire
        self.default_count = int(default_count)
        self._rng = random.Random(seed)
        self.picked: list[dict] = []
        self.records: list[dict] = []
        self.gate_count = len(self._gated())
        self.status = "type a count and press Acquire"

    def _gated(self) -> list[dict]:
        return list(getattr(self.source, "gated", self.source))

    def handle_message(self, content: dict) -> None:
        if content.get("type") != "acquire":
            self.status = f"unknown message: {content.get('type')}"
            return
        if self._debounced():
            return
        text = str(content.get("count", "")).strip()
        if not text.isdecimal() or int(text) < 1:
            self.status = "failed: target count must be a positive whole number"
            return
        self._run_guarded(lambda: self.acquire(int(text)))

    def acquire(self, count: int) -> list[dict]:
        """Randomly pick ``count`` gated targets, acquire, stream the pairs."""
        gated = self._gated()
        self.gate_count = len(gated)
        if not gated:
            raise RuntimeError(
                "the gate is empty — widen the thresholds (or clear the lasso) "
                "in the target explorer before acquiring."
            )
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError("target count must be a positive whole number")
        picked = self._rng.sample(gated, count) if count < len(gated) else list(gated)
        self.rows = []

        def _show_fresh_pair(index: int, _position: dict, record: dict) -> None:
            self.rows = self.rows + [self._row_entry(picked[index - 1], record)]
            self.status = f"acquired {index} of {len(picked)} target(s)..."

        records = acquire_targets(
            self.session,
            picked,
            state=self.state,
            focus=self.focus,
            options=self.options,
            on_record=_show_fresh_pair,
        )
        if self.after_acquire is not None:
            self.after_acquire(records)
            # The hijack may have rewritten the saved images: re-read them.
            self.rows = [
                self._row_entry(t, r) for t, r in zip(picked, records, strict=True)
            ]
        self.picked = picked
        self.records = records
        self.status = f"acquired {len(records)} of {len(gated)} gated target(s)"
        return records

    def _row_entry(self, target: dict, record: dict) -> dict:
        pair = pair_images(target, record, self.overviews)
        source = target.get("source") or {}
        if pair is None:
            return {
                "low_src": "",
                "high_src": "",
                "low_title": "no image in this record",
                "high_title": "",
            }
        low, high, width_um, height_um = pair
        return {
            "low_src": png_data_url(low),
            "high_src": png_data_url(high),
            "low_title": (
                f"overview crop — tile {source.get('naming_p', '?')} "
                f"({width_um:.0f} × {height_um:.0f} um)"
            ),
            "high_title": f"target {record.get('position_label', '?')} — same window",
        }
