"""Validate the objective-pair XY calibration on the real stage.

The objective-pair calibration promises that a frame position means the
same physical spot under both objectives: when the notebook asks for
``(x, y)`` with the target objective, the driver applies the calibrated
translation so the same cells land in the field of view. This module
*measures* how well that promise holds, on the actual microscope, before
a run relies on it.

The idea: visit a ring of positions around the origin (12 by default,
about 1000 µm out), take one picture at each with the overview job
(objective 1), then come back to exactly the same frame positions with
the target job (objective 2) and take a second picture. If the
calibration and the stage were perfect, each pair would show the same
spot. Registering each pair measures the leftover XY offset — the
combined error of the calibration and the stage — and averaging over
many separate sites gives a far better estimate than a single
measurement, because each site carries its own independent stage error.

Two steps, matching the two notebook cells:

- :func:`start_calibration_check` picks the sites and acquires the
  objective-1 image at each;
- :func:`finish_calibration_check` re-visits every site with the
  objective-2 job, registers each image pair, and reports per-site and
  summary offsets (also written as JSON + a PNG plot into the run root).

Sign convention: a site's ``(dx_um, dy_um)`` is where the objective-2
image found the sample relative to the objective-1 image, in frame
micrometres. The summary's mean is the systematic calibration error;
the spread around it is the per-move stage error.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._capture_run import capture_positions
from ._records import record_channel_paths
from .steps import with_focus_z

# Voting registration must agree this well (in µm) across methods before a
# site is trusted; see shared.algorithms.register_voting.
_MIN_TRUSTED_SITES = 3


@dataclass
class CalibrationCheck:
    """The state carried from the objective-1 pass to the objective-2 pass."""

    session: Any
    positions: list[dict]
    reference_records: list[dict]
    focus: Any = None
    radius_um: float = 0.0
    options: dict | None = None
    comparison_records: list[dict] = field(default_factory=list)
    report: dict | None = None


def _ring_positions(n: int, radius_um: float, rng: random.Random) -> list[dict]:
    """``n`` sites on a circle of ``radius_um`` around the frame origin.

    Evenly spaced angles with a little random jitter, so the sites cover
    the stage travel in every direction rather than clustering.
    """
    positions = []
    for k in range(n):
        angle = (k + rng.uniform(-0.3, 0.3)) * 2.0 * math.pi / n
        positions.append(
            {
                "x": radius_um * math.cos(angle),
                "y": radius_um * math.sin(angle),
            }
        )
    return positions


def start_calibration_check(
    session: Any,
    state: dict,
    *,
    focus: Any = None,
    n_positions: int = 12,
    radius_um: float = 1000.0,
    seed: int | None = None,
    options: dict | None = None,
) -> CalibrationCheck:
    """Acquire the objective-1 reference image at each validation site.

    ``state`` is the captured overview (objective 1) job state; ``focus``
    the fitted focus surface (used for z at each site, like every other
    capture). ``n_positions`` sites are spread on a ring of ``radius_um``
    around the frame origin — far enough out that each visit carries a
    real stage move, which is exactly the error this check wants to see.

    Returns the :class:`CalibrationCheck` to pass to
    :func:`finish_calibration_check`.
    """
    if n_positions < _MIN_TRUSTED_SITES:
        raise ValueError(
            f"at least {_MIN_TRUSTED_SITES} sites are needed for a meaningful "
            f"average, got {n_positions}"
        )
    rng = random.Random(seed)
    positions = _ring_positions(int(n_positions), float(radius_um), rng)
    records = capture_positions(
        session,
        with_focus_z(positions, focus),
        "cal-check-ref",
        state=state,
        options=options,
        label=lambda index, _pos: f"calcheck-{index:02d}",
    )
    return CalibrationCheck(
        session=session,
        positions=positions,
        reference_records=records,
        focus=focus,
        radius_um=float(radius_um),
        options=options,
    )


def finish_calibration_check(
    check: CalibrationCheck,
    state: dict,
    *,
    options: dict | None = None,
    output_root: Any = None,
    show: bool = True,
) -> dict:
    """Re-visit every site with the objective-2 job and report the offsets.

    The driver applies the calibrated objective translation on each move,
    so with a perfect calibration and stage each pair of images shows the
    same spot. Registering each pair measures what is left over.

    Returns the report dict (``sites`` holds the per-site detail). With
    ``output_root`` set, also writes ``calibration_check.json`` and
    ``calibration_check.png`` there. Raises ``RuntimeError`` when fewer
    than three sites register confidently — an average over less is noise,
    not a validation (move to a more textured part of the sample).
    """
    check.comparison_records = capture_positions(
        check.session,
        with_focus_z(check.positions, check.focus),
        "cal-check-cmp",
        state=state,
        options=options if options is not None else check.options,
        label=lambda index, _pos: f"calcheck-{index:02d}",
    )

    sites = []
    for position, ref_record, cmp_record in zip(
        check.positions, check.reference_records, check.comparison_records, strict=True
    ):
        offset = _pair_offset_um(ref_record, cmp_record)
        sites.append({"x": position["x"], "y": position["y"], **offset})

    trusted = [s for s in sites if s["trusted"]]
    if len(trusted) < _MIN_TRUSTED_SITES:
        raise RuntimeError(
            f"only {len(trusted)} of {len(sites)} sites registered confidently — "
            "not enough for a meaningful average. Move to a more textured part "
            "of the sample and re-run the check."
        )

    def _mean(values: list[float]) -> float:
        return sum(values) / len(values)

    dxs = [s["dx_um"] for s in trusted]
    dys = [s["dy_um"] for s in trusted]
    mean_dx, mean_dy = _mean(dxs), _mean(dys)
    spread = [
        math.hypot(s["dx_um"] - mean_dx, s["dy_um"] - mean_dy) for s in trusted
    ]
    report = {
        "n_sites": len(sites),
        "n_trusted": len(trusted),
        "radius_um": check.radius_um,
        # The systematic part: how far the calibration itself is off.
        "mean_dx_um": mean_dx,
        "mean_dy_um": mean_dy,
        "mean_offset_um": math.hypot(mean_dx, mean_dy),
        # The random part: per-move stage error around that mean.
        "stage_scatter_rms_um": math.sqrt(_mean([d**2 for d in spread])),
        "max_offset_um": max(math.hypot(s["dx_um"], s["dy_um"]) for s in trusted),
        "sites": sites,
    }
    check.report = report

    if output_root is not None:
        root = Path(output_root)
        root.mkdir(parents=True, exist_ok=True)
        (root / "calibration_check.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        _plot_report(report, save_path=root / "calibration_check.png", show=show)
    elif show:
        _plot_report(report, save_path=None, show=True)
    return report


def _pair_offset_um(ref_record: dict, cmp_record: dict) -> dict:
    """Register one objective-1 / objective-2 image pair -> offset in µm.

    The two images cover different fields of view at different pixel
    sizes, so both are first cut to the physical window they share
    (centred, the smaller of the two fields) and the coarser one is
    resampled onto the finer pixel grid. Voting registration then measures
    the shift; ``trusted`` is False when the methods disagree.
    """
    import numpy as np
    from skimage.transform import resize

    from shared.algorithms import register_voting

    from ._geom import crop_overview_at_target_fov
    from ._overview_widget import _load_channels
    from .discovery import read_overview_geometry

    pair = []
    for record, name in ((ref_record, "objective-1"), (cmp_record, "objective-2")):
        paths = record_channel_paths(record, context=f"calibration-check {name} record")
        image = _load_channels(paths[0])[0]
        geometry = read_overview_geometry(paths[0])
        pair.append((image, float(geometry["pixel_size_um"])))
    (ref_image, ref_ps), (cmp_image, cmp_ps) = pair

    fine_ps = min(ref_ps, cmp_ps)
    window_h_um = min(ref_image.shape[0] * ref_ps, cmp_image.shape[0] * cmp_ps)
    window_w_um = min(ref_image.shape[1] * ref_ps, cmp_image.shape[1] * cmp_ps)
    shape_fine = (
        max(8, int(window_h_um / fine_ps)),
        max(8, int(window_w_um / fine_ps)),
    )

    def _common_window(image: np.ndarray, pixel_size: float) -> np.ndarray:
        crop = crop_overview_at_target_fov(
            image,
            centroid_col_row_px=(image.shape[1] / 2.0, image.shape[0] / 2.0),
            source_pixel_size_um=pixel_size,
            target_shape_px=shape_fine,
            target_pixel_size_um=fine_ps,
        )
        if crop.shape != shape_fine:
            crop = resize(crop, shape_fine, preserve_range=True, anti_aliasing=True)
        return np.asarray(crop, dtype=np.float32)

    ref_window = _common_window(ref_image, ref_ps)
    cmp_window = _common_window(cmp_image, cmp_ps)
    # A featureless window would "register" perfectly at (0, 0) — every
    # method agrees because there is nothing to disagree about — and a
    # blank sample would then report a flawless calibration. Refuse to
    # trust a site without real image texture instead.
    if float(np.std(ref_window)) < 1e-6 or float(np.std(cmp_window)) < 1e-6:
        return {
            "dx_um": float("nan"),
            "dy_um": float("nan"),
            "trusted": False,
            "confidence": 0,
        }

    vote = register_voting(ref_window, cmp_window, fine_ps)
    # register_voting reports how far the ref content moved to become the
    # target content — negate so a site reads as "where objective 2 found
    # the sample relative to objective 1", the error an operator would
    # correct in the calibration.
    dx = vote.get("dx_um")
    dy = vote.get("dy_um")
    return {
        "dx_um": float("nan") if dx is None else -float(dx),
        "dy_um": float("nan") if dy is None else -float(dy),
        "trusted": bool(vote.get("trusted")),
        "confidence": vote.get("confidence"),
    }


def _plot_report(report: dict, *, save_path: Any, show: bool) -> None:
    """One figure: residual arrows at the sites, and the residual cloud."""
    import matplotlib

    if not show:
        matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt

    trusted = [s for s in report["sites"] if s["trusted"]]
    rejected = [s for s in report["sites"] if not s["trusted"]]

    fig, (ax_map, ax_cloud) = plt.subplots(1, 2, figsize=(11, 5))
    if trusted:
        ax_map.quiver(
            [s["x"] for s in trusted],
            [s["y"] for s in trusted],
            [s["dx_um"] for s in trusted],
            [s["dy_um"] for s in trusted],
            angles="xy",
            color="tab:blue",
        )
    if rejected:
        ax_map.scatter(
            [s["x"] for s in rejected],
            [s["y"] for s in rejected],
            marker="x",
            color="0.6",
            label=f"not trusted ({len(rejected)})",
        )
        ax_map.legend(loc="best", fontsize=8)
    ax_map.set_aspect("equal", adjustable="datalim")
    ax_map.set_xlabel("frame x (um)")
    ax_map.set_ylabel("frame y (um)")
    ax_map.set_title("offset per site (arrows exaggerated)", fontsize=10)

    ax_cloud.axhline(0.0, color="0.85", linewidth=1)
    ax_cloud.axvline(0.0, color="0.85", linewidth=1)
    ax_cloud.scatter(
        [s["dx_um"] for s in trusted],
        [s["dy_um"] for s in trusted],
        color="tab:blue",
        s=40,
    )
    ax_cloud.scatter(
        [report["mean_dx_um"]],
        [report["mean_dy_um"]],
        marker="+",
        s=160,
        color="tab:red",
        label=f"mean ({report['mean_dx_um']:+.2f}, {report['mean_dy_um']:+.2f}) um",
    )
    ax_cloud.set_aspect("equal", adjustable="datalim")
    ax_cloud.set_xlabel("dx (um)")
    ax_cloud.set_ylabel("dy (um)")
    ax_cloud.set_title(
        f"calibration off by {report['mean_offset_um']:.2f} um "
        f"(stage scatter {report['stage_scatter_rms_um']:.2f} um rms)",
        fontsize=10,
    )
    ax_cloud.legend(loc="best", fontsize=8)
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path, dpi=150)
