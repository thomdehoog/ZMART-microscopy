"""What one setting change sends over the wire, and that it lands.

Self-contained: no client, no server, no fixtures. A setting change is a single
named call -- plain JSON data, not code -- that the server dispatches through its
fixed allowlist. Kept deliberately simple so it can be read, tweaked, and
``regex``-ed by hand.
"""

from __future__ import annotations

from mesospim.connection import command_api
from mesospim.protocol import encode_call


def test_setting_change_sends_this_call():
    # one setting change (here: the emission filter) becomes one named call
    call = encode_call("set_state", {"settings": {"filter": "561/LP"}})

    # this exact JSON is the whole request -- data, not code: {method: args}
    assert call == '{"set_state": {"settings": {"filter": "561/LP"}}}'


def test_the_call_is_dispatched_and_the_state_reads_back():
    # a tiny Core-shaped stand-in: set_state emits a signal that updates state
    class _Sig:
        def __init__(self, core):
            self.core = core

        def emit(self, settings):
            self.core.state.update(settings)

    class _Core:
        def __init__(self):
            self.state = {"filter": "515/30"}
            self.sig_state_request_and_wait_until_done = _Sig(self)

    core = _Core()

    # dispatch the same call the client would send
    command_api.run(core, "set_state", {"settings": {"filter": "561/LP"}})

    # the state now reads back the new filter -- the change landed
    assert core.state["filter"] == "561/LP"


def test_an_unknown_call_is_rejected_by_the_allowlist():
    # the table IS the allowlist: a name not in it never runs
    import pytest

    with pytest.raises(KeyError):
        command_api.run(object(), "rm_rf_everything", {})
