"""Every route the page's target acquisition speaks, at the address it answers.

The routes that open a session, drive the stage, read and apply settings,
capture and serve the pictures were the bridge's own, at ``/api/<verb>`` and
``/view/``. They are target acquisition's: the bridge's general part runs any
workflow and knows no instrument. So they answer under the workflow's own
folder like the rest of its routes, and the map below says, one to one, where
each one went. Nothing answers at the old address any more, and nothing is
registered that is not on the map.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from zmart_interface.framework.bridge import server, workflows

OURS = "/api/target_acquisition/"

#: Where each route answered before, and where it answers now.
MOVED = {
    ("GET", "/api/instruments"): ("GET", OURS + "instruments"),
    ("POST", "/api/connect"): ("POST", OURS + "connect"),
    ("POST", "/api/disconnect"): ("POST", OURS + "disconnect"),
    ("GET", "/api/info"): ("GET", OURS + "info"),
    ("GET", "/api/setting"): ("GET", OURS + "setting"),
    ("GET", "/api/xyz"): ("GET", OURS + "xyz"),
    ("POST", "/api/xyz"): ("POST", OURS + "xyz"),
    ("GET", "/api/acquisition_settings"): ("GET", OURS + "acquisition_settings"),
    ("POST", "/api/state"): ("POST", OURS + "state"),
    ("POST", "/api/acquire"): ("POST", OURS + "acquire"),
    ("GET", "/api/viewer"): ("GET", OURS + "viewer"),
}

#: The workflow's own routes, which were under its folder already.
STAYED = [
    ("POST", "focus/begin"), ("POST", "focus/score"), ("POST", "focus/stop"), ("POST", "focus/end"),
    ("GET", "focus/measure"),
    ("POST", "scan"), ("GET", "scan"), ("POST", "scan/stop"),
    ("POST", "targets/discover"), ("GET", "targets/discover"), ("POST", "targets/discover/stop"),
    ("POST", "plots/compute"), ("GET", "plots/compute"), ("POST", "plots/compute/stop"),
    ("GET", "plots/columns"),
    ("POST", "targets/acquire/begin"), ("POST", "targets/acquire/focus"),
    ("POST", "targets/acquire/landed"), ("POST", "targets/acquire/end"), ("GET", "targets/acquire"),
    ("POST", "targets/raise"),
    ("GET", "protocols"), ("POST", "protocols"), ("POST", "protocol"), ("POST", "protocol/save"),
]

#: The pictures, ``/view/<kind>/<name>``, now a prefix under the folder.
PICTURES = (("GET", "/view/"), ("GET", OURS + "view/"))


def the_table(monkeypatch):
    """The routes as the bridge registers them: its own, and every workflow's half's."""
    monkeypatch.setattr(server, "ROUTES", dict(server.ROUTES))
    monkeypatch.setattr(server, "PREFIX_ROUTES", dict(server.PREFIX_ROUTES))
    workflows.load_halves(server.add_route)
    return set(server.ROUTES), set(server.PREFIX_ROUTES)


def test_thirty_six_routes_and_the_pictures_are_on_the_map():
    assert len(MOVED) + len(STAYED) == 36


def test_every_route_answers_at_its_new_address_and_nothing_else_is_registered(monkeypatch):
    exact, prefixes = the_table(monkeypatch)
    expected = set(MOVED.values()) | {(method, OURS + path) for method, path in STAYED}
    assert exact == expected
    assert prefixes == {PICTURES[1]}


def test_nothing_answers_at_an_old_address(monkeypatch):
    exact, prefixes = the_table(monkeypatch)
    assert not exact & set(MOVED)
    assert PICTURES[0] not in prefixes
