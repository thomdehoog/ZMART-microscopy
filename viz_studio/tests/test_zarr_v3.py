"""Zarr v3 and OME-Zarr 0.5, including sharded stores.

The engine has been able to read these all along — it registers ``zarr:``,
``zarr2:`` and ``zarr3:`` providers, implements the ``sharding_indexed`` codec,
and accepts OME multiscale versions 0.4 and 0.5. What stopped a version 3 store
opening was our own wiring: every source address was written ``|zarr2:``.

Sharding matters here for a reason that has nothing to do with speed of reading.
A run of forty thousand positions at six pyramid levels is millions of small
files, which a managed Windows filesystem handles badly. Sharding packs them into
few large ones, and the engine still fetches a single chunk out of a shard with an
HTTP range request rather than pulling the whole thing — so the filesystem relief
costs nothing at the viewer.

The scheme is chosen per store from what is on disk rather than by asking the
engine to detect it. ``zarr:`` would auto-detect, but it does so by probing for
*both* layouts on every source, doubling the small metadata requests that a large
folder is already dominated by.

Opening a version 3 store is only half of reading one. The viewer also has to say
how far a timelapse has got, how many channels an array really holds, and repair an
axis unit spelled the everyday way — and each of those was reading version 2
metadata only, so each failed on a 0.5 store while looking perfectly healthy. Those
are the classes below, and one of them, ``TestWhenOneFileHoldsSeveralMoments``,
covers a version 2 store as well: a file spanning several moments defeats counting
whichever version wrote it, and sharding is simply the form it usually takes.
"""

from __future__ import annotations

import json
import threading
import urllib.request

import numpy as np
import pytest
import stores
import zarr
from library import Library
from server import make_server
from stores import (
    axis_names,
    declared_channels,
    is_store,
    normalise_units,
    voxel_size,
    written_timepoints,
    zarr_scheme,
)


def _ome(*, unit="micrometer", channels=("488", "561")):
    """The OME-Zarr 0.5 description of a ``t, c, z, y, x`` image.

    ``unit`` is how the spatial axes spell their unit. The format asks for
    ``micrometer`` and the engine refuses a store that says anything else, so writing
    ``um`` here is how a store from a foreign instrument is imitated.
    """
    return {
        "version": "0.5",
        "multiscales": [
            {
                "axes": [
                    {"name": "t", "type": "time", "unit": "second"},
                    {"name": "c", "type": "channel"},
                    {"name": "z", "type": "space", "unit": unit},
                    {"name": "y", "type": "space", "unit": unit},
                    {"name": "x", "type": "space", "unit": unit},
                ],
                "datasets": [
                    {
                        "path": "0",
                        "coordinateTransformations": [
                            {"type": "scale", "scale": [1.0, 1.0, 2.0, 0.5, 0.5]}
                        ],
                    }
                ],
            }
        ],
        "omero": {"channels": [{"label": name} for name in channels]},
    }


def _v3_store(path, *, channels=("488", "561"), shards=None, unit="micrometer", describes=None):
    """An OME-Zarr 0.5 store: zarr v3, metadata under ``ome`` in ``zarr.json``.

    ``channels`` says how many channels the *array* really holds. ``describes``, where
    it is given, is what the ``omero`` block claims instead — which is how a store
    whose description has drifted from its own array is written, and that does happen.
    """
    shape = (1, len(channels), 4, 64, 64)
    chunks = (1, 1, 2, 32, 32)
    group = zarr.open_group(str(path), mode="w", zarr_format=3)
    array = group.create_array(
        "0", shape=shape, chunks=chunks, shards=shards, dtype="uint16"
    )
    array[:] = np.full(shape, 1200, dtype=np.uint16)
    group.attrs.update({"ome": _ome(unit=unit, channels=describes or channels)})
    return path


def _v2_store(path):
    """The layout everything else in this suite writes, for the contrast."""
    path.mkdir(parents=True)
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    group.create_array("0", shape=(4, 32, 32), chunks=(1, 32, 32), dtype="uint16")[:] = 900
    (path / ".zattrs").write_text(
        json.dumps(
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [{"name": a, "unit": "micrometer"} for a in ("z", "y", "x")],
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": [2.0, 0.5, 0.5]}
                                ],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


class TestChoosingTheScheme:
    def test_a_version_2_store_is_addressed_as_zarr2(self, tmp_path):
        assert zarr_scheme(_v2_store(tmp_path / "old.ome.zarr")) == "zarr2"

    def test_a_version_3_store_is_addressed_as_zarr3(self, tmp_path):
        assert zarr_scheme(_v3_store(tmp_path / "new.ome.zarr")) == "zarr3"

    def test_a_sharded_store_is_addressed_the_same_way(self, tmp_path):
        """Sharding is a codec, not a format version — it must not change the scheme."""
        store = _v3_store(tmp_path / "sharded.ome.zarr", shards=(1, 1, 4, 64, 64))
        assert zarr_scheme(store) == "zarr3"

    def test_something_unreadable_falls_back_rather_than_raising(self, tmp_path):
        empty = tmp_path / "nothing"
        empty.mkdir()
        assert zarr_scheme(empty) == "zarr2"


class TestReadingVersion3Metadata:
    """OME 0.5 puts multiscales under ``ome`` inside ``zarr.json``, not in ``.zattrs``."""

    def test_it_is_recognised_as_a_store_at_all(self, tmp_path):
        assert is_store(_v3_store(tmp_path / "new.ome.zarr"))

    def test_its_axes_are_read(self, tmp_path):
        store = _v3_store(tmp_path / "new.ome.zarr")
        assert axis_names(store) == ["t", "c", "z", "y", "x"]

    def test_its_voxel_size_is_read(self, tmp_path):
        """Spatial axes only — the t and c entries say nothing about magnification."""
        store = _v3_store(tmp_path / "new.ome.zarr")
        assert voxel_size(store) == (2.0, 0.5, 0.5)

    def test_its_channels_are_read_from_the_ome_block(self, tmp_path):
        """0.5 moved ``omero`` under ``ome``; reading the old place finds nothing."""
        store = _v3_store(tmp_path / "new.ome.zarr", channels=("488", "561", "640"))
        assert declared_channels(store) == ["488", "561", "640"]

    def test_a_sharded_store_reads_the_same(self, tmp_path):
        store = _v3_store(tmp_path / "sharded.ome.zarr", shards=(1, 1, 4, 64, 64))
        assert axis_names(store) == ["t", "c", "z", "y", "x"]
        assert declared_channels(store) == ["488", "561"]


# The ways a version 3 store can name the pieces of its image, and what each one
# leaves on disk for the moment numbered 3 of a five-dimensional image. All of these
# are ordinary, and a store we did not write may use any of them.
#
# Two things here are easy to walk past. The ``default`` naming puts a ``c`` in front
# of every piece, which is a folder of its own when the separator is a slash. And the
# two namings fall back to *different* separators when a store does not say: a slash
# for ``default``, a dot for ``v2``.
def _naming(name, separator=None):
    """One ``chunk_key_encoding``: how a version 3 store builds a piece's name.

    Leaving ``separator`` out writes a store that does not say, which is how the two
    namings come to be using different ones.
    """
    return {"name": name, **({"configuration": {"separator": separator}} if separator else {})}


_NAMINGS = {
    "default, in folders": (_naming("default", "/"), "0/c/3/0/0/0/0"),
    "default, all in one folder": (_naming("default", "."), "0/c.3.0.0.0.0"),
    "v2, in folders": (_naming("v2", "/"), "0/3/0/0/0/0"),
    "v2, all in one folder": (_naming("v2", "."), "0/3.0.0.0.0"),
    "default, separator unstated": (_naming("default"), "0/c/3/0/0/0/0"),
    "v2, separator unstated": (_naming("v2"), "0/3.0.0.0.0"),
}


def _v3_timelapse(path, *, moments=1000, imaged=(0, 1, 2), naming=None, shards=None):
    """A version 3 timelapse with room declared for ``moments`` and images at ``imaged``.

    This is the arrangement `DATA_LAYOUT.md` asks a run to use — declare room for
    comfortably more moments than the experiment could record, then fill them in as it
    goes — written to OME-Zarr 0.5 rather than 0.4. A moment nothing has been written
    to takes up no room on disk at all, which is what makes declaring generously free.

    ``naming`` is the ``chunk_key_encoding`` the array is given, from ``_NAMINGS``.
    Where it states no separator the store is written with the one that naming falls
    back to and the statement is then taken back out of the file, because zarr fills it
    in for us and a store from another writer may well leave it out.

    ``shards`` packs several moments into one file, which is the case where the names on
    disk stop being able to say how far the images reach.
    """
    encoding = naming or {"name": "default"}
    stated = encoding.get("configuration")
    fallback = "." if encoding["name"] == "v2" else "/"
    group = zarr.open_group(str(path), mode="w", zarr_format=3)
    array = group.create_array(
        "0",
        shape=(moments, 1, 1, 8, 8),
        chunks=(1, 1, 1, 8, 8),
        shards=shards,
        dtype="uint16",
        chunk_key_encoding={**encoding, "configuration": stated or {"separator": fallback}},
    )
    for moment in imaged:
        array[moment] = 1200
    if stated is None:
        described = json.loads((path / "0" / "zarr.json").read_text(encoding="utf-8"))
        described["chunk_key_encoding"] = encoding
        (path / "0" / "zarr.json").write_text(json.dumps(described), encoding="utf-8")
    group.attrs.update({"ome": _ome()})
    return path


def _v2_timelapse(path, *, moments=1000, imaged=(0, 1, 2), separator="/", spans=1):
    """The same timelapse written the way our own writer writes, as the control.

    ``spans`` is how many moments one file on disk covers, which is one for ordinary
    data. Anything more and the furthest file stops saying how far the images reach.
    """
    path.mkdir(parents=True, exist_ok=True)
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    array = group.create_array(
        "0",
        shape=(moments, 1, 1, 8, 8),
        chunks=(spans, 1, 1, 8, 8),
        dtype="uint16",
        chunk_key_encoding={"name": "v2", "separator": separator},
    )
    for moment in imaged:
        array[moment] = 1200
    described = _ome()
    (path / ".zattrs").write_text(
        json.dumps({k: v for k, v in described.items() if k != "version"}), encoding="utf-8"
    )
    return path


class TestHowFarAVersion3TimelapseReaches:
    """Counting the moments a version 3 store has actually imaged.

    This is what stops the time slider at the furthest moment on disk. It matters
    because a timelapse declares room for far more moments than it will record, so
    without a count the operator is offered every moment the store *claims* — and the
    drawing engine remembers "there is nothing here" for a moment looked at too early
    and will not look again, so such a moment stays blank for the rest of the session
    even after the microscope has written it.

    ``None`` from ``written_timepoints`` means "place no limit on the slider", so
    failing to read a version 3 store is not a small loss of precision. A run of three
    moments inside a store declaring a thousand offers the operator all thousand.
    """

    def test_the_namings_really_do_look_like_this(self, tmp_path):
        """What is on disk, checked rather than assumed, since everything else rests on it.

        Written down here because it is the one thing in this file that a new version
        of zarr could change underneath us, and because a reader of these tests should
        be able to see the layouts rather than take them on trust.
        """
        for label, (naming, piece) in _NAMINGS.items():
            store = _v3_timelapse(tmp_path / label.replace(", ", "_"), imaged=(3,), naming=naming)
            assert (store / piece).exists(), f"{label}: expected a piece at {piece}"

    @pytest.mark.parametrize("naming", list(_NAMINGS), ids=list(_NAMINGS))
    def test_three_moments_imaged_of_a_thousand_declared_are_counted(self, tmp_path, naming):
        store = _v3_timelapse(tmp_path / "new.ome.zarr", naming=_NAMINGS[naming][0])
        assert written_timepoints(store) == 3, (
            "the moments on disk were not counted, so the slider would offer all "
            "thousand moments the store declares"
        )

    def test_the_version_2_control_counts_the_same_three(self, tmp_path):
        """The same data written the old way. This already worked and must go on working."""
        assert written_timepoints(_v2_timelapse(tmp_path / "old.ome.zarr")) == 3

    @pytest.mark.parametrize("naming", list(_NAMINGS), ids=list(_NAMINGS))
    def test_a_moment_landing_is_noticed(self, tmp_path, naming):
        """The count has to move when the run writes another moment.

        The answer is remembered against the modification time of the folder holding
        the moments, so that asking again costs one cheap look. Version 3's default
        naming puts that folder one step further in, under ``c``, and the level folder
        above it is untouched by a write — so watching the wrong one leaves the viewer
        repeating the first answer it ever gave for the rest of the run.
        """
        store = _v3_timelapse(tmp_path / "new.ome.zarr", imaged=(0,), naming=_NAMINGS[naming][0])
        assert written_timepoints(store) == 1
        zarr.open_array(str(store / "0"), mode="r+")[4] = 1200
        assert written_timepoints(store) == 5, "a moment written during the run went unnoticed"

    @pytest.mark.parametrize("naming", list(_NAMINGS), ids=list(_NAMINGS))
    def test_a_store_with_nothing_written_yet_says_so(self, tmp_path, naming):
        """A live run met before its first moment lands, which is the ordinary case."""
        store = _v3_timelapse(tmp_path / "new.ome.zarr", imaged=(), naming=_NAMINGS[naming][0])
        assert written_timepoints(store) is None
        zarr.open_array(str(store / "0"), mode="r+")[0] = 1200
        assert written_timepoints(store) == 1, "the store was still thought to be empty"

    def test_a_canvas_imaged_at_one_far_along_moment_reaches_it(self, tmp_path):
        """A workflow images the moments it chooses, so moment 900 may be the only one."""
        store = _v3_timelapse(tmp_path / "new.ome.zarr", imaged=(900,))
        assert written_timepoints(store) == 901

    def test_a_flat_folder_too_large_to_read_is_still_abandoned(self, tmp_path, monkeypatch):
        """The cap on reading a heaped folder has to survive the version 3 names too.

        A store that files every piece in one folder can hold millions of them, which
        is slow to read and hard on the filesystem besides. The viewer looks at a
        bounded number and then declines rather than keeping the operator waiting. The
        limit is turned right down here so that the giving-up can be watched without
        writing millions of files.
        """
        monkeypatch.setattr(stores, "_SCAN_LIMIT", 5)
        naming, _ = _NAMINGS["default, all in one folder"]
        store = _v3_timelapse(tmp_path / "new.ome.zarr", imaged=(0, 1), naming=naming)
        for index in range(20):
            (store / "0" / f"c.0.0.0.{index}.0").write_bytes(b"")
        assert written_timepoints(store) is None


class TestWhenOneFileHoldsSeveralMoments:
    """A piece of image spanning several moments cannot be counted, and must not be.

    Everything in the class above rests on one file being one moment, so that the
    furthest file names the furthest moment. A store may instead give each file a span
    of the time axis: a chunk covering ten moments, or a shard packing a thousand of
    them into a single file. Sharding is not exotic — it exists so that a run of forty
    thousand positions does not leave millions of small files on a filesystem that
    handles them badly.

    Where a file spans several moments the furthest file says almost nothing. A run
    nine hundred moments into a shard spanning a thousand has written one file, numbered
    zero, and counting it as one moment would show the operator a single moment out of
    nine hundred that exist and are perfectly readable. So the answer is ``None``,
    meaning "I cannot say" — the slider is then not limited, and every moment the store
    declares stays reachable.

    That is a worse answer than a count and a much better one than a wrong count.
    Under-reporting is only tolerable while the error is bounded by one moment; bounded
    by the span of a shard it hides the whole run.
    """

    @pytest.mark.parametrize("naming", list(_NAMINGS), ids=list(_NAMINGS))
    def test_a_shard_spanning_the_whole_timelapse_is_not_counted(self, tmp_path, naming):
        store = _v3_timelapse(
            tmp_path / "new.ome.zarr",
            imaged=(900,),
            naming=_NAMINGS[naming][0],
            shards=(1000, 1, 1, 8, 8),
        )
        # One file exists, and it is numbered zero, because it holds every moment.
        assert written_timepoints(store) is None, (
            "a shard's number was read as a moment, so nine hundred imaged moments "
            "would have been shown as one"
        )

    def test_a_shard_holding_one_moment_each_is_counted_as_usual(self, tmp_path):
        """Sharding by itself is no obstacle: what matters is only the span in time.

        A store may shard across space — packing the pieces of one plane together —
        and still write one file per moment, and then the names say exactly what they
        say for any other store.
        """
        store = _v3_timelapse(tmp_path / "new.ome.zarr", imaged=(0, 1, 2), shards=(1, 1, 1, 8, 8))
        assert written_timepoints(store) == 3

    def test_a_version_2_chunk_spanning_several_moments_is_not_counted(self, tmp_path):
        """The same trap without any version 3 involved, and it is the older of the two.

        A version 2 store may chunk its time axis a hundred moments at a time. The file
        holding moment 900 is then numbered 9, and reading that as a moment says the run
        has reached its tenth moment when it has in fact reached its nine hundred and
        first.
        """
        store = _v2_timelapse(tmp_path / "old.ome.zarr", imaged=(900,), spans=100)
        assert (store / "0" / "9").exists(), "expected the file numbered 9 to hold moment 900"
        assert written_timepoints(store) is None


class TestReadingTheChannelCountFromTheArray:
    """The array says how many channels there are; the description only claims to.

    A store's ``omero`` block is a convenience — labels and colours for the layer
    list — and nothing keeps it in step with the array beside it. So a description
    naming three channels for a two-channel array is an ordinary sort of mistake,
    and believing it produces a row in the panel with nothing behind it at all: an
    empty layer the operator has no way to account for.
    """

    def test_a_description_claiming_more_channels_than_exist_is_not_believed(self, tmp_path):
        store = _v3_store(
            tmp_path / "new.ome.zarr", channels=("488", "561"), describes=("488", "561", "640")
        )
        assert declared_channels(store) == ["488", "561"], (
            "the omero block was believed over the array, so a third layer was offered "
            "with no data behind it"
        )

    def test_a_version_2_store_is_still_read_the_same_way(self, tmp_path):
        """The positive control: this already worked for version 2 and must go on working."""
        store = tmp_path / "old.ome.zarr"
        store.mkdir(parents=True)
        group = zarr.open_group(str(store), mode="w", zarr_format=2)
        group.create_array("0", shape=(1, 2, 4, 32, 32), chunks=(1, 1, 1, 32, 32), dtype="uint16")
        described = _ome(channels=("488", "561", "640"))
        (store / ".zattrs").write_text(
            json.dumps({k: v for k, v in described.items() if k != "version"}), encoding="utf-8"
        )
        assert declared_channels(store) == ["488", "561"]


class TestRepairingUnitsInAVersion3Description:
    """The unit repair has to reach into ``zarr.json``, or it stops working at 0.5.

    ``test_axis_units.py`` explains why the repair exists at all: the engine refuses
    a whole image over a unit spelled ``um``, which is what every microscopist writes
    and what a real 75 GB acquisition on this machine says. The repair was written for
    stores from foreign instruments — and an instrument new enough to have moved to
    OME-Zarr 0.5 is exactly the one most likely to need it. Reading only the version 2
    places means the repair quietly stops working on precisely those stores.
    """

    def _units_in(self, raw):
        described = json.loads(raw)["attributes"]["ome"]["multiscales"][0]["axes"]
        return [axis.get("unit") for axis in described]

    def test_the_everyday_spelling_is_repaired_where_version_3_keeps_it(self, tmp_path):
        store = _v3_store(tmp_path / "new.ome.zarr", unit="um")
        raw = (store / "zarr.json").read_bytes()
        assert self._units_in(raw) == ["second", None, "um", "um", "um"]
        assert self._units_in(normalise_units(raw)) == [
            "second",
            None,
            "micrometer",
            "micrometer",
            "micrometer",
        ]

    def test_the_rest_of_the_file_comes_through_untouched(self, tmp_path):
        """A repaired ``zarr.json`` still has to be a description zarr can read.

        Everything outside the attributes belongs to zarr rather than to OME, and
        losing any of it would leave a store that opened before and does not now —
        which would be a far worse outcome than an unrepaired unit.
        """
        store = _v3_store(tmp_path / "new.ome.zarr", unit="um")
        raw = (store / "zarr.json").read_bytes()
        before, after = json.loads(raw), json.loads(normalise_units(raw))
        assert after["zarr_format"] == before["zarr_format"] == 3
        assert after["node_type"] == before["node_type"] == "group"

    def test_a_store_already_spelled_correctly_is_left_byte_for_byte_alone(self, tmp_path):
        """The common case. These descriptions are handed to the browser to keep."""
        store = _v3_store(tmp_path / "new.ome.zarr")
        raw = (store / "zarr.json").read_bytes()
        assert normalise_units(raw) is raw


class TestServingVersion3:
    def _config_over_http(self, folder, name):
        server = make_server(port=0, data_dir=folder, store=[name], live=False)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_address[1]}/api/config"
            ) as answer:
                return json.loads(answer.read())
        finally:
            server.shutdown()
            thread.join(timeout=5)

    def test_the_config_addresses_it_as_zarr3(self, tmp_path):
        folder = tmp_path / "run"
        folder.mkdir()
        _v3_store(folder / "overview_pos001.ome.zarr", shards=(1, 1, 4, 64, 64))
        config = self._config_over_http(folder, "overview_pos001.ome.zarr")
        sources = [source for layer in config["layers"] for source in layer.get("sources", [])]
        assert sources, "a version 3 store produced no layers at all"
        assert all(source.endswith("|zarr3:") for source in sources), sources

    def test_a_version_2_store_is_still_addressed_as_zarr2(self, tmp_path):
        """The positive control: the change must not relabel what already worked."""
        folder = tmp_path / "run"
        folder.mkdir()
        _v2_store(folder / "overview_pos001.ome.zarr")
        config = self._config_over_http(folder, "overview_pos001.ome.zarr")
        sources = [source for layer in config["layers"] for source in layer.get("sources", [])]
        assert sources and all(source.endswith("|zarr2:") for source in sources), sources

    def test_a_version_3_store_opens_as_a_dataset(self, tmp_path):
        folder = tmp_path / "run"
        folder.mkdir()
        _v3_store(folder / "overview_pos001.ome.zarr")
        library = Library()
        number = library.open(folder)
        assert library.dataset(number).stores == ["overview_pos001.ome.zarr"]


class TestTheServerContractShardingNeeds:
    """Byte ranges and HEAD, which nothing asked of this server until sharding did.

    These live beside the sharding tests because that is the only thing that uses
    them, and because the end-to-end test above cannot say *why* it failed when
    one of them breaks — it simply waits for pixels that never come.
    """

    def _serving(self, tmp_path):
        folder = tmp_path / "run"
        folder.mkdir()
        store = _v2_store(folder / "overview_pos001.ome.zarr")
        server = make_server(port=0, data_dir=folder, store=[store.name], live=False)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        chunk = f"http://127.0.0.1:{server.server_address[1]}/data/0/{store.name}/0/0.0.0"
        return server, thread, chunk

    def _ask(self, url, *, headers=None, method="GET"):
        request = urllib.request.Request(url, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(request) as answer:
                return answer.status, dict(answer.headers), answer.read()
        except urllib.error.HTTPError as refused:
            return refused.code, dict(refused.headers), refused.read()

    def test_a_range_gets_exactly_those_bytes_and_says_so(self, tmp_path):
        server, thread, chunk = self._serving(tmp_path)
        try:
            _, _, whole = self._ask(chunk)
            status, headers, body = self._ask(chunk, headers={"Range": "bytes=4-11"})
            assert status == 206
            assert body == whole[4:12]
            assert headers["Content-Range"] == f"bytes 4-11/{len(whole)}"
            assert headers["Content-Length"] == "8"
        finally:
            server.shutdown()
            thread.join(timeout=5)

    def test_a_suffix_range_reads_from_the_end(self, tmp_path):
        """How the index at the end of a shard is fetched."""
        server, thread, chunk = self._serving(tmp_path)
        try:
            _, _, whole = self._ask(chunk)
            status, _, body = self._ask(chunk, headers={"Range": "bytes=-6"})
            assert status == 206
            assert body == whole[-6:]
        finally:
            server.shutdown()
            thread.join(timeout=5)

    def test_head_gives_the_size_without_the_body(self, tmp_path):
        """The body is not merely wasteful here — it desynchronises the connection."""
        server, thread, chunk = self._serving(tmp_path)
        try:
            _, _, whole = self._ask(chunk)
            status, headers, body = self._ask(chunk, method="HEAD")
            assert status == 200
            assert body == b""
            assert headers["Content-Length"] == str(len(whole))
            assert headers["Accept-Ranges"] == "bytes"
        finally:
            server.shutdown()
            thread.join(timeout=5)

    def test_a_range_past_the_end_is_refused_rather_than_wrapped(self, tmp_path):
        server, thread, chunk = self._serving(tmp_path)
        try:
            status, headers, _ = self._ask(chunk, headers={"Range": "bytes=999999-"})
            assert status == 416
            assert headers["Content-Range"].startswith("bytes */")
        finally:
            server.shutdown()
            thread.join(timeout=5)

    def test_no_range_still_gets_the_whole_thing(self, tmp_path):
        """The positive control: the ordinary request must be untouched."""
        server, thread, chunk = self._serving(tmp_path)
        try:
            status, headers, body = self._ask(chunk)
            assert status == 200
            assert "Content-Range" not in headers
            assert len(body) == int(headers["Content-Length"])
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_a_sharded_version_3_store_reaches_the_renderer(tmp_path, built_dist, browser):
    """The whole point, end to end: sharded v3 data actually draws.

    Nothing else in the suite would catch a wrong scheme being emitted, because
    every other fixture is version 2 and ``|zarr2:`` is right for those.
    """
    folder = tmp_path / "run"
    folder.mkdir()
    _v3_store(folder / "overview_pos001.ome.zarr", shards=(1, 1, 4, 64, 64))
    server = make_server(port=0, data_dir=folder, store=["overview_pos001.ome.zarr"], live=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 900, "height": 700})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
        page.wait_for_function(
            """() => {
                 const v = window.zmartViewer;
                 let needed = 0, available = 0;
                 for (const m of v.layerManager.managedLayers)
                   for (const rl of (m.layer && m.layer.renderLayers) || []) {
                     const p = rl.layerChunkProgressInfo;
                     if (p) { needed += p.numVisibleChunksNeeded; available += p.numVisibleChunksAvailable; }
                   }
                 return available > 0 && available >= needed;
               }""",
            timeout=120_000,
        )
        errors = page.evaluate(
            """() => {
                 const out = [];
                 for (const m of window.zmartViewer.layerManager.managedLayers)
                   for (const ds of (m.layer && m.layer.dataSources) || [])
                     if (ds.loadState && ds.loadState.error) out.push(String(ds.loadState.error));
                 return out;
               }"""
        )
        assert errors == []
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)
