"""The mock's kidney section ships with the package and needs no network.

From the review of 10 October, finding 11: the mock read its sample with
``skimage.data.kidney()``, which downloads 25 MB from gitlab.com the first
time. The microscope computer has no network, so the mock that is always
offered could not take a single picture there. The one plane it uses ships
beside the driver now.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from . import kidney


@pytest.fixture()
def no_network(monkeypatch):
    """scikit-image's sample data, as it is on a computer that cannot download it."""

    def unreachable():
        raise ConnectionError("gitlab.com cannot be reached")

    monkeypatch.setitem(sys.modules, "skimage.data", types.SimpleNamespace(kidney=unreachable))
    kidney.the_kidney_plane.cache_clear()
    yield
    kidney.the_kidney_plane.cache_clear()


def test_the_plane_is_read_from_the_package_without_the_network(no_network):
    plane = kidney.the_kidney_plane()
    assert plane.shape == (3, 512, 512)
    assert plane.dtype == np.uint16
    assert plane.max() > 1000, "the section has bright tissue in it"


def test_the_shipped_plane_is_scikit_images_middle_plane():
    data = pytest.importorskip("skimage.data")
    try:
        original = data.kidney()[8]
    except Exception as why:  # noqa: BLE001 -- only comparable where it can be fetched
        pytest.skip(f"scikit-image's kidney cannot be fetched here: {why}")
    kidney.the_kidney_plane.cache_clear()
    assert np.array_equal(kidney.the_kidney_plane(), np.moveaxis(original, -1, 0))


def test_the_mock_takes_a_picture_without_the_network(no_network, monkeypatch):
    from . import driver

    monkeypatch.setattr(driver, "_sample", None)
    sample = driver._the_micrograph(np)
    assert sample.shape == (3, 512, 512)
