"""The real bridge server on a free local port, with a fake NIS behind it."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the project folder
sys.path.insert(0, str(Path(__file__).resolve().parent))  # fake_nis

from fake_nis import FakeNisApi, running_bridge  # noqa: E402
from nis_useq.client import NisClient  # noqa: E402


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
