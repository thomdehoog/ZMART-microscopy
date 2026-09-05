"""The Setup: forwards to the driver, fills in what the driver left unsaid, and closes once."""

from __future__ import annotations

import pytest

from zmart_setup import layer, registry


@pytest.fixture(autouse=True)
def _a_clean_registry(monkeypatch):
    monkeypatch.setattr(registry, "REGISTRY", {})


class _Driver:
    """A driver that remembers what it was asked."""

    def __init__(self):
        self.asked = []
        self.closed = 0

    def ops(self, *, with_optional=True):
        ops = {
            "open": lambda connection: {"connection": connection},
            "close": self._close,
            "describe": lambda h: {
                "label": "Test scope",
                "checks": {"driver": "answering"},
                "subsystems": {"limits": {"supported": True, "axes": ["x_um"]},
                               "origin": {"supported": False}},
            },
            "where": lambda h: {"x_um": 1.0, "y_um": 2.0, "z_um": 3.0},
            "move": lambda h, x, y, z: {"x_um": x, "y_um": y, "z_um": z},
            "acquire": lambda h, *, into, name, z_um=None: {"images": [f"{into}/{name}"], "z_um": z_um},
            "read": lambda h, subsystem: {"subsystem": subsystem, "source": "default"},
            "publish": lambda h, subsystem, document: {"subsystem": subsystem, "document": document},
        }
        if with_optional:
            ops["objective"] = lambda h: {"slot": 0, "name": "10x"}
        return ops

    def _close(self, handle):
        self.closed += 1


CONNECTION = {"vendor": "v", "microscope": "m", "api": "a"}


@pytest.fixture
def driver():
    return _Driver()


def test_describe_answers_for_every_subsystem_even_the_unsaid(driver):
    registry.register(CONNECTION, ops=driver.ops())
    setup = layer.open_setup(CONNECTION)
    said = setup.describe()
    assert set(said["subsystems"]) == set(registry.SUBSYSTEMS)
    assert said["subsystems"]["limits"] == {"supported": True, "axes": ["x_um"]}
    assert said["subsystems"]["origin"] == {"supported": False}
    assert said["subsystems"]["orientation"] == {"supported": False}
    assert said["can"] == {"objective": True, "objectives": False, "markers": False}
    assert setup.supports("limits") and not setup.supports("calibration")


def test_the_vocabulary_forwards_and_answers_what_the_driver_said(driver, tmp_path):
    registry.register(CONNECTION, ops=driver.ops())
    setup = layer.open_setup({**CONNECTION, "password": "p"})
    assert setup.context == CONNECTION
    assert setup.where() == {"x_um": 1.0, "y_um": 2.0, "z_um": 3.0}
    assert setup.move(4, 5, 6) == {"x_um": 4.0, "y_um": 5.0, "z_um": 6.0}
    assert setup.acquire(into=tmp_path, name="home")["images"] == [f"{tmp_path}/home"]
    assert setup.objective() == {"slot": 0, "name": "10x"}
    assert setup.read("limits")["subsystem"] == "limits"
    assert setup.publish("origin", {"x_um": 0})["document"] == {"x_um": 0}


def test_an_optional_op_the_driver_lacks_is_a_plain_refusal(driver):
    registry.register(CONNECTION, ops=driver.ops(with_optional=False))
    setup = layer.open_setup(CONNECTION)
    assert setup.can("objective") is False
    with pytest.raises(RuntimeError, match="cannot report which objective"):
        setup.objective()
    with pytest.raises(RuntimeError, match="no markers"):
        setup.markers()


def test_an_unknown_subsystem_is_refused_before_the_driver_sees_it(driver):
    registry.register(CONNECTION, ops=driver.ops())
    setup = layer.open_setup(CONNECTION)
    with pytest.raises(ValueError, match="unknown subsystem"):
        setup.read("colour")
    with pytest.raises(ValueError, match="is a dict"):
        setup.publish("limits", "not a document")


def test_close_is_once_and_then_everything_refuses(driver):
    registry.register(CONNECTION, ops=driver.ops())
    setup = layer.open_setup(CONNECTION)
    setup.close()
    setup.close()
    assert driver.closed == 1
    assert setup.closed
    with pytest.raises(RuntimeError, match="closed"):
        setup.where()
