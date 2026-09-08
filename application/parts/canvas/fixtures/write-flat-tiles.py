"""Write a row of flat overview tiles at distinct stage heights, for a test.

    python write-flat-tiles.py <folder> <tiles> [<z_um>,<z_um>,...]

``<tiles>`` one-plane fields side by side along x, each written through the
run's own writer (``position_store_from_record``) at its own stage z, a
fraction of a micrometre apart -- the way a scanned overview lands once a
focus map has given every field its height. The size the rig's fields are,
1024 pixels square in two channels, so the stores carry the pyramid levels
the rig's do. Each tile is a flat grey of its own level, so a picture can
tell which tiles reached the screen.
Prints the stores' paths, one per line, relative to ``<folder>``.
"""
import sys
from pathlib import Path

import numpy as np
import tifffile

# Run by path from anywhere: the writer lives under the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from application.parts.storage.zarr_positions import position_store_from_record  # noqa: E402

folder = Path(sys.argv[1])
tiles = int(sys.argv[2])
# The heights, given: a run's own, in whatever order the focus map left them.
heights = [float(z) for z in sys.argv[3].split(",")] if len(sys.argv) > 3 else None
side = 1024
channels = 2
pixel_um = 1.0
frame_um = side * pixel_um
ome = (
    '<OME><Image><Pixels PhysicalSizeX="1e-06" PhysicalSizeXUnit="m" '
    'PhysicalSizeY="1e-06" PhysicalSizeYUnit="m" SizeC="1" /></Pixels></Image></OME>'
)
for index in range(tiles):
    raw = folder / "raw" / f"tile{index}"
    raw.mkdir(parents=True, exist_ok=True)
    planes = []
    for c in range(channels):
        path = raw / f"plane_c{c}.ome.tif"
        tifffile.imwrite(path, np.full((side, side), 1000 * (index + 1) + 500 * c, np.uint16), description=ome)
        planes.append({
            "t": 0, "c": c, "z": 0, "path": str(path),
            "x_um": 1000.0 + index * frame_um, "y_um": 2000.0,
            # Every tile at its own height, as a focus map leaves them.
            "z_um": heights[index] if heights else 30.0 + index * 0.7,
        })
    record = {
        "acquisition_type": "overview",
        "position_label": f"K00_M000000_G000000_P{index:06d}_V00",
        "planes": planes,
    }
    store = position_store_from_record(record, folder / "positions")
    print(store.relative_to(folder).as_posix())
