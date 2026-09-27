"""The real bridge server on a free local port, with a fake NIS behind it.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB), University of Zurich
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
Date: 2026-09-27
License: MIT
"""

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
