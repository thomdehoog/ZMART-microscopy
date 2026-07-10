"""Zoomable overview mosaic with per-channel colour and contrast controls.

The overview step captures one image per tile position. This viewer places
every tile at its real frame position (micrometres), so together they form
the map of the sample the run actually scanned — and the normal matplotlib
pan/zoom tools let the operator move around it and zoom in, exactly like a
slide-scanner viewer.

Multi-channel images are shown as an additive colour overlay, the way most
microscopy viewers do it: each channel gets its own colour, and the controls
on the right adjust one channel at a time —

- the **channel** list picks which channel the controls act on;
- the **show** checkboxes turn individual channels on and off;
- the **colour** button steps the active channel through a palette
  (gray, green, magenta, cyan, yellow, red, blue);
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

# The colours a channel can wear, in the order the colour button cycles
# through them. White first — a white channel renders as plain grayscale,
# so a single-channel image just looks like the raw camera image — then the
# CVD-friendly microscopy staples.
CHANNEL_COLORS = ("white", "lime", "magenta", "cyan", "yellow", "red", "blue")


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


class OverviewViewer:
    """The overview tiles on one zoomable frame-coordinate map.

    Create it with the ``overviews`` list the workflow already builds for
    target discovery (:func:`~.discovery.build_overview_inputs`): each entry
    names the saved image, the frame position it was captured at, and its
    pixel size — everything needed to place the tile at its true position
    and physical size.

    ``downsample`` (display only) skips pixels to keep very large mosaics
    responsive; the placement and extent stay exact. The underlying data is
    untouched — zooming shows the downsampled grid, not re-read detail.
    """

    def __init__(self, overviews: list[dict], *, downsample: int = 1) -> None:
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib.widgets import Button, CheckButtons, RadioButtons, RangeSlider

        if not overviews:
            raise ValueError("no overviews to show — run the overview step first")
        self.overviews = overviews
        step = max(1, int(downsample))

        # Load every tile as (C, H, W); all tiles must agree on the channel
        # count (they come from the same job).
        self._stacks = [_load_channels(o["image_path"])[:, ::step, ::step] for o in overviews]
        counts = {s.shape[0] for s in self._stacks}
        if len(counts) != 1:
            raise ValueError(f"tiles disagree on channel count: {sorted(counts)}")
        self.n_channels = counts.pop()

        #: Per-channel display state: colour name, visibility, and the
        #: (low, high) intensity range mapped to black..full colour.
        self.channels: dict[int, dict] = {}
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
        self._active = 0

        self.fig = plt.figure(figsize=(9, 7))
        self.ax = self.fig.add_axes([0.06, 0.06, 0.64, 0.88])
        self._images = []
        for overview, stack in zip(self.overviews, self._stacks, strict=True):
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
        self.ax.set_xlabel("frame x (um)")
        self.ax.set_ylabel("frame y (um)")
        self.ax.set_aspect("equal")
        self.ax.autoscale()
        self.ax.set_title(
            f"{len(self.overviews)} overview tile(s), {self.n_channels} channel(s) "
            f"— pan/zoom with the toolbar"
        )

        # Control column. Widget references are kept on self: matplotlib
        # widgets stop responding once garbage-collected.
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
        self._slider: RangeSlider | None = None
        self._rebuild_range_slider()

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
        """Blend a tile's channels into one RGB image (additive overlay)."""
        import numpy as np
        from matplotlib.colors import to_rgb

        h, w = stack.shape[1], stack.shape[2]
        rgb = np.zeros((h, w, 3), dtype=np.float32)
        for c in range(self.n_channels):
            state = self.channels[c]
            if not state["visible"]:
                continue
            lo, hi = state["range"]
            span = hi - lo if hi > lo else 1.0
            scaled = np.clip((stack[c].astype(np.float32) - lo) / span, 0.0, 1.0)
            rgb += scaled[:, :, None] * np.asarray(to_rgb(state["color"]), dtype=np.float32)
        return np.clip(rgb, 0.0, 1.0)

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
            "display\nrange",
            full_lo,
            full_hi,
            valinit=state["range"],
        )
        self._slider.on_changed(self._on_range_changed)


def view_overview(overviews: list[dict], *, downsample: int = 1) -> OverviewViewer:
    """Open the overview mosaic viewer; returns the :class:`OverviewViewer`.

    ``overviews`` is the list from
    :func:`~.steps.overview_inputs_from_records` (the same one target
    discovery consumes). ``downsample`` shows every n-th pixel for very
    large mosaics (display only — positions and sizes stay exact).
    """
    return OverviewViewer(overviews, downsample=downsample)
