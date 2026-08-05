"""Does a view built over OME-Zarr 0.5 tiles actually show anything?

The two generations of the format name a piece of an image differently, and the
difference is easy to miss. Version 0.4 stores a piece under its position with the
numbers joined together — ``0.0.0.1.2``. Version 0.5, which is built on the newer
zarr, usually puts a ``c`` in front, and that ``c`` is **a part of the name in its
own right**: ``c/0/0/0/1/2``, not ``c0/0/0/1/2``.

Joining it straight onto the first number gives a file that exists nowhere. Nothing
raises when that happens — the server answers "there is nothing here", exactly as it
does for ground nobody imaged, and the viewer fills it in. So the run opens, the
zoomed-out copies draw perfectly well because they are genuinely written, and the
full-size picture is simply **blank**, with nothing on screen to say why.

That is what these tests are for. They were written after finding exactly that
fault: every linked-view test in this suite used the older format, so the newer one
was never exercised, and a view over a real 0.5 acquisition would have shown nothing
at full zoom.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import linking
import numpy as np
from server import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zmart_storage.canvas import Channel, _declare_one  # noqa: E402
from zmart_storage.linked import PlacedTile, link_the_tiles  # noqa: E402

PIECE = 64
TILE = (1, 64, 64)
ACROSS = 2                      # two tiles side by side
BUNDLE = 128                    # how much picture one file holds when pieces are bundled
VOXEL_UM = (2.0, 0.35, 0.35)
ORIGIN_UM = (11.0, 5.5, 7.25)


def _a_newer_tile(store: Path, lands_x: int) -> Path:
    """One OME-Zarr 0.5 tile, holding the position each of its voxels came from."""
    arrays = _declare_one(
        store,
        canvas_shape=TILE,
        frames=1,
        channels=1,
        dtype="uint16",
        chunk=PIECE,
        levels=1,
        voxel_size_um=VOXEL_UM,
        origin_um=(ORIGIN_UM[0], ORIGIN_UM[1], ORIGIN_UM[2] + lands_x * VOXEL_UM[2]),
        channel_blocks=[Channel("488", window=(0, 4000)).described(65535)],
        ome_zarr_version="0.5",
    )
    across = np.arange(lands_x, lands_x + TILE[2], dtype=np.uint16)
    arrays[0][0, 0] = np.broadcast_to(1000 + across, TILE)
    return store


def _a_newer_run(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    placed = [
        PlacedTile(
            store=_a_newer_tile(folder / f"tile{index}.ome.zarr", index * TILE[2]),
            lands_at=(0, 0, index * TILE[2]),
        )
        for index in range(ACROSS)
    ]
    return link_the_tiles(
        folder, name="pointed", tiles=placed,
        view_shape=(TILE[0], TILE[1], ACROSS * TILE[2]),
    )


def _grab(address: str, into: Path) -> bool:
    try:
        with urllib.request.urlopen(address, timeout=30) as answer:
            body = answer.read()
    except urllib.error.HTTPError as why:
        if why.code == 404:
            return False
        raise
    into.parent.mkdir(parents=True, exist_ok=True)
    into.write_bytes(body)
    return True


def test_a_newer_format_view_points_at_files_that_exist(tmp_path):
    """The name the view asks for is the name the tile really used.

    This is the fault stated directly. A view that builds its piece names wrongly
    reports nothing wrong — it simply never finds anything — so the check has to be
    that the name resolves to a file which is actually on disk.
    """
    run = tmp_path / "run"
    view = _a_newer_run(run)

    listed = json.loads((view.path / "zmart-links.json").read_text(encoding="utf-8"))
    assert listed["prefix"] == "c", (
        "a 0.5 store names its pieces with a c in front, and the view should have "
        f"read that from the tiles rather than saying {listed['prefix']!r}"
    )

    for x in range(ACROSS):
        asked = f"0/c/0/0/0/0/{x}"
        found = linking.the_bytes_behind(view.path, asked)
        assert found is not None, (
            f"the view could not say where {asked} is, so that part of the picture "
            "would come out blank with nothing to say why"
        )
        assert (run / found.path).is_file(), (
            f"the view points {asked} at {found.path}, which is not a file that "
            "exists — the piece would be answered 'there is nothing here'"
        )


def test_a_newer_format_view_draws_the_specimen_and_not_blankness(tmp_path):
    """Read back through the server, every voxel is the one that was acquired.

    Every voxel holds ``1000 +`` the position it came from, so a blank picture and a
    misplaced one are both caught here, and told apart.
    """
    run = tmp_path / "run"
    view = _a_newer_run(run)
    width = ACROSS * TILE[2]

    server = make_server(
        port=0, data_dir=run, site_dir=run, store="pointed.ome.zarr", live=False,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = f"http://127.0.0.1:{server.server_address[1]}/data/0/pointed.ome.zarr"
    rebuilt = tmp_path / "asked" / "pointed.ome.zarr"
    rebuilt.mkdir(parents=True)
    served = 0
    try:
        _grab(f"{address}/zarr.json", rebuilt / "zarr.json")
        _grab(f"{address}/0/zarr.json", rebuilt / "0" / "zarr.json")
        for x in range(width // PIECE):
            name = f"c/0/0/0/0/{x}"
            if _grab(f"{address}/0/{name}", rebuilt / "0" / name):
                served += 1
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert served == width // PIECE, (
        f"only {served} of {width // PIECE} pieces of the full-size picture were "
        "served; the rest were answered 'there is nothing here', which is what a "
        "wrongly built piece name looks like from the outside"
    )

    import zarr
    picture = np.asarray(zarr.open_group(str(rebuilt), mode="r")["0"][0, 0, 0])
    expected = np.broadcast_to(1000 + np.arange(width, dtype=np.uint16), (TILE[1], width))
    wrong = np.argwhere(picture != expected)
    assert len(wrong) == 0, (
        f"{len(wrong)} of {picture.size} voxels came back from somewhere other than "
        "where they were acquired"
    )


def _a_bundled_tile(store: Path, lands_x: int) -> Path:
    """One 0.5 tile that keeps several pieces inside each file, rather than one.

    This is sharding: a bundle of pieces in a single file with a small index saying
    where each of them begins. A long run otherwise leaves millions of small files
    behind, which most filesystems handle badly, so real 0.5 acquisitions do it.
    """
    import zarr
    store.mkdir(parents=True, exist_ok=True)
    group = zarr.open_group(str(store), mode="w", zarr_format=3)
    array = group.create_array(
        "0", shape=(1, 1, TILE[0], BUNDLE, BUNDLE), dtype="uint16",
        chunks=(1, 1, 1, PIECE, PIECE),
        shards=(1, 1, 1, BUNDLE, BUNDLE),
    )
    across = np.arange(lands_x, lands_x + BUNDLE, dtype=np.uint16)
    array[0, 0] = np.broadcast_to(1000 + across, (TILE[0], BUNDLE, BUNDLE))

    document = json.loads((store / "zarr.json").read_text(encoding="utf-8"))
    document.setdefault("attributes", {})["ome"] = {
        "version": "0.5",
        "multiscales": [{
            "name": store.name,
            "axes": [
                {"name": "t", "type": "time"}, {"name": "c", "type": "channel"},
                {"name": "z", "type": "space", "unit": "micrometer"},
                {"name": "y", "type": "space", "unit": "micrometer"},
                {"name": "x", "type": "space", "unit": "micrometer"},
            ],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, 1.0, *VOXEL_UM]},
                {"type": "translation",
                 "translation": [0.0, 0.0, 0.0, 0.0, lands_x * VOXEL_UM[2]]},
            ]}],
        }],
    }
    (store / "zarr.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    return store


def test_tiles_that_bundle_their_pieces_are_pointed_at_too(tmp_path):
    """A sharded run opens, and the view is declared bundled exactly as its tiles are.

    What gets handed over is the bundle rather than a single piece, which changes
    nothing about the idea: the engine reads the bundle's own index and asks for the
    piece it wants by byte offset. What it does change is the *declaration* — a view
    stored differently from its tiles is a picture of noise, so the view has to
    bundle its pieces the same way round.
    """
    run = tmp_path / "run"
    run.mkdir()
    placed = [
        PlacedTile(
            store=_a_bundled_tile(run / f"bundled{index}.ome.zarr", index * BUNDLE),
            lands_at=(0, 0, index * BUNDLE),
        )
        for index in range(ACROSS)
    ]
    view = link_the_tiles(
        run, name="pointed", tiles=placed,
        view_shape=(TILE[0], BUNDLE, ACROSS * BUNDLE),
    )

    described = json.loads(
        (view.path / "0" / "zarr.json").read_text(encoding="utf-8")
    )
    bundling = [
        codec for codec in described["codecs"]
        if codec["name"] == "sharding_indexed"
    ]
    assert bundling, (
        "the view was declared with every piece in a file of its own while its "
        "tiles bundle theirs, so its description and their bytes disagree"
    )
    assert bundling[0]["configuration"]["chunk_shape"][-2:] == [PIECE, PIECE], (
        "the view's pieces inside a bundle are not the size the tiles' are"
    )
    assert (
        described["chunk_grid"]["configuration"]["chunk_shape"][-2:]
        == [BUNDLE, BUNDLE]
    ), "the view's bundles are not the size the tiles' bundles are"


def test_a_bundled_run_draws_every_voxel_where_it_was_acquired(tmp_path):
    """Read back through the server, a sharded run is the specimen and not noise."""
    run = tmp_path / "run"
    run.mkdir()
    placed = [
        PlacedTile(
            store=_a_bundled_tile(run / f"bundled{index}.ome.zarr", index * BUNDLE),
            lands_at=(0, 0, index * BUNDLE),
        )
        for index in range(ACROSS)
    ]
    width = ACROSS * BUNDLE
    link_the_tiles(
        run, name="pointed", tiles=placed,
        view_shape=(TILE[0], BUNDLE, width),
    )

    server = make_server(
        port=0, data_dir=run, site_dir=run, store="pointed.ome.zarr", live=False,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = f"http://127.0.0.1:{server.server_address[1]}/data/0/pointed.ome.zarr"
    rebuilt = tmp_path / "asked" / "pointed.ome.zarr"
    rebuilt.mkdir(parents=True)
    served = 0
    try:
        _grab(f"{address}/zarr.json", rebuilt / "zarr.json")
        _grab(f"{address}/0/zarr.json", rebuilt / "0" / "zarr.json")
        for x in range(width // BUNDLE):
            name = f"c/0/0/0/0/{x}"
            if _grab(f"{address}/0/{name}", rebuilt / "0" / name):
                served += 1
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert served == width // BUNDLE, (
        f"only {served} of {width // BUNDLE} bundles were served"
    )

    import zarr
    picture = np.asarray(zarr.open_group(str(rebuilt), mode="r")["0"][0, 0, 0])
    expected = np.broadcast_to(
        1000 + np.arange(width, dtype=np.uint16), (BUNDLE, width)
    )
    wrong = np.argwhere(picture != expected)
    assert len(wrong) == 0, (
        f"{len(wrong)} of {picture.size} voxels of a bundled run came back from "
        "somewhere other than where they were acquired"
    )


def test_bundling_needs_the_newer_format_and_says_so(tmp_path):
    """Asked for with 0.4, bundling is refused with the reason rather than ignored."""
    import pytest
    with pytest.raises(ValueError) as refused:
        _declare_one(
            tmp_path / "old.ome.zarr",
            canvas_shape=TILE, frames=1, channels=1, dtype="uint16",
            chunk=PIECE, levels=1, voxel_size_um=VOXEL_UM, origin_um=ORIGIN_UM,
            channel_blocks=[Channel("488", window=(0, 4000)).described(65535)],
            ome_zarr_version="0.4",
            shard=BUNDLE,
        )
    assert "0.5" in str(refused.value)


def test_the_older_format_still_names_its_pieces_the_old_way(tmp_path):
    """The fix for 0.5 must not disturb 0.4, which puts no c in front of anything."""
    run = tmp_path / "run"
    run.mkdir()
    placed = []
    for index in range(ACROSS):
        store = run / f"old{index}.ome.zarr"
        arrays = _declare_one(
            store,
            canvas_shape=TILE, frames=1, channels=1, dtype="uint16",
            chunk=PIECE, levels=1, voxel_size_um=VOXEL_UM,
            origin_um=(ORIGIN_UM[0], ORIGIN_UM[1],
                       ORIGIN_UM[2] + index * TILE[2] * VOXEL_UM[2]),
            channel_blocks=[Channel("488", window=(0, 4000)).described(65535)],
            ome_zarr_version="0.4",
        )
        arrays[0][0, 0] = 3
        placed.append(PlacedTile(store=store, lands_at=(0, 0, index * TILE[2])))

    view = link_the_tiles(
        run, name="pointedold", tiles=placed,
        view_shape=(TILE[0], TILE[1], ACROSS * TILE[2]),
    )
    listed = json.loads((view.path / "zmart-links.json").read_text(encoding="utf-8"))
    assert listed["prefix"] == "", "an 0.4 store puts nothing in front of a piece name"

    found = linking.the_bytes_behind(view.path, f"0/0{listed['separator']}0"
                                                f"{listed['separator']}0"
                                                f"{listed['separator']}0"
                                                f"{listed['separator']}0")
    assert found is not None and (run / found.path).is_file()
