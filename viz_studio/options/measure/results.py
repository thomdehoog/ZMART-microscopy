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
        "**0b. Is the bottom layer genuinely beneath the picture?**",
        lambda f: _reach(f, "0b. is the bottom layer beneath the picture",
                         "the bottom layer is genuinely beneath the picture"),
    ),
    (
        "  … a colour drawn there fills this share of the window",
        lambda f: _reach(f, "0b. is the bottom layer beneath the picture",
                         "with the colour in the bottom slot", "shares of the window",
                         "behind the engine (green)"),
    ),
    (
        "  … and the acquired picture is still showing on top of it",
        lambda f: _reach(f, "0b. is the bottom layer beneath the picture",
                         "with the colour in the bottom slot",
                         "the picture is still on top of it", "the picture survived"),
    ),
    (
        "  … the same colour drawn in the top slot instead (must be large)",
        lambda f: _reach(f, "0b. is the bottom layer beneath the picture",
                         "and the check can fail", "with the colour in the top slot",
                         "shares of the window", "behind the engine (green)"),
    ),
    (
        "  … which must hide the picture, and does (share left showing)",
        lambda f: _reach(f, "0b. is the bottom layer beneath the picture",
                         "and the check can fail", "with the colour in the top slot",
                         "shares of the window", "acquired picture (near white)"),
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
        "**1c. A disagreement about size** — band wider all round than cut, at rest "
        "(screen px)",
        lambda f: _reach(f, "1. registration",
                         "at rest, wider all round than it was cut"),
    ),
    (
        "  … while zooming, at least",
        lambda f: _reach(f, "1. registration", "zooming",
                         "wider all round than it was cut, at least"),
    ),
    (
        "  … with the operator's layer drawn 1.02× on purpose (must be large)",
        lambda f: _reach(f, "1. registration", "and a disagreement about size",
                         "the operator's layer drawn 1.02 times its proper size",
                         "wider all round than it was cut"),
    ),
    (
        "  … and the unevenness at that moment (which cannot see it)",
        lambda f: _reach(f, "1. registration", "and a disagreement about size",
                         "the operator's layer drawn 1.02 times its proper size",
                         "unevenness"),
    ),
    (
        "**1b. Registration of the bottom layer** — worst unevenness at rest (screen px)",
        lambda f: _reach(f, "1b. registration of the bottom layer",
                         "at rest, unevenness"),
    ),
    (
        "  … while panning",
        lambda f: _reach(f, "1b. registration of the bottom layer", "panning",
                         "unevenness"),
    ),
    (
        "  … while zooming",
        lambda f: _reach(f, "1b. registration of the bottom layer", "zooming",
                         "unevenness"),
    ),
    (
        "  … thrown about",
        lambda f: _reach(f, "1b. registration of the bottom layer", "thrown about",
                         "unevenness"),
    ),
    (
        "  … with the ring moved 8 px on purpose (must be large)",
        lambda f: _reach(f, "1b. registration of the bottom layer",
                         "and the check can fail",
                         "the ring moved 8 browser pixels", "unevenness"),
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
        "  … the same count with every channel switched off (must be small)",
        lambda f: _reach(f, "4. sparseness", "and with every channel switched off",
                         "picture"),
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
        "  … the option's own count of what it sent back (a different thing in each)",
        lambda f: _reach(f, "5. new data arriving while somebody is watching",
                         "does it appear at all",
                         "what the option said it sent back to the store"),
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
        "**7. Drawing rate** — frames a second at 20 positions, middle of five",
        lambda f: _rate(f, "20 positions"),
    ),
    (
        "  … at 200 positions, middle of five",
        lambda f: _rate(f, "200 positions"),
    ),
    (
        "**8. Two acquisitions at once** — both are drawn",
        lambda f: _both_are_drawn(f),
    ),
    (
        "  … how far the finer landed from where the store says (µm)",
        lambda f: _reach(f, "8. two acquisitions at once",
                         "seen from far enough out to hold both",
                         "how far its middle is from where it belongs (µm)",
                         "either way"),
    ),
    (
        "  … the band of ground between them, worst departure from 128 µm",
        lambda f: _reach(f, "8. two acquisitions at once", "seen close to",
                         "worst departure from it (µm)"),
    ),
    (
        "  … with the finer's stated origin moved 64 µm (must read about 64)",
        lambda f: _reach(f, "8. two acquisitions at once", "and the check can fail",
                         "seen close to", "worst departure from it (µm)"),
    ),
]


def _both_are_drawn(found: dict) -> str:
    """Whether each of the two runs reached the screen at all.

    Said as "yes" only when both did, and otherwise as which one is missing,
    because "no" on its own would leave a reader guessing which half of the
    arrangement had failed.
    """
    seen = found.get("8. two acquisitions at once", {}).get(
        "seen from far enough out to hold both", {}
    )
    if not seen:
        return "—"
    survey = seen.get("the survey is drawn")
    detail = seen.get("the detail scan is drawn")
    if survey and detail:
        return "yes"
    if not survey and not detail:
        return "**neither**"
    return "**only the survey**" if survey else "**only the detail scan**"


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


def _rate(found: dict, positions: str) -> str:
    """The drawing rate, always with the spread of the readings beside it.

    Written as "8.2 (7.4–8.6)" rather than as a bare number, and never as a bare
    number, because a single reading of this on a machine without a graphics card
    has been seen to vary by a factor of two on an unchanged build. Two columns
    whose ranges overlap have not been shown to differ, and a reader can see that
    from the table itself instead of having to know it.
    """
    middle = _reach(found, "7. drawing rate with many positions", positions,
                    "frames a second")
    if middle == "—":
        return "—"
    spread = _reach(found, "7. drawing rate with many positions", positions,
                    "frames a second, lowest and highest seen")
    if spread == "—":
        return middle
    low, high = json.loads(spread.replace("'", '"'))
    return f"{middle} ({low}–{high})"


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
