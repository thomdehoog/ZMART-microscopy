"""Create the conda environment the target acquisition analysis runs in.

One, ``classical``: read_images, segment_watershed, measure_objects and
build_object_table, at the versions in ``classical.txt``. The check at the end
runs the steps on a small image::

    python setup_env.py --step classical
"""

from __future__ import annotations

from pathlib import Path

from zmart_analysis.environments import setup_workflow_env

WORKFLOW = "target_acquisition_for_coders"
PYTHON_VERSION = "3.12"

#: Four bright blobs on a dark field, the picture every check segments.
BLOBS = (
    "; ".join(
        [
            "import sys, tempfile, numpy as np, tifffile",
            "from pathlib import Path",
            "sys.path.insert(0, r'__STEPS__')",
            "yy, xx = np.mgrid[0:96, 0:96]",
            "plane = sum(1500.0 * np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / 72.0)"
            " for y, x in [(24, 24), (24, 72), (72, 24), (72, 72)]).astype('uint16')",
            "given = dict(image_path='blobs.tif', tile_id=['T', 0, 0], tile_stage_xy_um=[0.0, 0.0],"
            " source_pixel_size_um=[1.0, 1.0], image_to_stage=[[1, 0], [0, 1]])",
        ]
    )
    + "; "
)

#: The blobs written as a TIFF and read by read_images, as a pipeline does.
BLOBS_READ = (
    BLOBS
    + "; ".join(
        [
            "path = Path(tempfile.mkdtemp()) / 'blobs.tif'",
            "tifffile.imwrite(path, plane)",
            "given['image_path'] = str(path)",
            "import read_images",
            "data = read_images.run(dict(input=given, metadata=dict(verbose=0)), dict())",
        ]
    )
    + "; "
)

#: The blobs handed on as read_images hands them on, for an environment
#: without the image readers.
BLOBS_HANDED_ON = BLOBS + (
    "data = dict(input=given, metadata=dict(verbose=0), read_images=dict(image=plane,"
    " extra_channels=[], channels=None, z_selection='mid', image_size_px=[96, 96], sha256='')); "
)

STEP_PROFILES = {
    "classical": {
        "description": "reading the image, the watershed, the features and the table",
        "install_torch": False,
        "pip_packages": [
            "pyyaml",
            "numpy",
            "scikit-image>=0.23",
            "tifffile>=2026.6.1",
            "imagecodecs",
            "ngio",  # OME-Zarr, NGFF 0.4 and 0.5
            "ome-types",  # OME-XML metadata
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
            (
                "the fast detector's watershed",
                "from skimage import filters, measure, morphology, segmentation; "
                "from scipy import ndimage; print('OK')",
            ),
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
            (
                "watershed steps, four blobs",
                BLOBS_READ + "import segment_watershed, measure_objects, build_object_table; "
                "data = segment_watershed.run(data, dict(), diameter=12, threshold=100); "
                "data = measure_objects.run(data, dict(), extras=['all']); "
                "table = build_object_table.run(data, dict())['object_analysis']; "
                "n = table['objects']['n_objects']; "
                "print(('OK ' if n == 4 else 'FAIL ') + str(n) + ' objects')",
            ),
        ],
    },
}


if __name__ == "__main__":
    setup_workflow_env(
        workflow=WORKFLOW,
        pip_packages=STEP_PROFILES["classical"]["pip_packages"],
        diagnostics=STEP_PROFILES["classical"]["diagnostics"],
        python_version=PYTHON_VERSION,
        install_torch=False,
        steps_dir=Path(__file__).resolve().parents[1] / "steps",
        locks_dir=Path(__file__).resolve().parent,
        default_step="classical",
    )
