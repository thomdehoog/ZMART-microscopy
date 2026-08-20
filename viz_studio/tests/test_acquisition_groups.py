"""Reading a store's shape from what is inside it: axes and channels.

What organises the layer list is the **dataset** — one load, one acquisition —
and that is covered in `test_datasets.py`. It used to be worked out here instead,
by reading a driver's naming convention off the filenames, and those tests went
with the code that did it: a store called anything at all now belongs to whatever
dataset it was loaded as part of.

What remains here is the half that never depended on names. A store describes its
own axes and its own channels, and the important property is that nothing is
hardcoded: a channel with no description, or an axis order nobody expected, must
still appear rather than being silently dropped.
"""

from __future__ import annotations

import json

import pytest
from stores import axis_names, channels


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
        """A channel we cannot name is far better shown than quietly lost.

        Unnamed channels used to stay greyscale, on the principle that a
        colour nobody asked for is an invention. Channels of one picture are
        now ADDED to each other on screen, and several white channels add to
        white -- the specimen disappears into a flat glare and no amount of
        recolouring one of them helps, because they are all the same colour.
        So where there are several, each takes its own; where there is one,
        the old principle stands and it is left plain.
        """
        store = _write_store(
            tmp_path / "overview_pos001.ome.zarr",
            axes=["c", "z", "y", "x"],
            shape=[3, 8, 64, 64],
        )
        found = channels(store)
        assert [c["name"] for c in found] == ["channel 1", "channel 2", "channel 3"]
        colours = [tuple(c["color"]) for c in found]
        assert len(set(colours)) == 3, (
            f"channels that are added together must not open alike: {colours}"
        )

    def test_a_lone_unnamed_channel_is_left_plain(self, tmp_path):
        """With nothing to tell it apart from, a colour would be an invention."""
        store = _write_store(
            tmp_path / "lonely_pos001.ome.zarr",
            axes=["c", "z", "y", "x"],
            shape=[1, 8, 64, 64],
        )
        assert channels(store)[0]["color"] is None

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
