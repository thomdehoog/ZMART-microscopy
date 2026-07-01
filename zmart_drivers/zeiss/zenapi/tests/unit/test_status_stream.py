"""Status-stream consumption: confirm_acquire and monitor()."""

import pytest
from mock_zen_api import idle_status, running_status

import zenapi as drv
from zenapi.commands.confirmations import confirm_acquire


def test_confirm_acquire_completes(fake_client):
    client, scope = fake_client
    scope.status_script = [running_status(), running_status(tiles_index=1), idle_status()]
    r = confirm_acquire(
        client, experiment_id="exp::E", start_timeout=5, heartbeat_interval=30,
        timeout=10, poll_interval=0.01,
    )
    assert r["success"] is True
    assert r["last_status"]["is_acquisition_running"] is False


def test_confirm_acquire_never_started(fake_client):
    client, scope = fake_client
    scope.status_script = [idle_status(), idle_status()]
    r = confirm_acquire(
        client, experiment_id="exp::E", start_timeout=5, heartbeat_interval=30,
        timeout=10, poll_interval=0.01,
    )
    assert r["success"] is False


def test_monitor_yields_status_dicts(fake_client):
    client, scope = fake_client
    scope.status_script = [running_status(), idle_status()]
    exp = drv.load_experiment(client, "E")
    items = list(drv.monitor(client, exp, kind="status"))
    assert len(items) == 2
    assert items[0]["is_acquisition_running"] is True
    assert items[1]["is_acquisition_running"] is False


def test_monitor_pixels_is_seam(fake_client):
    client, _ = fake_client
    with pytest.raises(NotImplementedError):
        list(drv.monitor(client, "exp::E", kind="pixels"))
