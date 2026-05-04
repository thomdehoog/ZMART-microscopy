"""Compact workflow helpers for the user-facing smart microscopy notebook."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np

from . import (
    acquire,
    apply_lrp_change,
    find_scanning_templates_dir,
    get_job_settings,
    get_stage_limits,
    lrp_set_z_use_mode,
    lrp_verify_z_use_mode,
    make_changeable_copy,
    move_xy,
    move_z,
    parse_lrp,
    parse_template_positions,
    ping,
    restore_template,
    save_experiment,
    select_job,
    set_stage_limits,
    strip_template,
    synthesize_tiles,
)
from .scanning_template_parsers import _tile_size_from_image_size_str
from .scanning_templates import STRIPPED_XML, TEMPLATE_BASE, TEMPLATE_XML


@dataclass
class WorkflowConfig:
    acquisition_job: str = "Overview"
    af_job: str = "AF Job"
    stage_x_min_um: Optional[float] = None
    stage_x_max_um: Optional[float] = None
    stage_y_min_um: Optional[float] = None
    stage_y_max_um: Optional[float] = None
    limit_margin_um: float = 500
    z_galvo_min_um: float = -200
    z_galvo_max_um: float = 200
    z_wide_min_um: float = -5000
    z_wide_max_um: float = 5000
    restore_template_after_af: bool = True
    ask_before_acquire: bool = True


def require(condition: Any, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def connect_to_lasx(lasx_api_connector: Any) -> Tuple[Any, Any]:
    client = lasx_api_connector.LasxApiClientPyModel
    client.Connect("PythonClient")
    client.PyApiClient.DelayInMilliseconds = 300
    mode = client.PyApiSetApiInterfaceToUse.Model.ApiInterfaceToUse
    client.PyApiSetApiInterfaceToUse.Model.ApiInterfaceToUse = (
        type(mode).Only_the_CAM_interface_is_used
    )
    require(ping(client), "LAS X is not responding.")
    templates_dir = find_scanning_templates_dir()
    require(templates_dir, "Could not find the LAS X ScanningTemplates directory.")
    print(f"Connected to LAS X. Templates: {templates_dir}")
    return client, templates_dir


def validate_config(config: WorkflowConfig) -> None:
    xy_values = (
        config.stage_x_min_um,
        config.stage_x_max_um,
        config.stage_y_min_um,
        config.stage_y_max_um,
    )
    require(
        all(value is None for value in xy_values) or all(value is not None for value in xy_values),
        "Set all four XY stage limits, or leave all four as None.",
    )
    require(config.z_galvo_min_um < config.z_galvo_max_um, "Invalid z-galvo limits.")
    require(config.z_wide_min_um < config.z_wide_max_um, "Invalid wide-z limits.")


def prepare_template(client: Any, config: WorkflowConfig) -> Optional[Dict[str, float]]:
    validate_config(config)
    if _has_configured_xy_limits(config):
        stage_limits = _set_stage_limits_from_config(config)
        print_stage_limits(stage_limits, "Stage limits from config")
    else:
        stage_limits = None
        print("XY stage limits will be derived from the scan field in Step 2.")

    strip_result = strip_template(client)
    require(strip_result, "Could not strip the template.")
    print("Template stripped. Draw the scan field in Navigator Expert, then run Step 2.")
    _ensure_z_galvo_template(client)
    return stage_limits


def read_scan_field(
    client: Any,
    templates_dir: Any,
    config: WorkflowConfig,
    stage_limits: Optional[Dict[str, float]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, float]]:
    validate_config(config)
    scan_data = _save_and_parse_template(client, templates_dir)
    scan_data, tile_positions = _get_tile_positions(client, scan_data, config.acquisition_job)
    require(
        tile_positions,
        "No scan tiles found. Draw a scan field in Navigator Expert, then rerun this cell.",
    )

    print_scan_summary(tile_positions)

    if stage_limits is None:
        if _has_configured_xy_limits(config):
            stage_limits = _set_stage_limits_from_config(config)
            print_stage_limits(stage_limits, "Stage limits from config")
        else:
            stage_limits = _set_stage_limits_from_tiles(tile_positions, config)
            print_stage_limits(
                stage_limits,
                f"Stage limits from scan field + {config.limit_margin_um:g} um margin",
            )
    else:
        print_stage_limits(stage_limits, "Stage limits")

    return scan_data, tile_positions, stage_limits


def plot_scan_layout(
    scan_data: Dict[str, Any],
    tile_positions: Dict[str, Any],
    stage_limits: Optional[Dict[str, float]] = None,
    title: str = "Acquisition Layout",
    fit_to_stage_limits: bool = True,
) -> None:
    figsize = _figure_size_for_stage_limits(stage_limits) if fit_to_stage_limits else (14, 10)
    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#f5f5f8")

    all_x: List[float] = []
    all_y: List[float] = []
    tile_colors = scan_data.get("visualization_data", {}).get("tile_colors", {})
    job_colors = {
        region["job_name"]: tuple(tile_colors[region["job_name"]])
        for region in tile_positions.values()
        if region["job_name"] in tile_colors
    }
    legend_jobs = set()

    for _, region in _sorted_region_items(tile_positions):
        job_name = region["job_name"]
        tile_size_um = region.get("tile_size_um")
        if tile_size_um is None:
            continue

        half = tile_size_um / 2
        rgba = job_colors.get(job_name, (0.78, 0.78, 0.78, 1.0))
        face = (rgba[0], rgba[1], rgba[2], 0.25)
        edge = (rgba[0], rgba[1], rgba[2], 0.80)

        for pos in region["positions"]:
            cx, cy = pos["x_um"], pos["y_um"]
            ax.add_patch(
                patches.Rectangle(
                    (cx - half, cy - half),
                    tile_size_um,
                    tile_size_um,
                    linewidth=0.6,
                    edgecolor=edge,
                    facecolor=face,
                    zorder=2,
                )
            )
            all_x.extend([cx - half, cx + half])
            all_y.extend([cy - half, cy + half])

        if job_name not in legend_jobs:
            label = "No job assigned" if job_name == "(unassigned)" else job_name
            ax.plot(
                [],
                [],
                "s",
                color=(rgba[0], rgba[1], rgba[2], 0.6),
                markersize=8,
                label=label,
            )
            legend_jobs.add(job_name)

    if stage_limits:
        ax.add_patch(
            patches.Rectangle(
                (stage_limits["x_min"], stage_limits["y_min"]),
                stage_limits["x_max"] - stage_limits["x_min"],
                stage_limits["y_max"] - stage_limits["y_min"],
                linewidth=1.0,
                edgecolor="#aaaaaa",
                facecolor="none",
                linestyle=(0, (5, 4)),
                zorder=1,
            )
        )
        ax.plot(
            [],
            [],
            ls=(0, (5, 4)),
            color="#aaaaaa",
            linewidth=1.0,
            label="Stage limits",
        )
        if fit_to_stage_limits:
            _print_scan_scale(tile_positions, stage_limits)

    if all_x and all_y:
        _draw_focus_points(ax, scan_data, all_x, all_y)
        if stage_limits and fit_to_stage_limits:
            _set_stage_limit_view(ax, stage_limits)
        else:
            _set_data_view(ax, all_x, all_y)

    ax.set_aspect("equal", adjustable="box")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_linewidth(0.8)
        spine.set_edgecolor("#cccccc")
    ax.set_title(title, fontsize=13, fontweight="bold", color="#222222", pad=12)
    ax.legend(
        loc="upper right",
        fontsize=9,
        facecolor="white",
        edgecolor="#cccccc",
        labelcolor="#444444",
    )
    plt.show()


def run_autofocus(
    client: Any,
    templates_dir: Any,
    tile_positions: Dict[str, Any],
    config: WorkflowConfig,
) -> Tuple[List[Dict[str, float]], Callable[[Any, Any], Any]]:
    scan_data = _save_and_parse_template(client, templates_dir)
    focus_positions = _collect_focus_positions(scan_data)
    require(
        focus_positions,
        "No focus map positions found. Add focus or autofocus points in "
        "Navigator Expert, then rerun this cell.",
    )

    print(f"Focus positions: {len(focus_positions)}")
    for index, point in enumerate(focus_positions, start=1):
        print(f"  {index}. x={point['x_um']:.1f}  y={point['y_um']:.1f} um")

    require(strip_template(client), "Could not strip the template for autofocus.")
    select_job(client, config.af_job)

    measured_z: List[Dict[str, float]] = []
    for index, point in enumerate(focus_positions, start=1):
        print(
            f"\n[{index}/{len(focus_positions)}] "
            f"x={point['x_um']:.0f}  y={point['y_um']:.0f}",
            end="",
            flush=True,
        )
        move_xy(client, point["x_um"], point["y_um"])
        result = acquire(client, config.af_job)
        require(result and result.get("success"), f"Autofocus failed at point {index}.")
        settings = get_job_settings(client, config.af_job)
        z_um = make_changeable_copy(settings)["zPosition"]["z-galvo"]
        measured_z.append({**point, "z_um": z_um})
        print(f"  z={z_um:.2f} um")

    if config.restore_template_after_af:
        require(restore_template(client), "Could not restore the template after autofocus.")

    interpolate_z = _fit_z_plane(measured_z)
    return measured_z, interpolate_z


def plot_focus_plane(
    measured_points: List[Dict[str, float]],
    tile_positions: Dict[str, Any],
    interpolate_z: Callable[[Any, Any], Any],
) -> None:
    xs = np.array([p["x_um"] for p in measured_points])
    ys = np.array([p["y_um"] for p in measured_points])
    zs = np.array([p["z_um"] for p in measured_points])

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    ax = axes[0]
    sc = ax.scatter(xs, ys, c=zs, cmap="coolwarm", s=200, edgecolors="k")
    for point in measured_points:
        ax.annotate(
            f"{point['z_um']:.2f}",
            (point["x_um"], point["y_um"]),
            textcoords="offset points",
            xytext=(8, 8),
            fontsize=8,
        )
    plt.colorbar(sc, ax=ax, label="Z (um)")
    ax.set_xlabel("X (um)")
    ax.set_ylabel("Y (um)")
    ax.set_title("Measured Focus Points")
    ax.set_aspect("equal")
    ax.invert_yaxis()

    ax = axes[1]
    tile_x = [p["x_um"] for r in tile_positions.values() for p in r["positions"]]
    tile_y = [p["y_um"] for r in tile_positions.values() for p in r["positions"]]
    if tile_x and tile_y:
        margin = 50
        xi = np.linspace(min(tile_x) - margin, max(tile_x) + margin, 100)
        yi = np.linspace(min(tile_y) - margin, max(tile_y) + margin, 100)
        grid_x, grid_y = np.meshgrid(xi, yi)
        cf = ax.contourf(
            grid_x,
            grid_y,
            interpolate_z(grid_x, grid_y),
            levels=20,
            cmap="coolwarm",
        )
        plt.colorbar(cf, ax=ax, label="Z (um)")
        ax.scatter(xs, ys, c="k", marker="*", s=100, zorder=5, label="Focus points")
        ax.plot(tile_x, tile_y, ".", color="gray", markersize=2, label="Tiles")
        ax.legend(fontsize=8)
    ax.set_xlabel("X (um)")
    ax.set_ylabel("Y (um)")
    ax.set_title("Interpolated Z Surface")
    ax.set_aspect("equal")
    ax.invert_yaxis()

    plt.tight_layout()
    plt.show()


def acquire_tiles(
    client: Any,
    tile_positions: Dict[str, Any],
    interpolate_z: Callable[[Any, Any], Any],
    config: WorkflowConfig,
) -> List[Dict[str, Any]]:
    sequence = _build_acquisition_sequence(tile_positions, interpolate_z)
    require(sequence, "No acquisition positions available.")
    print(f"Acquiring {len(sequence)} positions with '{config.acquisition_job}'.")
    _confirm_acquisition(sequence, config)

    require(strip_template(client), "Could not strip the template for acquisition.")
    select_job(client, config.acquisition_job)

    results = []
    for index, position in enumerate(sequence, start=1):
        print(
            f"[{index}/{len(sequence)}] R{position['region']}  "
            f"x={position['x_um']:.0f}  y={position['y_um']:.0f}  "
            f"z={position['z_um']:.2f}",
            end="",
            flush=True,
        )
        move_xy(client, position["x_um"], position["y_um"])
        move_z(client, config.acquisition_job, position["z_um"], z_mode="galvo")
        result = acquire(client, config.acquisition_job)
        success = bool(result and result.get("success"))
        elapsed = result.get("timing", {}).get("total_s", 0) if result else 0
        results.append({**position, "success": success})
        print(f"  {'OK' if success else 'FAIL'} ({elapsed:.1f}s)")

    ok = sum(result["success"] for result in results)
    print(f"\nDone: {ok}/{len(results)} successful")
    return results


def print_scan_summary(tile_positions: Dict[str, Any]) -> None:
    n_tiles = sum(len(region["positions"]) for region in tile_positions.values())
    print(f"Scan field: {len(tile_positions)} region(s), {n_tiles} tile(s)")
    for region_id, region in _sorted_region_items(tile_positions):
        print(
            f"  Region {region_id}: {region['job_name']}  "
            f"{region.get('num_rows', '?')}x{region.get('num_cols', '?')}  "
            f"tile={region.get('tile_size_um', '?')} um"
        )


def print_stage_limits(stage_limits: Dict[str, float], label: str = "Stage limits") -> None:
    print(label)
    print(f"  X: {stage_limits['x_min']:.0f} to {stage_limits['x_max']:.0f} um")
    print(f"  Y: {stage_limits['y_min']:.0f} to {stage_limits['y_max']:.0f} um")


def _figure_size_for_stage_limits(
    stage_limits: Optional[Dict[str, float]],
) -> Tuple[float, float]:
    if not stage_limits:
        return (14, 10)

    width = max(abs(stage_limits["x_max"] - stage_limits["x_min"]), 1.0)
    height = max(abs(stage_limits["y_max"] - stage_limits["y_min"]), 1.0)
    aspect = width / height

    max_width, max_height = 14.0, 10.0
    min_width, min_height = 6.0, 4.5
    if aspect >= max_width / max_height:
        return (max_width, max(min_height, max_width / aspect))
    return (max(min_width, max_height * aspect), max_height)


def _set_stage_limit_view(ax: Any, stage_limits: Dict[str, float]) -> None:
    x_min, x_max = stage_limits["x_min"], stage_limits["x_max"]
    y_min, y_max = stage_limits["y_min"], stage_limits["y_max"]
    width = max(abs(x_max - x_min), 1.0)
    height = max(abs(y_max - y_min), 1.0)
    pad_x = width * 0.03
    pad_y = height * 0.03
    ax.set_xlim(x_min - pad_x, x_max + pad_x)
    ax.set_ylim(y_max + pad_y, y_min - pad_y)


def _set_data_view(ax: Any, all_x: List[float], all_y: List[float]) -> None:
    width = max(max(all_x) - min(all_x), 1.0)
    height = max(max(all_y) - min(all_y), 1.0)
    pad_x = width * 0.05
    pad_y = height * 0.05
    ax.set_xlim(min(all_x) - pad_x, max(all_x) + pad_x)
    ax.set_ylim(max(all_y) + pad_y, min(all_y) - pad_y)


def _print_scan_scale(
    tile_positions: Dict[str, Any], stage_limits: Dict[str, float]
) -> None:
    tile_x: List[float] = []
    tile_y: List[float] = []
    for region in tile_positions.values():
        tile_size_um = region.get("tile_size_um")
        if tile_size_um is None:
            continue
        half = tile_size_um / 2
        for position in region["positions"]:
            tile_x.extend([position["x_um"] - half, position["x_um"] + half])
            tile_y.extend([position["y_um"] - half, position["y_um"] + half])

    if not tile_x or not tile_y:
        return

    stage_width = max(abs(stage_limits["x_max"] - stage_limits["x_min"]), 1.0)
    stage_height = max(abs(stage_limits["y_max"] - stage_limits["y_min"]), 1.0)
    tile_width = max(tile_x) - min(tile_x)
    tile_height = max(tile_y) - min(tile_y)
    print(
        "Scale frame: "
        f"stage {stage_width:.0f} x {stage_height:.0f} um; "
        f"scan field {tile_width:.0f} x {tile_height:.0f} um "
        f"({100 * tile_width / stage_width:.1f}% x "
        f"{100 * tile_height / stage_height:.1f}% of stage frame)"
    )


def _save_and_parse_template(client: Any, templates_dir: Any) -> Dict[str, Any]:
    saved = save_experiment(client, TEMPLATE_XML, templates_dir, timeout=60)
    require(saved, "Could not save the current LAS X experiment.")
    return parse_template_positions(templates_dir, TEMPLATE_BASE, client=client)


def _get_tile_positions(
    client: Any, scan_data: Dict[str, Any], acquisition_job: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    tile_positions = scan_data.get("acquisition_positions", {})
    if tile_positions:
        return scan_data, tile_positions

    geometries = scan_data.get("geometries", {})
    if not geometries:
        return scan_data, {}

    settings = get_job_settings(client, acquisition_job)
    tile_size_um = None
    if settings:
        tile_size_um = _tile_size_from_image_size_str(settings.get("imageSize", ""))
    require(
        tile_size_um,
        "No tile positions found and tile size could not be read from the job settings.",
    )

    scan_data = synthesize_tiles(scan_data, tile_size_um, job_name=acquisition_job)
    tile_positions = scan_data["acquisition_positions"]
    n_tiles = sum(len(region["positions"]) for region in tile_positions.values())
    print(f"Synthesized {n_tiles} tiles from Navigator geometries.")
    return scan_data, tile_positions


def _ensure_z_galvo_template(client: Any) -> None:
    def set_z_galvo(lrp_path: Any) -> None:
        parsed = parse_lrp(lrp_path)
        for job_name in parsed["jobs"]:
            lrp_set_z_use_mode(lrp_path, "z-galvo", job_name)

    def verify_z_galvo(lrp_path: Any) -> bool:
        parsed = parse_lrp(lrp_path)
        return all(
            lrp_verify_z_use_mode(lrp_path, "z-galvo", job_name)
            for job_name in parsed["jobs"]
        )

    result = apply_lrp_change(client, STRIPPED_XML, set_z_galvo, verify_fn=verify_z_galvo)
    require(result and result["success"], "Could not enforce z-galvo on all jobs.")
    print("z-galvo enforced on all jobs.")


def _has_configured_xy_limits(config: WorkflowConfig) -> bool:
    return all(
        value is not None
        for value in (
            config.stage_x_min_um,
            config.stage_x_max_um,
            config.stage_y_min_um,
            config.stage_y_max_um,
        )
    )


def _set_stage_limits_from_config(config: WorkflowConfig) -> Dict[str, float]:
    set_stage_limits(
        x_min=config.stage_x_min_um,
        x_max=config.stage_x_max_um,
        y_min=config.stage_y_min_um,
        y_max=config.stage_y_max_um,
        z_galvo_min=config.z_galvo_min_um,
        z_galvo_max=config.z_galvo_max_um,
        z_wide_min=config.z_wide_min_um,
        z_wide_max=config.z_wide_max_um,
    )
    return get_stage_limits()


def _set_stage_limits_from_tiles(
    tile_positions: Dict[str, Any], config: WorkflowConfig
) -> Dict[str, float]:
    centers_x = [p["x_um"] for r in tile_positions.values() for p in r["positions"]]
    centers_y = [p["y_um"] for r in tile_positions.values() for p in r["positions"]]
    require(centers_x and centers_y, "No tile positions available for stage limits.")
    tile_half = max((r.get("tile_size_um") or 0) for r in tile_positions.values()) / 2
    set_stage_limits(
        x_min=min(centers_x) - tile_half - config.limit_margin_um,
        x_max=max(centers_x) + tile_half + config.limit_margin_um,
        y_min=min(centers_y) - tile_half - config.limit_margin_um,
        y_max=max(centers_y) + tile_half + config.limit_margin_um,
        z_galvo_min=config.z_galvo_min_um,
        z_galvo_max=config.z_galvo_max_um,
        z_wide_min=config.z_wide_min_um,
        z_wide_max=config.z_wide_max_um,
    )
    return get_stage_limits()


def _collect_focus_positions(scan_data: Dict[str, Any]) -> List[Dict[str, float]]:
    return list(scan_data.get("focus_points", [])) or list(
        scan_data.get("autofocus_points", [])
    )


def _fit_z_plane(measured_points: List[Dict[str, float]]) -> Callable[[Any, Any], Any]:
    xs = np.array([p["x_um"] for p in measured_points])
    ys = np.array([p["y_um"] for p in measured_points])
    zs = np.array([p["z_um"] for p in measured_points])
    matrix = np.column_stack([xs, ys, np.ones(len(measured_points))])
    coeffs, *_ = np.linalg.lstsq(matrix, zs, rcond=None)

    def interpolate_z(x: Any, y: Any) -> Any:
        return coeffs[0] * x + coeffs[1] * y + coeffs[2]

    residuals = zs - np.array([interpolate_z(x, y) for x, y in zip(xs, ys)])
    print("Focus plane")
    print(f"  Z range:      {zs.max() - zs.min():.2f} um")
    print(f"  Tilt X:       {np.degrees(np.arctan(coeffs[0])):+.4f} deg")
    print(f"  Tilt Y:       {np.degrees(np.arctan(coeffs[1])):+.4f} deg")
    print(f"  Max residual: {np.max(np.abs(residuals)):.3f} um")
    return interpolate_z


def _build_acquisition_sequence(
    tile_positions: Dict[str, Any], interpolate_z: Callable[[Any, Any], Any]
) -> List[Dict[str, Any]]:
    sequence: List[Dict[str, Any]] = []
    for region_id, region in _sorted_region_items(tile_positions):
        rows: Dict[int, List[Dict[str, Any]]] = {}
        for position in region["positions"]:
            rows.setdefault(position["row"], []).append(position)
        for row_index in sorted(rows):
            row_tiles = sorted(rows[row_index], key=lambda p: p["col"])
            if row_index % 2 == 1:
                row_tiles = row_tiles[::-1]
            for position in row_tiles:
                sequence.append(
                    {
                        "region": region_id,
                        "x_um": position["x_um"],
                        "y_um": position["y_um"],
                        "z_um": interpolate_z(position["x_um"], position["y_um"]),
                    }
                )
    return sequence


def _confirm_acquisition(sequence: Iterable[Dict[str, Any]], config: WorkflowConfig) -> None:
    if not config.ask_before_acquire:
        return
    n_positions = len(list(sequence))
    answer = input(f"Type ACQUIRE to start {n_positions} positions: ").strip()
    require(answer == "ACQUIRE", "Acquisition cancelled.")


def _draw_focus_points(
    ax: Any, scan_data: Dict[str, Any], all_x: List[float], all_y: List[float]
) -> None:
    span = max(max(all_x) - min(all_x), max(all_y) - min(all_y))
    cross = span * 0.006
    circle_r = cross * 0.6

    focus_sets = [
        (scan_data.get("focus_points", []), "#4EB8B8", "Focus points"),
        (scan_data.get("autofocus_points", []), "#5CBF5C", "AutoFocus points"),
    ]
    for points, color, label in focus_sets:
        if not points:
            continue
        for point in points:
            fx, fy = point["x_um"], point["y_um"]
            ax.plot([fx - cross, fx + cross], [fy, fy], "-", color=color, linewidth=0.8)
            ax.plot([fx, fx], [fy - cross, fy + cross], "-", color=color, linewidth=0.8)
            ax.add_patch(
                patches.Circle(
                    (fx, fy),
                    circle_r,
                    linewidth=0.8,
                    edgecolor=color,
                    facecolor="none",
                    zorder=11,
                )
            )
            all_x.append(fx)
            all_y.append(fy)
        ax.plot([], [], "+", color=color, markersize=10, markeredgewidth=1.8, label=label)


def _sorted_region_items(regions: Dict[str, Any]) -> List[Tuple[str, Any]]:
    def key(item: Tuple[str, Any]) -> Tuple[int, Any]:
        region_id = item[0]
        try:
            return (0, int(region_id))
        except (TypeError, ValueError):
            return (1, str(region_id))

    return sorted(regions.items(), key=key)
