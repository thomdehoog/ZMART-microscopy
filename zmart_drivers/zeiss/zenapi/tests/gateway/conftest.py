"""Fixtures for the protocol-level tests: a fake gateway per test, real wheel, real TLS.

The whole folder is skipped when the ``zen_api`` wheel or ``grpclib`` is not
installed (see the driver README for the install line), so the plain offline
suite still runs anywhere.
"""

from __future__ import annotations

import pytest

pytest.importorskip("zen_api", reason="the zen_api wheel is not installed")
pytest.importorskip("grpclib", reason="grpclib is not installed")


@pytest.fixture
def gateway(tmp_path):
    """A running fake gateway on a free port with its own work folder."""
    from zenapi.simulator import FakeGateway

    gw = FakeGateway(tmp_path / "gateway")
    gw.start()
    try:
        yield gw
    finally:
        gw.stop()


@pytest.fixture
def config_ini(gateway, tmp_path):
    """A config.ini for the running fake gateway (what an operator would edit)."""
    return gateway.write_config(tmp_path / "config.ini")


@pytest.fixture
def client(config_ini):
    """A connected driver client with generous stage limits."""
    import zenapi as drv

    c = drv.connect(str(config_ini))
    drv.set_stage_limits(x_min=-1e5, x_max=1e5, y_min=-1e5, y_max=1e5, z_min=-1e4, z_max=1e4)
    try:
        yield c
    finally:
        drv.close(c)


@pytest.fixture
def connection(config_ini, tmp_path):
    """A controller-style connection dict pointing at the fake gateway and temp folders."""
    from zenapi import CONNECTION

    return {
        **CONNECTION,  # the registered identity: vendor / microscope / api
        "config": str(config_ini),
        "output_root": str(tmp_path / "out"),
        "machine_root": str(tmp_path / "programdata"),
    }
