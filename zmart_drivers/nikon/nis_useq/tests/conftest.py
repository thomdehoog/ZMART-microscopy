"""The real bridge server on a free local port, with a fake NIS behind it."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the project folder
sys.path.insert(0, str(Path(__file__).resolve().parent))  # fake_nis

from fake_nis import FakeNisApi  # noqa: E402
from nis_useq import bridge  # noqa: E402
from nis_useq.client import NisClient  # noqa: E402


@pytest.fixture
def fake() -> FakeNisApi:
    return FakeNisApi()


@pytest.fixture
def server(fake):
    """The bridge, with a background thread standing in for the NIS macro loop."""
    srv = bridge.serve(fake, "127.0.0.1", 0)
    stop = threading.Event()

    def macro_loop() -> None:
        while not stop.is_set():
            srv.pump(wait_s=0.01)

    thread = threading.Thread(target=macro_loop, daemon=True)
    thread.start()
    yield srv
    stop.set()
    thread.join()
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def port(server) -> int:
    return server.server_address[1]


@pytest.fixture
def client(port):
    with NisClient("127.0.0.1", port, timeout=5.0) as c:
        yield c
