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
    "check_calibration",
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
    for step in _ORDERED_STEPS[5:8]:
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
    for artifact in ("summary.json", "run_layout.png", "curation.json", "calibration_check.json"):
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
    for step in ("check_calibration", "run_overview", "discover_targets"):
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
