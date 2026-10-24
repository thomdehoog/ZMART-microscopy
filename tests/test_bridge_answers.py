"""The interface's bridge starts on the installed blocks and answers the operator page.

The bridge is the small web server behind the operator window: the page asks
it what microscopes there are, and it drives the chosen one through the
controller, runs the analysis and starts the viewer. Here it is started the
way the window starts it, from the installed package, and asked the
questions the page asks: what there is before anyone presses Connect, and
then, connected to the kidney mock, for one capture. The page's questions
are under ``/api/target_acquisition/``, the workflow the bridge serves.

A last check asks the browser walk itself how it starts the bridge, and where
that Python finds the interface: it must be the installed package, not the
interface's clone the walk runs from.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from conftest import KIDNEY_MOCK, REPO, checkout, write_report

#: Where the bridge answers the target acquisition workflow's page.
API = "/api/target_acquisition/"


def _a_free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _get(url: str) -> tuple[int, str, bytes]:
    with urllib.request.urlopen(url, timeout=30) as answer:
        return answer.status, answer.headers.get("Content-Type", ""), answer.read()


def _post(url: str, payload: dict) -> dict:
    asked = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                   headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(asked, timeout=120) as answer:
        return json.loads(answer.read())


@pytest.fixture
def a_bridge(tmp_path):
    """The installed bridge, on a free port, writing into this check's folder.

    It is started the way the operator window starts it, with the
    interface's own mock offered first (``zmart_interface.framework.bridge``). The
    kidney mock opens a small window of its own when a session connects to
    it, unless one is open already. The window is not what is checked here,
    and on a computer without a screen it cannot open, so this check holds
    the window's place itself (its lock names this Python) and no window is
    started.
    """
    from zmart_interface.workflows.target_acquisition.mock_microscope import driver

    state_file = tmp_path / "instrument.json"
    driver.claim_the_window(os.getpid(), state_file)
    port = _a_free_port()
    log = (tmp_path / "bridge.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "zmart_interface.framework.bridge", "--port", str(port),
         "--output-root", str(tmp_path / "runs")],
        cwd=tmp_path, stdout=log, stderr=subprocess.STDOUT,
        env={**os.environ, driver.STATE_FILE_ENV: str(state_file)},
    )
    at = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while True:
        try:
            _get(at + API + "instruments")
            break
        except OSError:
            if process.poll() is not None or time.monotonic() > deadline:
                log.close()
                pytest.fail("the bridge never answered:\n"
                            + (tmp_path / "bridge.log").read_text(encoding="utf-8")[-4000:])
            time.sleep(0.3)
    yield at
    process.terminate()
    process.wait(timeout=30)
    log.close()


@pytest.fixture
def the_controllers_mock_installed(a_clean_configuration_folder):
    """The controller's mock (beads), installed on this computer before the bridge starts.

    It is a driver like any other, kept with the controller's tests, so the
    controller's list holds it only once it is installed.
    """
    import zmart_controller

    zmart_controller.register_driver(checkout("ZMART-controller") / "tests" / "mock_driver")


def test_the_bridge_lists_the_kidney_mock_first(the_controllers_mock_installed, a_bridge):
    """``instruments`` offers the kidney mock first, then the drivers installed on the computer.

    First, so that a page opened by accident drives nothing real; and the
    controller's list after it, here the controller's mock.
    """
    status, _, body = _get(a_bridge + API + "instruments")
    names = [one["name"] for one in json.loads(body)["instruments"]]
    write_report("bridge-instruments", {"instruments": names})
    assert status == 200
    assert names == [KIDNEY_MOCK, "mock"], names


def test_the_bridge_serves_the_built_operator_page(a_bridge):
    """The page shipped inside the installed package is what the bridge serves at its root."""
    status, kind, body = _get(a_bridge + "/")
    assert status == 200
    assert "text/html" in kind
    assert b"<script" in body


def test_the_bridge_answers_the_questions_asked_before_connect(a_bridge):
    """The viewer's status answers before any microscope is connected: not running yet."""
    status, _, body = _get(a_bridge + API + "viewer")
    viewer = json.loads(body)
    assert status == 200 and viewer["running"] is False, viewer


def test_a_capture_through_the_bridge_is_the_controllers_answer(a_bridge):
    """Connected to the kidney mock, ``acquire`` answers ``{success, output}`` as the controller does.

    The bridge passes the controller's answer on untouched, so the page reads
    a capture the way a script does. The answer must fit the controller's
    contract for an acquisition, checked by the controller's own
    ``check_acquire_answer``: every saved file under ``files``, and under
    ``planes`` the file, channel, depth, moment and stage position of every
    picture.
    """
    from zmart_controller import check_acquire_answer

    connected = _post(a_bridge + API + "connect", {"instrument": KIDNEY_MOCK})
    answer = _post(a_bridge + API + "acquire", {"acquisition_type": "overview",
                                                "position_label": "assembly-check"})
    _post(a_bridge + API + "disconnect", {})
    write_report("bridge-acquire", {"connected": connected, "answer": answer})
    assert set(answer) == {"success", "output"}, answer
    assert answer["success"] is True, answer
    assert check_acquire_answer(answer) == [], answer
    assert answer["output"]["planes"], answer


@pytest.fixture
def a_driver_installed_under_the_kidneys_name(a_clean_configuration_folder, tmp_path):
    """A driver installed on this computer as ``interface-mock``, before the bridge starts.

    Its ``get_info`` says who it is, so a session connected to it is
    recognised at once.
    """
    import zmart_controller

    plugin = tmp_path / "impostor" / "zmart_controller_plugin"
    plugin.mkdir(parents=True)
    (plugin / "zmart_controller_plugin.json").write_text(
        json.dumps({"name": KIDNEY_MOCK, "connection": {}}), encoding="utf-8")
    (plugin / "zmart_controller_plugin.py").write_text(
        "class ZmartControllerPlugin:\n"
        "    def __init__(self, connection):\n"
        "        pass\n"
        "    def get_info(self):\n"
        "        return True, ('the impostor', 'C:/nowhere', False, {})\n",
        encoding="utf-8")
    zmart_controller.register_driver(plugin.parent)


def test_the_bridges_mock_is_the_interfaces_own(a_driver_installed_under_the_kidneys_name,
                                                 a_bridge):
    """With another driver installed as ``interface-mock``, the page still connects to the kidney.

    The bridge offers the interface's own mock under that name, plugged in
    directly, and lists the name once. Were the installed driver used
    instead, choosing the mock on the page would drive whatever that driver
    drives.
    """
    _, _, body = _get(a_bridge + API + "instruments")
    names = [one["name"] for one in json.loads(body)["instruments"]]
    assert names.count(KIDNEY_MOCK) == 1, names
    connected = _post(a_bridge + API + "connect", {"instrument": KIDNEY_MOCK})
    _post(a_bridge + API + "disconnect", {})
    assert connected["info"]["description"] != "the impostor", connected


def test_the_walks_bridge_runs_the_installed_interface():
    """The walk starts the bridge inside the interface's clone; that Python must still use the installed package.

    The walk's own JavaScript decides how the bridge's Python is started (it
    adds ``-P``, which keeps the clone's ``zmart_interface`` folder from
    standing in front of the installed one). This check asks the walk for that
    command and runs it, so it follows whatever the walk does. It needs the
    walk's Node.js tools, which ``install.py --no-walk-tools`` leaves out.
    """
    clone = checkout("ZMART-interface")
    if not (clone / "node_modules").is_dir():
        pytest.skip("the walk's Node.js tools are not installed (install.py --no-walk-tools)")
    sys.path.insert(0, str(REPO))
    try:
        import run_walk
    finally:
        sys.path.remove(str(REPO))
    env = {**os.environ, "PATH": os.pathsep.join([*run_walk.this_environments_programs(),
                                                  os.environ.get("PATH", "")]),
           "PYTHON": sys.executable}
    bridge = run_walk.where_the_walks_bridge_finds_the_interface(clone, env)
    write_report("walk-bridge-python", bridge)
    imported = Path(bridge["imported"]).resolve()
    assert clone.resolve() not in imported.parents, (
        f"the walk's bridge imports the interface from its clone ({imported}), "
        "so the walk would test the clone, not the installed block"
    )
    installed = Path(__import__("zmart_interface").__file__).resolve()
    assert imported == installed, (imported, installed)
