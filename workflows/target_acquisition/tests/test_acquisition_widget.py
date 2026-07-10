"""The acquisition gallery: random pick from the gate, same-scale pairs.

Offline: a stub session hands back synthetic OME-TIFF "acquired" images,
so the pairing/scale math runs against real files without a microscope.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

from types import SimpleNamespace  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
import tifffile  # noqa: E402
from workflow._acquisition_widget import acquire_gallery  # noqa: E402


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


def _write_ome(path, shape, pixel_size_um):
    """A minimal OME-TIFF: enough for read_overview_geometry to work."""
    h, w = shape
    description = (
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        '<Image><Pixels DimensionOrder="XYCZT" Type="uint16" '
        f'SizeX="{w}" SizeY="{h}" SizeC="1" SizeZ="1" SizeT="1" '
        f'PhysicalSizeX="{pixel_size_um}" PhysicalSizeY="{pixel_size_um}"/>'
        "</Image></OME>"
    )
    tifffile.imwrite(path, np.zeros((h, w), dtype=np.uint16), description=description)
    return path


class _StubSession:
    """Records moves; each acquire hands back one pre-written target image."""

    def __init__(self, image_dir, *, target_shape=(40, 40), target_pixel_um=0.25):
        self.image_dir = image_dir
        self.target_shape = target_shape
        self.target_pixel_um = target_pixel_um
        self.moves = []
        self.states = []
        self.acquired = 0

    def set_state(self, state):
        self.states.append(state)

    def set_xyz(self, x, y, z, **_kw):
        self.moves.append((x, y, z))

    def acquire(self, *, acquisition_type, position_label, options=None):
        self.acquired += 1
        path = _write_ome(
            self.image_dir / f"target_{position_label}.ome.tif",
            self.target_shape,
            self.target_pixel_um,
        )
        return {
            "acquisition_type": acquisition_type,
            "position_label": position_label,
            "images": [str(path)],
        }


def _targets(n):
    return [
        {
            "x": float(i),
            "y": 0.0,
            "source": {"naming_p": 0, "centroid_col_row_px": (50.0, 50.0)},
        }
        for i in range(n)
    ]


@pytest.fixture
def overview(tmp_path):
    path = tmp_path / "overview.tif"
    tifffile.imwrite(path, np.arange(100 * 100, dtype=np.uint16).reshape(100, 100))
    return {
        "image_path": path,
        "center_frame_um": (0.0, 0.0),
        "pixel_size_um": 1.0,
        "image_size_px": (100, 100),
        "label": 0,
    }


def test_acquires_a_random_sample_of_the_requested_size(tmp_path, overview):
    session = _StubSession(tmp_path)
    gallery = acquire_gallery(session, _targets(10), [overview], seed=42)
    records = gallery.acquire(3)
    assert len(records) == 3 == len(gallery.picked) == session.acquired
    assert all(p in _targets(10) for p in gallery.picked)
    # The same seed picks the same sample again (reproducible sessions).
    repeat = acquire_gallery(session, _targets(10), [overview], seed=42)
    repeat.acquire(3)
    assert repeat.picked == gallery.picked


def test_asking_for_more_than_the_gate_takes_the_whole_gate(tmp_path, overview):
    session = _StubSession(tmp_path)
    gallery = acquire_gallery(session, _targets(2), [overview])
    gallery.acquire(10)
    assert len(gallery.picked) == 2


def test_gallery_pairs_share_the_same_physical_window(tmp_path, overview):
    session = _StubSession(tmp_path)  # 40 px * 0.25 um = a 10 um FOV
    gallery = acquire_gallery(session, _targets(4), [overview], seed=1)
    gallery.acquire(2)

    assert len(gallery._gallery_axes) == 4  # two panels per acquired target
    for ax_low, ax_high in zip(
        gallery._gallery_axes[0::2], gallery._gallery_axes[1::2], strict=True
    ):
        low = ax_low.get_images()[0]
        high = ax_high.get_images()[0]
        # Both panels span the identical 10x10 um window...
        assert tuple(low.get_extent()) == tuple(high.get_extent()) == (-5.0, 5.0, 5.0, -5.0)
        # ...covered by 10 overview pixels (1 um each) on the left and the
        # full 40 target pixels (0.25 um each) on the right.
        assert np.asarray(low.get_array()).shape == (10, 10)
        assert np.asarray(high.get_array()).shape == (40, 40)


def test_source_can_be_an_explorer_like_object(tmp_path, overview):
    session = _StubSession(tmp_path)
    explorer = SimpleNamespace(gated=_targets(3))
    gallery = acquire_gallery(session, explorer, [overview])
    gallery.acquire(2)
    assert len(gallery.picked) == 2


def test_state_and_focus_reach_the_acquisition(tmp_path, overview):
    session = _StubSession(tmp_path)
    focus = SimpleNamespace(z_at=lambda x, y: 7.5)
    gallery = acquire_gallery(
        session, _targets(3), [overview], state={"changeable": {}}, focus=focus
    )
    gallery.acquire(1)
    assert session.states == [{"changeable": {}}]
    assert session.moves[0][2] == 7.5  # z came from the focus surface


def test_after_acquire_hook_sees_the_records_before_the_gallery(tmp_path, overview):
    session = _StubSession(tmp_path)
    seen = []
    gallery = acquire_gallery(
        session, _targets(3), [overview], after_acquire=lambda recs: seen.append(list(recs))
    )
    gallery.acquire(2)
    assert seen and seen[0] == gallery.records


def test_records_without_images_get_a_placeholder_row(tmp_path, overview):
    class _NoImageSession(_StubSession):
        def acquire(self, **kwargs):
            self.acquired += 1
            return {"position_label": kwargs["position_label"]}

    session = _NoImageSession(tmp_path)
    gallery = acquire_gallery(session, _targets(2), [overview])
    gallery.acquire(1)
    assert len(gallery._gallery_axes) == 2
    assert not gallery._gallery_axes[0].get_images()  # text placeholder, no crash


def test_empty_gate_is_a_clear_error(tmp_path):
    session = _StubSession(tmp_path)
    gallery = acquire_gallery(session, [], [])
    with pytest.raises(RuntimeError, match="gate is empty"):
        gallery.acquire(3)


def test_button_click_failure_lands_on_the_status_text(tmp_path):
    session = _StubSession(tmp_path)
    gallery = acquire_gallery(session, [], [])
    gallery._count_box.set_val("3")
    gallery._on_acquire_clicked(None)
    assert "acquire failed" in gallery._status.get_text()
