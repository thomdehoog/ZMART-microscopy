"""Command wrappers end-to-end over the fake scope (real bridge + dispatch)."""

import pytest
import zenapi as drv
from mock_zen_api import FakeGRPCError


def _wide_limits():
    drv.set_stage_limits(x_min=-1e6, x_max=1e6, y_min=-1e6, y_max=1e6, z_min=-1e6, z_max=1e6)


def test_move_xy_confirmed(fake_client):
    client, scope = fake_client
    _wide_limits()
    r = drv.move_xy(client, 1000, 2000)
    assert r["success"] is True and r["confirmed"] is True
    assert r["position"]["x_um"] == 1000
    assert scope.x_m == pytest.approx(1e-3)
    assert scope.y_m == pytest.approx(2e-3)


def test_move_z_confirmed(fake_client):
    client, scope = fake_client
    _wide_limits()
    r = drv.move_z(client, 50)
    assert r["success"] is True and r["confirmed"] is True
    assert scope.z_m == pytest.approx(50e-6)


def test_set_objective_by_name(fake_client):
    client, scope = fake_client
    r = drv.set_objective(client, name="Plan-Apochromat 63x/1.4")
    assert r["success"] is True and r["confirmed"] is True
    assert r["index"] == 2
    assert scope.objective_index == 2


def test_set_objective_by_index(fake_client):
    client, scope = fake_client
    drv.set_objective(client, index=1)
    assert scope.objective_index == 1


def test_set_objective_unknown_name_raises(fake_client):
    client, _ = fake_client
    with pytest.raises(ValueError, match="No objective named"):
        drv.set_objective(client, name="does-not-exist")


def test_move_xy_permanent_error_fails(fake_client):
    client, scope = fake_client
    _wide_limits()
    scope.errors["stage_move"] = FakeGRPCError("INVALID_ARGUMENT", "bad target")
    r = drv.move_xy(client, 10, 10)
    assert r["success"] is False


def test_load_and_run_experiment(fake_client):
    client, scope = fake_client
    exp = drv.load_experiment(client, "TileScan")
    assert exp.experiment_id == "exp::TileScan"
    r = drv.run_experiment(client, exp, output_name="myrun")
    assert r["success"] is True
    assert r["output_name"] == "myrun"
