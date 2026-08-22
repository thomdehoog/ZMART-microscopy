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
widget answers a ``sync`` message with a reset plus bounded binary replay so
re-opened views catch up. ``PROTOCOL.md`` in this package documents every trait
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

import copy
import math
import time
from collections.abc import Callable
from typing import Any

from ._support import (
    CHANNEL_HEX,
    CHANNEL_HEX_COLORBLIND,
    REACT_PRELUDE,
    heatmap_data_url,
    jpeg_bytes,
    png_bytes,
    png_data_url_ranged,
    require_anywidget,
    shrink_to_budget,
)

require_anywidget()

import anywidget  # noqa: E402
import traitlets  # noqa: E402

from .._acquisition_widget import _eta_text, pair_images  # noqa: E402
from .._discovery_widget import (  # noqa: E402
    _feature_value,
    _matching_target_indices,
    _numeric_features,
    crop_for_target,
)
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

# A whole overview map has a budget too, not just each tile in it. A browser
# holds every tile it is showing as uncompressed pixels, so what it has to
# cope with is the total across the map — and a large scan can bring thousands
# of tiles rather than the two dozen of a small one. Sharing this budget out
# over the expected tile count keeps a small map exactly as detailed as it has
# always been, and lets a large one stay coarse enough to open at all: about
# 40 megapixels of map works out near 160 MB of pixels in the browser.
_MAP_PIXEL_BUDGET = 40_000_000

# However large the scan, a tile is never shrunk below roughly 64x64. Past
# that a tile stops showing anything at all, and a map of blank squares is
# not worth the memory it saves.
_MIN_TILE_PIXEL_BUDGET = 4_096

# Catch-up snapshots can contain dozens of images at once. Keep their copies
# smaller than the live, one-at-a-time stream: 250k RGB pixels is enough for
# the 640x520 notebook viewport and bounds a 25-tile noisy snapshot to roughly
# 20 MiB of raw PNG buffers instead of a 100+ MiB base64 trait.
_SNAPSHOT_IMAGE_PIXEL_BUDGET = 250_000

# Gallery panels render at roughly 330 px wide. A 250k-pixel display copy is
# already larger than the UI while keeping ten two-image rows bounded.
_GALLERY_IMAGE_PIXEL_BUDGET = 250_000


class _ZmartWidget(anywidget.AnyWidget):
    """Base: routes anywidget messages to ``handle_message`` (testable)."""

    status = traitlets.Unicode("").tag(sync=True)
    #: Display mirror of a run in progress (buttons disable on it). The
    #: run-overlap interlock is the private ``_busy`` flag — this trait is
    #: healed if the page rewrites it, like ``read_only`` below.
    busy = traitlets.Bool(False).tag(sync=True)
    #: Display-only mirror of the read-only state (hides buttons in the
    #: browser). The ENFORCEMENT is the private flag below — a synced trait
    #: can be rewritten by anything in the page, so it is never the check.
    read_only = traitlets.Bool(False).tag(sync=True)
    _read_only_input_traits: tuple[str, ...] = ()
    #: Message kinds that stay answered on a frozen widget because they only
    #: READ state to serve a display (a hover preview). Never list a kind
    #: here that changes state or touches hardware.
    _read_only_safe_messages: tuple[str, ...] = ()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._last_run_ended: float | None = None
        self._hardware_allowed = True
        self._cancel_requested = False
        self._busy = False
        self._restoring_busy_trait = False
        self._restoring_read_only_input = False
        self._restoring_read_only_trait = False
        self._read_only_inputs: dict[str, Any] = {}
        self.on_msg(self._route_message)
        self.observe(self._heal_read_only_trait, names="read_only")
        self.observe(self._heal_busy_trait, names="busy")

    def _set_busy(self, value: bool) -> None:
        """Set the Python-private run flag and mirror it to the display."""
        self._busy = value
        self._restoring_busy_trait = True
        try:
            self.busy = value
        finally:
            self._restoring_busy_trait = False

    def _heal_busy_trait(self, change: dict) -> None:
        """``busy`` is a display mirror, never input.

        The run-overlap interlock and the cancel path read the private
        flag; if page code rewrites the synced trait (faking a run, or
        hiding a real one), restore the truth so every view stays honest.
        """
        if self._restoring_busy_trait or change["new"] == self._busy:
            return
        self._restoring_busy_trait = True
        try:
            self.busy = self._busy
        finally:
            self._restoring_busy_trait = False

    def make_read_only(self) -> None:
        """Freeze this widget model into a read-only display.

        This freezes the whole anywidget MODEL, including every browser view
        attached to it. Hardware messages and scripted calls are refused in
        Python, and browser-writable input traits are restored if a page
        script tries to change them. It is a model-wide safety lock, not a
        per-tab permission system.
        """
        if not self._hardware_allowed:
            self.read_only = True
            return
        self._hardware_allowed = False
        self._read_only_inputs = {
            name: copy.deepcopy(getattr(self, name)) for name in self._read_only_input_traits
        }
        if self._read_only_input_traits:
            self.observe(self._reject_read_only_input, names=list(self._read_only_input_traits))
        self.read_only = True

    def _heal_read_only_trait(self, change: dict) -> None:
        """Keep the display mirror honest in both directions.

        The synced trait is only a mirror of the Python-private lock. A
        forged ``false`` on a frozen widget must not advertise controls
        that would be refused — and a forged ``true`` on a live widget
        must not hide the buttons in every tab while hardware is in fact
        still allowed.
        """
        if self._restoring_read_only_trait:
            return
        expected = not self._hardware_allowed
        if change["new"] is expected:
            return
        self._restoring_read_only_trait = True
        try:
            self.read_only = expected
        finally:
            self._restoring_read_only_trait = False

    def _reject_read_only_input(self, change: dict) -> None:
        """Restore a browser input changed after the model was locked."""
        if self._hardware_allowed or self._restoring_read_only_input:
            return
        name = change["name"]
        expected = self._read_only_inputs[name]
        if change["new"] == expected:
            return
        self._restoring_read_only_input = True
        try:
            setattr(self, name, copy.deepcopy(expected))
        finally:
            self._restoring_read_only_input = False
        self.status = "this widget is read-only — state changes are disabled"

    def _set_trusted_input(self, name: str, value: Any) -> None:
        """Write a browser-writable input trait from trusted Python code.

        The lock cannot tell a browser write from a Python one — both
        arrive as the same trait change — so trusted display updates (for
        example, the first tile initialising the channel controls) mark
        themselves with the restorer's own flag. When the widget is frozen,
        the stored baseline moves along too, so later browser edits are
        still healed back to this new, correct value.
        """
        self._restoring_read_only_input = True
        try:
            setattr(self, name, value)
        finally:
            self._restoring_read_only_input = False
        if not self._hardware_allowed and name in self._read_only_inputs:
            self._read_only_inputs[name] = copy.deepcopy(value)

    def _route_message(self, _widget: Any, content: Any, _buffers: Any) -> None:
        # Anything can arrive on this channel; a non-dict is simply noise.
        if not isinstance(content, dict):
            return
        kind = content.get("type")
        if kind == "sync":
            # A freshly mounted browser view asks for a bounded replay.
            self.push_snapshot()
            return
        if not self._hardware_allowed and kind not in self._read_only_safe_messages:
            self.status = "this view is read-only — hardware actions are disabled"
            return
        if kind == "cancel":
            self.request_cancel()
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
        if not self._hardware_allowed:
            self.status = "this widget is read-only — cancellation is disabled"
            return
        if self._busy:
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
        # The interlock reads the PRIVATE flag: the synced ``busy`` trait is
        # a healed display mirror, so a page script can neither fake a run
        # (blocking every real one) nor hide one from the overlap guard.
        if self._busy:
            raise RuntimeError("a run is already in progress")
        self._cancel_requested = False
        self._set_busy(True)
        try:
            return work()
        finally:
            self._set_busy(False)
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
    _read_only_input_traits = ("channels",)
    #: Hovering a mark only serves a crop preview — an observer may browse.
    _read_only_safe_messages = ("mark",)

    _esm = (
        REACT_PRELUDE
        + """
function App({ model }) {
  const tiles = useStream(model, "tiles", "tile");
  const [channels, setChannels] = useTrait(model, "channels");
  const [marks] = useTrait(model, "marks");
  const [markHover] = useTrait(model, "mark_hover");
  const [status] = useTrait(model, "status");
  const [readOnly] = useTrait(model, "read_only");
  const view = React.useRef({ scale: 1, tx: 0, ty: 0, fitted: 0, user: false });
  const [, bump] = React.useReducer((n) => n + 1, 0);
  const [cursor, setCursor] = React.useState(null);
  const [holding, setHolding] = React.useState(null);
  const box = React.useRef(null);
  const W = widgetPx(640), H = widgetPx(520);

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

  // Each tile is placed once, in micrometres, and never moved again: panning
  // and zooming are applied to the single layer that holds them (below). A map
  // built from thousands of tiles would crawl if every one of them had to be
  // repositioned on each mouse move, and it is the browser, not the
  // microscope, that would be the slow part. Because the tile list keeps its
  // identity between renders, this list is only rebuilt when a tile actually
  // arrives — dragging the map re-uses it untouched.
  const tileLayer = React.useMemo(
    () => tiles.map((t, i) =>
      h("img", { key: i, src: t.src, draggable: false, style: {
        position: "absolute", left: t.x0, top: t.y0, width: t.w, height: t.h,
        imageRendering: "pixelated" } })),
    [tiles]);
  const v = view.current;

  return h("div", { style: { ...card, display: "flex", gap: 12 } },
    h("div", {
        ref: box, onPointerDown: onDown, onPointerMove: onMove,
        onPointerUp: () => (drag.current = null),
        onPointerLeave: () => { drag.current = null; setCursor(null); },
        style: { width: W, height: H, background: "#000", borderRadius: 10,
                 overflow: "hidden", position: "relative", cursor: "grab", flex: "none" } },
      // One layer carrying the whole map. Moving or scaling it moves every
      // tile at once, so a drag costs the same whether the map holds
      // twenty-five tiles or ten thousand. The layer is deliberately not
      // marked as "will change", which would ask the browser to keep a ready
      // drawing of the whole thing: a map measured in millimetres of sample is
      // far too large for that to be a kindness. The frame around it clips to
      // the visible part, which is all the browser then has to draw.
      h("div", { style: { position: "absolute", left: 0, top: 0,
          transformOrigin: "0 0",
          transform: `translate(${v.tx}px, ${v.ty}px) scale(${v.scale})` } },
        tileLayer),
      marks.map((m, i) =>
        h("div", { key: `m${i}`,
          onMouseEnter: () => model.send({ type: "mark", index: i }),
          onClick: (e) => { e.stopPropagation(); model.send({ type: "pick", index: i }); },
          title: m.acquired ? "already acquired" : (m.picked ? "picked — click to un-pick"
            : "click to pick for targeted acquisition"),
          style: { position: "absolute", left: m.x * v.scale + v.tx - 6,
                   top: m.y * v.scale + v.ty - 6, width: 12, height: 12,
                   borderRadius: 999, boxSizing: "border-box",
                   border: m.picked ? "2px solid #ffffff"
                     : `2px solid ${m.gated ? T.accent : T.dim}`,
                   background: m.acquired ? T.good
                     : (markHover.index === i ? T.accent : "transparent"),
                   cursor: "pointer" } })),
      (() => {
        // A scale bar that keeps a nice round length as the zoom changes —
        // the first thing a microscopist looks for on any image.
        if (!tiles.length || !v.scale) return null;
        let um = 1;
        for (const step of [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000]) {
          if (step * v.scale >= 60) { um = step; break; }
          um = step;
        }
        return h("div", { style: { position: "absolute", right: 12, bottom: 12,
            textAlign: "center", color: "#fff", fontSize: 11,
            textShadow: "0 0 4px #000" } },
          h("div", { style: { width: um * v.scale, height: 3, background: "#fff",
            boxShadow: "0 0 4px #000", marginBottom: 2 } }),
          `${um} um`);
      })(),
      h("div", { style: { position: "absolute", left: 10, bottom: 8, display: "flex", gap: 6 } },
        pill(`${tiles.length} tile(s) — drag to pan, scroll to zoom`),
        marks.length ? pill(`${marks.filter((m) => m.gated).length} / ${marks.length} gated`
          + (marks.some((m) => m.picked) ? ` · ${marks.filter((m) => m.picked).length} picked` : "")) : null,
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
        h("button", { title: "cycle colour", disabled: readOnly,
          onClick: () => setCh(i, { color: c.palette[(c.palette.indexOf(c.color) + 1) % c.palette.length] }),
          style: { width: 22, height: 22, borderRadius: 6, border: `1px solid ${T.edge}`,
                   background: c.color, cursor: "pointer" } }),
        h("button", { title: "show / hide", disabled: readOnly,
          onClick: () => setCh(i, { visible: !c.visible }),
          style: { ...btn(false), padding: "2px 8px",
                   background: c.visible ? T.accent : T.edge } }, c.visible ? "on" : "off"),
        h("span", { style: { color: T.dim, width: 30 } }, `ch ${i}`),
        h(NumBox, { value: Math.round(c.lo), disabled: readOnly,
          onCommit: (v) => setCh(i, { lo: v }) }),
        h(NumBox, { value: Math.round(c.hi), disabled: readOnly,
          onCommit: (v) => setCh(i, { hi: v }) }))),
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
    )

    def __init__(
        self,
        overviews: list[dict] | None = None,
        *,
        downsample: int | None = None,
        palette: str = "default",
    ) -> None:
        super().__init__()
        self._fixed_downsample = None if downsample is None else max(1, int(downsample))
        self.downsample = self._fixed_downsample or 1
        self._palette = CHANNEL_HEX_COLORBLIND if palette == "colorblind" else CHANNEL_HEX
        self.overviews: list[dict] = []
        self._stacks: list[Any] = []
        self._tile_entries: list[dict] = []
        self._targets: list[dict] = []
        self._marks_explorer: Any = None
        self._mark_crop_cache: dict[int, dict] = {}
        self._expected_tiles: int | None = None
        self._stream_started: float | None = None
        self.n_channels: int | None = None
        self.observe(self._on_channels_changed, names="channels")
        for overview in overviews or []:
            self.add_tile(overview)

    def expect_tiles(self, n: int) -> None:
        """Tell the viewer how many tiles the coming scan will bring.

        Purely for the operator's peace of mind: with the total known, the
        status line can say "tile 7 of 25 · about 4 min left" instead of
        just counting up. Call it right before ``run_overview``.
        """
        self._expected_tiles = max(1, int(n))
        self._stream_started = time.monotonic()

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

    def _tile_pixel_budget(self) -> int:
        """How many pixels one tile's display copy may use, given the map size.

        A map of two dozen tiles can afford to show each one in detail. A scan
        of several thousand cannot: the browser keeps every tile it displays as
        uncompressed pixels, so the detail has to be shared out over however
        many tiles are coming. Calling :meth:`expect_tiles` before a scan lets
        this be right from the very first tile; without it the count so far is
        used, which catches up as the map grows.

        Small maps are unaffected — twenty-five tiles still get the full
        per-tile budget — so this only changes what a large scan looks like.
        """
        expected = self._expected_tiles or max(1, len(self.overviews) + 1)
        share = _MAP_PIXEL_BUDGET // expected
        return int(min(_PER_IMAGE_PIXEL_BUDGET, max(_MIN_TILE_PIXEL_BUDGET, share)))

    def _step_for(self, overview: dict) -> int:
        """The display downsample for one tile (explicit, or budget-driven)."""
        if self._fixed_downsample is not None:
            return self._fixed_downsample
        h, w = overview["image_size_px"]
        # Every channel of the tile becomes pixels in the composite, so the
        # budget counts all of them, not just one plane.
        n_channels = len(overview.get("channel_paths") or [overview["image_path"]])
        pixels = int(h) * int(w) * max(1, n_channels)
        return max(1, math.ceil(math.sqrt(pixels / self._tile_pixel_budget())))

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
        self._send_tile(len(self._tile_entries) - 1, entry)
        done = len(self.overviews)
        if self._expected_tiles:
            self.status = (
                f"tile {done} of {self._expected_tiles}"
                f"{_eta_text(done, self._expected_tiles, self._stream_started)}"
            )
        else:
            self.status = f"{done} tile(s) on the map"

    def reload(self) -> None:
        """Re-read every tile from disk (after the simulation hijack)."""
        self._stacks = [_load_overview_channels(o, step=self._step_for(o)) for o in self.overviews]
        self._retile()

    def push_snapshot(self) -> None:
        """Replay a bounded, binary tile snapshot for a newly mounted view."""
        snapshot = [
            self._tile_entry(o, s, budget_px=_SNAPSHOT_IMAGE_PIXEL_BUDGET)
            for o, s in zip(self.overviews, self._stacks, strict=True)
        ]
        # Metadata stays in the trait for Python consumers and initial layout;
        # pixels never do. The reset + per-item buffers avoid one giant base64
        # JSON value and give the browser bounded work between messages.
        self.send({"type": "tile:reset", "preserve": True, "length": len(snapshot)})
        self.tiles = [
            {**{k: v for k, v in e.items() if k != "image"}, "src": ""} for e in snapshot
        ]
        for index, entry in enumerate(snapshot):
            self._send_tile(index, entry)

    def _send_tile(self, index: int, entry: dict) -> None:
        """Send one tile's metadata plus its picture, as raw bytes."""
        meta = {k: v for k, v in entry.items() if k != "image"}
        self.send(
            {
                "type": "tile",
                "index": index,
                "entry": {**meta, "src": ""},
                "buffer_keys": ["src"],
                "mime": "image/jpeg",
            },
            buffers=[entry["image"]],
        )

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
                    "color": self._palette[c % len(self._palette)],
                    "palette": list(self._palette),
                    "visible": True,
                    "lo": lo,
                    "hi": hi,
                }
            )
        # A trusted Python-side write: without this, initialising the
        # channel controls on a widget that was frozen while still empty
        # would be healed away, and every later tile would render black.
        self._set_trusted_input("channels", channels)

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
                color = self._palette[i % len(self._palette)]
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

    def _tile_entry(self, overview: dict, stack: Any, *, budget_px: int | None = None) -> dict:
        cx, cy = overview["center_frame_um"]
        h_px, w_px = overview["image_size_px"]
        ps = float(overview["pixel_size_um"])
        w_um, h_um = w_px * ps, h_px * ps
        composite = composite_channels(stack, self._channel_states())
        if budget_px is not None:
            composite = shrink_to_budget(composite, budget_px)
        return {
            "image": jpeg_bytes(composite),
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
        if not self._hardware_allowed:
            return
        if self._stacks:
            self._retile()

    # --- targets on the map --------------------------------------------------

    def show_targets(self, targets: list[dict] | None, explorer: Any = None) -> None:
        """Overlay the discovered cells on the map (or clear with ``None``).

        Each target draws at its frame position, blue when it passes the
        gate and grey when it does not, so gating can be judged against the
        sample itself. Pass the target ``explorer`` to keep the two views
        joined at the hip: every gate edit recolours the map, clicking a
        ring picks that cell for targeted acquisition (a white outline),
        acquired cells fill in green, and hovering shows the cell's crop
        on both figures.
        """
        if self._marks_explorer is not None:
            self._marks_explorer.unobserve(self._on_gate_recoloured, names="gated_mask")
            if getattr(self._marks_explorer, "_linked_viewer", None) is self:
                self._marks_explorer._linked_viewer = None
            self._marks_explorer = None
        self._targets = list(targets or [])
        self._mark_crop_cache = {}
        if explorer is not None and self._targets:
            self._marks_explorer = explorer
            explorer._linked_viewer = self
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
        n = len(self._targets)
        mask = explorer._mask_from_gate() if explorer is not None else [True] * n
        picked = getattr(explorer, "_picked", set()) if explorer is not None else set()
        acquired = getattr(explorer, "_acquired", set()) if explorer is not None else set()
        self.marks = [
            {
                "x": float(t["x"]),
                "y": float(t["y"]),
                "gated": bool(keep),
                "picked": i in picked,
                "acquired": i in acquired,
            }
            for i, (t, keep) in enumerate(zip(self._targets, mask, strict=True))
        ]

    def _display_range_for_crops(self) -> tuple[float, float] | None:
        """The channel-0 display window, so crops match the map's contrast.

        Without this, each crop would stretch over its own min..max and a
        cell could look wildly brighter in the side panel than on the map
        it was cut from.
        """
        states = self._channel_states()
        return states[0]["range"] if states else None

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
                "src": (
                    ""
                    if crop is None
                    else png_data_url_ranged(crop, self._display_range_for_crops())
                ),
                "title": f"target {index} (tile {source.get('naming_p', '?')})",
            }
        self.mark_hover = self._mark_crop_cache[index]
        if self._marks_explorer is not None:
            # Cross-highlight: the same cell's dot grows in the explorer.
            self._marks_explorer.hover = self.mark_hover

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
        kind = content.get("type")
        if kind == "mark":
            self._serve_mark_hover(content)
            return
        if kind == "pick":
            # Clicking a ring picks that cell — the pick state lives on the
            # linked explorer, which validates the index and republishes.
            if self._marks_explorer is not None:
                try:
                    index = int(content.get("index"))
                except (TypeError, ValueError, OverflowError):
                    return
                if 0 <= index < len(self._targets):
                    self._marks_explorer.toggle_pick(index)
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
    _read_only_input_traits = ("points",)

    _esm = (
        REACT_PRELUDE
        + """
function App({ model }) {
  const [squares] = useTrait(model, "squares");
  const [points, setPoints] = useTrait(model, "points");
  const [measured] = useTrait(model, "measured");
  const [heatmap] = useTrait(model, "heatmap");
  const [busy] = useTrait(model, "busy");
  const [status] = useTrait(model, "status");
  const W = widgetPxFor("focus", 620), H = widgetPxFor("focus", 470), pad = 40;

  // Every position carries the selected overview job's physical field size.
  // Fit the complete field bounds (not just their centres), keeping the same
  // x/y scale so overlaps and spacing are geometrically honest.
  const xBounds = squares.flatMap((q) => Number(q.w) > 0
    ? [q.x - q.w / 2, q.x + q.w / 2] : [q.x]);
  const yBounds = squares.flatMap((q) => Number(q.h) > 0
    ? [q.y - q.h / 2, q.y + q.h / 2] : [q.y]);
  const xs = [...xBounds, ...points.map((p) => p.x)];
  const ys = [...yBounds, ...points.map((p) => p.y)];
  if (!xs.length) xs.push(0);
  if (!ys.length) ys.push(0);
  const lo = (v) => Math.min(...v), hi = (v) => Math.max(...v);
  const xLo = lo(xs), yLo = lo(ys);
  const spanX = Math.max(hi(xs) - xLo, 1), spanY = Math.max(hi(ys) - yLo, 1);
  const s = Math.min((W - 2 * pad) / spanX, (H - 2 * pad) / spanY);
  const offsetX = pad + ((W - 2 * pad) - spanX * s) / 2;
  const offsetY = pad + ((H - 2 * pad) - spanY * s) / 2;
  const X = (x) => offsetX + (x - xLo) * s;
  const Y = (y) => offsetY + (y - yLo) * s;
  const toUm = (e, svg) => {
    const r = svg.getBoundingClientRect();
    const localX = (e.clientX - r.left) * W / r.width;
    const localY = (e.clientY - r.top) * H / r.height;
    return { x: xLo + (localX - offsetX) / s,
             y: yLo + (localY - offsetY) / s };
  };
  const fieldRect = (q, i, layer) => {
    const physical = Number(q.w) > 0 && Number(q.h) > 0;
    const width = physical ? q.w * s : 14;
    const height = physical ? q.h * s : 14;
    return h("rect", {
      key: `${layer}${i}`,
      x: X(q.x) - width / 2,
      y: Y(q.y) - height / 2,
      width,
      height,
      fill: layer === "base" ? "#f8fafc" : "none",
      stroke: layer === "border" ? "#e5e7eb" : "none",
      strokeWidth: 1,
    });
  };

  const [readOnly] = useTrait(model, "read_only");
  return h("div", { style: { ...card, width: W, padding: 0,
      background: "transparent", border: "none", boxShadow: "none" } },
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
        style: { ...btn(false), background: T.bad, color: "#ffffff" },
        onClick: () => model.send({ type: "cancel" }) }, "Cancel") : null,
      pill(`${points.length} point(s)`),
      h("span", { style: { color: T.dim, fontSize: 12 } }, status)),
    h("svg", {
        width: W, height: H,
        style: { background: "#ffffff", borderRadius: 10, cursor: "crosshair" },
        onClick: (e) => {
          if (busy || readOnly) return;
          const svg = e.currentTarget;
          const um = toUm(e, svg);
          setPoints([...points, { x: um.x, y: um.y }]);
        } },
      squares.map((q, i) => fieldRect(q, i, "base")),
      heatmap.src ? h("image", { href: heatmap.src, x: X(heatmap.x0), y: Y(heatmap.y0),
        width: heatmap.w * s, height: heatmap.h * s, preserveAspectRatio: "none",
        opacity: 0.82, style: { imageRendering: "auto" } }) : null,
      squares.map((q, i) => fieldRect(q, i, "border")),
      points.map((p, i) => {
        const m = measured[i];
        return h("g", { key: `p${i}`, style: { cursor: "pointer" },
            onClick: (e) => { e.stopPropagation();
              if (!busy && !readOnly) setPoints(points.filter((_, k) => k !== i)); } },
          h("circle", { cx: X(p.x), cy: Y(p.y), r: 7, fill: m ? T.good : T.bad,
            stroke: "#000", strokeWidth: 1.5 }),
          m ? h("text", { x: X(p.x) + 10, y: Y(p.y) - 8, fill: "#f8fafc", fontSize: 11 },
            m.z_um.toFixed(1) +
            (m.residual_um === undefined ? "" : ` (Δ${m.residual_um.toFixed(1)})`)) : null);
      })),
    h("div", { style: { color: T.dim, fontSize: 12, marginTop: 6 } },
      "click: add a focus point · click a point: remove it · squares: overview positions" +
      " · +x right, +y down (same as the overview map)"));
}
export default mount(App);
"""
    )

    def __init__(
        self,
        session: Any,
        positions: list[dict] | None = None,
        *,
        focus_positions: list[dict] | None = None,
        af_job: str | None = None,
        start_z: float | None = None,
        seed: bool = True,
    ) -> None:
        super().__init__()
        self.session = session
        self.af_job = af_job
        self.start_z = start_z
        self.squares = []
        for position in positions or []:
            size = position.get("tile_size") or {}
            width = float(size.get("x") or 0.0)
            height = float(size.get("y") or 0.0)
            self.squares.append(
                {
                    "x": float(position["x"]),
                    "y": float(position["y"]),
                    "w": width if width > 0 else 0.0,
                    "h": height if height > 0 else 0.0,
                    "fill": "",
                }
            )
        self.focus: Any = None
        self._measured_points: list[dict] | None = None
        # Autofocus results already collected this session, keyed by the
        # point's exact coordinates — re-measuring reuses them, so editing
        # the points only sends the stage to the NEW or moved ones.
        self._af_cache: dict[tuple[float, float], dict] = {}
        if seed:
            self.points = [
                {"x": float(p["x"]), "y": float(p["y"])}
                for p in (focus_positions or [])
            ]
        self.observe(self._on_points_edited, names="points")
        self.status = "pick focus points, then press Measure"

    def _on_points_edited(self, _change: Any) -> None:
        if not self._hardware_allowed:
            return
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
        fresh_points = [p for p in points if (float(p["x"]), float(p["y"])) not in self._af_cache]

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
            done = len(self.measured)
            self.status = (
                f"measuring... {done} of {len(points)} points"
                f"{_eta_text(done, len(points), run_started)}"
            )

        try:
            if fresh_points:
                run_started = time.monotonic()
                measure_focus(
                    self.session,
                    fresh_points,
                    af_job=self.af_job,
                    start_z=self.start_z,
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
            ""
            if worst is None
            else f"; largest fit residual {worst[1]:+.1f} µm at point {worst[0]}"
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

        xs = [m["x_um"] for m in self.measured]
        ys = [m["y_um"] for m in self.measured]
        for square in self.squares:
            half_width = float(square.get("w") or 0.0) / 2.0
            half_height = float(square.get("h") or 0.0) / 2.0
            xs.extend((square["x"] - half_width, square["x"] + half_width))
            ys.extend((square["y"] - half_height, square["y"] + half_height))

        def _span(values):
            lo, hi = float(min(values)), float(max(values))
            return (lo - 1.0, hi + 1.0) if hi - lo < 1e-9 else (lo, hi)

        x_lo, x_hi = _span(xs)
        y_lo, y_hi = _span(ys)
        gx, gy = np.meshgrid(np.linspace(x_lo, x_hi, 60), np.linspace(y_lo, y_hi, 60))
        mesh = np.asarray(self.focus.z_at(gx, gy), dtype=float).reshape(gx.shape)
        return {
            "src": heatmap_data_url(mesh),
            "x0": x_lo,
            "y0": y_lo,
            "w": x_hi - x_lo,
            "h": y_hi - y_lo,
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
    #: Cells the operator picked by hand (click a dot here, or a ring on
    #: the overview map). "Acquire selected" targets exactly these. The
    #: real pick state lives in Python; acquisition re-validates every
    #: pick against the gate at run time, so nothing written into this
    #: trait can smuggle a gated-out cell to the microscope.
    picked_indices = traitlets.List().tag(sync=True)
    #: Cells already acquired this session (drawn filled) — so nobody
    #: images the same cell twice without meaning to.
    acquired_indices = traitlets.List().tag(sync=True)
    _read_only_input_traits = ("x_feature", "y_feature", "gate")
    #: Hovering a dot only serves a crop preview — an observer may browse.
    _read_only_safe_messages = ("hover",)

    _esm = (
        REACT_PRELUDE
        + """
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
  const [picked] = useTrait(model, "picked_indices");
  const [acquired] = useTrait(model, "acquired_indices");
  const [readOnly] = useTrait(model, "read_only");
  const W = widgetPxFor("explorer", 460), H = widgetPxFor("explorer", 360), pad = 42;
  const moved = React.useRef(false);

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
  const lassoStart = React.useRef(null);
  const [trail, setTrail] = React.useState([]);

  const finishLasso = (e, commit) => {
    if (commit && lasso.current && moved.current && lasso.current.length >= 3)
      setGate({ ...gate, lasso: lasso.current });
    lasso.current = null;
    lassoStart.current = null;
    moved.current = false;
    setTrail([]);
    if (e.currentTarget.hasPointerCapture?.(e.pointerId))
      e.currentTarget.releasePointerCapture(e.pointerId);
  };

  const select = (value, onChange) => h("select", {
      value, disabled: readOnly, onChange: (e) => onChange(e.target.value),
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
        h("button", { disabled: readOnly, style: { ...btn(readOnly), padding: "4px 10px" },
          onClick: () => setGate({ ...gate, lasso: null }) }, "clear lasso")),
      h("svg", { width: W, height: H,
          style: { background: T.bg, borderRadius: 10, touchAction: "none" },
          onPointerDown: (e) => {
            if (readOnly) return;
            moved.current = false;
            lassoStart.current = [e.clientX, e.clientY];
            e.currentTarget.setPointerCapture(e.pointerId);
            lasso.current = [toData(e, e.currentTarget)]; setTrail(lasso.current);
          },
          onPointerMove: (e) => {
            if (!lasso.current) return;
            const start = lassoStart.current;
            if (start && Math.hypot(e.clientX - start[0], e.clientY - start[1]) >= 5)
              moved.current = true;
            lasso.current = [...lasso.current, toData(e, e.currentTarget)];
            setTrail(lasso.current);
          },
          onPointerUp: (e) => finishLasso(e, true),
          onPointerCancel: (e) => finishLasso(e, false),
          onLostPointerCapture: (e) => finishLasso(e, false) },
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
        dots.map((d, i) => h("circle", { key: i, cx: X(d.fx), cy: Y(d.fy),
          r: hover.index === i ? 7 : 5,
          fill: acquired.includes(i) ? T.good : (mask[i] ? T.accent : T.edge),
          stroke: picked.includes(i) ? T.ink : "none", strokeWidth: 2,
          style: { transition: "fill 0.2s, r 0.1s", cursor: readOnly ? "default" : "pointer" },
          onMouseEnter: () => model.send({ type: "hover", index: i }),
          onPointerDown: (e) => e.stopPropagation(),
          onClick: (e) => {
            e.stopPropagation();
            if (!readOnly) model.send({ type: "pick", index: i });
          } }))),
      h("div", { style: { display: "flex", gap: 6, marginTop: 8, alignItems: "center", fontSize: 12 } },
        h("span", { style: { color: T.dim } }, xf),
        h(NumBox, { value: rng[0], width: 72, disabled: readOnly,
          onCommit: (v) => setRange("x", 0, v) }),
        h(NumBox, { value: rng[1], width: 72, disabled: readOnly,
          onCommit: (v) => setRange("x", 1, v) }),
        h("span", { style: { color: T.dim } }, yf),
        h(NumBox, { value: rngY[0], width: 72, disabled: readOnly,
          onCommit: (v) => setRange("y", 0, v) }),
        h(NumBox, { value: rngY[1], width: 72, disabled: readOnly,
          onCommit: (v) => setRange("y", 1, v) }))),
    h("div", { style: { width: 190 } },
      h("div", { style: { fontWeight: 700, marginBottom: 6 } },
        `${mask.filter(Boolean).length} / ${dots.length} in the gate`),
      h("div", { style: { color: T.dim, fontSize: 12, marginBottom: 6, display: "flex",
                          gap: 6, alignItems: "center" } },
        pill(`${picked.length} picked`),
        picked.length && !readOnly ? h("button", {
          style: { ...btn(false), padding: "2px 8px", background: T.edge, color: T.dim },
          onClick: () => model.send({ type: "clear_picks" }) }, "clear") : null),
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
    )

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
        self._healing_axes = False
        self._publishing_indices = False
        self._publishing_mask = False
        self._picked: set[int] = set()  # Python owns the truth; the trait displays it
        self._acquired: set[int] = set()
        self._linked_viewer: Any = None  # set by OverviewViewerReact.show_targets
        self.features = _numeric_features(targets)
        self.x_feature = self.features[0]
        self.y_feature = self.features[1] if len(self.features) > 1 else self.features[0]
        self.observe(self._on_axes_changed, names=["x_feature", "y_feature"])
        self.observe(self._on_gate_changed, names="gate")
        self.observe(self._heal_index_traits, names=["picked_indices", "acquired_indices"])
        self.observe(self._heal_gated_mask, names="gated_mask")
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
            self._publish_gated_mask(mask)
        return [t for t, keep in zip(self.targets, mask, strict=True) if keep]

    # --- hand-picked cells ---------------------------------------------------

    @property
    def picked_targets(self) -> list[dict]:
        """The cells the operator picked by hand, in index order.

        The pick set lives in Python (`self._picked`); the synced trait is
        its display. Anything a page script writes into the trait is
        ignored here — and the acquisition step re-checks every pick
        against the gate anyway.
        """
        return [self.targets[i] for i in sorted(self._picked)]

    @property
    def picked_gated(self) -> tuple[list[dict], list[int]]:
        """The picked cells split into (inside the gate, indices outside it)."""
        mask = self._mask_from_gate()
        inside = [self.targets[i] for i in sorted(self._picked) if mask[i]]
        outside = [i for i in sorted(self._picked) if not mask[i]]
        return inside, outside

    def toggle_pick(self, index: int) -> None:
        """Pick a cell (or un-pick it) for targeted acquisition."""
        index = int(index)
        if not 0 <= index < len(self.targets):
            raise ValueError(f"no target {index} to pick")
        if index in self._picked:
            self._picked.discard(index)
        else:
            self._picked.add(index)
        self._publish_picks()

    def clear_picks(self) -> None:
        """Forget every hand-picked cell."""
        self._picked.clear()
        self._publish_picks()

    def note_acquired(self, targets: list[dict]) -> None:
        """Mark these cells as acquired (they render filled from now on).

        Called by the gallery when a run commits — random or selected —
        so nobody images the same cell twice without meaning to. Acquired
        cells also leave the pick set: their errand is done.
        """
        for i in _matching_target_indices(self.targets, targets, acquired=self._acquired):
            self._acquired.add(i)
            self._picked.discard(i)
        self._publishing_indices = True
        try:
            self.acquired_indices = sorted(self._acquired)
        finally:
            self._publishing_indices = False
        self._publish_picks()

    def _publish_picks(self) -> None:
        self._publishing_indices = True
        try:
            self.picked_indices = sorted(self._picked)
        finally:
            self._publishing_indices = False
        self.status = (
            f"{len(self._picked)} cell(s) picked for targeted acquisition"
            if self._picked
            else "thresholds AND lasso gate together · click a dot to pick it"
        )
        if self._linked_viewer is not None:
            self._linked_viewer._refresh_marks()

    def _heal_index_traits(self, change: dict) -> None:
        """The pick and acquired records are Python truth; traits display them.

        A page script rewriting these traits could hide an already-imaged
        cell (inviting a second exposure) or relabel the "Acquire selected"
        button — heal them back to the private sets immediately.
        """
        if self._publishing_indices:
            return
        truth = sorted(self._picked if change["name"] == "picked_indices" else self._acquired)
        if list(change["new"]) == truth:
            return
        self._publishing_indices = True
        try:
            setattr(self, change["name"], truth)
        finally:
            self._publishing_indices = False
        self.status = "ignored an invalid browser write to the pick record"

    def _publish_gated_mask(self, mask: list[bool]) -> None:
        self._publishing_mask = True
        try:
            self.gated_mask = mask
        finally:
            self._publishing_mask = False

    def _heal_gated_mask(self, change: dict) -> None:
        """Restore the gate display the moment page code scribbles on it.

        ``gated`` already recomputes from the raw gate on every read, so a
        forged mask never chooses targets — but until now it stayed on
        screen (and recoloured the linked map) until the next read. Heal it
        eagerly instead.
        """
        if self._publishing_mask:
            return
        mask = self._mask_from_gate()
        if list(change["new"]) == mask:
            return
        self._publish_gated_mask(mask)
        self.status = "ignored an invalid browser write to the gate display"

    def _on_axes_changed(self, change: Any) -> None:
        if not self._hardware_allowed or self._healing_axes:
            return
        if change["new"] not in self.features:
            # An unknown feature name arrives only from a page script or a
            # stale gate file — never from the dropdowns. Restore the
            # previous, valid axis instead of plotting NaN dots (which
            # would crash the histogram mid-update and freeze the explorer
            # at a stale state).
            self._healing_axes = True
            try:
                setattr(self, change["name"], change["old"])
            finally:
                self._healing_axes = False
            self.status = "ignored an unknown feature name from the page"
            return
        # A lasso drawn in the old feature space would gate nonsense in the
        # new one, so switching axes clears the whole gate (like matplotlib).
        self._recompute(reset_gate=True)

    def _on_gate_changed(self, _change: Any) -> None:
        if not self._hardware_allowed:
            return
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
        """Bin counts normalized to 0..1 — a slim distribution backdrop.

        A target can be missing a feature (its value is then NaN), so the
        bins are computed over the finite values only — NaNs must degrade
        to "no backdrop", never raise mid-update.
        """
        finite = [v for v in values if math.isfinite(v)]
        if not finite:
            return [1.0] + [0.0] * (bins - 1)
        lo, hi = min(finite), max(finite)
        if hi <= lo:
            return [1.0] + [0.0] * (bins - 1)
        counts = [0] * bins
        for v in finite:
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
        self._publish_gated_mask(self._mask_from_gate())
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
        kind = content.get("type")
        # The index comes from the browser: validate it rather than trusting
        # it (OverflowError covers JSON numbers like 1e999 -> infinity).
        try:
            index = int(content.get("index"))
        except (TypeError, ValueError, OverflowError):
            index = None
        if kind == "clear_picks":
            self.clear_picks()
            return
        if kind == "pick":
            if index is not None and 0 <= index < len(self.targets):
                self.toggle_pick(index)
            return
        if kind != "hover":
            self.status = f"unknown message: {content.get('type')}"
            return
        if index is None or not 0 <= index < len(self.targets):
            return
        if index not in self._crop_cache:
            # Cropping reads the full-resolution tile from disk — cache it,
            # or a fast mouse over many dots queues seconds of disk reads
            # ahead of the next button press.
            crop = crop_for_target(self.targets[index], self.overviews, crop_um=self.crop_um)
            source = self.targets[index].get("source") or {}
            # With a linked viewer, crops use ITS display window, so a cell
            # looks the same in the side panel as on the map it came from.
            viewer = self._linked_viewer
            display_range = viewer._display_range_for_crops() if viewer is not None else None
            self._crop_cache[index] = {
                "index": index,
                "src": "" if crop is None else png_data_url_ranged(crop, display_range),
                "title": f"target {index} (tile {source.get('naming_p', '?')})",
            }
        self.hover = self._crop_cache[index]
        if self._linked_viewer is not None:
            # Cross-highlight: the same cell lights up on the overview map.
            self._linked_viewer.mark_hover = self.hover


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
    #: How many cells are hand-picked in the linked explorer right now —
    #: drives the "Acquire selected" button's label and visibility.
    selected_count = traitlets.Int(0).tag(sync=True)
    #: Per-row curation: "good", "bad", or None — the operator's own QC
    #: record of the run (display-synced; Python owns the truth).
    verdicts = traitlets.List().tag(sync=True)
    _read_only_input_traits = ("verdicts",)

    _esm = (
        REACT_PRELUDE
        + """
function App({ model }) {
  const rows = useStream(model, "rows", "row");
  const [busy] = useTrait(model, "busy");
  const [status] = useTrait(model, "status");
  const [gateCount] = useTrait(model, "gate_count");
  const [defaultCount] = useTrait(model, "default_count");
  const [selectedCount] = useTrait(model, "selected_count");
  const [verdicts] = useTrait(model, "verdicts");
  const [readOnly] = useTrait(model, "read_only");
  const [count, setCount] = React.useState(String(defaultCount));
  const [zoom, setZoom] = React.useState(null);  // row index in the lightbox

  React.useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") setZoom(null); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const verdictBtn = (i, value, label, colour) => h("button", {
    title: value === "good" ? "mark this pair as good" : "mark this pair as bad",
    onClick: (e) => { e.stopPropagation(); model.send({ type: "verdict", index: i,
      value: verdicts[i] === value ? null : value }); },
    style: { ...btn(false), padding: "2px 10px",
             background: verdicts[i] === value ? colour : T.edge,
             color: verdicts[i] === value ? "#ffffff" : T.dim } }, label);

  const scaleBar = (r) => {
    if (!r.width_um) return null;
    let um = 1;
    for (const step of [1, 2, 5, 10, 20, 50, 100, 200, 500]) {
      if (step / r.width_um >= 0.18) { um = step; break; }
      um = step;
    }
    return h("div", { style: { position: "absolute", right: 8, bottom: 8,
        textAlign: "center", color: "#fff", fontSize: 10, textShadow: "0 0 4px #000" } },
      h("div", { style: { width: `${(um / r.width_um) * 100}%`, minWidth: 20, height: 3,
        background: "#fff", boxShadow: "0 0 4px #000", marginBottom: 1,
        marginLeft: "auto" } }),
      `${um} um`);
  };

  const pairPanels = (r, big) => [["low", r.low_title], ["high", r.high_title]].map(
    ([side, title]) => h("div", { key: side, style: { flex: 1, position: "relative" } },
      h("img", { src: r[side + "_src"], style: { width: "100%", borderRadius: 10,
        imageRendering: big ? "auto" : "pixelated", border: `1px solid ${T.edge}` } }),
      scaleBar(r),
      h("div", { style: { color: big ? "#f1f5f9" : T.dim, fontSize: 12, marginTop: 2 } }, title)));

  const fillWidth = Boolean(globalThis.ZMART_WIDGET_FILL?.gallery);
  return h("div", { style: { ...card,
      width: fillWidth ? "100%" : widgetPxFor("gallery", 700),
      position: "relative" } },
    h("style", null, "@keyframes zin { from { opacity: 0; transform: translateY(8px);} to { opacity: 1; transform: none;} }"),
    h("div", { style: { display: "flex", gap: 10, alignItems: "center", marginBottom: 10,
                        flexWrap: "wrap" } },
      readOnly ? pill("read-only view") : h("span", { style: { color: T.dim } }, "how many"),
      readOnly ? null : h("input", { style: inp, value: count,
        onChange: (e) => setCount(e.target.value),
        onKeyDown: (e) => { if (e.key === "Enter" && !busy)
          model.send({ type: "acquire", count }); } }),
      readOnly ? null : h("button", { style: btn(busy), disabled: busy,
        onClick: () => model.send({ type: "acquire", count }) },
        busy ? "acquiring..." : "Acquire"),
      !readOnly && selectedCount > 0 ? h("button", {
        title: "acquire exactly the cells you picked on the map / scatter",
        style: { ...btn(busy), background: busy ? T.edge : T.good, color: "#ffffff" },
        disabled: busy,
        onClick: () => model.send({ type: "acquire_selected" }) },
        `Acquire selected (${selectedCount})`) : null,
      busy && !readOnly ? h("button", {
        title: "stop cleanly before the next target (nothing is committed)",
        style: { ...btn(false), background: T.bad, color: "#ffffff" },
        onClick: () => model.send({ type: "cancel" }) }, "Cancel") : null,
      pill(`${gateCount} in the gate`),
      h("span", { style: { color: T.dim, fontSize: 12 } }, status)),
    rows.map((r, i) => {
      // A view mounted mid-run can receive row 5 before rows 0..4. useStream
      // skips sparse holes for rendering, so the compact array index is NOT
      // the acquisition index. Every row carries its authoritative wire index.
      const rowIndex = Number.isInteger(r.stream_index) ? r.stream_index : i;
      return h("div", { key: rowIndex,
        onClick: () => setZoom(i),
        title: "click to enlarge",
        style: { display: "flex", gap: 10, marginBottom: 10,
                 animation: "zin 0.35s ease", cursor: "zoom-in" } },
      pairPanels(r, false),
      readOnly ? null : h("div", { style: { display: "flex", flexDirection: "column",
          gap: 6, justifyContent: "center" } },
        verdictBtn(rowIndex, "good", "✓", T.good),
        verdictBtn(rowIndex, "bad", "✗", T.bad)));
    }),
    zoom !== null && rows[zoom] ? h("div", {
        onClick: () => setZoom(null),
        title: "click (or press Esc) to close",
        style: { position: "fixed", inset: 0, background: "rgba(2,6,23,0.88)",
                 zIndex: 1000, display: "flex", alignItems: "center",
                 justifyContent: "center", cursor: "zoom-out", padding: 30 } },
      h("div", { style: { display: "flex", gap: 16, maxWidth: "94vw",
                          maxHeight: "94vh" } },
        pairPanels(rows[zoom], true))) : null);
}
export default mount(App);
"""
    )

    def __init__(
        self,
        session: Any,
        source: Any,
        overviews: list[dict] | None = None,
        *,
        state: dict | None = None,
        focus: Any = None,
        options: dict | None = None,
        output_root: Any = None,
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
        self.output_root = output_root
        self.after_acquire = after_acquire
        self.default_count = int(default_count)
        self._rng = random.Random(seed)
        self.picked: list[dict] = []
        self.records: list[dict] = []
        self._row_entries: list[dict] = []
        self._run_started: float | None = None
        self._verdicts: list[str | None] = []
        self._publishing_verdicts = False
        self.observe(self._heal_verdict_trait, names="verdicts")
        self.gate_count = len(self._gated())
        # When the source is the explorer, mirror its hand-pick count so
        # the "Acquire selected" button can show and label itself.
        if hasattr(source, "observe") and hasattr(source, "picked_indices"):
            source.observe(self._on_picks_changed, names="picked_indices")
            self.selected_count = len(getattr(source, "picked_indices", []) or [])
        self.status = "type a count and press Acquire"

    def _on_picks_changed(self, _change: Any) -> None:
        self.selected_count = len(getattr(self.source, "picked_indices", []) or [])

    def _gated(self) -> list[dict]:
        return list(getattr(self.source, "gated", self.source))

    def push_snapshot(self) -> None:
        """Replay a bounded, binary row snapshot for a newly mounted view."""
        self.send({"type": "row:reset", "preserve": True, "length": len(self._row_entries)})
        self.rows = [
            {
                **{k: v for k, v in e.items() if k not in ("low_png", "high_png")},
                "stream_index": index,
                "low_src": "",
                "high_src": "",
            }
            for index, e in enumerate(self._row_entries)
        ]
        for index, entry in enumerate(self._row_entries):
            self._send_row(index, entry)

    def _send_row(self, index: int, entry: dict) -> None:
        """Send one gallery row as metadata plus two raw PNG buffers."""
        meta = {k: v for k, v in entry.items() if k not in ("low_png", "high_png")}
        self.send(
            {
                "type": "row",
                "index": index,
                "entry": {
                    **meta,
                    "stream_index": index,
                    "low_src": "",
                    "high_src": "",
                },
                "buffer_keys": ["low_src", "high_src"],
            },
            buffers=[entry.get("low_png") or b"", entry.get("high_png") or b""],
        )

    def _publish_verdicts(self) -> None:
        self._publishing_verdicts = True
        try:
            self.verdicts = list(self._verdicts)
        finally:
            self._publishing_verdicts = False

    def _heal_verdict_trait(self, change: dict) -> None:
        """Treat the synced verdict trait as display output, never QC truth."""
        if self._publishing_verdicts or list(change["new"]) == self._verdicts:
            return
        self._publish_verdicts()
        self.status = "ignored an invalid browser write to the curation record"

    def set_verdict(self, index: int, value: str | None) -> None:
        """Record the operator's judgement of one pair: "good", "bad", or None.

        This is the run's QC record — :meth:`save_curation` writes it next
        to the images. Scriptable and also driven by the ✓/✗ buttons. Only
        rows of a committed run can be judged, and a read-only widget
        refuses: the record must always match what every view displays.
        """
        if not self._hardware_allowed:
            raise RuntimeError("this view is read-only — the curation record is locked")
        if value not in ("good", "bad", None):
            raise ValueError('a verdict is "good", "bad", or None')
        if not 0 <= int(index) < len(self._verdicts):
            raise ValueError(
                f"no committed gallery row {index} to judge — a cancelled or "
                "failed run leaves nothing to curate"
            )
        self._verdicts[int(index)] = value
        self._publish_verdicts()

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
            for i, (r, v) in enumerate(zip(self.records, self._verdicts, strict=True))
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
            if 0 <= index < len(self._verdicts):
                self.set_verdict(index, value)
            elif 0 <= index < len(self._row_entries):
                # The row is still on screen from a run that never committed
                # (cancelled or failed) — explain instead of judging it.
                self.status = "that run was not committed — re-run before curating"
            return
        if kind == "acquire_selected":
            if self._debounced():
                return
            self._run_guarded(self.acquire_selected)
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

    def acquire_selected(self) -> list[dict]:
        """Acquire exactly the cells hand-picked in the explorer.

        The point-at-the-cell counterpart of the random sample: click cells
        on the map or the scatter, then run this (or press **Acquire
        selected**). Every pick is re-validated against the CURRENT gate —
        a pick that has since fallen outside the thresholds or lasso
        refuses the whole run loudly rather than quietly imaging a cell
        the gate excludes. Same busy/debounce/read-only guards as every
        other hardware path.
        """
        source = self.source
        if not hasattr(source, "picked_gated"):
            raise RuntimeError(
                "hand-picking needs the target explorer as the gallery's source — "
                "this gallery was built from a plain target list."
            )
        picked, outside = source.picked_gated
        if outside:
            raise RuntimeError(
                f"picked cell(s) {outside} are outside the current gate — widen "
                "the gate to include them, or un-pick them, then acquire again."
            )
        if not picked:
            raise RuntimeError(
                "no cells are picked — click cells on the map or the scatter first "
                "(or use the random 'Acquire' instead)."
            )
        gated_count = len(self._gated())
        self.gate_count = gated_count
        return self._hardware_run(lambda: self._acquire(picked, gated_count))

    def _acquire(self, picked: list[dict], gated_count: int) -> list[dict]:
        # This run replaces the previous result, so the previous result must
        # stop being "the result" now: if this run fails halfway, a later
        # summary cell must not quietly describe the OLD run while the
        # gallery shows the new, failed one.
        self.picked = []
        self.records = []
        self._row_entries = []
        self.send({"type": "row:reset"})
        self.rows = []
        # The curation record grows WITH the streamed rows and is emptied
        # again if the run fails: verdicts, records and curation.json must
        # always describe the same committed rows, so a cancelled run can
        # never leave judgements pointing at pairs that were never committed.
        self._verdicts = []
        self._publish_verdicts()
        self._run_started = time.monotonic()

        def _show_fresh_pair(index: int, _position: dict, record: dict) -> None:
            entry = self._row_entry(picked[index - 1], record)
            self._row_entries.append(entry)
            self._verdicts.append(None)
            self._publish_verdicts()
            # One message per fresh pair — never a resend of the rows so
            # far, with the two images as binary buffers.
            self._send_row(index - 1, entry)
            self.status = (
                f"acquired {index} of {len(picked)} target(s)"
                f"{_eta_text(index, len(picked), self._run_started)}..."
            )

        try:
            records = acquire_targets(
                self.session,
                picked,
                state=self.state,
                focus=self.focus,
                options=self.options,
                output_root=self.output_root,
                on_record=_show_fresh_pair,
                cancel=lambda: self._cancel_requested,
            )
            if self.after_acquire is not None:
                self.after_acquire(records)
                # The hijack may have rewritten the saved images: re-read them.
                refreshed_entries = [
                    self._row_entry(t, r) for t, r in zip(picked, records, strict=True)
                ]
            else:
                refreshed_entries = self._row_entries
        except BaseException:
            # Nothing commits on failure or cancel; the curation record must
            # agree. The streamed rows stay on screen (their files ARE saved)
            # but they carry no verdicts and cannot be judged.
            self._verdicts = []
            self._publish_verdicts()
            raise
        self._row_entries = refreshed_entries
        self.picked = picked
        self.records = records
        # The run is complete: publish the full rows snapshot so any view —
        # including one opened later — has the whole gallery.
        self.push_snapshot()
        # Tell the explorer which cells are now done: they render filled on
        # the scatter and the map, and leave the pick set.
        if hasattr(self.source, "note_acquired"):
            self.source.note_acquired(picked)
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
            "low_png": png_bytes(shrink_to_budget(low, _GALLERY_IMAGE_PIXEL_BUDGET)),
            "high_png": png_bytes(shrink_to_budget(high, _GALLERY_IMAGE_PIXEL_BUDGET)),
            "position_label": record.get("position_label"),
            "width_um": float(width_um),  # lets the browser draw a scale bar
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

    _esm = (
        REACT_PRELUDE
        + """
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
    )

    def refresh(self, ns: dict) -> RunStatusReact:
        """Rebuild the checklist from the notebook's variables (``globals()``)."""
        from .._run_status import run_status_rows

        self.rows = run_status_rows(ns)
        return self

    def handle_message(self, content: dict) -> None:
        self.status = f"unknown message: {content.get('type')}"


class CanvasReact(_ZmartWidget):
    """One picture of the sample, built from layers that move as one.

    Everything the operator needs to see about a slide sits in the same place
    and the same coordinates: the imagery itself, the carrier or plate it sits
    in, where the tiles will be taken, where the focus was measured, and any
    heat map drawn over the top. This widget holds those as separate *layers*
    that share one view, so panning or zooming moves all of them together and
    they can never drift apart.

    **The camera is the single source of truth.** Nothing stores its own
    position. ``camera`` says where the middle of the frame is, in
    micrometres on the sample, and how many screen pixels one micrometre
    takes. Every layer is drawn from that one description. This is what makes
    it possible to put a different image engine underneath later — one that
    draws with the graphics card and keeps its own camera, and so cannot
    simply be moved with the rest. Such an engine reads this camera instead of
    inventing its own, which is a matter of plugging it in rather than
    rewriting everything above it. The empty ``"engine"`` layer kind below is
    that slot.

    **Each layer decides three things for itself**, and they are deliberately
    separate:

    ``visible``
        Whether it is drawn at all. Switching a layer off removes it, rather
        than making it invisible: an unseen layer should cost nothing and
        should not quietly swallow clicks meant for something else.
    ``opacity``
        How solid it is on its own, from 0 to 1.
    ``dimmable``
        Whether the *shared* fade applies to it. Turning the shared fade down
        is how the operator sees the imagery through everything drawn over it
        — so anything they are working with by hand, like focus points, is
        usually better left out of it. Otherwise fading enough to see the
        sample would fade away the very thing being placed. The bottom layer
        is never dimmable for the same reason from the other direction: it is
        the thing being looked *at*.
    ``interactive``
        Whether clicks reach it. A heat map is there to be read, not clicked,
        and if it accepted clicks it would silently swallow every attempt to
        place a focus point underneath it.

    **The fade can vary across the sample.** ``opacity_map`` describes areas
    that should be more transparent than the rest — a few wells shown through
    while the surrounding layout stays solid, say. Those areas are given in
    micrometres on the sample, not in pixels on the screen, so a window onto
    the imagery stays over the same piece of sample as the view is panned and
    zoomed, instead of sliding about like a hole cut in the screen.
    """

    #: Where the middle of the frame is on the sample, and how big things are
    #: drawn: ``cx``/``cy`` in micrometres, ``scale`` in screen pixels per
    #: micrometre. Written by the operator's dragging and scrolling, and read
    #: by every layer — including, later, an image engine that draws its own.
    camera = traitlets.Dict({"cx": 0.0, "cy": 0.0, "scale": 1.0}).tag(sync=True)

    #: The layers, bottom first. Each is ``{id, kind, label, visible, opacity,
    #: dimmable, interactive}`` plus whatever that kind draws.
    layers = traitlets.List().tag(sync=True)

    #: The shared fade, from 0 (gone) to 1 (fully solid). It reaches only the
    #: layers that asked for it by being ``dimmable``.
    dim = traitlets.Float(1.0).tag(sync=True)

    #: Where the sample should show through more than elsewhere. ``kind`` is
    #: ``"none"`` or ``"regions"``; regions are given in micrometres.
    opacity_map = traitlets.Dict({"kind": "none"}).tag(sync=True)

    #: How far down a window reaches. The point of opening one is to see the
    #: imagery, and a window through a single layer would only reveal the next
    #: layer down — so by default it goes all the way:
    #:
    #: ``"all"``
    #:     Cut through everything above the bottom layer, whatever each layer
    #:     says for itself. The sample really shows through. Anything drawn
    #:     over the top, focus points included, is cut away inside the window
    #:     too, which is the price of an uninterrupted look at the sample.
    #: ``"chosen"``
    #:     Each layer decides for itself, through its own ``windowed``
    #:     setting. Use this to keep something over the window on purpose —
    #:     the carrier outline so the operator keeps their bearings, or the
    #:     focus points they are placing.
    window_reaches = traitlets.Unicode("all").tag(sync=True)

    #: The pictures on the imagery layer, as metadata only. Their pixels
    #: travel separately, one binary message per picture, so a scan of
    #: thousands of fields never becomes one enormous page.
    images = traitlets.List().tag(sync=True)

    #: The piece of sample the layers cover, ``[x0, y0, width, height]`` in
    #: micrometres. Each layer is given this as its own area, which is what a
    #: window is then cut out of — a layer with no area of its own would have
    #: nothing to cut. Recomputed from the layers as they change, so a caller
    #: does not have to think about it.
    extent = traitlets.List([-1000.0, -1000.0, 2000.0, 2000.0]).tag(sync=True)

    #: What the pointer does on the picture. ``"pan"`` moves the view;
    #: ``"focus"`` places and removes focus points; ``"move"`` picks a scan
    #: field up and puts it somewhere else. Only one at a time, so a click
    #: never has to be guessed at.
    tool = traitlets.Unicode("pan").tag(sync=True)

    #: What is picked out at the moment, as ``{"layer", "index"}`` — drawn
    #: brighter, and what a panel on the right reads to say more about it.
    selection = traitlets.Dict().tag(sync=True)

    #: The last place the pointer was, in micrometres — shown under the
    #: picture, and what a panel on the right reads to place something.
    cursor = traitlets.Dict().tag(sync=True)

    _read_only_input_traits = ("camera", "dim", "tool", "selection")

    _esm = (
        REACT_PRELUDE
        + """
// One shared view. Every layer is drawn from this and nothing else, so they
// cannot drift apart — and an image engine that keeps its own camera can be
// handed these same numbers rather than being moved along with the others.
function screenFrom(camera, W, H) {
  const scale = Number(camera.scale) > 0 ? Number(camera.scale) : 1;
  return { scale,
           tx: W / 2 - (Number(camera.cx) || 0) * scale,
           ty: H / 2 - (Number(camera.cy) || 0) * scale };
}

// How solid one layer ends up: its own setting, and the shared fade only if
// that layer asked to follow it.
function solidity(layer, dim) {
  const own = layer.opacity === undefined ? 1 : Number(layer.opacity);
  const shared = layer.dimmable ? (Number(dim) === 0 ? 0 : Number(dim) || 1) : 1;
  return Math.max(0, Math.min(1, own * shared));
}

// The see-through areas, drawn as a mask in SAMPLE coordinates. Because the
// mask sits inside the same moving frame as everything else, a window onto
// the imagery stays over the same piece of sample while the view moves,
// instead of sliding about like a hole cut in the screen.
function maskFor(omap, id, extent) {
  const regions = (omap && omap.kind === "regions" && omap.regions) || [];
  if (!regions.length) return null;
  const outside = omap.outside === undefined ? 1 : Number(omap.outside);
  const [ox, oy, ew, eh] = extent;
  // A mask is measured from the corner of the thing it is masking, and each
  // layer's corner is the canvas's own corner — so the areas, which are given
  // as places on the sample, are moved to match.
  const grey = (v) => `rgb(${v * 255},${v * 255},${v * 255})`;
  return h("svg", { width: 0, height: 0, style: { position: "absolute" },
                    "aria-hidden": "true" },
    h("defs", null,
      // The area the mask covers has to be stated outright. Left unsaid it
      // is worked out as a share of the drawing's own size, and this drawing
      // has none — which would leave an empty mask and hide every layer.
      h("mask", { id, maskUnits: "userSpaceOnUse", maskContentUnits: "userSpaceOnUse",
                  x: 0, y: 0, width: ew, height: eh },
        // White keeps a layer as it is; black lets the sample through.
        h("rect", { x: 0, y: 0, width: ew, height: eh, fill: grey(outside) }),
        regions.map((r, i) => {
          const paint = grey(r.opacity === undefined ? 0 : Number(r.opacity));
          if (r.shape === "polygon" && Array.isArray(r.points)) {
            return h("polygon", { key: i, fill: paint,
              points: r.points.map((p) => `${p[0] - ox},${p[1] - oy}`).join(" ") });
          }
          const b = r.bounds || [0, 0, 0, 0];
          return h("rect", { key: i, x: b[0] - ox, y: b[1] - oy,
                             width: b[2], height: b[3], fill: paint });
        }))));
}

function LayerBody({ layer, ox, oy, pics, picked, grabbed }) {
  if (layer.kind === "engine") {
    // The slot for an image engine that draws with the graphics card. It is
    // deliberately empty: it reads the shared camera when one is plugged in.
    return h("div", { style: { position: "absolute", inset: 0,
        display: "grid", placeItems: "center", color: T.dim, fontSize: 12 } },
      layer.label || "image engine — not plugged in");
  }
  if (layer.kind === "images") {
    const pictures = pics && pics.length ? pics : (layer.images || []);
    return pictures.map((im, i) =>
      h("img", { key: i, src: im.src, draggable: false, style: {
        position: "absolute", left: im.x0 - ox, top: im.y0 - oy,
        width: im.w, height: im.h,
        imageRendering: "pixelated" } }));
  }
  if (layer.kind === "shapes") {
    return (layer.shapes || []).map((s, i) => {
      const chosen = picked && picked.layer === layer.id && picked.index === i;
      const held = grabbed && grabbed.layer === layer.id && grabbed.index === i;
      const shift = held ? grabbed.by : { x: 0, y: 0 };
      if (s.shape === "polygon" && Array.isArray(s.points)) {
        const xs = s.points.map((p) => p[0]), ys = s.points.map((p) => p[1]);
        const x0 = Math.min(...xs), y0 = Math.min(...ys);
        return h("svg", { key: i, style: { position: "absolute", left: x0 - ox, top: y0 - oy,
            overflow: "visible", width: 0, height: 0 } },
          h("polygon", { points: s.points.map((p) => `${p[0] - x0},${p[1] - y0}`).join(" "),
            fill: s.fill || "none", stroke: s.stroke || "none",
            strokeWidth: s.stroke_um || 1, vectorEffect: "non-scaling-stroke" }));
      }
      const b = s.bounds || [0, 0, 0, 0];
      return h("div", { key: i, title: s.label || undefined,
        "data-shape": i, "data-layer": layer.id, style: {
        pointerEvents: layer.interactive ? "auto" : "none",
        position: "absolute", left: b[0] - ox + shift.x, top: b[1] - oy + shift.y,
        width: b[2], height: b[3],
        background: chosen ? "rgba(255,255,255,0.18)" : (s.fill || "transparent"),
        boxSizing: "border-box", opacity: held ? 0.75 : 1,
        border: chosen ? "2px solid #ffffff"
                       : (s.stroke ? `1px solid ${s.stroke}` : "none") } });
    });
  }
  if (layer.kind === "points") {
    // Points keep their size on screen rather than growing with the zoom, so
    // a focus point stays clickable however far out the view is.
    return (layer.points || []).map((p, i) => {
      const chosen = picked && picked.layer === layer.id && picked.index === i;
      const held = grabbed && grabbed.layer === layer.id && grabbed.index === i;
      const shift = held ? grabbed.by : { x: 0, y: 0 };
      return h("div", { key: i, "data-point": i, "data-layer": layer.id,
        title: p.label || undefined, style: {
        position: "absolute", left: p.x - ox + shift.x, top: p.y - oy + shift.y,
        width: 0, height: 0 } },
        h("div", { style: {
          position: "absolute", left: "-6px", top: "-6px", width: 12, height: 12,
          transform: "scale(var(--zmart-inverse-zoom, 1))", transformOrigin: "6px 6px",
          borderRadius: 999, boxSizing: "border-box",
          pointerEvents: layer.interactive ? "auto" : "none",
          background: chosen ? "#ffffff" : (p.fill || "transparent"),
          border: `2px solid ${chosen ? "#ffffff" : (p.stroke || T.accent)}` } }));
    });
  }
  return null;
}

function App({ model }) {
  const [camera, setCamera] = useTrait(model, "camera");
  const [layers] = useTrait(model, "layers");
  const [dim] = useTrait(model, "dim");
  const [omap] = useTrait(model, "opacity_map");
  const [windowReaches] = useTrait(model, "window_reaches");
  const [extentTrait] = useTrait(model, "extent");
  const [tool] = useTrait(model, "tool");
  const [selection] = useTrait(model, "selection");
  // Pictures arrive one at a time as the scan runs, rather than all at once.
  const streamed = useStream(model, "images", "image");
  const [status] = useTrait(model, "status");
  const [readOnly] = useTrait(model, "read_only");
  const box = React.useRef(null);
  const drag = React.useRef(null);
  const moved = React.useRef(false);
  const [cursor, setCursor] = React.useState(null);
  const [holding, setHolding] = React.useState(null);
  const W = widgetPx(760), H = widgetPx(560);
  // Until the operator moves the view themselves, keep the whole sample in
  // sight — a run that opens showing an empty corner of the slide is no use.
  const fitted = React.useMemo(() => {
    if (!extentTrait || extentTrait.length !== 4) return null;
    const [x0, y0, ew0, eh0] = extentTrait.map(Number);
    if (!(ew0 > 0 && eh0 > 0)) return null;
    return { cx: x0 + ew0 / 2, cy: y0 + eh0 / 2,
             scale: Math.min(W / ew0, H / eh0) * 0.92 };
  }, [extentTrait, W, H]);
  // Whichever view is actually on screen — the fitted one until the operator
  // takes over, theirs afterwards. Every handler works from this, so taking
  // over continues from what they were looking at instead of jumping back to
  // a view they never chose.
  const active = (moved.current || !fitted) ? camera : fitted;
  const view = screenFrom(active, W, H);
  const maskId = "zmart-canvas-window";
  const extent = (extentTrait && extentTrait.length === 4)
    ? extentTrait.map(Number) : [-1000, -1000, 2000, 2000];
  const [ox, oy, ew, eh] = extent;
  const mask = maskFor(omap, maskId, extent);

  const sampleAt = (e) => {
    const r = box.current.getBoundingClientRect();
    return { x: (e.clientX - r.left - view.tx) / view.scale,
             y: (e.clientY - r.top - view.ty) / view.scale };
  };

  useWheel(box, (e) => {
    if (readOnly) return;
    moved.current = true;
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    const at = sampleAt(e);
    const r = box.current.getBoundingClientRect();
    const scale = view.scale * factor;
    // Keep the sample point under the pointer exactly where it was.
    setCamera({ ...active, scale,
                cx: at.x + (W / 2 - (e.clientX - r.left)) / scale,
                cy: at.y + (H / 2 - (e.clientY - r.top)) / scale });
  });

  // A hand never holds perfectly still, so a click would otherwise register
  // as a tiny drag and nudge whatever was under it. Anything shorter than
  // this is treated as a click.
  const SLIP = 4;

  // What is under the pointer, if it belongs to a layer that takes clicks.
  const thingUnder = (e) => {
    const el = e.target.closest("[data-shape], [data-point]");
    if (!el) return null;
    const id = el.getAttribute("data-layer");
    const layer = (layers || []).find((l) => l.id === id);
    if (!layer || !layer.interactive || layer.visible === false) return null;
    const shape = el.getAttribute("data-shape");
    return { layer: id, index: Number(shape === null ? el.getAttribute("data-point") : shape),
             kind: shape === null ? "point" : "shape" };
  };

  const onDown = (e) => {
    if (readOnly) return;
    const under = tool === "pan" ? null : thingUnder(e);
    if (under) {
      // Take hold of it. Whether this turns out to be a click or a move is
      // only known when the pointer is let go.
      setHolding({ ...under, by: { x: 0, y: 0 } });
      drag.current = { x: e.clientX, y: e.clientY, from: e.clientX, fromY: e.clientY, on: under };
      e.currentTarget.setPointerCapture?.(e.pointerId);
      return;
    }
    moved.current = true;
    drag.current = { x: e.clientX, y: e.clientY, from: e.clientX, fromY: e.clientY, on: null };
  };

  const onMove = (e) => {
    const at = sampleAt(e);
    setCursor(at);
    if (!drag.current) return;
    if (drag.current.on) {
      // Carrying something: show it under the pointer, and tell Python only
      // once it is put down.
      setHolding({ ...drag.current.on,
                   by: { x: (e.clientX - drag.current.from) / view.scale,
                         y: (e.clientY - drag.current.fromY) / view.scale } });
      return;
    }
    setCamera({ ...active,
                cx: (Number(active.cx) || 0) - (e.clientX - drag.current.x) / view.scale,
                cy: (Number(active.cy) || 0) - (e.clientY - drag.current.y) / view.scale });
    drag.current = { ...drag.current, x: e.clientX, y: e.clientY };
  };

  const letGo = (e) => {
    const held = drag.current;
    drag.current = null;
    setHolding(null);
    if (readOnly || !held) return;
    const slipped = Math.hypot(e.clientX - held.from, e.clientY - held.fromY);
    if (held.on) {
      if (slipped <= SLIP) {
        // A click on something: pick it out, or take a focus point away.
        if (tool === "focus" && held.on.kind === "point") {
          model.send({ type: "remove", layer: held.on.layer, index: held.on.index });
        } else {
          model.send({ type: "pick", layer: held.on.layer, index: held.on.index });
        }
      } else {
        model.send({ type: "move", layer: held.on.layer, index: held.on.index,
                     dx: (e.clientX - held.from) / view.scale,
                     dy: (e.clientY - held.fromY) / view.scale });
      }
      return;
    }
    // A click on the bare picture, with the focus tool, puts a point there.
    if (tool === "focus" && slipped <= SLIP) {
      const at = sampleAt(e);
      model.send({ type: "place", x: at.x, y: at.y });
    }
  };

  const shown = (layers || []).filter((l) => l.visible !== false);
  // The bottom layer is what a window is opened to reveal, so it is never cut.
  const baseId = (layers || []).length ? (layers[0].id || 0) : null;
  const cutsThrough = (layer) =>
    windowReaches === "all" ? (layer.id || 0) !== baseId : Boolean(layer.windowed);

  return h("div", { style: { ...card, display: "flex", gap: 12 } },
    h("div", {
        ref: box, onPointerDown: onDown, onPointerMove: onMove,
        onPointerUp: letGo,
        onPointerCancel: letGo,
        onPointerLeave: (e) => { letGo(e); setCursor(null); },
        style: { width: W, height: H, background: "#000", borderRadius: 10,
                 overflow: "hidden", position: "relative",
                 cursor: tool === "pan" ? "grab" : "crosshair",
                 flex: "none" } },
      mask,
      // One moving frame. Everything below sits in sample coordinates and is
      // carried by this single transform, so no layer can drift from another.
      h("div", { style: { position: "absolute", left: 0, top: 0,
          transformOrigin: "0 0",
          ["--zmart-inverse-zoom"]: 1 / view.scale,
          transform: `translate(${view.tx}px, ${view.ty}px) scale(${view.scale})` } },
        shown.map((layer, i) =>
          h("div", { key: layer.id || i, style: {
              position: "absolute", left: ox, top: oy, width: ew, height: eh,
              opacity: solidity(layer, dim),
              // The window is cut through EVERY layer that follows it, all
              // at once — a window through one layer alone would reveal the
              // next layer down rather than the sample, which is the whole
              // point of it. The bottom layer is never cut: it is the thing
              // meant to show through.
              ...(cutsThrough(layer) && mask
                  // Only the standard property. The old prefixed one treats
                  // this as a picture to go and fetch rather than a mask drawn
                  // in the page, finds nothing, and hides the layer entirely.
                  ? { mask: `url(#${maskId})` }
                  : {}),
              // Never the container itself — it covers the whole sample and
              // would block every layer below it. Only what a layer actually
              // draws can be clicked, and only when that layer takes clicks.
              pointerEvents: "none" } },
            h(LayerBody, { layer, ox, oy, pics: streamed, picked: selection,
                           grabbed: holding })))),
      h("div", { style: { position: "absolute", left: 10, bottom: 8, display: "flex",
                          gap: 6 } },
        pill(`${shown.length} of ${(layers || []).length} layer(s)`),
        cursor ? pill(`x ${cursor.x.toFixed(0)} um · y ${cursor.y.toFixed(0)} um`) : null)),
    h("div", { style: { width: 230 } },
      h("div", { style: { fontWeight: 700, marginBottom: 8 } }, "the pointer"),
      h("div", { style: { display: "flex", gap: 6, marginBottom: 12 } },
        [["pan", "Move view"], ["focus", "Focus points"], ["move", "Move fields"]]
          .map(([name, label]) =>
            h("button", { key: name, disabled: readOnly,
              title: name === "pan" ? "drag to move the view"
                   : name === "focus" ? "click to add a focus point, click one to take it away"
                   : "drag a scan field to somewhere else",
              style: { ...btn(readOnly), padding: "3px 8px", fontSize: 11,
                       background: readOnly ? T.edge : (tool === name ? T.accent : T.edge),
                       color: tool === name ? "#ffffff" : T.ink },
              onClick: () => model.send({ type: "tool", value: name }) }, label))),
      h("div", { style: { fontWeight: 700, marginBottom: 8 } }, "layers"),
      (layers || []).map((layer, i) => {
        const hidden = layer.visible === false;
        return h("div", { key: layer.id || i, style: { display: "flex", alignItems: "center",
            gap: 8, marginBottom: 6 } },
          // One button per layer, saying what it will do rather than what the
          // layer currently is — an operator reads a button as an instruction.
          h("button", {
            title: hidden ? "draw this layer again" : "take this layer off the picture",
            "aria-pressed": hidden ? "false" : "true",
            disabled: readOnly,
            style: { ...btn(readOnly), padding: "3px 10px", minWidth: 58,
                     background: readOnly ? T.edge : (hidden ? T.edge : T.accent),
                     color: hidden ? T.ink : "#ffffff" },
            onClick: () => model.send({ type: "toggle", id: layer.id }) },
            hidden ? "Show" : "Hide"),
          h("span", { style: { flex: 1, color: hidden ? T.dim : T.ink,
                               textDecoration: hidden ? "line-through" : "none" } },
            layer.label || layer.kind),
          layer.dimmable ? pill("fades") : null);
      }),
      h("div", { style: { marginTop: 10, color: T.dim, fontSize: 12 } },
        `shared fade ${Math.round((Number(dim) || 0) * 100)}%`),
      h("input", { type: "range", min: 0, max: 100, value: Math.round((Number(dim) || 0) * 100),
        disabled: readOnly, style: { width: "100%" },
        onChange: (e) => model.send({ type: "dim", value: Number(e.target.value) / 100 }) }),
      h("div", { style: { color: T.dim, fontSize: 12, marginTop: 10 } }, status || "")));
}
export default mount(App);
"""
    )

    def __init__(self, layers: list[dict] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.layers = [self._layer_defaults(layer) for layer in (layers or [])]
        self._pictures: list[bytes] = []
        #: Called after the operator changes something on the picture, as
        #: ``on_edit(what, layer_id, details)`` — "place", "remove" or "move".
        #: The run sets this so a focus point put down here becomes one the
        #: microscope will actually measure, rather than only a drawing.
        self.on_edit: Callable[[str, str, dict], None] | None = None
        self.fit_extent()
        self.status = "drag to move, scroll to zoom — every layer moves together"

    @staticmethod
    def _layer_defaults(layer: dict) -> dict:
        """Fill in a layer's three choices, so a caller need only say what it is.

        The bottom layer is the thing being looked at, so it never follows the
        shared fade — stated here once rather than special-cased later.
        """
        filled = {
            "id": layer.get("id") or layer.get("kind", "layer"),
            "kind": layer.get("kind", "shapes"),
            "label": layer.get("label", ""),
            "visible": bool(layer.get("visible", True)),
            "opacity": float(layer.get("opacity", 1.0)),
            "dimmable": bool(layer.get("dimmable", True)),
            "interactive": bool(layer.get("interactive", False)),
            **{k: v for k, v in layer.items() if k not in _LAYER_CHOICES},
        }
        if filled["kind"] in ("engine", "images"):
            filled["dimmable"] = bool(layer.get("dimmable", False))
        # Following the dial and being cut by the window are separate
        # questions, though the answer is usually the same. A carrier outline
        # is the case where they differ: it may be worth keeping solid even
        # inside the window, so the operator does not lose their bearings
        # while looking at what shows through.
        filled["windowed"] = bool(layer.get("windowed", filled["dimmable"]))
        return filled

    # --- the layers ------------------------------------------------------------

    def set_layer(self, layer_id: str, **changes: Any) -> None:
        """Change one layer, leaving the rest of the picture exactly as it is."""
        updated = []
        for layer in self.layers:
            updated.append({**layer, **changes} if layer["id"] == layer_id else layer)
        self.layers = updated

    def add_layer(self, layer: dict, *, above: str | None = None) -> None:
        """Put a new layer into the stack, on top unless told otherwise."""
        filled = self._layer_defaults(layer)
        layers = [dict(existing) for existing in self.layers]
        if above is None:
            layers.append(filled)
        else:
            index = next((i for i, la in enumerate(layers) if la["id"] == above), len(layers) - 1)
            layers.insert(index + 1, filled)
        self.layers = layers
        self.fit_extent()

    def show_layer(self, layer_id: str, visible: bool = True) -> None:
        """Switch one layer on or off; off means not drawn at all."""
        self.set_layer(layer_id, visible=bool(visible))

    def look_at(self, cx: float, cy: float, scale: float | None = None) -> None:
        """Point the view at a place on the sample, in micrometres."""
        camera = {**self.camera, "cx": float(cx), "cy": float(cy)}
        if scale is not None:
            camera["scale"] = max(1e-9, float(scale))
        self.camera = camera

    def see_through(self, regions: list[dict] | None, *, outside: float = 1.0) -> None:
        """Make some areas of the sample show through the layers that fade.

        Each region is given in micrometres on the sample, so the window stays
        over the same piece of sample as the view is moved. Pass ``None`` to
        make everything solid again.
        """
        if not regions:
            self.opacity_map = {"kind": "none"}
            return
        self.opacity_map = {
            "kind": "regions",
            "regions": [dict(region) for region in regions],
            "outside": float(outside),
        }

    def show_picture(self, index: int, bounds: list[float], picture: bytes) -> None:
        """Put one picture on the imagery layer, as it becomes available.

        Called once per field as a scan produces it. The pixels travel as
        their own binary message rather than inside the page's description of
        itself, which is what keeps a scan of thousands of fields workable.
        """
        x0, y0, w, h = (float(v) for v in bounds)
        entry = {"x0": x0, "y0": y0, "w": w, "h": h}
        placed = [dict(image) for image in self.images]
        while len(placed) <= index:
            placed.append({})
        placed[index] = {**entry, "src": ""}
        self.images = placed
        while len(self._pictures) <= index:
            self._pictures.append(b"")
        self._pictures[index] = picture
        self.send(
            {
                "type": "image",
                "index": index,
                "entry": {**entry, "src": ""},
                "buffer_keys": ["src"],
                "mime": "image/jpeg",
            },
            buffers=[picture],
        )

    def push_snapshot(self) -> None:
        """Send every picture again, for a view that has only just opened.

        A browser opening part-way through a run — a refresh, a second tab —
        has the description of where each picture belongs but none of the
        pixels, because those were sent while it was not listening. Without
        this it would show empty frames where the sample should be.
        """
        self.send({"type": "image:reset", "preserve": True, "length": len(self._pictures)})
        for index, picture in enumerate(self._pictures):
            if not picture:
                continue
            entry = dict(self.images[index]) if index < len(self.images) else {}
            entry.pop("src", None)
            self.send(
                {
                    "type": "image",
                    "index": index,
                    "entry": {**entry, "src": ""},
                    "buffer_keys": ["src"],
                    "mime": "image/jpeg",
                },
                buffers=[picture],
            )

    def use_engine(self, label: str = "image engine") -> None:
        """Draw the imagery with an image engine instead of flat pictures.

        This is the whole of plugging in an engine that draws with the
        graphics card: the bottom layer changes kind, and everything above it
        is untouched, because nothing above it holds a position of its own —
        they all read the shared view, and so does the engine.
        """
        base = self.layers[0]["id"] if self.layers else None
        if base is None:
            raise ValueError("there is no bottom layer to draw the imagery with")
        self.set_layer(base, kind="engine", label=label)

    def use_pictures(self, label: str = "imagery") -> None:
        """Go back to drawing the imagery as flat pictures."""
        base = self.layers[0]["id"] if self.layers else None
        if base is None:
            raise ValueError("there is no bottom layer to draw the imagery with")
        self.set_layer(base, kind="images", label=label)

    def fit_extent(self, margin: float | None = None) -> None:
        """Work out the piece of sample the layers cover, with room to spare.

        Each layer is given this area as its own, which is what a window is
        cut out of; a layer with no area of its own has nothing to cut, and
        the window would quietly do nothing. Recomputed whenever the layers
        change, so a caller never has to set it by hand.
        """
        boxes = []
        for layer in self.layers:
            pictures = list(layer.get("images") or [])
            if layer.get("kind") in ("images", "engine"):
                pictures += list(self.images)
            for item in list(layer.get("shapes") or []) + pictures:
                bounds = item.get("bounds")
                if bounds is None and "x0" in item:
                    bounds = [item["x0"], item["y0"], item["w"], item["h"]]
                if bounds:
                    boxes.append([float(v) for v in bounds])
            for point in layer.get("points") or []:
                boxes.append([float(point["x"]), float(point["y"]), 0.0, 0.0])
        if not boxes:
            return
        if margin is None:
            # A little breathing room around whatever is there, in proportion
            # to it. A fixed margin looks right for a slide and swamps a scan
            # of four fields, which would then sit tiny in the middle.
            span = max(
                max(b[0] + b[2] for b in boxes) - min(b[0] for b in boxes),
                max(b[1] + b[3] for b in boxes) - min(b[1] for b in boxes),
            )
            margin = max(span * 0.04, 1.0)
        x0 = min(b[0] for b in boxes) - margin
        y0 = min(b[1] for b in boxes) - margin
        x1 = max(b[0] + b[2] for b in boxes) + margin
        y1 = max(b[1] + b[3] for b in boxes) + margin
        self.extent = [x0, y0, x1 - x0, y1 - y0]

    def set_images(self, layer_id: str, images: list[dict]) -> None:
        """Put pictures on a layer, each in its place on the sample.

        Every entry says where its picture belongs in micrometres —
        ``{"x0", "y0", "w", "h", "src"}`` — so the pictures land on the sample
        rather than on the screen, and are carried by the shared view like
        everything else. ``src`` is the picture itself; several entries may
        share one, in which case the browser decodes it once.
        """
        placed = []
        for image in images:
            missing = {"x0", "y0", "w", "h", "src"} - set(image)
            if missing:
                raise ValueError(f"a picture is missing {sorted(missing)}")
            placed.append(dict(image))
        self.set_layer(layer_id, images=placed)
        self.fit_extent()

    def see_through_fields(
        self,
        layer_id: str,
        indices: list[int] | None = None,
        *,
        opacity: float = 0.0,
        outside: float = 1.0,
    ) -> None:
        """Show the imagery through some or all of a layer's fields.

        The usual thing an operator wants is not a hand-drawn window but a
        real one: "let me see the sample under these scan fields". This takes
        the fields straight from a layer already on the canvas — the scan
        fields, the wells of a carrier, whatever that layer draws — and makes
        those the see-through areas.

        ``indices`` picks which of them; leave it out for all of them.
        ``opacity`` is how much of the covering layers is left over each field,
        so 0 shows the sample completely and 0.3 leaves a faint veil.
        ``outside`` is what happens everywhere else, normally fully solid.
        """
        layer = next((la for la in self.layers if la["id"] == layer_id), None)
        if layer is None:
            raise ValueError(f"there is no {layer_id!r} layer to take fields from")
        fields = layer.get("shapes") or layer.get("images") or []
        chosen = range(len(fields)) if indices is None else indices
        regions = []
        for index in chosen:
            if not 0 <= index < len(fields):
                raise ValueError(f"there is no field {index} on the {layer_id!r} layer")
            field = fields[index]
            bounds = field.get("bounds")
            if bounds is None and "x0" in field:
                bounds = [field["x0"], field["y0"], field["w"], field["h"]]
            if bounds is None:
                continue
            regions.append({"shape": "rect", "bounds": list(bounds), "opacity": float(opacity)})
        self.see_through(regions, outside=outside)

    # --- what the operator does on the picture ----------------------------------

    def _layer(self, layer_id: Any) -> dict | None:
        return next((la for la in self.layers if la["id"] == layer_id), None)

    def pick(self, layer_id: str, index: int) -> None:
        """Pick something out on the picture, or clear the choice with ``None``."""
        if layer_id is None:
            self.selection = {}
            return
        layer = self._layer(layer_id)
        if layer is None:
            return
        items = layer.get("shapes") or layer.get("points") or []
        if not 0 <= index < len(items):
            return
        self.selection = {"layer": layer_id, "index": int(index)}

    def place_point(self, layer_id: str, x: float, y: float) -> int:
        """Put a new point on the sample, and return which one it became."""
        layer = self._layer(layer_id)
        if layer is None:
            raise ValueError(f"there is no {layer_id!r} layer to put a point on")
        points = [dict(p) for p in (layer.get("points") or [])]
        points.append({"x": float(x), "y": float(y)})
        self.set_layer(layer_id, points=points)
        self.fit_extent()
        return len(points) - 1

    def remove_point(self, layer_id: str, index: int) -> None:
        """Take one point away again."""
        layer = self._layer(layer_id)
        if layer is None:
            return
        points = [dict(p) for p in (layer.get("points") or [])]
        if not 0 <= index < len(points):
            return
        points.pop(index)
        self.set_layer(layer_id, points=points)
        if self.selection.get("layer") == layer_id:
            self.selection = {}

    def move_item(self, layer_id: str, index: int, dx: float, dy: float) -> None:
        """Slide one shape or point across the sample by a distance."""
        layer = self._layer(layer_id)
        if layer is None:
            return
        if layer.get("shapes"):
            shapes = [dict(s) for s in layer["shapes"]]
            if not 0 <= index < len(shapes):
                return
            bounds = list(shapes[index].get("bounds") or [0, 0, 0, 0])
            bounds[0] += float(dx)
            bounds[1] += float(dy)
            shapes[index] = {**shapes[index], "bounds": bounds}
            self.set_layer(layer_id, shapes=shapes)
        elif layer.get("points"):
            points = [dict(p) for p in layer["points"]]
            if not 0 <= index < len(points):
                return
            points[index] = {**points[index],
                             "x": float(points[index]["x"]) + float(dx),
                             "y": float(points[index]["y"]) + float(dy)}
            self.set_layer(layer_id, points=points)
        else:
            return
        self.fit_extent()

    #: The layer a focus point is put on when the operator clicks bare sample.
    focus_layer = "focus"

    def _tell_the_run(self, what: str, layer_id: str, details: dict) -> None:
        """Pass one edit on to the run, without letting a mistake there stop the page."""
        if self.on_edit is None:
            return
        try:
            self.on_edit(what, layer_id, details)
        except Exception as exc:  # noqa: BLE001 -- the operator hears it, the page lives
            self.status = f"could not apply that: {exc}"

    def handle_message(self, content: dict) -> None:
        kind = content.get("type")
        if kind == "tool":
            wanted = content.get("value")
            if wanted in ("pan", "focus", "move"):
                self.tool = wanted
            return
        if kind in ("pick", "move", "remove"):
            layer_id = content.get("layer")
            try:
                index = int(content.get("index"))
            except (TypeError, ValueError, OverflowError):
                return
            if kind == "pick":
                self.pick(layer_id, index)
            elif kind == "remove":
                self.remove_point(layer_id, index)
                self._tell_the_run("remove", layer_id, {"index": index})
            else:
                try:
                    dx, dy = float(content.get("dx")), float(content.get("dy"))
                except (TypeError, ValueError):
                    return
                if math.isfinite(dx) and math.isfinite(dy):
                    self.move_item(layer_id, index, dx, dy)
                    self._tell_the_run("move", layer_id, {"index": index, "dx": dx, "dy": dy})
            return
        if kind == "place":
            try:
                x, y = float(content.get("x")), float(content.get("y"))
            except (TypeError, ValueError):
                return
            if math.isfinite(x) and math.isfinite(y):
                self.place_point(self.focus_layer, x, y)
                self._tell_the_run("place", self.focus_layer, {"x": x, "y": y})
            return
        if kind == "toggle":
            layer_id = content.get("id")
            current = next((la for la in self.layers if la["id"] == layer_id), None)
            if current is not None:
                self.show_layer(layer_id, not current.get("visible", True))
            return
        if kind == "dim":
            try:
                value = float(content.get("value"))
            except (TypeError, ValueError):
                return
            if math.isfinite(value):
                self.dim = min(1.0, max(0.0, value))
            return
        self.status = f"unknown message: {content.get('type')}"


#: The three choices every layer makes, plus its name — kept apart from
#: whatever that layer actually draws.
_LAYER_CHOICES = {
    "id",
    "kind",
    "label",
    "visible",
    "opacity",
    "dimmable",
    "windowed",
    "interactive",
}
