"""The four v4 review steps as React apps inside notebook cells.

Same workflow, same data, same safety paths as the matplotlib widgets in
``workflow/`` — only the front end differs: each widget here is a React
app rendered in the browser cell, talking to Python over anywidget traits
and messages. All hardware work still runs in Python through the
controller session (the browser can only *ask*; Python moves the stage),
and all image mathematics is shared with the matplotlib widgets so both
notebooks show identical pictures.

Live updates stream as one small message per new tile / measured point /
acquired pair (never a resend of everything already shown), and each
widget answers a ``sync`` message with the full picture so re-opened
views catch up. ``PROTOCOL.md`` in this package documents every trait
and message — that protocol is the seam to build a future non-notebook
(website) front end against.

Trust boundary, stated once: everything arriving from the browser —
messages AND trait writes — is treated as input to validate, never as
state to obey. Gating decisions are recomputed in Python from the raw
gate whenever they matter, counts and indices are checked before use,
and a malformed value degrades to a harmless default instead of an
exception that would leave the widget half-updated.
"""

from __future__ import annotations

import math
import time
from typing import Any

from ._support import (
    CHANNEL_HEX,
    REACT_PRELUDE,
    heatmap_data_url,
    png_bytes,
    png_data_url,
    png_to_data_url,
    require_anywidget,
    shrink_to_budget,
)

require_anywidget()

import anywidget  # noqa: E402
import traitlets  # noqa: E402

from .._acquisition_widget import pair_images  # noqa: E402
from .._discovery_widget import _feature_value, _numeric_features, crop_for_target  # noqa: E402
from .._focus_run import measure_focus  # noqa: E402
from .._focus_surface import fit_focus_surface, worst_residual_um  # noqa: E402
from .._overview_widget import _load_overview_channels, composite_channels  # noqa: E402
from .._records import record_channel_paths  # noqa: E402
from ..steps import acquire_targets  # noqa: E402

# Ignore button messages arriving within this window after a run finishes —
# clicks queued in the browser while Python was busy would otherwise start
# a second hardware run the moment the first completes.
_QUEUED_CLICK_WINDOW_S = 2.0

# Display copies travel to the browser as PNGs, so every image is kept
# under this pixel budget — a full-resolution 2048x2048 image would make a
# single update megabytes and stall the very channel the operator watches.
_PER_IMAGE_PIXEL_BUDGET = 1_500_000


class _ZmartWidget(anywidget.AnyWidget):
    """Base: routes anywidget messages to ``handle_message`` (testable)."""

    status = traitlets.Unicode("").tag(sync=True)
    busy = traitlets.Bool(False).tag(sync=True)
    #: Display-only mirror of the read-only state (hides buttons in the
    #: browser). The ENFORCEMENT is the private flag below — a synced trait
    #: can be rewritten by anything in the page, so it is never the check.
    read_only = traitlets.Bool(False).tag(sync=True)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._last_run_ended: float | None = None
        self._hardware_allowed = True
        self._cancel_requested = False
        self.on_msg(self._route_message)

    def make_read_only(self) -> None:
        """Turn this widget into a safe observer view.

        Hardware messages are refused in Python from now on (the browser
        buttons also hide, but that is courtesy, not the lock). Use it for
        a second tab or a colleague's view of a running session — they can
        watch everything and drive nothing.
        """
        self._hardware_allowed = False
        self.read_only = True

    def _route_message(self, _widget: Any, content: Any, _buffers: Any) -> None:
        # Anything can arrive on this channel; a non-dict is simply noise.
        if not isinstance(content, dict):
            return
        kind = content.get("type")
        if kind == "sync":
            # A freshly mounted browser view asks for the full picture.
            self.push_snapshot()
            return
        if kind == "cancel":
            self.request_cancel()
            return
        if not self._hardware_allowed:
            self.status = "this view is read-only — hardware actions are disabled"
            return
        self.handle_message(content)

    def handle_message(self, content: dict) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def push_snapshot(self) -> None:
        """Refresh the full-state traits for a (re)mounted browser view.

        The default is a no-op: widgets whose state already lives entirely
        in traits have nothing extra to push. Widgets that stream items as
        messages override this to publish the complete list.
        """

    def request_cancel(self) -> None:
        """Ask the running hardware loop to stop before its next site.

        The stop is cooperative and clean: the loop finishes the site it is
        on, then raises :class:`~.._capture_run.RunCancelled` — nothing is
        committed, and no further stage move is made. Honesty note for
        Jupyter: while a cell is running, the kernel only processes a
        browser click when it next comes up for air, so a Cancel pressed
        mid-run may only take effect late (or, if the run already ended,
        not at all — this method then says so). A future website host that
        processes messages concurrently gets immediate cancellation
        through this same path.
        """
        if self.busy:
            self._cancel_requested = True
            self.status = "cancel requested — stopping before the next site"
        else:
            self.status = "no run is in progress to cancel"

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
        """Run one action, reporting any failure on the status line.

        Widget messages have no cell output — an uncaught exception would
        vanish into the kernel log, so the error is shown where the
        operator is looking instead.
        """
        try:
            action()
        except Exception as exc:  # noqa: BLE001 -- shown to the operator, not lost
            self.status = f"failed: {exc}"

    def _hardware_run(self, work):
        """Busy-guard and debounce-stamp one real hardware run.

        Every path that drives the microscope — a browser button OR a
        scripted call — goes through here, so the busy flag, the read-only
        lock, and the queued-click window hold for both. Validation errors
        raise BEFORE this is entered, so a refused run never arms the
        debounce (a corrective click right after "the gate is empty" must
        not be eaten as a "queued" one).
        """
        if not self._hardware_allowed:
            raise RuntimeError("this view is read-only — hardware actions are disabled")
        if self.busy:
            raise RuntimeError("a run is already in progress")
        self.busy = True
        self._cancel_requested = False
        try:
            return work()
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
    range — committed when you leave the box or press Enter). Drag to pan,
    scroll to zoom, **Fit** to frame everything; once you pan or zoom, a
    growing map stops re-fitting under your hands. The cursor's frame
    position (micrometres) reads out live under the map. Stream tiles in
    live by passing :meth:`add_acquisition` as ``run_overview``'s
    ``on_record``.

    After discovery, :meth:`show_targets` overlays the found cells on the
    map itself — gated cells in blue, the rest grey — so gating can be
    judged against the sample, not just the scatter plot. Hovering a mark
    shows that cell's crop in the side panel. Pass the explorer to keep
    the colours live as the gate changes.
    """

    tiles = traitlets.List().tag(sync=True)
    channels = traitlets.List().tag(sync=True)
    marks = traitlets.List().tag(sync=True)
    mark_hover = traitlets.Dict().tag(sync=True)

    _esm = REACT_PRELUDE + """
function App({ model }) {
  const tiles = useStream(model, "tiles", "tile");
  const [channels, setChannels] = useTrait(model, "channels");
  const [marks] = useTrait(model, "marks");
  const [markHover] = useTrait(model, "mark_hover");
  const [status] = useTrait(model, "status");
  const view = React.useRef({ scale: 1, tx: 0, ty: 0, fitted: 0, user: false });
  const [, bump] = React.useReducer((n) => n + 1, 0);
  const [cursor, setCursor] = React.useState(null);
  const box = React.useRef(null);
  const W = 640, H = 520;

  const fit = () => {
    if (!tiles.length) return;
    const xs = tiles.flatMap((t) => [t.x0, t.x0 + t.w]);
    const ys = tiles.flatMap((t) => [t.y0, t.y0 + t.h]);
    const spanX = Math.max(...xs) - Math.min(...xs);
    const spanY = Math.max(...ys) - Math.min(...ys);
    const f = Math.min(W / spanX, H / spanY) * 0.95;
    view.current = { scale: f, tx: W / 2 - (Math.min(...xs) + spanX / 2) * f,
                     ty: H / 2 - (Math.min(...ys) + spanY / 2) * f,
                     fitted: tiles.length, user: view.current.user };
  };
  // Auto-fit while tiles stream in, but only until the operator takes the
  // view into their own hands — then keep it still under them.
  if (tiles.length && view.current.fitted !== tiles.length && !view.current.user) fit();

  useWheel(box, (e) => {
    const f = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    const r = box.current.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const v = view.current;
    view.current = { ...v, user: true,
                     scale: v.scale * f, tx: mx - (mx - v.tx) * f, ty: my - (my - v.ty) * f };
    bump();
  });
  const drag = React.useRef(null);
  const onDown = (e) => { drag.current = { x: e.clientX, y: e.clientY }; };
  const onMove = (e) => {
    const r = box.current.getBoundingClientRect();
    const v = view.current;
    setCursor({ x: (e.clientX - r.left - v.tx) / v.scale,
                y: (e.clientY - r.top - v.ty) / v.scale });
    if (!drag.current) return;
    view.current = { ...v, user: true,
                     tx: v.tx + e.clientX - drag.current.x, ty: v.ty + e.clientY - drag.current.y };
    drag.current = { x: e.clientX, y: e.clientY };
    bump();
  };

  const setCh = (i, patch) =>
    setChannels(channels.map((c, k) => (k === i ? { ...c, ...patch } : c)));

  return h("div", { style: { ...card, display: "flex", gap: 12 } },
    h("div", {
        ref: box, onPointerDown: onDown, onPointerMove: onMove,
        onPointerUp: () => (drag.current = null),
        onPointerLeave: () => { drag.current = null; setCursor(null); },
        style: { width: W, height: H, background: "#000", borderRadius: 10,
                 overflow: "hidden", position: "relative", cursor: "grab", flex: "none" } },
      tiles.map((t, i) => {
        const v = view.current;
        return h("img", { key: i, src: t.src, draggable: false, style: {
          position: "absolute", left: t.x0 * v.scale + v.tx, top: t.y0 * v.scale + v.ty,
          width: t.w * v.scale, height: t.h * v.scale, imageRendering: "pixelated" } });
      }),
      marks.map((m, i) => {
        const v = view.current;
        return h("div", { key: `m${i}`,
          onMouseEnter: () => model.send({ type: "mark", index: i }),
          style: { position: "absolute", left: m.x * v.scale + v.tx - 5,
                   top: m.y * v.scale + v.ty - 5, width: 10, height: 10,
                   borderRadius: 999, boxSizing: "border-box",
                   border: `2px solid ${m.gated ? T.accent : T.dim}`,
                   background: markHover.index === i ? T.accent : "transparent",
                   cursor: "pointer" } });
      }),
      h("div", { style: { position: "absolute", left: 10, bottom: 8, display: "flex", gap: 6 } },
        pill(`${tiles.length} tile(s) — drag to pan, scroll to zoom`),
        marks.length ? pill(`${marks.filter((m) => m.gated).length} / ${marks.length} gated`) : null,
        cursor ? pill(`x ${cursor.x.toFixed(0)} um · y ${cursor.y.toFixed(0)} um`) : null)),
    h("div", { style: { width: 230 } },
      h("div", { style: { display: "flex", alignItems: "center",
                          justifyContent: "space-between", marginBottom: 8 } },
        h("div", { style: { fontWeight: 700 } }, "channels"),
        h("button", { style: { ...btn(false), padding: "3px 10px" },
          onClick: () => { view.current.user = false; view.current.fitted = 0; bump(); } },
          "Fit")),
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
        h(NumBox, { value: Math.round(c.lo), onCommit: (v) => setCh(i, { lo: v }) }),
        h(NumBox, { value: Math.round(c.hi), onCommit: (v) => setCh(i, { hi: v }) }))),
      markHover.src
        ? h("div", { style: { marginTop: 8 } },
            h("img", { src: markHover.src, style: { width: 180, borderRadius: 8,
              imageRendering: "pixelated", border: `1px solid ${T.edge}` } }),
            h("div", { style: { color: T.dim, fontSize: 12, marginTop: 4 } }, markHover.title))
        : null,
      h("div", { style: { color: T.dim, marginTop: 8, fontSize: 12 } }, status)));
}
export default mount(App);
"""

    def __init__(
        self, overviews: list[dict] | None = None, *, downsample: int | None = None
    ) -> None:
        super().__init__()
        self._fixed_downsample = None if downsample is None else max(1, int(downsample))
        self.downsample = self._fixed_downsample or 1
        self.overviews: list[dict] = []
        self._stacks: list[Any] = []
        self._tile_entries: list[dict] = []
        self._targets: list[dict] = []
        self._marks_explorer: Any = None
        self._mark_crop_cache: dict[int, dict] = {}
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
        if self._fixed_downsample is not None:
            return self._fixed_downsample
        h, w = overview["image_size_px"]
        # Every channel of the tile becomes pixels in the composite, so the
        # budget counts all of them, not just one plane.
        n_channels = len(overview.get("channel_paths") or [overview["image_path"]])
        pixels = int(h) * int(w) * max(1, n_channels)
        return max(1, math.ceil(math.sqrt(pixels / _PER_IMAGE_PIXEL_BUDGET)))

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
        entry = self._tile_entry(overview, stack)
        self._tile_entries.append(entry)
        # One message per NEW tile — never a resend of the map so far, and
        # the pixels ride as a binary buffer (raw PNG, no base64 growth). A
        # freshly opened view catches up via the ``sync`` snapshot instead.
        meta = {k: v for k, v in entry.items() if k != "png"}
        self.send(
            {
                "type": "tile",
                "index": len(self._tile_entries) - 1,
                "entry": {**meta, "src": ""},
                "buffer_keys": ["src"],
            },
            buffers=[entry["png"]],
        )
        self.status = f"{len(self.overviews)} tile(s) on the map"

    def reload(self) -> None:
        """Re-read every tile from disk (after the simulation hijack)."""
        self._stacks = [
            _load_overview_channels(o, step=self._step_for(o)) for o in self.overviews
        ]
        self._retile()

    def push_snapshot(self) -> None:
        """Publish the complete tile list (a browser view asked to sync)."""
        self.tiles = [
            {**{k: v for k, v in e.items() if k != "png"}, "src": png_to_data_url(e["png"])}
            for e in self._tile_entries
        ]

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
        """The shared-compositor shape of the channel traits — sanitized.

        The ``channels`` trait is browser-writable, so its contents are
        input, not truth: a colour that does not parse or a range that is
        not two finite numbers falls back to a safe default instead of
        raising halfway through a recomposite (which would freeze the map
        at a stale state with no message).
        """
        from matplotlib.colors import to_rgb

        states = []
        for i, c in enumerate(self.channels):
            color = str(c.get("color", ""))
            try:
                to_rgb(color)
            except (ValueError, TypeError):
                color = CHANNEL_HEX[i % len(CHANNEL_HEX)]
            try:
                lo, hi = float(c.get("lo")), float(c.get("hi"))
            except (TypeError, ValueError):
                lo, hi = 0.0, 1.0
            if not (math.isfinite(lo) and math.isfinite(hi)):
                lo, hi = 0.0, 1.0
            states.append(
                {"color": color, "visible": bool(c.get("visible", True)), "range": (lo, hi)}
            )
        return states

    def _tile_entry(self, overview: dict, stack: Any) -> dict:
        cx, cy = overview["center_frame_um"]
        h_px, w_px = overview["image_size_px"]
        ps = float(overview["pixel_size_um"])
        w_um, h_um = w_px * ps, h_px * ps
        return {
            "png": png_bytes(composite_channels(stack, self._channel_states())),
            "x0": cx - w_um / 2.0,
            "y0": cy - h_um / 2.0,
            "w": w_um,
            "h": h_um,
            "label": overview.get("label"),
        }

    def _retile(self) -> None:
        self._tile_entries = [
            self._tile_entry(o, s) for o, s in zip(self.overviews, self._stacks, strict=True)
        ]
        self.push_snapshot()

    def _on_channels_changed(self, _change: Any) -> None:
        if self._stacks:
            self._retile()

    # --- targets on the map --------------------------------------------------

    def show_targets(self, targets: list[dict] | None, explorer: Any = None) -> None:
        """Overlay the discovered cells on the map (or clear with ``None``).

        Each target draws at its frame position, blue when it passes the
        gate and grey when it does not, so gating can be judged against the
        sample itself. Pass the target ``explorer`` to keep the colours
        live: every gate edit recolours the map. Hovering a mark shows that
        cell's crop in the side panel.
        """
        if self._marks_explorer is not None:
            self._marks_explorer.unobserve(self._on_gate_recoloured, names="gated_mask")
            self._marks_explorer = None
        self._targets = list(targets or [])
        self._mark_crop_cache = {}
        if explorer is not None and self._targets:
            self._marks_explorer = explorer
            explorer.observe(self._on_gate_recoloured, names="gated_mask")
        self._refresh_marks()

    def _on_gate_recoloured(self, _change: Any) -> None:
        self._refresh_marks()

    def _refresh_marks(self) -> None:
        if not self._targets:
            self.marks = []
            self.mark_hover = {}
            return
        explorer = self._marks_explorer
        mask = (
            explorer._mask_from_gate() if explorer is not None else [True] * len(self._targets)
        )
        self.marks = [
            {"x": float(t["x"]), "y": float(t["y"]), "gated": bool(keep)}
            for t, keep in zip(self._targets, mask, strict=True)
        ]

    def _serve_mark_hover(self, content: dict) -> None:
        try:
            index = int(content.get("index"))
        except (TypeError, ValueError, OverflowError):
            return
        if not 0 <= index < len(self._targets):
            return
        if index not in self._mark_crop_cache:
            crop = crop_for_target(
                self._targets[index], dict(enumerate(self.overviews)), crop_um=60.0
            )
            source = self._targets[index].get("source") or {}
            self._mark_crop_cache[index] = {
                "index": index,
                "src": "" if crop is None else png_data_url(crop),
                "title": f"target {index} (tile {source.get('naming_p', '?')})",
            }
        self.mark_hover = self._mark_crop_cache[index]

    # --- display settings ----------------------------------------------------

    def save_display(self, path: Any) -> None:
        """Write the channel display settings (colours/ranges) to a JSON file.

        Together with :meth:`load_display`, this survives a kernel restart:
        save into the run folder, and the next session shows the map the
        way you left it.
        """
        import json
        from pathlib import Path

        Path(path).write_text(json.dumps(list(self.channels), indent=2), encoding="utf-8")

    def load_display(self, path: Any) -> None:
        """Restore channel display settings saved by :meth:`save_display`.

        The loaded values pass through the same sanitizing as browser edits,
        so a hand-edited or stale file degrades to defaults instead of
        breaking the map.
        """
        import json
        from pathlib import Path

        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(loaded, list):
            raise ValueError(f"{path} does not hold a channel settings list")
        self.channels = loaded  # the observer recomposites (sanitized)

    def handle_message(self, content: dict) -> None:
        if content.get("type") == "mark":
            self._serve_mark_hover(content)
            return
        # The viewer has no hardware actions; nothing else arrives today.
        self.status = f"unknown message: {content.get('type')}"


# ---------------------------------------------------------------------------
# 2 · Focus picker
# ---------------------------------------------------------------------------


class FocusPickerReact(_ZmartWidget):
    """Pick focus points, measure them, and watch the map grow — React app.

    Click the map to add a point; click a point to remove it; **Measure**
    autofocuses at every point through the controller session, and the
    fitted surface streams in as a heatmap, refining after every measured
    point. Points already measured this session are reused; **Measure
    fresh** re-drives the stage through every point (use it when the focus
    may have drifted). ``require_focus()`` hands the surface to the rest
    of the run, exactly like the matplotlib picker.

    The map is drawn with +x to the right and +y downwards — the same
    orientation as the overview map, so tiles and focus points line up
    between the two figures.
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

  const [readOnly] = useTrait(model, "read_only");
  return h("div", { style: { ...card, width: W + 24 } },
    h("div", { style: { display: "flex", alignItems: "center", gap: 10, marginBottom: 8 } },
      readOnly ? pill("read-only view") : h("button", { style: btn(busy), disabled: busy,
        onClick: () => model.send({ type: "measure" }) },
        busy ? "measuring..." : "Measure focus"),
      readOnly ? null : h("button", {
        title: "forget this session's measurements and re-drive every point",
        style: { ...btn(busy), background: busy ? T.edge : T.bg, color: T.dim,
                 border: `1px solid ${T.edge}` }, disabled: busy,
        onClick: () => model.send({ type: "measure", fresh: true }) },
        "Measure fresh"),
      busy && !readOnly ? h("button", {
        title: "stop cleanly before the next point (nothing is committed)",
        style: { ...btn(false), background: T.bad, color: "#450a0a" },
        onClick: () => model.send({ type: "cancel" }) }, "Cancel") : null,
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
        width: 14, height: 14, fill: q.fill || "none", stroke: T.accent, strokeWidth: 1.5,
        style: { transition: "fill 0.3s" } })),
      points.map((p, i) => {
        const m = measured[i];
        return h("g", { key: `p${i}`, style: { cursor: "pointer" },
            onClick: (e) => { e.stopPropagation(); if (!busy) setPoints(points.filter((_, k) => k !== i)); } },
          h("circle", { cx: X(p.x), cy: Y(p.y), r: 7, fill: m ? T.good : T.bad,
            stroke: "#000", strokeWidth: 1.5 }),
          m ? h("text", { x: X(p.x) + 10, y: Y(p.y) - 8, fill: T.ink, fontSize: 11 },
            m.z_um.toFixed(1) +
            (m.residual_um === undefined ? "" : ` (Δ${m.residual_um.toFixed(1)})`)) : null);
      })),
    h("div", { style: { color: T.dim, fontSize: 12, marginTop: 6 } },
      "click: add a focus point · click a point: remove it · squares: overview positions" +
      " · +x right, +y down (same as the overview map)"));
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
        self.squares = [
            {"x": float(p["x"]), "y": float(p["y"]), "fill": ""} for p in (positions or [])
        ]
        self.focus: Any = None
        self._measured_points: list[dict] | None = None
        # Autofocus results already collected this session, keyed by the
        # point's exact coordinates — re-measuring reuses them, so editing
        # the points only sends the stage to the NEW or moved ones.
        self._af_cache: dict[tuple[float, float], dict] = {}
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
        # The per-point autofocus cache survives (the next Measure reuses
        # it); the fitted surface and its display do not.
        self.focus = None
        self.measured = []
        self.heatmap = {}
        self._measured_points = None
        self.squares = [{**q, "fill": ""} for q in self.squares]

    def handle_message(self, content: dict) -> None:
        if content.get("type") != "measure":
            self.status = f"unknown message: {content.get('type')}"
            return
        if self._debounced():
            return
        self._run_guarded(lambda: self.measure(fresh=bool(content.get("fresh"))))

    def measure(self, *, fresh: bool = False) -> Any:
        """Autofocus at every picked point and fit the surface (scriptable).

        The same run the **Measure** button starts, with the same busy
        guard and click-debounce bookkeeping — a click queued behind a
        scripted run is ignored just like one queued behind a button run.
        ``fresh=True`` forgets this session's cached measurements first,
        so every point re-drives the stage (use it when the focus may
        have drifted since the points were last measured). Returns the
        fitted focus surface.
        """
        if not self.points:
            raise RuntimeError("no focus points are picked yet — click the map first")
        if fresh:
            self._af_cache.clear()
        return self._hardware_run(self._measure)

    def _measure(self) -> Any:
        points = [dict(p) for p in self.points]
        self._invalidate()
        # Only the points without a cached result visit the stage; the rest
        # are reused from this session's earlier measurements.
        fresh_points = [
            p for p in points if (float(p["x"]), float(p["y"])) not in self._af_cache
        ]

        def _collected() -> list[dict]:
            return [
                self._af_cache[(float(p["x"]), float(p["y"]))]
                for p in points
                if (float(p["x"]), float(p["y"])) in self._af_cache
            ]

        def _fit_and_show() -> None:
            collected = _collected()
            self.focus = fit_focus_surface(collected)
            # Each point also reports how far it sits from the fit — one
            # large residual usually means that autofocus landed badly and
            # is quietly bending the whole surface.
            from .._focus_surface import residuals_um

            self.measured = residuals_um(self.focus)
            self.heatmap = self._render_heatmap()
            self._tint_squares()

        def _show_fresh_point(measurement: dict) -> None:
            self._af_cache[(measurement["x_um"], measurement["y_um"])] = measurement
            _fit_and_show()
            self.status = f"measuring... {len(self.measured)} of {len(points)} points"

        try:
            if fresh_points:
                measure_focus(
                    self.session, fresh_points, af_job=self.af_job, start_z=self.start_z,
                    on_point=_show_fresh_point,
                    cancel=lambda: self._cancel_requested,
                )
            _fit_and_show()
        except Exception:
            # A half-measured run must not leave a plausible-looking surface
            # on ``self.focus`` — a script reading it would fit z to a
            # partial point set. (The cache keeps the honest per-point
            # results; the next Measure reuses them.)
            self._invalidate()
            raise
        self._measured_points = points
        worst = worst_residual_um(self.focus)
        residual_note = (
            "" if worst is None else f"; largest fit residual {worst[1]:+.1f} µm at point {worst[0]}"
        )
        self.status = (
            f"focus surface fitted ({self.focus.model}, {len(points)} pts — "
            f"{len(fresh_points)} new, {len(points) - len(fresh_points)} reused"
            f"{residual_note})"
        )
        return self.focus

    def _tint_squares(self) -> None:
        """Colour each overview tile marker by the fitted z at its centre."""
        if not self.squares or self.focus is None:
            return
        from matplotlib import colormaps
        from matplotlib.colors import to_hex

        zs = [float(self.focus.z_at(q["x"], q["y"])) for q in self.squares]
        z_lo, z_hi = min(zs), max(zs)
        span = z_hi - z_lo if z_hi > z_lo else 1.0
        self.squares = [
            {**q, "fill": to_hex(colormaps["viridis"]((z - z_lo) / span))}
            for q, z in zip(self.squares, zs, strict=True)
        ]

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

    The gate decision is always recomputed in Python from the raw ``gate``
    trait at the moment it is used. The ``gated_mask`` trait is a display
    output only — nothing the browser writes into it can change which
    targets the acquisition step samples.
    """

    features = traitlets.List().tag(sync=True)
    x_feature = traitlets.Unicode().tag(sync=True)
    y_feature = traitlets.Unicode().tag(sync=True)
    dots = traitlets.List().tag(sync=True)
    gate = traitlets.Dict().tag(sync=True)
    gated_mask = traitlets.List().tag(sync=True)
    hover = traitlets.Dict().tag(sync=True)
    #: 20-bin histograms of the current axes (display only), so thresholds
    #: are set against the feature's distribution rather than blind.
    hist = traitlets.Dict().tag(sync=True)

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
  const [hist] = useTrait(model, "hist");
  const [readOnly] = useTrait(model, "read_only");
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
    next[axis][i] = v;
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
          onPointerDown: (e) => {
            if (readOnly) return;
            lasso.current = [toData(e, e.currentTarget)]; setTrail(lasso.current);
          },
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
        (hist.x || []).map((v, i, arr) => {
          const bw = (W - 2 * pad) / arr.length;
          return h("rect", { key: `hx${i}`, x: pad + i * bw, width: Math.max(bw - 1, 1),
            y: H - pad - v * 26, height: v * 26,
            fill: "rgba(56,189,248,0.22)" });
        }),
        (hist.y || []).map((v, i, arr) => {
          const bh = (H - 2 * pad) / arr.length;
          return h("rect", { key: `hy${i}`, x: pad, width: v * 26,
            y: H - pad - (i + 1) * bh, height: Math.max(bh - 1, 1),
            fill: "rgba(56,189,248,0.22)" });
        }),
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
        h(NumBox, { value: rng[0], width: 72, onCommit: (v) => setRange("x", 0, v) }),
        h(NumBox, { value: rng[1], width: 72, onCommit: (v) => setRange("x", 1, v) }),
        h("span", { style: { color: T.dim } }, yf),
        h(NumBox, { value: rngY[0], width: 72, onCommit: (v) => setRange("y", 0, v) }),
        h(NumBox, { value: rngY[1], width: 72, onCommit: (v) => setRange("y", 1, v) }))),
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
        self._crop_cache: dict[int, dict] = {}
        self._resetting_gate = False
        self.features = _numeric_features(targets)
        self.x_feature = self.features[0]
        self.y_feature = self.features[1] if len(self.features) > 1 else self.features[0]
        self.observe(self._on_axes_changed, names=["x_feature", "y_feature"])
        self.observe(self._on_gate_changed, names="gate")
        self._recompute(reset_gate=True)

    @property
    def gated(self) -> list[dict]:
        """The targets inside the gate — what the acquisition step samples.

        Recomputed here, from the raw gate, every time it is read. The
        synced ``gated_mask`` trait can be written by anything running in
        the browser page, so it is display output — never the basis for
        which targets the microscope visits.
        """
        mask = self._mask_from_gate()
        if list(self.gated_mask) != mask:
            # Heal the display if something scribbled over the mask.
            self.gated_mask = mask
        return [t for t, keep in zip(self.targets, mask, strict=True) if keep]

    def _on_axes_changed(self, _change: Any) -> None:
        # A lasso drawn in the old feature space would gate nonsense in the
        # new one, so switching axes clears the whole gate (like matplotlib).
        self._recompute(reset_gate=True)

    def _on_gate_changed(self, _change: Any) -> None:
        if not self._resetting_gate:
            self._recompute(reset_gate=False)

    @staticmethod
    def _finite_pair(value: Any) -> tuple[float, float] | None:
        """``[lo, hi]`` as two finite floats, or ``None`` for anything else.

        The gate arrives from the browser, so a threshold that does not
        parse (a half-typed number, a null) simply does not gate — the
        same as an empty box — rather than raising mid-update and freezing
        the widget at a stale state.
        """
        try:
            lo, hi = float(value[0]), float(value[1])
        except (TypeError, ValueError, IndexError, KeyError):
            return None
        if not (math.isfinite(lo) and math.isfinite(hi)):
            return None
        return (lo, hi)

    def _mask_from_gate(self) -> list[bool]:
        """Which targets pass the current gate (thresholds AND lasso)."""
        gate = self.gate or {}
        x_range = self._finite_pair(gate.get("x"))
        y_range = self._finite_pair(gate.get("y"))
        path = None
        lasso = gate.get("lasso")
        if isinstance(lasso, list) and len(lasso) >= 3:
            try:
                from matplotlib.path import Path as MplPath

                path = MplPath([(float(p[0]), float(p[1])) for p in lasso])
            except (TypeError, ValueError, IndexError):
                path = None
        mask = []
        for target in self.targets:
            fx = _feature_value(target, self.x_feature)
            fy = _feature_value(target, self.y_feature)
            keep = True
            if x_range:
                keep &= x_range[0] <= fx <= x_range[1]
            if y_range:
                keep &= y_range[0] <= fy <= y_range[1]
            if keep and path is not None:
                keep = bool(path.contains_point((fx, fy)))
            mask.append(bool(keep))
        return mask

    @staticmethod
    def _histogram(values: list[float], bins: int = 20) -> list[float]:
        """Bin counts normalized to 0..1 — a slim distribution backdrop."""
        lo, hi = min(values), max(values)
        if hi <= lo:
            return [1.0] + [0.0] * (bins - 1)
        counts = [0] * bins
        for v in values:
            k = min(int((v - lo) / (hi - lo) * bins), bins - 1)
            counts[k] += 1
        peak = max(counts)
        return [c / peak for c in counts]

    def _recompute(self, *, reset_gate: bool) -> None:
        self.dots = [
            {
                "fx": _feature_value(t, self.x_feature),
                "fy": _feature_value(t, self.y_feature),
            }
            for t in self.targets
        ]
        self.hist = {
            "x": self._histogram([d["fx"] for d in self.dots]),
            "y": self._histogram([d["fy"] for d in self.dots]),
        }
        if reset_gate:
            # Quietly: the observer would otherwise run a second, redundant
            # recompute for the very reset we are in the middle of.
            self._resetting_gate = True
            try:
                self.gate = {}
            finally:
                self._resetting_gate = False
        self.gated_mask = self._mask_from_gate()
        self.status = "thresholds AND lasso gate together"

    def save_gate(self, path: Any) -> None:
        """Write the current gate (axes + thresholds + lasso) to a JSON file.

        A repeat experiment usually wants yesterday's thresholds: save the
        gate into the run folder and :meth:`load_gate` it next session.
        """
        import json
        from pathlib import Path

        payload = {
            "x_feature": self.x_feature,
            "y_feature": self.y_feature,
            "gate": dict(self.gate or {}),
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_gate(self, path: Any) -> None:
        """Restore a gate saved by :meth:`save_gate`.

        The axes are set first (which clears any stale gate, exactly like a
        manual axis switch), then the saved thresholds and lasso apply. The
        values pass through the same sanitizing as browser edits, so a
        hand-edited file degrades to "does not gate" instead of breaking
        the explorer. Features missing from this target set raise a clear
        error rather than silently gating on the wrong axis.
        """
        import json
        from pathlib import Path

        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        for key in ("x_feature", "y_feature"):
            name = payload.get(key)
            if name not in self.features:
                raise ValueError(
                    f"{path} gates on feature {name!r}, which these targets do not "
                    f"have (available: {self.features})"
                )
        self.x_feature = payload["x_feature"]
        self.y_feature = payload["y_feature"]
        gate = payload.get("gate")
        self.gate = dict(gate) if isinstance(gate, dict) else {}

    def handle_message(self, content: dict) -> None:
        if content.get("type") != "hover":
            self.status = f"unknown message: {content.get('type')}"
            return
        # The index comes from the browser: validate it rather than trusting
        # it (OverflowError covers JSON numbers like 1e999 -> infinity).
        try:
            index = int(content.get("index"))
        except (TypeError, ValueError, OverflowError):
            return
        if not 0 <= index < len(self.targets):
            return
        if index not in self._crop_cache:
            # Cropping reads the full-resolution tile from disk — cache it,
            # or a fast mouse over many dots queues seconds of disk reads
            # ahead of the next button press.
            crop = crop_for_target(self.targets[index], self.overviews, crop_um=self.crop_um)
            source = self.targets[index].get("source") or {}
            self._crop_cache[index] = {
                "index": index,
                "src": "" if crop is None else png_data_url(crop),
                "title": f"target {index} (tile {source.get('naming_p', '?')})",
            }
        self.hover = self._crop_cache[index]


# ---------------------------------------------------------------------------
# 4 · Acquisition gallery
# ---------------------------------------------------------------------------


class AcquisitionGalleryReact(_ZmartWidget):
    """Acquire N random gated targets and review same-scale pairs — React app.

    Type a count and press **Acquire**: Python samples the explorer's live
    gate, drives the microscope through the same gated target-capture path
    as the scripts, and each overview/target pair fades into the gallery
    the moment it is saved. ``picked`` / ``records`` commit only when the
    whole run succeeds, exactly like the matplotlib gallery — and starting
    a new run clears the previous result first, so a failed re-run can
    never leave the old run masquerading as "the result".
    """

    rows = traitlets.List().tag(sync=True)
    gate_count = traitlets.Int(0).tag(sync=True)
    default_count = traitlets.Int(5).tag(sync=True)
    #: Per-row curation: "good", "bad", or None — the operator's own QC
    #: record of the run (display-synced; Python owns the truth).
    verdicts = traitlets.List().tag(sync=True)

    _esm = REACT_PRELUDE + """
function App({ model }) {
  const rows = useStream(model, "rows", "row");
  const [busy] = useTrait(model, "busy");
  const [status] = useTrait(model, "status");
  const [gateCount] = useTrait(model, "gate_count");
  const [defaultCount] = useTrait(model, "default_count");
  const [verdicts] = useTrait(model, "verdicts");
  const [readOnly] = useTrait(model, "read_only");
  const [count, setCount] = React.useState(String(defaultCount));

  const verdictBtn = (i, value, label, colour) => h("button", {
    title: value === "good" ? "mark this pair as good" : "mark this pair as bad",
    onClick: () => model.send({ type: "verdict", index: i,
      value: verdicts[i] === value ? null : value }),
    style: { ...btn(false), padding: "2px 10px",
             background: verdicts[i] === value ? colour : T.edge,
             color: verdicts[i] === value ? "#082f49" : T.dim } }, label);

  return h("div", { style: { ...card, width: 700 } },
    h("style", null, "@keyframes zin { from { opacity: 0; transform: translateY(8px);} to { opacity: 1; transform: none;} }"),
    h("div", { style: { display: "flex", gap: 10, alignItems: "center", marginBottom: 10 } },
      readOnly ? pill("read-only view") : h("span", { style: { color: T.dim } }, "how many"),
      readOnly ? null : h("input", { style: inp, value: count,
        onChange: (e) => setCount(e.target.value) }),
      readOnly ? null : h("button", { style: btn(busy), disabled: busy,
        onClick: () => model.send({ type: "acquire", count }) },
        busy ? "acquiring..." : "Acquire"),
      busy && !readOnly ? h("button", {
        title: "stop cleanly before the next target (nothing is committed)",
        style: { ...btn(false), background: T.bad, color: "#450a0a" },
        onClick: () => model.send({ type: "cancel" }) }, "Cancel") : null,
      pill(`${gateCount} in the gate`),
      h("span", { style: { color: T.dim, fontSize: 12 } }, status)),
    rows.map((r, i) => h("div", { key: i, style: {
        display: "flex", gap: 10, marginBottom: 10, animation: "zin 0.35s ease" } },
      [["low", r.low_title], ["high", r.high_title]].map(([side, title]) =>
        h("div", { key: side, style: { flex: 1 } },
          h("img", { src: r[side + "_src"], style: { width: "100%", borderRadius: 10,
            imageRendering: "pixelated", border: `1px solid ${T.edge}` } }),
          h("div", { style: { color: T.dim, fontSize: 12, marginTop: 2 } }, title))),
      readOnly ? null : h("div", { style: { display: "flex", flexDirection: "column",
          gap: 6, justifyContent: "center" } },
        verdictBtn(i, "good", "✓", T.good),
        verdictBtn(i, "bad", "✗", T.bad)))));
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
        self._row_entries: list[dict] = []
        self.gate_count = len(self._gated())
        self.status = "type a count and press Acquire"

    def _gated(self) -> list[dict]:
        return list(getattr(self.source, "gated", self.source))

    def push_snapshot(self) -> None:
        """Publish the complete row list (a browser view asked to sync)."""
        self.rows = [self._row_with_data_urls(e) for e in self._row_entries]

    @staticmethod
    def _row_with_data_urls(entry: dict) -> dict:
        meta = {k: v for k, v in entry.items() if k not in ("low_png", "high_png")}
        meta["low_src"] = png_to_data_url(entry["low_png"]) if entry.get("low_png") else ""
        meta["high_src"] = png_to_data_url(entry["high_png"]) if entry.get("high_png") else ""
        return meta

    def set_verdict(self, index: int, value: str | None) -> None:
        """Record the operator's judgement of one pair: "good", "bad", or None.

        This is the run's QC record — :meth:`save_curation` writes it next
        to the images. Scriptable and also driven by the ✓/✗ buttons.
        """
        if value not in ("good", "bad", None):
            raise ValueError('a verdict is "good", "bad", or None')
        if not 0 <= int(index) < len(self._row_entries):
            raise ValueError(f"no gallery row {index} to judge")
        verdicts = list(self.verdicts)
        verdicts[int(index)] = value
        self.verdicts = verdicts

    def save_curation(self, output_root: Any) -> Any:
        """Write the verdicts to ``curation.json`` in the run folder.

        One entry per acquired pair: the target's position label and the
        verdict ("good"/"bad"/null). Returns the path written.
        """
        import json
        from pathlib import Path

        root = Path(output_root)
        root.mkdir(parents=True, exist_ok=True)
        path = root / "curation.json"
        rows = [
            {
                "index": i,
                "position_label": (r.get("position_label", None)),
                "verdict": v,
            }
            for i, (r, v) in enumerate(zip(self.records, list(self.verdicts), strict=False))
        ]
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        return path

    def handle_message(self, content: dict) -> None:
        kind = content.get("type")
        if kind == "verdict":
            # Curation is metadata, not hardware — but the input is still
            # browser input, so it is validated, never obeyed blindly.
            try:
                index = int(content.get("index"))
            except (TypeError, ValueError, OverflowError):
                return
            value = content.get("value")
            if value not in ("good", "bad", None):
                return
            if 0 <= index < len(self._row_entries):
                self.set_verdict(index, value)
            return
        if kind != "acquire":
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
        """Randomly pick ``count`` gated targets, acquire, stream the pairs.

        Scriptable, with the same busy guard and click-debounce bookkeeping
        as the **Acquire** button — a click queued in the browser behind a
        scripted run is ignored just like one queued behind a button run.
        """
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
        return self._hardware_run(lambda: self._acquire(picked, len(gated)))

    def _acquire(self, picked: list[dict], gated_count: int) -> list[dict]:
        # This run replaces the previous result, so the previous result must
        # stop being "the result" now: if this run fails halfway, a later
        # summary cell must not quietly describe the OLD run while the
        # gallery shows the new, failed one.
        self.picked = []
        self.records = []
        self._row_entries = []
        self.rows = []
        self.verdicts = [None] * len(picked)

        def _show_fresh_pair(index: int, _position: dict, record: dict) -> None:
            entry = self._row_entry(picked[index - 1], record)
            self._row_entries.append(entry)
            # One message per fresh pair — never a resend of the rows so
            # far, with the two images as binary buffers.
            meta = {k: v for k, v in entry.items() if k not in ("low_png", "high_png")}
            self.send(
                {
                    "type": "row",
                    "index": index - 1,
                    "entry": {**meta, "low_src": "", "high_src": ""},
                    "buffer_keys": ["low_src", "high_src"],
                },
                buffers=[entry.get("low_png") or b"", entry.get("high_png") or b""],
            )
            self.status = f"acquired {index} of {len(picked)} target(s)..."

        records = acquire_targets(
            self.session,
            picked,
            state=self.state,
            focus=self.focus,
            options=self.options,
            on_record=_show_fresh_pair,
            cancel=lambda: self._cancel_requested,
        )
        if self.after_acquire is not None:
            self.after_acquire(records)
            # The hijack may have rewritten the saved images: re-read them.
            self._row_entries = [
                self._row_entry(t, r) for t, r in zip(picked, records, strict=True)
            ]
        self.picked = picked
        self.records = records
        # The run is complete: publish the full rows snapshot so any view —
        # including one opened later — has the whole gallery.
        self.push_snapshot()
        self.status = f"acquired {len(records)} of {gated_count} gated target(s)"
        return records

    def _row_entry(self, target: dict, record: dict) -> dict:
        pair = pair_images(target, record, self.overviews)
        source = target.get("source") or {}
        if pair is None:
            return {
                "low_png": b"",
                "high_png": b"",
                "position_label": record.get("position_label"),
                "low_title": "no image in this record",
                "high_title": "",
            }
        low, high, width_um, height_um = pair
        return {
            "low_png": png_bytes(shrink_to_budget(low, _PER_IMAGE_PIXEL_BUDGET)),
            "high_png": png_bytes(shrink_to_budget(high, _PER_IMAGE_PIXEL_BUDGET)),
            "position_label": record.get("position_label"),
            "low_title": (
                f"overview crop — tile {source.get('naming_p', '?')} "
                f"({width_um:.0f} × {height_um:.0f} um)"
            ),
            "high_title": f"target {record.get('position_label', '?')} — same window",
        }


# ---------------------------------------------------------------------------
# 5 · Run status
# ---------------------------------------------------------------------------


class RunStatusReact(_ZmartWidget):
    """A one-glance checklist of where the run stands.

    Call :meth:`refresh` with the notebook's ``globals()`` after any step
    and the checklist updates: what is done, what is still to do, and what
    deserves a second look (for example, a target job that equals the
    overview job). It only reads what the cells already created — it never
    talks to the microscope, so refreshing is always safe.
    """

    rows = traitlets.List().tag(sync=True)

    _esm = REACT_PRELUDE + """
function App({ model }) {
  const [rows] = useTrait(model, "rows");
  const [status] = useTrait(model, "status");
  const colours = { ok: T.good, todo: T.dim, warn: T.warn };
  const marks = { ok: "✓", todo: "·", warn: "!" };
  return h("div", { style: { ...card, width: 560 } },
    h("div", { style: { fontWeight: 700, marginBottom: 8 } }, "run status"),
    rows.map((r, i) => h("div", { key: i, style: {
        display: "flex", gap: 10, alignItems: "baseline", padding: "3px 0" } },
      h("span", { style: { color: colours[r.state] || T.dim, width: 14,
        fontWeight: 700, textAlign: "center" } }, marks[r.state] || "·"),
      h("span", { style: { width: 150, color: r.state === "todo" ? T.dim : T.ink } },
        r.label),
      h("span", { style: { color: T.dim, fontSize: 12 } }, r.detail))),
    h("div", { style: { color: T.dim, fontSize: 12, marginTop: 8 } },
      status || "re-run the status cell after any step to refresh"));
}
export default mount(App);
"""

    def refresh(self, ns: dict) -> RunStatusReact:
        """Rebuild the checklist from the notebook's variables (``globals()``)."""
        from .._run_status import run_status_rows

        self.rows = run_status_rows(ns)
        return self

    def handle_message(self, content: dict) -> None:
        self.status = f"unknown message: {content.get('type')}"


# ---------------------------------------------------------------------------
# 6 · Calibration check report
# ---------------------------------------------------------------------------


class CalibrationReportReact(_ZmartWidget):
    """The XY-calibration check's result as a readable panel.

    Feed it the report dict from ``finish_calibration_check``: it draws the
    per-site offset arrows on the ring, states the systematic error and the
    stage scatter in plain language, and — when ``acceptable_um`` is given —
    says outright whether the calibration is good enough for this run.
    """

    report = traitlets.Dict().tag(sync=True)
    acceptable_um = traitlets.Float(0.0).tag(sync=True)

    _esm = REACT_PRELUDE + """
function App({ model }) {
  const [report] = useTrait(model, "report");
  const [acceptable] = useTrait(model, "acceptable_um");
  const W = 340, H = 340, pad = 30;
  const sites = report.sites || [];
  const trusted = sites.filter((s) => s.trusted && s.dx_um !== null);
  const span = Math.max(...sites.map((s) => Math.hypot(s.x, s.y)), 1) * 1.15;
  const s = (W - 2 * pad) / (2 * span);
  const X = (x) => W / 2 + x * s, Y = (y) => H / 2 + y * s;
  // Offsets are micrometres on a millimetre-scale map: exaggerate to see.
  const mag = 0.15 * span / Math.max(...trusted.map((t) => Math.hypot(t.dx_um, t.dy_um)), 1e-9);
  const mean = Math.hypot(report.mean_dx_um || 0, report.mean_dy_um || 0);
  const verdict = !acceptable ? null : (mean <= acceptable
    ? { colour: T.good, text: `within the ±${acceptable} um you asked for` }
    : { colour: T.bad, text: `LARGER than the ±${acceptable} um you asked for — ` +
        "re-run the objective-pair calibration before trusting cross-objective moves" });

  return h("div", { style: { ...card, display: "flex", gap: 14, width: W + 320 } },
    h("svg", { width: W, height: H, style: { background: T.bg, borderRadius: 10, flex: "none" } },
      h("circle", { cx: W / 2, cy: H / 2, r: span * s * 0.001 || 1, fill: T.edge }),
      sites.map((q, i) => q.trusted && q.dx_um !== null
        ? h("g", { key: i },
            h("line", { x1: X(q.x), y1: Y(q.y),
              x2: X(q.x + q.dx_um * mag), y2: Y(q.y + q.dy_um * mag),
              stroke: T.accent, strokeWidth: 2 }),
            h("circle", { cx: X(q.x), cy: Y(q.y), r: 3, fill: T.accent }))
        : h("g", { key: i },
            h("line", { x1: X(q.x) - 4, y1: Y(q.y) - 4, x2: X(q.x) + 4, y2: Y(q.y) + 4,
              stroke: T.dim, strokeWidth: 1.5 }),
            h("line", { x1: X(q.x) - 4, y1: Y(q.y) + 4, x2: X(q.x) + 4, y2: Y(q.y) - 4,
              stroke: T.dim, strokeWidth: 1.5 }))),
      h("text", { x: 10, y: H - 10, fill: T.dim, fontSize: 11 },
        "arrows exaggerated · × = not trusted")),
    Object.keys(report).length === 0
      ? h("div", { style: { color: T.dim } }, "no report yet — run the check's two cells first")
      : h("div", null,
          h("div", { style: { fontWeight: 700, marginBottom: 8 } }, "objective calibration"),
          h("div", { style: { marginBottom: 6 } },
            `systematically off by ${mean.toFixed(2)} um ` +
            `(x ${(report.mean_dx_um || 0).toFixed(2)}, y ${(report.mean_dy_um || 0).toFixed(2)})`),
          h("div", { style: { color: T.dim, marginBottom: 6 } },
            `positive x means objective 2 lands towards +x of objective 1`),
          h("div", { style: { marginBottom: 6 } },
            `stage scatter ${(report.stage_scatter_rms_um || 0).toFixed(2)} um rms ` +
            `over ${report.n_trusted || 0} of ${report.n_sites || 0} sites`),
          verdict ? h("div", { style: { color: verdict.colour, fontWeight: 600,
            marginTop: 10 } }, verdict.text) : null));
}
export default mount(App);
"""

    def __init__(self, report: dict | None = None, *, acceptable_um: float | None = None) -> None:
        super().__init__()
        self.report = dict(report or {})
        self.acceptable_um = float(acceptable_um) if acceptable_um else 0.0

    def handle_message(self, content: dict) -> None:
        self.status = f"unknown message: {content.get('type')}"
