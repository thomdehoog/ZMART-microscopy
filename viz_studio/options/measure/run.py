"""Run the whole suite against one option, or against every option in turn.

    python viz_studio/options/measure/run.py --option neuroglancer-under
    python viz_studio/options/measure/run.py --option all

It writes a folder of photographs and a ``results.json`` beside them, prints a
readable summary as it goes, and — unless you ask it not to — rewrites the table
in ``viz_studio/options/RESULTS.md`` with a column for every option that has been
measured.

Nothing here knows anything about any particular option. That is the point: the
next two options are measured by running this file with a different word, and
the numbers land in the same table beside the first.

Before running it, build the page the measurements drive:

    npm --prefix viz_studio/options/harness run build
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import acquisitions  # noqa: E402
import drive  # noqa: E402
from results import write_the_table  # noqa: E402
from suite import EVERYTHING  # noqa: E402


def options_that_exist() -> list[str]:
    """Every option somebody has actually written, found by looking.

    A folder beside this one holding a ``viewer.js`` is an option. Discovered
    rather than listed here on purpose: a list would be a second place to
    remember to edit, and the person adding the third option should have to
    change one file, not two.
    """
    beside = _HERE.parent
    return sorted(
        folder.name
        for folder in beside.iterdir()
        if folder.is_dir() and (folder / "viewer.js").exists()
    )


def measure_one(option: str, data_dir: Path, out: Path) -> dict:
    """Every measurement, against one option."""
    found = {"option": option, "measured": time.strftime("%Y-%m-%d %H:%M")}
    with drive.Harness(data_dir, out / option, option=option) as harness:
        for name, measurement in EVERYTHING.items():
            print(f"  {name} …", flush=True)
            started = time.perf_counter()
            try:
                found[name] = measurement(harness, data_dir)
            except Exception as went_wrong:
                # A measurement that could not be taken is recorded as one that
                # could not be taken, not quietly left out. An option missing a
                # row in the table and an option with an empty row look the same
                # in a summary and are quite different things.
                found[name] = {
                    "could not be measured": str(went_wrong),
                    "where": traceback.format_exc().splitlines()[-3:],
                }
                print(f"    could not be measured: {went_wrong}", flush=True)
            print(f"    {time.perf_counter() - started:.1f} s", flush=True)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--option",
        default="neuroglancer-under",
        help="which option to measure, or 'all' for every one the page was built with",
    )
    parser.add_argument("--out", type=Path, default=_HERE.parent / "measurements")
    parser.add_argument(
        "--data",
        type=Path,
        default=None,
        help="where to write the little acquisitions; made fresh if left out",
    )
    parser.add_argument(
        "--leave-the-table-alone",
        action="store_true",
        help="do not rewrite the table in RESULTS.md",
    )
    args = parser.parse_args()

    drive.require_a_browser()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    data_dir = args.data or (out / "acquisitions")
    # Every store the suite needs, checked one by one rather than by looking for
    # a single one of them. A folder written before a new acquisition was added
    # would otherwise look complete, and the measurement that needed the new one
    # would fail with something about an address rather than with "it is not
    # there".
    missing = [
        name for name in acquisitions.EVERY_STORE
        if not (data_dir / f"{name}.ome.zarr").exists()
    ]
    if missing:
        print(
            f"writing the measurement acquisitions into {data_dir} "
            f"(missing: {', '.join(missing)}) …",
            flush=True,
        )
        acquisitions.write_them_all(data_dir)

    wanted = [args.option] if args.option != "all" else options_that_exist()

    everything = {}
    for option in wanted:
        print(f"\nmeasuring {option}", flush=True)
        everything[option] = measure_one(option, data_dir, out)
        (out / f"{option}.json").write_text(
            json.dumps(everything[option], indent=2, default=str)
        )
        print(f"  written to {out / f'{option}.json'}", flush=True)

    if not args.leave_the_table_alone:
        write_the_table(out)
        print(f"\nthe table in {_HERE.parent / 'RESULTS.md'} has been brought up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
