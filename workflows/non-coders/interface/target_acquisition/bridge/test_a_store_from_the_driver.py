"""A driver that saves a capture as one OME-Zarr image: the interface keeps that one copy.

A driver may offer ``"ome-zarr"`` in its ``format`` setting. The interface
then asks for it, and the capture arrives as one OME-Zarr 0.5 store, every
plane's ``path`` pointing into it with ``c``, ``z``, ``t`` as the index (the
controller's acquire contract). The interface uses that store as it is --
for the viewer, the small pictures and the analysis -- and writes no copy
of its own. A driver that offers only OME-TIFF is converted as before.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")
models = pytest.importorskip("ome_zarr_models.v05.image")

from ome_zarr_models.v05.axes import Axis  # noqa: E402
from pydantic_zarr.v3 import ArraySpec  # noqa: E402
from zmart_controller.template.zmart_controller_plugin.zmart_controller_plugin import (  # noqa: E402
    ZmartControllerPlugin,
)

from ..microscope.instrument import Instrument  # noqa: E402
from ..storage import viewer_service  # noqa: E402
from ..storage.jpeg_tiles import make_what_is_missing  # noqa: E402
from . import pictures, state  # noqa: E402


def a_driver_store(data: Path, name: str, pixels: np.ndarray, *, pixel_um: float = 2.0) -> Path:
    """An OME-Zarr 0.5 image as a driver writes one: axes t, c, z, y, x, one level."""
    store = data / name
    spec = ArraySpec.from_array(
        pixels, dimension_names=list("tczyx"), codecs=[{"name": "bytes", "configuration": {"endian": "little"}}],
    )
    image = models.Image.new(
        array_specs=[spec],
        paths=["0"],
        axes=[
            Axis(name="t", type="time", unit="second"),
            Axis(name="c", type="channel"),
            Axis(name="z", type="space", unit="micrometer"),
            Axis(name="y", type="space", unit="micrometer"),
            Axis(name="x", type="space", unit="micrometer"),
        ],
        scales=[[1.0, 1.0, 1.0, pixel_um, pixel_um]],
        translations=[[0.0, 0.0, 0.0, 0.0, 0.0]],
        multiscale_type="mean",
    )
    image.to_zarr(zarr.storage.LocalStore(str(store)), path="")["0"][...] = pixels
    return store


def a_record_from(store: Path, *, channels: int, label: str = "A1") -> dict:
    planes = [
        {"path": str(store), "t": 0, "z": 0, "c": c, "x_um": 100.0, "y_um": 50.0, "z_um": 3.0}
        for c in range(channels)
    ]
    return {"position_label": label, "files": [str(store)], "planes": planes, "format": "ome-zarr"}


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "run", tmp_path / "run")
    (tmp_path / "run" / "overview" / "data").mkdir(parents=True)
    return tmp_path / "run"


@pytest.fixture
def announced(monkeypatch):
    told = []
    monkeypatch.setattr(
        viewer_service, "a_position_landed",
        lambda kind, folder, *, store, projections_in=None: told.append((kind, Path(folder), Path(store))),
    )
    return told


def test_the_drivers_store_is_used_and_no_copy_is_made(run, announced):
    pixels = np.arange(2 * 64 * 64, dtype=np.uint16).reshape(1, 2, 1, 64, 64)
    store = a_driver_store(run / "overview" / "data", "overview_000001_A1.ome.zarr", pixels)
    record = a_record_from(store, channels=2)

    pictures.keep_position_as_zarr(record, "overview")

    assert "zarr_error" not in record
    assert record["zarr"] == str(store)
    assert record["frame_um"] == pytest.approx(64 * 2.0)
    assert not (run / "positions").exists(), "no second copy of the capture"
    assert announced == [("overview", store.parent, store)]


def test_a_tiff_capture_is_still_converted(run, announced, monkeypatch):
    converted = []
    monkeypatch.setattr(
        pictures, "position_store_from_record",
        lambda record, folder: converted.append(folder) or Path(folder) / "x.ome.zarr",
    )
    monkeypatch.setattr(pictures, "frame_um_of", lambda store: 1.0)
    record = {"position_label": "A1", "planes": [{"path": str(run / "a.ome.tif"), "c": 0, "z": 0, "t": 0}]}

    pictures.keep_position_as_zarr(record, "overview")

    assert converted == [run / "positions" / "overview"]


def test_the_small_picture_is_drawn_from_the_store(tmp_path):
    pixels = np.zeros((1, 2, 1, 64, 64), dtype=np.uint16)
    pixels[0, 0, 0, 10:20, 10:20] = 4000
    store = a_driver_store(tmp_path / "data", "overview_000001_C1.ome.zarr", pixels)
    record = a_record_from(store, channels=2, label="C1")

    note = make_what_is_missing(tmp_path / "view", {"C1": (record["planes"], (100.0, 50.0))})

    [tile] = json.loads(note.read_text())["tiles"]
    assert tile["label"] == "C1"
    assert tile["w"] == pytest.approx(64 * 2.0)
    assert tile["x0"] + tile["w"] / 2 == pytest.approx(100.0)


def test_a_rerun_stops_showing_the_drivers_stores_but_never_deletes_them(run, monkeypatch):
    store = a_driver_store(
        run / "overview" / "data", "overview_000001_A1.ome.zarr", np.zeros((1, 1, 1, 8, 8), np.uint16)
    )
    forgotten = []
    monkeypatch.setattr(viewer_service, "forget_stores", lambda kind, keeping: forgotten.append((kind, keeping)))
    monkeypatch.setattr(viewer_service, "stores_were_retired", lambda kind, folder: None)

    pictures.replace_the_acquisition("overview", keeping=set())

    assert store.is_dir(), "a driver's store is the capture itself, and stays"
    assert forgotten == [("overview", set())]


def test_forgetting_drops_a_kinds_stores_from_what_the_viewer_is_handed(monkeypatch, tmp_path):
    monkeypatch.setitem(viewer_service._viewer, "source_versions", {
        ("overview", "overview_000001_A1.ome.zarr"): 1,
        ("overview", "overview_x_A2.ome.zarr"): 2,
        ("targets", "targets_000002_T1.ome.zarr"): 1,
    })
    monkeypatch.setitem(viewer_service._viewer, "source_order", {
        "overview": ["overview_000001_A1.ome.zarr", "overview_x_A2.ome.zarr"],
        "targets": ["targets_000002_T1.ome.zarr"],
    })
    monkeypatch.setitem(viewer_service._viewer, "folder_types", {str(tmp_path / "data"): "overview"})
    monkeypatch.setitem(viewer_service._viewer, "pending", set())
    monkeypatch.setitem(viewer_service._viewer, "wake", type("Wake", (), {"set": lambda self: None})())

    viewer_service.forget_stores("overview", keeping={"overview_x_A2.ome.zarr"})

    assert set(viewer_service._viewer["source_versions"]) == {
        ("overview", "overview_x_A2.ome.zarr"), ("targets", "targets_000002_T1.ome.zarr"),
    }
    assert viewer_service._viewer["source_order"]["overview"] == ["overview_x_A2.ome.zarr"]
    assert viewer_service._viewer["pending"] == {str(tmp_path / "data")}


class FakeSession:
    def __init__(self):
        self.asked = None
        self.context = {"driver": "a driver"}

    def acquire(self, **asked):
        self.asked = asked
        return {"success": True, "output": {
            "position_label": asked["position_label"], "acquisition_type": asked["acquisition_type"],
            "files": [], "planes": [],
        }}


def test_the_driver_is_given_the_acquisition_type_and_the_runs_folder_for_it(tmp_path):
    """The label goes as it is, the kind of acquisition beside it, and the
    folder to save in is the run's folder for that kind. The answer is the
    controller's, untouched."""
    session = FakeSession()
    instrument = Instrument(session)
    instrument.run = tmp_path / "a-run_a1b2c3"

    answer = instrument.acquire_answer(position_label="K00_M000000_G000000_P000001_V00",
                                       acquisition_type="overview")

    assert session.asked == {
        "position_label": "K00_M000000_G000000_P000001_V00", "acquisition_settings": None,
        "acquisition_type": "overview", "output_folder": str(instrument.run / "overview"),
    }
    assert (instrument.run / "overview").is_dir()
    assert answer == {"success": True, "output": {
        "position_label": "K00_M000000_G000000_P000001_V00", "acquisition_type": "overview",
        "files": [], "planes": [],
    }}


def test_without_a_run_the_driver_saves_where_it_was_set_up():
    session = FakeSession()

    Instrument(session).acquire_answer(position_label="P0", acquisition_type="overview")

    assert session.asked["output_folder"] is None
    assert session.asked["acquisition_type"] == "overview"


def test_a_rerun_never_overwrites_an_earlier_capture(mock_session, tmp_path):
    """The same label taken twice in a run: both captures stand in the run's folder.

    The driver saves the second under a name of its own, so the first one's
    files are untouched; filing either moves nothing.
    """
    from ..storage.output import move_record_images, prepare_acquisition, prepare_experiment

    mock_session.run = prepare_experiment(tmp_path / "out", "a-run", hash6="a1b2c3")
    acquisition = prepare_acquisition(mock_session.run, "overview")
    first = mock_session.acquire(position_label="K00_M000000_G000000_P000001_V00", acquisition_type="overview")
    before = {path: Path(path).read_bytes() for path in first["files"]}
    again = mock_session.acquire(position_label="K00_M000000_G000000_P000001_V00", acquisition_type="overview")

    assert not set(first["files"]) & set(again["files"])
    assert {Path(plane["path"]).parent for plane in first["planes"]} == {acquisition / "data"}
    assert {path: Path(path).read_bytes() for path in first["files"]} == before
    for record in (first, again):
        move_record_images(record, acquisition)
    assert {path: Path(path).read_bytes() for path in first["files"]} == before
    assert all(Path(path).is_file() for path in again["files"])


def test_the_viewer_is_told_where_the_drivers_projections_are(run, monkeypatch):
    landed = []
    monkeypatch.setattr(
        viewer_service, "a_position_landed",
        lambda kind, folder, *, store, projections_in=None: landed.append((kind, Path(projections_in))),
    )
    data = run / "focussing" / "data"
    data.mkdir(parents=True)
    stack = a_driver_store(data, "focussing_000001_F1.ome.zarr", np.zeros((1, 1, 3, 8, 8), np.uint16))
    # The driver's projection, under the store's own name in ``projections`` beside ``data``.
    a_driver_store(run / "focussing" / "projections", "focussing_000001_F1.ome.zarr",
                   np.zeros((1, 1, 1, 8, 8), np.uint16))
    record = a_record_from(stack, channels=1, label="F1")
    record["planes"] = [{**record["planes"][0], "z": z} for z in range(3)]
    flat = a_driver_store(run / "overview" / "data", "overview_000002_A1.ome.zarr", np.zeros((1, 1, 1, 8, 8), np.uint16))

    pictures.keep_position_as_zarr(record, "focussing")
    pictures.keep_position_as_zarr(a_record_from(flat, channels=1), "overview")

    assert landed == [
        ("focussing", run / "focussing" / "projections"),
        ("overview", run / "overview" / "data"),
    ], "a stack's projection is the driver's; a flat capture is its own"


def test_the_view_asks_the_viewer_to_read_the_given_projections(monkeypatch, tmp_path):
    asked = []
    monkeypatch.setattr(viewer_service, "_ask", lambda port, path, body: asked.append((path, body)))
    data = tmp_path / "run" / "overview" / "data"
    data.mkdir(parents=True)
    (data / "overview_1_A1.ome.zarr").mkdir()
    wake = type("Wake", (), {"set": lambda self: None})()
    for key, value in {
        "port": 1, "wake": wake, "opened": set(), "bake": False, "canvas": {},
        "run_folder": str(tmp_path / "run"), "pending": set(), "publishing": set(),
        "source_versions": {}, "source_order": {}, "folder_types": {}, "projections_in": {},
    }.items():
        monkeypatch.setitem(viewer_service._viewer, key, value)
    monkeypatch.setattr(viewer_service, "_refresh_metadata", lambda wake, include_pending: None)

    viewer_service.a_position_landed("overview", data, store=data / "overview_1_A1.ome.zarr", projections_in=data)
    viewer_service._publish_once(wake, {str(data)})

    [(path, body)] = asked
    assert path == "/api/stores/open"
    assert body["views"]["projection_path"] == str(data)
    assert body["views"]["projections_given"] is True


class NotSetUp(ZmartControllerPlugin):
    """A class driver whose data location is not set up yet."""

    def __init__(self, connection):
        pass

    def disconnect(self):
        pass

    def get_info(self):
        return True, ("A scope in memory. +z points up.", {
            "limits": {"done": True, "says": "published"},
            "data_location": {"done": False, "says": "run set_data_location.ipynb once"},
        }, False, {})

    def get_actuators(self):
        return True, tuple({"options": ["m"], "default": "m"} for _ in "xyz")

    def get_xyz(self, with_actuators):
        return True, (0.0, 0.0, 0.0, {"x": {"m": 0.0}, "y": {"m": 0.0}, "z": {"m": 0.0}},
                      (-10.0, 10.0, -10.0, 10.0, -1.0, 1.0))


def test_without_its_own_folder_for_runs_the_interface_refuses_to_connect(monkeypatch):
    """The interface decides where its runs go, from ``--output-root``; it never asks the driver.

    Without one, connect refuses and says how to start the interface, and
    names what the microscope still needs set up, in its own words.
    """
    from . import connecting

    monkeypatch.setitem(connecting.offered, "not-set-up", (NotSetUp, {}))
    monkeypatch.setattr(state, "output_root", None)

    with pytest.raises(RuntimeError, match="--output-root") as refused:
        connecting.connect({"instrument": "not-set-up"})
    assert "run set_data_location.ipynb once" in str(refused.value)


def test_the_run_folder_is_made_under_the_interfaces_own_folder(monkeypatch, tmp_path):
    from . import connecting

    monkeypatch.setitem(connecting.offered, "not-set-up", (NotSetUp, {}))
    monkeypatch.setattr(state, "output_root", str(tmp_path))
    monkeypatch.setattr(viewer_service, "start", lambda *args, **kwargs: None)
    try:
        connecting.connect({"instrument": "not-set-up", "experiment": "a-test"})
        run = state.the_run()
        assert run.parent == tmp_path and run.name.startswith("a-test_")
        assert state.session.run == run
    finally:
        connecting.close_the_last_session()


@pytest.mark.parametrize("installed", ["0.4.0rc7", "0.4.0", "0.4.7"])
def test_a_controller_whose_acquire_takes_the_type_and_the_folder_is_accepted(installed):
    from . import connecting

    connecting.accept_the_controller(installed)


@pytest.mark.parametrize("installed", ["0.2.0", "0.3.0", "0.4.0rc6", "0.5.0"])
def test_an_older_or_newer_controller_is_refused_in_words(installed):
    from . import connecting

    with pytest.raises(RuntimeError, match=f"the ZMART Controller {installed} is installed"):
        connecting.accept_the_controller(installed)


def test_the_installed_controller_is_accepted():
    from importlib.metadata import version

    from . import connecting

    connecting.accept_the_controller(version("zmart-controller"))
