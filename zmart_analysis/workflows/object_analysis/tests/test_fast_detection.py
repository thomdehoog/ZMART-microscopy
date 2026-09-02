"""The fast detector: QuPath's watershed, held to a field whose nuclei are known.

Cellpose is the accurate way and a minute a field; this is the way that
answers in a second. The test lays nuclei down itself -- bright discs of a
known size on a sloped, noisy background, some touching -- so the count it
expects is not a guess, and checks that the two methods are told apart by
the segmentation's own identity.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("skimage")
pytest.importorskip("scipy")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "steps"))
from detect_objects import (  # noqa: E402
    segmentation_params,
    segmentation_params_hash,
    watershed_masks,
)


def a_field(*, side=512, radius=9, spacing=48, seed=0):
    """Nuclei on a grid, each nudged off it, over a background that slopes
    across the field and carries noise: what a DAPI plane is like, minus the
    biology. Returns the plane and how many nuclei were put down."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:side, 0:side].astype(np.float32)
    plane = 300.0 + 200.0 * xx / side + rng.normal(0.0, 40.0, (side, side)).astype(np.float32)
    count = 0
    for cy in range(spacing, side - spacing, spacing):
        for cx in range(spacing, side - spacing, spacing):
            y = cy + rng.integers(-6, 7)
            x = cx + rng.integers(-6, 7)
            plane += 1500.0 * np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / (2 * (radius * 0.75) ** 2))
            count += 1
    return np.clip(plane, 0, 65535).astype(np.uint16), count


def test_finds_the_nuclei_that_were_laid_down():
    plane, laid = a_field()
    masks, used = watershed_masks(plane, diameter_px=2 * 9, threshold=100.0)
    found = int(masks.max())
    assert abs(found - laid) <= laid * 0.1, (found, laid)
    # Every object is a nucleus-sized thing, not a fragment or a clump.
    areas = np.bincount(masks.ravel())[1:]
    disc = np.pi * 9 ** 2
    assert areas.min() > disc / 8 and areas.max() < disc * 5
    assert used["threshold"] == 100.0 and used["background_radius_px"] == 18


def test_a_threshold_above_the_nuclei_finds_nothing():
    plane, _ = a_field()
    masks, _ = watershed_masks(plane, diameter_px=18, threshold=5000.0)
    assert int(masks.max()) == 0


def test_the_two_methods_have_different_identities():
    given = {"diameter": 30, "channels": [0]}
    accurate = segmentation_params(given, {"method": "accurate"})
    fast = segmentation_params(given, {"method": "fast", "threshold": 100})
    assert accurate["method"] == "accurate" and fast["method"] == "fast"
    assert fast["threshold"] == 100.0
    assert segmentation_params_hash(accurate) != segmentation_params_hash(fast)
    # The default, when the pipeline says nothing, is the accurate one.
    assert segmentation_params(given, {})["method"] == "accurate"
