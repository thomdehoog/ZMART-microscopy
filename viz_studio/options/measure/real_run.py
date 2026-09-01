"""Measure one option on a run this rig did not write, and touch nothing beside it.

The measurement suite next to this file writes little acquisitions of its own
and measures the options over them. That is the right way to compare the
options with one another, and the wrong way to learn what one of them does
on a run a microscope actually produced: every finding from the one real
75 GB acquisition this project has opened was invisible to a suite that only
ever looked at stores it wrote itself (``RESULTS.md`` says so at length).

So this is the rig pointed outward. It is handed a folder or a store that
already exists, serves it read-only from where it is, opens the chosen option
on it once, and writes down what happened: how long until a picture, how many
requests that took and how many bytes crossed the wire — pieces and
descriptions counted separately, so a later "is this format smaller" question
cannot choose a flattering subset — and a photograph of what was drawn.

It does not run the synthetic rows, does not write fixtures beside the run,
and does not rewrite the results table. Its answer goes to its own folder.

Run it through the rig's own door::

    python viz_studio/options/measure/run.py --external-run /path/to/run --option neuroglancer-under
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import drive

#: The stores a run may hold, in the order one is worth opening. A composed
#: picture the viewer linked, if there is one, is the whole run; failing that,
#: the first position store there is.
_A_COMPOSED_PICTURE = "*.zmartview.zarr"
_A_STORE = "*.ome.zarr"


def the_store_to_open(run: Path) -> tuple[Path, str]:
    """The folder to serve and the store within it to open, or a plain refusal.

    Accepts one store, a folder of stores, or a run folder whose stores sit
    under ``positions/<type>/``. Nothing is written anywhere: this only looks.
    """
    run = Path(run).resolve()
    if not run.exists():
        raise FileNotFoundError(f"{run} does not exist")
    if run.is_dir() and (run / "zarr.json").is_file() or (run / ".zattrs").is_file():
        return run.parent, run.name
    candidates: list[Path] = []
    for pattern in (_A_COMPOSED_PICTURE, _A_STORE):
        candidates = sorted(run.glob(pattern))
        if candidates:
            return run, candidates[0].name
    positions = run / "positions"
    if positions.is_dir():
        for kind in sorted(one for one in positions.iterdir() if one.is_dir()):
            for pattern in (_A_COMPOSED_PICTURE, _A_STORE):
                candidates = sorted(kind.glob(pattern))
                if candidates:
                    return kind, candidates[0].name
    raise FileNotFoundError(
        f"{run} holds no OME-Zarr store to open: looked for {_A_COMPOSED_PICTURE} and "
        f"{_A_STORE} in it and under positions/<type>/"
    )


def drawn_share_of(picture) -> float:
    """What fraction of the photograph is not black: 0 for an empty box, 1 for full.

    The one number that tells "opened and drew" from "opened and drew nothing",
    which is the failure this project keeps meeting. A run whose picture never
    arrives reports itself perfectly loaded and photographs as black.
    """
    import numpy as np

    pixels = np.asarray(picture)
    if pixels.ndim == 3:
        pixels = pixels[..., :3].max(axis=-1)
    return float((pixels > 16).mean()) if pixels.size else 0.0


def measure(option: str, run: Path, out: Path, *, browser=None) -> dict:
    """Open ``option`` on ``run`` once and write down what it cost."""
    served_from, store_name = the_store_to_open(run)
    store = store_name[: -len(".ome.zarr")] if store_name.endswith(".ome.zarr") else store_name
    out = Path(out) / option
    out.mkdir(parents=True, exist_ok=True)
    found = {
        "option": option,
        "run": str(Path(run).resolve()),
        "served_from": str(served_from),
        "store": store_name,
        "measured": time.strftime("%Y-%m-%d %H:%M"),
        "read_only": True,
    }
    with drive.Harness(served_from, out, option=option, browser=browser) as harness:
        harness.clear_ledger()
        started = time.perf_counter()
        harness.open(store=store, draw="none")
        found["seconds_to_a_settled_picture"] = round(time.perf_counter() - started, 3)
        found["requests"] = harness.read_ledger()
        picture = harness.photograph()
        found["photograph"] = harness.save_frame(picture, "opened")
        found["drawn_share"] = drawn_share_of(picture)
        found["view"] = harness.believes("window.harness.view()")
        found["console"] = list(harness.console)[-20:]
    where = out / "real-run.json"
    where.write_text(json.dumps(found, indent=2, default=str), encoding="utf-8")
    found["written_to"] = str(where)
    return found
