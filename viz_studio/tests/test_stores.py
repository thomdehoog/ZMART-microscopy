"""Finding the stores under a path, and colouring the channels they name.

An acquisition folder and a single store must both be openable, because the
operator points at whichever they have — the whole tiled experiment, or one
tile they want to look at closely.
"""

from __future__ import annotations

import json

import pytest
from stores import (
    channel_color,
    channel_of,
    discover,
    is_store,
    layer_names,
    prefer_filter,
    select_tiles,
)


def make_store(path):
    path.mkdir(parents=True)
    (path / ".zattrs").write_text(
        json.dumps({"multiscales": [{"version": "0.4", "datasets": [{"path": "0"}]}]}),
        encoding="utf-8",
    )
    return path


def test_a_store_is_recognised_by_its_multiscales(tmp_path):
    assert is_store(make_store(tmp_path / "one.ome.zarr"))


def test_a_plain_folder_is_not_a_store(tmp_path):
    (tmp_path / "plain").mkdir()
    assert not is_store(tmp_path / "plain")
    assert not is_store(tmp_path / "does-not-exist")


def test_a_group_without_multiscales_is_not_itself_a_store(tmp_path):
    """The tiled acquisition's parent has an empty .zattrs — it is a container."""
    group = tmp_path / "multitile.ome.zarr"
    group.mkdir()
    (group / ".zattrs").write_text("{}", encoding="utf-8")
    assert not is_store(group)


def test_pointing_at_one_store_opens_just_it(tmp_path):
    store = make_store(tmp_path / "single.ome.zarr")
    parent, names = discover(store)
    assert parent == tmp_path.resolve()
    assert names == ["single.ome.zarr"]


def test_pointing_at_a_group_opens_every_store_in_it(tmp_path):
    group = tmp_path / "multitile.ome.zarr"
    group.mkdir()
    (group / ".zattrs").write_text("{}", encoding="utf-8")
    for name in ("Tile1_Ch647.ome.zarr", "Tile0_Ch488.ome.zarr", "Tile0_Ch647.ome.zarr"):
        make_store(group / name)
    (group / "not-a-store").mkdir()

    parent, names = discover(group)
    assert parent == group.resolve()
    assert names == ["Tile0_Ch488.ome.zarr", "Tile0_Ch647.ome.zarr", "Tile1_Ch647.ome.zarr"]


def test_layer_order_is_stable_between_runs(tmp_path):
    group = tmp_path / "g"
    group.mkdir()
    for name in ("b.ome.zarr", "a.ome.zarr", "c.ome.zarr"):
        make_store(group / name)
    assert discover(group)[1] == discover(group)[1] == sorted(discover(group)[1])


_REAL_NAMES = [
    "Mag5_Tile0_Ch488_Flt405-488-561-640-Quadrupleblock_Sh1_Rot15.99995.ome.zarr",
    "Mag5_Tile0_Ch488_FltEmpty_Sh1_Rot15.99995.ome.zarr",
    "Mag5_Tile0_Ch647_Flt405-488-561-640-Quadrupleblock_Sh1_Rot15.99995.ome.zarr",
    "Mag5_Tile1_Ch488_Flt405-488-561-640-Quadrupleblock_Sh1_Rot15.99995.ome.zarr",
    "Mag5_Tile1_Ch488_FltEmpty_Sh1_Rot15.99995.ome.zarr",
    "Mag5_Tile1_Ch647_Flt405-488-561-640-Quadrupleblock_Sh1_Rot15.99995.ome.zarr",
    "Mag5_Tile2_Ch488_Flt405-488-561-640-Quadrupleblock_Sh1_Rot15.99995.ome.zarr",
]


def test_labels_stay_unique_when_only_the_filter_differs():
    """Tile0_Ch488 exists twice here — through two filters. Both must be nameable."""
    labels = layer_names(_REAL_NAMES)
    assert len(set(labels)) == len(labels)
    assert "Tile0_Ch647" in labels
    assert sum(label.startswith("Tile0_Ch488") for label in labels) == 2


def test_labels_stay_short_when_tile_and_channel_are_enough():
    assert layer_names(["Mag5_Tile0_Ch488_FltEmpty_Sh1.ome.zarr"]) == ["Tile0_Ch488"]


def test_selecting_tiles_keeps_only_those_asked_for():
    kept = select_tiles(_REAL_NAMES, [0, 1])
    assert len(kept) == 6
    assert not any("Tile2" in name for name in kept)


def test_selecting_no_tiles_at_all_keeps_everything():
    assert select_tiles(_REAL_NAMES, None) == _REAL_NAMES


def test_selecting_a_tile_that_is_not_there_yields_nothing():
    assert select_tiles(_REAL_NAMES, [7]) == []


def test_preferring_a_filter_leaves_one_store_per_tile_and_channel():
    """Two tiles, two channels — four layers, not six."""
    kept = prefer_filter(select_tiles(_REAL_NAMES, [0, 1]), "Empty")
    assert len(kept) == 4
    assert [(_tile(n), channel_of(n)) for n in kept] == [
        ("Tile0", "488"),
        ("Tile0", "647"),
        ("Tile1", "488"),
        ("Tile1", "647"),
    ]


def test_the_asked_for_filter_wins_where_it_exists():
    kept = prefer_filter(select_tiles(_REAL_NAMES, [0]), "Empty")
    ch488 = next(n for n in kept if channel_of(n) == "488")
    assert "FltEmpty" in ch488


def test_a_channel_with_only_one_filter_survives_the_choice():
    """647 was never acquired through the empty filter; it must not vanish."""
    kept = prefer_filter(select_tiles(_REAL_NAMES, [0]), "Empty")
    ch647 = next(n for n in kept if channel_of(n) == "647")
    assert "Quadrupleblock" in ch647


def test_asking_for_no_filter_keeps_every_acquisition():
    assert prefer_filter(_REAL_NAMES, None) == _REAL_NAMES


def test_deduplicated_layers_get_short_labels_again():
    """With one store per tile+channel there is nothing left to disambiguate."""
    kept = prefer_filter(select_tiles(_REAL_NAMES, [0, 1]), "Empty")
    assert layer_names(kept) == ["Tile0_Ch488", "Tile0_Ch647", "Tile1_Ch488", "Tile1_Ch647"]


def _tile(name: str) -> str:
    return next(p for p in name.split("_") if p.startswith("Tile"))


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Mag5_Tile0_Ch488_FltEmpty_Sh1_Rot15.ome.zarr", "488"),
        ("Mag2x_Tile1_Ch647_Flt405-488-561-640-Quadrupleblock_Sh0_Rot0.ome.zarr", "647"),
        ("demo.zarr", None),
    ],
)
def test_channel_is_read_from_the_store_name(name, expected):
    assert channel_of(name) == expected


def test_green_and_magenta_for_the_two_channels_in_this_experiment():
    assert channel_color("Tile0_Ch488_x.ome.zarr") == (0.0, 1.0, 0.4)
    assert channel_color("Tile0_Ch647_x.ome.zarr") == (1.0, 0.2, 1.0)


def test_an_unknown_channel_is_left_uncoloured(tmp_path):
    """Better plain than a colour that claims a wavelength it does not know."""
    assert channel_color("Tile0_Ch999_x.ome.zarr") is None
    assert channel_color("demo.zarr") is None
