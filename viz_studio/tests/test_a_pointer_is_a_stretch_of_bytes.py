"""A pointer says a file, a place in it, and a length — not just a file.

When the viewer asks for a piece of a picture that was never written down, the
answer is found in the list of pointers beside it and the bytes come from a file
that already exists. For every store this reads today those bytes are the *whole*
of that file, because a piece of an ordinary zarr image is a file of its own.

It is still answered as a stretch of bytes — where the file is, how far into it to
start, and how many bytes to take — and these tests are about that shape. Two kinds
of store make it necessary rather than tidy. A **sharded** store keeps many pieces
inside one larger file, so a piece of it is a stretch in the middle. And a store
that is not zarr at all, such as a TIFF stack, is the same shape of problem. Neither
can be answered for by handing over a whole file, and both become possible without
anything that reads the list having to change.

The tests below check the shape works now, that a view written before the shape
changed is still readable, and that a list this reader does not understand is left
alone rather than guessed at.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import linking
import pytest
from server import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zmart_storage.canvas import Channel, _declare_one  # noqa: E402
from zmart_storage.linked import PlacedTile, link_the_tiles  # noqa: E402

PIECE = 64
TILE = (1, 64, 128)
VOXEL_UM = (2.0, 0.35, 0.35)
ORIGIN_UM = (11.0, 5.5, 7.25)


def _a_small_view(folder: Path) -> Path:
    """One tile, and a view pointing at it. Enough to have a list of pointers."""
    folder.mkdir(parents=True, exist_ok=True)
    store = folder / "tile.ome.zarr"
    arrays = _declare_one(
        store,
        canvas_shape=TILE,
        frames=1,
        channels=1,
        dtype="uint16",
        chunk=PIECE,
        levels=1,
        voxel_size_um=VOXEL_UM,
        origin_um=ORIGIN_UM,
        channel_blocks=[Channel("488", window=(0, 4000)).described(65535)],
    )
    arrays[0][0, 0] = 7
    view = link_the_tiles(
        folder, name="pointed",
        tiles=[PlacedTile(store=store, lands_at=(0, 0, 0))],
        view_shape=TILE,
    )
    return view.path


def _ask(address: str, byte_range: str | None = None) -> tuple[int, bytes]:
    """Ask the server for something, optionally for only part of it."""
    request = urllib.request.Request(address)
    if byte_range is not None:
        request.add_header("Range", byte_range)
    try:
        with urllib.request.urlopen(request, timeout=30) as answer:
            return answer.status, answer.read()
    except urllib.error.HTTPError as why:
        return why.code, b""


def _serving(folder: Path, image: str):
    server = make_server(
        port=0, data_dir=folder, site_dir=folder, store=image, live=False,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}/data/0"


def test_a_pointer_says_where_the_bytes_are_and_how_many(tmp_path):
    """The answer is a file, a place in it and a length — the whole file, today."""
    run = tmp_path / "run"
    view = _a_small_view(run)

    found = linking.the_bytes_behind(view, "0/0/0/0/0/0")
    assert found is not None, (
        "the view could not say where its first piece is, so it would draw nothing"
    )
    assert found.offset == 0 and found.length is None, (
        f"a piece of an ordinary zarr image is the whole of its file, but this said "
        f"it begins at {found.offset} and runs for {found.length} bytes"
    )
    assert found.is_the_whole_file
    assert (run / found.path).is_file(), (
        f"the view points at {found.path}, which is not a file that exists"
    )


def test_the_list_says_how_a_tile_keeps_its_pieces(tmp_path):
    """Written down rather than assumed, so a sharded tile can be described later."""
    run = tmp_path / "run"
    view = _a_small_view(run)
    listed = json.loads((view / "zmart-links.json").read_text(encoding="utf-8"))

    # Version 3 is version 2 with the companion file a growing view adds tiles to.
    # This asserted 2 for a while after the writer had moved on, which made it a
    # test of a number nobody was writing any more rather than of the shape below.
    assert listed["version"] == 3
    for tile in listed["tiles"]:
        assert tile["held_as"] == "file", (
            "every tile written here keeps each piece in a file of its own, and the "
            "list should say so plainly rather than leaving a reader to assume it"
        )


def test_a_view_written_before_this_change_is_still_read(tmp_path):
    """An older list is understood, not refused.

    Version 1 did not say how a tile keeps its pieces because there was only one way
    it could — each piece its own file. That is a known answer rather than a guess,
    so a view built before this change still opens instead of quietly drawing
    nothing.
    """
    run = tmp_path / "run"
    view = _a_small_view(run)
    listing = view / "zmart-links.json"
    older = json.loads(listing.read_text(encoding="utf-8"))
    older["version"] = 1
    for tile in older["tiles"]:
        tile.pop("held_as", None)
    listing.write_text(json.dumps(older, indent=1), encoding="utf-8")

    found = linking.the_bytes_behind(view, "0/0/0/0/0/0")
    assert found is not None, "a view written before this change stopped being read"
    assert found.is_the_whole_file


def test_a_way_of_holding_pieces_we_do_not_know_is_refused(tmp_path):
    """Refused rather than guessed at, because a guess would be drawn as specimen.

    If a tile said its pieces live inside a larger file and this reader did not know
    how to find them, handing over the whole file — or the wrong stretch of it —
    would not raise anything anywhere. The viewer would simply draw whatever those
    bytes happened to decode to. So the whole list is left unread instead.
    """
    run = tmp_path / "run"
    view = _a_small_view(run)
    listing = view / "zmart-links.json"
    listed = json.loads(listing.read_text(encoding="utf-8"))
    for tile in listed["tiles"]:
        tile["held_as"] = "packed-somehow"
    listing.write_text(json.dumps(listed, indent=1), encoding="utf-8")

    assert linking.the_bytes_behind(view, "0/0/0/0/0/0") is None, (
        "a way of holding pieces this reader does not know was answered for anyway"
    )


def test_the_server_hands_over_the_stretch_a_pointer_asks_for(tmp_path, monkeypatch):
    """A piece living inside a larger file is served as that piece, not the file.

    This is what the shape is *for*, and no store written by this project needs it
    yet — so the pointer is stood in for here. What is being checked is the half
    that will not change when sharded stores arrive: given a place and a length, the
    server answers with exactly those bytes and treats them as the whole of what was
    asked for.
    """
    run = tmp_path / "run"
    run.mkdir()
    (run / "pretend.ome.zarr").mkdir()
    inside_a_larger_file = bytes(range(256))
    (run / "shard.bin").write_bytes(inside_a_larger_file)

    monkeypatch.setattr(
        linking, "the_bytes_behind",
        lambda store, inside: linking.Held(path="shard.bin", offset=100, length=50),
    )

    server, thread, address = _serving(run, "pretend.ome.zarr")
    try:
        status, body = _ask(f"{address}/pretend.ome.zarr/0/0/0/0/0/0")
        assert status == 200
        assert body == inside_a_larger_file[100:150], (
            "the server handed back something other than the stretch the pointer "
            "named, which would be drawn as though it were the specimen"
        )

        # And a browser asking for part of a piece means part of *the piece*, not
        # part of the file it happens to live in. This is how a sharded store is
        # read, so getting it wrong would show up only on real data.
        status, body = _ask(f"{address}/pretend.ome.zarr/0/0/0/0/0/0", "bytes=10-19")
        assert status == 206
        assert body == inside_a_larger_file[110:120], (
            "a range asked for inside a piece was measured from the beginning of "
            "the file rather than from the beginning of the piece"
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_a_piece_no_tile_covers_is_still_answered_plainly(tmp_path):
    """Ground nobody imaged stays a plain "there is nothing here"."""
    run = tmp_path / "run"
    _a_small_view(run)
    server, thread, address = _serving(run, "pointed.ome.zarr")
    try:
        status, _ = _ask(f"{address}/pointed.ome.zarr/0/0/0/0/9/9")
        assert status == 404
    finally:
        server.shutdown()
        thread.join(timeout=5)
