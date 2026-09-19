"""
Live round-trip against a running mesoSPIM Remote Control server.
=================================================================
The one suite that cannot run in CI: it drives a **real** mesoSPIM through its
Remote Control TCP server (the Remote Control tab; mesoSPIM-control pull
request #106) -- ideally in ``-D`` demo mode (all Demo backends, no
hardware). It is the bench check for the pieces the offline mock cannot prove:
the call vocabulary against a live Core, the operation polling, and the
acquisition run + image-writer path resolution.

Run it (mesoSPIM ``-D`` running with the TCP transport started on 42000)::

    MESOSPIM_TOKEN=<password> python -m pytest zmart_drivers/mesospim/tests -m integration

Point it elsewhere with env vars::

    MESOSPIM_HOST=127.0.0.1 MESOSPIM_PORT=42000 MESOSPIM_TOKEN=<password> \\
        python -m pytest zmart_drivers/mesospim/tests -m integration

The acquisition test fires a capture, so it is **opt-in** to avoid triggering
lasers on real hardware -- enable it only when it is safe (demo mode, or a
sample-free instrument)::

    MESOSPIM_ALLOW_ACQUIRE=1 python -m pytest zmart_drivers/mesospim/tests -m integration

If no server answers at the address, every test *skips* (so the marker is safe to
run anywhere). Author: Thom de Hoog (ZMB, University of Zurich). License: MIT.
"""

from __future__ import annotations

import os

import mesospim as drv
import pytest
from mesospim.limits import checks as limits
from mesospim.protocol import PROTOCOL_VERSION

pytestmark = pytest.mark.integration

_HOST = os.environ.get("MESOSPIM_HOST", "127.0.0.1")
_PORT = int(os.environ.get("MESOSPIM_PORT", "42000"))
_ALLOW_ACQUIRE = os.environ.get("MESOSPIM_ALLOW_ACQUIRE") == "1"
# The Remote Control password; unset means mesoSPIM's loopback placeholder.
_TOKEN = os.environ.get("MESOSPIM_TOKEN")


@pytest.fixture
def live_client():
    """A client connected to a live server, or skip if none is reachable."""
    try:
        client = drv.connect({"host": _HOST, "port": _PORT, "timeout": 5.0, "token": _TOKEN})
    except (ConnectionError, drv.MesospimError) as exc:
        pytest.skip(f"no live mesoSPIM Remote Control server at {_HOST}:{_PORT} ({exc})")
    try:
        yield client
    finally:
        drv.close(client)


@pytest.fixture
def wide_limits():
    """Generous stage limits so the (no-net-motion) move test isn't fail-closed."""
    limits.clear_stage_limits()
    limits.set_stage_limits(
        x=(-1e6, 1e6), y=(-1e6, 1e6), z=(-1e6, 1e6), f=(-1e6, 1e6), theta=(-360, 360)
    )
    yield
    limits.clear_stage_limits()


def test_greeting_reports_protocol_and_app(live_client):
    info = live_client.server_info
    assert info.get("app") == "mesoSPIM-control"
    assert int(info.get("protocol")) == PROTOCOL_VERSION


def test_get_config_has_lasers_and_camera(live_client):
    """Validates the config document against the live Core."""
    cfg = drv.get_config(live_client)
    assert cfg.get("lasers"), "no lasers reported"
    assert cfg.get("filters"), "no filters reported"
    cam = cfg.get("camera") or {}
    assert int(cam.get("pixels_x", 0)) > 0 and int(cam.get("pixels_y", 0)) > 0
    for zoom in cfg.get("zooms", []):
        assert "pixel_size_um" in zoom


def test_get_limits_reports_an_envelope_for_every_axis(live_client):
    enforced = drv.get_limits(live_client)["enforced"]["axes"]
    for axis in ("x", "y", "z", "f", "theta"):
        assert enforced.get(axis), f"no enforced limit for {axis!r}"


def test_get_state_has_run_state_position_and_settings(live_client):
    state = drv.get_state(live_client)
    assert state.get("state") is not None, "run state should be readable over Remote Control"
    pos = state.get("position") or {}
    for axis in ("x", "y", "z", "f", "theta"):
        assert axis in pos, f"position missing axis {axis!r}"


def test_move_absolute_completes_without_moving(live_client, wide_limits):
    """Exercise the move + operation polling + confirm plumbing with zero net motion."""
    from mesospim import commands as cmd

    pos = drv.get_positions(live_client)
    targets = {a: float(pos[a]) for a in ("x", "y", "z") if pos.get(a) is not None}
    assert targets, "could not read a linear position to re-target"
    result = cmd.move_absolute(live_client, targets)
    assert result["success"], result["message"]
    assert result["data"]["operation"]["status"] == "completed"


@pytest.mark.skipif(
    not _ALLOW_ACQUIRE,
    reason="set MESOSPIM_ALLOW_ACQUIRE=1 to run the capture (fires a snap)",
)
def test_acquire_writes_a_file(live_client, tmp_path):
    """The bench check for the acquisition run path + image-writer resolution."""
    result = drv.acquire(
        live_client,
        "snap",
        options={"folder": str(tmp_path), "filename": "integration_snap.tiff", "planes": 1},
    )
    assert result.files, "server returned no frame files"
    for path in result.files:
        assert path.exists(), f"reported frame file does not exist: {path}"
    assert result.planes >= 1
