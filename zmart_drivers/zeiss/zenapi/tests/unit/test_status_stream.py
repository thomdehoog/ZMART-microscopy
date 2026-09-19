"""Acquisition status: the GetStatus readback (confirm_acquire) and the monitor() stream."""

import pytest
import zenapi as drv
from mock_zen_api import idle_status, running_status
from zenapi.commands.confirmations import confirm_acquire


def test_confirm_acquire_reads_final_status(fake_client):
    client, scope = fake_client
    scope.status_by_experiment["exp::E"] = idle_status(images_acquired_index=7, images_count=7)
    sink = {}
    r = confirm_acquire(client, experiment_id="exp::E", poll_window=1.0, sink=sink)
    assert r["success"] is True
    assert r["last_status"]["images_count"] == 7
    assert sink["last_status"] is r["last_status"]


def test_confirm_acquire_unconfirmed_while_still_running(fake_client):
    client, scope = fake_client
    scope.status_by_experiment["exp::E"] = running_status()
    r = confirm_acquire(client, experiment_id="exp::E", poll_window=0.05, poll_interval=0.01)
    assert r["success"] is False
    assert r["last_status"]["is_experiment_running"] is True


def test_monitor_yields_status_dicts(fake_client):
    client, scope = fake_client
    scope.status_script = [running_status(), idle_status()]
    exp = drv.load_experiment(client, "ZMART_Snap")
    items = list(drv.monitor(client, exp, kind="status"))
    assert len(items) == 2
    assert items[0]["is_acquisition_running"] is True
    assert items[1]["is_acquisition_running"] is False


def test_start_experiment_then_stop(fake_client):
    client, scope = fake_client
    exp = drv.load_experiment(client, "ZMART_ZStack")
    started = drv.start_experiment(client, exp, output_name="live1")
    assert started["output_name"] == "live1"
    assert drv.get_status(client)["is_experiment_running"] is True  # active experiment
    assert drv.stop(client)["experiment_id"] == "exp::ZMART_ZStack"


def test_monitor_pixels_is_seam(fake_client):
    client, _ = fake_client
    with pytest.raises(NotImplementedError):
        list(drv.monitor(client, "exp::E", kind="pixels"))
