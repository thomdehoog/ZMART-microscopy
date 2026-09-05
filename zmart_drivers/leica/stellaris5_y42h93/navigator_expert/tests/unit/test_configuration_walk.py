"""The ZMART driver configuration workflow, walked against this driver.

Nothing of the driver is stood in for. The setup adapter, the machine
profile and its ProgramData layout, the limits, orientation, calibration and
origin modules, the acquisition path, the gate and the connect handshake all
run as they would on the instrument. Two things are stood in for, because a
test machine has neither: the CAM socket, played by ``MockLasxClient``, the
behavioural stand-in the rest of this suite uses; and the camera's pixels,
which LAS X native AutoSave would write to disk after an acquisition. Here a
picture of a real micrograph is written there instead, of the sample as it
would look from where the stage stands, through the lens the job carries,
recorded by a camera mounted a quarter-turn round.

The walk is the one the operator page makes, through the same seam the
bridge calls, in the same order: limits from the four corners, the origin
where the stage stands, the orientation from three pictures and a known
move, the objective pair from a focus stack under each lens. Each step
publishes into one configuration. Then a controller session opens on that
configuration, and what the driver loaded at connect is compared with what
was published: the gate's limits, the orientation, the lens translations,
and the frame counting from the origin.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import tifffile

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[6]
_HELPERS = _HERE.parents[1] / "helpers"
for _p in (_REPO_ROOT, _HELPERS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mock_lasx_api import MockLasxClient  # noqa: E402
from navigator_expert.acquisition import materialize, product  # noqa: E402
from navigator_expert.acquisition import save as _save  # noqa: E402
from navigator_expert.commands import gate as _gate  # noqa: E402
from navigator_expert.config import machine as _machine  # noqa: E402
from navigator_expert.connection import session as drv_session  # noqa: E402
from navigator_expert.connection import session_state  # noqa: E402
from navigator_expert.zmart_adapter import setup as leica_setup  # noqa: E402
from navigator_expert.zmart_adapter import zmart_adapter as adapter  # noqa: E402

import zmart_controller  # noqa: E402
import zmart_drivers.setup as seam  # noqa: E402
from zmart_drivers.mock import mock_driver, mock_setup  # noqa: E402
from zmart_drivers.setup import procedures  # noqa: E402

#: How the pretend camera is mounted: the quarter-turn the orientation step
#: has to find.
CAMERA = {"rotation_deg": 90, "reflection": False}
#: Where each lens looks and focuses relative to the 10x, in micrometres.
#: The 10x is the reference; the 40x is off, as a real 40x tends to be.
OFFSET_UM = {1: (0.0, 0.0, 0.0), 2: (-18.0, 11.0, 3.5)}
#: The two jobs an operator would have set up in LAS X, one per lens.
JOBS = {
    "Overview": {"slot": 1, "name": "HC PL APO 10x/0.40 CS2", "magnification": 10,
                 "pixel_um": 4.0, "frame_px": 256},
    "HiRes": {"slot": 2, "name": "HC PL APO 40x/1.30 OIL CS2", "magnification": 40,
              "pixel_um": 1.0, "frame_px": 256},
}
HOME = (50000.0, 30000.0)


def _instrument() -> MockLasxClient:
    """The stand-in for the CAM socket, with the two jobs an operator set up."""
    client = MockLasxClient(latency=0.0)
    for job, spec in JOBS.items():
        field_um = spec["pixel_um"] * spec["frame_px"]
        client._jobs[job].update({
            "objective": {"name": spec["name"], "magnification": spec["magnification"],
                          "slotIndex": spec["slot"]},
            "pixelSize": f"{spec['pixel_um']} um x {spec['pixel_um']} um",
            "format": f"{spec['frame_px']} x {spec['frame_px']}",
            "imageSize": f"{field_um} um x {field_um} um",
        })
    client._selected_job = "Overview"
    return client


def _the_operator_focuses(client: MockLasxClient, job: str) -> None:
    """Focus in LAS X: put the job's Z where the sample is sharp under its lens."""
    x, y = client._stage_x * 1e6, client._stage_y * 1e6
    sharp = mock_driver.sharp_height_um(x, y) + OFFSET_UM[JOBS[job]["slot"]][2]
    client._jobs[job]["zPosition"]["z-wide"]["position"] = sharp


def _camera(root: Path):
    """What LAS X native AutoSave writes after an acquire: one plane of the
    sample as seen from where the stage stands, through the job's lens, by
    the camera as mounted."""
    def collect(client, acq, **_kw):
        job = client._jobs[acq.job]
        x, y = client._stage_x * 1e6, client._stage_y * 1e6
        z = float(job["zPosition"]["z-wide"]["position"])
        slot = job["objective"]["slotIndex"]
        pixel = float(job["pixelSize"].split()[0])
        frame_px = int(job["format"].split()[0])
        dx, dy, dz = OFFSET_UM[slot]
        aligned = mock_driver._the_sample_from(np, x + dx, y + dy, z - dz, 0, frame_px=frame_px, pixel_um=pixel)
        raw = mock_setup.as_the_camera_records(np, aligned, CAMERA)
        folder = root / "autosave" / f"{acq.job}-{acq.started_at:.6f}"
        folder.mkdir(parents=True)
        path = folder / "image--Z00--C00.ome.tif"
        tifffile.imwrite(str(path), raw)
        return product.ExportedAcquisition(
            source_root=folder.parent, source_dir=folder,
            positions=[product.ExportedPosition(
                t=0, planes={product.PlaneIndex(0, 0, 0): product.PlaneSource(path=path)})],
            metadata=product.AcquisitionMetadata(
                size_x=frame_px, size_y=frame_px, size_t=1, size_z=1, size_c=1, pixel_type="uint16",
                physical_size_x_um=pixel, physical_size_y_um=pixel,
                channels=(product.ChannelMetadata(index=0, name="C0"),)),
            method="test camera", source_exporter="lasx_native_autosave", vendor_metadata_sources=(),
        )
    return collect


@pytest.fixture
def stand_ins(tmp_path):
    """The CAM socket and the camera, stood in for; everything else is the driver."""
    client = _instrument()
    healthy = {"path": "x", "corrupted": False, "violations": [], "error": None}
    with (
        patch.object(drv_session, "connect_python_client", return_value=client),
        patch.object(_save, "collect_lasx_native_autosave", _camera(tmp_path)),
        patch.object(materialize._ome, "check_ome_tiff", return_value=healthy),
        patch.object(materialize._ome, "check_ome_xml_file", return_value=healthy),
    ):
        yield client
    _machine.use_configuration(None)


def test_the_workflow_configures_this_driver_and_a_session_then_stands_on_it(stand_ins, tmp_path):
    client = stand_ins
    instrument = next(i for i in seam.get_instruments() if i["vendor"] == "leica")

    # ---- Connect, with New configuration chosen on the card ----------------
    setup = seam.open_setup(instrument)
    started = setup.new_configuration()
    assert setup.configuration()["id"] == started["id"]
    assert started["has"] == {"limits": False, "orientation": False, "calibration": False, "origin": False}

    # ---- Define limits: the operator drives to each corner in LAS X, the
    #      page imports the drives' reading there -----------------------------
    corners = [(5000.0, 6000.0), (110000.0, 6000.0), (5000.0, 70000.0), (110000.0, 70000.0)]
    read = [setup.move(x, y, 0.0) for x, y in corners]
    xs = [r["x_um"] for r in read]
    ys = [r["y_um"] for r in read]
    limits = dict(setup.read("limits", fresh=True)["document"])
    limits["x_um"] = {"range": [min(xs), max(xs)]}
    limits["y_um"] = {"range": [min(ys), max(ys)]}
    setup.publish("limits", limits)
    assert setup.read("limits")["source"] == "published"

    # ---- Define coordinate system origin: back to the field, focused ---------
    setup.move(*HOME, 0.0)
    _the_operator_focuses(client, "Overview")
    origin = procedures.origin_here(setup)
    # the stand-in keeps the stage in metres, so a nanometre of rounding is fair
    assert abs(origin["x_um"] - HOME[0]) < 1e-3 and abs(origin["y_um"] - HOME[1]) < 1e-3
    setup.publish("origin", origin)

    # ---- Image-to-stage calibration: three pictures and a known move ---------
    orientation = procedures.measure_orientation(setup, into=tmp_path / "orientation", stage_move_um=40.0)
    assert orientation["accepted"], orientation.get("why")
    assert (orientation["orientation"]["rotation_deg"], orientation["orientation"]["reflection"]) == (90, False)
    setup.publish("orientation", orientation["orientation"],
                  evidence=[orientation["diagnostic"]])
    assert setup.read("orientation")["source"] == "published"

    # ---- Objective calibration: the 10x, then the operator switches to the
    #      40x's job in LAS X and refocuses, then the pair ----------------------
    turn = orientation["orientation"]
    reference = procedures.capture_lens_view(setup, into=tmp_path / "lens", name="1-2-reference",
                                             orientation=turn)
    assert reference["lens"]["slot"] == 1
    client._selected_job = "HiRes"
    _the_operator_focuses(client, "HiRes")
    target = procedures.capture_lens_view(setup, into=tmp_path / "lens", name="1-2-target",
                                          orientation=turn)
    assert target["lens"]["slot"] == 2
    pair = procedures.measure_objective_pair(reference, target)
    assert pair["accepted"], pair.get("why")
    dx, dy, dz = pair["translation_um"]["x"], pair["translation_um"]["y"], pair["translation_um"]["z"]
    assert abs(dx - OFFSET_UM[2][0]) <= 4.0 and abs(dy - OFFSET_UM[2][1]) <= 4.0
    assert abs(dz - OFFSET_UM[2][2]) <= 0.6
    document = {"objectives": {
        "1": {"name": JOBS["Overview"]["name"], "translation_um": [0.0, 0.0, 0.0]},
        "2": {"name": JOBS["HiRes"]["name"], "translation_um": [dx, dy, dz]},
    }}
    # Evidence goes in under names that say which pair and side it is, the
    # way the bridge stages it: a snapshot holds them flat, so two focus
    # sheets both called focus.png would collide.
    staged = tmp_path / "evidence"
    staged.mkdir()
    evidence = []
    for name, source in (("1-2-reference_focus.png", reference["diagnostic"]),
                         ("1-2-target_focus.png", target["diagnostic"]),
                         ("1-2-objective_pair.png", pair["diagnostic"])):
        (staged / name).write_bytes(Path(source).read_bytes())
        evidence.append(str(staged / name))
    setup.publish("calibration", document, evidence=evidence)
    listed = setup.configurations()[0]
    assert listed["id"] == started["id"]
    assert listed["has"] == {"limits": True, "orientation": True, "calibration": True, "origin": True}
    setup.close()

    # ---- What the folder holds: the driver's own layout, evidence beside ---
    made = _machine.MACHINE.api_root() / started["id"]
    assert sorted(p.name for p in made.iterdir()) == ["calibration", "limits", "orientation", "origin"]
    newest_orientation = sorted((made / "orientation").iterdir())[-1]
    assert (newest_orientation / "orientation.json").is_file()
    assert (newest_orientation / "orientation.png").is_file()

    # ---- A session on that configuration, through the controller ------------
    client2 = _instrument()
    with patch.object(drv_session, "connect_python_client", return_value=client2):
        offered = zmart_controller.get_configurations(instrument)
        assert offered[0]["id"] == started["id"]
        session = zmart_controller.set_instrument({**instrument, "configuration": started["id"]})
        try:
            # the gate stands on the published limits, not the bundled fallback
            governing = _gate.describe(client2)
            assert governing is not None and not governing.get("is_fallback"), governing
            assert started["id"] in str(governing.get("path"))
            # the orientation and the lens translations are the ones published
            loaded = session_state.get(client2)
            assert loaded.orientation.rotate_deg == 90 and loaded.orientation.mirrored is False
            assert loaded.translations is not None
            got = loaded.translations[2]
            assert abs(got[0] - dx) < 1e-6 and abs(got[1] - dy) < 1e-6 and abs(got[2] - dz) < 1e-6
            # and the frame counts from the origin: the stage stands where the
            # origin was read, so the position reads as zero
            client2._stage_x, client2._stage_y = HOME[0] * 1e-6, HOME[1] * 1e-6
            client2._sync_stage_to_jobs()
            pos = session.get_xyz()
            assert abs(pos["x"]["value"]) < 1e-6 and abs(pos["y"]["value"]) < 1e-6
        finally:
            session.disconnect()

    # ---- and one without limits is refused by the controller: the first
    #      configuration, seeded at the very first open, never had any --------
    seeded = sorted(p.name for p in _machine.MACHINE.configurations())[0]
    assert seeded != started["id"]
    with pytest.raises(RuntimeError, match="no limits"):
        zmart_controller.set_instrument({**instrument, "configuration": seeded})
