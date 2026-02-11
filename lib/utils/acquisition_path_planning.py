#!/usr/bin/env python3
"""
acquisition_path_planning.py

Vendor-agnostic utilities for acquisition path planning:
- Optimal path calculation (OR-Tools TSP solver)
- Multiple ordering strategies (rowwise, meandering, shortest_path, etc.)
- Workflow data structures and persistence

For Leica LAS X hardware control, see ``vendors.lasx.autofocus``.

Usage:
    from utils.acquisition_path_planning import (
        calculate_acquisition_order,
        order_points,
        order_groups,
        order_tiles_in_group,
        PositionReadback,
        create_workflow_dict,
        assign_focus_points_to_groups,
        save_workflow_state,
    )
"""

import math
import random as _random
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Literal
from copy import deepcopy

# OR-Tools for production-grade TSP solving (optional)
try:
    from ortools.constraint_solver import routing_enums_pb2, pywrapcp
    ORTOOLS_AVAILABLE = True
except ImportError:
    ORTOOLS_AVAILABLE = False

_TSP_SOLVER_MSG_SHOWN = False


# ━━━ Ordering Strategies ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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


# —— Row / Column helpers ——————————————————————————————————————————————————————

def _assign_grid_indices(
    points: List[Dict[str, Any]],
    axis: str,
    tolerance_fraction: float = 0.3,
) -> List[int]:
    """
    Assign row or column indices by clustering coordinates.

    *axis* is ``'y'`` for rows (group by Y) or ``'x'`` for columns.
    Points within *tolerance_fraction* \u00d7 median spacing are put in the same
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


# —— TSP solvers ———————————————————————————————————————————————————————————————

def _solve_tsp_ortools(points: List[Dict[str, Any]]) -> List[int]:
    """
    Solve the Travelling Salesman Problem using Google OR-Tools.

    Finds the order to visit **ALL** points exactly once that minimizes
    total travel distance (open-path TSP \u2014 no return to start).

    Returns:
        List of indices in optimal visiting order.
    """
    n = len(points)
    if n <= 1:
        return list(range(n))
    if n == 2:
        return [0, 1]

    # Build integer distance matrix (OR-Tools needs ints \u2014 scale \u00b5m to nm)
    SCALE = 1000  # \u00b5m \u2192 nm for integer precision
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

    # Search parameters \u2014 use multiple strategies for best result
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
    2-opt local search \u2014 runs until no improvement found (full sweep).

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
            print("  \u2139 TSP solver: Google OR-Tools")
        else:
            print("  \u2139 TSP solver: built-in (multi-start NN + 2-opt)")
            print("    For potentially better results: pip install ortools")
        _TSP_SOLVER_MSG_SHOWN = True

    if ORTOOLS_AVAILABLE:
        return _solve_tsp_ortools(points)
    else:
        return _solve_tsp_builtin(points)


# —— Public ordering API ———————————————————————————————————————————————————————

def order_points(
    points: List[Dict[str, Any]],
    strategy: OrderStrategy = "shortest_path",
) -> List[int]:
    """
    Return an index list that reorders *points* according to *strategy*.

    Every point is included exactly once in the output.

    Strategies:
        rowwise              \u2013 left\u2192right, top\u2192bottom
        rowwise_meandering   \u2013 snake pattern by rows
        columnwise           \u2013 top\u2192bottom, left\u2192right
        columnwise_meandering \u2013 snake pattern by columns
        shortest_path        \u2013 TSP (OR-Tools), minimises total travel
        random               \u2013 random order
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
        start_strategy: *Deprecated* \u2013 ignored, kept for backward compat.
        optimize: *Deprecated* \u2013 ignored, kept for backward compat.

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
    """Total Euclidean travel distance in \u00b5m for an ordered sequence."""
    if len(ordered_points) < 2:
        return 0.0
    return sum(
        _euclidean_distance(ordered_points[i], ordered_points[i + 1])
        for i in range(len(ordered_points) - 1)
    )


# ━━━ Position Readback ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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


# ━━━ Workflow Helpers ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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
            bb = group.get("group_bounding_box")
            if bb:
                inside = (bb["x_min_um"] <= fx <= bb["x_max_um"]
                          and bb["y_min_um"] <= fy <= bb["y_max_um"])
                if inside:
                    cx = (bb["x_min_um"] + bb["x_max_um"]) / 2
                    cy = (bb["y_min_um"] + bb["y_max_um"]) / 2
                    dist = math.hypot(fx - cx, fy - cy)
                    if dist < best_dist:
                        best_group = gid
                        best_dist = dist
            else:
                # Without bounding box, use centroid of tile positions
                tiles = group.get("positions", group.get("tiles", []))
                if tiles:
                    cx = sum(p["x_um"] for p in tiles) / len(tiles)
                    cy = sum(p["y_um"] for p in tiles) / len(tiles)
                    dist = math.hypot(fx - cx, fy - cy)
                    if dist < best_dist:
                        best_group = gid
                        best_dist = dist

        # Fall back to nearest centroid
        if best_group is None:
            for gid, group in positions.items():
                bb = group.get("group_bounding_box")
                if bb:
                    cx = (bb["x_min_um"] + bb["x_max_um"]) / 2
                    cy = (bb["y_min_um"] + bb["y_max_um"]) / 2
                else:
                    tiles = group.get("positions", group.get("tiles", []))
                    if not tiles:
                        continue
                    cx = sum(p["x_um"] for p in tiles) / len(tiles)
                    cy = sum(p["y_um"] for p in tiles) / len(tiles)
                dist = math.hypot(fx - cx, fy - cy)
                if dist < best_dist:
                    best_group = gid
                    best_dist = dist

        if best_group is not None:
            fp_copy = deepcopy(fp)
            fp_copy["assigned_group"] = best_group
            assignments[best_group].append(fp_copy)

    return assignments


# ━━━ Data Persistence ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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


# ━━━ CLI ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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
        print(f"{strat:>25s}: {' \u2192 '.join(path_ids)}  ({dist:.0f} \u00b5m)")
