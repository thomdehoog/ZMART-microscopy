"""Shared pytest setup: import bootstrap + a real bridge server over a fake NIS API."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# parents: [0]=tests [1]=nis_elements_6_10 [2]=nikon [3]=zmart_drivers [4]=repo root
_VENDOR_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[4]
_HELPERS = Path(__file__).resolve().parent / "helpers"
for entry in (_VENDOR_DIR, _REPO_ROOT, _HELPERS):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))


@pytest.fixture
def fake_api():
    from fake_nis_api import FakeNisApi

    return FakeNisApi()


@pytest.fixture
def bridge(fake_api):
    """The real bridge server, listening on a free loopback port, over the fake API."""
    from nis_elements_6_10.bridge import nis_bridge

    server = nis_bridge.serve(fake_api, "127.0.0.1", 0, pump_thread=True)
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def client(bridge):
    from nis_elements_6_10.connection.client import NisClient

    c = NisClient("127.0.0.1", bridge.server_address[1], timeout=5.0)
    c.connect()
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def connection(bridge, tmp_path):
    """A controller-style connection dict pointing at the test bridge and temp folders."""
    return {
        "vendor": "nikon",
        "microscope": "test-scope",
        "api": "nis-elements-bridge",
        "host": "127.0.0.1",
        "port": bridge.server_address[1],
        "output_root": str(tmp_path / "out"),
        "machine_root": str(tmp_path / "programdata"),
    }
