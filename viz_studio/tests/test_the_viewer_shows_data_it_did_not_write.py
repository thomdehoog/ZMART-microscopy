"""The viewer serves data written by a stranger's pen, and notices arrivals.

`a_microscope.AMicroscope` writes an acquisition the way the instrument
would -- plain zarr, no ZMART package anywhere near it. These tests close
the loop the contract promises from the other side: what that stranger
writes, plain zarr can read back exactly, a new moment only ever adds
files, our own server shows it, and the collection's declaration is a
sufficient arrival signal for a watcher -- position and timepoint alike,
one small file, no filesystem events needed.

Keeping the writers strangers to each other is the point: the viewer may
depend on the CONTRACT, never on our publisher's habits.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import zarr

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "building"))

from a_microscope import AMicroscope  # noqa: E402
from server import make_server  # noqa: E402

FRAME = 256


def a_frame(value: int, channels: int = 1) -> np.ndarray:
    seed = np.random.default_rng(value)
    return seed.integers(300, 3000, (channels, FRAME, FRAME)).astype("uint16")


def test_plain_zarr_reads_back_exactly_what_the_microscope_wrote(tmp_path):
    scope = AMicroscope(tmp_path / "overview", voxel_size=(0.5, 0.5),
                        timepoints=2, channels=2)
    pixels = a_frame(7, channels=2)
    scope.image_a_position("posA", pixels, location_yx=(0.0, 300.0))

    read = zarr.open_array(str(scope.collection / "posA" / "0"), mode="r")
    assert read.shape == (2, 2, 1, FRAME, FRAME)
    assert np.array_equal(np.asarray(read[0, 0, 0]), pixels[0])
    assert np.array_equal(np.asarray(read[0, 1, 0]), pixels[1])

    # The pyramid follows the contract's rule -- each level a 2x2 average.
    level1 = np.asarray(zarr.open_array(
        str(scope.collection / "posA" / "1"), mode="r")[0, 0, 0])
    expected = (pixels[0].reshape(FRAME // 2, 2, FRAME // 2, 2)
                .mean(axis=(1, 3)).round().astype("uint16"))
    assert np.array_equal(level1, expected)

    # And the place travels inside the member, as a translation.
    described = json.loads((scope.collection / "posA" / "zarr.json").read_text())
    placed = described["attributes"]["ome"]["multiscales"][0]["datasets"][0]
    kinds = {one["type"]: one for one in placed["coordinateTransformations"]}
    assert kinds["translation"]["translation"][3:] == [0.0, 150.0]  # y, x in um


def test_a_new_moment_only_adds_files_here_too(tmp_path):
    scope = AMicroscope(tmp_path / "overview", timepoints=3)
    scope.image_a_position("posA", a_frame(1), location_yx=(0, 0))

    member = scope.collection / "posA"
    before = {path: path.read_bytes() for path in member.rglob("*")
              if path.is_file() and "/c/0/" in str(path).replace("\\", "/")}
    assert before, "moment zero wrote no chunk files at all?"

    scope.image_a_position("posA", a_frame(2), location_yx=(0, 0), timepoint=1)

    after = {path: path.read_bytes() for path in member.rglob("*")
             if path.is_file() and "/c/0/" in str(path).replace("\\", "/")}
    assert after == before, (
        "the stranger's writer touched moment zero while recording moment "
        "one -- the write-once promise has to hold on their side of the "
        "fence too, or replacement semantics stop meaning anything"
    )


def test_the_declaration_is_a_sufficient_arrival_signal(tmp_path):
    """The watcher's whole contract: stat one file, learn every arrival."""
    scope = AMicroscope(tmp_path / "overview", timepoints=4)
    said = scope.collection / "zarr.json"

    def declared() -> dict:
        return json.loads(said.read_text())["attributes"]["zmart"]

    opening = declared()
    assert opening["members"] == [] and opening["moments"] == {}

    scope.image_a_position("posA", a_frame(1), location_yx=(0, 0))
    first = declared()
    assert first["members"] == ["posA"]
    assert first["moments"] == {"posA": 1}  # a new POSITION is visible here

    scope.image_a_position("posA", a_frame(2), location_yx=(0, 0), timepoint=1)
    second = declared()
    assert second["moments"] == {"posA": 2}, (
        "a new TIMEPOINT must move the declaration -- chunk files appearing "
        "is not a signal anybody can safely watch"
    )

    scope.image_a_position("posB", a_frame(3), location_yx=(0, 256))
    third = declared()
    assert third["members"] == ["posA", "posB"]
    assert third["moments"] == {"posA": 2, "posB": 1}


def test_our_own_server_shows_the_strangers_data(tmp_path):
    scope = AMicroscope(tmp_path / "overview")
    scope.image_a_position("posA", a_frame(9), location_yx=(0, 0))

    server = make_server(port=0, data_dir=scope.collection.parent,
                         store=["survey.ome.zarr/posA"])
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    try:
        port = server.server_address[1]

        def fetch(path: str) -> tuple[int, bytes]:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}{path}", timeout=30) as answer:
                    return answer.status, answer.read()
            except urllib.error.HTTPError as refused:
                return refused.code, b""

        status, described = fetch("/data/0/survey.ome.zarr/posA/zarr.json")
        assert status == 200, "the member's description must be servable"
        ome = json.loads(described)["attributes"]["ome"]
        assert [axis["name"] for axis in ome["multiscales"][0]["axes"]] == [
            "t", "c", "z", "y", "x"]

        status, chunk = fetch("/data/0/survey.ome.zarr/posA/0/c/0/0/0/0/0")
        assert status == 200 and len(chunk) > 0, (
            "the pixels the microscope wrote must reach the wire"
        )
    finally:
        server.shutdown()
        serving.join(timeout=5)
