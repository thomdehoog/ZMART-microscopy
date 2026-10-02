"""A capture travels from a mock microscope, through the interface's writer, to the viewer.

This is the path every picture on the operator's canvas takes. A mock
microscope captures a field through the controller, and its answer must fit
the controller's contract for an acquisition (``check_acquire_answer``): every
saved file under ``files``, and under ``planes`` the file, channel, depth,
moment and stage position of each picture. The interface moves the files into
the run and writes them as one OME-Zarr position, reading nothing but
``files`` and ``planes``. The viewer, started beside the run the way the
interface's bridge starts it -- laid out over the reach the controller's
``get_xyz`` reports per axis, everywhere a picture can show -- opens that
position and lists it in
``/api/config``, which is where any drawing engine learns what there is to
draw.

The same is asked of both mocks: the interface's own (the kidney) and the
controller's (the beads). The interface promises to work with any microscope
the controller drives, so a capture that fits the controller's contract must
be one its writer can keep. Real drivers are not asked to capture here: that
needs their microscope, and their own tests check their answers.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import pytest

from conftest import checkout, write_report

#: Capture one field on a mock, keep it the way the bridge keeps a scan's
#: field, publish it to the viewer, and ask the viewer what it serves.
CAPTURE_KEEP_AND_SERVE = """
    import json, sys, time, urllib.request
    from pathlib import Path
    import zmart_controller
    import zmart_controller.session
    from zmart_interface.parts.storage import viewer_service
    from zmart_interface.parts.storage.output import (
        move_record_images, position_label, prepare_acquisition, prepare_experiment)
    from zmart_controller.utils import check_acquire_answer
    from zmart_interface.parts.storage.zarr_positions import position_store_from_record

    which, output_root, driver = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    if which == "interface":
        from zmart_interface import mock_microscope
        added = mock_microscope.register()
    else:
        added = zmart_controller.register_driver(driver, remember=False)
    connection = {**added[0], "output_root": str(output_root)}
    if which == "controller":
        connection["mock_timing"] = "instant"
    session = zmart_controller.session.set_instrument(connection)
    try:
        info = session.get_info()["report"]
        standing = session.get_xyz()["report"]
        area = {f"{axis}_um": standing[axis]["reach"] for axis in ("x", "y", "z")}
        run = prepare_experiment(info["output_root"], "assembly")
        answer = session.acquire(acquisition_type="overview", position_label=position_label(0))
        problems = check_acquire_answer(answer)
        if not answer["success"] or problems:
            raise SystemExit(f"the capture does not fit the contract: {problems} {answer}")
        record = answer["report"]
        move_record_images(record, prepare_acquisition(run, "overview").data)
        folder = run / "positions" / "overview"
        store = position_store_from_record(record, folder)
    finally:
        session.disconnect()

    viewer_service.start(run, bake=True, canvas=area)
    viewer_service.a_position_landed("overview", folder, store=store)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        status = viewer_service.status()
        if status["publications"].get("overview", {}).get("state") == "ready" and status["sources"]:
            break
        time.sleep(0.5)
    config = json.load(urllib.request.urlopen(status["url"] + "/api/config", timeout=60))
    viewer_service.stop()
    print(json.dumps({"store": str(store), "status": status, "config": config}))
"""


def _addresses_in(config: dict) -> list[str]:
    """Every data address the viewer's configuration names, as text."""
    found = []

    def walk(value):
        if isinstance(value, dict):
            for inner in value.values():
                walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)
        elif isinstance(value, str):
            found.append(value)

    walk(config.get("layers", []))
    return found


def _check_served(said: dict) -> None:
    status = said["status"]
    assert status["running"] and not status["error"], status
    assert status["publications"]["overview"]["state"] == "ready", status
    assert status["publications"]["overview"]["published"] == 1, status
    assert said["config"].get("layers"), said["config"]
    assert any("overview" in address for address in _addresses_in(said["config"])), said["config"]


def test_a_capture_from_the_interfaces_mock_is_served_by_the_viewer(fresh_python, tmp_path):
    """The kidney mock's field, taken where the stage stands after Connect, is served by the viewer.

    Nothing is stood in for: the controller, the interface's writer and its
    viewer service, and the installed viewer, all as the bridge uses them.
    The field is taken before anything is moved, which is the first place an
    operator may press Acquire.
    """
    said = fresh_python(CAPTURE_KEEP_AND_SERVE, "interface", str(tmp_path / "runs"), "",
                        env={"ZMART_MOCK_STATE": str(tmp_path / "instrument.json")})
    write_report("viewer-serves-interface-mock", said)
    _check_served(said)


def test_a_capture_from_the_controllers_mock_is_served_by_the_viewer(fresh_python, tmp_path):
    """The controller's mock (beads) fits the contract, so the interface keeps its capture and the viewer serves it."""
    driver = checkout("ZMART-controller") / "tests" / "mock_zmart_driver"
    said = fresh_python(CAPTURE_KEEP_AND_SERVE, "controller", str(tmp_path / "runs"), str(driver))
    write_report("viewer-serves-controller-mock", said)
    _check_served(said)
