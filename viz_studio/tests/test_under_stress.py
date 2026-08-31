"""What the viewer does when the data is large, awkward, or being written to.

A mesoSPIM acquisition can be three or four hundred gigabytes, and the reason for
building on this engine at all is to see that in three dimensions while it is
still arriving. So the cases that matter are not the tidy ones. They are: an image
far too large to read through, a store caught half-written, a folder that
disappears, a request for something that was never imaged, and a great many
questions asked at once.

The rule for every test here is that the viewer must **answer** — correctly if it
can, honestly if it cannot — and never sit there. Each one is bounded in time, so
a stall shows up as a failure rather than as a test run that never ends.
"""

from __future__ import annotations

import concurrent.futures
import http.client
import json
import shutil
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import stores
import zarr
from library import Library
from server import make_server
from stores import axis_names, channels, is_store, written_timepoints

# Nothing here may take longer than this. The point of these tests is to catch
# something that stalls, so a generous ceiling is still a ceiling.
PATIENCE = 10.0


def write_store(path: Path, *, shape, chunks, axes, nested=False, fill=None, omero=None):
    """A real OME-Zarr, written exactly as asked — including badly."""
    path.mkdir(parents=True, exist_ok=True)
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    extra = {"chunk_key_encoding": {"name": "v2", "separator": "/"}} if nested else {}
    array = group.create_array("0", shape=shape, chunks=chunks, dtype="uint16", **extra)
    if fill is not None:
        array[fill] = 1234
    attrs = {
        "multiscales": [
            {
                "version": "0.4",
                "axes": [{"name": a} for a in axes],
                "datasets": [{"path": "0"}],
            }
        ]
    }
    if omero:
        attrs["omero"] = omero
    (path / ".zattrs").write_text(json.dumps(attrs), encoding="utf-8")
    return path


def request(port, path, method="GET", body=None, timeout=PATIENCE):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        headers = {"Content-Length": str(len(body))} if body is not None else {}
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


@pytest.fixture
def serving(tmp_path):
    """A running server over ``tmp_path``, with a helper to (re)start it."""
    running = []

    def start(store, **kwargs):
        site = tmp_path / "site"
        site.mkdir(exist_ok=True)
        (site / "index.html").write_text("x", encoding="utf-8")
        server = make_server(port=0, data_dir=tmp_path, site_dir=site, store=store, **kwargs)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        running.append((server, thread))
        return server.server_address[1]

    try:
        yield start
    finally:
        for server, thread in running:
            server.shutdown()
            thread.join(timeout=5)


# --------------------------------------------------------------------------
# Size: an image too large to read through
# --------------------------------------------------------------------------


class TestVeryLargeImages:
    """The cost of answering must not grow with the size of the acquisition."""

    def test_a_declared_but_barely_written_image_is_described_quickly(self, tmp_path, serving):
        """Declaring 400 GB and writing a corner of it must still answer at once."""
        # 200_000 x 200_000 x 64 x 2ch of 16-bit is far past 400 GB, declared.
        store = write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(2, 64, 200_000, 200_000),
            chunks=(1, 1, 256, 256),
            axes=("c", "z", "y", "x"),
            fill=(slice(None), slice(0, 1), slice(0, 256), slice(0, 256)),
        )
        started = time.monotonic()
        port = serving(store.name)
        status, body = request(port, "/api/config")
        elapsed = time.monotonic() - started
        assert status == 200
        assert len(json.loads(body)["layers"]) == 2
        assert elapsed < PATIENCE, f"describing a huge image took {elapsed:.1f}s"

    def test_counting_frames_is_one_glance_when_pieces_are_filed_in_folders(self, tmp_path):
        """The layout `DATA_LAYOUT.md` asks for makes this independent of size."""
        store = write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(6, 1, 2, 512, 512),
            chunks=(1, 1, 1, 256, 256),
            axes=("t", "c", "z", "y", "x"),
            nested=True,
            fill=(slice(0, 3),),
        )
        started = time.monotonic()
        assert written_timepoints(store) == 3
        assert time.monotonic() - started < 1.0

    def test_an_unreasonable_flat_folder_is_abandoned_rather_than_endured(self, tmp_path):
        """Millions of files in one folder cannot be counted; say so and move on.

        Answering "I do not know" lets the viewer fall back to the length the file
        claims. Sitting there reading three million names would freeze the panel.
        """
        store = write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(4, 1, 1, 256, 256),
            chunks=(1, 1, 1, 256, 256),
            axes=("t", "c", "z", "y", "x"),
            fill=(slice(0, 2),),
        )
        level = store / "0"
        # Stand in for a very large flat acquisition.
        for i in range(21_000):
            (level / f"0.0.0.{i}.0").write_bytes(b"")
        started = time.monotonic()
        answer = written_timepoints(store)
        elapsed = time.monotonic() - started
        assert answer is None, "expected the count to be abandoned, not guessed"
        assert elapsed < PATIENCE, f"gave up only after {elapsed:.1f}s"

    def test_a_folder_given_up_on_is_not_counted_again(self, tmp_path, monkeypatch):
        """Having given up once on a huge folder, the viewer does not try again.

        A run writes a piece every few seconds, so the folder's modification time
        is always moving and a fresh look would be taken on every refresh. Since a
        folder that large will never become small again, the verdict is kept.

        To watch that happen without writing millions of files, the limit is turned
        right down and the folder is then made small again. Real data cannot shrink
        like this; the shrinking is only here so that a second count, if one were
        taken, would give a different answer and so be visible.
        """
        monkeypatch.setattr(stores, "_SCAN_LIMIT", 5)
        store = write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(4, 1, 1, 256, 256),
            chunks=(1, 1, 1, 256, 256),
            axes=("t", "c", "z", "y", "x"),
            fill=(slice(0, 2),),
        )
        level = store / "0"
        for i in range(20):
            (level / f"0.0.0.{i}.0").write_bytes(b"")
        assert written_timepoints(store) is None

        for i in range(3, 20):
            (level / f"0.0.0.{i}.0").unlink()
        assert written_timepoints(store) is None, "counted again a folder it had abandoned"

    def test_a_store_looked_at_before_its_first_frame_is_asked_again(self, tmp_path):
        """"Nothing yet" is an answer about this moment, not about the run.

        The viewer meets a store at whatever moment the operator happens to open
        the folder, and during a live run that is often before the first frame has
        landed. Answering "nothing has been written" is right at that moment and
        wrong a few seconds later, so it must not be the answer the viewer keeps.
        Were it kept, the time slider would offer no frames at all for the rest of
        the session, however long the run went on.
        """
        store = write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(4, 1, 1, 256, 256),
            chunks=(1, 1, 1, 256, 256),
            axes=("t", "c", "z", "y", "x"),
            nested=True,
        )
        assert written_timepoints(store) is None, "an empty store has no frames yet"

        # The run produces its first frame.
        zarr.open_array(str(store / "0"), mode="r+")[0] = 1234
        assert written_timepoints(store) == 1, "the store was still thought to be empty"

    def test_asking_twice_costs_nothing_the_second_time(self, tmp_path):
        store = write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(4, 1, 1, 512, 512),
            chunks=(1, 1, 1, 256, 256),
            axes=("t", "c", "z", "y", "x"),
            nested=True,
            fill=(slice(0, 2),),
        )
        written_timepoints(store)
        started = time.monotonic()
        for _ in range(200):
            written_timepoints(store)
        assert time.monotonic() - started < 1.0


# --------------------------------------------------------------------------
# Honesty: what the frame count is allowed to claim
# --------------------------------------------------------------------------


class TestHowFarTheDataReaches:
    """What the frame count is allowed to claim, and the ways it could be wrong.

    The whole reason a timelapse may declare room for ten thousand moments and
    fill them in as it goes is that ``written_timepoints`` says how far the images
    on disk actually reach, and the viewer stops the time slider there. That is
    only safe if the number can be trusted in both directions.

    Reaching too far is the worse of the two failures. The operator lands on a
    moment that was never imaged, the drawing engine notes "there is nothing here"
    and does not look again, and that moment stays blank for the rest of the
    session even after the microscope has written it. Not reaching far enough is
    milder but still bad: data that is sitting on disk and perfectly readable
    cannot be got to, and nothing on screen explains why.

    So the number is one past the furthest moment that holds an image: far enough
    to reach everything, and no further. A moment in the middle with nothing in it
    is offered as well and draws empty, which is the truth about it. ``None`` means
    there is nothing to stop the slider at, and the viewer then limits nothing.
    """

    def test_the_furthest_moment_on_disk_is_where_the_slider_stops(self, tmp_path):
        """The ordinary case: five moments imaged in order, so the slider offers five."""
        store = write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(10, 1, 1, 64, 64),
            chunks=(1, 1, 1, 64, 64),
            axes=("t", "c", "z", "y", "x"),
            nested=True,
            fill=(slice(0, 5),),
        )
        answer = written_timepoints(store)
        assert answer == 5
        # Nothing on disk lies beyond where the slider would stop.
        assert not (store / "0" / str(answer)).exists()

    def test_running_a_second_experiment_into_the_same_folder_starts_over(self, tmp_path):
        """A shorter re-run must not be described with the first run's length.

        Pointing a second experiment at a folder that already held one is an
        ordinary thing to do, and the viewer may well have been left open across
        it. If it keeps the longer count from the run before, the operator is
        offered moments this experiment never imaged.
        """
        path = tmp_path / "overview_pos001.ome.zarr"
        write_store(
            path,
            shape=(10, 1, 1, 64, 64),
            chunks=(1, 1, 1, 64, 64),
            axes=("t", "c", "z", "y", "x"),
            nested=True,
            fill=(slice(0, 5),),
        )
        assert written_timepoints(path) == 5

        # The same folder is cleared away and a second, shorter run writes into it.
        shutil.rmtree(path)
        write_store(
            path,
            shape=(10, 1, 1, 64, 64),
            chunks=(1, 1, 1, 64, 64),
            axes=("t", "c", "z", "y", "x"),
            nested=True,
            fill=(slice(0, 2),),
        )
        assert written_timepoints(path) == 2, "the first run's length was still being claimed"

    def test_a_moment_beyond_a_gap_stays_reachable(self, tmp_path):
        """Moment 7 exists and is readable, so the slider has to reach it.

        Stopping at 1 — the last moment before the first gap — would be safe in the
        narrow sense that moment 0 really is there, but it would put moment 7 out of
        reach with nothing on screen to say it had ever been imaged. Reaching as far
        as the data does costs a few empty moments in between and hides nothing.
        """
        store = write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(10, 1, 1, 64, 64),
            chunks=(1, 1, 1, 64, 64),
            axes=("t", "c", "z", "y", "x"),
            nested=True,
        )
        array = zarr.open_array(str(store / "0"), mode="r+")
        array[0] = 1234
        array[7] = 1234
        assert written_timepoints(store) == 8, "a moment past the gap was put out of reach"

    def test_a_black_frame_does_not_hide_everything_after_it(self, tmp_path):
        """A bleached or failed acquisition leaves a hole, and it is not rare.

        Zarr does not write a piece of image that holds nothing but the fill value,
        so a frame that came out entirely black is stored as no frame at all. An
        otherwise perfectly ordinary timelapse therefore ends up with a gap in the
        middle of it, and stopping the slider at that gap would hide the moments
        after it — which were imaged, and are sitting there readable.
        """
        store = write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(10, 1, 1, 64, 64),
            chunks=(1, 1, 1, 64, 64),
            axes=("t", "c", "z", "y", "x"),
            nested=True,
        )
        array = zarr.open_array(str(store / "0"), mode="r+")
        for moment in range(7):
            array[moment] = 0 if moment == 3 else 1234
        assert not (store / "0" / "3").exists(), "the all-black frame was written after all"
        assert written_timepoints(store) == 7, "moments 4, 5 and 6 were hidden"

    @pytest.mark.parametrize("nested", [True, False])
    def test_a_canvas_imaged_at_chosen_moments_reaches_its_furthest_one(self, tmp_path, nested):
        """One moment imaged far along, and the answer says so rather than hedging.

        A target-scan workflow images its canvas at the moments it decides on rather
        than at every moment in turn, so this is normal data and not a broken store.
        The store may declare room for a thousand moments while holding one.

        Answering 901 does offer 900 moments that were never imaged, and that is a
        real cost rather than a technicality. It is still the smallest number that
        reaches the image. The tempting alternative is to answer ``None`` — to say
        "I cannot put a sensible number on this" — and this test is here to record
        why that turns out to be worse. ``None`` means "do not limit the slider at
        all", so the operator would be offered all one thousand declared moments
        instead of 901. It would also leave the answer at ``None`` however much the
        run went on, and it is a *change* in this number that tells the viewer a
        store has grown and is worth reading again, so new frames would go unnoticed
        as well.
        """
        store = write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(1000, 1, 1, 64, 64),
            chunks=(1, 1, 1, 64, 64),
            axes=("t", "c", "z", "y", "x"),
            nested=nested,
        )
        zarr.open_array(str(store / "0"), mode="r+")[900] = 1234
        assert written_timepoints(store) == 901

    def test_a_backfilled_moment_does_not_move_the_reach(self, tmp_path):
        """Filling in an earlier moment leaves the answer where it was, and that is a gap.

        This is not a defect in the reach itself — 901 was right before the backfill
        and is still right after it. It is recorded here because the viewer uses this
        same number for a second job it was never designed for: an unchanged count is
        how the page decides a store has *not* grown and need not be read again. So a
        moment filled in behind the furthest one is written to disk without anything
        telling the page to look, and if the operator had already visited it the
        drawing engine will still believe it empty.

        Reaching further is not the fix for that; a separate signal that changes on
        any write is. Pinned so the next person to touch this knows the limitation is
        known rather than overlooked.
        """
        store = write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(1000, 1, 1, 64, 64),
            chunks=(1, 1, 1, 64, 64),
            axes=("t", "c", "z", "y", "x"),
            nested=True,
        )
        array = zarr.open_array(str(store / "0"), mode="r+")
        array[900] = 1234
        assert written_timepoints(store) == 901
        array[500] = 1234
        assert written_timepoints(store) == 901

    def test_closing_a_store_lets_go_of_its_frame_count(self, tmp_path):
        """Whatever counting remembers has to be given back when the store is closed.

        The count is kept so that asking again costs one cheap look rather than a
        reading of the folder. Nothing expires it on its own, so an operator working
        through one folder after another would otherwise accumulate a count for
        every folder they had ever opened.
        """
        import stores as stores_module

        store = write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(10, 1, 1, 64, 64),
            chunks=(1, 1, 1, 64, 64),
            axes=("t", "c", "z", "y", "x"),
            nested=True,
            fill=(slice(0, 3),),
        )
        # A count taken while the moments folder is still within the clock's
        # reach of "now" is deliberately not remembered (see
        # _MTIME_STILL_MOVING_NS), and this test is about the remembering — so
        # the freshly written store ages past that reach first.
        time.sleep(stores_module._MTIME_STILL_MOVING_NS / 1e9 + 0.02)
        assert written_timepoints(store) == 3
        assert any(key.startswith(str(store)) for key in stores_module._frame_counts)

        stores_module.forget(store)
        assert not any(key.startswith(str(store)) for key in stores_module._frame_counts)
        # And the answer is simply worked out again, unchanged.
        assert written_timepoints(store) == 3

    def test_closing_a_store_lets_go_of_what_its_array_said_too(self, tmp_path):
        """Counting reads a second small file, and that is remembered as well.

        How the pieces of an image are named, and how much of the timelapse one of
        them holds, are read from the array's own description — a few hundred bytes
        beside the pieces. It is remembered for the same reason everything else here
        is, and it has to be given back for the same reason too: closing a folder
        should return the memory it was using, or "close what you are not using" is
        advice the viewer does not honour.
        """
        import stores as stores_module

        store = write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(10, 1, 1, 64, 64),
            chunks=(1, 1, 1, 64, 64),
            axes=("t", "c", "z", "y", "x"),
            nested=True,
            fill=(slice(0, 3),),
        )
        assert written_timepoints(store) == 3
        assert any(key.startswith(str(store)) for key in stores_module._array_cache)

        stores_module.forget(store)
        assert not any(key.startswith(str(store)) for key in stores_module._array_cache)
        assert written_timepoints(store) == 3


# --------------------------------------------------------------------------
# Damage: stores caught half-written, or malformed
# --------------------------------------------------------------------------


class TestHalfWrittenAndBroken:
    """During a live run the viewer will meet stores that are not finished."""

    def test_a_store_with_no_description_yet_is_not_mistaken_for_an_image(self, tmp_path):
        half = tmp_path / "overview_pos001.ome.zarr"
        half.mkdir()
        assert is_store(half) is False

    def test_a_truncated_description_does_not_raise(self, tmp_path):
        half = tmp_path / "overview_pos001.ome.zarr"
        half.mkdir()
        # A file caught mid-write: valid JSON up to the point it stops.
        (half / ".zattrs").write_text('{"multiscales": [{"axes": [{"na', encoding="utf-8")
        assert is_store(half) is False
        assert axis_names(half) == []
        assert len(channels(half)) == 1
        assert written_timepoints(half) is None

    # Five ways a description can be wrong while still being valid JSON, and the
    # axes each one leaves genuinely readable. A file caught mid-write gives the
    # first sort of damage; a foreign instrument or a hand-edited description gives
    # the rest, and all of them turn up in practice.
    #
    # What each case is expected to *answer* is written down, because "reading it
    # did not raise" is not the property that matters. A reader that quietly
    # returned nothing at all would satisfy that, and returning nothing here is not
    # a small loss: a store described as having no channels gets no row in the
    # panel, so the acquisition simply disappears from the viewer with nothing on
    # screen to explain where it went. That is the failure this is really guarding
    # against, and only an expectation can catch it.
    _MALFORMED = {
        "multiscales is null rather than a list": (
            '{"multiscales": null}', []),
        "the axes and datasets are both null": (
            '{"multiscales": [{"axes": null, "datasets": null}]}', []),
        "the axes are bare numbers rather than named entries": (
            '{"multiscales": [{"axes": [1, 2, 3]}]}', []),
        "the omero channels are a string rather than a list": (
            '{"multiscales": [{}], "omero": {"channels": "not a list"}}', []),
        "a dataset with no path, so the array cannot be found": (
            '{"multiscales": [{"axes": [{"name": "c"}], "datasets": [{"path": null}]}]}',
            ["c"]),
    }

    @pytest.mark.parametrize(
        ("attrs", "axes"), list(_MALFORMED.values()), ids=list(_MALFORMED)
    )
    def test_nonsense_metadata_is_survived(self, tmp_path, attrs, axes):
        """Whatever is in the file, the viewer gives a safe answer rather than falling over.

        Surviving is the least of it. Each of these has a right answer, and the
        right answer is always the cautious one: report what the file really says,
        claim nothing it does not, and never let a damaged description cost the
        operator the acquisition.
        """
        store = tmp_path / "overview_pos001.ome.zarr"
        store.mkdir(exist_ok=True)
        (store / ".zattrs").write_text(attrs, encoding="utf-8")

        # Only the axes the file genuinely names. Inventing one would put a slider
        # on screen for a dimension the image does not have; dropping one that is
        # named would hide a dimension it does. The last case names a channel axis
        # and nothing else, so that is exactly what comes back.
        assert axis_names(store) == axes, (
            "a damaged description was read as declaring axes it does not"
        )

        # There is still exactly one row in the panel, named after the file and
        # left greyscale. Named after the file because that is genuinely all we
        # know about this store, and greyscale because nothing in it told us a
        # colour. One row rather than none is the part that matters: the operator
        # can still see the acquisition and look at it.
        found = channels(store)
        assert len(found) == 1, (
            f"a damaged description produced {len(found)} rows in the panel rather "
            "than the one row that keeps the acquisition visible"
        )
        assert found[0]["name"] == "overview_pos001"
        assert found[0]["color"] is None

        # And nothing pretends to know how far a timelapse has got. ``None`` means
        # "put no limit on the time slider", which is the honest answer when the
        # description cannot be read — a guessed number would either hide moments
        # that exist or offer moments that never will.
        assert written_timepoints(store) is None, (
            "a length was claimed for a store whose description cannot be read"
        )

    def test_the_config_survives_a_folder_of_rubbish(self, tmp_path, serving):
        good = write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(1, 2, 64, 64), chunks=(1, 1, 64, 64), axes=("c", "z", "y", "x"),
            fill=(slice(None),),
        )
        broken = tmp_path / "overview_pos002.ome.zarr"
        broken.mkdir()
        (broken / ".zattrs").write_text("{ not json at all", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")

        port = serving([good.name, broken.name])
        status, body = request(port, "/api/config")
        assert status == 200
        # The good store is still described; the broken one does not stop it.
        # Asked of the sources rather than of the group heading, because what is
        # being tested is that the readable store survived its neighbour — not what
        # the dataset it landed in happens to be called.
        served = [source for row in json.loads(body)["layers"] for source in row["sources"]]
        assert any(good.name in source for source in served), served


# --------------------------------------------------------------------------
# Absence: asking for what was never imaged
# --------------------------------------------------------------------------


class TestSparseAndMissing:
    """Most of a live acquisition has not been imaged yet. That is normal."""

    def test_a_piece_that_was_never_imaged_answers_at_once(self, tmp_path, serving):
        store = write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(1, 1, 4096, 4096), chunks=(1, 1, 256, 256), axes=("c", "z", "y", "x"),
            fill=(slice(None), slice(None), slice(0, 256), slice(0, 256)),
        )
        port = serving(store.name)
        started = time.monotonic()
        for index in range(60):
            status, _ = request(port, f"/data/0/{store.name}/0/0.0.{index}.15")
            assert status == 404, "an unimaged piece must read as empty, not as an error"
        elapsed = time.monotonic() - started
        assert elapsed < PATIENCE, f"60 misses took {elapsed:.1f}s"

    def test_a_folder_that_vanishes_does_not_take_the_viewer_with_it(self, tmp_path, serving):
        store = write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(1, 2, 64, 64), chunks=(1, 1, 64, 64), axes=("c", "z", "y", "x"),
            fill=(slice(None),),
        )
        port = serving(store.name)
        assert request(port, "/api/config")[0] == 200
        import shutil

        shutil.rmtree(store)
        status, body = request(port, "/api/config")
        assert status == 200, "the viewer must still answer once the data has gone"
        assert request(port, "/api/announce", method="POST", body=b"{}")[0] == 200


# --------------------------------------------------------------------------
# Pressure: many questions at once
# --------------------------------------------------------------------------


class TestManyAtOnce:
    """The engine asks for a great many pieces in parallel. So do these."""

    def test_a_hundred_pieces_asked_for_together(self, tmp_path, serving):
        store = write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(1, 1, 2048, 2048), chunks=(1, 1, 256, 256), axes=("c", "z", "y", "x"),
            fill=(slice(None),),
        )
        port = serving(store.name)
        started = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
            answers = list(
                pool.map(
                    lambda i: request(port, f"/data/0/{store.name}/0/0.0.{i % 8}.{i // 8 % 8}")[0],
                    range(100),
                )
            )
        elapsed = time.monotonic() - started
        assert all(status == 200 for status in answers)
        assert elapsed < PATIENCE, f"100 parallel reads took {elapsed:.1f}s"

    def test_announcing_stays_cheap_under_repetition(self, tmp_path, serving):
        """A run announcing steadily must cost the server almost nothing.

        Announcements arrive at the rate acquisitions finish, so a hundred of them
        is already far more than a real run produces in a minute. They must not
        become the expensive part: an announcement only nudges whoever is
        listening, and does no reading of its own.
        """
        for i in range(20):
            write_store(
                tmp_path / f"overview_pos{i:03d}.ome.zarr",
                shape=(1, 1, 64, 64), chunks=(1, 1, 64, 64), axes=("c", "z", "y", "x"),
                fill=(slice(None),),
            )
        port = serving(sorted(p.name for p in tmp_path.glob("*.ome.zarr")))
        request(port, "/api/announce", method="POST", body=b"{}")
        started = time.monotonic()
        for _ in range(100):
            assert request(port, "/api/announce", method="POST", body=b"{}")[0] == 200
        elapsed = time.monotonic() - started
        assert elapsed < 5.0, f"100 announcements took {elapsed:.1f}s"

    def _cache_header(self, port, path: str) -> str | None:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=PATIENCE)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            response.read()
            return response.getheader("Cache-Control")
        finally:
            conn.close()

    def _reply_to(self, port, path: str) -> tuple[int, dict[str, str]]:
        """The status and every header the server answers a plain GET with.

        More than the one header, because whether a browser may keep something is
        not settled by ``Cache-Control`` on its own. Handed a last-modified time or
        an expiry instead, a browser will work out a lifetime for itself and stop
        asking — so a test about what may be kept has to be able to see all of
        them, not just the obvious one. The names are lowered because HTTP does not
        care about their case and a test should not either.
        """
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=PATIENCE)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            response.read()
            return response.status, {
                name.lower(): value for name, value in response.getheaders()
            }
        finally:
            conn.close()

    def _one_written_piece(self, tmp_path):
        return write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(1, 1, 512, 512), chunks=(1, 1, 256, 256), axes=("c", "z", "y", "x"),
            fill=(slice(None),),
        )

    def test_nothing_is_kept_while_the_instrument_is_still_writing(self, tmp_path, serving):
        """During a run the browser must hold no copy of the image.

        Nothing on disk is settled while an acquisition is in progress, and a copy
        held in the browser would go on showing an old version of a region with
        nothing on screen to say so. Live is the default, so this is what an
        experiment gets without anyone having to ask for it.
        """
        store = self._one_written_piece(tmp_path)
        port = serving(store.name)
        assert self._cache_header(port, f"/data/0/{store.name}/0/0.0.0.0") == "no-store"

    def test_pieces_are_kept_once_the_run_is_finished(self, tmp_path, serving):
        """Moving back over an old run must be free.

        Nothing is writing, so nothing can change, and there is no reason to fetch
        a region twice. Parsed loosely, so the exact spelling of the header is not
        what this test is about.
        """
        store = self._one_written_piece(tmp_path)
        port = serving(store.name, live=False)
        cache = self._cache_header(port, f"/data/0/{store.name}/0/0.0.0.0")
        assert "immutable" in cache, cache
        assert int(cache.split("max-age=")[1].split(",")[0]) > 86_400, cache

    def test_a_piece_not_yet_written_is_never_kept(self, tmp_path, serving):
        """Data arriving later must still be found.

        Most of a sparse or half-finished acquisition answers "nothing here", and
        that answer must not be kept by anyone — otherwise a region imaged five
        minutes from now would go on reading as empty, and the operator would be
        looking at a hole in their data with nothing on screen to say it had since
        been filled in.

        Checked in the finished mode, which is the only one that lets the browser
        keep anything at all. That is what gives the check its meaning: the written
        piece next door in this very same server is handed over with permission to
        keep it for a year, so a missing piece coming back without that permission
        is a decision about the missing piece rather than about the mode the server
        happens to be running in.
        """
        store = self._one_written_piece(tmp_path)
        port = serving(store.name, live=False)

        # The contrast first, so the absence below can be attributed to something.
        # This is the keeping mode, and a piece that does exist is indeed offered
        # to be kept.
        status, headers = self._reply_to(port, f"/data/0/{store.name}/0/0.0.0.0")
        assert status == 200
        assert "immutable" in headers.get("cache-control", ""), headers

        status, headers = self._reply_to(port, f"/data/0/{store.name}/0/9.9.9.9")
        # A piece that was never imaged is the ordinary case rather than an error,
        # and it is answered plainly and briefly. Worth asserting, because a reply
        # that never reached this part of the server at all would also come back
        # without permission to keep anything, and would prove nothing.
        assert status == 404, f"expected the ordinary empty answer, got {status}"
        assert headers.get("content-length") == "0", headers

        # Nothing offers to keep it — and, just as importantly, nothing lets the
        # browser decide for itself how long to keep it. That second half is worth
        # spelling out: an empty answer is one a browser is allowed to hold on to,
        # and handed a last-modified time or an expiry it will work out a lifetime
        # of its own and stop asking. So what is asserted is that the reply carries
        # none of the four things it could do that with.
        for keepable in ("cache-control", "expires", "last-modified", "etag"):
            assert keepable not in headers, (
                f"the empty answer carries {keepable!r}, which a browser can use to "
                f"go on believing a region is empty after it has been imaged: {headers}"
            )


# --------------------------------------------------------------------------
# The guard, pushed harder
# --------------------------------------------------------------------------


class TestTheGuardUnderAttack:
    """Whatever is asked for, only files inside an open folder may be read."""

    @pytest.mark.parametrize(
        "attack",
        [
            "0/../../../../etc/passwd",
            "0/%2e%2e/%2e%2e/etc/passwd",
            "0/....//....//etc/passwd",
            "0//etc/passwd",
            "../0/x",
            "999999999999999999999/x",
            "-1/x",
            "0/" + "a/" * 200 + "x",
        ],
    )
    def test_nothing_outside_an_open_folder_is_reachable(self, tmp_path, attack):
        write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(1, 1, 8, 8), chunks=(1, 1, 8, 8), axes=("c", "z", "y", "x"),
            fill=(slice(None),),
        )
        library = Library()
        library.open(tmp_path)
        target = library.resolve(attack)
        assert target is None or tmp_path.resolve() in target.parents

    def test_a_symbolic_link_out_of_the_folder_is_refused(self, tmp_path):
        secret = tmp_path / "secret.txt"
        secret.write_text("not yours", encoding="utf-8")
        folder = tmp_path / "run"
        folder.mkdir()
        write_store(
            folder / "overview_pos001.ome.zarr",
            shape=(1, 1, 8, 8), chunks=(1, 1, 8, 8), axes=("c", "z", "y", "x"),
            fill=(slice(None),),
        )
        try:
            (folder / "escape").symlink_to(secret)
        except (OSError, NotImplementedError):
            pytest.skip("symbolic links are not available here")
        library = Library()
        library.open(folder)
        assert library.resolve("0/escape") is None


# --------------------------------------------------------------------------
# Saved targets, pushed harder
# --------------------------------------------------------------------------


class TestSavingUnderStress:
    def test_a_very_large_target_list_is_refused_rather_than_swallowed(self, tmp_path, serving):
        write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(1, 1, 8, 8), chunks=(1, 1, 8, 8), axes=("c", "z", "y", "x"),
            fill=(slice(None),),
        )
        port = serving("overview_pos001.ome.zarr")
        document = {
            "version": 1,
            "annotations": [
                {"id": f"t{i}", "type": "point", "point": [1.0, 2.0, 3.0], "description": ""}
                for i in range(10_001)
            ],
        }
        status, _ = request(port, "/api/annotations", "POST", json.dumps(document).encode())
        assert status == 400

    def test_saving_from_several_places_at_once_leaves_a_readable_file(self, tmp_path, serving):
        """Two saves racing must not leave a half-written file behind."""
        write_store(
            tmp_path / "overview_pos001.ome.zarr",
            shape=(1, 1, 8, 8), chunks=(1, 1, 8, 8), axes=("c", "z", "y", "x"),
            fill=(slice(None),),
        )
        port = serving("overview_pos001.ome.zarr")

        def save(n):
            document = {
                "version": 1,
                "annotations": [
                    {"id": f"t{n}-{i}", "type": "point", "point": [float(i), 0.0, 0.0],
                     "description": "x" * 200}
                    for i in range(200)
                ],
            }
            return request(port, "/api/annotations", "POST", json.dumps(document).encode())[0]

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            assert all(status == 200 for status in pool.map(save, range(16)))

        status, body = request(port, "/api/annotations")
        assert status == 200
        # Whichever save landed last, the file is complete and readable.
        assert len(json.loads(body)["annotations"]) == 200
