"""The scale measurement, run small, so a regression is caught before it is felt.

``measure_ten_thousand_linked.py`` beside the tests answers the real question —
ten thousand positions, timed and checked — and takes minutes to do it. This runs
the same code over a few hundred positions so that every ordinary test run
exercises the whole path: growing a view a position at a time, folding the list,
parsing and indexing it the way the server does, looking pieces up, and following
pointers to the voxels behind them. Every check in the measurement is an
``assert``, so a wrong pointer or a hole that answers with a file fails here.

What this cannot catch is a cost that grows with size — an add that is cheap at
three hundred tiles and ruinous at ten thousand. That is what the measurement
itself is for, and it should be re-run whenever the writer or the reader changes:

    python viz_studio/measure_ten_thousand_linked.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def test_a_few_hundred_positions_grow_link_and_answer_correctly(tmp_path):
    """The whole measurement path, at a size an ordinary test run can afford."""
    here = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "measure_ten_thousand_linked", here / "measure_ten_thousand_linked.py")
    assert spec is not None and spec.loader is not None
    measured = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("measure_ten_thousand_linked", measured)
    spec.loader.exec_module(measured)

    # 18 x 18 is 324 places, about 300 of them imaged after the holes — enough
    # for tiles to cross rows, holes to scatter, and both zooms to be asked.
    measured._measure(tmp_path, grid=18)
