"""Opt-in, small real LAS X simulator capture through the unchanged driver.

Pass jobs explicitly; their names never determine geometry or pixel content.
The probe confirms the current XYZ through the driver, but requests no new
location. It does not rewrite jobs, remove vendor exports or edit config.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import zarr

from application.parts.microscope.simulator_pixels import KidneyPixels, SimulatorPixels
from application.parts.storage.zarr_positions import position_store_from_record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--job", action="append", required=True)
    parser.add_argument("--pixels", choices=("kidney", "cells"), default="kidney")
    parser.add_argument("--focus-z-um", type=float, help="Synthetic specimen focus; defaults to initial stage Z")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("use a new output directory to preserve previous evidence")
    from zmart_drivers.leica.stellaris5_y42h93.navigator_expert.commands import commands
    from zmart_drivers.leica.stellaris5_y42h93.navigator_expert.connection.lasx_runtime import (
        load_lasx_api_runtime,
    )
    from zmart_drivers.leica.stellaris5_y42h93.navigator_expert.readers import api_reader
    from zmart_drivers.leica.stellaris5_y42h93.navigator_expert.zmart_adapter import (
        zmart_adapter as driver,
    )

    client = load_lasx_api_runtime().LasxApiClientPyModel
    if not client.Connect("PythonClient"):
        raise RuntimeError("LAS X is unavailable")
    hardware = api_reader.get_hardware_info(client)
    if hardware.get("SystemType") != "SIMULATOR":
        raise RuntimeError("This probe is only for a positively identified LAS X simulator")
    if api_reader.get_scan_status(client) != "eScanIdle":
        raise RuntimeError("The simulator must be idle before this probe")
    jobs = api_reader.get_jobs(client)
    names = {job["Name"] for job in jobs}
    if set(args.job) - names:
        raise ValueError(f"Unknown jobs: {set(args.job) - names}")
    selected = next(job["Name"] for job in jobs if job["IsSelected"])
    args.output.mkdir(parents=True)
    handle = driver.connect({"output_root": str(args.output)})
    client = handle.client
    records = []
    try:
        focus_z = args.focus_z_um
        if focus_z is None and args.pixels == "kidney":
            focus_z = float(driver.get_xyz(handle)["z"]["value"])
        pixels = KidneyPixels(focus_z_um=focus_z) if args.pixels == "kidney" else SimulatorPixels()
        for i, job in enumerate(args.job):
            print(f"Capturing {job!r} through LAS X", flush=True)
            focus = driver.get_xyz(handle)
            position = {key: focus[key]["value"] for key in "xyz"}
            # The real driver stamps captures from its confirmed last destination.
            driver.set_xyz(handle, **position)
            record = driver.acquire(
                handle,
                acquisition_type="verification",
                position_label=f"p{i:03d}",
                options={
                    "job": job,
                    "backlash_correction": False,
                    "cleanup_source": False,
                    "strip_scan_fields": False,
                },
            )
            record["requested_position_um"] = position
            (args.output / f"capture-{i}.json").write_text(
                json.dumps(record, indent=2), encoding="utf-8"
            )
            paths = set(record["images"] + record["vendor_metadata"])
            before = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths}
            store = position_store_from_record(
                record, args.output / "positions", pixel_provider=pixels
            )
            assert all(
                hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
                for path, digest in before.items()
            )
            group = zarr.open_group(str(store), mode="r")
            pixels = np.asarray(group["0"])
            record.update(
                zarr_path=str(store),
                original_sha256=before,
                synthetic_pixels=pixels.recipe,
                pixel_shape=list(pixels.shape),
                pixel_nonzero=int(np.count_nonzero(pixels)),
            )
            records.append(record)
            (args.output / "records.json").write_text(
                json.dumps(records, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    {"job": job, "shape": list(pixels.shape), "nonzero": record["pixel_nonzero"]}
                ),
                flush=True,
            )
    finally:
        commands.select_job(client, selected)


if __name__ == "__main__":
    main()
