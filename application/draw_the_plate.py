"""Draw the whole plate as it stands, while the run is still going.

    python draw_the_plate.py --bridge 8791 --into plate.png

The operator window shows the picture on its canvas, and that is the right
place to look at it. But there are two moments when you want the plate as a
plain picture instead: when you are watching a long run from somewhere else,
and when you are asking whether the *data* is complete rather than whether
the window is drawing it. This is for those. It opens no browser, touches no
canvas, and asks nothing of the operator page — it fetches the picture the
viewer is already serving and writes it out as a PNG.

Because it reads the run's own smallest copy of itself, it costs almost
nothing to run: a 96-well plate comes back as a few hundred pixels across, a
couple of pieces of picture, however many hundreds of fields have been
acquired into it. So it can be run every minute of a long acquisition
without getting in the way of the acquisition.

What it tells you, beyond the picture itself:

- how many positions the viewer has linked into one picture so far, and how
  far the scan has got, so you can see whether the picture is behind the run;
- how many pieces of the picture actually carried anything, which is the
  question to ask when a plate looks emptier than it should;
- what share of the plate carries picture at all.

Author: Thom de Hoog (ZMB, University of Zurich).
License: MIT
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

import numpy as np


def _fetch(url: str, seconds: float = 300) -> bytes | None:
    """The bytes at an address, or nothing at all if they cannot be had.

    A piece of picture that is not there is an ordinary answer rather than a
    fault: most of a plate is the space between the wells, and nobody has
    imaged that. So a missing piece is simply left as nought.
    """
    try:
        with urllib.request.urlopen(url, timeout=seconds) as answer:
            return answer.read()
    except (urllib.error.URLError, OSError):
        return None


def the_plate_as_it_stands(
    port: int, acquisition: str = "overview", tries: int = 4,
) -> tuple[np.ndarray, dict]:
    """The acquisition's smallest copy of itself, and what was learned fetching it.

    ``port`` is the operator bridge's, not the viewer's: the bridge is asked
    where its viewer is and what it is serving, so this needs only the one
    number an operator already knows.

    **Where a run is asked about changes while the run goes on**, and that is
    worth knowing rather than being surprised by. Each time the growing folder
    of positions is linked into one picture again, the viewer serves the new
    picture at a new address and lets the old one go. So an address read a
    moment ago can be gone by the time it is used — which, during a scan, is
    most of the time. It is asked for again rather than treated as a failure.
    """
    at = f"http://127.0.0.1:{port}"

    for attempt in range(tries):
        state = json.loads(_fetch(f"{at}/api/viewer") or b"{}")
        scan = json.loads(_fetch(f"{at}/api/scan") or b"{}")
        held = (state.get("sources") or {}).get(acquisition)

        if not held:
            known = ", ".join(state.get("sources") or {}) or "nothing yet"
            raise SystemExit(
                f"the viewer is not serving an acquisition called {acquisition!r}. "
                f"It is serving: {known}."
            )

        url = held[0]["url"].split("|")[0].rstrip("/")
        described = _fetch(f"{url}/zarr.json")
        if described:
            break
        if attempt == tries - 1:
            raise SystemExit(
                f"the picture at {url} was gone before it could be read, {tries} "
                "times over. That happens while a scan is landing positions "
                "quickly; try again when the run is quieter."
            )
    root = json.loads(described)
    described = root["attributes"]["ome"]["multiscales"][0]
    axes = [axis["name"] for axis in described["axes"]]
    levels = [dataset["path"] for dataset in described["datasets"]]

    coarsest = levels[-1]
    array = json.loads(_fetch(f"{url}/{coarsest}/zarr.json") or b"{}")
    shape, kind = array["shape"], np.dtype(array["data_type"])
    piece = array["chunk_grid"]["configuration"]["chunk_shape"]
    down, across = axes.index("y"), axes.index("x")
    height, width = shape[down], shape[across]

    from numcodecs import Zstd  # noqa: PLC0415 -- only needed once there is a picture

    unzip = Zstd()
    picture = np.zeros((height, width), dtype=kind)
    carried = asked = 0

    for row in range(-(-height // piece[down])):
        for column in range(-(-width // piece[across])):
            address = [0] * len(shape)
            address[down], address[across] = row, column
            asked += 1
            body = _fetch(f"{url}/{coarsest}/c/" + "/".join(str(one) for one in address))
            if not body:
                continue
            carried += 1
            block = np.squeeze(np.frombuffer(unzip.decode(body), dtype=kind).reshape(piece))
            if block.ndim > 2:
                block = block.reshape(-1, block.shape[-2], block.shape[-1])[0]
            top, left = row * piece[down], column * piece[across]
            rows = min(block.shape[0], height - top)
            columns = min(block.shape[1], width - left)
            picture[top:top + rows, left:left + columns] = block[:rows, :columns]

    return picture, {
        "acquisition": acquisition,
        "positions linked": root["attributes"].get("zmart", {}).get("tiles"),
        "levels": len(levels),
        "coarsest": f"{width} x {height}",
        "pieces carrying picture": f"{carried} of {asked}",
        "scan": f"{scan.get('done')} of {scan.get('of')}",
    }


def _as_a_picture(picture: np.ndarray) -> np.ndarray:
    """The stored numbers as something an eye can read.

    Stretched between the darkest and brightest of what was *imaged*, ignoring
    the ground nobody has been to — otherwise a plate that is mostly empty
    space stretches its whole range across that emptiness and the tissue comes
    out as a flat white smear.
    """
    imaged = picture[picture > 0]
    if not imaged.size:
        return np.zeros(picture.shape, dtype=np.uint8)
    low, high = np.percentile(imaged, [1, 99.5])
    shown = np.clip((picture.astype(np.float32) - low) / max(float(high - low), 1.0), 0, 1)
    return (shown * 255).astype(np.uint8)


def main() -> int:
    parsing = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parsing.add_argument("--bridge", type=int, default=8791,
                         help="the port the operator bridge is answering on")
    parsing.add_argument("--into", default="plate.png", help="where to write the picture")
    parsing.add_argument("--acquisition", default="overview",
                         help="which acquisition to draw: overview, focussing, targets")
    asked = parsing.parse_args()

    picture, learned = the_plate_as_it_stands(asked.bridge, asked.acquisition)
    for name, value in learned.items():
        print(f"{name}: {value}")

    from PIL import Image  # noqa: PLC0415 -- only needed to write the file

    Image.fromarray(_as_a_picture(picture)).save(asked.into)
    covered = 100 * float((picture > 0).mean())
    print(f"wrote {asked.into}; {covered:.1f}% of the picture carries acquired image")
    return 0


if __name__ == "__main__":
    sys.exit(main())
