"""Starting the viewer when its usual door is already taken.

The viewer answers on port 8848 by default. On a shared lab PC that number may
well belong to something else, and a second copy of the viewer certainly wants
it. What used to happen then was the worst of both worlds: the attempt died with
a bare ``OSError`` quoting an error number, and there was no way to ask for a
different port — so on that machine the viewer could not be started at all, and
nothing on screen suggested a way forward.

Three things are checked here, and they are all about somebody at a microscope
being able to get on with their day:

1. a port already in use is explained, and the explanation says what to do;
2. ``--port`` exists and is passed through to the server;
3. asking for port 0 — "any free one" — reports the port actually chosen rather
   than the useless ``http://127.0.0.1:0`` that came of trusting the argument.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "server"))

from server import make_server  # noqa: E402


def test_a_port_already_in_use_is_explained(tmp_path: Path) -> None:
    """The message has to name the problem and offer the way out."""
    holder = make_server(port=0, data_dir=tmp_path, site_dir=tmp_path)
    taken = holder.server_address[1]
    try:
        with pytest.raises(OSError) as refused:
            make_server(port=taken, data_dir=tmp_path, site_dir=tmp_path)
        said = str(refused.value)
        assert str(taken) in said, "the message does not say which port was in use"
        assert "--port" in said, "the message does not offer a way to choose another"
        # Written for somebody who is not a programmer, so it must not simply be
        # an error number.
        assert "already using it" in said
    finally:
        holder.server_close()


def test_asking_for_any_free_port_reports_the_one_it_got(tmp_path: Path) -> None:
    """Port 0 means "choose for me", and the answer has to come from the server.

    Building the address from the number that was *asked for* gave
    ``http://127.0.0.1:0``, which leads nowhere. The server knows which port it
    actually got, so it is the thing to ask.
    """
    server = make_server(port=0, data_dir=tmp_path, site_dir=tmp_path)
    try:
        chosen = server.server_address[1]
        assert chosen != 0, "the server did not report the port it was given"
        assert 1024 <= chosen <= 65535
        # And it is genuinely listening there.
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", chosen)) == 0
    finally:
        server.server_close()


def test_two_viewers_can_run_side_by_side(tmp_path: Path) -> None:
    """The whole point: a second copy must be able to start somewhere else."""
    first = make_server(port=0, data_dir=tmp_path, site_dir=tmp_path)
    second = make_server(port=0, data_dir=tmp_path, site_dir=tmp_path)
    try:
        assert first.server_address[1] != second.server_address[1]
    finally:
        first.server_close()
        second.server_close()


def test_run_demo_offers_a_port_and_passes_it_on() -> None:
    """``--port`` has to reach the launcher, not merely be accepted and ignored."""
    import run_demo

    passed = {}

    def remember(**kwargs):
        passed.update(kwargs)

    original = run_demo.open_window
    run_demo.open_window = remember
    try:
        # The demo path needs the built page to exist; where it does not, the
        # command stops before opening anything and there is nothing to check.
        if not (Path(run_demo._HERE) / "app" / "page" / "dist" / "index.html").exists():
            pytest.skip("the viewer page has not been built, so run_demo stops early")
        assert run_demo.main(["--port", "8899"]) == 0
    finally:
        run_demo.open_window = original

    assert passed.get("port") == 8899, (
        f"--port did not reach the launcher; it was given {passed.get('port')!r}"
    )
