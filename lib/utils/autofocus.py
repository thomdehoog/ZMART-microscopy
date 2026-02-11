#!/usr/bin/env python3
"""
autofocus_utils.py

Utilities for autofocus acquisition workflow:
- Optimal path calculation (OR-Tools TSP solver)
- Multiple ordering strategies (rowwise, meandering, shortest_path, etc.)
- LAS X API client wrapper with reconnection and race condition protection
- Autofocus sequence execution

Usage:
    from utils.autofocus import (
        calculate_acquisition_order,
        order_points,
        LasXClient,
        run_autofocus_sequence,
        acquire_all_positions,
    )
"""

import math
import random as _random
import threading
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable, Literal, Tuple
from copy import deepcopy

# OR-Tools for production-grade TSP solving (optional)
try:
    from ortools.constraint_solver import routing_enums_pb2, pywrapcp
    ORTOOLS_AVAILABLE = True
except ImportError:
    ORTOOLS_AVAILABLE = False

_TSP_SOLVER_MSG_SHOWN = False


# Ã¢â€ÂÃ¢â€ÂÃ¢â€Â Ordering Strategies Ã¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€Â

OrderStrategy = Literal[
    "rowwise",
    "rowwise_meandering",
    "columnwise",
    "columnwise_meandering",
    "shortest_path",
    "random",
]

ALL_ORDER_STRATEGIES: list[str] = [
    "rowwise",
    "rowwise_meandering",
    "columnwise",
    "columnwise_meandering",
    "shortest_path",
    "random",
]


def _euclidean_distance(p1: Dict[str, Any], p2: Dict[str, Any]) -> float:
    """Calculate Euclidean distance between two points."""
    return math.hypot(p1["x_um"] - p2["x_um"], p1["y_um"] - p2["y_um"])


# Ã¢â€â‚¬Ã¢â€â‚¬ Row / Column helpers Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def _assign_grid_indices(
    points: List[Dict[str, Any]],
    axis: str,
    tolerance_fraction: float = 0.3,
) -> List[int]:
    """
    Assign row or column indices by clustering coordinates.

    *axis* is ``'y'`` for rows (group by Y) or ``'x'`` for columns.
    Points within *tolerance_fraction* Ãƒâ€” median spacing are put in the same
    row / column.
    """
    coords = [p["y_um"] if axis == "y" else p["x_um"] for p in points]
    sorted_unique = sorted(set(coords))

    if len(sorted_unique) <= 1:
        return [0] * len(points)

    # Compute a tolerance from the median gap between sorted unique values
    gaps = [sorted_unique[i + 1] - sorted_unique[i] for i in range(len(sorted_unique) - 1)]
    median_gap = sorted(gaps)[len(gaps) // 2]
    tol = median_gap * tolerance_fraction

    # Cluster
    clusters: list[float] = [sorted_unique[0]]
    for v in sorted_unique[1:]:
        if v - clusters[-1] > tol:
            clusters.append(v)

    # Map each point to its cluster index
    indices: list[int] = []
    for c in coords:
        best_idx = min(range(len(clusters)), key=lambda i: abs(c - clusters[i]))
        indices.append(best_idx)

    return indices


def _order_rowwise(points: List[Dict[str, Any]], meandering: bool = False) -> List[int]:
    """Order left-to-right, top-to-bottom.  If *meandering*, alternate direction per row."""
    row_indices = _assign_grid_indices(points, axis="y")
    n_rows = max(row_indices) + 1

    # Build (row, x, original_index) tuples
    items = [(row_indices[i], points[i]["x_um"], i) for i in range(len(points))]

    ordered: list[int] = []
    for r in range(n_rows):
        row_items = [(x, idx) for (row, x, idx) in items if row == r]
        row_items.sort(key=lambda t: t[0])
        if meandering and r % 2 == 1:
            row_items.reverse()
        ordered.extend(idx for _, idx in row_items)

    return ordered


def _order_columnwise(points: List[Dict[str, Any]], meandering: bool = False) -> List[int]:
    """Order top-to-bottom, left-to-right.  If *meandering*, alternate direction per column."""
    col_indices = _assign_grid_indices(points, axis="x")
    n_cols = max(col_indices) + 1

    items = [(col_indices[i], points[i]["y_um"], i) for i in range(len(points))]

    ordered: list[int] = []
    for c in range(n_cols):
        col_items = [(y, idx) for (col, y, idx) in items if col == c]
        col_items.sort(key=lambda t: t[0])
        if meandering and c % 2 == 1:
            col_items.reverse()
        ordered.extend(idx for _, idx in col_items)

    return ordered


# Ã¢â€â‚¬Ã¢â€â‚¬ TSP solvers Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def _solve_tsp_ortools(points: List[Dict[str, Any]]) -> List[int]:
    """
    Solve the Travelling Salesman Problem using Google OR-Tools.

    Finds the order to visit **ALL** points exactly once that minimizes
    total travel distance (open-path TSP Ã¢â‚¬â€ no return to start).

    Returns:
        List of indices in optimal visiting order.
    """
    n = len(points)
    if n <= 1:
        return list(range(n))
    if n == 2:
        return [0, 1]

    # Build integer distance matrix (OR-Tools needs ints Ã¢â‚¬â€ scale Ã‚Âµm to nm)
    SCALE = 1000  # Ã‚Âµm Ã¢â€ â€™ nm for integer precision
    dist_matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                d = _euclidean_distance(points[i], points[j])
                dist_matrix[i][j] = int(d * SCALE)

    # Create routing model
    manager = pywrapcp.RoutingIndexManager(n, 1, 0)  # 1 vehicle, depot at 0
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return dist_matrix[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Search parameters Ã¢â‚¬â€ use multiple strategies for best result
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    # Time limit scales with problem size, min 1s
    search_params.time_limit.FromSeconds(max(1, n // 10))

    solution = routing.SolveWithParameters(search_params)

    if solution is None:
        # Fallback: just return indices in order
        return list(range(n))

    # Extract path
    path: list[int] = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        path.append(manager.IndexToNode(index))
        index = solution.Value(routing.NextVar(index))

    return path


def _nearest_neighbor_tsp(points: List[Dict[str, Any]], start_idx: int = 0) -> List[int]:
    """Nearest-neighbor heuristic as initial solution."""
    n = len(points)
    if n <= 1:
        return list(range(n))

    visited = [False] * n
    path = [start_idx]
    visited[start_idx] = True
    current = start_idx

    for _ in range(n - 1):
        best_next = -1
        best_dist = float("inf")
        for j in range(n):
            if not visited[j]:
                d = _euclidean_distance(points[current], points[j])
                if d < best_dist:
                    best_dist = d
                    best_next = j
        path.append(best_next)
        visited[best_next] = True
        current = best_next

    return path


def _two_opt_improve(points: List[Dict[str, Any]], path: List[int],
                     max_iterations: int = 500) -> List[int]:
    """
    2-opt local search Ã¢â‚¬â€ runs until no improvement found (full sweep).

    Unlike the old version, this does NOT break after the first improvement
    per iteration; it fully sweeps all (i, j) pairs before restarting.
    """
    def _seg_dist(p: List[int]) -> float:
        return sum(
            _euclidean_distance(points[p[i]], points[p[i + 1]])
            for i in range(len(p) - 1)
        )

    best = path[:]
    best_len = _seg_dist(best)
    improved = True
    it = 0

    while improved and it < max_iterations:
        improved = False
        it += 1
        for i in range(1, len(best) - 1):
            for j in range(i + 1, len(best)):
                new = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                new_len = _seg_dist(new)
                if new_len < best_len - 1e-9:
                    best = new
                    best_len = new_len
                    improved = True

    return best


def _solve_tsp_builtin(points: List[Dict[str, Any]]) -> List[int]:
    """
    Built-in TSP solver: multi-start nearest-neighbor + full 2-opt.

    Tries starting from each of the 4 corners + centroid, picks the best.
    Good results for typical microscopy layouts (tens to low hundreds of points).
    """
    n = len(points)
    if n <= 2:
        return list(range(n))

    # Find candidate start indices (corners + centroid)
    xs = [p["x_um"] for p in points]
    ys = [p["y_um"] for p in points]
    cx, cy = sum(xs) / n, sum(ys) / n

    candidates = set()
    candidates.add(min(range(n), key=lambda i: xs[i] + ys[i]))          # top-left
    candidates.add(min(range(n), key=lambda i: xs[i] - ys[i]))          # bottom-left
    candidates.add(min(range(n), key=lambda i: -xs[i] + ys[i]))         # top-right
    candidates.add(min(range(n), key=lambda i: -xs[i] - ys[i]))         # bottom-right
    candidates.add(min(range(n), key=lambda i: (xs[i]-cx)**2 + (ys[i]-cy)**2))  # center

    best_path = None
    best_dist = float("inf")

    for start in candidates:
        path = _nearest_neighbor_tsp(points, start)
        path = _two_opt_improve(points, path)
        d = sum(
            _euclidean_distance(points[path[i]], points[path[i + 1]])
            for i in range(len(path) - 1)
        )
        if d < best_dist:
            best_dist = d
            best_path = path

    return best_path or list(range(n))


def _solve_tsp(points: List[Dict[str, Any]]) -> List[int]:
    """
    Solve TSP using OR-Tools if available, otherwise fall back to
    multi-start nearest-neighbor + 2-opt.
    """
    global _TSP_SOLVER_MSG_SHOWN
    if not _TSP_SOLVER_MSG_SHOWN:
        if ORTOOLS_AVAILABLE:
            print("  Ã¢â€žÂ¹ TSP solver: Google OR-Tools")
        else:
            print("  Ã¢â€žÂ¹ TSP solver: built-in (multi-start NN + 2-opt)")
            print("    For potentially better results: pip install ortools")
        _TSP_SOLVER_MSG_SHOWN = True

    if ORTOOLS_AVAILABLE:
        return _solve_tsp_ortools(points)
    else:
        return _solve_tsp_builtin(points)


# Ã¢â€â‚¬Ã¢â€â‚¬ Public ordering API Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def order_points(
    points: List[Dict[str, Any]],
    strategy: OrderStrategy = "shortest_path",
) -> List[int]:
    """
    Return an index list that reorders *points* according to *strategy*.

    Every point is included exactly once in the output.

    Strategies:
        rowwise              Ã¢â‚¬â€œ leftÃ¢â€ â€™right, topÃ¢â€ â€™bottom
        rowwise_meandering   Ã¢â‚¬â€œ snake pattern by rows
        columnwise           Ã¢â‚¬â€œ topÃ¢â€ â€™bottom, leftÃ¢â€ â€™right
        columnwise_meandering Ã¢â‚¬â€œ snake pattern by columns
        shortest_path        Ã¢â‚¬â€œ TSP (OR-Tools), minimises total travel
        random               Ã¢â‚¬â€œ random order
    """
    if not points:
        return []

    if strategy == "rowwise":
        return _order_rowwise(points, meandering=False)
    elif strategy == "rowwise_meandering":
        return _order_rowwise(points, meandering=True)
    elif strategy == "columnwise":
        return _order_columnwise(points, meandering=False)
    elif strategy == "columnwise_meandering":
        return _order_columnwise(points, meandering=True)
    elif strategy == "shortest_path":
        return _solve_tsp(points)
    elif strategy == "random":
        idx = list(range(len(points)))
        _random.shuffle(idx)
        return idx
    else:
        raise ValueError(
            f"Unknown ordering strategy '{strategy}'. "
            f"Choose from: {ALL_ORDER_STRATEGIES}"
        )


def calculate_acquisition_order(
    focus_points: List[Dict[str, Any]],
    strategy: OrderStrategy = "shortest_path",
    # Legacy parameters kept for backwards compatibility
    start_strategy: str | None = None,
    optimize: bool = True,
) -> List[Dict[str, Any]]:
    """
    Calculate optimal visiting order for focus points.

    All enabled focus points are included in the result.

    Args:
        focus_points: List of focus points with x_um, y_um coordinates.
        strategy: Ordering strategy (see ``order_points`` for options).
        start_strategy: *Deprecated* Ã¢â‚¬â€œ ignored, kept for backward compat.
        optimize: *Deprecated* Ã¢â‚¬â€œ ignored, kept for backward compat.

    Returns:
        List of focus points in visiting order with ``acquisition_order`` field.
    """
    if not focus_points:
        return []

    enabled = [fp for fp in focus_points if fp.get("enabled", True)]
    if not enabled:
        return []

    idx_order = order_points(enabled, strategy)

    ordered: list[dict] = []
    for order, idx in enumerate(idx_order):
        pt = deepcopy(enabled[idx])
        pt["acquisition_order"] = order
        pt["z_measured"] = False
        ordered.append(pt)

    return ordered


def order_groups(
    positions: Dict[str, Dict[str, Any]],
    strategy: OrderStrategy = "shortest_path",
) -> List[str]:
    """
    Return group IDs in the requested order (based on group centroids).

    All groups are included.
    """
    if not positions:
        return []

    # Build centroid pseudo-points
    centroids: list[dict] = []
    gids: list[str] = []
    for gid, group in positions.items():
        tiles = group.get("tiles", group.get("positions", []))
        if not tiles:
            continue
        cx = sum(t["x_um"] for t in tiles) / len(tiles)
        cy = sum(t["y_um"] for t in tiles) / len(tiles)
        centroids.append({"x_um": cx, "y_um": cy})
        gids.append(gid)

    idx_order = order_points(centroids, strategy)
    return [gids[i] for i in idx_order]


def order_tiles_in_group(
    group: Dict[str, Any],
    strategy: OrderStrategy = "shortest_path",
) -> List[int]:
    """
    Return tile indices within a group in the requested order.

    All tiles are included.
    """
    tiles = group.get("tiles", group.get("positions", []))
    return order_points(tiles, strategy)


def calculate_total_travel_distance(ordered_points: List[Dict[str, Any]]) -> float:
    """Total Euclidean travel distance in Ã‚Âµm for an ordered sequence."""
    if len(ordered_points) < 2:
        return 0.0
    return sum(
        _euclidean_distance(ordered_points[i], ordered_points[i + 1])
        for i in range(len(ordered_points) - 1)
    )


# Ã¢â€ÂÃ¢â€ÂÃ¢â€Â LAS X API Client Wrapper Ã¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€Â

class LasXClient:
    """
    Thread-safe LAS X API client with automatic reconnection.

    Usage::

        lasx = LasXClient("PythonClient", max_retries=3)
        client = lasx.client          # raw API handle
        result = lasx.execute_with_retry(some_function, arg1, arg2)
    """

    def __init__(self, client_name: str = "PythonClient", max_retries: int = 3):
        self.client_name = client_name
        self.max_retries = max_retries
        self.client = None
        self._lock = threading.Lock()
        self.connect()

    # Ã¢â€â‚¬Ã¢â€â‚¬ Connection management Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    def connect(self):
        """Connect (or reconnect) to LAS X, closing any existing connection."""
        with self._lock:
            if self.client is not None:
                try:
                    self.client.Disconnect()
                except Exception:
                    pass
                time.sleep(0.5)

            from LasxApi import PYLICamApiConnector as lasxApi

            self.client = lasxApi.LasxApiClientPyModel
            confirmed = self.client.Connect(self.client_name)
            if not confirmed:
                raise ConnectionError("Failed to connect to LAS X")

            # Configure
            self.client.PyApiClient.DelayInMilliseconds = 300
            mode = self.client.PyApiSetApiInterfaceToUse.Model.ApiInterfaceToUse
            self.client.PyApiSetApiInterfaceToUse.Model.ApiInterfaceToUse = (
                type(mode).Only_the_CAM_interface_is_used
            )
            self.client.PyApiSetApiInterfaceToUse.UpdateSync(10)

        # Verify the connection actually works
        self.ping()

        return self.client

    def ping(self, timeout: float = 5.0) -> bool:
        """
        Verify the API connection is alive by reading the scan status.

        Raises ConnectionError if unresponsive.
        """
        import concurrent.futures

        def _read_status():
            return str(self.client.PyApiStatusScan.Model.ScanStatus)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_read_status)
            try:
                status = future.result(timeout=timeout)
                print(f"  Ã¢Å“â€œ LAS X ping OK (scan status: {status})")
                return True
            except concurrent.futures.TimeoutError:
                raise ConnectionError(
                    f"LAS X connection ping timed out after {timeout}s Ã¢â‚¬â€ "
                    "API is connected but not responding. "
                    "Check that LAS X is running and not busy."
                )

    def disconnect(self):
        """Gracefully disconnect."""
        with self._lock:
            if self.client is not None:
                try:
                    self.client.Disconnect()
                except Exception:
                    pass
                self.client = None

    # Ã¢â€â‚¬Ã¢â€â‚¬ Retry wrapper Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    def execute_with_retry(self, func: Callable, *args, **kwargs):
        """Execute *func* with serialised API access and auto-reconnect."""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                with self._lock:
                    return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                print(f"  Ã¢Å¡Â  Attempt {attempt + 1}/{self.max_retries} failed: {e}")
                if attempt < self.max_retries - 1:
                    print("  Reconnecting...")
                    time.sleep(1.0)
                    self.connect()
        raise last_error  # type: ignore[misc]


# Legacy helper Ã¢â‚¬â€ kept for backward compatibility
def connect_to_lasx(client_name: str = "PythonClient"):
    """Legacy connect function.  Prefer ``LasXClient`` instead."""
    from LasxApi import PYLICamApiConnector as lasxApi

    client = lasxApi.LasxApiClientPyModel
    confirmed = client.Connect(client_name)
    if not confirmed:
        raise ConnectionError("Failed to connect to LAS X")

    client.PyApiClient.DelayInMilliseconds = 300
    mode = client.PyApiSetApiInterfaceToUse.Model.ApiInterfaceToUse
    client.PyApiSetApiInterfaceToUse.Model.ApiInterfaceToUse = (
        type(mode).Only_the_CAM_interface_is_used
    )
    client.PyApiSetApiInterfaceToUse.UpdateSync(10)
    return client


# Ã¢â€ÂÃ¢â€ÂÃ¢â€Â LAS X Hardware Runner Ã¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€Â


# â”â”â” Position Readback â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

@dataclass
class PositionReadback:
    """Result of a stage move with optional before/after position verification."""
    confirmed: bool
    target_x: Optional[float] = None
    target_y: Optional[float] = None
    target_z: Optional[float] = None
    before_x: Optional[float] = None
    before_y: Optional[float] = None
    before_z: Optional[float] = None
    after_x: Optional[float] = None
    after_y: Optional[float] = None
    after_z: Optional[float] = None

    @property
    def error_x(self) -> Optional[float]:
        if self.after_x is not None and self.target_x is not None:
            return abs(self.after_x - self.target_x)
        return None

    @property
    def error_y(self) -> Optional[float]:
        if self.after_y is not None and self.target_y is not None:
            return abs(self.after_y - self.target_y)
        return None

    @property
    def error_z(self) -> Optional[float]:
        if self.after_z is not None and self.target_z is not None:
            return abs(self.after_z - self.target_z)
        return None


class LasXAutofocusRunner:
    """
    Wrapper for LAS X hardware operations (stage moves, AF, image save).

    All methods are synchronous and wait for completion.
    Set ``verbose=True`` for per-call diagnostics (helps find hangs).
    """

    def __init__(self, client, af_job_name: str = "AF Job", verbose: bool = True):
        self.client = client
        self.af_job_name = af_job_name
        self.verbose = verbose

    def _log(self, msg: str):
        if self.verbose:
            import sys
            print(f"    [HW] {msg}", flush=True)
            sys.stdout.flush()

    # â€”â€” Position readout â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”
    def get_xy_position(self, timeout: int = 15) -> Tuple[float, float]:
        """
        Read current XY stage position in Âµm.

        Uses PyApiCommand "GetXY" to query the hardware.
        """
        self._log("reading XY position ...")
        self.client.PyApiCommand.Model.Command = "GetXY"
        confirmed = self.client.PyApiCommand.UpdateSync(timeout)

        if self.client.PyApiCommandEcho.Model.HasError:
            error_msg = self.client.PyApiCommandEcho.Model.Error
            raise RuntimeError(f"GetXY failed: {error_msg}")

        x = float(self.client.PyApiGetXY.Model.XPosition) * 1e6  # m â†’ Âµm
        y = float(self.client.PyApiGetXY.Model.YPosition) * 1e6  # m â†’ Âµm
        self._log(f"XY = ({x:.1f}, {y:.1f}) Âµm [{'OK' if confirmed else 'Timeout'}]")
        return (x, y)

    def get_z_position(
        self, job_name: str | None = None, use_galvo: bool = True,
    ) -> float:
        """
        Read current Z position in Âµm for a specific job.

        Args:
            job_name: Job to query Z for (defaults to af_job_name).
            use_galvo: Read galvo-Z (True) or wide-Z (False).
        """
        import json as _json

        job = job_name or self.af_job_name
        self._log(f"reading Z position (job={job}) ...")
        self.client.PyApiGetJobSettingsByName.Model.JobName = job
        self.client.PyApiGetJobSettingsByName.UpdateAsync()
        self.client.PyApiCommand.Model.Command = "GetJobSettingsByName"
        self.client.PyApiCommand.UpdateAsync()

        # Wait for async result
        time.sleep(0.5)

        settings = self.client.PyApiGetJobSettingsByName.Model.Settings
        if isinstance(settings, str):
            settings = _json.loads(settings)

        z_key = "z-galvo" if use_galvo else "z-wide"
        try:
            z = float(settings["zPosition"][z_key]["position"])
            self._log(f"Z = {z:.2f} Âµm ({z_key})")
            return z
        except (KeyError, TypeError) as e:
            raise ValueError(
                f"Could not extract Z position from settings: {e}\n"
                f"Settings: {settings}"
            )

    # â€”â€” Stage movement â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”
    def move_stage_xy(
        self, x_um: float, y_um: float,
        timeout: int = 10, verify: bool = True,
        tolerance_um: float = 1.0,
    ) -> PositionReadback:
        """
        Move XY stage to absolute position.

        Args:
            x_um, y_um: Target position in Âµm.
            timeout: Timeout for the move command.
            verify: If True, read position before and after move.
            tolerance_um: Position error threshold for warnings.

        Returns:
            PositionReadback with before/after positions and confirmation.
        """
        readback = PositionReadback(confirmed=False, target_x=x_um, target_y=y_um)

        if verify:
            try:
                bx, by = self.get_xy_position()
                readback.before_x, readback.before_y = bx, by
            except Exception as e:
                self._log(f"âš  XY readout before move failed: {e}")

        self._log(f"move XY â†’ ({x_um:.1f}, {y_um:.1f}) Âµm ...")
        self.client.PyApiMoveHardwareXY.Model.RelativePosition = False
        self.client.PyApiMoveHardwareXY.Model.XPosition = x_um
        self.client.PyApiMoveHardwareXY.Model.YPosition = y_um
        self.client.PyApiMoveHardwareXY.Model.MoveXyMode = type(
            self.client.PyApiMoveHardwareXY.Model.MoveXyMode
        ).eMoveXY
        self.client.PyApiMoveHardwareXY.Model.Units = type(
            self.client.PyApiMoveHardwareXY.Model.Units
        ).eMicrons
        readback.confirmed = self.client.PyApiMoveHardwareXY.UpdateSync(timeout)
        self._log(f"move XY done (confirmed={readback.confirmed})")

        if verify:
            try:
                ax, ay = self.get_xy_position()
                readback.after_x, readback.after_y = ax, ay
                ex = readback.error_x
                ey = readback.error_y
                if ex is not None and ey is not None:
                    if ex > tolerance_um or ey > tolerance_um:
                        self._log(
                            f"âš  Position error: "
                            f"Î”x={ex:.2f} Âµm, Î”y={ey:.2f} Âµm "
                            f"(tolerance={tolerance_um:.1f} Âµm)"
                        )
            except Exception as e:
                self._log(f"âš  XY readout after move failed: {e}")

        return readback

    def move_stage_z(
        self, z_um: float, job_name: str | None = None,
        use_galvo: bool = True, timeout: int = 30,
        verify: bool = True, tolerance_um: float = 0.5,
    ) -> PositionReadback:
        """
        Move Z stage to absolute position.

        Args:
            z_um: Target Z position in Âµm.
            job_name: Job name (defaults to af_job_name).
            use_galvo: Use galvo Z (True) or wide Z (False).
            timeout: Timeout for the move command.
            verify: If True, read Z before and after move.
            tolerance_um: Position error threshold for warnings.

        Returns:
            PositionReadback with before/after Z and confirmation.
        """
        job = job_name or self.af_job_name
        readback = PositionReadback(confirmed=False, target_z=z_um)

        if verify:
            try:
                readback.before_z = self.get_z_position(
                    job_name=job, use_galvo=use_galvo,
                )
            except Exception as e:
                self._log(f"âš  Z readout before move failed: {e}")

        self._log(f"move Z â†’ {z_um:.2f} Âµm (job={job}, galvo={use_galvo}) ...")
        self.client.PyApiMoveZByJobName.Model.JobName = job
        self.client.PyApiMoveZByJobName.Model.RelativePosition = False
        self.client.PyApiMoveZByJobName.Model.ZPosition = z_um
        mode_type = type(self.client.PyApiMoveZByJobName.Model.ZUseMode)
        self.client.PyApiMoveZByJobName.Model.ZUseMode = (
            mode_type.eUseGalvo if use_galvo else mode_type.eUseWide
        )
        self.client.PyApiMoveZByJobName.Model.Units = type(
            self.client.PyApiMoveZByJobName.Model.Units
        ).eMicrons
        readback.confirmed = self.client.PyApiMoveZByJobName.UpdateSync(timeout)
        self._log(f"move Z done (confirmed={readback.confirmed})")

        if verify:
            try:
                readback.after_z = self.get_z_position(
                    job_name=job, use_galvo=use_galvo,
                )
                ez = readback.error_z
                if ez is not None and ez > tolerance_um:
                    self._log(
                        f"âš  Z position error: "
                        f"Î”z={ez:.2f} Âµm (tolerance={tolerance_um:.1f} Âµm)"
                    )
            except Exception as e:
                self._log(f"âš  Z readout after move failed: {e}")

        return readback


    # â€”â€” Autofocus / Acquisition â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”â€”
    def run_autofocus(self, timeout: int = 30) -> bool:
        self._log(f"autofocus (job={self.af_job_name}) ...")
        self.client.PyApiAcquireJob.Model.JobName = self.af_job_name
        confirmed = self.client.PyApiAcquireJob.UpdateSync(timeout)
        self._log(f"acquire returned (confirmed={confirmed}), waiting for idle ...")
        self.wait_for_idle()
        self._log("autofocus done")
        return confirmed

    def acquire_job(self, job_name: str, timeout: int = 30) -> bool:
        self._log(f"acquire job '{job_name}' ...")
        self.client.PyApiAcquireJob.Model.JobName = job_name
        confirmed = self.client.PyApiAcquireJob.UpdateSync(timeout)
        self._log(f"acquire returned (confirmed={confirmed}), waiting for idle ...")
        self.wait_for_idle()
        self._log("acquire done")
        return confirmed

    def wait_for_idle(self, poll_interval: float = 0.2, max_wait: float = 120):
        """Block until scan status is idle (with timeout)."""
        start = time.time()
        last_status = None
        while True:
            try:
                status = str(self.client.PyApiStatusScan.Model.ScanStatus)
            except Exception as e:
                self._log(f"\u26a0 ScanStatus read failed: {e}")
                status = "ERROR"

            if status != last_status:
                self._log(f"scan status: {status}")
                last_status = status

            if status == "ScanIsIdle":
                return

            elapsed = time.time() - start
            if elapsed > max_wait:
                raise TimeoutError(
                    f"Timed out after {elapsed:.0f}s waiting for idle "
                    f"(last status: {status})"
                )
            time.sleep(poll_interval)

    # Ã¢â€â‚¬Ã¢â€â‚¬ Image saving Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    def save_current_image(
        self,
        output_dir: str,
        format: str = "OMETIFF",
        timeout: int = 30,
    ) -> bool:
        """
        Save the currently selected image.

        Uses the correct LAS X save pattern with trailing backslash.
        """
        self._log(f"saving image to {output_dir} ...")
        # LAS X requires Windows-style trailing backslash
        path = str(output_dir)
        if not path.endswith("\\"):
            path += "\\\\"

        save_model = self.client.PyApiSaveCurrentSelectedImage.Model
        save_model.FilePath = path

        fmt_type = type(save_model.FileFormat)
        fmt_map = {
            "OMETIFF": fmt_type.OMETIFF,
            "TIFF": fmt_type.TIFF,
            "PNG": fmt_type.PNG,
        }
        save_model.FileFormat = fmt_map.get(format.upper(), fmt_type.OMETIFF)
        save_model.MultiPageTiff = False
        save_model.AllImagesToSameDirectory = True
        save_model.ExportMetadata = True

        result = self.client.PyApiSaveCurrentSelectedImage.UpdateSync(timeout)
        self._log(f"save done (confirmed={result})")
        return result


# Ã¢â€ÂÃ¢â€ÂÃ¢â€Â Autofocus Sequence Ã¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€Â

def run_autofocus_sequence(
    ordered_points: List[Dict[str, Any]],
    client,
    af_job_name: str = "AF Job",
    progress_callback: Optional[Callable[[int, int, Dict], None]] = None,
    dry_run: bool = False,
    get_z_function: Optional[Callable[[], float]] = None,
) -> List[Dict[str, Any]]:
    """
    Run autofocus sequence on ordered focus points.

    The *progress_callback* receives ``(current, total, info_dict)`` where
    ``info_dict`` always contains ``"status"`` (one of ``"moving"``,
    ``"focusing"``, ``"complete"``) and ``"identifier"``.  On ``"complete"``
    it also contains ``"z_um"``.

    Returns list of points with measured Z values.
    """
    if dry_run:
        import random
        measured: list[dict] = []
        for i, point in enumerate(ordered_points):
            ident = point.get("identifier", f"#{i}")

            if progress_callback:
                progress_callback(i, len(ordered_points),
                                  {"status": "moving", "identifier": ident})

            mp = deepcopy(point)
            mp["z_um"] = (
                100.0
                + point["x_um"] * 0.001
                + point["y_um"] * 0.0005
                + random.uniform(-2, 2)
            )
            mp["z_measured"] = True
            measured.append(mp)

            if progress_callback:
                progress_callback(i + 1, len(ordered_points),
                                  {"status": "complete", "identifier": ident,
                                   "z_um": mp["z_um"]})
        return measured

    # Real hardware
    runner = LasXAutofocusRunner(client, af_job_name)
    measured = []

    for i, point in enumerate(ordered_points):
        ident = point.get("identifier", f"#{i}")

        if progress_callback:
            progress_callback(i, len(ordered_points),
                              {"status": "moving", "identifier": ident})

        runner.move_stage_xy(point["x_um"], point["y_um"])

        if progress_callback:
            progress_callback(i, len(ordered_points),
                              {"status": "focusing", "identifier": ident})

        success = runner.run_autofocus()
        if not success:
            print(f"  Ã¢Å¡Â  Autofocus failed at {ident}")

        z_um = get_z_function() if get_z_function else runner.get_z_position()

        mp = deepcopy(point)
        mp["z_um"] = z_um
        mp["z_measured"] = True
        measured.append(mp)

        if progress_callback:
            progress_callback(i + 1, len(ordered_points),
                              {"status": "complete", "identifier": ident,
                               "z_um": z_um})

    return measured


# Ã¢â€ÂÃ¢â€ÂÃ¢â€Â Image Acquisition Ã¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€Â

def acquire_all_positions(
    updated_positions: Dict[str, Dict[str, Any]],
    client,
    output_dir: str,
    image_format: str = "OMETIFF",
    use_galvo_z: bool = True,
    group_order: Optional[List[str]] = None,
    tile_strategy: OrderStrategy = "shortest_path",
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> List[str]:
    """
    Acquire images at all positions with interpolated Z values.

    Args:
        updated_positions: Positions with interpolated Z.
        client: Connected LAS X API client.
        output_dir: Directory to save images.
        image_format: "OMETIFF", "TIFF", or "PNG".
        use_galvo_z: Use galvo Z (True) or wide Z (False).
        group_order: Optional pre-computed group ordering.
        tile_strategy: Ordering strategy for tiles within each group.
        progress_callback: callback(current, total, message).

    Returns:
        List of saved image file paths.
    """
    from pathlib import Path

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    runner = LasXAutofocusRunner(client)
    saved_images: list[str] = []

    total_tiles = sum(len(g.get("tiles", [])) for g in updated_positions.values())
    current_tile = 0

    gids = group_order or list(updated_positions.keys())

    for gid in gids:
        group = updated_positions[gid]
        job_name = group["job_name"]
        tiles = group.get("tiles", [])

        tile_indices = order_tiles_in_group(group, tile_strategy)

        for tile_idx in tile_indices:
            tile = tiles[tile_idx]
            current_tile += 1

            if progress_callback:
                progress_callback(current_tile, total_tiles,
                                  f"Group {gid}, Tile {tile_idx}: Moving...")

            runner.move_stage_xy(tile["x_um"], tile["y_um"])

            if tile.get("z_interpolated", False) or tile.get("z_um", 0) != 0:
                runner.move_stage_z(tile["z_um"], job_name=job_name, use_galvo=use_galvo_z)

            if progress_callback:
                progress_callback(current_tile, total_tiles,
                                  f"Group {gid}, Tile {tile_idx}: Acquiring...")

            runner.acquire_job(job_name)

            # Save image with the correct LAS X pattern
            runner.save_current_image(str(output_path), format=image_format)

            filename = f"tile_{gid}_{tile_idx:04d}.ome.tiff"
            saved_images.append(str(output_path / filename))

            if progress_callback:
                progress_callback(current_tile, total_tiles,
                                  f"Group {gid}, Tile {tile_idx}: Ã¢Å“â€œ")

    return saved_images


# Ã¢â€ÂÃ¢â€ÂÃ¢â€Â Workflow Helpers Ã¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€Â

def create_workflow_dict(parsed_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create simplified workflow dict from parsed template data.
    """
    positions: dict[str, dict] = {}

    for gid, group in parsed_data.get("acquisition_positions", {}).items():
        positions[gid] = {
            "section_x": group.get("section_x"),
            "section_y": group.get("section_y"),
            "job_name": group["job_name"],
            "tile_size_um": group["tile_size_um"],
            "num_tiles": group["num_tiles"],
            "num_rows": group["num_rows"],
            "num_cols": group["num_cols"],
            "group_bounding_box": group["group_bounding_box"],
            "geometry_id": group.get("geometry_id"),
            "tiles": [
                {
                    "acquisition_order": pos["acquisition_order"],
                    "row": pos["row"],
                    "col": pos["col"],
                    "x_um": pos["x_um"],
                    "y_um": pos["y_um"],
                    "z_um": pos["z_um"],
                    "bounding_box": pos["bounding_box"],
                }
                for pos in group["positions"]
            ],
        }

    all_focus_points: list[dict] = []
    for fp in parsed_data.get("focus_points", []):
        all_focus_points.append({
            "identifier": fp["identifier"],
            "type": fp.get("type", "FocusPoint"),
            "x_um": fp["x_um"],
            "y_um": fp["y_um"],
            "z_um": fp.get("z_um", 0.0),
            "enabled": fp.get("enabled", True),
            "z_measured": False,
            "source": "focus_points",
        })
    for afp in parsed_data.get("autofocus_points", []):
        all_focus_points.append({
            "identifier": afp["identifier"],
            "type": afp.get("type", "AutoFocusPoint"),
            "x_um": afp["x_um"],
            "y_um": afp["y_um"],
            "z_um": afp.get("z_um", 0.0),
            "enabled": afp.get("enabled", True),
            "z_measured": False,
            "source": "autofocus_points",
        })

    return {
        "positions": positions,
        "focus_points": all_focus_points,
        "metadata": {
            "total_groups": len(positions),
            "total_tiles": sum(p["num_tiles"] for p in positions.values()),
            "total_focus_points": len(all_focus_points),
        },
    }


def assign_focus_points_to_groups(
    focus_points: List[Dict[str, Any]],
    positions: Dict[str, Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Assign focus points to their containing (or nearest) position group."""
    assignments: dict[str, list] = {gid: [] for gid in positions}

    for fp in focus_points:
        fx, fy = fp["x_um"], fp["y_um"]
        best_group = None
        best_dist = float("inf")

        # First try containing group
        for gid, group in positions.items():
            bb = group["group_bounding_box"]
            if (bb["x_min_um"] <= fx <= bb["x_max_um"]
                    and bb["y_min_um"] <= fy <= bb["y_max_um"]):
                cx = (bb["x_min_um"] + bb["x_max_um"]) / 2
                cy = (bb["y_min_um"] + bb["y_max_um"]) / 2
                dist = math.hypot(fx - cx, fy - cy)
                if dist < best_dist:
                    best_group = gid
                    best_dist = dist

        # Fall back to nearest
        if best_group is None:
            for gid, group in positions.items():
                bb = group["group_bounding_box"]
                cx = (bb["x_min_um"] + bb["x_max_um"]) / 2
                cy = (bb["y_min_um"] + bb["y_max_um"]) / 2
                dist = math.hypot(fx - cx, fy - cy)
                if dist < best_dist:
                    best_group = gid
                    best_dist = dist

        if best_group is not None:
            fp_copy = deepcopy(fp)
            fp_copy["assigned_group"] = best_group
            assignments[best_group].append(fp_copy)

    return assignments


# Ã¢â€ÂÃ¢â€ÂÃ¢â€Â Data Persistence Ã¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€Â

def save_workflow_state(
    output_dir: str,
    label: str,
    **data,
) -> str:
    """
    Save workflow state as JSON.  Always saves regardless of DRY_RUN.

    Returns the path to the saved file.
    """
    import json
    from pathlib import Path

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    filepath = out / f"{label}.json"

    # Make data JSON-serializable (handle numpy, etc.)
    def _default(obj):
        if hasattr(obj, "item"):   # numpy scalar
            return obj.item()
        if hasattr(obj, "tolist"):  # numpy array
            return obj.tolist()
        return str(obj)

    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=_default)

    return str(filepath)


# Ã¢â€ÂÃ¢â€ÂÃ¢â€Â CLI Ã¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€ÂÃ¢â€Â

if __name__ == "__main__":
    test_points = [
        {"identifier": "FP1", "x_um": 0,    "y_um": 0,    "z_um": 0, "enabled": True},
        {"identifier": "FP2", "x_um": 1000, "y_um": 0,    "z_um": 0, "enabled": True},
        {"identifier": "FP3", "x_um": 1000, "y_um": 1000, "z_um": 0, "enabled": True},
        {"identifier": "FP4", "x_um": 0,    "y_um": 1000, "z_um": 0, "enabled": True},
        {"identifier": "FP5", "x_um": 500,  "y_um": 500,  "z_um": 0, "enabled": True},
    ]

    for strat in ALL_ORDER_STRATEGIES:
        ordered = calculate_acquisition_order(test_points, strategy=strat)
        dist = calculate_total_travel_distance(ordered)
        path_ids = [p["identifier"] for p in ordered]
        print(f"{strat:>25s}: {' Ã¢â€ â€™ '.join(path_ids)}  ({dist:.0f} Ã‚Âµm)")
