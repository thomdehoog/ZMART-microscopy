"""The brightness measurement must describe what is really there, per channel.

Two faults are guarded here. Both produced a picture that looked broken to an
operator while every part of the viewer reported itself perfectly content, which
is why they are worth a test that looks at the numbers rather than at whether the
code ran.

**A run still going was measured as pure black.** A writer produces the smallest,
whole-field copy of an image *last*, so for the whole of a run that copy is not
there yet. Asking zarr for a piece that was never written does not raise an
error — it hands back the fill value, zero — so measuring that copy gave a
flawless picture of nothing: a window of nought to one, a histogram of a single
bar, and a `BLACK 0` / `WHITE 1` readout that an `Auto` button would restore. The
answer was then remembered for the rest of the session, so it did not even come
right when the run finished.

**Every channel of a multi-channel store shared one window.** Brightness was
measured for the store as a whole, so a store whose first channel peaks around
1200 and whose second peaks around 39800 handed both channels a window spanning
the pair. The faint channel's entire useful range then sat in the bottom
hundredth of its slider — the precise state the slider was built to prevent.

Each test below also checks that it *could* have failed, by measuring the thing
the old code measured and showing that it gives the wrong answer. A test that
cannot fail is worse than no test, because it is quietly reassuring.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
import zarr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import contrast  # noqa: E402

# The two channels are deliberately far apart, in the way a real Stellaris
# acquisition is: a bright structural marker and a faint one that matters just as
# much. Sharing one window between them is invisible while both draw saturated
# and obvious the moment the shader is correct.
FAINT_PEAK = 1200
BRIGHT_PEAK = 39800


def _write_two_channel_store(path: Path, *, levels: int = 3) -> Path:
    """A small OME-Zarr store with one faint channel and one bright one."""
    shape = (2, 8, 256, 256)
    rng = np.random.default_rng(7)
    full = np.zeros(shape, dtype=np.uint16)
    # A little background everywhere and a bright patch in the middle, so each
    # channel has a real distribution rather than a single value.
    for channel, peak in enumerate((FAINT_PEAK, BRIGHT_PEAK)):
        background = rng.integers(0, max(peak // 20, 2), size=shape[1:], dtype=np.uint16)
        full[channel] = background
        full[channel][:, 96:160, 96:160] = peak

    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    datasets = []
    data = full
    for level in range(levels):
        array = group.create_array(
            str(level),
            shape=data.shape,
            chunks=(1, 2, 64, 64),
            dtype="uint16",
            chunk_key_encoding={"name": "v2", "separator": "/"},
        )
        array[...] = data
        datasets.append(
            {
                "path": str(level),
                "coordinateTransformations": [
                    {"type": "scale", "scale": [1.0, 1.0, 2.0**level, 2.0**level]}
                ],
            }
        )
        data = data[:, :, ::2, ::2]

    (path / ".zattrs").write_text(
        json.dumps(
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [
                            {"name": "c", "type": "channel"},
                            {"name": "z", "type": "space", "unit": "micrometer"},
                            {"name": "y", "type": "space", "unit": "micrometer"},
                            {"name": "x", "type": "space", "unit": "micrometer"},
                        ],
                        "datasets": datasets,
                    }
                ],
                "omero": {
                    "channels": [
                        {"label": "faint", "color": "00FF00"},
                        {"label": "bright", "color": "FF0000"},
                    ]
                },
            }
        )
    )
    return path


def _unwrite_the_smallest_copy(store: Path) -> str:
    """Leave the smallest copy declared but empty, as a run in progress does.

    Returns the level that was emptied, so a test can put it back.
    """
    attrs = json.loads((store / ".zattrs").read_text())
    level = attrs["multiscales"][0]["datasets"][-1]["path"]
    for entry in (store / level).iterdir():
        if entry.name != ".zarray":
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    return level


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return _write_two_channel_store(tmp_path / "run.ome.zarr")


# --------------------------------------------------------------------------
# A run that is still being written


def test_a_run_still_writing_is_not_measured_as_black(store: Path) -> None:
    """The window must come from pixels that exist, not from unwritten ones."""
    _unwrite_the_smallest_copy(store)

    found = contrast.measure(store, channel=1)
    low, high = found["window"]

    assert (low, high) != (0.0, 1.0), (
        "the window collapsed to (0, 1), which is what reading an unwritten copy "
        "of the image gives"
    )
    # The bright channel's signal has to be inside the window it is shown with.
    assert high > BRIGHT_PEAK / 2, f"window {(low, high)} does not reach the signal"
    assert found["histogram"] is not None
    assert sum(found["histogram"]["counts"]) > 0


def test_the_old_way_of_measuring_really_did_give_black(store: Path) -> None:
    """Proof that the test above can fail — the fault is reproduced here.

    This measures exactly what the previous code measured: the smallest copy of
    the image and nothing else. If this ever stops giving a one-count window,
    the test above has stopped being a guard against anything.
    """
    level = _unwrite_the_smallest_copy(store)

    smallest = zarr.open_group(str(store), mode="r")[level]
    values = np.asarray(smallest[...], dtype=np.float64).ravel()
    low, high = contrast._window(values, volumetric=False)

    assert (low, high) == (0.0, 1.0), (
        "reading the unwritten copy no longer gives a black window, so the "
        "fault this test guards has changed shape and the guard needs rewriting"
    )


def test_a_measurement_taken_mid_run_is_marked_to_be_taken_again(store: Path) -> None:
    """It is honest now and better later, and the viewer must know the difference."""
    _unwrite_the_smallest_copy(store)
    assert contrast.measure(store, channel=1)["settled"] is False
    assert contrast.coarsest_level_is_written(store) is False


def test_a_finished_run_is_measured_once_and_settles(store: Path) -> None:
    assert contrast.coarsest_level_is_written(store) is True
    assert contrast.measure(store, channel=1)["settled"] is True


def test_a_store_with_nothing_written_at_all_says_so(tmp_path: Path) -> None:
    """Declared and empty is not the same as dark, and must not be remembered."""
    store = _write_two_channel_store(tmp_path / "empty.ome.zarr")
    attrs = json.loads((store / ".zattrs").read_text())
    for dataset in attrs["multiscales"][0]["datasets"]:
        for entry in (store / dataset["path"]).iterdir():
            if entry.name != ".zarray":
                shutil.rmtree(entry) if entry.is_dir() else entry.unlink()

    found = contrast.measure(store, channel=0)
    assert found["settled"] is False
    assert found["histogram"] is None


# --------------------------------------------------------------------------
# Several channels in one store


def test_each_channel_is_measured_on_its_own(store: Path) -> None:
    faint = contrast.measure(store, channel=0)["window"]
    bright = contrast.measure(store, channel=1)["window"]

    assert faint != bright, "both channels were given the same window"
    # Each window has to sit around its own channel's signal. The faint channel's
    # top must be nowhere near the bright channel's peak, or its slider is
    # useless again.
    assert faint[1] < BRIGHT_PEAK / 4, f"the faint channel was given {faint}"
    assert bright[1] > BRIGHT_PEAK / 2, f"the bright channel was given {bright}"


def test_measuring_the_store_as_a_whole_really_did_flatten_the_faint_channel(
    store: Path,
) -> None:
    """Proof that the test above can fail.

    Measured without naming a channel — which is what the previous code did — the
    window is the mixture's, and the faint channel's whole range disappears into
    the bottom of it.
    """
    together = contrast.measure(store)["window"]
    faint = contrast.measure(store, channel=0)["window"]

    assert together[1] > BRIGHT_PEAK / 2, (
        "the shared window no longer stretches to the bright channel, so this "
        "no longer reproduces the fault"
    )
    where_the_faint_channel_ends = (faint[1] - together[0]) / (together[1] - together[0])
    assert where_the_faint_channel_ends < 0.1, (
        "the faint channel used to occupy under a tenth of the shared window; "
        f"it now occupies {where_the_faint_channel_ends:.2f}"
    )


def test_each_channel_gets_its_own_histogram(store: Path) -> None:
    faint = contrast.measure(store, channel=0)["histogram"]
    bright = contrast.measure(store, channel=1)["histogram"]
    assert faint["counts"] != bright["counts"]
    assert faint["high"] < bright["high"]


def test_a_declared_window_is_read_per_channel(tmp_path: Path) -> None:
    """A window the store declares for one channel must not be given to another."""
    store = _write_two_channel_store(tmp_path / "declared.ome.zarr")
    attrs = json.loads((store / ".zattrs").read_text())
    attrs["omero"]["channels"][1]["window"] = {"start": 100, "end": 200}
    (store / ".zattrs").write_text(json.dumps(attrs))

    assert contrast.measure(store, channel=1)["window"] == (100.0, 200.0)
    # Channel 0 declares nothing, so it is measured rather than handed its
    # neighbour's declaration.
    assert contrast.measure(store, channel=0)["window"] != (100.0, 200.0)


def test_a_store_without_a_channel_axis_is_unaffected(tmp_path: Path) -> None:
    """The mesoSPIM shape — one channel per file — must measure as it always did."""
    store = tmp_path / "single.ome.zarr"
    data = np.full((4, 64, 64), 500, dtype=np.uint16)
    data[:, 16:48, 16:48] = 5000
    group = zarr.open_group(str(store), mode="w", zarr_format=2)
    array = group.create_array(
        "0", shape=data.shape, chunks=(1, 32, 32), dtype="uint16",
        chunk_key_encoding={"name": "v2", "separator": "/"},
    )
    array[...] = data
    (store / ".zattrs").write_text(
        json.dumps(
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [
                            {"name": "z", "type": "space"},
                            {"name": "y", "type": "space"},
                            {"name": "x", "type": "space"},
                        ],
                        "datasets": [{"path": "0"}],
                    }
                ]
            }
        )
    )

    found = contrast.measure(store)
    assert found["window"][1] > 1000
    assert found["settled"] is True
    # Asking for a channel of a store that has none is harmless: there is one
    # channel and it is the whole image.
    assert contrast.measure(store, channel=0)["window"] == found["window"]
