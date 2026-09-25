"""The real bridge server on a free local port, with a fake NIS behind it."""

from __future__ import annotations

import pytest
from nis_bridge.client import NisClient
from nis_bridge.fake import FakeNisApi, running_bridge


@pytest.fixture
def fake() -> FakeNisApi:
    return FakeNisApi()


@pytest.fixture
def server(fake):
    with running_bridge(fake) as server:
        yield server


@pytest.fixture
def port(server) -> int:
    return server.server_address[1]


@pytest.fixture
def client(port):
    with NisClient("127.0.0.1", port, timeout=5.0) as c:
        yield c
