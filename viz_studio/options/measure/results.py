"""Turn the measurements into the table in ``RESULTS.md``.

One column per option, so that three viewers can be read side by side. The table
is generated rather than written by hand, for a reason worth stating: a table
kept by hand slowly stops describing the run it came from, and a number that has
quietly stopped matching its measurement is worse than no number at all.

Everything outside the table is written by people and left alone. The table sits
between two markers in the file, and only what is between them is replaced.
"""

from __future__ import annotations

import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
RESULTS = _HERE.parent / "RESULTS.md"

BEGIN = "<!-- the table below is written by measure/results.py; edit above or below it -->"
END = "<!-- end of the generated table -->"


def _reach(found: dict, *path, otherwise="—"):
    """Follow a path of keys, and say plainly when it is not there."""
    at = found
    for step in path:
        if not isinstance(at, dict) or step not in at:
            return otherwise
        at = at[step]
    if isinstance(at, bool):
        return "yes" if at else "**no**"
    if at is None:
        return "—"
    return str(at)


# What goes in the table, in the order OPTIONS.md asks the questions. Each row is
# a name and a way of pulling one number out of one option's measurements.
ROWS = [
    (
        "**0. Can a surface underneath the engine be seen?**",
        lambda f: _reach(f, "0. can a surface underneath be seen",
                         "a surface underneath is usable"),
    ),
    (
        "**1. Registration** — worst unevenness at rest (screen px)",
        lambda f: _reach(f, "1. registration", "at rest, unevenness"),
    ),
    (
        "  … while panning",
        lambda f: _reach(f, "1. registration", "panning", "unevenness"),
    ),
    (
        "  … while zooming",
        lambda f: _reach(f, "1. registration", "zooming", "unevenness"),
    ),
    (
        "  … thrown about",
        lambda f: _reach(f, "1. registration", "thrown about", "unevenness"),
    ),
    (
        "  … with the hole moved 8 px on purpose (must be large)",
        lambda f: _reach(f, "1. registration", "and the check can fail",
                         "the hole moved 8 browser pixels", "unevenness"),
    ),
    (
        "**2. Handedness** — brightness across the picture (levels per 100 px)",
        lambda f: _reach(f, "2. handedness",
                         "brightness across the picture, grey levels per hundred pixels"),
    ),
    (
        "  … the bright edge is on the right",
        lambda f: _reach(f, "2. handedness", "the bright edge is drawn on the right"),
    ),
    (
        "  … dragging carries the picture with the hand (slope)",
        lambda f: _reach(f, "2. handedness",
                         "and dragging carries the picture with the hand", "slope"),
    ),
    (
        "**3. Two gestures** — removed gestures that moved the view",
        lambda f: _moved_anything(f),
    ),
    (
        "  … gestures the page refused",
        lambda f: _refused(f),
    ),
    (
        "**4. Sparseness** — share of the window showing picture",
        lambda f: _reach(f, "4. sparseness",
                         "share of the window showing acquired picture"),
    ),
    (
        "  … the operator's plan shows through the gaps",
        lambda f: _reach(f, "4. sparseness",
                         "the operator's plan shows through the gaps"),
    ),
    (
        "**5a. New data appears at all**",
        lambda f: _reach(f, "5. new data arriving while somebody is watching",
                         "does it appear at all", "it appeared"),
    ),
    (
        "  … readers the option had to send back to the store",
        lambda f: _reach(f, "5. new data arriving while somebody is watching",
                         "does it appear at all", "readers sent back to the store"),
    ),
    (
        "**5b. What the refresh costs** — pieces re-fetched",
        lambda f: _reach(f, "5. new data arriving while somebody is watching",
                         "what the refresh costs",
                         "pieces of image re-fetched to show the new tiles"),
    ),
    (
        "**5c. The picture survives the refresh** — seconds before it is back",
        lambda f: _reach(f, "5. new data arriving while somebody is watching",
                         "does the picture survive the refresh",
                         "seconds before the picture was back to half of that"),
    ),
    (
        "  … what the window showed while it refreshed",
        lambda f: _reach(f, "5. new data arriving while somebody is watching",
                         "does the picture survive the refresh",
                         "what the window showed, frame by frame"),
    ),
    (
        "**5d. The view stays put** — centre moved (µm)",
        lambda f: _reach(f, "5. new data arriving while somebody is watching",
                         "does the view stay where the operator put it",
                         "the centre moved (µm)"),
    ),
    (
        "**5e. How soon a tile shows** (seconds)",
        lambda f: _reach(f, "5. new data arriving while somebody is watching",
                         "how soon after the tile lands does it show", "seconds"),
    ),
    (
        "**5f. Does it keep up** — frames a second, first round → last",
        lambda f: _first_to_last(f),
    ),
    (
        "  … tiles written meanwhile",
        lambda f: _reach(f, "5. new data arriving while somebody is watching",
                         "does it keep up", "tiles written during the measurement"),
    ),
    (
        "**6. Requests** — to redraw one view, unbounded",
        lambda f: _reach(f, "6. requests", "unbounded", "requests to redraw the view"),
    ),
    (
        "  … of those, for ground nobody imaged",
        lambda f: _reach(f, "6. requests", "unbounded",
                         "of which were for ground nobody imaged"),
    ),
    (
        "  … bounded by the coverage record",
        lambda f: _reach(f, "6. requests", "bounded to the imaged ground",
                         "requests to redraw the view"),
    ),
    (
        "  … of those, for ground nobody imaged",
        lambda f: _reach(f, "6. requests", "bounded to the imaged ground",
                         "of which were for ground nobody imaged"),
    ),
    (
        "**7. Drawing rate** — frames a second at 20 positions",
        lambda f: _reach(f, "7. drawing rate with many positions", "20 positions",
                         "frames a second"),
    ),
    (
        "  … at 200 positions",
        lambda f: _reach(f, "7. drawing rate with many positions", "200 positions",
                         "frames a second"),
    ),
]


def _moved_anything(found: dict) -> str:
    made = found.get("3. two gestures and no more", {})
    removed = made.get("the gestures that were removed", {})
    if not removed:
        return "—"
    moved = [name for name, what in removed.items() if what != "unchanged, byte for byte"]
    return "none" if not moved else f"**{len(moved)}: {'; '.join(moved)}**"


def _refused(found: dict) -> str:
    counted = found.get("3. two gestures and no more", {}).get("what the page counted")
    if not counted:
        return "—"
    refused = counted.get("refused", {})
    return ", ".join(f"{value} {key}" for key, value in refused.items() if value)


def _first_to_last(found: dict) -> str:
    rate = _reach(
        found, "5. new data arriving while somebody is watching",
        "does it keep up", "frames a second, round by round",
    )
    if rate == "—":
        return "—"
    numbers = json.loads(rate.replace("'", '"'))
    if not numbers:
        return "—"
    return f"{numbers[0]} → {numbers[-1]}"


def write_the_table(measurements: Path) -> str:
    """Rewrite the table in RESULTS.md from whatever measurements are on disk."""
    found = {}
    for path in sorted(Path(measurements).glob("*.json")):
        found[path.stem] = json.loads(path.read_text())
    if not found:
        return ""
    options = list(found)
    lines = [
        BEGIN,
        "",
        "| | " + " | ".join(options) + " |",
        "| --- | " + " | ".join("---" for _ in options) + " |",
        "| *measured* | "
        + " | ".join(found[o].get("measured", "—") for o in options)
        + " |",
    ]
    for name, pull in ROWS:
        lines.append(
            f"| {name} | " + " | ".join(pull(found[o]) for o in options) + " |"
        )
    lines += ["", END]
    table = "\n".join(lines)

    text = RESULTS.read_text() if RESULTS.exists() else ""
    if BEGIN in text and END in text:
        before = text.split(BEGIN)[0]
        after = text.split(END)[1]
        RESULTS.write_text(before + table + after)
    else:
        RESULTS.write_text(text + "\n\n" + table + "\n")
    return table
