"""The focus-picking figure: clicks edit points, Measure fits and draws the map.

All offline: matplotlib runs on the Agg (file-only) backend and clicks are
simulated by calling the handlers with stub events, so these tests exercise
exactly the code paths a real click travels — minus the mouse.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402
from workflow._focus_widget import FocusPicker, pick_focus_points  # noqa: E402


class _StubSession:
    """Controller-session stand-in: scripted focus z per (x, y), like test_focus_run."""

    def __init__(self, focus_by_xy=None, seed_points=None, current_z=0.0):
        self.focus_by_xy = focus_by_xy or {}
        self.seed_points = seed_points
        self.current_z = current_z
        self.moves = []
        self.procedures = []

    def get_xyz(self):
        return {"z": {"value": self.current_z}}

    def set_xyz(self, x, y, z, **_kw):
        self.moves.append((x, y, z))

    def run_procedure(self, procedure):
        self.procedures.append(procedure)
        if procedure["name"] == "get_focus_points":
            if self.seed_points is None:
                raise RuntimeError("no focus points found in the scan field")
            return {"positions": [dict(p) for p in self.seed_points]}
        x, y, _z = self.moves[-1]
        return {"ran": "autofocus", "frame_z_um": self.focus_by_xy[(x, y)]}


class _Event:
    """Just the fields the click handler reads off a matplotlib event."""

    def __init__(self, ax, button, xdata, ydata):
        self.inaxes = ax
        self.button = button
        self.xdata = xdata
        self.ydata = ydata
        # Screen-pixel position, used by right-click removal.
        self.x, self.y = ax.transData.transform((xdata, ydata))


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


def test_add_and_remove_points_by_click():
    picker = FocusPicker(_StubSession(), seed=False)
    picker._on_click(_Event(picker.ax, button=1, xdata=10.0, ydata=20.0))
    picker._on_click(_Event(picker.ax, button=1, xdata=30.0, ydata=40.0))
    assert picker.points == [{"x": 10.0, "y": 20.0}, {"x": 30.0, "y": 40.0}]

    # Right-click on (near) the first point removes exactly that one.
    picker._on_click(_Event(picker.ax, button=3, xdata=10.0, ydata=20.0))
    assert picker.points == [{"x": 30.0, "y": 40.0}]

    # A right-click far from every point removes nothing.
    picker._on_click(_Event(picker.ax, button=3, xdata=500.0, ydata=500.0))
    assert len(picker.points) == 1


def test_clicks_outside_the_axes_are_ignored():
    picker = FocusPicker(_StubSession(), seed=False)
    picker._on_click(_Event(picker.ax, button=1, xdata=1.0, ydata=1.0))
    other_fig, other_ax = plt.subplots()
    picker._on_click(_Event(other_ax, button=1, xdata=2.0, ydata=2.0))
    assert picker.points == [{"x": 1.0, "y": 1.0}]


def test_seeds_from_lasx_focus_points():
    session = _StubSession(seed_points=[{"x": 5.0, "y": 6.0}, {"x": 7.0, "y": 8.0}])
    picker = pick_focus_points(session)
    assert picker.points == [{"x": 5.0, "y": 6.0}, {"x": 7.0, "y": 8.0}]
    assert session.procedures == [{"name": "get_focus_points"}]


def test_seed_failure_starts_empty():
    """A scope with no scan-field template (or no such procedure) is normal."""
    picker = pick_focus_points(_StubSession(seed_points=None))
    assert picker.points == []


def test_measure_fits_surface_and_draws_heatmap():
    focus = {(0.0, 0.0): 3.0, (10.0, 0.0): 4.0, (0.0, 10.0): 5.0}
    session = _StubSession(focus)
    picker = FocusPicker(session, seed=False, start_z=0.0)
    for x, y in focus:
        picker.add_point(x, y)

    surface = picker.measure()

    assert picker.focus is surface
    assert surface.z_at(5, 5) == pytest.approx(4.5)
    assert picker.measured == [
        {"x_um": x, "y_um": y, "z_um": z} for (x, y), z in focus.items()
    ]
    # The heatmap and its colorbar were drawn into the SAME figure, with one
    # z annotation per measured point.
    assert picker._heatmap is not None
    assert picker._colorbar is not None
    assert len(picker._z_labels) == 3
    assert picker.require_focus() is surface

    # Re-measuring updates the map in place rather than stacking a second one.
    heatmap = picker._heatmap
    picker.measure()
    assert picker._heatmap is heatmap
    assert len(picker.fig.axes) == 3  # main axes + button + one colorbar


def test_measure_without_points_is_a_clear_error():
    picker = FocusPicker(_StubSession(), seed=False)
    with pytest.raises(RuntimeError, match="no focus points"):
        picker.measure()


def test_require_focus_before_measuring_is_a_clear_error():
    picker = FocusPicker(_StubSession(), seed=False)
    picker.add_point(0.0, 0.0)
    with pytest.raises(RuntimeError, match="not been measured"):
        picker.require_focus()


def test_button_click_failure_lands_on_the_figure_title():
    """The Measure button must never lose an error in a silent callback."""
    picker = FocusPicker(_StubSession(), seed=False)  # no points -> measure fails
    picker._on_measure_clicked(None)
    assert "measure failed" in picker.ax.get_title()
