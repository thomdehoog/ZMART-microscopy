import importlib.util
from pathlib import Path

import numpy as np


def _load_registration():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "calibration"
        / "lib"
        / "registration.py"
    )
    spec = importlib.util.spec_from_file_location(
        "calibration_registration_for_test", module_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _blob_image(seed=4, size=160):
    rng = np.random.default_rng(seed)
    image = np.zeros((size, size), dtype=np.float32)
    yy, xx = np.mgrid[:size, :size]
    for y, x, amp in zip(
        rng.integers(20, size - 20, 60),
        rng.integers(20, size - 20, 60),
        rng.uniform(80, 250, 60),
    ):
        image += amp * np.exp(-(((yy - y) ** 2 + (xx - x) ** 2) / (2 * 2.2 ** 2)))
    return image


def _shift_image(image, *, dx, dy):
    shifted = np.zeros_like(image)
    src_y0 = max(0, -dy)
    src_y1 = min(image.shape[0], image.shape[0] - dy)
    dst_y0 = max(0, dy)
    dst_y1 = min(image.shape[0], image.shape[0] + dy)
    src_x0 = max(0, -dx)
    src_x1 = min(image.shape[1], image.shape[1] - dx)
    dst_x0 = max(0, dx)
    dst_x1 = min(image.shape[1], image.shape[1] + dx)
    shifted[dst_y0:dst_y1, dst_x0:dst_x1] = image[src_y0:src_y1, src_x0:src_x1]
    return shifted


def test_register_voting_uses_sign_phase_shift_convention():
    registration = _load_registration()
    ref = _blob_image()
    expected_dx, expected_dy = 7, -5
    tgt = _shift_image(ref, dx=expected_dx, dy=expected_dy)

    vote = registration.register_voting(
        ref, tgt, pixel_um=1.0, tolerance_um=2.0, min_agree=2,
    )

    assert vote["trusted"]
    assert vote["confidence"] == 4
    assert abs(vote["dx_um"] - expected_dx) < 0.25
    assert abs(vote["dy_um"] - expected_dy) < 0.25
    for method in vote["per_method"].values():
        for key in ("dx_um", "dy_um", "quality"):
            value = method.get(key)
            assert value is None or np.isfinite(value)


def test_each_registration_method_uses_sign_phase_shift_convention():
    registration = _load_registration()
    ref = _blob_image()
    expected_dx, expected_dy = 7, -5
    tgt = _shift_image(ref, dx=expected_dx, dy=expected_dy)

    methods = [
        registration._method_phase,
        registration._method_masked,
        registration._method_cv2_ncc,
        registration._method_orb,
    ]
    for method in methods:
        dx_um, dy_um, _ = method(ref, tgt, 1.0, 30)
        assert abs(dx_um - expected_dx) < 0.5, (method.__name__, dx_um)
        assert abs(dy_um - expected_dy) < 0.5, (method.__name__, dy_um)
