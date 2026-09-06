"""Write a small stack timelapse the way a run writes one, for a test.

    python write-a-timelapse.py <folder> <frames> <planes>

One position, ``<planes>`` deep and ``<frames>`` moments long, 256 pixels
square, in the storage the runs use -- so what the page opens here is the
same kind of picture an acquisition leaves behind. Each moment carries one
bright square that moves to the right with time, and each plane one that
sits lower with depth, so a picture of any moment and plane is unlike the
next: a test can tell from the pixels alone whether a slider moved it.
Prints the position's own image folder.
"""
import sys
from pathlib import Path

import numpy as np

# Run by path from anywhere: the storage package lives at the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from zmart_storage.canvas import Channel  # noqa: E402
from zmart_storage.positions import start_a_run  # noqa: E402

folder = Path(sys.argv[1])
frames = int(sys.argv[2])
planes = int(sys.argv[3])
side = 256
with start_a_run(folder, name="timelapse", room=(planes, side, side), tile_shape=(planes, side, side),
                 voxel_size_um=(2.0, 1.0, 1.0), channels=[Channel("488")], frames=frames) as run:
    for t in range(frames):
        picture = np.zeros((planes, side, side), np.uint16)
        for z in range(planes):
            x0, y0 = 20 + t * 50, 20 + z * 60
            picture[z, y0:y0 + 40, x0:x0 + 40] = 60000
        position = run.write(picture, at=(0, 0, 0), frame=t)
# The position's own image, which any zarr reader can open as it is. The
# picture the run links above it is made of pointers the viewer's server
# resolves, and a plain file server cannot.
print(position)
