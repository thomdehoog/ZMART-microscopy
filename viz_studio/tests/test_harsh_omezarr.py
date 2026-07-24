"""Harsh tests for reading real OME-Zarr: channel discovery, contrast, serving.

These build genuine (small) OME-Zarr v2 stores on disk with zarr, in the two
shapes a microscope actually produces — a single store, and a folder of
sibling stores, one per tile and channel — and then push the code that opens
them with awkward, adversarial, and malformed input. The point is to prove the
answer to "the channels shown are the channels in the store" holds up, and that
nothing here crashes, leaks a file, or invents a channel that is not on disk.

They need only numpy and zarr (already required to run the tool); they do not
need the network share, a browser, or the built frontend, so they run anywhere.
"""

from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

import numpy as np
import pytest

from contrast import display_window
from server import make_server
from stores import (
    channel_color,
    channel_of,
    discover,
    is_store,
    layer_names,
    prefer_filter,
    select_tiles,
)


# --------------------------------------------------------------------------
# Helpers: write real OME-Zarr v2 stores, the way the acquisition does.
# --------------------------------------------------------------------------

def write_store(path: Path, data: np.ndarray, *, omero: tuple[float, float] | None = None) -> Path:
    """Write ``data`` (a z, y, x volume) as a one-level OME-Zarr v2 store."""
    import zarr

    path = Path(path)
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    arr = group.create_array("0", shape=data.shape, chunks=data.shape, dtype=data.dtype)
    arr[:] = data
    attrs: dict = {
        "multiscales": [{
            "version": "0.4",
            "axes": [{"name": "z", "type": "space"}, {"name": "y", "type": "space"}, {"name": "x", "type": "space"}],
            "datasets": [{"path": "0", "coordinateTransformations": [{"type": "scale", "scale": [2.0, 1.0, 1.0]}]}],
        }]
    }
    if omero is not None:
        attrs["omero"] = {"channels": [{"window": {"start": omero[0], "end": omero[1], "min": 0, "max": 65535}}]}
    (path / ".zattrs").write_text(json.dumps(attrs), encoding="utf-8")
    return path


def a_volume(seed: int = 0, *, hi: int = 4000) -> np.ndarray:
    """A small, narrow-band 16-bit volume (like a real, mostly-dark acquisition)."""
    rng = np.random.default_rng(seed)
    v = rng.integers(80, hi, size=(6, 16, 16), dtype=np.uint16)
    return v


def channel_folder(root: Path, names: list[str], **kw) -> Path:
    """Write a folder of per-channel stores, one store per name."""
    root.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(names):
        write_store(root / name, a_volume(i), **kw)
    return root


# --------------------------------------------------------------------------
# 1. The channels shown are the channels on disk
# --------------------------------------------------------------------------

def test_folder_of_channel_stores_is_discovered_as_one_layer_each(tmp_path):
    names = ["Tile0_Ch488.ome.zarr", "Tile0_Ch561.ome.zarr", "Tile0_Ch647.ome.zarr"]
    folder = channel_folder(tmp_path / "acq", names)
    parent, found = discover(folder)
    assert parent == folder.resolve()
    assert found == sorted(names)                       # every store, and only those, sorted
    assert channel_of(found[0]) == "488"
    assert layer_names(found) == ["Tile0_Ch488", "Tile0_Ch561", "Tile0_Ch647"]


def test_single_store_path_yields_exactly_that_store(tmp_path):
    store = write_store(tmp_path / "one_Ch488.ome.zarr", a_volume())
    parent, found = discover(store)
    assert parent == store.parent.resolve()
    assert found == [store.name]


def test_known_wavelengths_are_coloured_and_unknown_ones_stay_grey(tmp_path):
    # 405/488/561/647 have conventional colours; 594 and 730 do not and must not
    # be given an invented one.
    for wl in ("405", "488", "561", "647"):
        assert channel_color(f"Tile0_Ch{wl}.ome.zarr") is not None
    for wl in ("594", "730"):
        assert channel_color(f"Tile0_Ch{wl}.ome.zarr") is None


def test_more_channels_than_the_colour_palette_still_all_appear(tmp_path):
    names = [f"Tile0_Ch{wl}.ome.zarr" for wl in ("405", "488", "561", "594", "647", "730")]
    folder = channel_folder(tmp_path / "acq", names)
    _, found = discover(folder)
    assert len(found) == 6                               # all six channels are layers
    assert len(layer_names(found)) == len(set(layer_names(found)))  # labels stay unique


def test_two_filters_of_one_channel_collapse_to_a_single_layer(tmp_path):
    # The same tile and channel through two filters are alternatives, not two
    # channels — overlaying both would double the apparent signal.
    names = [
        "Tile0_Ch488_Flt488.ome.zarr",
        "Tile0_Ch488_Flt405-488.ome.zarr",
        "Tile0_Ch647_Flt647.ome.zarr",
    ]
    kept = prefer_filter(names, wanted="Flt488")
    assert len(kept) == 2                               # one 488, one 647
    assert any("Flt488.ome" in n and "405" not in n for n in kept)
    assert "Tile0_Ch647_Flt647.ome.zarr" in kept


def test_selecting_tiles_keeps_only_those_tiles(tmp_path):
    names = ["Tile0_Ch488.ome.zarr", "Tile1_Ch488.ome.zarr", "Tile2_Ch488.ome.zarr"]
    assert select_tiles(names, [0, 2]) == ["Tile0_Ch488.ome.zarr", "Tile2_Ch488.ome.zarr"]
    assert select_tiles(names, None) == names           # None means "all"


def test_labels_disambiguate_when_short_names_would_clash(tmp_path):
    # Same tile and channel, two filters: shortening blindly gives two identical
    # labels, so the filter block must be restored to tell them apart.
    names = ["Tile0_Ch488_Flt488.ome.zarr", "Tile0_Ch488_Flt561.ome.zarr"]
    labels = layer_names(names)
    assert len(set(labels)) == 2


# --------------------------------------------------------------------------
# 2. Discovery is robust to junk in the folder
# --------------------------------------------------------------------------

def test_malformed_zattrs_is_not_mistaken_for_a_store(tmp_path):
    bad = tmp_path / "broken.ome.zarr"
    bad.mkdir()
    (bad / ".zattrs").write_text("{ this is not json", encoding="utf-8")
    assert is_store(bad) is False


def test_zattrs_without_multiscales_is_not_a_store(tmp_path):
    plain = tmp_path / "notimage.zarr"
    plain.mkdir()
    (plain / ".zattrs").write_text(json.dumps({"something": 1}), encoding="utf-8")
    assert is_store(plain) is False
    empty = tmp_path / "empty.zarr"
    empty.mkdir()
    (empty / ".zattrs").write_text(json.dumps({"multiscales": []}), encoding="utf-8")
    assert is_store(empty) is False                     # an empty pyramid is not an image


def test_folder_ignores_files_and_non_stores(tmp_path):
    folder = tmp_path / "acq"
    channel_folder(folder, ["Tile0_Ch488.ome.zarr"])
    (folder / "notes.txt").write_text("hello", encoding="utf-8")     # a stray file
    (folder / "scratch").mkdir()                                     # a plain directory
    junk = folder / "half.ome.zarr"; junk.mkdir()
    (junk / ".zattrs").write_text("not json", encoding="utf-8")      # a broken store
    _, found = discover(folder)
    assert found == ["Tile0_Ch488.ome.zarr"]            # only the real store survives


def test_empty_folder_discovers_nothing(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    parent, found = discover(folder)
    assert found == []


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Tile0_Ch488.ome.zarr", "488"),   # normal
        ("Ch647", "647"),                  # bare
        ("Ch48.ome.zarr", None),           # only two digits — not a channel
        ("ch488.ome.zarr", None),          # lower-case c does not match
        ("Ch4880.ome.zarr", "488"),        # first three digits win
        ("Tile0.ome.zarr", None),          # no channel declared at all
    ],
)
def test_channel_parsing_edges(name, expected):
    assert channel_of(name) == expected


# --------------------------------------------------------------------------
# 3. Contrast: a sensible window from any volume, and never a crash
# --------------------------------------------------------------------------

def test_window_is_ordered_and_inside_the_data_range(tmp_path):
    store = write_store(tmp_path / "s.ome.zarr", a_volume(hi=4000))
    low, high = display_window(store)
    assert low < high
    assert 0 <= low and high <= 65535
    assert high < 4000                                  # windowed to the band, not the 16-bit max


def test_all_zero_volume_does_not_crash_and_stays_visible(tmp_path):
    store = write_store(tmp_path / "z.ome.zarr", np.zeros((4, 8, 8), dtype=np.uint16))
    low, high = display_window(store)
    assert high > low                                   # the one-count fallback, not a blank ramp
    assert (low, high) == (0.0, 1.0)


def test_uniform_volume_falls_back_to_a_one_count_window(tmp_path):
    store = write_store(tmp_path / "u.ome.zarr", np.full((4, 8, 8), 1234, dtype=np.uint16))
    low, high = display_window(store)
    assert high == low + 1.0


def test_omero_window_is_honoured_for_the_plane_and_ignored_for_the_volume(tmp_path):
    store = write_store(tmp_path / "o.ome.zarr", a_volume(hi=5000), omero=(100.0, 900.0))
    assert display_window(store) == (100.0, 900.0)                   # the plane trusts the store
    vlow, vhigh = display_window(store, volumetric=True)             # the volume measures instead
    assert (vlow, vhigh) != (100.0, 900.0)
    assert vlow < vhigh


def test_missing_or_broken_store_returns_the_full_range(tmp_path):
    assert display_window(tmp_path / "does-not-exist.zarr") == (0.0, 65535.0)
    broken = tmp_path / "broken.zarr"; broken.mkdir()
    (broken / ".zattrs").write_text("{ not json", encoding="utf-8")
    assert display_window(broken) == (0.0, 65535.0)


def test_one_hot_pixel_does_not_crush_the_window(tmp_path):
    v = np.full((6, 16, 16), 800, dtype=np.uint16)
    v[0, 0, 0] = 65535                                   # a single saturated pixel
    store = write_store(tmp_path / "hot.ome.zarr", v)
    _, high = display_window(store)
    assert high < 65535                                 # percentile, not max — image not crushed


def test_volume_window_starts_higher_than_the_plane_window(tmp_path):
    store = write_store(tmp_path / "v.ome.zarr", a_volume(hi=6000))
    plane_low, _ = display_window(store)
    volume_low, _ = display_window(store, volumetric=True)
    assert volume_low >= plane_low                      # keeps the volume's background transparent


# --------------------------------------------------------------------------
# 4. The HTTP contract, end to end, over real channel stores
# --------------------------------------------------------------------------

@pytest.fixture
def serving(tmp_path):
    """A server over a real three-channel acquisition folder, on a free port."""
    site = tmp_path / "site"
    (site / "assets").mkdir(parents=True)
    (site / "index.html").write_text("<!doctype html><title>page</title>", encoding="utf-8")
    data = tmp_path / "data"
    names = ["Tile0_Ch488.ome.zarr", "Tile0_Ch561.ome.zarr", "Tile0_Ch647.ome.zarr"]
    channel_folder(data, names)
    (tmp_path / "outside.txt").write_text("SECRET", encoding="utf-8")

    server = make_server(port=0, data_dir=data, site_dir=site, store=names)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], names
    finally:
        server.shutdown()
        thread.join(timeout=5)


def request(port, path, method="GET", body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        headers = {"Content-Length": str(len(body))} if body is not None else {}
        conn.request(method, path, body=body, headers=headers)
        r = conn.getresponse()
        return r.status, r.read()
    finally:
        conn.close()


def test_config_has_one_coloured_layer_per_channel(serving):
    port, names = serving
    status, body = request(port, "/api/config")
    assert status == 200
    config = json.loads(body)
    assert len(config["layers"]) == len(names)          # exactly the channels on disk
    by_source = {layer["source"]: layer for layer in config["layers"]}
    assert f"/data/{names[0]}/|zarr2:" in by_source
    for layer in config["layers"]:
        assert layer["color"] is not None               # multi-channel: each is coloured
        assert layer["window"]["low"] < layer["window"]["high"]


def test_health_is_ok(serving):
    port, _ = serving
    status, _ = request(port, "/api/health")
    assert status == 200


def test_missing_chunk_is_404_not_an_error(serving):
    # zarr reads a missing chunk as "empty here"; a 500 would break sparse data.
    port, names = serving
    status, _ = request(port, f"/data/{names[0]}/0/9.9.9")
    assert status == 404


@pytest.mark.parametrize(
    "attack",
    [
        "/data/../outside.txt",
        "/data/../../outside.txt",
        "/data/%2e%2e/outside.txt",
        "/data/..%2f..%2foutside.txt",
        "/data/Tile0_Ch488.ome.zarr/../../../outside.txt",
    ],
)
def test_path_traversal_cannot_escape_the_data_directory(serving, attack):
    port, _ = serving
    status, body = request(port, attack)
    assert status in (403, 404)                          # refused...
    assert b"SECRET" not in body                         # ...and the file never leaks


def test_goto_survives_valid_and_garbage_payloads(serving):
    port, _ = serving
    ok = json.dumps({"box": {"low": [0, 0, 0], "high": [10, 10, 10]}}).encode()
    status, _ = request(port, "/api/goto", method="POST", body=ok)
    assert status == 200
    for junk in (b"", b"not json at all", b"[1,2,3]", b"{" + b"x" * 100000):
        status, _ = request(port, "/api/goto", method="POST", body=junk)
        assert status < 500                              # a bad body is a client error, never a crash
