"""Zoomable overview mosaic with per-channel colour and contrast controls.

The overview step captures one image per tile position. This viewer places
every tile at its real frame position (micrometres), so together they form
the map of the sample the run actually scanned — and the normal matplotlib
pan/zoom tools let the operator move around it and zoom in, exactly like a
slide-scanner viewer.

The map can be opened empty and grow **live**: pass the viewer's
:meth:`OverviewViewer.add_acquisition` as ``run_overview``'s ``on_record``
callback and every tile appears on screen the moment the microscope saves
it, instead of the operator waiting for the whole scan.

Multi-channel images are shown as an additive colour overlay, the way most
microscopy viewers do it: each channel gets its own colour, and the controls
on the right adjust one channel at a time —

- the **channel** list picks which channel the controls act on;
- the **show** checkboxes turn individual channels on and off;
- the **colour** button steps the active channel through a palette
  (white, green, magenta, cyan, yellow, red, blue);
- the **display range** slider sets which intensities map to black and to
  full colour — dragging the lower handle up brightens the background away,
  narrowing the range increases contrast. This is the same "min/max" control
  as in Fiji/ImageJ's Brightness & Contrast.

Like the other widgets, interaction needs an interactive matplotlib backend
(`%matplotlib widget` in JupyterLab). Everything is also scriptable:
:meth:`OverviewViewer.set_channel` changes colour/visibility/range in code,
which is how the offline tests drive it.
"""

from __future__ import annotations

from typing import Any

from ._canvas import force_draw

# The colours a channel can wear, in the order the colour button cycles
# through them. White first — a white channel renders as plain grayscale,
# so a single-channel image just looks like the raw camera image — then the
# CVD-friendly microscopy staples.
CHANNEL_COLORS = ("white", "lime", "magenta", "cyan", "yellow", "red", "blue")
_DISPLAY_PIXEL_BUDGET = 20_000_000


def _load_channels(path: Any):
    """Read an image file as a ``(channels, height, width)`` stack.

    Accepts the shapes our saved images actually come in: a plain 2-D image
    (one channel) or a 3-D stack with the channel axis first or last (the
    channel axis is recognised as the small one — microscopy images have a
    handful of channels but thousands of pixels).
    """
    import numpy as np
    import tifffile

    arr = np.asarray(tifffile.imread(str(path)))
    arr = np.squeeze(arr)
    if arr.ndim == 2:
        return arr[None, :, :]
    if arr.ndim == 3:
        if arr.shape[0] <= 8 < min(arr.shape[1], arr.shape[2]):
            return arr
        if arr.shape[-1] <= 8 < min(arr.shape[0], arr.shape[1]):
            return np.moveaxis(arr, -1, 0)
    raise ValueError(
        f"{path}: cannot tell which axis holds the channels in shape "
        f"{arr.shape} — expected a 2-D image or a 3-D stack with few "
        f"channels and many pixels."
    )


def _load_overview_channels(overview: dict, *, step: int = 1):
    """Load one overview's single-file stack or indexed per-channel files."""
    import numpy as np

    paths = overview.get("channel_paths") or [overview["image_path"]]
    stacks = [_load_channels(path)[:, ::step, ::step] for path in paths]
    shapes = {stack.shape[1:] for stack in stacks}
    if len(shapes) != 1:
        raise ValueError(f"overview channel planes disagree on image shape: {sorted(shapes)}")
    return np.concatenate(stacks, axis=0)


def composite_channels(stack, channels):
    """Blend a ``(C, H, W)`` stack into one RGB image (additive overlay).

    ``channels`` is one display-state dict per channel, in channel order:
    ``{"color", "visible", "range": (lo, hi)}`` — the same state the viewers
    keep. Shared by the matplotlib viewer and the React viewer so both
    render a tile identically.
    """
    import numpy as np
    from matplotlib.colors import to_rgb

    h, w = stack.shape[1], stack.shape[2]
    rgb = np.zeros((h, w, 3), dtype=np.float32)
    for c, state in enumerate(channels):
        if not state["visible"]:
            continue
        lo, hi = state["range"]
        span = hi - lo if hi > lo else 1.0
        scaled = np.clip((stack[c].astype(np.float32) - lo) / span, 0.0, 1.0)
        rgb += scaled[:, :, None] * np.asarray(to_rgb(state["color"]), dtype=np.float32)
    return np.clip(rgb, 0.0, 1.0)


class OverviewViewer:
    """The overview tiles on one zoomable frame-coordinate map.

    Create it with the ``overviews`` list the workflow already builds for
    target discovery (:func:`~.discovery.build_overview_inputs`) — or with
    no tiles at all, and stream them in with :meth:`add_acquisition` /
    :meth:`add_tile` while the microscope scans.

    ``downsample`` (display only) skips pixels to keep very large mosaics
    responsive; the placement and extent stay exact. When tiles are given
    up front it defaults to whatever keeps the display under a fixed pixel
    budget; a viewer that starts empty shows full resolution unless a
    ``downsample`` is passed.
    """

    def __init__(
        self, overviews: list[dict] | None = None, *, downsample: int | None = None
    ) -> None:
        import matplotlib.pyplot as plt
        import numpy as np

        self.overviews: list[dict] = []
        self._stacks: list[Any] = []
        self._images: list[Any] = []
        self.n_channels: int | None = None
        #: Per-channel display state: colour name, visibility, and the
        #: (low, high) intensity range mapped to black..full colour.
        self.channels: dict[int, dict] = {}
        self._active = 0
        self._controls_built = False

        overviews = list(overviews or [])
        if downsample is not None:
            step = max(1, int(downsample))
        elif overviews:
            total_pixels = sum(
                int(o["image_size_px"][0])
                * int(o["image_size_px"][1])
                * len(o.get("channel_paths") or [o["image_path"]])
                for o in overviews
            )
            step = max(1, int(np.ceil(np.sqrt(total_pixels / _DISPLAY_PIXEL_BUDGET))))
        else:
            step = 1
        self.downsample = step

        self.fig = plt.figure(figsize=(9, 7))
        # Leave room on the left for the y-axis label.
        self.ax = self.fig.add_axes([0.09, 0.08, 0.61, 0.86])
        self.ax.set_xlabel("frame x (um)")
        self.ax.set_ylabel("frame y (um)")
        self.ax.set_aspect("equal")
        self.ax.set_title("waiting for the first overview tile...")

        for overview in overviews:
            self.add_tile(overview, draw=False)
        if self._stacks:
            # Batch construction: base the initial display ranges on ALL
            # tiles together, exactly as if they had arrived at once.
            self._init_channel_state()
            self._refresh()
        self.fig.canvas.draw_idle()

    # --- growing the map ----------------------------------------------------

    def add_acquisition(self, index: int, position: dict, record: dict) -> dict:
        """Add one fresh overview acquisition to the map (live streaming).

        Matches the ``on_record(index, position, record)`` callback shape of
        :func:`~.steps.run_overview`, so the notebook can pass this method
        directly and watch the mosaic grow tile by tile during the scan.
        Returns the overview entry it built (also kept on ``self.overviews``).
        """
        from ._records import record_channel_paths
        from .discovery import read_overview_geometry

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

    def add_tile(self, overview: dict, *, draw: bool = True) -> None:
        """Place one more tile on the map at its real frame position."""
        stack = _load_overview_channels(overview, step=self.downsample)
        if self.n_channels is None:
            self.n_channels = stack.shape[0]
        elif stack.shape[0] != self.n_channels:
            raise ValueError(
                f"tiles disagree on channel count: {sorted({self.n_channels, stack.shape[0]})}"
            )
        self.overviews.append(overview)
        self._stacks.append(stack)

        first_tile = not self.channels
        if first_tile:
            self._init_channel_state()

        cx, cy = overview["center_frame_um"]
        h_px, w_px = overview["image_size_px"]
        ps = float(overview["pixel_size_um"])
        half_w, half_h = w_px * ps / 2.0, h_px * ps / 2.0
        image = self.ax.imshow(
            self._composite(stack),
            # Row 0 sits at the tile's smallest y, matching how pixel
            # coordinates map to frame coordinates everywhere else in
            # the pipeline (overview_pixel_to_frame).
            extent=(cx - half_w, cx + half_w, cy + half_h, cy - half_h),
            interpolation="nearest",
        )
        self._images.append(image)
        self.ax.autoscale()
        self._set_title()
        if draw:
            force_draw(self.fig)

    def reload(self) -> None:
        """Re-read every tile's file from disk and refresh the map.

        Needed after something rewrites the saved images in place — the
        simulation-mode hijack does exactly that after the scan.
        """
        self._stacks = [
            _load_overview_channels(o, step=self.downsample) for o in self.overviews
        ]
        self._refresh()

    def _set_title(self) -> None:
        self.ax.set_title(
            f"{len(self.overviews)} overview tile(s), {self.n_channels} channel(s) "
            f"— pan/zoom with the toolbar"
            + (f" (display 1/{self.downsample} pixels)" if self.downsample > 1 else "")
        )

    def _init_channel_state(self) -> None:
        """Set the per-channel colours and display ranges from the loaded tiles.

        Runs once, when the first tile(s) arrive; later tiles inherit the
        same display settings so a growing map does not re-brighten under
        the operator's eyes. It also builds the on-figure controls, whose
        layout needs the channel count.
        """
        import numpy as np

        self.channels = {}
        for c in range(self.n_channels):
            values = np.concatenate([s[c].ravel() for s in self._stacks])
            full_lo, full_hi = float(values.min()), float(values.max())
            if full_hi <= full_lo:
                full_hi = full_lo + 1.0
            lo, hi = (float(v) for v in np.percentile(values, (1.0, 99.5)))
            if hi - lo < 1e-9:
                # A (nearly) flat channel: a percentile window would map it
                # all to black. Show its actual value instead.
                lo, hi = min(0.0, full_lo), full_hi
            self.channels[c] = {
                "color": CHANNEL_COLORS[c % len(CHANNEL_COLORS)],
                "visible": True,
                "range": (lo, hi),
                # The slider's bounds: wide enough to hold both the data and
                # the initial window.
                "full_range": (min(full_lo, lo, 0.0), max(full_hi, hi)),
            }
        if not self._controls_built:
            self._build_controls()

    def _build_controls(self) -> None:
        """The control column; built once the channel count is known."""
        from matplotlib.widgets import Button, CheckButtons, RadioButtons

        # Widget references are kept on self: matplotlib widgets stop
        # responding once garbage-collected.
        labels = [f"ch {c}" for c in range(self.n_channels)]
        self._radio_ax = self.fig.add_axes([0.74, 0.66, 0.22, 0.26])
        self._radio_ax.set_title("channel", fontsize=9)
        self._radio = RadioButtons(self._radio_ax, labels)
        self._radio.on_clicked(self._on_channel_selected)

        self._check_ax = self.fig.add_axes([0.74, 0.38, 0.22, 0.24])
        self._check_ax.set_title("show", fontsize=9)
        self._checks = CheckButtons(self._check_ax, labels, [True] * self.n_channels)
        self._checks.on_clicked(self._on_visibility_toggled)

        self._color_ax = self.fig.add_axes([0.74, 0.28, 0.22, 0.06])
        self._color_button = Button(self._color_ax, self._color_label())
        self._color_button.on_clicked(self._on_color_cycled)

        self._slider_ax = None
        self._slider = None
        self._rebuild_range_slider()
        self._controls_built = True

    # --- public, scriptable controls --------------------------------------

    def set_channel(
        self,
        channel: int,
        *,
        color: str | None = None,
        visible: bool | None = None,
        vmin: float | None = None,
        vmax: float | None = None,
    ) -> None:
        """Change one channel's colour / visibility / display range in code.

        Does exactly what the on-figure controls do, for use from a script
        or on a static backend where clicking is not available.
        """
        if not self.channels:
            raise RuntimeError("no tiles loaded yet — add a tile before adjusting channels")
        state = self.channels[channel]
        if color is not None:
            state["color"] = color
        if visible is not None:
            state["visible"] = bool(visible)
        lo, hi = state["range"]
        if vmin is not None:
            lo = float(vmin)
        if vmax is not None:
            hi = float(vmax)
        state["range"] = (lo, hi)
        self._refresh()

    # --- rendering ---------------------------------------------------------

    def _composite(self, stack):
        return composite_channels(stack, [self.channels[c] for c in range(self.n_channels)])

    def _refresh(self) -> None:
        for image, stack in zip(self._images, self._stacks, strict=True):
            image.set_data(self._composite(stack))
        self.fig.canvas.draw_idle()

    # --- control callbacks ---------------------------------------------------

    def _color_label(self) -> str:
        return f"colour: {self.channels[self._active]['color']}"

    def _on_channel_selected(self, label: str) -> None:
        self._active = int(label.split()[-1])
        self._color_button.label.set_text(self._color_label())
        self._rebuild_range_slider()
        self.fig.canvas.draw_idle()

    def _on_visibility_toggled(self, label: str) -> None:
        channel = int(label.split()[-1])
        state = self.channels[channel]
        state["visible"] = not state["visible"]
        self._refresh()

    def _on_color_cycled(self, _event: Any) -> None:
        state = self.channels[self._active]
        index = CHANNEL_COLORS.index(state["color"]) if state["color"] in CHANNEL_COLORS else -1
        state["color"] = CHANNEL_COLORS[(index + 1) % len(CHANNEL_COLORS)]
        self._color_button.label.set_text(self._color_label())
        self._refresh()

    def _on_range_changed(self, value: tuple[float, float]) -> None:
        self.channels[self._active]["range"] = (float(value[0]), float(value[1]))
        self._refresh()

    def _rebuild_range_slider(self) -> None:
        """(Re)create the display-range slider for the active channel.

        A RangeSlider's bounds are fixed at construction, and each channel
        has its own intensity range — so switching channels swaps the
        slider out rather than re-scaling it.
        """
        from matplotlib.widgets import RangeSlider

        if self._slider_ax is not None:
            self._slider_ax.remove()
        state = self.channels[self._active]
        full_lo, full_hi = state["full_range"]
        self._slider_ax = self.fig.add_axes([0.76, 0.12, 0.18, 0.05])
        self._slider = RangeSlider(
            self._slider_ax,
            "",
            full_lo,
            full_hi,
            valinit=state["range"],
        )
        self._slider_ax.set_title("display range", fontsize=9)
        self._slider.valtext.set_visible(False)
        self._slider.on_changed(self._on_range_changed)


def view_overview(
    overviews: list[dict] | None = None, *, downsample: int | None = None
) -> OverviewViewer:
    """Open the overview mosaic viewer; returns the :class:`OverviewViewer`.

    ``overviews`` is the list from
    :func:`~.steps.overview_inputs_from_records` (the same one target
    discovery consumes) — or ``None``/empty to open an empty map and stream
    tiles in live via ``run_overview(..., on_record=viewer.add_acquisition)``.
    ``downsample`` shows every n-th pixel for very large mosaics (display
    only — positions and sizes stay exact).
    """
    return OverviewViewer(overviews, downsample=downsample)
