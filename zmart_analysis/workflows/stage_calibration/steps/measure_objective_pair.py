"""measure_objective_pair -- how two objectives line up, and what a pixel covers.

A target found on a low-power overview has to be imaged again under a
high-power lens, and the two lenses do not look at exactly the same place or
sit at exactly the same height. This step measures both from pictures taken
with the stage standing still: the same field through each objective, and a
short focus stack through each.

- **Where they look.** The two frames are brought to the same scale using
  each lens's pixel size and laid over one another; the shift between them is
  how far the target lens looks from the reference lens, in micrometres.
- **Where they focus.** Each stack is scored for sharpness plane by plane and
  the sharp height read off; the difference is how far the target lens focuses
  from the reference lens.

Both are vendor-blind: they take images and heights and return numbers. The
driver's part -- moving, capturing, saying which lens is in -- happens before
this step and never inside it.

Takes ``input["reference"]`` and ``input["target"]``, each a dict of
``image`` (a 2-D picture at the shared position, *already corrected for the
rig's orientation*), ``pixel_um`` (that lens's pixel size), and optionally
``stack`` (planes in height order) with ``z_um`` (the height of each). The
pictures are expected to be taken at one stage XY; the stacks to be centred
around each lens's own rough focus.

Publishes under ``pipeline_data["measure_objective_pair"]``::

    translation_um   x, y, z: where the target lens looks and focuses
                     relative to the reference lens
    pixel_um         both pixel sizes, echoed so the record is complete
    focus            the sharp height under each lens, or None without a stack
    registration     the raw shift, and how well the pictures agree where
                     they overlap once shifted
    accepted         whether that agreement was strong enough to trust
"""

from __future__ import annotations

import numpy as np
import tifffile
from scipy.ndimage import zoom
from skimage.registration import phase_cross_correlation

METADATA = {
    "description": "Where and at what height a target objective looks relative to a reference one",
    "version": "1.0",
    "max_workers": 1,
    "environment": "ZMART--stage_calibration--main",
}

#: How well the two pictures must agree, once one is laid over the other by
#: the shift found, for that shift to be believed: the correlation of the
#: overlapping pixels, where 1 is identical and 0 is unrelated. Two views of
#: the same field through different lenses agree strongly but not perfectly,
#: because the lenses resolve differently.
AGREEMENT_MIN = 0.5


def _plane(source, channel: int = 0) -> np.ndarray:
    array = source if isinstance(source, np.ndarray) else tifffile.imread(str(source))
    array = np.asarray(array)
    while array.ndim > 2:
        array = array[channel if array.shape[0] > channel else 0]
        channel = 0
    return array.astype(np.float64)


def _brenner(plane: np.ndarray) -> float:
    """Mean squared difference between pixels two apart, along both axes."""
    across = plane[:, 2:] - plane[:, :-2]
    down = plane[2:, :] - plane[:-2, :]
    return float(np.mean(across * across) + np.mean(down * down))


def sharp_height_um(stack, z_um) -> dict:
    """Score every plane and refine the peak between planes with a parabola."""
    planes = [_plane(p) for p in stack]
    z = np.asarray(z_um, dtype=float)
    if len(planes) != len(z):
        raise ValueError(f"{len(planes)} planes but {len(z)} heights")
    scores = np.array([_brenner(p) for p in planes])
    best = int(np.argmax(scores))
    peak_z = float(z[best])
    # A peak on the first or last plane is not a peak: the stack did not reach
    # far enough to see the sharpness fall away again on that side, so the
    # true focus may lie beyond it. Reported rather than guessed.
    bracketed = 0 < best < len(scores) - 1
    if bracketed:
        a, b, c = scores[best - 1], scores[best], scores[best + 1]
        denominator = a - 2 * b + c
        if denominator < 0:
            offset = 0.5 * (a - c) / denominator
            step = float(z[best + 1] - z[best - 1]) / 2.0
            peak_z = float(z[best] + offset * step)
    return {"peak_z_um": peak_z, "peak_index": best, "bracketed": bool(bracketed),
            "scores": scores.tolist(), "z_um": z.tolist()}


def _to_scale(image: np.ndarray, from_um: float, to_um: float) -> np.ndarray:
    """Resample so that one pixel covers ``to_um`` micrometres."""
    factor = from_um / to_um
    if abs(factor - 1.0) < 1e-9:
        return image
    return zoom(image, factor, order=1)


def _centre_crop(image: np.ndarray, rows: int, cols: int) -> np.ndarray:
    r0 = (image.shape[0] - rows) // 2
    c0 = (image.shape[1] - cols) // 2
    return image[r0:r0 + rows, c0:c0 + cols]


def overlap_agreement(reference: np.ndarray, moved: np.ndarray, dcol: float, drow: float) -> float:
    """How alike the two pictures are where they overlap, once laid over one
    another by the shift found: a plain correlation of the shared pixels."""
    # The features moved by (dcol, drow): what sits at (r, c) in the moved
    # picture sat at (r - drow, c - dcol) in the reference. So the moved
    # picture's rows from drow onward line up with the reference's from zero.
    dc, dr = int(round(dcol)), int(round(drow))
    rows, cols = reference.shape
    r_mov = slice(max(0, dr), min(rows, rows + dr))
    c_mov = slice(max(0, dc), min(cols, cols + dc))
    r_ref = slice(max(0, -dr), min(rows, rows - dr))
    c_ref = slice(max(0, -dc), min(cols, cols - dc))
    a = reference[r_ref, c_ref].ravel()
    b = moved[r_mov, c_mov].ravel()
    if a.size < 16 or a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def run(pipeline_data: dict, state: dict, **params) -> dict:
    given = pipeline_data["input"]
    channel = int(params.get("channel", 0))
    upsample = int(params.get("upsample", 20))
    agreement_min = float(params.get("agreement_min", AGREEMENT_MIN))

    reference, target = given["reference"], given["target"]
    ref_um, tgt_um = float(reference["pixel_um"]), float(target["pixel_um"])
    ref = _plane(reference["image"], channel)
    tgt = _plane(target["image"], channel)

    # Bring the finer picture down to the coarser scale rather than the other
    # way round: inventing detail cannot help a correlation, and a picture
    # with fewer pixels correlates faster.
    scale_um = max(ref_um, tgt_um)
    ref_s = _to_scale(ref, ref_um, scale_um)
    tgt_s = _to_scale(tgt, tgt_um, scale_um)
    rows = min(ref_s.shape[0], tgt_s.shape[0])
    cols = min(ref_s.shape[1], tgt_s.shape[1])
    ref_c = _centre_crop(ref_s, rows, cols)
    tgt_c = _centre_crop(tgt_s, rows, cols)

    shift, error, _ = phase_cross_correlation(ref_c, tgt_c, upsample_factor=upsample)
    # Where the target's features sit relative to the reference's (target
    # minus reference), in the shared scale. The pictures are already laid
    # down the way the stage sees them, so this is a stage-frame shift.
    dcol_px, drow_px = float(-shift[1]), float(-shift[0])
    # A feature that appears further right under the target lens is one the
    # target lens sees to the left of where the reference lens sees it: the
    # target looks that far in the other direction.
    dx_um = -dcol_px * scale_um
    dy_um = -drow_px * scale_um

    focus = {"reference": None, "target": None}
    dz_um = None
    for name, side in (("reference", reference), ("target", target)):
        if side.get("stack"):
            focus[name] = sharp_height_um(side["stack"], side["z_um"])
    if focus["reference"] and focus["target"]:
        dz_um = focus["target"]["peak_z_um"] - focus["reference"]["peak_z_um"]

    agreement = overlap_agreement(ref_c, tgt_c, dcol_px, drow_px)
    accepted = agreement >= agreement_min
    # A focus difference is only reported when both stacks bracketed their
    # peak; a peak on the end of a stack says "refocus and take a wider
    # stack", not a height.
    unbracketed = [name for name in ("reference", "target")
                   if focus[name] is not None and not focus[name]["bracketed"]]
    if unbracketed:
        dz_um = None
    return {
        "measure_objective_pair": {
            "translation_um": {"x": dx_um, "y": dy_um, "z": dz_um},
            "pixel_um": {"reference": ref_um, "target": tgt_um, "overlay": scale_um},
            "focus": focus,
            "registration": {
                "dcol_px": dcol_px, "drow_px": drow_px,
                "agreement": agreement, "error": float(error),
            },
            "accepted": bool(accepted) and not unbracketed,
            "why": (
                None if accepted and not unbracketed
                else (f"the focus peak sits at the end of the {' and '.join(unbracketed)} stack, so the "
                      "sharpest plane was not reached; refocus under that lens and measure it again")
                if unbracketed
                else (f"the two pictures agree only {agreement:.2f} where they overlap (less than "
                      f"{agreement_min}); check that both were taken at the same stage position and in focus")
            ),
            "settings": {"channel": channel, "upsample": upsample},
        }
    }


# ---------------------------------------------------------------------------
# The picture of the result, as the notebook shows it
# ---------------------------------------------------------------------------


def _norm(a: np.ndarray) -> np.ndarray:
    a = a.astype(np.float64)
    lo, hi = float(a.min()), float(a.max())
    return np.zeros_like(a) if hi - lo < 1e-12 else (a - lo) / (hi - lo)


def overlay_rgb(ref_norm: np.ndarray, tgt_norm: np.ndarray) -> np.ndarray:
    """Reference in magenta, target in green: where the two carry the same
    structure the colours add up to white, so a misfit shows as fringes."""
    h = max(ref_norm.shape[0], tgt_norm.shape[0]); w = max(ref_norm.shape[1], tgt_norm.shape[1])
    rgb = np.zeros((h, w, 3))
    rgb[: ref_norm.shape[0], : ref_norm.shape[1], 0] = ref_norm
    rgb[: ref_norm.shape[0], : ref_norm.shape[1], 2] = ref_norm
    rgb[: tgt_norm.shape[0], : tgt_norm.shape[1], 1] = tgt_norm
    return np.clip(rgb, 0.0, 1.0)


def write_focus_diagnostic(stack, focus: dict, path, *, title: str = "Software Autofocus", channel: int = 0):
    """One lens's focus result, as the notebook shows it under its measure
    cell: the Brenner curve with its peak, and beside it the slice the
    microscope considered sharpest -- which should look like the sample in
    focus, not an empty field. ``None`` without matplotlib."""
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
    except ImportError:
        return None
    # The curve and the picture stand the same height, side by side, with the
    # picture square: placed by hand rather than by a layout that would size
    # the image axis to the picture and leave it shorter than the plot.
    fig = Figure(figsize=(12, 5), facecolor="white")
    FigureCanvasAgg(fig)
    top, bottom = 0.86, 0.15
    height = top - bottom                        # of the figure's 5 in
    square = height * 5 / 12                     # the same height, as a share of 12 in
    ax = fig.add_axes([0.07, bottom, 0.94 - square - 0.07 - 0.04, height])
    ax_img = fig.add_axes([0.94 - square, bottom, square, height])
    ax.plot(focus["z_um"], focus["scores"], marker="o")
    bracketed = focus.get("bracketed", True)
    ax.axvline(focus["peak_z_um"], color="red" if bracketed else "#b45309", linestyle="--",
               label=f"peak z = {focus['peak_z_um']:.3f} um" if bracketed
               else f"no peak: sharpest at the stack's end ({focus['peak_z_um']:.1f} um)")
    ax.set_xlabel("z (um, absolute)"); ax.set_ylabel("Brenner Gradient Score")
    ax.set_title(title if bracketed else f"{title} — refocus and measure again", color="#0f172a" if bracketed else "#b45309")
    ax.legend(loc="best")
    stack = list(stack or [])
    if stack:
        ax_img.imshow(_plane(stack[min(focus["peak_index"], len(stack) - 1)], channel), cmap="gray", origin="upper")
    ax_img.set_title(f"Focus position (Z = {focus['peak_z_um']:.2f} µm)")
    ax_img.set_xticks([]); ax_img.set_yticks([])
    fig.savefig(str(path), dpi=100)
    return str(path)


def write_overlay_diagnostic(reference: dict, target: dict, answer: dict, path, *, channel: int = 0):
    """The X/Y result, as the notebook shows it: the two lenses' views laid
    over one another, reference in magenta and target in green, as acquired
    and after the shift the measurement found. ``None`` without matplotlib."""
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from scipy.ndimage import shift as nd_shift
    except ImportError:
        return None
    ref_um, tgt_um = float(reference["pixel_um"]), float(target["pixel_um"])
    ref = _plane(reference["image"], channel); tgt = _plane(target["image"], channel)
    scale_um = max(ref_um, tgt_um)
    ref_s = _to_scale(ref, ref_um, scale_um); tgt_s = _to_scale(tgt, tgt_um, scale_um)
    rows = min(ref_s.shape[0], tgt_s.shape[0]); cols = min(ref_s.shape[1], tgt_s.shape[1])
    ref_c = _centre_crop(ref_s, rows, cols); tgt_c = _centre_crop(tgt_s, rows, cols)
    reg = answer["registration"]
    tgt_back = nd_shift(tgt_c, (-reg["drow_px"], -reg["dcol_px"]), order=1)
    t = answer["translation_um"]
    fig = Figure(figsize=(12, 6), facecolor="white")
    FigureCanvasAgg(fig)
    top, bottom = 0.84, 0.04
    height = top - bottom
    square = height * 6 / 12
    ax = fig.add_axes([0.5 - square - 0.02, bottom, square, height])
    ax2 = fig.add_axes([0.5 + 0.02, bottom, square, height])
    ax.imshow(overlay_rgb(_norm(ref_c), _norm(tgt_c)), origin="upper")
    ax.set_title(f"Reference (magenta) vs target (green), as acquired\nshift ({t['x']:+.2f}, {t['y']:+.2f}) um")
    ax.set_axis_off()
    ax2.imshow(overlay_rgb(_norm(ref_c), _norm(tgt_back)), origin="upper")
    ax2.set_title("Target after the measured correction"); ax2.set_axis_off()
    fig.savefig(str(path), dpi=100)
    return str(path)
