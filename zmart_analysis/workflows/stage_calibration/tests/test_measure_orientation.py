"""measure_orientation: every one of the eight layouts is recovered, and so is the pixel size.

The scene is synthetic and deliberately rich in structure: smoothed noise,
which has edges in every direction and repeats nowhere. Three windows are cut
from it the way a stage would present them -- at home, and after moving a
known distance along +X and along +Y -- and each window is then recorded the
way a camera turned by a given orientation would record it. The step has to
say which orientation that was, from the pictures alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.ndimage import gaussian_filter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "steps"))
from measure_orientation import (  # noqa: E402
    STAGE_FROM_ORIENTATION, orientation_document, reorient, run, unorient,
)

PIXEL_UM = 2.5
MOVE_UM = 60.0
WINDOW = 160


@pytest.fixture(scope="module")
def scene() -> np.ndarray:
    noise = np.random.default_rng(7).random((900, 900))
    return gaussian_filter(noise, 2.0) * 4000.0


def _window(scene, x_um: float, y_um: float) -> np.ndarray:
    """What an aligned camera sees with the stage at (x, y): features move
    toward lower columns as the stage moves +X, and toward lower rows as it
    moves +Y."""
    col = 400 + int(round(x_um / PIXEL_UM))
    row = 400 + int(round(y_um / PIXEL_UM))
    return scene[row:row + WINDOW, col:col + WINDOW]


def _three_raw(scene, rotation_deg: int, reflection: bool):
    home = _window(scene, 0, 0)
    plus_x = _window(scene, MOVE_UM, 0)
    plus_y = _window(scene, 0, MOVE_UM)
    return [unorient(w, rotation_deg, reflection) for w in (home, plus_x, plus_y)]


def _measured(raw):
    data = {
        "input": {"home": raw[0], "plus_x": raw[1], "plus_y": raw[2], "stage_move_um": MOVE_UM},
        "metadata": {"verbose": 0},
    }
    return run(data, {})["measure_orientation"]


@pytest.mark.parametrize("rotation_deg,reflection", sorted(STAGE_FROM_ORIENTATION))
def test_every_layout_is_recovered(scene, rotation_deg, reflection):
    out = _measured(_three_raw(scene, rotation_deg, reflection))
    assert out["accepted"], out["why"]
    assert out["orientation"]["rotation_deg"] == rotation_deg
    assert out["orientation"]["reflection"] is reflection
    assert out["orientation"] == orientation_document(rotation_deg, reflection)
    assert out["residual"] < 0.05


@pytest.mark.parametrize("rotation_deg,reflection", sorted(STAGE_FROM_ORIENTATION))
def test_the_pixel_size_comes_with_it(scene, rotation_deg, reflection):
    out = _measured(_three_raw(scene, rotation_deg, reflection))
    assert out["pixel_um"]["mean"] == pytest.approx(PIXEL_UM, rel=0.02)
    assert out["pixel_um"]["x"] == pytest.approx(PIXEL_UM, rel=0.02)
    assert out["pixel_um"]["y"] == pytest.approx(PIXEL_UM, rel=0.02)


def test_the_correction_it_names_lines_the_picture_up(scene):
    """The document is only worth adopting if applying it undoes the camera."""
    aligned = _window(scene, 0, 0)
    for (rotation_deg, reflection) in STAGE_FROM_ORIENTATION:
        raw = unorient(aligned, rotation_deg, reflection)
        out = _measured(_three_raw(scene, rotation_deg, reflection))
        doc = out["orientation"]
        assert np.array_equal(reorient(raw, doc["rotation_deg"], doc["reflection"]), aligned)


def test_a_rig_turned_by_part_of_a_turn_is_refused(scene):
    """A camera mounted 25 degrees off sees every move along a slanted line.
    The windows are cut large, turned, and cropped back to size so the turned
    corners fall outside the picture and cannot register with each other."""
    from scipy.ndimage import rotate

    def slanted(x_um, y_um):
        col = 400 + int(round(x_um / PIXEL_UM))
        row = 400 + int(round(y_um / PIXEL_UM))
        big = scene[row - WINDOW // 2:row + WINDOW + WINDOW // 2,
                    col - WINDOW // 2:col + WINDOW + WINDOW // 2]
        # Turning by interpolation leaves a faint lattice fixed to the output
        # pixels, identical in every picture; a real camera has no such
        # thing, and left in it would register with itself at zero shift.
        turned = gaussian_filter(rotate(big, 25.0, reshape=False, order=3), 1.0)
        return turned[WINDOW // 2:WINDOW // 2 + WINDOW, WINDOW // 2:WINDOW // 2 + WINDOW]

    out = _measured([slanted(0, 0), slanted(MOVE_UM, 0), slanted(0, MOVE_UM)])
    assert out["accepted"] is False
    assert "quarter-turn" in out["why"]


def test_a_field_that_did_not_move_is_a_loud_error(scene):
    home = _window(scene, 0, 0)
    with pytest.raises(ValueError, match="did not move"):
        _measured([home, home, home])


def test_the_document_says_what_each_stage_axis_comes_from():
    assert orientation_document(0, False)["sign_convention"] == {
        "stage_x_from_image": "+X", "stage_y_from_image": "+Y"}
    assert orientation_document(90, False)["sign_convention"] == {
        "stage_x_from_image": "-Y", "stage_y_from_image": "+X"}
    assert orientation_document(0, True)["sign_convention"] == {
        "stage_x_from_image": "-X", "stage_y_from_image": "+Y"}


def test_the_diagnostic_picture_is_written(scene, tmp_path):
    import sys
    from measure_orientation import write_diagnostic

    raw = _three_raw(scene, 90, False)
    out = _measured(raw)
    path = write_diagnostic(raw[0], raw[1], raw[2], out, tmp_path / "orientation.png")
    if path is None:
        pytest.skip("matplotlib not installed")
    assert (tmp_path / "orientation.png").stat().st_size > 10_000
