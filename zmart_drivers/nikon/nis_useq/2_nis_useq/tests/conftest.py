"""The real bridge server on a free local port, with a fake NIS behind it."""

from __future__ import annotations

import pytest
from nis_bridge.fake import FakeNisApi, running_bridge


@pytest.fixture
def fake() -> FakeNisApi:
    return FakeNisApi()


@pytest.fixture
def port(fake) -> int:
    with running_bridge(fake) as server:
        yield server.server_address[1]
