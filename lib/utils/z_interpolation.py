#!/usr/bin/env python3
"""
z_interpolation.py

Z-surface interpolation for microscopy autofocus workflow.

Interpolates Z values from measured focus points to all tile positions.
Supports both global and per-group interpolation modes.

Usage:
    from utils.z_interpolation import interpolate_z_surface, update_positions_with_z
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional, Literal, Tuple
from copy import deepcopy

# Try to import scipy interpolation functions
try:
    from scipy.interpolate import griddata, Rbf, LinearNDInterpolator, NearestNDInterpolator
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("Warning: scipy not available. Using basic linear interpolation.")


# ─── Interpolation Methods ────────────────────────────────────────────────────

def _plane_fit(points: List[Dict[str, Any]]) -> Tuple[float, float, float]:
    """
    Fit a plane z = ax + by + c to the given points.
    
    Uses least squares fitting.
    
    Args:
        points: List of points with x_um, y_um, z_um
    
    Returns:
        Tuple (a, b, c) for plane equation z = ax + by + c
    """
    if len(points) < 3:
        # Not enough points for a plane, return flat at mean Z
        mean_z = sum(p["z_um"] for p in points) / len(points) if points else 0
        return (0.0, 0.0, mean_z)
    
    # Build matrices for least squares
    n = len(points)
    A = np.zeros((n, 3))
    b = np.zeros(n)
    
    for i, p in enumerate(points):
        A[i, 0] = p["x_um"]
        A[i, 1] = p["y_um"]
        A[i, 2] = 1.0
        b[i] = p["z_um"]
    
    # Solve using least squares
    try:
        result, residuals, rank, s = np.linalg.lstsq(A, b, rcond=None)
        return (result[0], result[1], result[2])
    except np.linalg.LinAlgError:
        mean_z = sum(p["z_um"] for p in points) / len(points)
        return (0.0, 0.0, mean_z)


def _interpolate_point_plane(x: float, y: float, plane: Tuple[float, float, float]) -> float:
    """Evaluate plane equation at a point."""
    a, b, c = plane
    return a * x + b * y + c


def _interpolate_basic(
    measured_points: List[Dict[str, Any]],
    target_x: float,
    target_y: float,
    method: str = 'idw'
) -> float:
    """
    Basic interpolation without scipy.
    
    Methods:
        'idw': Inverse distance weighting
        'nearest': Nearest neighbor
        'plane': Plane fit
    """
    if not measured_points:
        return 0.0
    
    if len(measured_points) == 1:
        return measured_points[0]["z_um"]
    
    if method == 'nearest':
        # Find nearest point
        best_dist = float('inf')
        best_z = 0.0
        for p in measured_points:
            dist = math.hypot(p["x_um"] - target_x, p["y_um"] - target_y)
            if dist < best_dist:
                best_dist = dist
                best_z = p["z_um"]
        return best_z
    
    elif method == 'plane':
        plane = _plane_fit(measured_points)
        return _interpolate_point_plane(target_x, target_y, plane)
    
    else:  # 'idw' (inverse distance weighting)
        weighted_sum = 0.0
        weight_total = 0.0
        power = 2.0  # IDW power parameter
        
        for p in measured_points:
            dist = math.hypot(p["x_um"] - target_x, p["y_um"] - target_y)
            if dist < 1e-9:  # Very close to a measured point
                return p["z_um"]
            weight = 1.0 / (dist ** power)
            weighted_sum += weight * p["z_um"]
            weight_total += weight
        
        return weighted_sum / weight_total if weight_total > 0 else 0.0


def _interpolate_scipy(
    measured_points: List[Dict[str, Any]],
    target_points: List[Tuple[float, float]],
    method: str = 'linear'
) -> np.ndarray:
    """
    Interpolate using scipy methods.
    
    Methods:
        'linear': Linear interpolation (griddata)
        'cubic': Cubic interpolation (griddata)
        'rbf': Radial basis function interpolation
        'nearest': Nearest neighbor
    """
    if not measured_points:
        return np.zeros(len(target_points))
    
    # Extract coordinates
    known_xy = np.array([[p["x_um"], p["y_um"]] for p in measured_points])
    known_z = np.array([p["z_um"] for p in measured_points])
    target_xy = np.array(target_points)
    
    if method == 'rbf':
        # Radial basis function - handles extrapolation well
        rbf = Rbf(known_xy[:, 0], known_xy[:, 1], known_z, function='multiquadric')
        return rbf(target_xy[:, 0], target_xy[:, 1])
    
    elif method in ('linear', 'cubic'):
        # griddata for linear/cubic
        result = griddata(known_xy, known_z, target_xy, method=method)
        
        # Handle NaN values (extrapolation) with nearest neighbor
        nan_mask = np.isnan(result)
        if np.any(nan_mask):
            nearest_result = griddata(known_xy, known_z, target_xy, method='nearest')
            result[nan_mask] = nearest_result[nan_mask]
        
        return result
    
    else:  # 'nearest'
        return griddata(known_xy, known_z, target_xy, method='nearest')


# ─── Main Interpolation Function ──────────────────────────────────────────────

def interpolate_z_surface(
    measured_points: List[Dict[str, Any]],
    positions: Dict[str, Dict[str, Any]],
    mode: Literal['global', 'per-group'] = 'per-group',
    method: str = 'linear',
    fallback_method: str = 'plane'
) -> Dict[str, Dict[str, float]]:
    """
    Interpolate Z values across the acquisition field.
    
    Args:
        measured_points: Focus points with measured Z values
        positions: Position groups from workflow_data['positions']
        mode: 'global' uses all points, 'per-group' uses only points within each group
        method: Interpolation method ('linear', 'cubic', 'rbf', 'idw', 'nearest', 'plane')
        fallback_method: Method to use when a group has insufficient points
    
    Returns:
        Dict mapping group_id -> {tile_index: z_value}
        
    Example:
        {
            "0": {0: 105.2, 1: 105.4, 2: 105.1, ...},
            "1": {0: 98.7, 1: 98.9, ...},
        }
    """
    z_surface = {}
    
    # Filter to measured points only
    measured = [p for p in measured_points if p.get("z_measured", False)]
    
    if not measured:
        print("Warning: No measured focus points. Returning zero Z values.")
        for gid, group in positions.items():
            z_surface[gid] = {i: 0.0 for i in range(len(group["tiles"]))}
        return z_surface
    
    if mode == 'global':
        # Use all measured points for all groups
        for gid, group in positions.items():
            z_surface[gid] = _interpolate_for_group(
                measured, group["tiles"], method, fallback_method
            )
    
    else:  # 'per-group'
        # Assign focus points to groups and interpolate per-group
        from .acquisition_path_planning import assign_focus_points_to_groups
        
        assignments = assign_focus_points_to_groups(measured, positions)
        
        for gid, group in positions.items():
            group_points = assignments.get(gid, [])
            
            if len(group_points) >= 3:
                # Enough points for interpolation within group
                z_surface[gid] = _interpolate_for_group(
                    group_points, group["tiles"], method, fallback_method
                )
            elif len(group_points) > 0:
                # Few points - use fallback method
                z_surface[gid] = _interpolate_for_group(
                    group_points, group["tiles"], fallback_method, 'nearest'
                )
            else:
                # No points in group - use global fallback
                z_surface[gid] = _interpolate_for_group(
                    measured, group["tiles"], fallback_method, 'nearest'
                )
    
    return z_surface


def _interpolate_for_group(
    measured_points: List[Dict[str, Any]],
    tiles: List[Dict[str, Any]],
    method: str,
    fallback_method: str
) -> Dict[int, float]:
    """
    Interpolate Z values for tiles in a single group.
    
    Returns dict mapping tile index to Z value.
    """
    if not tiles:
        return {}
    
    # Get target coordinates
    target_coords = [(t["x_um"], t["y_um"]) for t in tiles]
    
    # Choose interpolation based on scipy availability and method
    if SCIPY_AVAILABLE and method in ('linear', 'cubic', 'rbf', 'nearest'):
        try:
            z_values = _interpolate_scipy(measured_points, target_coords, method)
            return {i: float(z) for i, z in enumerate(z_values)}
        except Exception as e:
            print(f"Warning: scipy interpolation failed ({e}), using fallback")
    
    # Basic interpolation
    result = {}
    basic_method = method if method in ('idw', 'nearest', 'plane') else fallback_method
    
    for i, (tx, ty) in enumerate(target_coords):
        result[i] = _interpolate_basic(measured_points, tx, ty, basic_method)
    
    return result


def update_positions_with_z(
    positions: Dict[str, Dict[str, Any]],
    z_surface: Dict[str, Dict[int, float]]
) -> Dict[str, Dict[str, Any]]:
    """
    Update position tiles with interpolated Z values.
    
    Args:
        positions: Original positions dict from workflow_data
        z_surface: Interpolated Z values from interpolate_z_surface()
    
    Returns:
        Updated positions dict with Z values set
    """
    updated = deepcopy(positions)
    
    for gid, group in updated.items():
        group_z = z_surface.get(gid, {})
        
        for i, tile in enumerate(group["tiles"]):
            if i in group_z:
                tile["z_um"] = group_z[i]
                tile["z_interpolated"] = True
            else:
                tile["z_interpolated"] = False
    
    return updated


# ─── Analysis Functions ───────────────────────────────────────────────────────

def analyze_z_surface(
    z_surface: Dict[str, Dict[int, float]],
    positions: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Analyze the interpolated Z surface.
    
    Returns statistics about Z variation.
    """
    all_z = []
    group_stats = {}
    
    for gid, group_z in z_surface.items():
        z_values = list(group_z.values())
        all_z.extend(z_values)
        
        if z_values:
            group_stats[gid] = {
                "min_z_um": min(z_values),
                "max_z_um": max(z_values),
                "mean_z_um": sum(z_values) / len(z_values),
                "range_z_um": max(z_values) - min(z_values),
                "n_tiles": len(z_values),
            }
    
    global_stats = {}
    if all_z:
        global_stats = {
            "global_min_z_um": min(all_z),
            "global_max_z_um": max(all_z),
            "global_mean_z_um": sum(all_z) / len(all_z),
            "global_range_z_um": max(all_z) - min(all_z),
            "total_tiles": len(all_z),
        }
    
    return {
        "global": global_stats,
        "per_group": group_stats,
    }


def compute_z_gradient(
    z_surface: Dict[str, Dict[int, float]],
    positions: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Compute Z gradient (tilt) information.
    
    Fits a plane to each group and returns tilt angles.
    """
    gradients = {}
    
    for gid, group in positions.items():
        group_z = z_surface.get(gid, {})
        
        # Build points for plane fit
        points = []
        for i, tile in enumerate(group["tiles"]):
            if i in group_z:
                points.append({
                    "x_um": tile["x_um"],
                    "y_um": tile["y_um"],
                    "z_um": group_z[i]
                })
        
        if len(points) >= 3:
            a, b, c = _plane_fit(points)
            
            # Convert slopes to angles (degrees)
            tilt_x_deg = math.degrees(math.atan(a))
            tilt_y_deg = math.degrees(math.atan(b))
            
            gradients[gid] = {
                "slope_x_um_per_um": a,
                "slope_y_um_per_um": b,
                "intercept_z_um": c,
                "tilt_x_degrees": tilt_x_deg,
                "tilt_y_degrees": tilt_y_deg,
            }
    
    return gradients


# ─── Extrapolation Helpers ────────────────────────────────────────────────────

def check_extrapolation_risk(
    measured_points: List[Dict[str, Any]],
    positions: Dict[str, Dict[str, Any]],
    margin_factor: float = 0.1
) -> Dict[str, Any]:
    """
    Check for tiles that require extrapolation (outside measured point coverage).
    
    Args:
        measured_points: Measured focus points
        positions: Position groups
        margin_factor: Tolerance for boundary (fraction of range)
    
    Returns:
        Dict with extrapolation risk information
    """
    if not measured_points:
        return {"warning": "No measured points", "at_risk_tiles": []}
    
    # Get measured point bounds
    measured_x = [p["x_um"] for p in measured_points if p.get("z_measured", False)]
    measured_y = [p["y_um"] for p in measured_points if p.get("z_measured", False)]
    
    if not measured_x:
        return {"warning": "No measured points", "at_risk_tiles": []}
    
    x_min, x_max = min(measured_x), max(measured_x)
    y_min, y_max = min(measured_y), max(measured_y)
    
    # Add margin
    x_range = max(x_max - x_min, 1.0)
    y_range = max(y_max - y_min, 1.0)
    margin_x = x_range * margin_factor
    margin_y = y_range * margin_factor
    
    safe_x_min = x_min - margin_x
    safe_x_max = x_max + margin_x
    safe_y_min = y_min - margin_y
    safe_y_max = y_max + margin_y
    
    # Check each tile
    at_risk_tiles = []
    
    for gid, group in positions.items():
        for i, tile in enumerate(group["tiles"]):
            tx, ty = tile["x_um"], tile["y_um"]
            if not (safe_x_min <= tx <= safe_x_max and safe_y_min <= ty <= safe_y_max):
                at_risk_tiles.append({
                    "group_id": gid,
                    "tile_index": i,
                    "x_um": tx,
                    "y_um": ty,
                    "outside_x": tx < safe_x_min or tx > safe_x_max,
                    "outside_y": ty < safe_y_min or ty > safe_y_max,
                })
    
    return {
        "measured_bounds": {
            "x_min_um": x_min, "x_max_um": x_max,
            "y_min_um": y_min, "y_max_um": y_max,
        },
        "safe_bounds": {
            "x_min_um": safe_x_min, "x_max_um": safe_x_max,
            "y_min_um": safe_y_min, "y_max_um": safe_y_max,
        },
        "n_at_risk": len(at_risk_tiles),
        "n_total": sum(len(g["tiles"]) for g in positions.values()),
        "at_risk_tiles": at_risk_tiles,
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Test interpolation
    print("Testing Z interpolation...")
    
    # Create test measured points (tilted plane with some noise)
    measured = [
        {"identifier": "FP1", "x_um": 0, "y_um": 0, "z_um": 100.0, "z_measured": True},
        {"identifier": "FP2", "x_um": 1000, "y_um": 0, "z_um": 101.0, "z_measured": True},
        {"identifier": "FP3", "x_um": 1000, "y_um": 1000, "z_um": 102.5, "z_measured": True},
        {"identifier": "FP4", "x_um": 0, "y_um": 1000, "z_um": 101.5, "z_measured": True},
    ]
    
    # Create test positions
    positions = {
        "0": {
            "tiles": [
                {"x_um": 250, "y_um": 250},
                {"x_um": 500, "y_um": 250},
                {"x_um": 750, "y_um": 250},
                {"x_um": 250, "y_um": 500},
                {"x_um": 500, "y_um": 500},
                {"x_um": 750, "y_um": 500},
            ],
            "group_bounding_box": {
                "x_min_um": 0, "x_max_um": 1000,
                "y_min_um": 0, "y_max_um": 1000,
            }
        }
    }
    
    # Test global interpolation
    print("\nGlobal interpolation (linear):")
    z_surface = interpolate_z_surface(measured, positions, mode='global', method='linear')
    
    for gid, group_z in z_surface.items():
        print(f"  Group {gid}:")
        for i, z in group_z.items():
            tile = positions[gid]["tiles"][i]
            print(f"    Tile {i} ({tile['x_um']}, {tile['y_um']}): Z = {z:.2f} µm")
    
    # Analyze
    print("\nZ Surface Analysis:")
    analysis = analyze_z_surface(z_surface, positions)
    print(f"  Global range: {analysis['global']['global_range_z_um']:.2f} µm")
    
    # Gradient
    print("\nZ Gradient:")
    gradients = compute_z_gradient(z_surface, positions)
    for gid, grad in gradients.items():
        print(f"  Group {gid}: tilt_x = {grad['tilt_x_degrees']:.3f}°, tilt_y = {grad['tilt_y_degrees']:.3f}°")
