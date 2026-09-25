"""useq sequences run by the pymmcore-plus runner through NisEngine, the bridge and a fake NIS."""

import pytest
import tifffile
import useq
import useq.v2 as v2
from nis_useq.engine import NisEngine
from useq import Channel, CustomAction, HardwareAutofocus, MDAEvent

pymmcore_plus = pytest.importorskip("pymmcore_plus")
from pymmcore_plus.mda import MDARunner, PMDAEngine  # noqa: E402


class Frames:
    """A pymmcore-plus output handler that keeps every frame."""

    def __init__(self):
        self.images, self.events, self.metas = [], [], []

    def frameReady(self, image, event, meta):
        self.images.append(image)
        self.events.append(event)
        self.metas.append(meta)

    @property
    def z(self):
        return [meta["position"]["z"] for meta in self.metas]


@pytest.fixture
def engine(port):
    engine = NisEngine("127.0.0.1", port, timeout=5.0)
    yield engine
    engine.close()


def run(engine, sequence, output=None):
    runner = MDARunner()
    runner.set_engine(engine)
    frames = Frames()
    runner.run(sequence, output=[frames] + ([output] if output else []))
    return frames


def moves(fake):
    return [call for call in fake.calls if call.startswith("move")]


# -- the engine and the runner ----------------------------------------------------


def test_is_a_pymmcore_plus_engine(engine):
    assert isinstance(engine, PMDAEngine)


def test_v2_sequence_positions_channels_and_z(engine, fake):
    sequence = v2.MDASequence(
        axes=(
            v2.StagePositions(
                values=[
                    v2.Position(x=100, y=200, z=500, name="a"),
                    v2.Position(x=300, y=200, z=600, name="b"),
                ]
            ),
            v2.ChannelsPlan(values=[Channel(config="DAPI", exposure=20), Channel(config="FITC")]),
            v2.ZRangeAround(range=2, step=1),
        ),
        axis_order=("p", "c", "z"),
    )
    frames = run(engine, sequence)

    assert len(frames.images) == 12
    # every frame is a new capture, in order (capture 1 was the size probe)
    assert [int(image.max()) for image in frames.images] == list(range(2, 14))
    assert frames.z == [499, 500, 501] * 2 + [599, 600, 601] * 2
    assert frames.events[0].pos_name == "a" and frames.metas[0]["exposure_ms"] == 20
    # the channel and exposure are sent only when they change
    assert [c for c in fake.calls if c.startswith(("config", "exposure"))] == [
        "config(DAPI)", "exposure(20)", "config(FITC)",
        "config(DAPI)", "exposure(20)", "config(FITC)",
    ]  # fmt: skip


def test_classic_sequence(engine):
    sequence = useq.MDASequence(
        stage_positions=[(100, 200, 500)],
        channels=["DAPI"],
        z_plan={"top": 510, "bottom": 500, "step": 5},
    )
    assert run(engine, sequence).z == [500, 505, 510]


def test_time_plan_is_timed_by_the_runner(engine):
    sequence = v2.MDASequence(time_plan={"interval": 0.2, "loops": 3})
    times = [meta["runner_time_ms"] for meta in run(engine, sequence).metas]
    assert len(times) == 3 and times[2] - times[0] >= 390


def test_writes_ome_tiff(engine, tmp_path):
    sequence = useq.MDASequence(
        channels=["DAPI", "FITC"], z_plan={"top": 502, "bottom": 500, "step": 1}
    )
    run(engine, sequence, output=tmp_path / "run.ome.tiff")
    data = tifffile.imread(tmp_path / "run.ome.tiff")
    assert data.shape == (2, 3, 48, 64)


def test_writes_ome_zarr(engine, tmp_path):
    pytest.importorskip("tensorstore")
    sequence = useq.MDASequence(stage_positions=[(0, 0, 500), (10, 0, 500)], channels=["DAPI"])
    run(engine, sequence, output=tmp_path / "run.ome.zarr")
    assert (tmp_path / "run.ome.zarr" / "zarr.json").exists()


def test_second_run_needs_no_size_probe(engine, fake):
    sequence = useq.MDASequence(time_plan={"interval": 0, "loops": 2})
    run(engine, sequence)
    run(engine, sequence)
    assert fake.captures == 1 + 2 + 2


def test_temporary_images_are_removed(engine):
    run(engine, useq.MDASequence(time_plan={"interval": 0, "loops": 1}))
    assert not engine._workdir.exists()


# -- checks before anything moves ---------------------------------------------------


def test_position_outside_the_limits_stops_the_run_before_any_move(engine, fake):
    sequence = useq.MDASequence(stage_positions=[(0, 0, 500), (0, 0, 20000)])
    with pytest.raises(ValueError, match="z = 20000.0 um is outside the stage limits"):
        run(engine, sequence)
    assert moves(fake) == []


def test_unknown_optical_configuration(engine, fake):
    with pytest.raises(ValueError, match="'GFP' is not an optical configuration"):
        run(engine, useq.MDASequence(channels=["DAPI", "GFP"]))
    assert fake.captures == 1  # only the size probe


@pytest.mark.parametrize(
    "event, message",
    [
        (MDAEvent(roi=(0, 0, 10, 10)), "ROI"),
        (MDAEvent(properties=[("Camera", "Binning", 2)]), "unsupported property Camera.Binning"),
        (MDAEvent(properties=[("Nosepiece", "Position", 3)]), "no objective in nosepiece slot 3"),
        (MDAEvent(properties=[("PFS", "State", "maybe")]), "On"),
        (MDAEvent(action=CustomAction(name="bleach")), "the only custom action"),
        (MDAEvent(action=HardwareAutofocus(autofocus_motor_offset=10)), "PFS offset"),
    ],
)
def test_unsupported_events_are_refused(engine, event, message):
    with pytest.raises(ValueError, match=message):
        run(engine, [MDAEvent(), event])


def test_pfs_actions_need_a_pfs(port, fake):
    fake.has_pfs = False
    engine = NisEngine("127.0.0.1", port, timeout=5.0)
    with pytest.raises(ValueError, match="needs a Perfect Focus System"):
        run(engine, [MDAEvent(action=HardwareAutofocus())])
    engine.close()


def test_relative_z_needs_a_position_z(engine, fake):
    sequence = useq.MDASequence(stage_positions=[(100, 200)], z_plan={"range": 4, "step": 2})
    with pytest.raises(ValueError, match="not every stage position has a z"):
        run(engine, sequence)
    assert moves(fake) == []


# -- properties and focus ------------------------------------------------------------


def test_nosepiece_and_pfs_properties(engine, fake):
    run(engine, [MDAEvent(properties=[("Nosepiece", "Position", 4), ("PFS", "State", "On")])])
    assert "objective(4)" in fake.calls and "pfs(on)" in fake.calls


@pytest.mark.parametrize(
    "make_sequence, planes",
    [
        # classic useq focuses at the position (500), so the stack is centred on the focus
        (useq.MDASequence, [501, 502, 503]),
        # useq v2 focuses at the first plane (499), so the stack starts at the focus
        (v2.MDASequence, [502, 503, 504]),
    ],
)
def test_hardware_autofocus_shifts_the_planes_at_that_position(engine, fake, make_sequence, planes):
    sequence = make_sequence(
        stage_positions=[(100, 200, 500)],
        z_plan={"range": 2, "step": 1},
        autofocus_plan=useq.AxesBasedAF(axes=("p",)),
    )
    frames = run(engine, sequence)
    assert frames.z == planes  # the PFS locked at 502
    assert fake.calls[2:4] == ["pfs(on)", "pfs(off)"] and fake.calls.count("pfs(on)") == 1


def test_software_autofocus(engine, fake):
    focus = CustomAction(name="autofocus", data={"range_um": 20, "speed": 40})
    events = [
        MDAEvent(index={"p": 0}, z_pos=500, action=focus),
        MDAEvent(index={"p": 0}, z_pos=500),
    ]
    assert run(engine, events).z == [503]
    assert "autofocus(20,40)" in fake.calls


def test_failed_focus_warns_and_the_run_goes_on(engine, fake, caplog):
    fake.autofocus_result = 0
    focus = CustomAction(name="autofocus")
    events = [
        MDAEvent(index={"p": 0}, z_pos=500, action=focus),
        MDAEvent(index={"p": 0}, z_pos=500),
    ]
    assert run(engine, events).z == [500]
    assert "focus not found" in caplog.text


def test_pfs_that_does_not_lock_is_switched_off(engine, fake, monkeypatch, caplog):
    monkeypatch.setattr(fake, "pfs_status", lambda: 6)  # "search stopped"
    events = [MDAEvent(z_pos=500, action=HardwareAutofocus()), MDAEvent(z_pos=500)]
    assert run(engine, events).z == [500]
    assert "cannot find focus" in caplog.text and fake.calls[-2:] == ["move_z(500)", "capture"]
    assert "pfs(off)" in fake.calls


def test_focus_correction_cannot_push_the_stage_past_its_limits(engine, fake):
    fake.focal_plane_z = 9990.0  # the PFS locks near the top of the Z range
    events = [MDAEvent(index={"p": 0}, z_pos=9000, action=HardwareAutofocus())]
    events.append(MDAEvent(index={"p": 0}, z_pos=9500))  # 9500 + 990 is past 10000
    with pytest.raises(ValueError, match="with focus correction.*outside the stage limits"):
        run(engine, events)


# -- without pymmcore-plus: the calls a runner makes -------------------------------


def test_engine_can_be_driven_by_hand(engine):
    sequence = useq.MDASequence(channels=["DAPI"], stage_positions=[(10, 20, 30)])
    summary = engine.setup_sequence(sequence)
    assert summary["image_infos"][0]["plane_shape"] == (48, 64)
    images = []
    for event in engine.event_iterator(sequence):
        engine.setup_event(event)
        images += [image for image, _, _ in engine.exec_event(event)]
        engine.teardown_event(event)
    engine.teardown_sequence(sequence)
    assert len(images) == 1 and images[0].dtype == "uint16"
