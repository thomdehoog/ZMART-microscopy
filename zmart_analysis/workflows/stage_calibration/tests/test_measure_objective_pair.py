"""measure_objective_pair: the target lens's offset in x, y and z is read off two views.

Two lenses look at one scene. The target lens has finer pixels, looks a known
distance away from the reference lens, and focuses at a known different
height. The step is handed what each lens recorded and has to give those
three numbers back.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.ndimage import gaussian_filter, zoom

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "steps"))
from measure_objective_pair import run, sharp_height_um  # noqa: E402

REF_UM, TGT_UM = 2.0, 0.5
OFFSET_UM = (-18.0, 11.0)   # where the target lens looks, relative to the reference
REF_FOCUS_UM, TGT_FOCUS_UM = 100.0, 103.5


@pytest.fixture(scope="module")
def scene() -> np.ndarray:
    """The specimen at 0.5 um per pixel, so both lenses can be cut from it."""
    noise = np.random.default_rng(3).random((1200, 1200))
    return gaussian_filter(noise, 3.0) * 4000.0


def _view(scene, lens_um: float, centre_um, window_px: int) -> np.ndarray:
    """What a lens centred on ``centre_um`` records, at its own pixel size."""
    scale = lens_um / 0.5
    half_um = window_px * lens_um / 2.0
    c0 = int(round((600 * 0.5 + centre_um[0] - half_um) / 0.5))
    r0 = int(round((600 * 0.5 + centre_um[1] - half_um) / 0.5))
    span = int(round(window_px * scale))
    cut = scene[r0:r0 + span, c0:c0 + span]
    return zoom(cut, 1.0 / scale, order=1) if scale != 1.0 else cut


def _blurred(image, radius):
    return gaussian_filter(image, radius) if radius > 0 else image


def _stack(image, focus_um, heights):
    return [_blurred(image, 0.8 * abs(z - focus_um)) for z in heights], list(heights)


def test_the_offset_and_the_focus_difference_are_recovered(scene):
    ref = _view(scene, REF_UM, (0.0, 0.0), 128)
    tgt = _view(scene, TGT_UM, OFFSET_UM, 256)
    ref_stack, ref_z = _stack(ref, REF_FOCUS_UM, np.arange(96.0, 105.0, 1.0))
    tgt_stack, tgt_z = _stack(tgt, TGT_FOCUS_UM, np.arange(99.0, 108.0, 1.0))
    data = {"input": {
        "reference": {"image": ref, "pixel_um": REF_UM, "stack": ref_stack, "z_um": ref_z},
        "target": {"image": tgt, "pixel_um": TGT_UM, "stack": tgt_stack, "z_um": tgt_z},
    }, "metadata": {"verbose": 0}}
    out = run(data, {})["measure_objective_pair"]
    assert out["accepted"], out["why"]
    assert out["translation_um"]["x"] == pytest.approx(OFFSET_UM[0], abs=1.0)
    assert out["translation_um"]["y"] == pytest.approx(OFFSET_UM[1], abs=1.0)
    assert out["translation_um"]["z"] == pytest.approx(TGT_FOCUS_UM - REF_FOCUS_UM, abs=0.3)
    assert out["pixel_um"] == {"reference": REF_UM, "target": TGT_UM, "overlay": REF_UM}


def test_without_stacks_only_the_look_is_reported(scene):
    ref = _view(scene, REF_UM, (0.0, 0.0), 128)
    tgt = _view(scene, TGT_UM, OFFSET_UM, 256)
    data = {"input": {
        "reference": {"image": ref, "pixel_um": REF_UM},
        "target": {"image": tgt, "pixel_um": TGT_UM},
    }, "metadata": {"verbose": 0}}
    out = run(data, {})["measure_objective_pair"]
    assert out["translation_um"]["z"] is None
    assert out["focus"] == {"reference": None, "target": None}
    assert out["translation_um"]["x"] == pytest.approx(OFFSET_UM[0], abs=1.0)


def test_the_sharp_height_is_refined_between_planes(scene):
    image = _view(scene, REF_UM, (0.0, 0.0), 96)
    stack, z = _stack(image, 50.4, np.arange(46.0, 55.0, 1.0))
    assert sharp_height_um(stack, z)["peak_z_um"] == pytest.approx(50.4, abs=0.25)


def test_each_cell_draws_its_own_picture(scene, tmp_path):
    from measure_objective_pair import write_focus_diagnostic, write_overlay_diagnostic

    ref = _view(scene, REF_UM, (0.0, 0.0), 128)
    tgt = _view(scene, TGT_UM, OFFSET_UM, 256)
    ref_stack, ref_z = _stack(ref, REF_FOCUS_UM, np.arange(96.0, 105.0, 1.0))
    focus = sharp_height_um(ref_stack, ref_z)
    path = write_focus_diagnostic(ref_stack, focus, tmp_path / "focus.png")
    if path is None:
        pytest.skip("matplotlib not installed")
    assert (tmp_path / "focus.png").stat().st_size > 10_000
    reference = {"image": ref, "pixel_um": REF_UM}
    target = {"image": tgt, "pixel_um": TGT_UM}
    out = run({"input": {"reference": reference, "target": target}, "metadata": {"verbose": 0}}, {})["measure_objective_pair"]
    write_overlay_diagnostic(reference, target, out, tmp_path / "overlay.png")
    assert (tmp_path / "overlay.png").stat().st_size > 10_000


def test_a_peak_on_the_end_of_a_stack_is_not_a_peak(scene):
    """The stack never reached the sharp plane: no height is reported, and
    the answer says to refocus rather than pretending."""
    image = _view(scene, REF_UM, (0.0, 0.0), 96)
    stack, z = _stack(image, 60.0, np.arange(46.0, 55.0, 1.0))   # sharp above the top plane
    f = sharp_height_um(stack, z)
    assert f["bracketed"] is False and f["peak_index"] == len(z) - 1
    ref = _view(scene, REF_UM, (0.0, 0.0), 128); tgt = _view(scene, TGT_UM, OFFSET_UM, 256)
    out = run({"input": {
        "reference": {"image": ref, "pixel_um": REF_UM, "stack": stack, "z_um": z},
        "target": {"image": tgt, "pixel_um": TGT_UM, "stack": stack, "z_um": z},
    }, "metadata": {"verbose": 0}}, {})["measure_objective_pair"]
    assert out["translation_um"]["z"] is None
    assert out["accepted"] is False
    assert "refocus" in out["why"]
