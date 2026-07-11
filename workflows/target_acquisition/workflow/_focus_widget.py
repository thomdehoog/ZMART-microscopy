"""Interactive focus-point picking with an in-figure focus-map heatmap.

This is the notebook's Focus step (step 5) as one figure the operator works
in directly. The figure shows the overview positions for context; the operator
clicks where the microscope should autofocus, then presses the **Measure
focus** button. The stage visits each picked point, runs the autofocus job
there, and collects the sharp z it reports. The measured points are fitted
into a :class:`~._focus_surface.FocusSurface`, and that surface is drawn as a
heatmap behind the points in the same figure — so choosing points, measuring
them, and judging the resulting focus map all happen in one place.

Clicking needs an *interactive* matplotlib backend. In JupyterLab, run
``%matplotlib widget`` once (this needs the ``ipympl`` package) before
creating the picker. On a static backend (like the default ``inline`` one)
the figure still renders, but clicks do nothing — points can then be added in
code with :meth:`FocusPicker.add_point`, which is also how the offline tests
drive it.

The stage moves through the controller session's gated ``set_xyz``, exactly
like every other move in the workflow — the widget adds no new way to move
the microscope, only a friendlier way to choose where.
"""

from __future__ import annotations

import time
from typing import Any

from ._canvas import force_draw
from ._focus_run import measure_focus
from ._focus_surface import fit_focus_surface

# How close (in screen pixels) a right-click must land to an existing point
# to remove it. Screen pixels, not micrometres, so the feel of "clicking on
# a point" does not change with the zoom level.
_REMOVE_RADIUS_PX = 12.0

# Ignore Measure clicks arriving within this window after a run finishes:
# clicks queued while the stage was measuring would otherwise start a
# second, unwanted measurement run the moment the first completes.
_QUEUED_CLICK_WINDOW_S = 2.0


class FocusPicker:
    """One figure to pick focus points, measure them, and see the focus map.

    Create it with the controller session and (optionally) the overview
    positions, which are drawn as hollow squares for context. Any focus
    points already placed in LAS X are pre-filled, so work done at the
    microscope is not lost. Then:

    - **left-click** adds a focus point where you clicked;
    - **right-click** removes the nearest point (within a small radius);
    - the **Measure focus** button visits every point, autofocuses, fits the
      focus surface, and draws it as a heatmap behind the points.

    After measuring, ``picker.focus`` holds the fitted
    :class:`~._focus_surface.FocusSurface` the rest of the run uses (and
    :meth:`require_focus` fetches it with a helpful error if measuring was
    skipped). Press the button again after adding or moving points to
    re-measure; the heatmap updates in place.
    """

    def __init__(
        self,
        session: Any,
        positions: list[dict] | None = None,
        *,
        af_job: str | None = None,
        start_z: float | None = None,
        seed: bool = True,
        grid: int = 40,
    ) -> None:
        import matplotlib.pyplot as plt
        from matplotlib.widgets import Button

        self.session = session
        self.positions = [dict(p) for p in (positions or [])]
        self.af_job = af_job
        self.start_z = start_z
        self.grid = int(grid)

        #: The picked focus points, each ``{"x": float, "y": float}`` in frame
        #: micrometres. Edited by clicks or :meth:`add_point`/:meth:`remove_point`.
        self.points: list[dict] = []
        #: What :meth:`measure` collected: ``[{"x_um", "y_um", "z_um"}]``.
        self.measured: list[dict] | None = None
        #: The fitted focus surface, set by :meth:`measure`.
        self.focus: Any = None
        self._measured_points: list[dict] | None = None
        self._last_measure_ended: float | None = None

        if seed:
            self.points = self._seed_from_lasx()

        self.fig, self.ax = plt.subplots(figsize=(7, 6))
        # Leave room under the axes for the button row.
        self.fig.subplots_adjust(bottom=0.16)
        self._button_ax = self.fig.add_axes([0.66, 0.03, 0.24, 0.07])
        # Keep a reference: matplotlib buttons stop responding if the Button
        # object is garbage-collected.
        self._button = Button(self._button_ax, "Measure focus")
        self._button.on_clicked(self._on_measure_clicked)
        self.fig.canvas.mpl_connect("button_press_event", self._on_click)

        self._points_artist = None
        self._heatmap = None
        self._colorbar = None
        self._z_labels: list[Any] = []
        # Autofocus results already collected this session, keyed by the
        # point's exact coordinates — re-measuring reuses them, so editing
        # the points only sends the stage to the NEW or moved ones.
        self._af_cache: dict[tuple[float, float], dict] = {}

        self._squares_artist = None
        if self.positions:
            self._squares_artist = self.ax.scatter(
                [p["x"] for p in self.positions],
                [p["y"] for p in self.positions],
                marker="s",
                facecolors="none",
                edgecolors="tab:blue",
                s=90,
                label=f"overviews ({len(self.positions)})",
                zorder=2,
            )
        self.ax.set_xlabel("frame x (um)")
        self.ax.set_ylabel("frame y (um)")
        self.ax.set_aspect("equal", adjustable="datalim")
        self._redraw_points()

    # --- picking ---------------------------------------------------------

    def add_point(self, x: float, y: float) -> dict:
        """Add a focus point at frame ``(x, y)`` micrometres; returns it."""
        self._invalidate_focus()
        point = {"x": float(x), "y": float(y)}
        self.points.append(point)
        self._redraw_points()
        return point

    def remove_point(self, index: int) -> dict:
        """Remove (and return) the picked point at ``index``."""
        self._invalidate_focus()
        point = self.points.pop(index)
        self._redraw_points()
        return point

    def _seed_from_lasx(self) -> list[dict]:
        """Focus points already placed in LAS X, or none when unavailable.

        A microscope with no scan-field template (or an adapter without the
        procedure) is normal — the operator simply starts from an empty map.
        """
        procedures = self.session.get_procedures()
        if "get_focus_points" not in procedures:
            return []
        result = self.session.run_procedure({"name": "get_focus_points"})
        return [
            {"x": float(p["x"]), "y": float(p["y"])}
            for p in (result.get("positions") or [])
        ]

    def _on_click(self, event: Any) -> None:
        if event.inaxes is not self.ax:
            return
        # While the toolbar is zooming or panning, clicks belong to the
        # toolbar, not to point picking.
        toolbar = getattr(self.fig.canvas, "toolbar", None)
        if toolbar is not None and getattr(toolbar, "mode", ""):
            return
        if event.xdata is None or event.ydata is None:
            return
        if event.button == 1:
            self.add_point(event.xdata, event.ydata)
        elif event.button == 3:
            index = self._nearest_point_index(event)
            if index is not None:
                self.remove_point(index)

    def _nearest_point_index(self, event: Any) -> int | None:
        """The picked point within the click's remove radius, or ``None``."""
        best, best_d2 = None, _REMOVE_RADIUS_PX**2
        for i, p in enumerate(self.points):
            px, py = self.ax.transData.transform((p["x"], p["y"]))
            d2 = (px - event.x) ** 2 + (py - event.y) ** 2
            if d2 <= best_d2:
                best, best_d2 = i, d2
        return best

    # --- measuring -------------------------------------------------------

    def measure(self, *, fresh: bool = False) -> Any:
        """Autofocus at every picked point, fit the surface, draw the heatmap.

        Moves the stage to each point (through the session's gated moves),
        runs the autofocus job there, and fits the collected z values into a
        :class:`~._focus_surface.FocusSurface`. Returns the surface (also kept
        as ``self.focus``). Raises ``RuntimeError`` when no points are picked.

        Points measured earlier this session are normally reused (the title
        says how many). That cache never expires on its own — so after a long
        pause, a stage bump, or anything else that may have drifted the
        focus, pass ``fresh=True`` to forget it and re-drive the stage
        through every point.
        """
        if not self.points:
            raise RuntimeError(
                "no focus points are picked yet — left-click the map (or call "
                "add_point) to choose where the microscope should autofocus."
            )
        if fresh:
            self._af_cache.clear()
        if self._measured_points != self.points:
            self._invalidate_focus()

        # Only the points without a cached autofocus result visit the stage:
        # re-measuring after an edit runs the new or moved points and reuses
        # everything already measured this session.
        points = [dict(point) for point in self.points]
        fresh = [p for p in points if self._point_key(p) not in self._af_cache]
        reused = len(points) - len(fresh)

        def _collected_so_far() -> list[dict]:
            return [
                self._af_cache[self._point_key(p)]
                for p in points
                if self._point_key(p) in self._af_cache
            ]

        def _show_fresh_point(measurement: dict) -> None:
            # Live progress: refit and redraw the map after every measured
            # point, so the operator watches the surface take shape while
            # the stage is still visiting the remaining points.
            self._af_cache[(measurement["x_um"], measurement["y_um"])] = measurement
            self.measured = _collected_so_far()
            self.focus = fit_focus_surface(self.measured)
            self._draw_heatmap()
            self.ax.set_title(
                f"measuring... {len(self.measured)} of {len(points)} points "
                f"({self.focus.model} fit so far)"
            )
            force_draw(self.fig)

        try:
            if fresh:
                measure_focus(
                    self.session,
                    fresh,
                    af_job=self.af_job,
                    start_z=self.start_z,
                    on_point=_show_fresh_point,
                )
        except Exception:
            self._invalidate_focus()
            raise
        finally:
            self._last_measure_ended = time.monotonic()
        self.measured = _collected_so_far()
        self._measured_points = points
        self.focus = fit_focus_surface(self.measured)
        self._draw_heatmap()
        # Name the point that fits worst: one bad autofocus (dust, a
        # bubble) quietly bends the whole surface, and the residual is how
        # the operator spots it.
        from ._focus_surface import worst_residual_um

        worst = worst_residual_um(self.focus)
        residual_note = (
            "" if worst is None else f"; worst fit residual {worst[1]:+.1f} µm at point {worst[0]}"
        )
        self.ax.set_title(
            f"focus surface ({self.focus.model}, {len(points)} pts — "
            f"{len(fresh)} new, {reused} reused{residual_note})"
        )
        return self.focus

    @staticmethod
    def _point_key(point: dict) -> tuple[float, float]:
        # measure_focus echoes the input coordinates verbatim, so a cache
        # keyed on the exact floats matches its own measurement.
        return (float(point["x"]), float(point["y"]))

    def require_focus(self) -> Any:
        """The fitted focus surface; a clear error when measuring was skipped."""
        if self.focus is None or self._measured_points != self.points:
            raise RuntimeError(
                "the current focus points have not been measured — press "
                "'Measure focus' before continuing."
            )
        return self.focus

    def _invalidate_focus(self) -> None:
        """Drop a fitted surface as soon as its defining points change.

        Individual autofocus results stay cached (``_af_cache``) — the next
        Measure reuses them and only visits new or moved points; what must
        never survive an edit is the fitted surface and its display.
        """
        self.measured = None
        self.focus = None
        self._measured_points = None
        for label in getattr(self, "_z_labels", []):
            label.remove()
        self._z_labels = []
        if getattr(self, "_colorbar", None) is not None:
            self._colorbar.remove()
            self._colorbar = None
        if getattr(self, "_heatmap", None) is not None:
            self._heatmap.remove()
            self._heatmap = None
        if getattr(self, "_squares_artist", None) is not None:
            self._squares_artist.set_facecolor("none")

    def _on_measure_clicked(self, _event: Any) -> None:
        # A click that queued up while the stage was measuring is delivered
        # the moment it finishes — running it would move the stage through
        # every point again. Programmatic measure() is not debounced.
        if (
            self._last_measure_ended is not None
            and time.monotonic() - self._last_measure_ended < _QUEUED_CLICK_WINDOW_S
        ):
            self.ax.set_title("ignored a click queued during the previous measure")
            self.fig.canvas.draw_idle()
            return
        # A widget callback swallows tracebacks in most notebook frontends,
        # so surface any problem on the figure itself where the operator
        # is looking.
        try:
            self.measure()
        except Exception as exc:  # noqa: BLE001 -- shown to the operator, not lost
            self.ax.set_title(f"measure failed: {exc}", fontsize=9, wrap=True)
            self.fig.canvas.draw_idle()

    # --- drawing ---------------------------------------------------------

    def _redraw_points(self) -> None:
        if self._points_artist is not None:
            self._points_artist.remove()
            self._points_artist = None
        if self.points:
            self._points_artist = self.ax.scatter(
                [p["x"] for p in self.points],
                [p["y"] for p in self.points],
                marker="x",
                color="tab:green",
                s=70,
                label="focus points",
                zorder=3,
            )
        if self.focus is None:
            self.ax.set_title(
                f"left-click: add · right-click: remove · {len(self.points)} "
                f"focus point(s) — press 'Measure focus'"
            )
        self.fig.canvas.draw_idle()

    def _draw_heatmap(self) -> None:
        """Draw (or refresh) the fitted z(x, y) heatmap behind the points."""
        import numpy as np

        xs = [m["x_um"] for m in self.measured]
        ys = [m["y_um"] for m in self.measured]
        # Cover the measured points AND the overview positions, so the map
        # shows the focus z where the run will actually acquire.
        if self.positions:
            xs = xs + [p["x"] for p in self.positions]
            ys = ys + [p["y"] for p in self.positions]

        def _span(values: list[float]) -> tuple[float, float]:
            lo, hi = float(min(values)), float(max(values))
            if hi - lo < 1e-9:  # a single point has no area; pad it
                lo, hi = lo - 1.0, hi + 1.0
            return lo, hi

        x_lo, x_hi = _span(xs)
        y_lo, y_hi = _span(ys)
        gx = np.linspace(x_lo, x_hi, self.grid)
        gy = np.linspace(y_lo, y_hi, self.grid)
        mesh_x, mesh_y = np.meshgrid(gx, gy)
        mesh_z = np.asarray(self.focus.z_at(mesh_x, mesh_y), dtype=float).reshape(mesh_x.shape)

        if self._heatmap is None:
            self._heatmap = self.ax.imshow(
                mesh_z,
                origin="lower",
                extent=(x_lo, x_hi, y_lo, y_hi),
                aspect="auto",
                cmap="viridis",
                zorder=1,
            )
            self._colorbar = self.fig.colorbar(
                self._heatmap, ax=self.ax, label="focus z (um)"
            )
        else:
            self._heatmap.set_data(mesh_z)
            self._heatmap.set_extent((x_lo, x_hi, y_lo, y_hi))
            self._heatmap.set_clim(float(mesh_z.min()), float(mesh_z.max()))

        # Tint each overview tile marker with the fitted z at its centre, so
        # the tiles themselves wear the focus map's colours.
        if self._squares_artist is not None:
            from matplotlib import colormaps

            z_lo, z_hi = float(mesh_z.min()), float(mesh_z.max())
            span = z_hi - z_lo if z_hi > z_lo else 1.0
            tile_z = [
                float(self.focus.z_at(p["x"], p["y"])) for p in self.positions
            ]
            self._squares_artist.set_facecolor(
                [colormaps["viridis"]((z - z_lo) / span) for z in tile_z]
            )

        for label in self._z_labels:
            label.remove()
        self._z_labels = [
            self.ax.annotate(
                f"{m['z_um']:.1f}",
                (m["x_um"], m["y_um"]),
                textcoords="offset points",
                xytext=(6, 6),
                fontsize=8,
                zorder=4,
            )
            for m in self.measured
        ]
        self.ax.set_title(
            f"focus surface ({self.focus.model}, {len(self.measured)} pts)"
        )
        self.fig.canvas.draw_idle()


def pick_focus_points(
    session: Any,
    positions: list[dict] | None = None,
    *,
    af_job: str | None = None,
    start_z: float | None = None,
    seed: bool = True,
) -> FocusPicker:
    """Open the focus-picking figure; returns the :class:`FocusPicker`.

    ``session`` is the connected controller session; ``positions`` are the
    overview frame positions (drawn for context). ``af_job`` names the
    autofocus job when the instrument has more than one; ``start_z`` is the z
    to start each autofocus from (default: the current z). ``seed=False``
    skips pre-filling points already placed in LAS X.
    """
    return FocusPicker(
        session, positions, af_job=af_job, start_z=start_z, seed=seed
    )
