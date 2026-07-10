"""The overview mosaic viewer: tile placement, channel overlay, controls.

Offline: synthetic TIFF tiles, Agg backend, controls driven through the
same code paths the on-figure widgets call.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
import tifffile  # noqa: E402
from workflow._overview_widget import OverviewViewer, _load_channels, view_overview  # noqa: E402


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


def _tile(tmp_path, name, *, channels=2, size=(20, 30), value=100):
    """A (C, H, W) uint16 tile whose channel c is a constant c*value."""
    h, w = size
    data = np.stack(
        [np.full((h, w), (c + 1) * value, dtype=np.uint16) for c in range(channels)]
    )
    path = tmp_path / name
    tifffile.imwrite(path, data)
    return path


def _overviews(tmp_path, centers, **tile_kw):
    entries = []
    for i, center in enumerate(centers):
        path = _tile(tmp_path, f"tile_{i}.tif", **tile_kw)
        size = tile_kw.get("size", (20, 30))
        entries.append(
            {
                "image_path": path,
                "center_frame_um": center,
                "pixel_size_um": 2.0,
                "image_size_px": size,
                "label": i,
            }
        )
    return entries


def test_load_channels_accepts_2d_and_both_3d_layouts(tmp_path):
    flat = tmp_path / "flat.tif"
    tifffile.imwrite(flat, np.zeros((10, 12), dtype=np.uint16))
    assert _load_channels(flat).shape == (1, 10, 12)

    first = tmp_path / "first.tif"
    tifffile.imwrite(first, np.zeros((3, 10, 12), dtype=np.uint16))
    assert _load_channels(first).shape == (3, 10, 12)

    last = tmp_path / "last.tif"
    tifffile.imwrite(last, np.zeros((10, 12, 3), dtype=np.uint16))
    assert _load_channels(last).shape == (3, 10, 12)


def test_tiles_sit_at_their_frame_positions(tmp_path):
    # 30 px wide * 2 um = 60 um wide; 20 px tall * 2 um = 40 um tall.
    viewer = view_overview(_overviews(tmp_path, [(0.0, 0.0), (100.0, 0.0)]))
    assert viewer.n_channels == 2
    first, second = (tuple(im.get_extent()) for im in viewer._images)
    assert first == (-30.0, 30.0, 20.0, -20.0)
    assert second == (70.0, 130.0, 20.0, -20.0)


def test_separate_plane_files_are_loaded_as_channels(tmp_path):
    first = tmp_path / "c0.tif"
    second = tmp_path / "c1.tif"
    tifffile.imwrite(first, np.ones((10, 12), dtype=np.uint16))
    tifffile.imwrite(second, np.full((10, 12), 2, dtype=np.uint16))
    overview = {
        "image_path": first,
        "channel_paths": [first, second],
        "center_frame_um": (0.0, 0.0),
        "pixel_size_um": 1.0,
        "image_size_px": (10, 12),
    }
    viewer = view_overview([overview])
    assert viewer.n_channels == 2


def test_hiding_a_channel_removes_its_contribution(tmp_path):
    viewer = view_overview(_overviews(tmp_path, [(0.0, 0.0)]))
    both = np.asarray(viewer._images[0].get_array()).copy()
    viewer.set_channel(1, visible=False)
    only_first = np.asarray(viewer._images[0].get_array())
    assert both.sum() > only_first.sum()
    viewer.set_channel(1, visible=True)
    assert np.allclose(np.asarray(viewer._images[0].get_array()), both)


def test_channel_color_lands_in_the_right_rgb_slot(tmp_path):
    viewer = view_overview(_overviews(tmp_path, [(0.0, 0.0)], channels=1))
    viewer.set_channel(0, color="red", vmin=0.0, vmax=50.0)  # pixels (100) saturate
    rgb = np.asarray(viewer._images[0].get_array())
    assert rgb[0, 0, 0] == pytest.approx(1.0)  # red channel full
    assert rgb[0, 0, 1] == pytest.approx(0.0)
    assert rgb[0, 0, 2] == pytest.approx(0.0)


def test_display_range_sets_brightness(tmp_path):
    viewer = view_overview(_overviews(tmp_path, [(0.0, 0.0)], channels=1))
    viewer.set_channel(0, vmin=0.0, vmax=200.0)  # pixel value 100 -> half bright
    half = np.asarray(viewer._images[0].get_array())[0, 0].max()
    viewer.set_channel(0, vmin=0.0, vmax=100.0)  # now fully bright
    full = np.asarray(viewer._images[0].get_array())[0, 0].max()
    assert half == pytest.approx(0.5, abs=0.01)
    assert full == pytest.approx(1.0)


def test_color_button_cycles_the_active_channel(tmp_path):
    viewer = view_overview(_overviews(tmp_path, [(0.0, 0.0)]))
    before = viewer.channels[0]["color"]
    viewer._on_color_cycled(None)
    assert viewer.channels[0]["color"] != before


def test_downsample_keeps_extent_but_shrinks_pixels(tmp_path):
    viewer = view_overview(_overviews(tmp_path, [(0.0, 0.0)]), downsample=2)
    rgb = np.asarray(viewer._images[0].get_array())
    assert rgb.shape[:2] == (10, 15)  # every 2nd pixel of (20, 30)
    assert tuple(viewer._images[0].get_extent()) == (-30.0, 30.0, 20.0, -20.0)


def test_default_downsample_obeys_display_budget(tmp_path, monkeypatch):
    monkeypatch.setattr("workflow._overview_widget._DISPLAY_PIXEL_BUDGET", 100)
    viewer = view_overview(_overviews(tmp_path, [(0.0, 0.0)]))
    assert viewer.downsample > 1


def test_mismatched_channel_counts_are_refused(tmp_path):
    entries = _overviews(tmp_path, [(0.0, 0.0)], channels=2)
    (tmp_path / "b").mkdir()
    entries += _overviews(tmp_path / "b", [(50.0, 0.0)], channels=3)
    with pytest.raises(ValueError, match="channel count"):
        OverviewViewer(entries)


def _ome_tile(tmp_path, name, *, value=200, size=(20, 30), ps=2.0):
    """A single-channel OME tile add_acquisition can read geometry from."""
    h, w = size
    desc = (
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        f'<Image><Pixels DimensionOrder="XYCZT" Type="uint16" SizeX="{w}" SizeY="{h}" '
        f'SizeC="1" SizeZ="1" SizeT="1" PhysicalSizeX="{ps}" PhysicalSizeY="{ps}"/>'
        "</Image></OME>"
    )
    path = tmp_path / name
    tifffile.imwrite(path, np.full((h, w), value, dtype=np.uint16), description=desc)
    return path


def test_empty_viewer_streams_tiles_live(tmp_path):
    """An empty map grows tile-by-tile via the run_overview callback shape."""
    viewer = view_overview([])
    assert viewer.overviews == []
    assert "waiting" in viewer.ax.get_title()

    for index, (x, y) in enumerate([(0.0, 0.0), (100.0, 0.0)], start=1):
        record = {"images": [str(_ome_tile(tmp_path, f"live_{index}.ome.tif"))]}
        viewer.add_acquisition(index, {"x": x, "y": y, "z": 0.0}, record)

    assert len(viewer._images) == 2
    assert viewer.n_channels == 1
    assert tuple(viewer._images[0].get_extent()) == (-30.0, 30.0, 20.0, -20.0)
    assert tuple(viewer._images[1].get_extent()) == (70.0, 130.0, 20.0, -20.0)
    assert "2 overview tile(s)" in viewer.ax.get_title()


def test_reload_picks_up_rewritten_pixels(tmp_path):
    """After the simulation hijack rewrites files, reload() refreshes the map."""
    path = _ome_tile(tmp_path, "tile.ome.tif", value=100)
    viewer = view_overview([])
    viewer.add_acquisition(1, {"x": 0.0, "y": 0.0}, {"images": [str(path)]})
    viewer.set_channel(0, vmin=0.0, vmax=400.0)
    before = np.asarray(viewer._images[0].get_array()).max()

    tifffile.imwrite(path, np.full((20, 30), 400, dtype=np.uint16))
    viewer.reload()
    after = np.asarray(viewer._images[0].get_array()).max()
    assert after > before


def test_channel_settings_survive_streamed_additions(tmp_path):
    """A growing map must not re-brighten under the operator's eyes."""
    viewer = view_overview([])
    viewer.add_acquisition(
        1, {"x": 0.0, "y": 0.0}, {"images": [str(_ome_tile(tmp_path, "a.ome.tif"))]}
    )
    viewer.set_channel(0, color="red", vmin=1.0, vmax=2.0)
    state_before = dict(viewer.channels[0])
    viewer.add_acquisition(
        2, {"x": 100.0, "y": 0.0}, {"images": [str(_ome_tile(tmp_path, "b.ome.tif"))]}
    )
    assert viewer.channels[0] == state_before


def test_adjusting_channels_before_any_tile_is_a_clear_error():
    viewer = view_overview([])
    with pytest.raises(RuntimeError, match="no tiles loaded yet"):
        viewer.set_channel(0, visible=False)
