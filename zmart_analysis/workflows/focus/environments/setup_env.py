"""Create the conda environment for the focus workflow.

One environment, ``SMART--focus--main``. Scoring sharpness needs numpy, a DCT
from scipy, and the readers -- no cellpose, no torch, no GPU. Keeping it out
of the vision environment means a focus run costs a small environment rather
than a deep-learning one.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "parts"))
from _env_setup import setup_workflow_env  # noqa: E402


WORKFLOW = "focus"
PYTHON_VERSION = "3.12"

PIP_PACKAGES = [
    "pyyaml",
    "numpy",
    "scipy",         # scipy.fft.dctn, the entropy metric's transform
    # Before 2026.6.1 tifffile imports a name zarr 3.3 moved, and the first
    # read fails with a misleading "zarr 3.3.0 < 3 is not supported".
    "tifffile>=2026.6.1",
    "imagecodecs",
    "ngio",          # OME-Zarr, NGFF 0.4 and 0.5
    "ome-types",     # OME-XML metadata
]

#: ``__STEPS__`` is replaced with this workflow's steps directory before the
#: check runs. A placeholder rather than a format field, because these are
#: Python one-liners and braces are theirs.
DIAGNOSTICS = [
    (
        "DCT transform",
        "import numpy as np; from scipy.fft import dctn; "
        "print('OK' if dctn(np.zeros((8, 8)), norm='ortho').shape == (8, 8) else 'FAIL')",
    ),
    (
        "TIFF/zarr interop",
        "import tifffile, tifffile.zarr, zarr; "
        "print(tifffile.__version__ + ' + zarr ' + zarr.__version__)",
    ),
    (
        "scores a z-stack in an OME-Zarr position",
        "import sys, tempfile, numpy as np, ngio; "
        "from pathlib import Path; "
        "d = Path(tempfile.mkdtemp()) / 'p.zarr'; "
        "a = np.zeros((1, 1, 5, 32, 32), dtype='uint16'); "
        "a[0, 0, 2] = np.random.default_rng(0).integers(0, 4096, size=(32, 32)); "
        "ngio.create_ome_zarr_from_array(d, a, pixelsize=1.0, z_spacing=1.0, "
        "axes_names=('t','c','z','y','x'), levels=1, overwrite=True); "
        "sys.path.insert(0, r'__STEPS__'); "
        "from score_focus import run; "
        "payload = dict(input=dict(image_path=str(d)), metadata=dict(verbose=0)); "
        "peak = run(payload, dict(), skip_ends=0)['score_focus']['peak_index']; "
        "print('OK' if abs(peak - 2) < 0.5 else 'FAIL peak=' + str(peak))",
    ),
]


if __name__ == "__main__":
    steps = str(Path(__file__).resolve().parents[1] / "steps")
    setup_workflow_env(
        workflow=WORKFLOW,
        pip_packages=PIP_PACKAGES,
        diagnostics=[
            (label, code.replace("__STEPS__", steps)) for label, code in DIAGNOSTICS
        ],
        python_version=PYTHON_VERSION,
        install_torch=False,
        default_step="main",
    )
