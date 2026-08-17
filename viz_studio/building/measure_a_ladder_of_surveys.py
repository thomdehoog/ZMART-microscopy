"""Climb a ladder of survey sizes and keep the running scorecard.

One rung is one power of two of positions — 2^6 = 64 up to 2^15 = 32,768 —
measured with the full watched churn of ``measure_a_governed_run_at_scale``:
a real browser watches the survey grow at its boundary and be replaced in
its interior, and every change is timed from the writer's publish to the
first painted frame that shows it. The surveys are square, so each rung
uses the side length whose square lands closest to its power of two
(2^7 = 128 becomes an 11 x 11 survey of 121, and so on); the point is the
trend across sizes, and a few positions either way do not bend it.

After every rung the WHOLE table so far is printed again, so a ladder that
takes hours shows its answer as it climbs rather than only at the top. The
same numbers are appended to ``ladder_results.json`` beside the fixtures,
one record per rung, so the run survives its terminal.

For each rung the scorecard keeps, in milliseconds unless said otherwise:

* the writer's cost per change — least, middling (median), mean, 90th
  percentile and worst — split into landings (new tiles) and replacements,
  because they do different work;
* the server's derive per commit and how many tiles it read from disk;
* landing-to-visible, the number an operator actually feels;
* the one-time costs: writing the fixture, the initial bake, the cold
  open, how long the coarse slabs took to warm, and the end-of-run
  linked view;
* the recorder's transient count, where anything but zero fails the rung.

Run it with::

    python measure_a_ladder_of_surveys.py --fixtures E:/zmart-scale-runs
    python measure_a_ladder_of_surveys.py --powers 6-12 --churn 40
    python measure_a_ladder_of_surveys.py --tidy   # delete each fixture after
                                                   # its rung, for small disks

``--tidy`` trades repeatability for disk: a deleted fixture is rebuilt from
scratch on the next run. Leave it off on a machine with room, so repeated
ladders pay the writing once. Expect the top rungs to take a while — the
32,768-position fixture alone writes for the better part of an hour — and
note that the coarse-slab warm-up is waited on for at most five minutes
(the harness's own cap), so on the biggest surveys some changes may land
on still-cold regions; the worst-case columns are where that shows.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: One rung per power of two: the side length whose square lands closest.
LADDER = {
    6: 8,      # 64
    7: 11,     # 121
    8: 16,     # 256
    9: 23,     # 529
    10: 32,    # 1,024
    11: 45,    # 2,025
    12: 64,    # 4,096
    13: 91,    # 8,281
    14: 128,   # 16,384
    15: 181,   # 32,761
}

A_ROW = re.compile(
    r"^\s+(land|replace)\s+\S+\s+(\d+)ms\s+(\d+)ms\s+(\d+)\s+(\d+|nan)ms\s*$"
)
ONE_TIMERS = {
    "wrote_fixture_s": re.compile(r"written in (\d+) s"),
    "baked_s": re.compile(r"declared baked in ([\d.]+) s"),
    "cold_open_s": re.compile(r"Cold open at \d+ committed positions: ([\d.]+) s"),
    "warm_s": re.compile(r"coarse slabs warm ([\d.]+) s"),
    "finish_s": re.compile(r"finish_the_run.*: ([\d.]+) s"),
    "transients": re.compile(r"transients: (\d+)"),
}


def spread(values: list[float]) -> dict:
    """Least, middling, mean, 90th percentile and worst — the honest spread.

    The middling value says what a change usually costs; the 90th percentile
    and the worst say what the slow ones cost, which is what an operator
    notices. A mean without the rest hides exactly those.
    """
    if not values:
        return {}
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "min": round(ordered[0], 1),
        "median": round(statistics.median(ordered), 1),
        "mean": round(statistics.fmean(ordered), 1),
        "p90": round(ordered[min(len(ordered) - 1,
                                 int(0.9 * (len(ordered) - 1)))], 1),
        "max": round(ordered[-1], 1),
    }


def one_rung(power: int, across: int, churn: int, fixtures: str | None,
             tidy: bool) -> dict:
    """Run the full churn at one survey size and distill its numbers."""
    order = [sys.executable, str(HERE / "measure_a_governed_run_at_scale.py"),
             "--across", str(across), "--churn", str(churn),
             "--bake", "--warm-first"]
    if fixtures:
        order += ["--fixtures", fixtures]
    began = time.time()
    ran = subprocess.run(order, capture_output=True, text=True)
    out = ran.stdout
    sys.stdout.write(out)
    if ran.returncode != 0:
        sys.stdout.write(ran.stderr[-4000:])
        raise RuntimeError(f"the {across}x{across} rung failed "
                           f"(exit {ran.returncode})")

    changes = []
    for line in out.splitlines():
        matched = A_ROW.match(line)
        if matched:
            kind, writer, derive, read, visible = matched.groups()
            changes.append({
                "kind": kind,
                "writer_ms": float(writer),
                "derive_ms": float(derive),
                "tiles_read": int(read),
                "visible_ms": None if visible == "nan" else float(visible),
            })
    record = {
        "power": power,
        "positions": across * across,
        "across": across,
        "wall_s": round(time.time() - began, 1),
        "writer_land_ms": spread([c["writer_ms"] for c in changes
                                  if c["kind"] == "land"]),
        "writer_replace_ms": spread([c["writer_ms"] for c in changes
                                     if c["kind"] == "replace"]),
        "derive_ms": spread([c["derive_ms"] for c in changes]),
        "visible_ms": spread([c["visible_ms"] for c in changes
                              if c["visible_ms"] is not None]),
        "tiles_read_total": sum(c["tiles_read"] for c in changes),
    }
    for name, pattern in ONE_TIMERS.items():
        matched = pattern.search(out)
        record[name] = float(matched.group(1)) if matched else None

    if tidy and fixtures:
        built = Path(fixtures) / "experiment" / "acquisitions" / f"survey-{across}"
        if built.is_dir():
            shutil.rmtree(built)
            sys.stdout.write(f"(tidied away {built})\n")
    return record


def the_table_so_far(records: list[dict]) -> str:
    """Every rung measured so far, one line each, medians with the spread."""
    lines = [
        "",
        "== the ladder so far "
        "(median [p90/max] ms; one-time costs in seconds) ==",
        f"{'positions':>9} {'land':>16} {'replace':>16} {'derive':>16} "
        f"{'visible':>16} {'read':>5} {'bake':>7} {'warm':>7} {'finish':>7} "
        f"{'trans':>6}",
    ]
    for r in records:
        def told(name, r=r):
            s = r.get(name) or {}
            if not s:
                return "-"
            return f"{s['median']:.0f} [{s['p90']:.0f}/{s['max']:.0f}]"
        lines.append(
            f"{r['positions']:>9} {told('writer_land_ms'):>16} "
            f"{told('writer_replace_ms'):>16} {told('derive_ms'):>16} "
            f"{told('visible_ms'):>16} {r['tiles_read_total']:>5} "
            f"{(r['baked_s'] or 0):>7.1f} "
            f"{(r['warm_s'] if r['warm_s'] is not None else 0):>7.1f} "
            f"{(r['finish_s'] or 0):>7.1f} "
            f"{int(r['transients'] or 0):>6}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parsing = argparse.ArgumentParser(description=__doc__)
    parsing.add_argument("--powers", default="6-15",
                         help="which rungs, as a range of powers of two "
                              "(default 6-15: 64 up to 32,768 positions)")
    parsing.add_argument("--churn", type=int, default=40,
                         help="watched changes per rung, half landings and "
                              "half replacements (the harness's default 40)")
    parsing.add_argument("--fixtures", default=None,
                         help="where the fixtures live, passed through to "
                              "the harness")
    parsing.add_argument("--tidy", action="store_true",
                         help="delete each rung's fixture after measuring "
                              "it, for machines without room for them all")
    asked = parsing.parse_args()
    low, high = (int(part) for part in asked.powers.split("-"))

    results = (Path(asked.fixtures) if asked.fixtures else HERE) \
        / "ladder_results.json"
    records: list[dict] = []
    if results.is_file():
        records = json.loads(results.read_text(encoding="utf-8"))
        done = {r["power"] for r in records}
        print(f"picking up: rungs {sorted(done)} already measured "
              f"in {results}")

    for power in range(low, high + 1):
        if any(r["power"] == power for r in records):
            continue
        across = LADDER[power]
        print(f"\n#### rung 2^{power}: {across * across} positions "
              f"({across} across), churn {asked.churn}", flush=True)
        record = one_rung(power, across, asked.churn, asked.fixtures,
                          asked.tidy)
        records.append(record)
        records.sort(key=lambda r: r["power"])
        results.parent.mkdir(parents=True, exist_ok=True)
        results.write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(the_table_so_far(records), flush=True)
    print(f"the ladder is measured; every rung's full spread is in {results}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
