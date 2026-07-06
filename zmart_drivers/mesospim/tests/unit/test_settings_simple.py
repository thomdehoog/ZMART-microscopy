"""The exact script the driver injects to change a setting.

Self-contained: it only builds the injected script -- no client, no server, no
fixtures. This is the whole Python the driver sends over the socket; mesoSPIM
runs it with ``self`` == the live Core.
"""

from __future__ import annotations

from mesospim.connection.scripts import build_script


def test_setting_change_injects_this_script():
    # build the script for one setting change (here: the emission filter)
    script = build_script("set_state", {"settings": {"filter": "561/LP"}}, "N")

    # this is exactly what gets injected and run inside mesoSPIM
    assert script == (
        "# zmart-cmd: set_state\n"
        "import json as _zjson, base64 as _zb64, traceback as _ztb\n"
        "def _zmart_emit(_obj):\n"
        "    _zpayload = _zb64.b64encode(_zjson.dumps(_obj).encode('utf-8')).decode('ascii')\n"
        "    print('<<<ZMART-RESULT:N|' + _zpayload + '|N:ZMART-END>>>')\n"
        "try:\n"
        '    _a = _zjson.loads(\'{"settings": {"filter": "561/LP"}}\')\n'
        "    _settings = dict(_a['settings'])\n"
        "    self.sig_state_request_and_wait_until_done.emit(_settings)\n"
        "    _result = {'applied': _settings}\n"
        "    _zmart_emit({'ok': True, 'data': _result})\n"
        "except Exception:\n"
        "    _zmart_emit({'ok': False, 'error': _ztb.format_exc()})\n"
    )
