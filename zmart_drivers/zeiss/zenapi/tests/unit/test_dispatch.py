"""The dumb backbone: fire/retry/confirm/re-fire over a synthetic fire_fn."""

import pytest
from mock_zen_api import build_fake_client

from zenapi.commands.dispatch import confirm_and_fire


@pytest.fixture
def client():
    c, _ = build_fake_client()
    yield c
    c.close()


def _ok_fire(value="V"):
    def fire():
        return {"success": True, "error": None, "transient": None, "value": value, "logs": []}

    return fire


def test_success_without_confirm(client):
    r = confirm_and_fire(client, "op", fire_fn=_ok_fire("X"))
    assert r["success"] is True
    assert r["confirmed"] is None
    assert r["value"] == "X"


def test_confirm_success(client):
    r = confirm_and_fire(
        client, "op", fire_fn=_ok_fire(),
        confirm_fn=lambda: {"success": True, "logs": []},
        max_confirm_attempts=1, refire_on_unconfirmed=False,
    )
    assert r["success"] is True and r["confirmed"] is True


def test_transient_retry_then_success(client):
    calls = {"n": 0}

    def fire():
        calls["n"] += 1
        if calls["n"] < 3:
            return {"success": False, "error": "busy", "transient": True, "value": None, "logs": []}
        return {"success": True, "error": None, "transient": None, "value": "ok", "logs": []}

    r = confirm_and_fire(client, "op", fire_fn=fire, max_retries=3)
    assert r["success"] is True
    assert calls["n"] == 3


def test_permanent_fails_immediately(client):
    calls = {"n": 0}

    def fire():
        calls["n"] += 1
        return {"success": False, "error": "invalid", "transient": False, "value": None, "logs": []}

    r = confirm_and_fire(client, "op", fire_fn=fire, max_retries=3)
    assert r["success"] is False
    assert calls["n"] == 1  # no retry on permanent


def test_unconfirmed_is_soft_success(client):
    r = confirm_and_fire(
        client, "op", fire_fn=_ok_fire(),
        confirm_fn=lambda: {"success": False, "logs": []},
        max_confirm_attempts=1, refire_on_unconfirmed=False, success_on_unconfirmed=True,
    )
    assert r["success"] is True
    assert r["confirmed"] is False


def test_refire_on_unconfirmed_reconfirms(client):
    fires = {"n": 0}
    confirms = {"n": 0}

    def fire():
        fires["n"] += 1
        return {"success": True, "error": None, "transient": None, "value": "v", "logs": []}

    def confirm():
        confirms["n"] += 1
        return {"success": confirms["n"] >= 2, "logs": []}

    r = confirm_and_fire(
        client, "op", fire_fn=fire, confirm_fn=confirm,
        max_confirm_attempts=3, refire_on_unconfirmed=True,
    )
    assert r["success"] is True and r["confirmed"] is True
    assert fires["n"] == 2  # initial fire + one re-fire before the 2nd confirm
    assert confirms["n"] == 2
