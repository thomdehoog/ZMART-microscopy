"""The watched acquisition follows one continuous tile-by-tile spiral."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "picture"))

from show_a_run_growing import spiral_order  # noqa: E402


def coordinates(position_id: str, width: int) -> tuple[int, int]:
    return (int(position_id[1:1 + width]), int(position_id[1 + width:]))


@pytest.mark.parametrize("across", [3, 4, 39, 40])
def test_the_show_uses_one_true_spiral_without_jumps(across):
    """Odd and even surveys visit every tile once through adjacent moves."""
    width = len(str(across - 1))
    order = spiral_order(across, width)
    visited = [coordinates(position_id, width) for position_id in order]

    assert len(visited) == across * across
    assert set(visited) == {
        (row, column)
        for row in range(across)
        for column in range(across)
    }
    assert all(
        abs(row_a - row_b) + abs(column_a - column_b) == 1
        for (row_a, column_a), (row_b, column_b)
        in zip(visited[:-1], visited[1:], strict=True)
    )
