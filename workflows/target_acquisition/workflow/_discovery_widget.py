"""Explore discovered cells and gate which ones become targets.

After segmentation, every discovered cell is a dot in a scatter plot, and
the operator decides — visually — which cells the run should re-image. The
figure gives three ways to work:

- **choose the axes**: the radio lists on the right put any measured
  feature on x and y (position, area, brightness — whatever the
  segmentation reported), so the plot can be a spatial map, an
  area-vs-intensity cloud, or anything in between;
- **gate**: drag the two range sliders to set thresholds on the current x
  and y features, or draw a free-form region around points with the mouse
  (a lasso). Points inside the gate stay coloured; everything else fades
  to gray. The gate is the AND of both: sliders always apply, and a lasso
  narrows it further ("clear lasso" removes it);
- **inspect**: hovering near a dot shows that cell's image crop in the
  side panel, cut from its overview tile, so a suspicious point can be
  judged by its actual picture before it is kept or gated out.

``explorer.gated`` is the list of targets inside the gate — the
acquisition step samples from it. Interaction needs an interactive
matplotlib backend (``%matplotlib widget`` in JupyterLab); everything is
also scriptable (:meth:`TargetExplorer.set_axes`,
:meth:`TargetExplorer.set_ranges`), which is how the offline tests run.
"""

from __future__ import annotations

import math
from typing import Any

# How close (screen pixels) the pointer must be to a dot for the side
# panel to show that cell's crop.
_HOVER_RADIUS_PX = 12.0


def _numeric_features(targets: list[dict]) -> list[str]:
    """The feature names every plot axis can use, across all targets.

    ``x`` and ``y`` (the frame position) always exist; any numeric value the
    segmentation put in ``target["source"]`` (area, intensity, ...) is
    offered too.
    """
    names: list[str] = ["x", "y"]
    # naming_p is the tile the cell came from — an identifier, not a
    # measurement — so it never becomes a plot axis.
    seen = set(names) | {"naming_p"}
    candidates = dict.fromkeys(
        key for target in targets for key in (target.get("source") or {}) if key not in seen
    )
    for key in candidates:
        values = [(target.get("source") or {}).get(key) for target in targets]
        if all(
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
            for value in values
        ):
            names.append(key)
    return names


def _feature_value(target: dict, feature: str) -> float:
    if feature in ("x", "y"):
        return float(target[feature])
    value = (target.get("source") or {}).get(feature)
    return float(value) if value is not None else float("nan")


def crop_for_target(target: dict, overviews: dict[int, dict], *, crop_um: float):
    """One cell's picture, cut from its overview tile, or ``None``.

    ``overviews`` maps the tile index (``naming_p``) to the overview entry.
    Shared by the matplotlib explorer and the React explorer so the hover
    panel shows the identical crop in both.
    """
    source = target.get("source") or {}
    overview = overviews.get(source.get("naming_p"))
    centroid = source.get("centroid_col_row_px")
    if overview is None or centroid is None:
        return None
    from ._geom import crop_overview_at_target_fov
    from ._overview_widget import _load_channels

    pixel_size = float(overview["pixel_size_um"])
    side_px = max(1, round(crop_um / pixel_size))
    return crop_overview_at_target_fov(
        _load_channels(overview["image_path"])[0],
        centroid_col_row_px=tuple(centroid),
        source_pixel_size_um=pixel_size,
        # A square window of crop_um a side, expressed as a "target FOV" so
        # the shared window math (and its edge padding) is reused instead of
        # re-derived here.
        target_shape_px=(side_px, side_px),
        target_pixel_size_um=pixel_size,
    )


class TargetExplorer:
    """Scatter, gate, and inspect the discovered cells before acquiring.

    ``targets`` is :func:`~.discovery.discover_targets` output;
    ``overviews`` is the same list the discovery ran on (used to cut each
    cell's crop for the hover panel). ``crop_um`` is the side length of
    that crop in micrometres.
    """

    def __init__(
        self,
        targets: list[dict],
        overviews: list[dict] | None = None,
        *,
        crop_um: float = 60.0,
    ) -> None:
        import matplotlib.pyplot as plt
        from matplotlib.widgets import Button, LassoSelector, RadioButtons, RangeSlider

        if not targets:
            raise ValueError("no targets to explore — run target discovery first")
        self.targets = targets
        self.overviews = {i: o for i, o in enumerate(overviews or [])}
        self.crop_um = float(crop_um)
        self.features = _numeric_features(targets)
        self._x_feature = self.features[0]
        self._y_feature = self.features[1] if len(self.features) > 1 else self.features[0]
        self._lasso_path = None  # matplotlib Path in data coords, or None
        self._crop_cache: dict[int, Any] = {}

        self.fig = plt.figure(figsize=(10, 6.5))
        self.ax = self.fig.add_axes([0.07, 0.24, 0.50, 0.70])
        self._crop_ax = self.fig.add_axes([0.60, 0.45, 0.17, 0.30])
        self._crop_ax.set_axis_off()
        self._crop_ax.set_title("hover a point", fontsize=9)

        # Axis choosers.
        self._x_radio_ax = self.fig.add_axes([0.80, 0.60, 0.17, 0.30])
        self._x_radio_ax.set_title("x axis", fontsize=9)
        self._x_radio = RadioButtons(self._x_radio_ax, self.features, active=0)
        self._x_radio.on_clicked(self._on_x_feature)
        self._y_radio_ax = self.fig.add_axes([0.80, 0.24, 0.17, 0.30])
        self._y_radio_ax.set_title("y axis", fontsize=9)
        self._y_radio = RadioButtons(
            self._y_radio_ax, self.features, active=self.features.index(self._y_feature)
        )
        self._y_radio.on_clicked(self._on_y_feature)

        # Threshold sliders (one per current axis) + the lasso.
        self._x_slider_ax = None
        self._y_slider_ax = None
        self._x_slider: RangeSlider | None = None
        self._y_slider: RangeSlider | None = None

        self._clear_ax = self.fig.add_axes([0.60, 0.30, 0.17, 0.06])
        self._clear_button = Button(self._clear_ax, "clear lasso")
        self._clear_button.on_clicked(self._on_clear_lasso)

        self._scatter = None
        self._lasso: LassoSelector | None = None
        self.fig.canvas.mpl_connect("motion_notify_event", self._on_hover)

        self._rebuild_axes()

    # --- gating ------------------------------------------------------------

    @property
    def gated(self) -> list[dict]:
        """The targets inside the gate (sliders AND lasso) — what acquisition samples."""
        return [t for t, keep in zip(self.targets, self._gate_mask(), strict=True) if keep]

    def _gate_mask(self) -> list[bool]:
        import numpy as np

        xs = np.array([_feature_value(t, self._x_feature) for t in self.targets])
        ys = np.array([_feature_value(t, self._y_feature) for t in self.targets])
        mask = np.ones(len(self.targets), dtype=bool)
        if self._x_slider is not None:
            lo, hi = self._x_slider.val
            mask &= (xs >= lo) & (xs <= hi)
        if self._y_slider is not None:
            lo, hi = self._y_slider.val
            mask &= (ys >= lo) & (ys <= hi)
        if self._lasso_path is not None:
            points = np.column_stack([xs, ys])
            mask &= self._lasso_path.contains_points(points)
        return mask.tolist()

    def set_axes(self, x_feature: str, y_feature: str) -> None:
        """Put ``x_feature`` / ``y_feature`` on the plot axes (in code)."""
        for feature in (x_feature, y_feature):
            if feature not in self.features:
                raise ValueError(f"unknown feature {feature!r}; have {self.features}")
        if self._x_radio.value_selected != x_feature:
            self._x_radio.set_active(self.features.index(x_feature))
        if self._y_radio.value_selected != y_feature:
            self._y_radio.set_active(self.features.index(y_feature))

    def set_ranges(
        self,
        x_range: tuple[float, float] | None = None,
        y_range: tuple[float, float] | None = None,
    ) -> None:
        """Set the threshold sliders in code (same effect as dragging them)."""
        if x_range is not None:
            self._x_slider.set_val(x_range)
        if y_range is not None:
            self._y_slider.set_val(y_range)

    # --- callbacks -----------------------------------------------------------

    def _on_x_feature(self, label: str) -> None:
        self._x_feature = label
        self._rebuild_axes()

    def _on_y_feature(self, label: str) -> None:
        self._y_feature = label
        self._rebuild_axes()

    def _on_lasso(self, vertices: list[tuple[float, float]]) -> None:
        from matplotlib.path import Path as MplPath

        # A degenerate lasso (a click) has no area; treat it as no lasso.
        self._lasso_path = MplPath(vertices) if len(vertices) >= 3 else None
        self._restyle()

    def _on_clear_lasso(self, _event: Any) -> None:
        self._lasso_path = None
        self._restyle()

    def _on_slider(self, _value: Any) -> None:
        self._restyle()

    def _on_hover(self, event: Any) -> None:
        if event.inaxes is not self.ax or event.xdata is None:
            return
        index = self._nearest_target_index(event)
        if index is not None:
            self._show_crop(index)

    # --- drawing ---------------------------------------------------------------

    def _rebuild_axes(self) -> None:
        """Redraw the scatter and rebuild both sliders for the current features.

        Changing an axis feature changes the numeric range a slider must
        span, and a RangeSlider's bounds are fixed at construction — so a
        feature switch swaps the sliders out. The lasso is cleared too: it
        was drawn in the old coordinate space and would gate nonsense in
        the new one.
        """
        import numpy as np
        from matplotlib.widgets import LassoSelector, RangeSlider

        self._lasso_path = None
        xs = np.array([_feature_value(t, self._x_feature) for t in self.targets])
        ys = np.array([_feature_value(t, self._y_feature) for t in self.targets])

        if self._lasso is not None:
            self._lasso.disconnect_events()
        self.ax.clear()
        self._scatter = self.ax.scatter(xs, ys, s=40, zorder=3)
        self.ax.set_xlabel(self._x_feature)
        self.ax.set_ylabel(self._y_feature)

        def _bounds(values: np.ndarray) -> tuple[float, float]:
            lo, hi = float(np.nanmin(values)), float(np.nanmax(values))
            if hi - lo < 1e-9:  # a flat feature still needs a draggable span
                lo, hi = lo - 1.0, hi + 1.0
            return lo, hi

        for slider_ax in (self._x_slider_ax, self._y_slider_ax):
            if slider_ax is not None:
                slider_ax.remove()
        x_lo, x_hi = _bounds(xs)
        y_lo, y_hi = _bounds(ys)
        self._x_slider_ax = self.fig.add_axes([0.10, 0.11, 0.42, 0.035])
        self._x_slider = RangeSlider(
            self._x_slider_ax, "", x_lo, x_hi, valinit=(x_lo, x_hi)
        )
        self._x_slider_ax.set_title(self._x_feature, fontsize=8, loc="left", pad=1)
        self._x_slider.on_changed(self._on_slider)
        self._y_slider_ax = self.fig.add_axes([0.10, 0.035, 0.42, 0.035])
        self._y_slider = RangeSlider(
            self._y_slider_ax, "", y_lo, y_hi, valinit=(y_lo, y_hi)
        )
        self._y_slider_ax.set_title(self._y_feature, fontsize=8, loc="left", pad=1)
        self._y_slider.on_changed(self._on_slider)
        self._lasso = LassoSelector(self.ax, onselect=self._on_lasso)
        self._restyle()

    def _restyle(self) -> None:
        """Recolour the dots to the current gate and refresh the count."""
        mask = self._gate_mask()
        colors = ["tab:blue" if keep else "0.8" for keep in mask]
        self._scatter.set_color(colors)
        self.ax.set_title(
            f"{sum(mask)} of {len(self.targets)} targets in the gate "
            f"(sliders{' + lasso' if self._lasso_path is not None else ''})"
        )
        self.fig.canvas.draw_idle()

    # --- hover crop ---------------------------------------------------------------

    def _nearest_target_index(self, event: Any) -> int | None:
        best, best_d2 = None, _HOVER_RADIUS_PX**2
        for i, target in enumerate(self.targets):
            fx = _feature_value(target, self._x_feature)
            fy = _feature_value(target, self._y_feature)
            px, py = self.ax.transData.transform((fx, fy))
            d2 = (px - event.x) ** 2 + (py - event.y) ** 2
            if d2 <= best_d2:
                best, best_d2 = i, d2
        return best

    def _show_crop(self, index: int) -> None:
        crop = self._crop_for(index)
        self._crop_ax.clear()
        self._crop_ax.set_axis_off()
        if crop is None:
            self._crop_ax.set_title("no image for this point", fontsize=9)
        else:
            self._crop_ax.imshow(crop, cmap="gray", interpolation="nearest")
            source = self.targets[index].get("source") or {}
            self._crop_ax.set_title(
                f"target {index} (tile {source.get('naming_p', '?')})", fontsize=9
            )
        self.fig.canvas.draw_idle()

    def _crop_for(self, index: int):
        """This cell's picture, cut from its overview tile (cached per call)."""
        if index not in self._crop_cache:
            self._crop_cache[index] = crop_for_target(
                self.targets[index], self.overviews, crop_um=self.crop_um
            )
        return self._crop_cache[index]


def explore_targets(
    targets: list[dict],
    overviews: list[dict] | None = None,
    *,
    crop_um: float = 60.0,
) -> TargetExplorer:
    """Open the target explorer; returns the :class:`TargetExplorer`.

    ``targets`` is the :func:`~.discovery.discover_targets` output and
    ``overviews`` the list it ran on (needed for the hover crops).
    ``explorer.gated`` is what the acquisition step samples from.
    """
    return TargetExplorer(targets, overviews, crop_um=crop_um)
