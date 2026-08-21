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

from workflow import react as wreact  # noqa: E402
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
    assert flow.viewer.marks == []  # step 6 never rewrites the step 5 overview
    assert len(flow.gallery.records) == 2 == len(flow.gallery.picked)
    assert flow.gallery._verdicts[0] == "good"
    root = flow.root
    assert root.parent == tmp_path / "run"
    assert root.name.startswith("target-acquisition_")
    for artifact in ("summary.json", "run_layout.png", "curation.json"):
        assert (root / artifact).exists(), artifact
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


def test_a_restart_that_gave_up_waiting_does_not_happen_later_anyway(tmp_path):
    """Refusing a restart must mean it really did not happen.

    A restart waits its turn behind whatever the microscope is already doing,
    so it can still be queued when the wait runs out. If it were left queued
    after the operator had been told it failed, it would go ahead later —
    releasing the microscope and wiping the run in the middle of whatever they
    had moved on to. Being told "no" has to be the truth.
    """
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    flow.run_step("connect")
    hub.drain(60)
    session, root = flow.session, flow.root

    # Occupy the worker the way a long acquisition would. This is a widget
    # message rather than a step, so it does not show up as a pending step.
    release = threading.Event()
    assert hub.submit(lambda: release.wait(20))
    for _ in range(200):  # let the worker actually pick the work up
        if not hub._work.empty():
            time.sleep(0.005)
        else:
            break

    with pytest.raises(RuntimeError, match="nothing was restarted"):
        flow.reset(timeout=0.5)

    release.set()
    hub.drain(60)

    # The run carried on untouched: same session, same folder, same progress.
    assert flow.session is session
    assert flow.root == root
    assert flow.completed == ["connect"]
    assert not session.disconnected

    flow.run_step("disconnect")
    hub.drain(60)


def test_finished_steps_the_page_offers_again_are_still_refused(tmp_path):
    """The page invites some steps to be repeated; the run does not allow it.

    Once a step is done, the page relabels its button — Connect becomes
    "Reconnect", Set origin becomes "Change Origin", and the overview job
    becomes "Recapture Overview Job" — so an operator who picked the wrong
    job, or zeroed the stage in the wrong place, is invited to put it right.
    Pressing those buttons is refused, because a finished step cannot run
    twice.

    This test records that disagreement rather than blessing it: the two
    sides need to be brought together, either by letting these steps run
    again (which has real consequences — moving the origin after positions
    are loaded moves every coordinate with it) or by not offering them.
    """
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    refusals = []
    hub.broadcast = _recording_broadcast(hub, refusals)

    for step in ("connect", "set_origin", "capture_overview_job"):
        flow.run_step(step)
        hub.drain(60)

    for step in ("connect", "set_origin", "capture_overview_job"):
        refusals.clear()
        flow.run_step(step)
        hub.drain(60)
        failed = [e for e in refusals if e["state"] == "failed"]
        assert failed, f"{step} was expected to refuse a second run"
        assert "already complete" in failed[0]["message"]

    flow.run_step("disconnect")
    hub.drain(60)


def _recording_broadcast(hub, sink):
    """Watch the run's own progress events without disturbing them."""
    original = hub.broadcast

    def recording(event):
        if event.get("kind") == "flow":
            sink.append(event)
        original(event)

    return recording


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
    assert "padding: 28px 16px 60px 50px" in page
    assert "header, .step { max-width: 1600px" in page
    assert "max-width: 1600px; margin: 0 0 12px" in page
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
    picture = _get(base, f"/buffer/{tile_messages[0]['buffers'][0]}")
    # Map tiles travel as JPEG — a display copy made in its thousands.
    assert picture[:3] == b"\xff\xd8\xff"  # pixels travel as real binary
    assert tile_messages[0]["content"]["mime"] == "image/jpeg"
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
            "host": "127.0.0.1",
            "port": 8765,
            "demo": True,
            "analysis_repo": None,
            "vendor": "leica",
            "demo_root": None,
            "af_job": None,
            "experiment": "target-acquisition",
            "open_window": False,
        }
    ]


class _StubServer:
    """A server that records the lifecycle calls ``serve`` makes on it.

    The window tests are about which path ``serve`` takes, not about HTTP, so
    they run against this instead of binding a socket.
    """

    def __init__(self, address=("127.0.0.1", 8765)):
        self.server_address = address
        self.served = False
        self.shut_down = False
        self.closed = False

    def serve_forever(self):
        self.served = True

    def shutdown(self):
        self.shut_down = True

    def server_close(self):
        self.closed = True


class _StubWebview:
    """A pywebview stand-in; ``fail_with`` makes ``create_window`` raise."""

    def __init__(self, fail_with=None):
        self.fail_with = fail_with
        self.window = None
        self.started = False

    def create_window(self, title, url, **kwargs):
        if self.fail_with is not None:
            raise self.fail_with
        self.window = (title, url, kwargs)

    def start(self):
        self.started = True


def test_window_flag_asks_serve_for_a_native_window(monkeypatch):
    import sys

    from workflow.webapp import __main__ as cli

    calls = []
    monkeypatch.setattr(sys, "argv", ["workflow.webapp", "--demo", "--window"])
    monkeypatch.setattr(cli, "serve", lambda **kwargs: calls.append(kwargs))
    cli.main()
    assert calls[0]["open_window"] is True


def test_a_native_window_shows_the_page_and_closes_the_server_on_exit(monkeypatch):
    from workflow import webapp

    server, webview = _StubServer(), _StubWebview()
    monkeypatch.setattr(webapp, "make_server", lambda **kwargs: (server, None, None))
    monkeypatch.setattr(webapp, "_load_webview", lambda: webview)
    webapp.serve(open_window=True, demo=True)
    title, url, _kwargs = webview.window
    assert title == "ZMART target acquisition"
    assert url == "http://127.0.0.1:8765"
    assert webview.started
    assert server.served, "the page must be served while the window is open"
    assert server.shut_down and server.closed


def test_a_window_bound_to_all_interfaces_dials_loopback(monkeypatch):
    from workflow import webapp

    server, webview = _StubServer(address=("0.0.0.0", 9100)), _StubWebview()
    monkeypatch.setattr(webapp, "make_server", lambda **kwargs: (server, None, None))
    monkeypatch.setattr(webapp, "_load_webview", lambda: webview)
    webapp.serve(open_window=True, demo=True)
    assert webview.window[1] == "http://127.0.0.1:9100"


def test_a_missing_pywebview_still_serves_the_page(monkeypatch, capsys):
    from workflow import webapp

    server = _StubServer()
    monkeypatch.setattr(webapp, "make_server", lambda **kwargs: (server, None, None))
    monkeypatch.setattr(webapp.importlib, "import_module", _raise_import_error)
    webapp.serve(open_window=True, demo=True)
    assert server.served and server.closed
    assert "pywebview" in capsys.readouterr().out


def test_a_window_engine_failure_keeps_serving_and_closes_the_server(monkeypatch, capsys):
    from workflow import webapp

    server = _StubServer()
    webview = _StubWebview(fail_with=RuntimeError("WebView2 runtime is missing"))
    monkeypatch.setattr(webapp, "make_server", lambda **kwargs: (server, None, None))
    monkeypatch.setattr(webapp, "_load_webview", lambda: webview)
    monkeypatch.setattr(webapp, "_wait_for_interrupt", lambda: None)
    webapp.serve(open_window=True, demo=True)
    assert server.served, "a failed window must not take the page down with it"
    assert server.shut_down and server.closed
    assert "WebView2 runtime is missing" in capsys.readouterr().out


def _raise_import_error(name):
    raise ImportError(f"no module named {name}")


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


# ---------------------------------------------------------------------------
# The host's own promises: what it turns into JSON, what it forgets, and what
# it survives. These are the properties every widget quietly relies on.
# ---------------------------------------------------------------------------


def test_values_a_widget_holds_all_survive_the_trip_to_the_browser():
    """Traits carry more than plain JSON, and none of it may stop an update.

    Widget traits hold coordinate pairs as tuples and measurements as numpy
    numbers, neither of which JSON knows. Anything that cannot be converted
    honestly is sent as text rather than raising, because one awkward value
    must never stop the operator's page from being told what changed.
    """
    import numpy as np
    from workflow.webapp._host import _jsonable

    assert _jsonable((1.0, 2.0)) == [1.0, 2.0]
    assert _jsonable(np.float64(1.5)) == 1.5
    assert _jsonable(np.int64(7)) == 7
    assert _jsonable(Path("/tmp/run")) == "/tmp/run"


def test_replacing_a_widget_stops_the_old_one_being_heard():
    """After a restart the previous widgets must fall silent.

    A restart builds fresh widgets under the same names. If the old ones kept
    reporting their changes, a finished run could still write over the new
    one's display — the map showing tiles from an experiment that has ended.
    """
    hub = WidgetHub()
    first = wreact.run_status({})
    second = wreact.run_status({})
    hub.add_widget("status", first)
    hub.add_widget("status", second)

    seen = []
    hub.broadcast = lambda event: seen.append(event)

    first.status = "from the run that ended"
    assert seen == [], "the replaced widget was still being listened to"

    second.status = "from the run that is live"
    assert [e["value"] for e in seen if e.get("kind") == "trait"] == ["from the run that is live"]


def test_the_oldest_pictures_are_forgotten_once_the_store_is_full(monkeypatch):
    """Image bytes are kept for the browser to fetch, but not forever.

    Every picture sent to the page waits in memory until the browser collects
    it. On a long run that would grow without end, so the oldest are dropped
    once the store is full — they have long since been fetched. The newest is
    always kept, because it is the one nobody has had a chance to ask for yet.
    """
    from workflow.webapp import _host

    monkeypatch.setattr(_host, "_BUFFER_CAP_BYTES", 1000)
    hub = WidgetHub()
    ids = [hub._store_buffer(b"x" * 400) for _ in range(5)]

    assert hub.buffer(ids[-1]) == b"x" * 400, "the newest picture must still be there"
    assert hub.buffer(ids[0]) is None, "the oldest should have been let go"
    assert hub._buffer_bytes <= 1000


def test_one_failing_action_does_not_take_the_whole_page_down():
    """A step that breaks must not stop every later step from running.

    All the work runs on one thread, one thing at a time. If an unexpected
    failure escaped and ended that thread, the page would go quiet forever and
    the operator would have no way to disconnect the microscope.
    """
    hub = WidgetHub()
    assert hub.submit(lambda: 1 / 0)
    hub.drain(30)

    afterwards = []
    assert hub.submit(lambda: afterwards.append("still working"))
    hub.drain(30)
    assert afterwards == ["still working"]


def test_messages_and_edits_for_a_widget_that_is_not_there_are_refused():
    """The page may ask about a widget that this run has not created yet."""
    hub = WidgetHub()
    assert hub.dispatch_message("explorer", {"type": "sync"}) is False
    assert hub.valid_trait_changes("explorer", {"status": "hello"}) is False
    assert hub.dispatch_trait_changes("explorer", {"status": "hello"}) is False


def test_only_real_traits_with_believable_values_are_accepted():
    """The page may only write to traits that exist, with values that fit.

    Everything arriving from the browser is checked before it reaches a
    widget. A name that is not a synced trait, a private one, or a value of
    the wrong kind is refused outright rather than being half-applied.
    """
    hub = WidgetHub()
    viewer = wreact.view_overview()
    hub.add_widget("overview", viewer)

    assert hub.valid_trait_changes("overview", {"channels": []}) is True
    assert hub.valid_trait_changes("overview", {"not_a_trait": 1}) is False
    assert hub.valid_trait_changes("overview", {"_tile_entries": []}) is False
    assert hub.valid_trait_changes("overview", {"channels": "not a list"}) is False
    assert hub.valid_trait_changes("overview", "not even a mapping") is False


# ---------------------------------------------------------------------------
# What the operator is told when a step cannot run.
# ---------------------------------------------------------------------------


def test_an_unknown_action_is_simply_not_run():
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=Path("/tmp"))
    assert flow.run_step("polish_the_objective") is False
    assert flow.has_step("polish_the_objective") is False


def test_an_unexpected_failure_reaches_the_operator_instead_of_vanishing(tmp_path):
    """A step that breaks in an unforeseen way still has to say so.

    Steps refuse politely when they know why. When something fails that nobody
    anticipated, the page must still show what happened — a silent button is
    far worse at the microscope than an ugly message.
    """
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    events = []
    hub.broadcast = _recording_broadcast(hub, events)

    def broken() -> str:
        raise ValueError("the stage said something unrepeatable")

    flow._steps["connect"] = broken
    flow.run_step("connect")
    hub.drain(60)

    failed = [e for e in events if e["state"] == "failed"]
    assert failed and failed[0]["message"] == (
        "ValueError: the stage said something unrepeatable"
    )
    assert flow.completed == []


def test_after_disconnect_the_run_says_so_rather_than_half_working(tmp_path):
    """Once the microscope is released, later steps must not pretend."""
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    events = []
    for step in ("connect", "disconnect"):
        flow.run_step(step)
        hub.drain(60)
    hub.broadcast = _recording_broadcast(hub, events)

    flow.run_step("set_origin")
    hub.drain(60)
    failed = [e for e in events if e["state"] == "failed"]
    assert failed and "this session is disconnected" in failed[0]["message"]


def test_a_restart_waits_for_the_action_already_under_way(tmp_path):
    """Restarting in the middle of a step is refused, not queued behind it."""
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    flow.run_step("connect")
    hub.drain(60)

    blocker = threading.Event()
    assert hub.submit(blocker.wait)
    flow.run_step("set_origin")  # now sitting in the queue behind the blocker
    try:
        with pytest.raises(RuntimeError, match="wait for the current workflow action"):
            flow.reset(timeout=5)
    finally:
        blocker.set()
    hub.drain(60)
    flow.run_step("disconnect")
    hub.drain(60)


def test_the_two_jobs_must_actually_differ(tmp_path):
    """Imaging targets at overview magnification would waste the whole run.

    The overview job and the target job are captured separately, and the run
    refuses to continue if they turn out to be the same — the usual cause is
    forgetting to switch job in LAS X between the two captures.
    """
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    events = []
    for step in ("connect", "set_origin", "capture_overview_job"):
        flow.run_step(step)
        hub.drain(60)

    # Stand in for an operator who never switched job in LAS X.
    flow.session.TARGET_JOB = flow.session.OVERVIEW_JOB
    hub.broadcast = _recording_broadcast(hub, events)
    flow.run_step("capture_target_job")
    hub.drain(60)

    failed = [e for e in events if e["state"] == "failed"]
    assert failed and "the overview and target jobs are the same" in failed[0]["message"]
    assert "capture_target_job" not in flow.completed


# ---------------------------------------------------------------------------
# The HTTP surface: every wrong turn answered plainly.
# ---------------------------------------------------------------------------


def _expect_status(call, expected: int) -> None:
    with pytest.raises(urllib.error.HTTPError) as caught:
        call()
    assert caught.value.code == expected


def test_asking_for_things_that_are_not_there_gets_a_plain_refusal(demo_server):
    """Every unknown address answers honestly instead of failing oddly."""
    base, _hub, _flow = demo_server

    _expect_status(lambda: _get(base, "/no-such-page"), 404)
    _expect_status(lambda: _get(base, "/esm/no-such-widget.mjs"), 404)
    _expect_status(lambda: _get(base, "/buffer/0123456789abcdef"), 404)
    _expect_status(lambda: _post(base, "/nowhere", {}), 404)
    _expect_status(lambda: _post(base, "/action", {"step": "polish_the_objective"}), 404)
    _expect_status(lambda: _post(base, "/msg", {"widget": "ghost", "content": {}}), 404)
    _expect_status(lambda: _post(base, "/trait", {"widget": "ghost", "changes": {}}), 404)


def test_a_trait_edit_the_widget_would_not_accept_is_turned_away(demo_server):
    """Nonsense from the page is refused before it reaches a widget."""
    base, _hub, _flow = demo_server
    _expect_status(
        lambda: _post(base, "/trait", {"widget": "overview", "changes": {"channels": 5}}), 400
    )
    _expect_status(
        lambda: _post(base, "/trait", {"widget": "overview", "changes": {"nope": 1}}), 400
    )


def test_a_page_from_somewhere_else_cannot_press_these_buttons(demo_server):
    """This page drives a microscope and has no login of its own.

    The only protection against another site quietly firing these actions at
    the machine is that they must come from this page, so an unrecognisable
    or foreign origin is refused before the request is even read.
    """
    base, _hub, _flow = demo_server

    def post_with_origin(origin: str):
        request = urllib.request.Request(
            base + "/action",
            data=json.dumps({"step": "connect"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": origin},
        )
        return urllib.request.urlopen(request, timeout=10)

    _expect_status(lambda: post_with_origin("https://example.com"), 403)
    _expect_status(lambda: post_with_origin("http://example.com"), 403)
    _expect_status(lambda: post_with_origin("http://127.0.0.1:1"), 403)
    _expect_status(lambda: post_with_origin("http://["), 403)


def test_a_body_whose_length_makes_no_sense_is_not_read(demo_server):
    """A wrong or oversized length is answered, never trusted."""
    base, _hub, _flow = demo_server
    request = urllib.request.Request(
        base + "/action",
        data=b'{"step": "connect"}',
        headers={"Content-Type": "application/json", "Content-Length": "not a number"},
    )
    with pytest.raises((urllib.error.HTTPError, urllib.error.URLError, ValueError)):
        urllib.request.urlopen(request, timeout=10)


# ---------------------------------------------------------------------------
# The refusals an operator is most likely to meet in a real session.
# ---------------------------------------------------------------------------


def test_scanning_before_the_focus_is_measured_is_refused_kindly(tmp_path):
    """Skipping Measure would scan the whole sample out of focus.

    The overview scan needs a focus surface to hold the sample sharp across
    the slide. Pressing Scan before pressing Measure is an easy mistake and an
    expensive one, so the run stops and says what is missing rather than
    filling a run folder with blurred tiles.
    """
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    for step in _ORDERED_STEPS[:5]:
        flow.run_step(step)
        hub.drain(60)

    events = []
    hub.broadcast = _recording_broadcast(hub, events)
    flow.run_step("run_overview")  # no Measure first, and no focus points picked
    hub.drain(60)

    failed = [e for e in events if e["state"] == "failed"]
    assert failed, "scanning without a focus surface should have been refused"
    assert "run_overview" not in flow.completed
    assert flow.overview_records is None

    flow.run_step("disconnect")
    hub.drain(60)


def test_a_live_run_will_not_start_without_the_analysis_checkout(tmp_path):
    """A real session needs the analysis code before it touches the stage.

    Finding out that the analysis repository is missing only after the
    microscope is connected and a run folder exists would waste an operator's
    setup, so it is refused right at the start with the flag to pass.
    """
    hub = WidgetHub()
    with pytest.raises(ValueError, match="analysis-repo"):
        RunFlow(hub, demo=False, demo_root=tmp_path / "run")

    # The same guard must not stand in the way of the simulated microscope.
    RunFlow(hub, demo=True, demo_root=tmp_path / "run")


def test_a_microscope_that_is_not_ready_stops_the_run_with_its_own_words(
    tmp_path, monkeypatch
):
    """A driver that reports it is not ready must be quoted, not swallowed.

    The check that the microscope is in a fit state to be driven belongs to
    the controller. When it objects, the page shows the reason it gave rather
    than replacing it with something vaguer.
    """
    import workflow

    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    for step in ("connect", "set_origin"):
        flow.run_step(step)
        hub.drain(60)

    def not_ready(_state):
        raise RuntimeError("the objective turret is still moving")

    monkeypatch.setattr(workflow, "require_driver_ready", not_ready)
    events = []
    hub.broadcast = _recording_broadcast(hub, events)
    flow.run_step("capture_overview_job")
    hub.drain(60)

    failed = [e for e in events if e["state"] == "failed"]
    assert failed and failed[0]["message"] == "the objective turret is still moving"
    assert "capture_overview_job" not in flow.completed


def test_a_button_pressed_while_the_queue_is_full_says_the_server_is_busy(tmp_path):
    """Work is bounded, and a refused button still explains itself."""
    from workflow.webapp import _host

    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    release = threading.Event()
    started = threading.Event()

    def _block_worker():
        started.set()
        release.wait()

    assert hub.submit(_block_worker)
    assert started.wait(10)
    events = []
    hub.broadcast = _recording_broadcast(hub, events)
    try:
        for _ in range(_host._WORK_QUEUE_CAP):
            hub.submit(lambda: None)
        assert flow.run_step("connect") is False
    finally:
        release.set()
    hub.drain(60)

    failed = [e for e in events if e.get("kind") == "flow" and e["state"] == "failed"]
    assert failed and "the server is busy" in failed[-1]["message"]
    # The refusal must not leave the step stuck as pending forever.
    assert "connect" not in flow._pending


def test_a_restart_that_goes_wrong_reports_the_reason(tmp_path):
    """If the restart itself fails, the browser hears why."""
    hub = WidgetHub()
    flow = RunFlow(hub, demo=True, demo_root=tmp_path / "run")
    flow.run_step("connect")
    hub.drain(60)

    def broken() -> None:
        raise RuntimeError("the engine would not shut down")

    flow._reset_now = broken
    with pytest.raises(RuntimeError, match="the engine would not shut down"):
        flow.reset(timeout=10)


def test_a_state_changing_request_for_another_host_is_refused(demo_server):
    """Loopback-only means loopback-only, for writes as well as reads."""
    base, _hub, _flow = demo_server
    request = urllib.request.Request(
        base + "/action",
        data=json.dumps({"step": "connect"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Host": "microscope.example.com"},
    )
    _expect_status(lambda: urllib.request.urlopen(request, timeout=10), 403)


def test_stopping_with_ctrl_c_closes_the_socket_and_reminds_the_operator(capsys, monkeypatch):
    """Ctrl+C must release the port and mention the live session.

    The server holds a port; leaving it held would stop the next run starting.
    The parting line also reminds the operator that stopping the page is not
    the same as releasing the microscope.
    """
    from workflow import webapp

    class _FakeServer:
        server_address = ("127.0.0.1", 8765)

        def __init__(self):
            self.closed = False

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            self.closed = True

    fake = _FakeServer()
    monkeypatch.setattr(webapp, "make_server", lambda **_kw: (fake, None, None))
    webapp.serve(demo=True)

    assert fake.closed, "the port must be released on Ctrl+C"
    printed = capsys.readouterr().out
    assert "http://127.0.0.1:8765" in printed
    assert "disconnect the session if it was live" in printed


# ---------------------------------------------------------------------------
# A hostile client on the same machine.
#
# The page has no login of its own: anything running on the microscope PC can
# reach it. The widgets already refuse forged state when poked directly; these
# tests come the way a real attacker would, over the HTTP surface, and check
# the refusals survive the trip.
# ---------------------------------------------------------------------------


def _raw_request(base: str, method: str, path: str, body: bytes = b"", headers=None):
    """Send a request with the path untouched, so traversal is really tested."""
    import http.client

    host = base.removeprefix("http://")
    connection = http.client.HTTPConnection(host, timeout=10)
    try:
        connection.request(
            method, path, body=body, headers=headers or {"Content-Type": "application/json"}
        )
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _advance_to_targets(base, hub, flow):
    for step in _ORDERED_STEPS[:5]:
        flow.run_step(step)
    hub.drain(60)
    hub.dispatch_message("focus", {"type": "measure"})
    for step in ("run_overview", "discover_targets"):
        flow.run_step(step)
    hub.drain(180)
    return flow.explorer


def test_a_forged_gate_sent_over_the_wire_cannot_widen_what_is_imaged(demo_server):
    """Claiming every cell passes the gate must not make it so.

    Which cells are worth imaging is decided in Python from the gate the
    operator set. The mask the page holds is only a picture of that decision,
    so writing a more generous one over the wire must change what is drawn and
    nothing else — otherwise a stray script could spend an operator's session
    imaging the whole slide.
    """
    base, hub, flow = demo_server
    explorer = _advance_to_targets(base, hub, flow)
    total = len(explorer.targets)

    # Narrow the gate the way an operator would, so some cells fall outside it.
    xs = sorted(float(t["x"]) for t in explorer.targets)
    _post(
        base,
        "/trait",
        {"widget": "explorer", "changes": {"gate": {"x": [xs[0], xs[len(xs) // 3]]}}},
    )
    hub.drain(60)
    honest = len(explorer.gated)
    assert 0 < honest < total, "this test needs a gate that really excludes cells"

    result = _post(
        base, "/trait", {"widget": "explorer", "changes": {"gated_mask": [True] * total}}
    )
    assert result["ok"] is True  # accepted as a display value...
    hub.drain(60)

    # ...but the decision itself is unmoved, and the display is put back.
    assert len(explorer.gated) == honest, "a forged mask changed what would be imaged"
    assert sum(bool(v) for v in explorer.gated_mask) == honest


def test_a_forged_busy_or_read_only_flag_is_healed(demo_server):
    """The page's copy of "a run is in progress" is a mirror, not the truth.

    If writing these could set them, a script could either hide a run that is
    really happening or fake one that is not — and the second would let it
    lock the operator out of their own microscope.
    """
    base, hub, flow = demo_server
    flow.run_step("connect")
    hub.drain(60)
    viewer = flow.viewer

    _post(base, "/trait", {"widget": "overview", "changes": {"busy": True}})
    hub.drain(60)
    assert viewer.busy is False, "a forged busy flag stuck"
    assert viewer._busy is False

    _post(base, "/trait", {"widget": "overview", "changes": {"read_only": True}})
    hub.drain(60)
    assert viewer.read_only is False, "a forged read-only flag stuck"


def test_no_path_can_reach_out_of_the_places_the_page_serves(demo_server):
    """Only the page, the widget code and the run's own pictures are served.

    The addresses that take a name — a widget's code, a picture's ticket — look
    up that name in a table rather than joining it onto a folder, so a name
    dressed up as a path leads nowhere.
    """
    base, _hub, _flow = demo_server
    for path in (
        "/buffer/../../../../etc/passwd",
        "/buffer/..%2f..%2fetc%2fpasswd",
        "/esm/../../../../etc/passwd.mjs",
        "/esm/..%2f..%2f_flow.mjs",
        "/../_flow.py",
    ):
        status, body = _raw_request(base, "GET", path)
        assert status == 404, f"{path} answered {status}"
        assert b"root:" not in body and b"import" not in body


def test_numbers_json_cannot_really_carry_are_refused(demo_server):
    """"Not a number" and "infinity" are not values a microscope can use.

    Python's JSON reader accepts them by default, and they would flow onward
    into coordinates. They are turned away at the door instead.
    """
    base, _hub, _flow = demo_server
    for body in (
        b'{"widget": "overview", "changes": {"downsample": NaN}}',
        b'{"widget": "overview", "changes": {"downsample": Infinity}}',
        b'{"widget": "overview", "changes": {"downsample": -Infinity}}',
    ):
        status, _ = _raw_request(base, "POST", "/trait", body)
        assert status == 400, "a JSON constant that is not a number was let through"


def test_a_deeply_nested_or_oversized_body_is_turned_away_and_the_server_lives(demo_server):
    """Awkward bodies must cost a refusal, not the server.

    Deep nesting can exhaust the reader's own stack and an enormous body can
    exhaust memory; both are answered plainly, and the page keeps working
    afterwards — which is the part that matters at the microscope.
    """
    base, hub, flow = demo_server

    nested = b'{"widget": "overview", "changes": ' + b"[" * 20_000 + b"]" * 20_000 + b"}"
    status, _ = _raw_request(base, "POST", "/trait", nested)
    assert status == 400

    oversized = b'{"widget": "overview", "changes": {"status": "' + b"x" * (5 * 1024 * 1024) + b'"}}'
    try:
        status, _ = _raw_request(base, "POST", "/trait", oversized)
        assert status == 400
    except (ConnectionResetError, BrokenPipeError, OSError):
        pass  # refusing before reading it all is a perfectly good answer

    # Still answering, and still the same run.
    assert json.loads(_get(base, "/state"))["flow"]["demo"] is True
    assert flow.run_step("connect") is True
    hub.drain(60)


def test_a_flood_of_edits_cannot_starve_the_operators_own_buttons(demo_server):
    """One noisy client must not take the microscope away from the operator.

    Work is bounded and refused once the queue is full, so a script hammering
    the page gets turned away rather than building a backlog that would keep
    firing long after the operator moved on.
    """
    base, hub, flow = demo_server
    flow.run_step("connect")
    hub.drain(60)

    refused = 0
    for index in range(400):
        answer = _post(
            base, "/trait", {"widget": "overview", "changes": {"status": f"flood {index}"}}
        )
        refused += 0 if answer["ok"] else 1
    hub.drain(120)

    # Whether any were refused depends on how fast the worker drains, but the
    # page must be answering and the run must be intact either way.
    assert isinstance(refused, int)
    assert flow.session is not None, "the flood disturbed the live session"
    assert flow.completed == ["connect"]
    flow.run_step("disconnect")
    hub.drain(60)
    assert flow.completed == ["connect", "disconnect"]


def test_a_live_connection_that_fails_halfway_leaves_nothing_running(tmp_path, monkeypatch):
    """A failed Connect must not leave the analysis engine or session behind.

    Connect starts the analysis engine, then opens the microscope, then makes
    the run folder. If any of those fails, whatever already started has to be
    shut down again — otherwise a second attempt meets an engine that is still
    holding the GPU, or a session the microscope thinks is still in use.

    This matters most on real hardware, so the pieces are stood in for here
    rather than driven: the point is what the page does with them, not what
    they do.
    """
    import workflow

    class _Engine:
        def __init__(self):
            self.shut_down = False

        def shutdown(self):
            self.shut_down = True

    class _Session:
        def __init__(self, info):
            self._info = info
            self.disconnected = False

        def get_info(self):
            if self._info is None:
                raise RuntimeError("the microscope would not say where it saves")
            return self._info

        def disconnect(self):
            self.disconnected = True

    engine = _Engine()
    monkeypatch.setattr(workflow, "load_analysis_engine", lambda _repo: engine)
    monkeypatch.setattr(workflow, "preflight_analysis_engine", lambda _engine: None)

    # The microscope itself refuses to open.
    def refuse(_vendor):
        raise RuntimeError("no microscope answered")

    monkeypatch.setattr(workflow, "connect", refuse)
    hub = WidgetHub()
    flow = RunFlow(hub, demo=False, analysis_repo=tmp_path / "analysis")
    events = []
    hub.broadcast = _recording_broadcast(hub, events)
    flow.run_step("connect")
    hub.drain(60)

    assert engine.shut_down, "the analysis engine was left running after a failed connect"
    assert flow.session is None and flow.completed == []
    assert [e for e in events if e["state"] == "failed"], "the operator was not told"

    # Now the microscope opens but cannot say where it saves: both must close.
    second_engine = _Engine()
    session = _Session(None)
    monkeypatch.setattr(workflow, "load_analysis_engine", lambda _repo: second_engine)
    monkeypatch.setattr(workflow, "connect", lambda _vendor: session)
    flow.run_step("connect")
    hub.drain(60)

    assert session.disconnected, "the microscope was left connected"
    assert second_engine.shut_down, "the analysis engine was left running"
    assert flow.session is None and flow.completed == []


def test_only_so_many_views_may_watch_one_run():
    """Each open view costs a thread, so their number is bounded.

    A tab watching the run holds a server thread and a queue of its own for as
    long as it lives. One operator needs a handful; nothing stopped a confused
    or hostile local script from opening them until the machine ran out of
    threads. Refusing is kinder than accepting a view that cannot be served —
    the browser retries by itself.
    """
    from workflow.webapp import _host

    hub = WidgetHub()
    accepted = [hub.add_client() for _ in range(_host._MAX_EVENT_STREAMS)]
    assert all(client is not None for client in accepted)
    assert hub.add_client() is None, "the number of watching views was not bounded"

    # A view going away makes room again, so refreshing a tab keeps working.
    hub.remove_client(accepted[0])
    replacement = hub.add_client()
    assert replacement is not None
    hub.remove_client(replacement)


def test_a_refused_view_is_told_plainly_over_http(demo_server, monkeypatch):
    """The refusal reaches the browser as an answer, not a dropped connection."""
    import urllib.error

    base, hub, _flow = demo_server
    monkeypatch.setattr(hub, "add_client", lambda: None)
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(base + "/events", timeout=10)
    assert caught.value.code == 503
