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
    if 0 < best < len(scores) - 1:
        a, b, c = scores[best - 1], scores[best], scores[best + 1]
        denominator = a - 2 * b + c
        if denominator < 0:
            offset = 0.5 * (a - c) / denominator
            step = float(z[best + 1] - z[best - 1]) / 2.0
            peak_z = float(z[best] + offset * step)
    return {"peak_z_um": peak_z, "peak_index": best, "scores": scores.tolist(), "z_um": z.tolist()}


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
    return {
        "measure_objective_pair": {
            "translation_um": {"x": dx_um, "y": dy_um, "z": dz_um},
            "pixel_um": {"reference": ref_um, "target": tgt_um, "overlay": scale_um},
            "focus": focus,
            "registration": {
                "dcol_px": dcol_px, "drow_px": drow_px,
                "agreement": agreement, "error": float(error),
            },
            "accepted": bool(accepted),
            "why": None if accepted else (
                f"the two pictures agree only {agreement:.2f} where they overlap (less than "
                f"{agreement_min}); check that both were taken at the same stage position and in focus"
            ),
            "settings": {"channel": channel, "upsample": upsample},
        }
    }


# ---------------------------------------------------------------------------
# The picture of the result, as the notebook shows it
# ---------------------------------------------------------------------------


def write_diagnostic(reference: dict, target: dict, answer: dict, path, *, channel: int = 0):
    """Draw the two views and their overlay, so the shift can be checked by eye.

    Left and middle: what each lens saw, brought to one scale. Right: the two
    laid over one another by the shift found -- the reference in green and
    the target in magenta, so where they agree is white and any misfit shows
    as coloured fringes. Under each stack, its sharpness curve with the peak
    the height was read from.

    Written to ``path`` as a PNG and the path returned; ``None`` without
    matplotlib.
    """
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from scipy.ndimage import shift as nd_shift
    except ImportError:
        return None
    ref_um, tgt_um = float(reference["pixel_um"]), float(target["pixel_um"])
    ref = _plane(reference["image"], channel)
    tgt = _plane(target["image"], channel)
    scale_um = max(ref_um, tgt_um)
    ref_s = _to_scale(ref, ref_um, scale_um)
    tgt_s = _to_scale(tgt, tgt_um, scale_um)
    rows = min(ref_s.shape[0], tgt_s.shape[0]); cols = min(ref_s.shape[1], tgt_s.shape[1])
    ref_c = _centre_crop(ref_s, rows, cols); tgt_c = _centre_crop(tgt_s, rows, cols)
    reg = answer["registration"]
    # Move the target back by the shift found, so the two should coincide.
    tgt_back = nd_shift(tgt_c, (-reg["drow_px"], -reg["dcol_px"]), order=1)
    norm = lambda a: np.clip((a - np.percentile(a, 1)) / max(np.percentile(a, 99.5) - np.percentile(a, 1), 1e-9), 0, 1)
    overlay = np.dstack([norm(tgt_back), norm(ref_c), norm(tgt_back)])

    has_stacks = bool(answer.get("focus", {}).get("reference")) and bool(answer.get("focus", {}).get("target"))
    fig = Figure(figsize=(12, 7.5 if has_stacks else 4.4), facecolor="#f7f7f5")
    FigureCanvasAgg(fig)
    grid = fig.add_gridspec(2 if has_stacks else 1, 3, height_ratios=(2, 1) if has_stacks else (1,))
    for col, (image, title, cmap) in enumerate((
        (ref_c, f"reference · {ref_um:g} µm/px", "gray"),
        (tgt_c, f"target · {tgt_um:g} µm/px, at {scale_um:g}", "gray"),
        (overlay, "overlay after the shift · reference green, target magenta", None),
    )):
        ax = fig.add_subplot(grid[0, col])
        ax.imshow(image, cmap=cmap, interpolation="nearest")
        ax.set_title(title, fontsize=10); ax.set_xticks([]); ax.set_yticks([])
    if has_stacks:
        for col, name in enumerate(("reference", "target")):
            f = answer["focus"][name]
            ax = fig.add_subplot(grid[1, col])
            ax.plot(f["z_um"], f["scores"], "o-", color="#2c5aa0", ms=3)
            ax.axvline(f["peak_z_um"], color="#e6a100", lw=1.5)
            ax.set_title(f"{name} sharpness · peak at {f['peak_z_um']:.2f} µm", fontsize=10)
            ax.set_xlabel("height (µm)"); ax.set_yticks([])
    t = answer["translation_um"]
    z = "—" if t.get("z") is None else f"{t['z']:+.2f}"
    fig.suptitle((("Accepted: " if answer.get("accepted") else "Not accepted: ")
                  + f"target looks ({t['x']:+.1f}, {t['y']:+.1f}) µm and focuses {z} µm from the reference · "
                  f"agreement {reg.get('agreement', 0):.2f}"),
                 fontsize=12, color="#1f7a3a" if answer.get("accepted") else "#b3261e")
    fig.savefig(str(path), dpi=100)
    return str(path)
