"""read_images then score_focus: every metric peaks on the sharp plane, and the peak refines.

The stack is synthetic and deliberately simple: one noisy plane, blurred by
growing amounts either side of it. Blur removes high frequencies, which is
what both metrics are measuring, so both must agree on where the sharp plane
is without either being tuned.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import score_focus
import tifffile
from helpers import fresh_output, load_step

read_images = load_step("focus", "read_images")

SHARP_AT = 4
N_PLANES = 9


def _mitosis_field() -> np.ndarray:
    """A real microscopy field from scikit-image's sample data, as float64.

    The image is downloaded on first use and cached. Without a network the
    test that needs it is skipped, not failed: a missing download says
    nothing about the focus step.
    """
    data = pytest.importorskip("skimage.data")
    try:
        return data.human_mitosis().astype(np.float64)
    except Exception as exc:
        pytest.skip(f"skimage sample image human_mitosis unavailable: {exc}")


def _require_focus_environment() -> None:
    """Skip unless conda and the ZMART--focus--main environment both exist.

    The engine runs the focus pipeline inside that environment, which
    environments/main.yml describes. Without it the test is skipped, not
    failed.
    """
    from zmart_analysis.conda import env_exists, get_conda_info

    try:
        info = get_conda_info()
    except Exception:
        pytest.skip("conda is not installed")
    if not env_exists(info, "ZMART--focus--main"):
        pytest.skip(
            "ZMART--focus--main not found; conda env create -f workflows/non-coders/analysis/focus/environments/main.yml"
        )


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
    tifffile.imwrite(path, np.stack(planes).astype(np.uint16), metadata={"axes": "ZYX"})
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


def _focus(data, **params):
    """The focus pipeline in this process: read_images, then score_focus.

    ``channel``, ``level`` and ``t`` go to the reader, the rest to the scorer.
    """
    reader = {key: params.pop(key) for key in ("channel", "level", "t") if key in params}
    data = read_images.run({"metadata": {"verbose": 0}, **data}, {}, **reader)
    return score_focus.run(data, {}, **params)["score_focus"]


def _scored(stack_path, **params):
    return _focus({"input": {"image_path": str(stack_path)}}, **params)


def _cell_like_stack(path, rng_seed=0):
    """A 9-plane stack of bright blobs on a dark background, sharpest at plane 4.

    The noise stack above suits the gradient and frequency metrics, but pure
    white noise has no neighbour correlation, so Vollath F4 rightly scores it
    as unsharp at every plane. Cells are not noise: this stack is what a
    fluorescence field looks like, so every metric must agree on it.
    """
    from scipy import ndimage

    rng = np.random.default_rng(rng_seed)
    yy, xx = np.mgrid[0:96, 0:96]
    image = np.zeros((96, 96))
    for cy, cx in rng.integers(8, 88, size=(25, 2)):
        image += 3000 * np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * 2.0**2))
    planes = [
        rng.poisson(ndimage.gaussian_filter(image, 0.01 + 1.2 * abs(z - SHARP_AT)) + 50)
        for z in range(N_PLANES)
    ]
    tifffile.imwrite(path, np.stack(planes).astype(np.uint16), metadata={"axes": "ZYX"})
    return path


@pytest.fixture
def cell_stack_path(tmp_path):
    return _cell_like_stack(tmp_path / "cells.tiff")


ALL_METRICS = ("brenner", "dct", "vollath_f4", "intensity")


def test_all_four_metrics_are_scored_on_every_run(stack_path):
    assert set(_scored(stack_path)["metrics"]) == set(ALL_METRICS)


@pytest.mark.parametrize("metric", ALL_METRICS)
def test_every_metric_peaks_on_the_sharp_plane_of_a_cell_like_stack(cell_stack_path, metric):
    result = _scored(cell_stack_path, metric=metric)
    assert result["metric"] == metric
    assert int(np.argmax(result["metrics"][metric]["scores"])) == SHARP_AT
    assert result["peak_index"] == pytest.approx(SHARP_AT, abs=0.3)


def test_vollath_f4_sees_no_focus_in_pure_noise(stack_path):
    """White noise is uncorrelated with its neighbour, so F4 stays near zero
    on the sharp plane and the blurred planes score higher. This is the
    metric working as designed, and why the cell-like stack exists."""
    f4 = _scored(stack_path)["metrics"]["vollath_f4"]["scores"]
    assert int(np.argmax(f4)) != SHARP_AT


def test_intensity_percentile_is_recorded_and_checked(cell_stack_path):
    result = _scored(cell_stack_path, metric="intensity", intensity_percentile=95)
    assert result["settings"]["intensity_percentile"] == 95.0
    with pytest.raises(ValueError, match="intensity_percentile"):
        _scored(cell_stack_path, intensity_percentile=100)


def test_an_unknown_metric_is_refused(stack_path):
    with pytest.raises(ValueError, match="metric must be one of"):
        _scored(stack_path, metric="laplacian")


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
    result = _focus(data)
    assert result["peak_z_um"] == pytest.approx(100.0 + 2.0 * result["peak_index"])
    assert abs(result["peak_z_um"] - 108.0) < 1.0


def _planes_written_one_per_file(tmp_path, blur_at):
    """The stack a ZMART driver writes: one file per plane, flat, in z order."""
    sharp = np.random.default_rng(0).integers(0, 4096, size=(64, 64)).astype(np.float64)
    paths = []
    for z in range(N_PLANES):
        path = tmp_path / f"focussing_aaaaaa_K00_P000000_T000000_C00_Z{z:05d}.ome.tiff"
        tifffile.imwrite(path, _blurred(sharp, blur_at(z)).astype(np.uint16))
        paths.append(str(path))
    return paths


def test_a_stack_written_one_plane_per_file_scores_the_same(tmp_path, stack_path):
    """A driver hands back planes, not a stack, so this step accepts them.

    Every ZMART driver writes one 2-D plane per file -- Leica and the mock
    alike -- so a focus stack arrives as a list of paths in z order, with the
    heights the caller drove to. Nothing is assembled and nothing is copied:
    the planes are read where the acquisition left them.
    """
    paths = _planes_written_one_per_file(tmp_path, lambda z: abs(z - SHARP_AT))
    z_um = [100.0 + 2.0 * z for z in range(N_PLANES)]

    data = {"input": {"image_paths": paths, "z_um": z_um}, "metadata": {"verbose": 0}}
    result = _focus(data)

    assert result["n_planes"] == N_PLANES
    assert result["peak_index"] == pytest.approx(SHARP_AT)
    assert result["peak_z_um"] == pytest.approx(100.0 + 2.0 * SHARP_AT)
    # The same answer the single-file stack gives, because it is the same stack.
    assert result["metrics"]["brenner"]["scores"] == pytest.approx(
        _scored(stack_path)["metrics"]["brenner"]["scores"]
    )


def test_a_plane_list_must_say_where_it_starts_and_ends(tmp_path):
    """One path is not a stack, and no path at all is not an input."""
    paths = _planes_written_one_per_file(tmp_path, lambda z: abs(z - SHARP_AT))

    with pytest.raises(ValueError, match="found no focus stack"):
        _focus({"input": {}})
    with pytest.raises(ValueError, match="one plane cannot be focused"):
        _focus({"input": {"image_paths": paths[:1]}})
    with pytest.raises(ValueError, match="2 heights but the stack has 9 planes"):
        _focus({"input": {"image_paths": paths, "z_um": [0.0, 1.0]}})


def test_a_stack_and_its_heights_must_agree(stack_path):
    data = {
        "input": {"image_path": str(stack_path), "z_um": [0.0, 1.0]},
        "metadata": {"verbose": 0},
    }
    with pytest.raises(ValueError, match="2 heights but the stack has 9 planes"):
        _focus(data)


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


def test_skipping_nothing_lets_the_artefact_win(stack_with_a_bright_edge):
    """Proves the guard is what excluded it, not the shape of the stack."""
    result = _scored(stack_with_a_bright_edge, skip_ends=0)
    assert result["peak_index"] == 0.0
    assert result["considered"] == (0, N_PLANES - 1)


def test_skipping_more_than_the_stack_holds_is_clamped_and_reported(stack_path):
    """A short stack is scored with what it can spare rather than refused,
    and the record says how many planes were really skipped."""
    result = _scored(stack_path, skip_ends=5)
    assert result["settings"]["skip_ends"] == 5
    assert result["settings"]["skip_ends_applied"] == 4
    assert result["considered"] == (4, 4)
    assert result["peak_index"] == pytest.approx(SHARP_AT, abs=0.3)


def test_a_constant_background_offset_changes_no_metrics_verdict(tmp_path):
    """A brighter background is not sharper. Every metric but intensity must
    give the same ranking with 2000 counts added to every pixel, and the
    entropy metric the same score, since it leaves the mean out."""
    dark = _cell_like_stack(tmp_path / "dark.tiff")
    planes = tifffile.imread(dark)
    tifffile.imwrite(
        tmp_path / "bright.tiff", (planes + 2000).astype(np.uint16), metadata={"axes": "ZYX"}
    )
    a = _scored(dark)["metrics"]
    b = _scored(tmp_path / "bright.tiff")["metrics"]
    for name in ("brenner", "dct", "vollath_f4"):
        assert int(np.argmax(a[name]["scores"])) == int(np.argmax(b[name]["scores"])) == SHARP_AT
    assert a["dct"]["scores"] == pytest.approx(b["dct"]["scores"], rel=1e-6)
    assert a["brenner"]["scores"] == pytest.approx(b["brenner"]["scores"], rel=1e-6)


def test_a_true_maximum_on_the_first_allowed_plane_is_found(tmp_path):
    """The sharp plane sits exactly at ``skip_ends``. It is bracketed by
    lower neighbours, so it is a peak and gets a height, even though the
    refined index may drift a little into the skipped planes."""
    stack = _write_stack(tmp_path / "early.tiff", lambda z: abs(z - 2))
    result = _scored(stack, skip_ends=2)
    assert result["found"] is True
    assert result["peak_index"] == pytest.approx(2, abs=0.3)
    assert result["peak_z_um"] is None  # no heights were given, so a plane index only


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
    image = _mitosis_field()
    rng = np.random.default_rng(0)
    z_um = [100.0 + 2.0 * i for i in range(15)]
    planes = [
        rng.poisson(ndimage.gaussian_filter(image, 0.35 * abs(z - true_focus_um))) for z in z_um
    ]
    path = tmp_path / "defocus.tiff"
    tifffile.imwrite(path, np.stack(planes).astype(np.uint16), metadata={"axes": "ZYX"})

    data_in = {"input": {"image_path": str(path), "z_um": z_um}, "metadata": {"verbose": 0}}
    result = _focus(data_in)

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
    excluding it keeps it from being chosen. The spectral entropy is fooled
    too, since white noise has the flattest spectrum of all; no sharpness
    measure tells noise from detail, which is why the ends are skipped for
    every metric alike.
    """
    ndimage = pytest.importorskip("scipy.ndimage")
    image = _mitosis_field()
    rng = np.random.default_rng(0)
    z_um = [100.0 + 2.0 * i for i in range(15)]
    planes = [ndimage.gaussian_filter(image, 0.35 * abs(z - 108.0)) for z in z_um]
    stack = np.stack(planes).astype(np.uint16)
    stack[0] = rng.integers(0, int(image.max()), size=stack.shape[1:])
    path = tmp_path / "artefact.tiff"
    tifffile.imwrite(path, stack, metadata={"axes": "ZYX"})

    data_in = {"input": {"image_path": str(path), "z_um": z_um}, "metadata": {"verbose": 0}}
    result = _focus(data_in)

    brenner = np.asarray(result["metrics"]["brenner"]["scores"])
    dct = np.asarray(result["metrics"]["dct"]["scores"])
    lo, hi = result["considered"]
    assert brenner[0] > 10 * brenner[lo : hi + 1].max()
    assert dct[0] > dct[lo : hi + 1].max()
    assert int(np.argmax(dct[lo : hi + 1])) + lo == int(np.argmax(brenner[lo : hi + 1])) + lo
    assert result["peak_z_um"] == pytest.approx(108.0, abs=0.25)


@pytest.mark.integration
@pytest.mark.conda_env
def test_the_pipeline_runs_through_the_engine(tmp_path, engine_factory, wait_for_results):
    """focus.yaml is registered, submitted and drained the way a caller does.

    Every other test in this file calls ``run`` directly, which would pass
    even if the pipeline file were malformed or the step's result could not
    survive the trip back from a worker subprocess. This is the one that says
    the YAML is usable.
    """
    _require_focus_environment()
    stack = np.stack(
        [
            np.full((32, 32), 100, dtype=np.uint16)
            if z != 4
            else np.random.default_rng(0).integers(0, 4096, size=(32, 32)).astype(np.uint16)
            for z in range(9)
        ]
    )
    path = tmp_path / "stack.tiff"
    tifffile.imwrite(path, stack, metadata={"axes": "ZYX"})
    z_um = [100.0 + 2.0 * z for z in range(9)]

    pipeline = Path(__file__).resolve().parents[1] / "pipelines" / "focus.yaml"
    with engine_factory() as engine:
        engine.register("focus", str(pipeline), fresh_output())
        engine.submit(pipeline="focus", data={"image_path": str(path), "z_um": z_um})
        results = wait_for_results(engine, "focus", 1)
        board = engine.status("focus")

    assert len(results) == 1, board
    found = results[0]["score_focus"]
    assert found["metric"] == "brenner"
    assert found["n_planes"] == 9
    assert tuple(found["considered"]) == (2, 6)
    assert found["peak_z_um"] == pytest.approx(108.0)
    assert set(found["metrics"]) == set(ALL_METRICS)


def test_a_channel_is_taken_from_a_four_axis_stack(tmp_path):
    """The scored channel is the one asked for, not the first one present."""
    rng = np.random.default_rng(1)
    noise = rng.integers(0, 4096, size=(64, 64)).astype(np.float64)
    flat = np.zeros((64, 64))
    stack = np.stack([np.stack([flat, noise]) for _ in range(3)])
    path = tmp_path / "two_channel.tiff"
    tifffile.imwrite(path, stack.astype(np.uint16), metadata={"axes": "ZCYX"})

    data = {"input": {"image_path": str(path)}, "metadata": {"verbose": 0}}
    assert _focus(data, channel=0, skip_ends=0)["metrics"]["brenner"]["scores"][0] == 0.0
    assert _focus(data, channel=1, skip_ends=0)["metrics"]["brenner"]["scores"][0] > 0.0
    with pytest.raises(ValueError, match="Index 2 is out of range for 'c' of size 2"):
        _focus(data, channel=2, skip_ends=0)


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
    stack = np.stack(planes)[None, None]  # t, c, z, y, x
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
    return _focus({"input": {"image_path": str(path)}}, **params)


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
    result = _focus(data)
    assert result["z_um"] == pytest.approx(z_um)


# --- a sweep that never reached the sample ----------------------------------


def test_a_stack_that_never_reached_the_sample_reports_no_height(tmp_path):
    """Still rising at the edge means the sharp plane is outside the sweep.

    A drive begun far from the tissue comes back having seen only its
    approach, and the sharpest plane it holds is simply the last one before
    it stopped. Reporting that as the focus would put a surface through a
    height nobody measured, so it reports none.
    """
    sharp = np.random.default_rng(0).integers(0, 4096, size=(64, 64)).astype(np.float64)
    climbing = tmp_path / "climbing.tiff"
    tifffile.imwrite(
        climbing,
        np.stack([_blurred(sharp, N_PLANES - z) for z in range(N_PLANES)]).astype(np.uint16),
        metadata={"axes": "ZYX"},
    )

    result = _scored(climbing)

    assert result["found"] is False
    assert result["peak_z_um"] is None
    assert result["metrics"]["brenner"]["scores"]  # the curve is still there to draw


def test_a_stack_with_the_sample_in_it_is_found(stack_path):
    """The ordinary case, said out loud, so the one above means something."""
    result = _scored(stack_path)
    assert result["found"] is True
