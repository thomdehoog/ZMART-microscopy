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
    monday = tmp_path / "run_monday"
    friday = tmp_path / "run_friday"
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
    """Closing is by acquisition type, because that is the unit on screen."""

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
