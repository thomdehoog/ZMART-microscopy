"""Shared pytest setup: import bootstrap + mock-server/client fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add the drivers dir (parent of mesospim) so `import mesospim` works regardless
# of where pytest is invoked from. parents: [0]=tests [1]=mesospim [2]=zmart_drivers.
_DRIVERS_DIR = Path(__file__).resolve().parents[2]
if str(_DRIVERS_DIR) not in sys.path:
    sys.path.insert(0, str(_DRIVERS_DIR))

# Add the repo root so `import zmart_controller` resolves.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Add the helpers dir so `import mock_mesospim_server` works.
_HELPERS = Path(__file__).resolve().parent / "helpers"
if str(_HELPERS) not in sys.path:
    sys.path.insert(0, str(_HELPERS))


@pytest.fixture
def server(tmp_path):
    """A running mock command server writing frames under a temp dir."""
    from mock_mesospim_server import MockMesospimServer

    with MockMesospimServer(output_dir=tmp_path / "server_out") as srv:
        yield srv


@pytest.fixture
def client(server):
    """A connected MesospimClient talking to the mock server."""
    from mesospim.connection.client import MesospimClient

    c = MesospimClient(server.host, server.port, timeout=3.0)
    c.connect()
    try:
        yield c
    finally:
        c.close()
