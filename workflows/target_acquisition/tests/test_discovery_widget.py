"""The target explorer: feature axes, slider + lasso gating, hover crops.

Offline: synthetic targets and overview tiles, Agg backend, interaction
driven through the same handlers real mouse events call.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
import tifffile  # noqa: E402
from workflow._discovery_widget import explore_targets  # noqa: E402


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


def _target(x, y, *, area, intensity, tile=0, centroid=(50.0, 50.0)):
    return {
        "x": x,
        "y": y,
        "source": {
            "naming_p": tile,
            "centroid_col_row_px": centroid,
            "area_px": area,
            "mean_intensity": intensity,
        },
    }


@pytest.fixture
def targets():
    return [
        _target(0.0, 0.0, area=10, intensity=1.0),
        _target(10.0, 0.0, area=20, intensity=2.0),
        _target(0.0, 10.0, area=30, intensity=3.0),
        _target(10.0, 10.0, area=40, intensity=4.0),
    ]


@pytest.fixture
def overview(tmp_path):
    path = tmp_path / "overview.tif"
    tifffile.imwrite(path, np.arange(100 * 100, dtype=np.uint16).reshape(100, 100))
    return {
        "image_path": path,
        "center_frame_um": (0.0, 0.0),
        "pixel_size_um": 1.0,
        "image_size_px": (100, 100),
        "label": 0,
    }


class _Motion:
    """Just the fields the hover handler reads off a matplotlib event."""

    def __init__(self, ax, xdata, ydata):
        self.inaxes = ax
        self.xdata = xdata
        self.ydata = ydata
        self.x, self.y = ax.transData.transform((xdata, ydata))


def test_features_are_discovered_from_the_targets(targets):
    explorer = explore_targets(targets)
    assert explorer.features == ["x", "y", "area_px", "mean_intensity"]


def test_incomplete_or_nonfinite_features_are_not_offered(targets):
    targets[0]["source"]["optional"] = 1.0
    targets[1]["source"]["nonfinite"] = float("nan")
    for target in targets[1:]:
        target["source"].setdefault("optional", None)
    for target in targets:
        target["source"].setdefault("nonfinite", 1.0)
    explorer = explore_targets(targets)
    assert "optional" not in explorer.features
    assert "nonfinite" not in explorer.features


def test_axes_can_be_switched(targets):
    explorer = explore_targets(targets)
    explorer.set_axes("area_px", "mean_intensity")
    assert explorer.ax.get_xlabel() == "area_px"
    assert explorer.ax.get_ylabel() == "mean_intensity"
    # sliders now span the new features, so the full population stays gated
    assert len(explorer.gated) == len(targets)


def test_slider_thresholds_gate(targets):
    explorer = explore_targets(targets)
    explorer.set_axes("area_px", "mean_intensity")
    explorer.set_ranges(x_range=(15, 45))  # drops area 10
    assert [t["source"]["area_px"] for t in explorer.gated] == [20, 30, 40]
    explorer.set_ranges(y_range=(2.5, 5.0))  # additionally drops intensity 2
    assert [t["source"]["area_px"] for t in explorer.gated] == [30, 40]


def test_lasso_gates_and_clears(targets):
    explorer = explore_targets(targets)  # axes = x, y
    # A rectangle around the two left-hand points (x = 0).
    explorer._on_lasso([(-1, -1), (1, -1), (1, 11), (-1, 11)])
    assert {(t["x"], t["y"]) for t in explorer.gated} == {(0.0, 0.0), (0.0, 10.0)}
    explorer._on_clear_lasso(None)
    assert len(explorer.gated) == len(targets)


def test_lasso_is_the_and_of_sliders_and_region(targets):
    explorer = explore_targets(targets)
    explorer._on_lasso([(-1, -1), (11, -1), (11, 1), (-1, 1)])  # the two y=0 points
    explorer.set_ranges(x_range=(5.0, 15.0))  # AND x >= 5
    assert [(t["x"], t["y"]) for t in explorer.gated] == [(10.0, 0.0)]


def test_switching_axes_clears_the_lasso(targets):
    explorer = explore_targets(targets)
    old_selector = explorer._lasso
    explorer._on_lasso([(-1, -1), (1, -1), (1, 11), (-1, 11)])
    assert len(explorer.gated) == 2
    explorer.set_axes("area_px", "mean_intensity")
    assert len(explorer.gated) == len(targets)
    assert explorer._lasso is not old_selector


def test_hover_shows_the_cell_crop(targets, overview):
    explorer = explore_targets(targets, [overview], crop_um=20.0)
    explorer._on_hover(_Motion(explorer.ax, 0.0, 0.0))  # over the first target
    images = explorer._crop_ax.get_images()
    assert len(images) == 1
    # 20 um at 1 um/px -> a 20x20 crop around the centroid.
    assert np.asarray(images[0].get_array()).shape == (20, 20)
    assert "target 0" in explorer._crop_ax.get_title()


def test_hover_far_from_any_point_changes_nothing(targets, overview):
    explorer = explore_targets(targets, [overview])
    explorer._on_hover(_Motion(explorer.ax, 500.0, 500.0))
    assert not explorer._crop_ax.get_images()


def test_no_targets_is_a_clear_error():
    with pytest.raises(ValueError, match="no targets"):
        explore_targets([])


def test_duplicate_valued_targets_are_each_marked_acquired():
    first = _target(1.0, 2.0, area=10, intensity=3.0)
    second = {**first, "source": dict(first["source"])}
    explorer = explore_targets([first, second])
    explorer.toggle_pick(0)
    explorer.toggle_pick(1)

    explorer.note_acquired([first, second])

    assert explorer._acquired == {0, 1}
    assert explorer._picked == set()


def test_copied_duplicates_resolve_across_calls_without_breaking_identity_idempotence():
    first = _target(1.0, 2.0, area=10, intensity=3.0)
    second = {**first, "source": dict(first["source"])}
    explorer = explore_targets([first, second])
    copied_first = {**first, "source": dict(first["source"])}
    copied_second = {**second, "source": dict(second["source"])}

    explorer.note_acquired([copied_first])
    assert explorer._acquired == {0}
    explorer.note_acquired([first])  # repeating the original is idempotent
    assert explorer._acquired == {0}
    explorer.note_acquired([copied_second])
    assert explorer._acquired == {0, 1}
