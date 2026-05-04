import sys
from pathlib import Path

import pytest


def _load_calibration_module():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import navigator_expert.driver.calibration as calibration
    return calibration


def _config():
    return {
        "schema_version": 9,
        "reference_objective_slot": 1,
        "image_to_stage": [[0.0, -1.0], [1.0, 0.0]],
        "objectives": {
            "1": {
                "name": "ref",
                "shift_xy_um": [0.0, 0.0],
                "offset_z_um": 0.0,
                "shift_z_um": 0.0,
            },
            "2": {
                "name": "tgt",
                "shift_xy_um": [-6.0, 13.0],
                "offset_z_um": -120.0,
                "shift_z_um": -3.0,
            },
        },
    }


def test_shift_xy_returned_as_stored():
    cal = _load_calibration_module()
    assert cal.get_shift_xy_um(_config(), 1) == (0.0, 0.0)
    assert cal.get_shift_xy_um(_config(), 2) == (-6.0, 13.0)


def test_offset_z_returned_as_stored():
    cal = _load_calibration_module()
    assert cal.get_offset_z_um(_config(), 1) == 0.0
    assert cal.get_offset_z_um(_config(), 2) == -120.0


def test_shift_z_returned_as_stored():
    cal = _load_calibration_module()
    assert cal.get_shift_z_um(_config(), 1) == 0.0
    assert cal.get_shift_z_um(_config(), 2) == -3.0


def test_translate_xy_uses_shift_xy():
    cal = _load_calibration_module()
    cfg = _config()

    target_xy = cal.translate_xy_between_objectives(
        100.0, 200.0, cfg, from_slot=1, to_slot=2,
    )
    assert target_xy == (94.0, 213.0)  # (100, 200) + (-6, 13)

    source_xy = cal.translate_xy_between_objectives(
        *target_xy, cfg, from_slot=2, to_slot=1,
    )
    assert source_xy == (100.0, 200.0)


def test_translate_z_combines_offset_and_shift():
    cal = _load_calibration_module()
    cfg = _config()

    z_target = cal.translate_z_between_objectives(
        500.0, cfg, from_slot=1, to_slot=2,
    )
    # 500 + (-120 + -3) = 377
    assert z_target == 377.0

    # Round-trip
    z_back = cal.translate_z_between_objectives(
        z_target, cfg, from_slot=2, to_slot=1,
    )
    assert z_back == 500.0


def test_translate_xyz_combines_xy_and_z():
    cal = _load_calibration_module()
    cfg = _config()
    x, y, z = cal.translate_xyz_between_objectives(
        100.0, 200.0, 500.0, cfg, from_slot=1, to_slot=2,
    )
    assert (x, y, z) == (94.0, 213.0, 377.0)


def test_pixel_to_stage_uses_image_to_stage_matrix():
    cal = _load_calibration_module()
    xy = cal.pixel_to_stage_xy_um(
        60, 40,
        stage_xy_um=(100.0, 200.0),
        pixel_size_um=1.0,
        image_size=100,
        config=_config(),
    )
    assert xy == (110.0, 210.0)


def test_missing_shift_xy_raises_clearly():
    """A target without a measured shift should fail loudly, not silently
    return zero — silent zero would let the cookbook target the wrong
    place if someone forgot --measure-xy."""
    cal = _load_calibration_module()
    cfg = _config()
    cfg["objectives"]["2"].pop("shift_xy_um")
    with pytest.raises(ValueError, match="shift_xy_um"):
        cal.get_shift_xy_um(cfg, 2)


def test_missing_slot_raises_clearly():
    cal = _load_calibration_module()
    cfg = _config()
    with pytest.raises(ValueError, match="No calibration entry"):
        cal.get_shift_xy_um(cfg, 9)


def test_update_objective_writes_only_passed_fields():
    cal = _load_calibration_module()
    cfg = {"objectives": {}}
    cal.update_objective(cfg, 2, name="tgt", shift_xy_um=(1.5, -2.5))
    assert cfg["objectives"]["2"] == {
        "name": "tgt",
        "shift_xy_um": [1.5, -2.5],
    }
    cal.update_objective(cfg, 2, offset_z_um=-100.0, shift_z_um=-7.0)
    assert cfg["objectives"]["2"]["offset_z_um"] == -100.0
    assert cfg["objectives"]["2"]["shift_z_um"] == -7.0
    assert cfg["objectives"]["2"]["name"] == "tgt"  # untouched


def test_set_image_to_stage_coerces_to_floats():
    cal = _load_calibration_module()
    cfg = {}
    cal.set_image_to_stage(cfg, [[0, -1], [1, 0]])
    assert cfg["image_to_stage"] == [[0.0, -1.0], [1.0, 0.0]]
