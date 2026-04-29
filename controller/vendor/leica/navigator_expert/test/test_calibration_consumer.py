import sys
from pathlib import Path

import pytest


def _load_calibration_module():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import navigator_expert.driver.calibration as calibration
    return calibration


def _config():
    return {
        "schema_version": 6,
        "reference_objective_slot": 1,
        "image_to_stage": [[0.0, -1.0], [1.0, 0.0]],
        "objectives": {
            "1": {"is_reference": True},
            "2": {
                "parcentric_xy": {
                    "shift_um":  [-6.0, 13.0],
                    "offset_um": [-7.0, 21.0],
                },
                "parfocal_z": {
                    "shift_um": -3.0,
                    "offset_um": None,
                },
            },
        },
    }


def test_parcentric_shift_returned_as_stored():
    cal = _load_calibration_module()
    assert cal.get_parcentric_shift_um(_config(), 1) == (0.0, 0.0)
    assert cal.get_parcentric_shift_um(_config(), 2) == (-6.0, 13.0)


def test_parcentric_offset_diagnostic():
    cal = _load_calibration_module()
    assert cal.get_parcentric_offset_um(_config(), 1) == (0.0, 0.0)
    assert cal.get_parcentric_offset_um(_config(), 2) == (-7.0, 21.0)


def test_translate_uses_shift_only():
    cal = _load_calibration_module()
    cfg = _config()

    target_xy = cal.translate_stage_xy_between_objectives(
        100.0, 200.0, cfg, from_slot=1, to_slot=2,
    )
    assert target_xy == (94.0, 213.0)  # = (100, 200) + (-6, 13)

    source_xy = cal.translate_stage_xy_between_objectives(
        *target_xy, cfg, from_slot=2, to_slot=1,
    )
    assert source_xy == (100.0, 200.0)


def test_pixel_to_stage_uses_canonical_image_to_stage_matrix():
    cal = _load_calibration_module()
    xy = cal.pixel_to_stage_xy_um(
        60, 40,
        stage_xy_um=(100.0, 200.0),
        pixel_size_um=1.0,
        image_size=100,
        config=_config(),
    )
    assert xy == (110.0, 210.0)


def test_parfocal_shift_returned_as_stored():
    cal = _load_calibration_module()
    assert cal.get_parfocal_shift_um(_config(), 1) == 0.0
    assert cal.get_parfocal_shift_um(_config(), 2) == -3.0


def test_missing_shift_raises_clearly():
    """A target without a measured shift should fail loudly, not silently
    return zero — silent zero would let the cookbook target to the wrong
    place after someone forgot the --measure-xy flag."""
    cal = _load_calibration_module()
    cfg = _config()
    cfg["objectives"]["2"]["parcentric_xy"] = {
        "shift_um": None,
        "offset_um": [-7.0, 21.0],
    }
    with pytest.raises(ValueError, match="shift_um"):
        cal.get_parcentric_shift_um(cfg, 2)
