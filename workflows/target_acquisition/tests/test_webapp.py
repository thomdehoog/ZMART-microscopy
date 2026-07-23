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
import queue
import re
import threading
import time
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
    # Discovery links the cells onto the overview map: one mark per target,
    # each carrying its gated/picked/acquired state for the map to colour.
    assert len(flow.viewer.marks) == len(flow.targets)
    assert all(set(m) >= {"x", "y", "gated", "picked", "acquired"} for m in flow.viewer.marks)
    assert len(flow.gallery.records) == 2 == len(flow.gallery.picked)
    assert flow.gallery._verdicts[0] == "good"
    root = flow.root
    assert root.parent == tmp_path / "run"
    assert root.name.startswith("target-acquisition_")
    for artifact in (
        "summary.json",
        "run_layout.png",
        "overview_targets.png",  # the overview mosaic with acquired targets on top
        "curation.json",
        "run_journal.jsonl",  # the timestamped step-by-step record
    ):
        assert (root / artifact).exists(), artifact
    # The journal recorded the run as it happened: a line per step event.
    journal = [
        json.loads(line)
        for line in (root / "run_journal.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert any(e["step"] == "connect" and e["state"] == "done" for e in journal)
    assert any(e["step"] == "save_results" and e["state"] == "done" for e in journal)
    assert flow.session.disconnected and flow.engine.shut_down
    # The checklist read the simulated session like a real one.
    rows = {row["label"]: row for row in flow.status_widget.rows}
    assert rows["Microscope"]["state"] == "warn"
    assert "disconnected" in rows["Microscope"]["detail"]


def test_reset_requires_connection_then_safely_disconnects_and_starts_fresh(tmp_path):
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")

    with pytest.raises(RuntimeError, match="connect before restarting"):
        flow.reset()

    flow.run_step("connect")
    hub.drain(60)
    first_root = flow.root
    first_viewer = flow.viewer
    first_session = flow.session
    first_engine = flow.engine

    flow.reset()

    assert first_session.disconnected and first_engine.shut_down
    assert flow.completed == []
    assert flow.session is None and flow.engine is None and flow.root is None
    assert flow.viewer is not first_viewer
    assert set(hub.state_snapshot()) == {"status", "overview"}
    assert hub.widget("focus") is None
    assert hub.widget("explorer") is None
    assert hub.widget("gallery") is None

    flow.run_step("connect")
    hub.drain(60)
    assert flow.completed == ["connect"]
    assert flow.root != first_root
    flow.run_step("disconnect")
    hub.drain(60)


def test_steps_refuse_out_of_order_with_plain_sentences(tmp_path):
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    events: list[dict] = []
    original = hub.broadcast
    hub.broadcast = lambda event: (events.append(event), original(event))[1]
    flow.run_step("run_overview")  # long before its prerequisites
    hub.drain()
    failed = [e for e in events if e.get("kind") == "flow" and e.get("state") == "failed"]
    assert failed and "finish load positions" in failed[0]["message"]
    assert "Traceback" not in failed[0]["message"]


def test_origin_must_precede_every_coordinate_dependent_step(tmp_path):
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    flow.run_step("connect")
    flow.run_step("capture_overview_job")  # deliberately skip Set origin
    hub.drain()
    assert flow.completed == ["connect"]
    assert flow.overview_state is None

    # Once positions exist, Set origin cannot be repeated and silently change
    # the frame underneath their cached coordinates.
    for step in ("set_origin", "capture_overview_job", "capture_target_job", "load_positions"):
        flow.run_step(step)
    hub.drain()
    positions = list(flow.positions)
    flow.run_step("set_origin")
    hub.drain()
    assert flow.positions == positions
    assert flow.completed.count("set_origin") == 1


def test_positions_are_loaded_only_after_restoring_overview_controller_state(tmp_path):
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    for step in _ORDERED_STEPS[:4]:
        flow.run_step(step)
    hub.drain()
    assert flow.session.job == flow.session.TARGET_JOB

    calls = []
    set_state = flow.session.set_state
    get_info = flow.session.get_info

    def tracked_set_state(state):
        calls.append(("set_state", state["changeable"]["job"]))
        return set_state(state)

    def tracked_get_info():
        calls.append(("get_info", "tile_positions"))
        return get_info()

    flow.session.set_state = tracked_set_state
    flow.session.get_info = tracked_get_info
    flow.run_step("load_positions")
    hub.drain()

    assert calls == [
        ("set_state", flow.session.OVERVIEW_JOB),
        ("get_info", "tile_positions"),
    ]
    assert flow.session.job == flow.session.OVERVIEW_JOB


def test_duplicate_overview_requests_coalesce_before_hardware(tmp_path):
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    for step in _ORDERED_STEPS[:5]:
        flow.run_step(step)
    hub.drain()
    hub.dispatch_message("focus", {"type": "measure"})
    hub.drain()

    calls = 0
    original = flow._steps["run_overview"]

    def _counted_overview():
        nonlocal calls
        calls += 1
        return original()

    flow._steps["run_overview"] = _counted_overview
    for _ in range(50):
        assert flow.run_step("run_overview")
    hub.drain(120)
    assert calls == 1
    assert len(flow.viewer.overviews) == len(flow.positions) == 4


def test_duplicate_widget_runs_and_sync_floods_are_coalesced(tmp_path):
    hub = WidgetHub()
    RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    blocker = threading.Event()
    worker_started = threading.Event()

    def _block_worker():
        worker_started.set()
        blocker.wait()

    assert hub.submit(_block_worker)
    assert worker_started.wait(10)
    try:
        for _ in range(5000):
            assert hub.dispatch_message("overview", {"type": "sync"})
        assert hub._work.qsize() == 1
    finally:
        blocker.set()
    hub.drain()


def test_sync_during_an_executing_replay_queues_one_followup(tmp_path):
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    viewer = flow.viewer
    original = viewer._route_message
    replay_started = threading.Event()
    release = threading.Event()
    calls = 0

    def blocked_route(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            replay_started.set()
            assert release.wait(10)
        return original(*args)

    viewer._route_message = blocked_route
    assert hub.dispatch_message("overview", {"type": "sync"})
    assert replay_started.wait(10)
    for _ in range(100):
        assert hub.dispatch_message("overview", {"type": "sync"})
    release.set()
    hub.drain()
    assert calls == 2


def test_stale_hardware_message_is_dropped_with_feedback(tmp_path, monkeypatch):
    from workflow.webapp import _host

    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    for step in _ORDERED_STEPS[:5]:
        flow.run_step(step)
    hub.drain()
    focus = flow.picker
    calls = 0
    original = focus._route_message

    def counted_route(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    focus._route_message = counted_route
    blocker = threading.Event()
    assert hub.submit(blocker.wait)
    monkeypatch.setattr(_host, "_STALE_HARDWARE_MESSAGE_S", -1.0)
    assert hub.dispatch_message("focus", {"type": "measure"})
    blocker.set()
    hub.drain()
    assert calls == 0
    assert "ignored a hardware action queued too long" in focus.status


def test_worker_queue_is_bounded_and_recovers_after_pressure():
    from workflow.webapp import _host

    hub = WidgetHub()
    release = threading.Event()
    started = threading.Event()

    def _block_worker():
        started.set()
        release.wait()

    assert hub.submit(_block_worker)
    assert started.wait(10)
    try:
        for _ in range(_host._WORK_QUEUE_CAP):
            assert hub.submit(lambda: None)
        assert hub.submit(lambda: None) is False
        assert hub._work.qsize() == _host._WORK_QUEUE_CAP
    finally:
        release.set()
    hub.drain()
    assert hub.submit(lambda: None) is True
    hub.drain()


def test_restart_refuses_while_an_acquisition_is_in_flight(tmp_path):
    # Restart must not queue behind a running Acquire/Measure — otherwise it
    # times out, reports failure, then disconnects the scope later anyway.
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    for step in _ORDERED_STEPS[:5]:
        flow.run_step(step)
    hub.drain()
    hub.dispatch_message("focus", {"type": "measure"})
    for step in ("run_overview", "discover_targets"):
        flow.run_step(step)
    hub.drain(120)

    flow.gallery._set_busy(True)  # an acquisition is in flight
    try:
        with pytest.raises(RuntimeError, match="target acquisition is running"):
            flow.reset()
        assert flow.session is not None  # the session was NOT torn down
    finally:
        flow.gallery._set_busy(False)
    # Once it finishes, restart works again.
    flow.reset()


def test_restart_refuses_while_work_is_merely_queued(tmp_path):
    # The TOCTOU the widget _busy flag misses: work sits on the worker queue
    # but has not started (so no _busy yet). Restart must still refuse, or it
    # queues behind that work and disconnects later after "restart failed".
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    flow.run_step("connect")
    hub.drain(60)

    started, release = threading.Event(), threading.Event()

    def _block_worker():
        started.set()
        release.wait(10)

    assert hub.submit(_block_worker)  # the worker is now busy
    assert started.wait(10)
    assert hub.submit(lambda: None)  # and a second job is queued behind it
    try:
        with pytest.raises(RuntimeError, match="microscope is busy"):
            flow.reset()
        assert flow.session is not None  # not torn down
    finally:
        release.set()
    hub.drain()


def test_release_on_shutdown_runs_after_in_flight_work_not_concurrently(tmp_path):
    # Shutdown release must serialize behind the worker, never drive the
    # session from the main thread while the worker is mid-acquisition.
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    flow.run_step("connect")
    hub.drain(60)
    assert not flow.session.disconnected

    order, started, release = [], threading.Event(), threading.Event()

    def _block_worker():
        started.set()
        release.wait(10)
        order.append("worker-done")

    assert hub.submit(_block_worker)
    assert started.wait(10)

    def _shutdown():
        flow.release_on_shutdown(timeout=10)
        order.append("released")

    shutdown = threading.Thread(target=_shutdown, daemon=True)
    shutdown.start()
    time.sleep(0.2)
    assert not flow.session.disconnected  # release has NOT run alongside the worker
    release.set()
    shutdown.join(10)
    assert order == ["worker-done", "released"]  # release ran AFTER the worker
    assert flow.session.disconnected and flow.engine.shut_down


def test_release_on_shutdown_skips_when_already_disconnected(tmp_path):
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    flow.run_step("connect")
    flow.run_step("disconnect")
    hub.drain(60)
    engine = flow.engine
    # A second release must not disconnect or shut down anything again.
    engine.shut_down = False  # if release ran, it would flip this back to True
    flow.release_on_shutdown(timeout=5)
    assert engine.shut_down is False


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
    assert page.count("ZMART-microscopy: Target acquisition") == 2
    assert "Where the run stands" not in page
    assert "The same run as the operator notebook" not in page
    assert 'id="widget-status"' not in page
    # Two-pane shell: collapsible step controls on the left, one shared
    # viewing stage on the right. The viewers mount into the stage, not into
    # the individual step sections.
    assert '<div class="shell">' in page
    assert '<div class="controls">' in page
    assert '<div class="stage" id="stage">' in page
    controls = page.split('<div class="controls">', 1)[1].split('<div class="stage"', 1)[0]
    assert "step-connect" in controls  # steps live in the left controls column
    assert 'id="widget-overview"' not in controls  # viewers are NOT in the steps
    stage = page.split('<div class="stage" id="stage">', 1)[1]
    for name in ("focus", "overview", "explorer", "gallery"):
        assert f'id="widget-{name}"' in stage  # every viewer mounts on the stage
    assert "globalThis.ZMART_WIDGET_SCALE = 2" in page
    assert 'globalThis.ZMART_WIDGET_SCALES = { explorer: 2.5 }' in page
    assert 'globalThis.ZMART_WIDGET_FILL = { gallery: true }' in page
    assert re.findall(r'<details class="step" id="step-([^"]+)"[^>]* open>', page) == [
        "connect"
    ]
    assert 'id="widget-overview" hidden' in page
    assert 'id="new-run-btn" disabled' in page
    assert "Restart workflow" in page
    assert "Available after Connect." in page
    connect_body = page.split('id="step-connect"', 1)[1].split("</details>", 1)[0]
    assert connect_body.index('data-step="connect"') < connect_body.index('id="new-run-btn"')
    assert 'content: "Collapsed"' in page and 'content: "Open"' in page
    assert 'if (ev.step === "run_overview") showOverview()' in page
    assert 'button.classList.toggle("running", ev.state === "running")' in page
    assert "@keyframes button-spin" in page
    assert 'position: absolute; left: 10px' in page
    assert ".step-btn.running { padding: 8px 2px 8px 34px; }" in page
    assert ".step.done .step-btn { background: #16a34a" in page
    assert 'connect: "Reconnect"' in page
    assert 'set_origin: "Change Origin"' in page
    assert 'capture_overview_job: "Recapture Overview Job"' in page
    assert "label.textContent = completedLabels[step]" in page
    assert 'section.dataset.opened === "true"' in page
    assert 'post("/reset", {})' in page
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


def test_reset_endpoint_refuses_unconnected_run_then_safely_resets_active_run(demo_server):
    base, hub, flow = demo_server

    with pytest.raises(urllib.error.HTTPError) as err:
        _post(base, "/reset", {})
    assert err.value.code == 409

    assert _post(base, "/action", {"step": "connect"}) == {"ok": True}
    hub.drain(60)
    first_session = flow.session
    first_engine = flow.engine

    assert _post(base, "/reset", {}) == {"ok": True}
    assert first_session.disconnected and first_engine.shut_down
    state = json.loads(_get(base, "/state"))
    assert state["flow"] == {"completed": [], "demo": True}
    assert set(state["widgets"]) == {"status", "overview"}
    assert flow.session is None and flow.root is None


def test_loopback_server_rejects_host_header_rebinding_reads(demo_server):
    base, _hub, _flow = demo_server
    for path in ("/state", "/events", "/buffer/nope"):
        request = urllib.request.Request(base + path, headers={"Host": "hostile.example"})
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(request, timeout=10)
        assert err.value.code == 403


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


def test_cross_origin_and_simple_content_type_posts_are_refused(demo_server):
    base, hub, flow = demo_server
    payload = json.dumps({"step": "connect"}).encode("utf-8")

    with pytest.raises(urllib.error.HTTPError) as err:
        _post_raw(base, "/action", payload, content_type="text/plain")
    assert err.value.code == 415

    request = urllib.request.Request(
        base + "/action",
        data=payload,
        headers={"Content-Type": "application/json", "Origin": "https://hostile.example"},
    )
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(request, timeout=10)
    assert err.value.code == 403
    hub.drain()
    assert flow.session is None and flow.completed == []


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
def test_nonstandard_json_constants_are_refused(demo_server, constant):
    base, _hub, flow = demo_server
    body = b'{"step":' + constant + b"}"
    with pytest.raises(urllib.error.HTTPError) as err:
        _post_raw(base, "/action", body)
    assert err.value.code == 400
    assert flow.session is None


def test_mistyped_trait_value_is_rejected_before_the_worker(demo_server):
    base, hub, _flow = demo_server
    body = json.dumps({"widget": "overview", "changes": {"busy": []}}).encode("utf-8")
    with pytest.raises(urllib.error.HTTPError) as err:
        _post_raw(base, "/trait", body)
    assert err.value.code == 400
    assert hub.widget("overview").busy is False


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


def test_dropped_sse_client_gets_a_disconnect_sentinel():
    hub = WidgetHub()
    client = hub.add_client()
    hub.remove_client(client)
    assert client.get_nowait() is None
    with pytest.raises(queue.Empty):
        client.get_nowait()


def test_repeated_web_saves_do_not_leak_matplotlib_figures(tmp_path):
    import matplotlib.pyplot as plt

    hub, flow = _run_demo_flow(tmp_path)
    before = set(plt.get_fignums())
    for _ in range(3):
        assert flow.run_step("save_results")
        hub.drain(60)
    assert set(plt.get_fignums()) == before


def test_failed_engine_shutdown_is_not_retried_and_session_is_released(tmp_path):
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    flow.run_step("connect")
    hub.drain()
    calls = 0

    def fail_shutdown():
        nonlocal calls
        calls += 1
        raise RuntimeError("engine stuck")

    flow.engine.shutdown = fail_shutdown
    events = []
    hub.broadcast = events.append
    for _ in range(2):
        assert flow.run_step("disconnect")
        hub.drain()
    assert calls == 1
    assert flow.session.disconnected
    assert "disconnect" not in flow.completed
    failures = [e for e in events if e.get("step") == "disconnect" and e.get("state") == "failed"]
    assert len(failures) == 2
    assert all("microscope session was still released" in e["message"] for e in failures)


def test_live_cli_registers_instrument_before_starting_server(monkeypatch):
    import sys

    from workflow.webapp import __main__ as cli

    calls = []
    monkeypatch.setattr(sys, "argv", ["workflow.webapp", "--analysis-repo", "/analysis"])
    monkeypatch.setattr(cli.importlib, "import_module", lambda name: calls.append(("import", name)))
    monkeypatch.setattr(cli, "serve", lambda **kwargs: calls.append(("serve", kwargs)))
    cli.main()
    assert calls[0] == ("import", "_bootstrap")
    assert calls[1][0] == "serve"
    assert calls[1][1]["analysis_repo"] == "/analysis"


def test_demo_cli_stays_driver_free(monkeypatch):
    import sys

    from workflow.webapp import __main__ as cli

    calls = []
    monkeypatch.setattr(sys, "argv", ["workflow.webapp", "--demo"])
    monkeypatch.setattr(
        cli.importlib,
        "import_module",
        lambda name: pytest.fail(f"demo imported driver bootstrap {name}"),
    )
    monkeypatch.setattr(cli, "serve", lambda **kwargs: calls.append(kwargs))
    cli.main()
    assert calls == [
        {
            "open_browser": False,
            "open_window": False,
            "host": "127.0.0.1",
            "port": 8765,
            "demo": True,
            "analysis_repo": None,
            "vendor": "leica",
            "demo_root": None,
            "af_job": None,
            "experiment": "target-acquisition",
        }
    ]


def test_window_flag_requests_a_native_window(monkeypatch):
    """``--window`` asks :func:`serve` to open the page in a desktop window."""
    import sys

    from workflow.webapp import __main__ as cli

    calls = []
    monkeypatch.setattr(sys, "argv", ["workflow.webapp", "--demo", "--window"])
    monkeypatch.setattr(cli, "serve", lambda **kwargs: calls.append(kwargs))
    cli.main()
    assert calls[0]["open_window"] is True


def test_window_release_hardware_even_when_the_window_fails(monkeypatch):
    """If the native window cannot open, the microscope is still released.

    A dropped hardware session is the dangerous failure, so releasing it must
    happen on every path out — including "the window engine was missing".
    """
    from workflow import webapp

    released = []

    class _FakeServer:
        def serve_forever(self):
            pass  # the background thread returns immediately in the test

        def shutdown(self):
            released.append("shutdown")

        def server_close(self):
            released.append("close")

    class _FakeFlow:
        def release_on_shutdown(self):
            released.append("release")

    class _FakeWebview:
        def create_window(self, *args, **kwargs):
            raise RuntimeError("no window engine")

        def start(self):  # pragma: no cover - never reached
            pass

    # Do not actually block waiting for Ctrl+C in the fallback.
    monkeypatch.setattr(webapp, "_wait_for_interrupt", lambda: None)
    webapp._run_in_window(_FakeServer(), _FakeFlow(), "http://127.0.0.1:0", _FakeWebview())
    assert "release" in released and "close" in released


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
