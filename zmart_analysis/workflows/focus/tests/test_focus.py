"""score_focus: both metrics peak on the sharp plane, and the peak refines.

The stack is synthetic and deliberately simple: one noisy plane, blurred by
growing amounts either side of it. Blur removes high frequencies, which is
what both metrics are measuring, so both must agree on where the sharp plane
is without either being tuned.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import tifffile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "steps"))
from score_focus import run  # noqa: E402

SHARP_AT = 4
N_PLANES = 9


def _blurred(image: np.ndarray, radius: int) -> np.ndarray:
    """A cheap separable box blur, so the test needs no scipy.ndimage."""
    out = image.astype(np.float64)
    for _ in range(radius):
        out = (np.roll(out, 1, 0) + out + np.roll(out, -1, 0)) / 3.0
        out = (np.roll(out, 1, 1) + out + np.roll(out, -1, 1)) / 3.0
    return out


def _write_stack(path, blur_at):
    """A 9-plane stack, sharpest at plane 4, blurred by ``blur_at(z)`` either side."""
    sharp = np.random.default_rng(0).integers(0, 4096, size=(64, 64)).astype(np.float64)
    planes = [_blurred(sharp, blur_at(z)) for z in range(N_PLANES)]
    tifffile.imwrite(
        path, np.stack(planes).astype(np.uint16), metadata={"axes": "ZYX"}
    )
    return path


@pytest.fixture
def stack_path(tmp_path):
    """Blur grows evenly either side of the sharp plane."""
    return _write_stack(tmp_path / "stack.tiff", lambda z: abs(z - SHARP_AT))


@pytest.fixture
def lopsided_stack_path(tmp_path):
    """Blur grows twice as fast above the sharp plane as below it."""
    return _write_stack(
        tmp_path / "lopsided.tiff",
        lambda z: (SHARP_AT - z) if z < SHARP_AT else 2 * (z - SHARP_AT),
    )


def _scored(stack_path, **params):
    data = {"input": {"image_path": str(stack_path)}, "metadata": {"verbose": 0}}
    return run(data, {}, **params)["score_focus"]


def test_both_metrics_peak_on_the_sharp_plane(stack_path):
    result = _scored(stack_path)
    assert result["n_planes"] == N_PLANES
    assert int(np.argmax(result["metrics"]["brenner"]["scores"])) == SHARP_AT
    assert int(np.argmax(result["metrics"]["dct"]["scores"])) == SHARP_AT


def test_an_even_peak_refines_onto_the_sharp_plane(stack_path):
    """Neighbours that fall away equally leave the vertex where it started."""
    assert _scored(stack_path)["peak_index"] == pytest.approx(SHARP_AT)


def test_a_lopsided_peak_refines_off_the_plane(lopsided_stack_path):
    """True focus sits nearer the gentler side, and between two planes."""
    peak = _scored(lopsided_stack_path)["peak_index"]
    assert peak != SHARP_AT
    assert SHARP_AT - 0.5 < peak < SHARP_AT


def test_scores_fall_away_from_focus(stack_path):
    brenner = _scored(stack_path)["metrics"]["brenner"]["scores"]
    assert brenner[SHARP_AT] > brenner[SHARP_AT - 2] > brenner[0]
    assert brenner[SHARP_AT] > brenner[SHARP_AT + 2] > brenner[-1]


def test_the_metric_chooses_which_peak_is_reported(stack_path):
    assert _scored(stack_path, metric="dct")["metric"] == "dct"
    with pytest.raises(ValueError, match="metric must be one of"):
        _scored(stack_path, metric="tenengrad")


def test_heights_map_onto_the_refined_peak(stack_path):
    z_um = [100.0 + 2.0 * z for z in range(N_PLANES)]
    data = {
        "input": {"image_path": str(stack_path), "z_um": z_um},
        "metadata": {"verbose": 0},
    }
    result = run(data, {})["score_focus"]
    assert result["peak_z_um"] == pytest.approx(100.0 + 2.0 * result["peak_index"])
    assert abs(result["peak_z_um"] - 108.0) < 1.0


def test_a_stack_and_its_heights_must_agree(stack_path):
    data = {
        "input": {"image_path": str(stack_path), "z_um": [0.0, 1.0]},
        "metadata": {"verbose": 0},
    }
    with pytest.raises(ValueError, match="2 heights but the stack has 9 planes"):
        run(data, {})


@pytest.fixture
def stack_with_a_bright_edge(tmp_path):
    """An artefact on the first plane of the drive.

    High-contrast detail across the whole frame -- the first plane of a stack
    where the stage had not settled or the shutter was still opening. It is
    not in focus on anything; it just has far harder edges than the tissue,
    which is exactly what a sharpness metric rewards.
    """
    path = _write_stack(tmp_path / "artefact.tiff", lambda z: abs(z - SHARP_AT))
    stack = tifffile.imread(path)
    stack[0] = np.random.default_rng(7).integers(0, 65535, size=stack.shape[1:])
    tifffile.imwrite(path, stack, metadata={"axes": "ZYX"})
    return path


def test_an_artefact_at_the_end_cannot_win(stack_with_a_bright_edge):
    result = _scored(stack_with_a_bright_edge)
    brenner = result["metrics"]["brenner"]["scores"]
    assert brenner[0] > brenner[SHARP_AT], "the artefact should out-score real focus"
    assert result["peak_index"] == pytest.approx(SHARP_AT), "yet it must not be chosen"
    assert result["considered"] == (2, N_PLANES - 3)


def test_the_scores_still_report_what_was_set_aside(stack_with_a_bright_edge):
    """Skipped planes are excluded from winning, not from the curve."""
    scores = _scored(stack_with_a_bright_edge)["metrics"]["brenner"]["scores"]
    assert len(scores) == N_PLANES


def test_skipping_nothing_lets_the_artefact_win(stack_with_a_bright_edge):
    """Proves the guard is what excluded it, not the shape of the stack."""
    result = _scored(stack_with_a_bright_edge, skip_ends=0)
    assert result["peak_index"] == 0.0
    assert result["considered"] == (0, N_PLANES - 1)


def test_skipping_more_than_the_stack_holds_is_refused(stack_path):
    with pytest.raises(ValueError, match="leaves no plane to choose from"):
        _scored(stack_path, skip_ends=5)


@pytest.mark.pooch
@pytest.mark.parametrize("true_focus_um", [108.0, 108.5, 108.7, 109.0])
def test_real_pixels_find_focus_between_planes(tmp_path, true_focus_um):
    """On a real field, both metrics land within a fraction of a plane step.

    Synthetic stacks can flatter a metric: noiseless, and sharp exactly on a
    plane. This is a defocus series built from a real microscopy field, with
    shot noise per plane and true focus deliberately off the sampling grid,
    which is the only case where the parabola earns its place.
    """
    ndimage = pytest.importorskip("scipy.ndimage")
    data = pytest.importorskip("skimage.data")

    image = data.human_mitosis().astype(np.float64)
    rng = np.random.default_rng(0)
    z_um = [100.0 + 2.0 * i for i in range(15)]
    planes = [
        rng.poisson(ndimage.gaussian_filter(image, 0.35 * abs(z - true_focus_um)))
        for z in z_um
    ]
    path = tmp_path / "defocus.tiff"
    tifffile.imwrite(
        path, np.stack(planes).astype(np.uint16), metadata={"axes": "ZYX"}
    )

    data_in = {"input": {"image_path": str(path), "z_um": z_um},
               "metadata": {"verbose": 0}}
    result = run(data_in, {})["score_focus"]

    for name in ("brenner", "dct"):
        found = result["metrics"][name]["peak_z_um"]
        assert abs(found - true_focus_um) < 0.25, (
            f"{name} put focus at {found:.2f} um, not {true_focus_um} um"
        )


@pytest.mark.pooch
def test_an_artefact_frame_would_beat_real_focus_on_brenner(tmp_path):
    """Why skip_ends exists, measured rather than asserted.

    An unsettled first plane is not in focus on anything, but its edges are
    harder than tissue. At the same dynamic range as the field it replaces it
    still out-scores true focus on brenner by a wide margin, so nothing but
    excluding it keeps it from being chosen. DCT entropy is not fooled.
    """
    ndimage = pytest.importorskip("scipy.ndimage")
    data = pytest.importorskip("skimage.data")

    image = data.human_mitosis().astype(np.float64)
    rng = np.random.default_rng(0)
    z_um = [100.0 + 2.0 * i for i in range(15)]
    planes = [ndimage.gaussian_filter(image, 0.35 * abs(z - 108.0)) for z in z_um]
    stack = np.stack(planes).astype(np.uint16)
    stack[0] = rng.integers(0, int(image.max()), size=stack.shape[1:])
    path = tmp_path / "artefact.tiff"
    tifffile.imwrite(path, stack, metadata={"axes": "ZYX"})

    data_in = {"input": {"image_path": str(path), "z_um": z_um},
               "metadata": {"verbose": 0}}
    result = run(data_in, {})["score_focus"]

    brenner = np.asarray(result["metrics"]["brenner"]["scores"])
    dct = np.asarray(result["metrics"]["dct"]["scores"])
    lo, hi = result["considered"]
    assert brenner[0] > 10 * brenner[lo:hi + 1].max()
    assert dct[0] < dct[lo:hi + 1].max()
    assert result["peak_z_um"] == pytest.approx(108.0, abs=0.25)


@pytest.mark.integration
def test_the_pipeline_runs_through_the_engine(tmp_path, engine_factory, wait_for_results):
    """focus.yaml is registered, submitted and drained the way a caller does.

    Every other test in this file calls ``run`` directly, which would pass
    even if the pipeline file were malformed or the step's result could not
    survive the trip back from a worker subprocess. This is the one that says
    the YAML is usable.
    """
    stack = np.stack([
        np.full((32, 32), 100, dtype=np.uint16) if z != 4
        else np.random.default_rng(0).integers(0, 4096, size=(32, 32)).astype(np.uint16)
        for z in range(9)
    ])
    path = tmp_path / "stack.tiff"
    tifffile.imwrite(path, stack, metadata={"axes": "ZYX"})
    z_um = [100.0 + 2.0 * z for z in range(9)]

    pipeline = Path(__file__).resolve().parents[1] / "pipelines" / "focus.yaml"
    with engine_factory() as engine:
        engine.register("focus", str(pipeline))
        engine.submit("focus", {"image_path": str(path), "z_um": z_um})
        results = wait_for_results(engine, "focus", 1)

    assert len(results) == 1, engine.status("focus")
    found = results[0]["score_focus"]
    assert found["metric"] == "brenner"
    assert found["n_planes"] == 9
    assert tuple(found["considered"]) == (2, 6)
    assert found["peak_z_um"] == pytest.approx(108.0)
    assert set(found["metrics"]) == {"brenner", "dct"}


def test_a_channel_is_taken_from_a_four_axis_stack(tmp_path):
    """The scored channel is the one asked for, not the first one present."""
    rng = np.random.default_rng(1)
    noise = rng.integers(0, 4096, size=(64, 64)).astype(np.float64)
    flat = np.zeros((64, 64))
    stack = np.stack([np.stack([flat, noise]) for _ in range(3)])
    path = tmp_path / "two_channel.tiff"
    tifffile.imwrite(path, stack.astype(np.uint16), metadata={"axes": "ZCYX"})

    data = {"input": {"image_path": str(path)}, "metadata": {"verbose": 0}}
    assert run(data, {}, channel=0, skip_ends=0)["score_focus"]["metrics"]["brenner"]["scores"][0] == 0.0
    assert run(data, {}, channel=1, skip_ends=0)["score_focus"]["metrics"]["brenner"]["scores"][0] > 0.0
    with pytest.raises(ValueError, match="Index 2 is out of range for 'c' of size 2"):
        run(data, {}, channel=2, skip_ends=0)


# ---------------------------------------------------------------------------
# The same stack, as an OME-Zarr position
# ---------------------------------------------------------------------------

Z_SPACING_UM = 2.0
FIRST_PLANE_UM = 100.0


@pytest.fixture
def zarr_position(tmp_path):
    """A TCZYX position whose sharp plane is at index 4, on two channels.

    Channel 1 is flat, so a run that scores it finds nothing to peak on --
    which is how the channel argument is shown to be doing something.
    """
    ngio = pytest.importorskip("ngio")

    sharp = np.random.default_rng(0).integers(0, 4096, size=(64, 64)).astype(np.float64)
    planes = [_blurred(sharp, abs(z - SHARP_AT)) for z in range(N_PLANES)]
    stack = np.stack(planes)[None, None]                      # t, c, z, y, x
    flat = np.zeros_like(stack)
    array = np.concatenate([stack, flat], axis=1).astype(np.uint16)

    path = tmp_path / "position.zarr"
    ngio.create_ome_zarr_from_array(
        path,
        array,
        pixelsize=0.325,
        z_spacing=Z_SPACING_UM,
        axes_names=("t", "c", "z", "y", "x"),
        channels_meta=["signal", "empty"],
        translation=(0.0, 0.0, FIRST_PLANE_UM, 0.0, 0.0),
        levels=1,
        overwrite=True,
    )
    return path


def _scored_store(path, **params):
    data = {"input": {"image_path": str(path)}, "metadata": {"verbose": 0}}
    return run(data, {}, **params)["score_focus"]


def test_a_zarr_position_focuses_like_a_tiff_stack(zarr_position):
    result = _scored_store(zarr_position)
    assert result["n_planes"] == N_PLANES
    assert int(np.argmax(result["metrics"]["brenner"]["scores"])) == SHARP_AT
    assert int(np.argmax(result["metrics"]["dct"]["scores"])) == SHARP_AT


def test_the_heights_come_from_the_store(zarr_position):
    """No z_um was passed: the position already knows where its planes are."""
    result = _scored_store(zarr_position)
    assert result["z_um"] == pytest.approx(
        [FIRST_PLANE_UM + Z_SPACING_UM * z for z in range(N_PLANES)]
    )
    assert result["peak_z_um"] == pytest.approx(FIRST_PLANE_UM + Z_SPACING_UM * SHARP_AT)
    assert result["settings"]["heights"] == "from the image"


def test_a_named_channel_is_scored(zarr_position):
    """Channel 'empty' is flat, so its curve has nothing to find."""
    signal = _scored_store(zarr_position, channel="signal")
    empty = _scored_store(zarr_position, channel="empty")

    assert max(signal["metrics"]["brenner"]["scores"]) > 0
    assert max(empty["metrics"]["brenner"]["scores"]) == 0
    assert signal["settings"]["channel"] == "signal"


def test_given_heights_still_win_over_the_stores_own(zarr_position):
    z_um = [500.0 + z for z in range(N_PLANES)]
    data = {
        "input": {"image_path": str(zarr_position), "z_um": z_um},
        "metadata": {"verbose": 0},
    }
    result = run(data, {})["score_focus"]
    assert result["z_um"] == pytest.approx(z_um)
    assert result["settings"]["heights"] == "given"
