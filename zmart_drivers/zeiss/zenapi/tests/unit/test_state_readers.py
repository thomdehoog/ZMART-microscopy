"""Readers: parsing, m->µm, objective enrichment, diagnostics, status, ping."""

import pytest
import zenapi as drv
from zenapi.readers.reading import Reading


def test_get_xy_parses_and_converts(fake_client):
    client, scope = fake_client
    scope.x_m, scope.y_m = 1e-3, 2e-3
    pos = drv.get_xy(client)
    assert pos["x_m"] == pytest.approx(1e-3)
    assert pos["x_um"] == pytest.approx(1000.0)
    assert pos["y_um"] == pytest.approx(2000.0)


def test_get_z_in_micrometers(fake_client):
    client, scope = fake_client
    scope.z_m = 50e-6
    assert drv.get_z(client) == pytest.approx(50.0)


def test_get_objective_enriched(fake_client):
    client, scope = fake_client
    scope.objective_index = 1
    obj = drv.get_objective(client)
    assert obj["index"] == 1
    assert obj["name"] == "Plan-Apochromat 20x/0.8"
    assert obj["magnification"] == 20


def test_diagnostics_wraps_in_reading(fake_client):
    client, _ = fake_client
    r = drv.get_xy(client, diagnostics=True)
    assert isinstance(r, Reading)
    assert r.source == "api"
    assert r.observed_at > 0


def test_get_status_sentinel_without_experiment(fake_client):
    client, _ = fake_client
    s = drv.get_status(client)
    assert s["is_experiment_running"] is False
    assert s["is_acquisition_running"] is False


def test_ping_true(fake_client):
    client, _ = fake_client
    assert drv.ping(client) is True
