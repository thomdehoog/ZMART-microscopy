"""Child script for crash-recovery integration test.

Runs start_run + multiple acquire_and_save calls, with a slow sleep
between each so the parent process can kill it mid-run. Mocks LAS X
primitives so no microscope is needed.

Invoked by ``test_acquisition_crash_recovery.py`` via subprocess.Popen.
Arguments: <output_root> <count> <sleep_between_s>
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np


def _setup_sys_path() -> None:
    # The test launches us from arbitrary cwd. Resolve repo paths from this
    # file's location: navigator_expert/test/_crash_recovery_child.py
    here = Path(__file__).resolve()
    repo_root = here.parents[5]           # .../smart-microscopy
    vendor = here.parents[3]               # .../controller/vendor
    leica = here.parents[2]                # .../controller/vendor/leica
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(vendor))
    sys.path.insert(0, str(leica))


def main() -> None:
    _setup_sys_path()

    media_path = Path(sys.argv[1])
    count = int(sys.argv[2])
    sleep_s = float(sys.argv[3])

    media_path.mkdir(parents=True, exist_ok=True)
    experiment_dir = media_path / "experiment--crash-test"
    metadata_dir = experiment_dir / "metadata"
    experiment_dir.mkdir(exist_ok=True)
    metadata_dir.mkdir(exist_ok=True)

    image_name = "image--L0000--J08--E00--X00--Y00--T0000--Z00--C00.ome.tif"
    xml_name = "image--L0000--J08--E00--T0000.ome.xml"
    image_path = experiment_dir / image_name
    xml_path = metadata_dir / xml_name
    image_path.write_bytes(b"fake_tiff" * 200)
    xml_path.write_bytes(b"<xml/>")

    from shared.output_layout import Naming  # noqa: E402
    import navigator_expert.driver as drv  # noqa: E402
    from navigator_expert.driver.acquisition import save as acquisition  # noqa: E402

    fake_image = np.ones((8, 8), dtype=np.uint8)

    with patch.object(
        acquisition._readers, "get_lasx_settings",
        return_value={"export": {"media_path": str(media_path)}},
    ), patch.object(
        acquisition._fc, "read_relative_path", return_value="",
    ), patch.object(
        acquisition._acquire, "acquire_frame",
        return_value=(fake_image, image_path),
    ), patch.object(
        acquisition._ome, "check_ome_tiff",
        return_value={"path": "x", "corrupted": False, "violations": [], "error": None},
    ), patch.object(
        acquisition._ome, "check_ome_xml_file",
        return_value={"path": "x", "corrupted": False, "violations": [], "error": None},
    ):
        run = drv.start_run(client=None, experiment="crash-exp")

        # Write a beacon so parent knows the run dir to look at.
        beacon = media_path / "run_dir.txt"
        beacon.write_text(str(run.layout.run_dir))

        for i in range(count):
            naming = Naming(
                acquisition_type="overview-scan",
                hash6=run.layout.hash6, p=i,
            )
            drv.acquire_and_save(
                client=None, run=run, job="HiRes", naming=naming,
            )
            sys.stdout.write(f"acq {i} done\n")
            sys.stdout.flush()
            time.sleep(sleep_s)


if __name__ == "__main__":
    main()
