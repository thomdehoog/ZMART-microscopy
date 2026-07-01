"""Micrometer (public) <-> meter (wire) conversion, at the boundary and scalars."""

import pytest

import zenapi as drv
from zenapi.utils import m_to_um, to_um, um_to_m


def test_scalar_conversions():
    assert to_um(1, "mm") == 1000.0
    assert to_um(1, "m") == 1e6
    assert to_um(5, "um") == 5.0
    assert um_to_m(1000) == pytest.approx(1e-3)
    assert m_to_um(1.5e-3) == pytest.approx(1500.0)


def test_unknown_unit_raises():
    with pytest.raises(ValueError):
        to_um(1, "furlong")


def test_move_xy_builds_meters_on_the_wire(fake_client):
    client, scope = fake_client
    drv.set_stage_limits(x_min=-1e6, x_max=1e6, y_min=-1e6, y_max=1e6, z_min=-1e6, z_max=1e6)
    drv.move_xy(client, 1000, 2000)  # micrometers
    assert scope.x_m == pytest.approx(1e-3)
    assert scope.y_m == pytest.approx(2e-3)


def test_get_xy_returns_micrometers(fake_client):
    client, scope = fake_client
    scope.x_m = 1.5e-3
    assert drv.get_xy(client)["x_um"] == pytest.approx(1500.0)
