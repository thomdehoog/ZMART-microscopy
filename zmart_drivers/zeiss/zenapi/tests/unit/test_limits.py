"""Stage safety envelope: set/get, config, and out-of-range rejection (no RPC)."""

import pytest
import zenapi as drv
from zenapi.motion import limits


def test_set_get_roundtrip():
    drv.set_stage_limits(x_min=-100, x_max=100, y_min=-50, y_max=50, z_min=0, z_max=200)
    lim = drv.get_stage_limits()
    assert lim["x_max"] == 100
    assert lim["z_max"] == 200


def test_apply_from_config():
    cfg = {"stage_um": {"x": [-1, 1], "y": [-2, 2], "z": [0, 3]}}
    drv.apply_stage_limits_from_config(cfg)
    assert drv.get_stage_limits()["y_max"] == 2


def test_move_xy_out_of_range_never_fires(fake_client):
    client, scope = fake_client
    drv.set_stage_limits(x_min=-100, x_max=100, y_min=-100, y_max=100, z_min=0, z_max=100)
    scope.x_m = 0.123  # sentinel: the stub must NOT be called
    r = drv.move_xy(client, 99999, 0)  # µm, far out of range
    assert r["success"] is False
    assert "outside limits" in r["message"]
    assert scope.x_m == 0.123


def test_unconfigured_raises():
    limits._stage_limits.update({k: None for k in limits._stage_limits})
    with pytest.raises(RuntimeError, match="not configured"):
        limits._check_z_limits(5)
