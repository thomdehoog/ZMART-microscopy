"""The dispatch backbone: fire/retry/confirm, with fake fire+confirm callables."""

from __future__ import annotations

from mesospim.commands.dispatch import confirm_and_fire
from mesospim.config.profiles import CommandProfile
from mesospim.protocol import Reply


def _ok(data=None):
    return Reply(ok=True, data=data or {})


def test_fire_no_confirm_success():
    prof = CommandProfile(confirm_fn=None)
    r = confirm_and_fire(None, "x", prof, fire_fn=lambda: _ok({"v": 1}), confirm_fn=None)
    assert r["success"] and r["confirmed"] is None and r["data"] == {"v": 1}


def test_nak_is_failure():
    prof = CommandProfile()
    r = confirm_and_fire(
        None, "x", prof, fire_fn=lambda: Reply(ok=False, error="bad"), confirm_fn=None
    )
    assert not r["success"] and "server rejected" in r["message"]


def test_transient_retry_then_success():
    calls = {"n": 0}

    def fire():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("flaky")
        return _ok()

    prof = CommandProfile(max_retries=3, confirm_fn=None)
    r = confirm_and_fire(None, "x", prof, fire_fn=fire, confirm_fn=None)
    assert r["success"] and r["timing"]["attempts"] == 3


def test_transient_exhausted_fails():
    def fire():
        raise TimeoutError("gone")

    prof = CommandProfile(max_retries=1, confirm_fn=None)
    r = confirm_and_fire(None, "x", prof, fire_fn=fire, confirm_fn=None)
    assert not r["success"] and "transport failed" in r["message"]


def test_confirm_success():
    prof = CommandProfile(max_confirm_attempts=3)

    def confirm(client, observed_after):
        return {"confirmed": True, "value": 5}

    r = confirm_and_fire(None, "x", prof, fire_fn=_ok, confirm_fn=confirm)
    assert r["success"] and r["confirmed"] is True and r["data"]["value"] == 5


def test_confirm_exhausted_success_on_unconfirmed():
    prof = CommandProfile(max_confirm_attempts=2, success_on_unconfirmed=True)
    r = confirm_and_fire(
        None, "x", prof, fire_fn=_ok, confirm_fn=lambda c, observed_after: {"confirmed": False}
    )
    assert r["success"] and r["confirmed"] is False


def test_confirm_exhausted_hard_fail():
    prof = CommandProfile(max_confirm_attempts=2, success_on_unconfirmed=False)
    r = confirm_and_fire(
        None, "x", prof, fire_fn=_ok, confirm_fn=lambda c, observed_after: {"confirmed": False}
    )
    assert not r["success"] and r["confirmed"] is False


def test_refire_on_unconfirmed_calls_fire_again():
    fires = {"n": 0}

    def fire():
        fires["n"] += 1
        return _ok()

    prof = CommandProfile(
        max_confirm_attempts=3, refire_on_unconfirmed=True, success_on_unconfirmed=True
    )
    confirm_and_fire(
        None, "x", prof, fire_fn=fire, confirm_fn=lambda c, observed_after: {"confirmed": False}
    )
    # initial fire + one re-fire per attempt before the last -> > 1
    assert fires["n"] > 1


def test_single_confirm_attempt_disables_refire():
    # __post_init__ guard: 1 attempt cannot re-fire.
    prof = CommandProfile(max_confirm_attempts=1, refire_on_unconfirmed=True)
    assert prof.refire_on_unconfirmed is False
