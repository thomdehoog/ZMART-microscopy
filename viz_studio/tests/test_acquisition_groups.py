"""Reading a run's shape from what is on disk: types, positions, channels.

A smart-microscopy run writes one OME-Zarr per acquisition, named by the driver
as ``{acquisition_type}_{position_label}``. The viewer has to work out from those
names and from each store's own description how to organise its layer list:
which acquisition types exist, and what channels are inside them.

The important property throughout is that nothing is hardcoded. An experiment may
invent an acquisition type nobody has heard of, or a channel with no description,
and both must still appear — grouped sensibly, and never silently dropped.
"""

from __future__ import annotations

import json

import pytest
from stores import axis_names, channels, group_by_type, split_name


class TestSplittingAName:
    """The driver joins the acquisition type and the position with an underscore."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("overview_pos001.ome.zarr", ("overview", "pos001")),
            ("targetscan_cell042.ome.zarr", ("targetscan", "cell042")),
            ("prescan_pos001.zarr", ("prescan", "pos001")),
            # A position label may itself contain underscores; only the first splits.
            ("targetscan_well_A1_cell_7.ome.zarr", ("targetscan", "well_A1_cell_7")),
        ],
    )
    def test_the_type_comes_before_the_first_underscore(self, name, expected):
        assert split_name(name) == expected

    def test_a_name_with_no_position_is_still_a_type(self):
        """Hand-made and older stores must not be hidden just for being plain."""
        assert split_name("demo.zarr") == ("demo", "")


class TestGrouping:
    """Positions of one acquisition type belong together, in a stable order."""

    def test_positions_gather_under_their_type(self):
        groups = group_by_type(
            [
                "overview_pos002.ome.zarr",
                "targetscan_cell042.ome.zarr",
                "overview_pos001.ome.zarr",
            ]
        )
        assert [kind for kind, _ in groups] == ["overview", "targetscan"]
        assert dict(groups)["overview"] == [
            "overview_pos001.ome.zarr",
            "overview_pos002.ome.zarr",
        ]

    def test_an_unfamiliar_acquisition_type_still_appears(self):
        """Nothing here lists the types we expect, so a new one needs no code change."""
        groups = dict(group_by_type(["photobleach_pos001.ome.zarr"]))
        assert "photobleach" in groups

    def test_the_order_does_not_wander_between_runs(self):
        names = ["b_pos2.zarr", "a_pos1.zarr", "b_pos1.zarr"]
        assert group_by_type(names) == group_by_type(list(reversed(names)))


def _write_store(path, *, axes, shape, omero_channels=None):
    """A minimal OME-Zarr: enough metadata to be read, no pixels needed."""
    path.mkdir(parents=True)
    attrs = {
        "multiscales": [
            {
                "version": "0.4",
                "axes": [{"name": a} for a in axes],
                "datasets": [{"path": "0"}],
            }
        ]
    }
    if omero_channels is not None:
        attrs["omero"] = {"channels": omero_channels}
    (path / ".zattrs").write_text(json.dumps(attrs), encoding="utf-8")
    (path / "0").mkdir()
    (path / "0" / ".zarray").write_text(json.dumps({"shape": shape}), encoding="utf-8")
    return path


class TestReadingChannels:
    """Channel identity comes from the file, because the filename can no longer say."""

    def test_names_and_colours_come_from_the_omero_block(self, tmp_path):
        store = _write_store(
            tmp_path / "overview_pos001.ome.zarr",
            axes=["t", "c", "z", "y", "x"],
            shape=[3, 2, 8, 64, 64],
            omero_channels=[
                {"label": "structure", "color": "FFFFFF"},
                {"label": "marker-a", "color": "00FF66"},
            ],
        )
        found = channels(store)
        assert [c["name"] for c in found] == ["structure", "marker-a"]
        assert found[0]["color"] == pytest.approx((1.0, 1.0, 1.0))
        assert found[1]["color"] == pytest.approx((0.0, 1.0, 0.4), abs=0.01)

    def test_the_array_decides_how_many_channels_there_are(self, tmp_path):
        """A description promising more channels than exist must not invent a layer."""
        store = _write_store(
            tmp_path / "overview_pos001.ome.zarr",
            axes=["c", "z", "y", "x"],
            shape=[2, 8, 64, 64],
            omero_channels=[{"label": "a"}, {"label": "b"}, {"label": "c"}],
        )
        assert len(channels(store)) == 2

    def test_channels_with_no_description_are_numbered_not_dropped(self, tmp_path):
        """A channel we cannot name is far better shown than quietly lost."""
        store = _write_store(
            tmp_path / "overview_pos001.ome.zarr",
            axes=["c", "z", "y", "x"],
            shape=[3, 8, 64, 64],
        )
        found = channels(store)
        assert [c["name"] for c in found] == ["channel 1", "channel 2", "channel 3"]
        assert all(c["color"] is None for c in found), "unnamed channels stay greyscale"

    def test_a_store_with_no_channel_axis_is_one_layer(self, tmp_path):
        store = _write_store(
            tmp_path / "overview_pos001.ome.zarr", axes=["z", "y", "x"], shape=[8, 64, 64]
        )
        assert len(channels(store)) == 1

    def test_a_malformed_colour_leaves_the_channel_greyscale(self, tmp_path):
        """Better plain than crashing on a colour we cannot read."""
        store = _write_store(
            tmp_path / "overview_pos001.ome.zarr",
            axes=["c", "z", "y", "x"],
            shape=[1, 8, 64, 64],
            omero_channels=[{"label": "odd", "color": "not-a-colour"}],
        )
        assert channels(store)[0]["color"] is None

    def test_an_unreadable_store_does_not_raise(self, tmp_path):
        """A half-written store during a live run must not take the viewer down."""
        broken = tmp_path / "overview_pos001.ome.zarr"
        broken.mkdir()
        (broken / ".zattrs").write_text("{ not json", encoding="utf-8")
        assert axis_names(broken) == []
        assert len(channels(broken)) == 1  # falls back to one plain layer


class TestReadingAxes:
    """A slider is offered only for an axis the store really has."""

    def test_the_declared_axes_come_back_in_order(self, tmp_path):
        store = _write_store(
            tmp_path / "a_b.ome.zarr", axes=["t", "c", "z", "y", "x"], shape=[2, 2, 4, 8, 8]
        )
        assert axis_names(store) == ["t", "c", "z", "y", "x"]

    def test_a_store_without_time_says_so(self, tmp_path):
        store = _write_store(
            tmp_path / "a_b.ome.zarr", axes=["c", "z", "y", "x"], shape=[2, 4, 8, 8]
        )
        assert "t" not in axis_names(store)
