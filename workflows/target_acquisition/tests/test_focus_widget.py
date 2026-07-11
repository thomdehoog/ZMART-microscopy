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

    def get_procedures(self):
        return {"autofocus": {}}

    def get_info(self):
        return {"focus_positions": [dict(p) for p in (self.seed_points or [])]}

    def set_xyz(self, x, y, z, **_kw):
        self.moves.append((x, y, z))

    def run_procedure(self, procedure):
        self.procedures.append(procedure)
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
    picker = pick_focus_points(session, focus_positions=session.seed_points)
    assert picker.points == [{"x": 5.0, "y": 6.0}, {"x": 7.0, "y": 8.0}]
    assert session.procedures == []


def test_seed_failure_starts_empty():
    """A scope with no configured focus positions is normal."""
    picker = pick_focus_points(_StubSession(seed_points=None), focus_positions=[])
    assert picker.points == []


def test_seed_operational_failure_is_not_hidden():
    with pytest.raises(KeyError):
        pick_focus_points(_StubSession(), focus_positions=[{"not_x": 1.0}])


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


def test_editing_points_invalidates_the_measured_surface():
    session = _StubSession({(0.0, 0.0): 3.0, (1.0, 1.0): 4.0})
    picker = FocusPicker(session, seed=False, start_z=0.0)
    picker.add_point(0.0, 0.0)
    picker.measure()
    picker.add_point(1.0, 1.0)
    with pytest.raises(RuntimeError, match="current focus points have not been measured"):
        picker.require_focus()
    assert picker._heatmap is None


def test_button_click_failure_lands_on_the_figure_title():
    """The Measure button must never lose an error in a silent callback."""
    picker = FocusPicker(_StubSession(), seed=False)  # no points -> measure fails
    picker._on_measure_clicked(None)
    assert "measure failed" in picker.ax.get_title()


def test_heatmap_grows_while_measuring():
    """The fitted map refreshes after every measured point, not only at the end."""
    heatmaps_during = []

    class _PeekingSession(_StubSession):
        def run_procedure(self, procedure):
            heatmaps_during.append(picker._heatmap is not None)
            return super().run_procedure(procedure)

    focus = {(0.0, 0.0): 3.0, (10.0, 0.0): 4.0, (0.0, 10.0): 5.0}
    picker = FocusPicker(_PeekingSession(focus), seed=False, start_z=0.0)
    for x, y in focus:
        picker.add_point(x, y)
    picker.measure()
    # No map before the first point; the 2nd and 3rd autofocus runs happen
    # with the map from the earlier points already on screen.
    assert heatmaps_during == [False, True, True]
    assert len(picker._z_labels) == 3


def test_remeasure_only_visits_new_points():
    """Editing points and re-measuring reuses the session's earlier results."""
    focus = {(0.0, 0.0): 3.0, (10.0, 0.0): 4.0, (5.0, 5.0): 3.5}
    session = _StubSession(focus)
    picker = FocusPicker(session, seed=False, start_z=0.0)
    picker.add_point(0.0, 0.0)
    picker.add_point(10.0, 0.0)
    picker.measure()
    assert len(session.procedures) == 2

    picker.add_point(5.0, 5.0)
    picker.measure()  # only the new point drives the stage
    assert len(session.procedures) == 3
    assert len(picker.require_focus().measured) == 3

    picker.remove_point(2)
    picker.measure()  # nothing new: a pure refit, no stage moves at all
    assert len(session.procedures) == 3
    assert len(picker.require_focus().measured) == 2
    assert "reused" in picker.ax.get_title()


def test_overview_tiles_wear_the_heatmap_colours():
    import numpy as np

    session = _StubSession({(0.0, 0.0): 1.0, (10.0, 0.0): 5.0, (0.0, 10.0): 3.0})
    picker = FocusPicker(
        session,
        [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}],
        seed=False,
        start_z=0.0,
    )
    # Hollow until measured.
    assert picker._squares_artist.get_facecolor().size == 0
    for xy in [(0.0, 0.0), (10.0, 0.0), (0.0, 10.0)]:
        picker.add_point(*xy)
    picker.measure()
    colors = picker._squares_artist.get_facecolor()
    assert colors.shape[0] == 2
    # The two tiles sit at different fitted z, so they wear different colours.
    assert not np.allclose(colors[0], colors[1])
    # Editing a point drops the tint together with the surface.
    picker.add_point(3.0, 3.0)
    assert picker._squares_artist.get_facecolor().size == 0
