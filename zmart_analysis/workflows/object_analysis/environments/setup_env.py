"""Create conda environments for the object_analysis workflow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "parts"))
from _env_setup import setup_workflow_env  # noqa: E402


WORKFLOW = "object_analysis"
PYTHON_VERSION = "3.12"

STEP_PROFILES = {
    "vision": {
        "description": "Cellpose detection",
        "install_torch": True,
        "pip_packages": [
            "pyyaml",
            "numpy",
            # tifffile exposes a TIFF as a zarr array, which is how OME-TIFF
            # and OME-Zarr reach the same plane selection. Versions before
            # 2026.6.1 import a name zarr 3.3 moved, and fail on the first
            # read with a misleading "zarr 3.3.0 < 3 is not supported".
            "tifffile>=2026.6.1",
            "imagecodecs",
            "pooch",
            "ngio",          # OME-Zarr, NGFF 0.4 and 0.5
            "ome-types",     # OME-XML metadata
            "cellpose",
        ],
        "diagnostics": [
            (
                "TIFF/zarr interop",
                "import tifffile, tifffile.zarr, zarr; "
                "print(f'tifffile {tifffile.__version__} + zarr {zarr.__version__}')",
            ),
            (
                "reads an OME-Zarr position",
                "import tempfile, numpy as np, ngio; "
                "from pathlib import Path; "
                "d = Path(tempfile.mkdtemp()) / 'p.zarr'; "
                "ngio.create_ome_zarr_from_array("
                "    d, np.zeros((1, 1, 2, 8, 8), dtype='uint16'), pixelsize=1.0, "
                "    axes_names=('t','c','z','y','x'), levels=1, overwrite=True); "
                "c = ngio.open_ome_zarr_container(str(d), mode='r'); "
                "print('OK')",
            ),
            ("OME-XML metadata", "import ome_types; print('OK')"),
            ("cellpose", "from cellpose import models; print('OK')"),
        ],
    },
    "classical": {
        "description": "scikit-image classical feature extraction",
        "install_torch": False,
        "pip_packages": [
            "pyyaml",
            "numpy",
            "scikit-image>=0.23",
        ],
        "diagnostics": [
            (
                "scikit-image",
                "from skimage.measure import regionprops_table; "
                "import numpy as np; "
                "m = np.zeros((8, 8), dtype=np.int32); "
                "m[2:4, 2:4] = 1; "
                "regionprops_table(m, properties=('label', 'area')); "
                "print('OK')",
            ),
        ],
    },
}


def _selected_profile() -> dict:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--step", default="vision")
    args, _ = parser.parse_known_args()
    if args.step not in STEP_PROFILES:
        expected = ", ".join(sorted(STEP_PROFILES))
        raise SystemExit(f"Unknown --step {args.step!r}. Expected one of: {expected}")
    return STEP_PROFILES[args.step]


if __name__ == "__main__":
    profile = _selected_profile()
    setup_workflow_env(
        workflow=WORKFLOW,
        pip_packages=profile["pip_packages"],
        diagnostics=profile["diagnostics"],
        python_version=PYTHON_VERSION,
        install_torch=profile["install_torch"],
        default_step="vision",
    )
