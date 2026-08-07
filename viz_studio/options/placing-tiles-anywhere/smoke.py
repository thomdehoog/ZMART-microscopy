"""Fetch the whole picture over HTTP, the way a browser would, and check it."""

import json
import sys
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import geometry as g
from compose import Composer
from compose_server import serve, STORE

HERE = Path(__file__).resolve().parent
POSITIONS = HERE / "run" / "anywhere.ome.zarr" / "positions"


def get(address: str, inside: str) -> bytes:
    with urllib.request.urlopen(f"{address}/{STORE}/{inside}") as answer:
        return answer.read()


def main() -> None:
    server, address, ledger = serve(POSITIONS, g.PLACES)
    print(f"serving on {address}/{STORE}")

    described = json.loads(get(address, "zarr.json"))
    multiscale = described["attributes"]["ome"]["multiscales"][0]
    print("axes:", [one["name"] for one in multiscale["axes"]])
    print("transformations sit inside the dataset:",
          [one["type"] for one in multiscale["datasets"][0]["coordinateTransformations"]])
    print("none beside the multiscale:",
          "coordinateTransformations" not in multiscale)

    array = json.loads(get(address, "0/zarr.json"))
    print("shape:", array["shape"], "pieces of:",
          array["chunk_grid"]["configuration"]["chunk_shape"])

    # Every piece fetched over the wire, decoded by plain zarr, laid out and
    # compared with the canvas we meant to make.
    import zarr
    scratch = HERE / "over-the-wire.zarr"
    if scratch.exists():
        import shutil
        shutil.rmtree(scratch)
    (scratch / "0").mkdir(parents=True)
    (scratch / "0" / "zarr.json").write_bytes(json.dumps(array).encode())
    across = g.CANVAS // g.CHUNK
    for cy in range(across):
        for cx in range(across):
            body = get(address, f"0/c/0/0/0/{cy}/{cx}")
            where = scratch / "0" / "c" / "0" / "0" / "0" / str(cy)
            where.mkdir(parents=True, exist_ok=True)
            (where / str(cx)).write_bytes(body)
    got = zarr.open_array(str(scratch / "0"), mode="r")[0, 0, 0]
    wrong = int((got != g.truth()).sum())
    print(f"\nfetched {ledger['pieces']} pieces over HTTP; voxels wrong: {wrong}")
    print("anything asked for that does not exist:", ledger["refused"])

    import shutil
    shutil.rmtree(scratch)
    server.shutdown()
    if wrong:
        raise SystemExit("the picture served over HTTP is not the picture meant")


if __name__ == "__main__":
    main()
