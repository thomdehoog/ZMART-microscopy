"""The dispatch backbone: fire/retry/confirm, with fake fire+confirm callables."""

from __future__ import annotations

from mesospim.commands.dispatch import confirm_and_fire
from mesospim.config.profiles import CommandProfile
from mesospim.connection.client import MesospimError
from mesospim.protocol import Reply
from mesospim.readers.readers import Reading, _reading_value_after


def _ok(data=None):
    return Reply(ok=True, data=data or {})


def test_fire_no_confirm_success():
    prof = CommandProfile()
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

    prof = CommandProfile(max_retries=3)
    r = confirm_and_fire(None, "x", prof, fire_fn=fire, confirm_fn=None)
    assert r["success"] and r["timing"]["attempts"] == 3


def test_transient_exhausted_fails():
    def fire():
        raise TimeoutError("gone")

    prof = CommandProfile(max_retries=1)
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


def test_freshness_gate_rejects_pre_fire_readback():
    # A reading taken BEFORE the command fired must never confirm it: the gate
    # feeds confirm_fn an observed_after stamped at fire time.
    stale = Reading.now({"x": 1.0})  # observed before confirm_and_fire runs

    def confirm(client, observed_after):
        value = _reading_value_after(stale, observed_after)
        return {"confirmed": value is not None}

    prof = CommandProfile(max_confirm_attempts=2, success_on_unconfirmed=False)
    r = confirm_and_fire(None, "x", prof, fire_fn=_ok, confirm_fn=confirm)
    assert not r["success"] and r["confirmed"] is False


def test_fresh_readback_confirms():
    # A reading taken AFTER the fire passes the gate and confirms.
    def confirm(client, observed_after):
        fresh = Reading.now({"x": 1.0})
        return {"confirmed": _reading_value_after(fresh, observed_after) is not None}

    prof = CommandProfile(max_confirm_attempts=2)
    r = confirm_and_fire(None, "x", prof, fire_fn=_ok, confirm_fn=confirm)
    assert r["success"] and r["confirmed"] is True


def test_unexpected_fire_error_returns_envelope_not_exception():
    # A non-transient, non-NAK error (e.g. a ProtocolError on a garbled reply)
    # must be converted to a failed envelope, not raised.
    from mesospim.protocol import ProtocolError

    def fire():
        raise ProtocolError("garbled reply line")

    prof = CommandProfile()
    r = confirm_and_fire(None, "x", prof, fire_fn=fire, confirm_fn=None)
    assert not r["success"] and "unexpected error" in r["message"]


def test_refire_nak_returns_envelope_not_exception():
    # A NAK on re-fire is permanent, not a crash: the caller still gets the
    # standard envelope (regression for the un-caught MesospimError bug).
    fires = {"n": 0}

    def fire():
        fires["n"] += 1
        if fires["n"] == 1:
            return _ok()
        raise MesospimError("rejected on re-fire")

    prof = CommandProfile(
        max_confirm_attempts=3, refire_on_unconfirmed=True, success_on_unconfirmed=True
    )
    r = confirm_and_fire(
        None, "x", prof, fire_fn=fire, confirm_fn=lambda c, observed_after: {"confirmed": False}
    )
    assert r["success"] and r["confirmed"] is False
    assert fires["n"] > 1  # it did attempt the re-fire
