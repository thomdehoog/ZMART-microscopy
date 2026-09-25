"""The real bridge server on a free local port, with a pretend NIS behind it."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # this part's folder
sys.path.insert(0, str(Path(__file__).resolve().parent))  # the scripted model in test_agent

from nis_bridge.fake import FakeNisApi, running_bridge  # noqa: E402


@pytest.fixture
def fake() -> FakeNisApi:
    return FakeNisApi()


@pytest.fixture
def port(fake) -> int:
    with running_bridge(fake) as server:
        yield server.server_address[1]
