"""The exact script the driver injects to change a setting.

Self-contained: it only builds the injected script -- no client, no server, no
fixtures. This is the whole Python the driver sends over the socket; mesoSPIM
runs it with ``self`` == the live Core. It is kept deliberately plain so it can
be read, tweaked, and ``regex``-ed by hand in the Remote Scripting window.
"""

from __future__ import annotations

from mesospim.connection.scripts import build_script


def test_setting_change_injects_this_script():
    # build the script for one setting change (here: the emission filter)
    script = build_script("set_state", {"settings": {"filter": "561/LP"}})

    # this is exactly what gets injected and run inside mesoSPIM
    assert script == (
        "# zmart-cmd: set_state\n"
        "import json, traceback\n"
        "try:\n"
        "    _a = {'settings': {'filter': '561/LP'}}\n"
        "    _settings = dict(_a['settings'])\n"
        "    self.sig_state_request_and_wait_until_done.emit(_settings)\n"
        "    _result = {'applied': _settings}\n"
        "    print('__ZMART_OK__' + json.dumps(_result))\n"
        "except Exception:\n"
        "    print('__ZMART_ERR__' + json.dumps(traceback.format_exc()))\n"
    )
