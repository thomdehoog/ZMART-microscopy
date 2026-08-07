"""Telling an open page that something has changed.

The viewer used to find this out by asking, several times a second, whether
anything on disk had moved. Now the server says so. These tests cover both ends
of that: the small piece of machinery that keeps track of who is listening, and
the connection a page actually holds open.

The reason it is worth testing carefully is that the failure is silent. A
viewer that stops hearing announcements looks exactly like an experiment that
has stopped producing data — nothing goes red, nothing is logged, the picture
simply stops changing — and the two call for very different reactions in the
middle of the night.
"""

from __future__ import annotations

import http.client
import json
import threading
import time

import announcements as announcements_mod
import pytest
from announcements import Announcements, FolderWatcher
from server import make_server


class TestKeepingTrackOfWhoIsListening:
    """The bookkeeping, on its own, with no server or browser involved."""

    def test_nobody_listening_means_nobody_told(self):
        told = Announcements()
        assert told.say_something_changed() == 0

    def test_everyone_listening_is_told(self):
        told = Announcements()
        first, second = told.listen(), told.listen()
        assert told.say_something_changed() == 2
        assert not first.empty() and not second.empty()

    def test_a_page_that_has_gone_is_not_told(self):
        told = Announcements()
        going = told.listen()
        staying = told.listen()
        told.stop_listening(going)
        assert told.say_something_changed() == 1
        assert not staying.empty()

    def test_shutting_down_releases_everyone(self):
        """Otherwise each listener sits out its heartbeat before noticing.

        Sending each one a "we are finished" rather than simply forgetting them is
        what lets their threads end promptly, which is what keeps a test suite (and
        an operator closing the window) from waiting.
        """
        told = Announcements()
        waiting = told.listen()
        told.close()
        assert waiting.get(timeout=1) is None
        assert told.listening == 0

    def test_listening_after_shutdown_does_not_wait_for_ever(self):
        told = Announcements()
        told.close()
        assert told.listen().get(timeout=1) is None


class TestWatchingTheDisk:
    """The safety net for data that arrives with nobody announcing it."""

    class _Changing:
        """Stands in for the library: says something different when told to."""

        def __init__(self):
            self.answer = "same"

        def revision(self):
            return self.answer

    def test_it_says_nothing_while_nothing_changes(self):
        library, told = self._Changing(), Announcements()
        heard = told.listen()
        watcher = FolderWatcher(library, told, every=0.01)
        watcher.start()
        try:
            time.sleep(0.2)
        finally:
            watcher.stop()
        assert heard.empty(), "it spoke up when nothing had happened"

    def test_it_speaks_when_something_changes(self):
        library, told = self._Changing(), Announcements()
        heard = told.listen()
        watcher = FolderWatcher(library, told, every=0.01)
        watcher.start()
        try:
            time.sleep(0.1)
            library.answer = "different"
            assert heard.get(timeout=2) is not None
        finally:
            watcher.stop()

    def test_it_stays_quiet_about_a_change_the_microscope_has_already_announced(self):
        """The same write must not be announced twice, once by each mechanism.

        Two things notice a write: the application driving the microscope, which
        knows because it did the writing, and this watcher, which sees the disk move
        a moment later. Left alone they both speak, so every position an experiment
        produces costs each open page two full rebuilds of the expensive "what is
        open" answer — over a second apiece once a folder holds a few thousand
        acquisitions.

        The second announcement is worse than merely wasteful. Nothing on disk has
        moved between the two, and *that* is the signal the page reads as "image was
        written into a store I already have open" — so it throws away everything it
        has fetched and fetches it again, once per position, for nothing.

        The two are kept apart by what the disk says rather than by counting
        announcements, so a change landing *after* the microscope spoke is still
        noticed. That is the second half of this test.
        """
        library, told = self._Changing(), Announcements()
        heard = told.listen()
        watcher = FolderWatcher(library, told, every=0.01)
        watcher.start()
        try:
            # Let the watcher settle on what the disk looks like now, so that the
            # change below is one it would otherwise notice and speak about.
            time.sleep(0.1)
            assert heard.empty(), "it spoke before anything had happened"

            # The write happens, and the microscope announces it itself, saying what
            # the disk looked like at that moment. That is the one announcement the
            # page should get.
            library.answer = "after the write"
            told.say_something_changed(covering="after the write")
            assert heard.get(timeout=1) is not None, "the microscope's own announcement"

            time.sleep(0.2)
            assert heard.empty(), (
                "the watcher repeated the write the microscope had already "
                "announced, which costs every open page a second rebuild and makes "
                "it refetch the whole view"
            )

            # And it must still speak for the next write, which nobody announced.
            library.answer = "and then another write"
            assert heard.get(timeout=2) is not None, (
                "the watcher went quiet for good instead of only for the write it "
                "had already been told about"
            )
        finally:
            watcher.stop()

    def test_a_folder_that_cannot_be_read_does_not_stop_it(self):
        """A share hiccuping must not end the watching for the rest of the session."""

        class Hiccuping:
            def __init__(self):
                self.calls = 0

            def revision(self):
                self.calls += 1
                if self.calls == 2:
                    raise OSError("the share went away for a moment")
                return "changed" if self.calls > 2 else "first"

        library, told = Hiccuping(), Announcements()
        heard = told.listen()
        watcher = FolderWatcher(library, told, every=0.01)
        watcher.start()
        try:
            assert heard.get(timeout=2) is not None
        finally:
            watcher.stop()


def _serving(tmp_path, **kwargs):
    site = tmp_path / "site"
    site.mkdir(exist_ok=True)
    (site / "index.html").write_text("x", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    store = data / "overview_pos001.ome.zarr"
    if not store.exists():
        store.mkdir()
        (store / ".zattrs").write_text(
            json.dumps(
                {
                    "multiscales": [
                        {"version": "0.4", "axes": [{"name": a} for a in "zyx"],
                         "datasets": [{"path": "0"}]}
                    ]
                }
            ),
            encoding="utf-8",
        )
    server = make_server(port=0, data_dir=data, site_dir=site,
                         store="overview_pos001.ome.zarr", **kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class TestTheConnectionAPageHolds:
    """The endpoint itself, spoken to directly rather than through a browser."""

    def test_an_announcement_reaches_a_listener(self, tmp_path):
        server, thread = _serving(tmp_path)
        port = server.server_address[1]
        listening = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            listening.request("GET", "/api/events")
            response = listening.getresponse()
            assert response.status == 200
            assert response.getheader("Content-Type") == "text/event-stream"
            # An announcement must never be kept and replayed: it says something
            # about a moment, and a recording of it would be worse than useless.
            assert response.getheader("Cache-Control") == "no-store"
            # The greeting, which is what tells the browser the connection is open
            # rather than still being made.
            assert b"listening" in response.readline()

            # Wait until the server agrees somebody is there, so this is not a race.
            for _ in range(100):
                telling = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                telling.request("POST", "/api/announce", body=b"{}",
                                headers={"Content-Length": "2"})
                told = json.loads(telling.getresponse().read())["told"]
                telling.close()
                if told:
                    break
                time.sleep(0.05)
            assert told == 1, "the announcement reached nobody"

            heard = b""
            deadline = time.monotonic() + 10
            while b"changed" not in heard and time.monotonic() < deadline:
                heard += response.readline()
            assert b"changed" in heard, f"nothing arrived on the connection: {heard!r}"
        finally:
            listening.close()
            server.shutdown()
            thread.join(timeout=5)

    def test_announcing_with_nobody_there_is_not_an_error(self, tmp_path):
        """A script announcing into an empty room should be told so, not fail.

        An acquisition script that announces a position and is told nobody was
        listening has learnt something useful — the viewer is not open — and it
        should be able to carry on either way.
        """
        server, thread = _serving(tmp_path)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
            conn.request("POST", "/api/announce", body=b"{}", headers={"Content-Length": "2"})
            response = conn.getresponse()
            assert response.status == 200
            assert json.loads(response.read()) == {"told": 0}
            conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)

    def test_a_quiet_connection_is_given_a_sign_of_life(self, tmp_path, monkeypatch):
        """Nothing happening for a while must still put something on the wire.

        This is not about telling the page anything — the line sent is a comment
        the browser hands to nobody. It is about the *writing*. A page that has been
        closed is only discovered by trying to write to it, so without this a server
        left running overnight beside an experiment would hold on to a thread for
        every window anybody had ever opened, and never find out that they had gone.

        The wait is shortened here from fifteen seconds to a tenth of one, because
        what is being checked is that the sign of life is sent at all, and nobody
        should have to wait fifteen seconds to find that out.
        """
        monkeypatch.setattr(announcements_mod, "QUIET_HEARTBEAT_S", 0.1)
        server, thread = _serving(tmp_path)
        listening = http.client.HTTPConnection(
            "127.0.0.1", server.server_address[1], timeout=10
        )
        try:
            listening.request("GET", "/api/events")
            response = listening.getresponse()
            assert b"listening" in response.readline(), "the greeting"

            heard = b""
            deadline = time.monotonic() + 10
            while b"still here" not in heard and time.monotonic() < deadline:
                heard += response.readline()
            assert b"still here" in heard, (
                "nothing at all was written to a quiet connection, so a page that "
                f"had been closed would never be noticed: {heard!r}"
            )
        finally:
            listening.close()
            server.shutdown()
            thread.join(timeout=5)

    def test_the_old_polling_question_is_gone(self, tmp_path):
        """Nothing should be asking this any more, and nothing answers it."""
        server, thread = _serving(tmp_path)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
            conn.request("GET", "/api/revision")
            assert conn.getresponse().status == 404
            conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)

    def test_finished_data_does_not_watch_the_disk(self, tmp_path):
        """Nothing can change, so nothing looks. This is the whole of static mode.

        Checked by writing a new acquisition and insisting that *nothing* is said
        about it, which is the behaviour someone opening last week's run wants: a
        viewer that does no work at all while they read.
        """
        server, thread = _serving(tmp_path, live=False)
        port = server.server_address[1]
        listening = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            listening.request("GET", "/api/events")
            response = listening.getresponse()
            response.readline()  # the greeting

            appeared = tmp_path / "data" / "prescan_pos001.ome.zarr"
            appeared.mkdir()
            (appeared / ".zattrs").write_text(
                json.dumps({"multiscales": [{"version": "0.4",
                                             "axes": [{"name": a} for a in "zyx"],
                                             "datasets": [{"path": "0"}]}]}),
                encoding="utf-8",
            )
            time.sleep(1.5)
            # Nothing announced, so the connection has nothing on it beyond what a
            # quiet connection sends, which is nothing at all this soon.
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("POST", "/api/announce", body=b"{}", headers={"Content-Length": "2"})
            assert json.loads(conn.getresponse().read())["told"] == 1
            conn.close()
        finally:
            listening.close()
            server.shutdown()
            thread.join(timeout=5)


@pytest.mark.parametrize("route", ["/api/announce"])
def test_a_badly_formed_announcement_is_refused_plainly(tmp_path, route):
    server, thread = _serving(tmp_path)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
        conn.request("POST", route, body=b"not json", headers={"Content-Length": "8"})
        response = conn.getresponse()
        assert response.status == 400
        assert "readable JSON" in json.loads(response.read())["error"]
        conn.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
