"""The web interface: the notebook's flow, served to a plain browser.

Three layers, tested separately so a failure names its culprit:

- the FLOW: every notebook step runs in order against the simulated
  microscope, with the operator's clicks (Measure, Acquire, a verdict)
  arriving as widget messages — the web twin of the notebook
  end-to-end test;
- the HTTP surface: the page, the widget modules, the state snapshot,
  the event stream, and the message/trait/action posts;
- the page's promises: it embeds no code and fetches nothing from the
  internet.

A real-browser (Playwright) pass lives in ``test_webapp_browser.py``.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402

pytest.importorskip("anywidget")

from workflow.webapp import RunFlow, WidgetHub, make_server  # noqa: E402

_ORDERED_STEPS = [
    "connect",
    "set_origin",
    "capture_overview_job",
    "capture_target_job",
    "load_positions",
    "run_overview",
    "discover_targets",
    "save_results",
    "disconnect",
]


def _run_demo_flow(tmp_path: Path) -> tuple[WidgetHub, RunFlow]:
    """Drive the full demo run the way the buttons would, and return it."""
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    for step in _ORDERED_STEPS[:5]:
        assert flow.run_step(step)
    hub.drain()
    # The operator presses Measure in the focus panel...
    hub.dispatch_message("focus", {"type": "measure"})
    for step in _ORDERED_STEPS[5:7]:
        flow.run_step(step)
    hub.drain(120)
    # ...acquires two cells, and judges the first pair good.
    hub.dispatch_message("gallery", {"type": "acquire", "count": "2"})
    hub.drain(120)
    hub.dispatch_message("gallery", {"type": "verdict", "index": 0, "value": "good"})
    flow.run_step("save_results")
    flow.run_step("disconnect")
    hub.drain(60)
    return hub, flow


def test_demo_flow_runs_the_whole_notebook_order(tmp_path):
    hub, flow = _run_demo_flow(tmp_path)
    assert flow.completed == _ORDERED_STEPS
    # The same assertions the notebook end-to-end test makes about a run.
    assert len(flow.viewer.overviews) == 4
    assert len(flow.targets) >= 4
    assert len(flow.gallery.records) == 2 == len(flow.gallery.picked)
    assert flow.gallery._verdicts[0] == "good"
    root = tmp_path / "run"
    for artifact in ("summary.json", "run_layout.png", "curation.json"):
        assert (root / artifact).exists(), artifact
    assert flow.session.disconnected and flow.engine.shut_down
    # The checklist read the simulated session like a real one.
    rows = {row["label"]: row for row in flow.status_widget.rows}
    assert rows["Microscope"]["state"] == "warn"
    assert "disconnected" in rows["Microscope"]["detail"]


def test_steps_refuse_out_of_order_with_plain_sentences(tmp_path):
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    events: list[dict] = []
    original = hub.broadcast
    hub.broadcast = lambda event: (events.append(event), original(event))[1]
    flow.run_step("run_overview")  # long before its prerequisites
    hub.drain()
    failed = [e for e in events if e.get("kind") == "flow" and e.get("state") == "failed"]
    assert failed and "capture the overview job first" in failed[0]["message"]
    assert "Traceback" not in failed[0]["message"]


def test_cancel_is_applied_immediately_not_queued(tmp_path):
    """The concurrent-host promise: cancel does not wait behind the worker."""
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    for step in _ORDERED_STEPS[:5]:
        flow.run_step(step)
    hub.drain()
    hub.dispatch_message("focus", {"type": "measure"})
    for step in ("run_overview", "discover_targets"):
        flow.run_step(step)
    hub.drain(120)
    gallery = flow.gallery

    blocker = threading.Event()
    hub.submit(blocker.wait)  # the worker is now busy, like a running cell
    try:
        gallery._set_busy(True)  # a run is in flight on the worker
        hub.dispatch_message("gallery", {"type": "cancel"})
        # No drain: the flag must already be set although the worker is stuck.
        assert gallery._cancel_requested is True
    finally:
        gallery._set_busy(False)
        blocker.set()
    hub.drain()


@pytest.fixture()
def demo_server(tmp_path):
    server, hub, flow = make_server(port=0, demo=True, demo_root=tmp_path / "run")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base, hub, flow
    finally:
        server.shutdown()
        server.server_close()


def _get(base: str, path: str) -> bytes:
    return urllib.request.urlopen(base + path, timeout=10).read()


def _post(base: str, path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(request, timeout=10).read())


def test_http_surface_serves_page_modules_state_and_actions(demo_server):
    base, hub, flow = demo_server

    page = _get(base, "/").decode("utf-8")
    assert "ZMART target acquisition" in page
    # The operator page shows no code and fetches nothing from the internet.
    # (The one allowed "http" string is the inline favicon's SVG namespace
    # identifier — an XML name, never a network request.)
    fetchable = page.replace(base, "").replace("http://www.w3.org/2000/svg", "")
    assert "http://" not in fetchable and "https://" not in fetchable
    for code_marker in ("def ", "import workflow", "self.", "zmart_controller."):
        assert code_marker not in page, code_marker

    state = json.loads(_get(base, "/state"))
    assert set(state["widgets"]) >= {"status", "overview"}
    assert state["flow"] == {"completed": [], "demo": True}

    esm = _get(base, "/esm/overview.mjs").decode("utf-8")
    assert "export default" in esm and "createRoot" in esm

    assert _post(base, "/action", {"step": "connect"}) == {"ok": True}
    hub.drain(60)
    state = json.loads(_get(base, "/state"))
    assert state["flow"]["completed"] == ["connect"]
    rows = {row["label"]: row for row in state["widgets"]["status"]["rows"]}
    assert rows["Microscope"]["state"] == "ok"

    # Unknown things answer with a clean 404, never a stack trace.
    for bad in ("/esm/nope.mjs", "/buffer/nope"):
        with pytest.raises(urllib.error.HTTPError) as err:
            _get(base, bad)
        assert err.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as err:
        _post(base, "/msg", {"widget": "nope", "content": {}})
    assert err.value.code == 404


def test_streamed_tiles_reach_a_tab_as_events_and_binary_buffers(demo_server):
    base, hub, flow = demo_server

    events: list[dict] = []
    ready = threading.Event()

    def _listen() -> None:
        with urllib.request.urlopen(base + "/events", timeout=60) as stream:
            ready.set()
            for raw in stream:
                line = raw.decode("utf-8").strip()
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: ") :]))
                    if any(
                        e.get("kind") == "flow"
                        and e.get("step") == "run_overview"
                        and e.get("state") == "done"
                        for e in events
                    ):
                        return

    listener = threading.Thread(target=_listen, daemon=True)
    listener.start()
    assert ready.wait(10)

    for step in _ORDERED_STEPS[:5]:
        _post(base, "/action", {"step": step})
    hub.drain(60)
    _post(base, "/msg", {"widget": "focus", "content": {"type": "measure"}})
    _post(base, "/action", {"step": "run_overview"})
    listener.join(timeout=120)
    assert not listener.is_alive(), "the overview never finished streaming"

    tile_messages = [
        e
        for e in events
        if e.get("kind") == "msg"
        and e.get("widget") == "overview"
        and e.get("content", {}).get("type") == "tile"
    ]
    assert len(tile_messages) == 4  # one live message per tile, as in Jupyter
    png = _get(base, f"/buffer/{tile_messages[0]['buffers'][0]}")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # pixels travel as real binary
    # The focus panel widget announced itself so the page could mount it.
    assert any(e == {"kind": "widget", "widget": "focus"} for e in events)


# ---------------------------------------------------------------------------
# Adversarial: everything below is a hostile page script, a confused
# client, or plain bad luck — none of it may reach hardware state, crash
# the server, or wedge the worker.
# ---------------------------------------------------------------------------


def _post_raw(base: str, path: str, data: bytes, content_type="application/json"):
    request = urllib.request.Request(base + path, data=data, headers={"Content-Type": content_type})
    return urllib.request.urlopen(request, timeout=10)


def test_malformed_requests_get_clean_answers_and_the_server_survives(demo_server):
    base, hub, flow = demo_server
    bad_bodies = [
        b"",  # no body at all
        b"not json {{{",
        b"[1, 2, 3]",  # JSON, but not an object
        b'"just a string"',
        json.dumps({"step": None}).encode(),
        json.dumps({"widget": 42, "content": None}).encode(),
        json.dumps({"widget": "gallery"}).encode(),  # no content at all
        json.dumps({"widget": "overview", "changes": "not-a-dict"}).encode(),
    ]
    for path in ("/action", "/msg", "/trait"):
        for body in bad_bodies:
            try:
                _post_raw(base, path, body)
            except urllib.error.HTTPError as err:
                assert err.code in (400, 404), (path, body, err.code)
    # An unknown GET, a traversal probe, and an unknown POST all answer too.
    for path in ("/secret", "/../etc/passwd", "/esm/../__init__.mjs"):
        try:
            _get(base, path)
        except urllib.error.HTTPError as err:
            assert err.code == 404
    # After all of that the server still works and the worker still turns.
    assert _post(base, "/action", {"step": "connect"}) == {"ok": True}
    hub.drain(60)
    assert flow.completed == ["connect"]


def test_forged_traits_and_messages_cannot_move_python_truth(demo_server):
    """The HTTP surface is exactly as forgeable as a browser page — and the
    widgets' healing must hold across it, because this is the very
    'website host' PROTOCOL.md promises the same safety for."""
    base, hub, flow = demo_server
    for step in _ORDERED_STEPS[:5]:
        _post(base, "/action", {"step": step})
    hub.drain(60)
    _post(base, "/msg", {"widget": "focus", "content": {"type": "measure"}})
    for step in ("run_overview", "discover_targets"):
        _post(base, "/action", {"step": step})
    hub.drain(120)

    explorer, gallery = flow.explorer, flow.gallery
    explorer.toggle_pick(0)
    # Forge every healed trait over HTTP, exactly like a hostile page.
    _post(base, "/trait", {"widget": "gallery", "changes": {"busy": True, "read_only": True}})
    _post(
        base,
        "/trait",
        {
            "widget": "explorer",
            "changes": {
                "picked_indices": [],
                "acquired_indices": [0, 1, 2],
                "gated_mask": [False] * len(explorer.targets),
                "x_feature": "no_such_feature",
            },
        },
    )
    _post(base, "/trait", {"widget": "gallery", "changes": {"verdicts": ["good"] * 50}})
    _post(
        base,
        "/msg",
        {"widget": "gallery", "content": {"type": "verdict", "index": 10**9, "value": "good"}},
    )
    _post(base, "/msg", {"widget": "gallery", "content": {"type": "acquire", "count": "no thanks"}})
    hub.drain(60)

    assert gallery.busy is False and gallery.read_only is False
    assert gallery._hardware_allowed is True
    assert explorer.picked_indices == [0] and explorer._picked == {0}
    assert explorer.acquired_indices == [] and explorer._acquired == set()
    assert explorer.x_feature in explorer.features
    assert list(gallery.verdicts) == gallery._verdicts == []
    assert "failed: target count must be a positive whole number" in gallery.status

    # And the real controls still work afterwards.
    _post(base, "/msg", {"widget": "gallery", "content": {"type": "acquire", "count": "1"}})
    hub.drain(120)
    assert len(gallery.records) == 1


def test_a_stalled_event_stream_client_is_dropped_not_waited_on(demo_server):
    base, hub, flow = demo_server
    # A tab that connects and never reads: its queue fills, then it is
    # dropped — meanwhile a healthy run keeps streaming to Python state.
    stalled = hub.add_client()
    for i in range(5000):
        hub.broadcast({"kind": "flow", "step": "noise", "state": "running", "message": str(i)})
    assert stalled not in hub._clients  # dropped once its queue overflowed
    _post(base, "/action", {"step": "connect"})
    hub.drain(60)
    assert flow.completed == ["connect"]


def test_buffer_store_stays_bounded_under_a_flood(demo_server):
    base, hub, flow = demo_server
    from workflow.webapp import _host

    for _ in range(80):
        hub._store_buffer(b"x" * (1024 * 1024))  # 80 MiB offered
    assert hub._buffer_bytes <= _host._BUFFER_CAP_BYTES
    # Old ids expire with a clean 404; fresh ones still serve.
    fresh = hub._store_buffer(b"\x89PNG fresh")
    assert _get(base, f"/buffer/{fresh}") == b"\x89PNG fresh"


def test_double_clicks_and_repeat_steps_stay_idempotent(demo_server):
    base, hub, flow = demo_server
    for _ in range(3):  # a triple-clicked Connect button
        _post(base, "/action", {"step": "connect"})
    hub.drain(60)
    assert flow.completed == ["connect"]  # once done, once listed
    # The repeat attempts refused with a sentence, not a second session.
    session = flow.session
    _post(base, "/action", {"step": "connect"})
    hub.drain(60)
    assert flow.session is session
