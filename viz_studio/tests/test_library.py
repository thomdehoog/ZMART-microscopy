"""Opening and closing images while the viewer is running.

An operator wants to add to what is on screen — last week's run for comparison, a
second overview, a colleague's data from another drive — and to close things again
once they have been looked at. These tests cover that, and cover the guard that
comes with it: a viewer that could be talked into reading any file on the machine
would be a poor thing to leave running next to a microscope.
"""

from __future__ import annotations

import http.client
import json
import os
import threading

import numpy as np
import pytest
import zarr
from library import Library
from server import make_server


def _tiny_store(path):
    """A real but minimal OME-Zarr: enough to be found and read, quick to write.

    These tests are about which folders are open and which files may be read
    rather than about image content, so building a full demo volume for each of
    them would only make them slow.
    """
    path.mkdir(parents=True)
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    data = np.full((4, 32, 32), 2000, dtype=np.uint16)
    group.create_array("0", shape=data.shape, chunks=(1, 32, 32), dtype="uint16")[:] = data
    (path / ".zattrs").write_text(
        json.dumps(
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [{"name": a} for a in ("z", "y", "x")],
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": [2.0, 0.35, 0.35]}
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


@pytest.fixture
def two_runs(tmp_path):
    """Two separate folders, each holding one acquisition, as two runs would be."""
    # A folder holds one acquisition and is named after it: the load names the
    # dataset, so this is what the panel and the close-by-name API both use.
    monday = tmp_path / "overview"
    friday = tmp_path / "targetscan"
    monday.mkdir()
    friday.mkdir()
    _tiny_store(monday / "overview.ome.zarr")
    _tiny_store(friday / "targetscan_cell007.ome.zarr")
    (tmp_path / "secret.txt").write_text("not an image", encoding="utf-8")
    return monday, friday, tmp_path


class TestOpeningFolders:
    """Each opened folder gets its own number, and both stay readable."""

    def test_two_folders_can_be_open_at_once(self, two_runs):
        monday, friday, _ = two_runs
        library = Library()
        first = library.open(monday)
        second = library.open(friday)
        assert first != second
        names = [name for _, _, name in library.entries()]
        assert names == ["overview.ome.zarr", "targetscan_cell007.ome.zarr"]

    def test_a_single_store_can_be_opened_directly(self, two_runs):
        """An operator should not have to know whether they picked a store or a folder."""
        monday, _, _ = two_runs
        library = Library()
        library.open(monday / "overview.ome.zarr")
        assert [name for _, _, name in library.entries()] == ["overview.ome.zarr"]

    def test_a_folder_with_no_images_says_so_helpfully(self, two_runs):
        """The ordinary mistake is picking one level too high, so say that."""
        _, _, parent = two_runs
        library = Library()
        # The parent holds run folders, not stores.
        with pytest.raises(ValueError, match="one level down"):
            library.open(parent)

    def test_a_missing_folder_is_reported_plainly(self, tmp_path):
        library = Library()
        with pytest.raises(FileNotFoundError, match="no folder at"):
            library.open(tmp_path / "nowhere")

    def test_a_file_is_not_a_folder_of_images(self, two_runs):
        _, _, parent = two_runs
        library = Library()
        with pytest.raises(ValueError, match="not a folder"):
            library.open(parent / "secret.txt")


class TestClosing:
    """Closing is by dataset, because that is the unit on screen."""

    def test_closing_an_acquisition_removes_it(self, two_runs):
        monday, friday, _ = two_runs
        library = Library()
        library.open(monday)
        library.open(friday)
        library.close_group("targetscan")
        assert [name for _, _, name in library.entries()] == ["overview.ome.zarr"]

    def test_closing_the_last_one_empties_the_library(self, two_runs):
        monday, _, _ = two_runs
        library = Library()
        library.open(monday)
        library.close_group("overview")
        assert library.is_empty()

    def test_closing_something_that_is_not_open_is_harmless(self, two_runs):
        monday, _, _ = two_runs
        library = Library()
        library.open(monday)
        library.close_group("nothing-like-this")
        assert not library.is_empty()

    def test_a_closed_folder_number_is_never_reused(self, two_runs):
        """A chunk still in flight must not land on whatever was opened next."""
        monday, friday, _ = two_runs
        library = Library()
        first = library.open(monday)
        library.close(first)
        second = library.open(friday)
        assert second != first


class TestTheGuard:
    """Only files inside an opened folder may be read, whatever the request says."""

    def test_a_file_inside_an_open_folder_resolves(self, two_runs):
        monday, _, _ = two_runs
        library = Library()
        number = library.open(monday)
        target = library.resolve(f"{number}/overview.ome.zarr/.zattrs")
        assert target is not None and target.is_file()

    @pytest.mark.parametrize(
        "attack",
        [
            "0/../secret.txt",
            "0/../../secret.txt",
            "0/overview.ome.zarr/../../secret.txt",
        ],
    )
    def test_climbing_out_of_the_folder_is_refused(self, two_runs, attack):
        monday, _, _ = two_runs
        library = Library()
        library.open(monday)
        assert library.resolve(attack) is None

    def test_a_folder_that_is_not_open_is_refused(self, two_runs):
        monday, _, _ = two_runs
        library = Library()
        library.open(monday)
        assert library.resolve("7/overview.ome.zarr/.zattrs") is None

    def test_a_closed_folder_stops_being_readable(self, two_runs):
        monday, _, _ = two_runs
        library = Library()
        number = library.open(monday)
        assert library.resolve(f"{number}/overview.ome.zarr/.zattrs") is not None
        library.close(number)
        assert library.resolve(f"{number}/overview.ome.zarr/.zattrs") is None

    @pytest.mark.parametrize("nonsense", ["", "abc/x", "0", "/", "notanumber/store/x"])
    def test_a_malformed_request_is_refused(self, two_runs, nonsense):
        monday, _, _ = two_runs
        library = Library()
        library.open(monday)
        assert library.resolve(nonsense) is None


# --- the endpoints the interface uses ---------------------------------------


def _post(port, route, body):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        raw = json.dumps(body).encode()
        conn.request("POST", route, body=raw, headers={"Content-Length": str(len(raw))})
        response = conn.getresponse()
        return response.status, json.loads(response.read() or b"{}")
    finally:
        conn.close()


@pytest.fixture
def serving_two_runs(two_runs):
    monday, friday, parent = two_runs
    site = parent / "site"
    site.mkdir()
    (site / "index.html").write_text("x", encoding="utf-8")
    server = make_server(port=0, data_dir=monday, site_dir=site, store="overview.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], friday
    finally:
        server.shutdown()
        thread.join(timeout=5)


class TestOpeningThroughTheApi:
    def test_opening_a_folder_adds_its_acquisition(self, serving_two_runs):
        port, friday = serving_two_runs
        status, config = _post(port, "/api/stores/open", {"path": str(friday)})
        assert status == 200
        assert config["groups"] == ["overview", "targetscan"]

    def test_the_new_images_become_readable(self, serving_two_runs):
        """Opening must also grant permission to read the files, or nothing shows."""
        port, friday = serving_two_runs
        _, config = _post(port, "/api/stores/open", {"path": str(friday)})
        added = [row for row in config["layers"] if row["group"] == "targetscan"][0]
        # The source address points at the newly opened folder by its number.
        prefix = added["sources"][0].removesuffix("|zarr2:")
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
        conn.request("GET", f"{prefix}.zattrs")
        assert conn.getresponse().status == 200
        conn.close()

    def test_a_folder_with_nothing_in_it_is_refused_with_a_reason(self, serving_two_runs, tmp_path):
        port, _ = serving_two_runs
        empty = tmp_path / "empty"
        empty.mkdir()
        status, answer = _post(port, "/api/stores/open", {"path": str(empty)})
        assert status == 400
        assert "no OME-Zarr image" in answer["error"]

    def test_a_missing_folder_answers_not_found(self, serving_two_runs, tmp_path):
        port, _ = serving_two_runs
        status, answer = _post(port, "/api/stores/open", {"path": str(tmp_path / "nope")})
        assert status == 404
        assert "no folder at" in answer["error"]

    def test_an_empty_request_is_refused(self, serving_two_runs):
        port, _ = serving_two_runs
        status, _ = _post(port, "/api/stores/open", {})
        assert status == 400


class TestClosingThroughTheApi:
    def test_closing_removes_the_acquisition_from_the_answer(self, serving_two_runs):
        port, friday = serving_two_runs
        _post(port, "/api/stores/open", {"path": str(friday)})
        status, config = _post(port, "/api/stores/close", {"group": "targetscan"})
        assert status == 200
        assert config["groups"] == ["overview"]

    def test_closed_images_stop_being_readable(self, serving_two_runs):
        """Closing has to withdraw permission too, not merely stop showing it."""
        port, friday = serving_two_runs
        _, config = _post(port, "/api/stores/open", {"path": str(friday)})
        added = [row for row in config["layers"] if row["group"] == "targetscan"][0]
        prefix = added["sources"][0].removesuffix("|zarr2:")
        _post(port, "/api/stores/close", {"group": "targetscan"})
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
        conn.request("GET", f"{prefix}.zattrs")
        assert conn.getresponse().status == 403
        conn.close()

    def test_closing_without_saying_what_is_refused(self, serving_two_runs):
        port, _ = serving_two_runs
        status, _ = _post(port, "/api/stores/close", {})
        assert status == 400


class TestChoosingAFolder:
    def test_without_a_desktop_window_it_explains_itself(self, serving_two_runs):
        """A browser tab cannot open a folder chooser, and should say so."""
        port, _ = serving_two_runs
        status, answer = _post(port, "/api/browse", {})
        assert status == 501
        assert "type or paste" in answer["reason"]

    def test_with_a_chooser_it_returns_the_chosen_folder(self, two_runs):
        monday, friday, parent = two_runs
        site = parent / "site"
        site.mkdir()
        (site / "index.html").write_text("x", encoding="utf-8")
        server = make_server(
            port=0,
            data_dir=monday,
            site_dir=site,
            store="overview.ome.zarr",
            browse=lambda: str(friday),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, answer = _post(server.server_address[1], "/api/browse", {})
        finally:
            server.shutdown()
            thread.join(timeout=5)
        assert status == 200
        assert answer["path"] == str(friday)

    def test_pressing_cancel_is_an_ordinary_outcome(self, two_runs):
        monday, _, parent = two_runs
        site = parent / "site"
        site.mkdir()
        (site / "index.html").write_text("x", encoding="utf-8")
        server = make_server(
            port=0,
            data_dir=monday,
            site_dir=site,
            store="overview.ome.zarr",
            browse=lambda: None,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, answer = _post(server.server_address[1], "/api/browse", {})
        finally:
            server.shutdown()
            thread.join(timeout=5)
        assert status == 200
        assert answer["cancelled"] is True


class TestNoticingThatSomethingChanged:
    """The cheap question the viewer asks several times a second.

    Reading every store's description is far too heavy to repeat that often, so
    the viewer asks a much smaller question instead — one that only says whether
    anything has moved — and asks the expensive one when the answer changes.

    Everything below is about one failure mode, because it is the one that
    actually happened and it is nasty: if the answer stops moving while an
    acquisition is still becoming readable, the viewer settles down and never
    looks again. The acquisition then stays invisible for the rest of the session
    and nothing anywhere reports a problem.
    """

    def test_it_moves_when_a_new_acquisition_appears(self, tmp_path):
        library = Library()
        _tiny_store(tmp_path / "overview_pos001.ome.zarr")
        library.open(tmp_path)
        before = library.revision()
        _tiny_store(tmp_path / "overview_pos002.ome.zarr")
        assert library.revision() != before

    def test_it_moves_when_a_description_is_rewritten_in_place(self, tmp_path):
        """The one that was missed, and the reason a run could go unseen.

        A folder is marked as changed when something is created inside it or
        removed from it — not when a file already inside it is rewritten. Writers
        routinely create the description file early and empty, then fill it in
        once the image is safely on disk. To anyone watching, that folder appeared
        (so the answer moved once, while there was still nothing readable there)
        and then never changed again, so the viewer looked exactly once, at the
        only moment when there was nothing to find.

        This is written as a test of the *rewrite* specifically, because the
        create-a-new-folder case above passed throughout and told us nothing.
        """
        library = Library()
        _tiny_store(tmp_path / "overview_pos001.ome.zarr")
        library.open(tmp_path)

        # A folder that exists but is not yet readable as an image: this is what a
        # microscope leaves on disk while it is still writing.
        still_writing = tmp_path / "prescan_pos001.ome.zarr"
        still_writing.mkdir()
        (still_writing / ".zattrs").write_text("{}", encoding="utf-8")
        while_writing = library.revision()
        # Two things are being said here, and both of them need saying. The folder
        # still being written is not offered yet, which is the point of this
        # check — but the store that *is* readable has to be offered, or an empty
        # list would satisfy the first half while telling us nothing at all. A
        # library that had lost both stores would then look like a library
        # behaving correctly.
        open_now = [name for _, _, name in library.entries()]
        assert "overview_pos001.ome.zarr" in open_now, (
            f"the readable store went missing, so this proves nothing: {open_now}"
        )
        assert "prescan_pos001.ome.zarr" not in open_now, (
            f"a folder still being written was offered as an image: {open_now}"
        )

        # Now the writer fills in the description it created earlier. Nothing is
        # added to the folder, so the folder's own time does not move -- only the
        # file's does.
        (still_writing / ".zattrs").write_text(
            json.dumps(
                {
                    "multiscales": [
                        {
                            "version": "0.4",
                            "axes": [{"name": a} for a in ("z", "y", "x")],
                            "datasets": [
                                {
                                    "path": "0",
                                    "coordinateTransformations": [
                                        {"type": "scale", "scale": [2.0, 0.35, 0.35]}
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        assert library.revision() != while_writing, (
            "the acquisition became readable and nothing said so — a viewer would "
            "never look again, and it would stay invisible for the whole session"
        )

    def test_it_moves_even_when_the_clock_does_not(self, tmp_path):
        """The same change, with the timestamps forced to be identical.

        The test above only fails when the machine is slow enough for the two
        writes to land in different ticks of the clock — which on Windows advances
        about every sixteen milliseconds, so on a warm run they share one and the
        rewrite becomes invisible. That is not a hypothetical: a writer creating an
        empty description and filling it in immediately is the whole reason this
        machinery exists. So here the times are made equal on purpose, and the
        answer still has to move.
        """
        library = Library()
        _tiny_store(tmp_path / "overview_pos001.ome.zarr")
        library.open(tmp_path)

        still_writing = tmp_path / "prescan_pos001.ome.zarr"
        still_writing.mkdir()
        described = still_writing / ".zattrs"
        described.write_text("{}", encoding="utf-8")
        pinned = described.stat()
        while_writing = library.revision()

        described.write_text(
            json.dumps({"multiscales": [{"version": "0.4", "axes": [], "datasets": []}]}),
            encoding="utf-8",
        )
        os.utime(described, ns=(pinned.st_atime_ns, pinned.st_mtime_ns))
        assert described.stat().st_mtime_ns == pinned.st_mtime_ns, "the clock was not pinned"

        assert library.revision() != while_writing, (
            "a description rewritten within one tick of the clock went unnoticed"
        )

    def test_it_stays_put_when_nothing_has_happened(self, tmp_path):
        """The other half: asking twice with nothing going on must look the same.

        Without this, the check above could be satisfied by an answer that simply
        changed every time, which would send the viewer off to do the expensive
        work several times a second for ever.
        """
        library = Library()
        _tiny_store(tmp_path / "overview_pos001.ome.zarr")
        library.open(tmp_path)
        assert library.revision() == library.revision()
