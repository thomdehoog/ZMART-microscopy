"""measure_orientation -- which way the picture is turned relative to the stage.

A camera or scanner is often mounted a quarter- or half-turn away from the
stage's own X and Y, and some acquisition settings mirror the image on top.
This step works that out from three pictures of the same field: one at home,
one after the stage moved a known distance along +X, and one after it moved
the same distance along +Y. Where the features went tells which way the
picture is turned, and how far they went tells how much specimen one pixel
covers.

Nothing here knows which microscope took the pictures. That is the point: the
driver's part is to move and capture, and this step's part is to look. The
answer is one of the eight lossless ways of laying an image down -- a whole
quarter-turn, optionally combined with a left-right mirror -- so it never
resamples or blurs anything, and a rig turned by anything other than a whole
quarter is reported as a rig problem rather than corrected around.

Takes ``input["home"]``, ``input["plus_x"]`` and ``input["plus_y"]`` -- three
2-D images as the driver wrote them, *raw*, before any correction -- and
``input["stage_move_um"]``, the distance the stage moved for the second and
third. Parameters are in ``orientation.yaml``.

Publishes under ``pipeline_data["measure_orientation"]``::

    orientation     the document a driver adopts: rotation_deg, reflection,
                    sign_convention, measured, schema_version
    accepted        whether the fit was close enough to a whole quarter-turn
                    to trust; when it is not, `why` says what to look at
    residual        how far the measured mapping sat from the nearest of the
                    eight, in the same units as `residual_max`
    pixel_um        micrometres per pixel, from how far the features moved --
                    one estimate per axis and their mean
    registrations   the raw feature shifts, in pixels, for the record

## The sign convention, written down once

On a rig with nothing turned, moving the stage +X carries the specimen +X
under a fixed camera, and its features move in the picture toward *lower*
column numbers. The measured matrix ``M`` therefore holds how features move
per micrometre of stage travel, and the correction that lines the picture up
with the stage is ``-inv(M)``: the minus is what turns "features moved that
way" into "the stage moved this way". Flipping that sign would turn every
answer by a half-turn; it can never introduce a mirror. This is the same
convention the Leica driver's own measurement uses, so the document produced
here is one that driver adopts unchanged.
"""

from __future__ import annotations

import numpy as np
import tifffile
from skimage.registration import phase_cross_correlation

METADATA = {
    "description": "Which of the eight lossless orientations lines the picture up with the stage",
    "version": "1.0",
    "max_workers": 1,
    "environment": "ZMART--stage_calibration--main",
}

SCHEMA_VERSION = 3

#: How a clockwise turn moves an image displacement (column, row): each entry
#: sends (+1 column, 0 rows) and (0 columns, +1 row) to their new places.
_STAGE_FROM_ROTATION = {
    0: ((1, 0), (0, 1)),
    90: ((0, -1), (1, 0)),
    180: ((-1, 0), (0, -1)),
    270: ((0, 1), (-1, 0)),
}

#: All eight: the four turns, and the four turns of a left-right mirrored
#: image. The mirror comes first and the turn second, always, so that every
#: mapping has exactly one name.
STAGE_FROM_ORIENTATION = {
    **{(deg, False): m for deg, m in _STAGE_FROM_ROTATION.items()},
    (0, True): ((-1, 0), (0, 1)),
    (90, True): ((0, -1), (-1, 0)),
    (180, True): ((1, 0), (0, -1)),
    (270, True): ((0, 1), (1, 0)),
}

#: How far from a whole quarter-turn a measured mapping may sit and still be
#: believed. The distance is between the fitted 2x2 matrix and its nearest
#: of the eight; a perfectly measured rig gives 0, and a rig turned by 10
#: degrees gives about 0.25, which is where belief should stop.
RESIDUAL_MAX = 0.25


def reorient(array: np.ndarray, rotation_deg: int, reflection: bool) -> np.ndarray:
    """Lay a raw picture down the way the stage sees it: mirror first, then turn."""
    if reflection:
        array = np.fliplr(array)
    k = rotation_deg // 90
    if k:
        array = np.rot90(array, k=-k)  # negative k turns clockwise
    return np.ascontiguousarray(array)


def unorient(array: np.ndarray, rotation_deg: int, reflection: bool) -> np.ndarray:
    """The opposite of :func:`reorient`: what a camera turned this way would record."""
    k = rotation_deg // 90
    if k:
        array = np.rot90(array, k=k)
    if reflection:
        array = np.fliplr(array)
    return np.ascontiguousarray(array)


def _signed_axis(row) -> str:
    index = next(i for i, value in enumerate(row) if value)
    return f"{'+' if row[index] > 0 else '-'}{('X', 'Y')[index]}"


def orientation_document(rotation_deg: int, reflection: bool, *, measured: bool = True) -> dict:
    """The document a driver adopts, in the shape its orientation.json takes."""
    rows = STAGE_FROM_ORIENTATION[(rotation_deg, reflection)]
    return {
        "schema_version": SCHEMA_VERSION,
        "measured": bool(measured),
        "rotation_deg": int(rotation_deg),
        "reflection": bool(reflection),
        "sign_convention": {
            "stage_x_from_image": _signed_axis(rows[0]),
            "stage_y_from_image": _signed_axis(rows[1]),
        },
    }


def nearest_orientation(matrix) -> tuple[tuple[int, bool], float]:
    """The one of the eight closest to a fitted 2x2 matrix, and how far it sat."""
    fitted = np.asarray(matrix, dtype=float)
    best, best_residual = None, float("inf")
    for key, canonical in STAGE_FROM_ORIENTATION.items():
        residual = float(np.linalg.norm(fitted - np.asarray(canonical, dtype=float)))
        if residual < best_residual:
            best, best_residual = key, residual
    return best, best_residual


def _plane(source, channel: int) -> np.ndarray:
    """One 2-D plane, as floats. A stack hands over the channel asked for."""
    if isinstance(source, np.ndarray):
        array = source
    else:
        array = tifffile.imread(str(source))
    array = np.asarray(array)
    while array.ndim > 2:
        index = channel if array.shape[0] > channel else 0
        array = array[index]
        channel = 0
    return array.astype(np.float64)


def overlap_agreement(reference: np.ndarray, moved: np.ndarray, dcol: float, drow: float) -> float:
    """How alike the two pictures are where they overlap, once laid over one
    another by a shift: a plain correlation of the shared pixels, 1 for
    identical and 0 for unrelated. What sits at (r, c) in the moved picture
    sat at (r - drow, c - dcol) in the reference."""
    dc, dr = int(round(dcol)), int(round(drow))
    rows, cols = reference.shape
    r_mov = slice(max(0, dr), min(rows, rows + dr))
    c_mov = slice(max(0, dc), min(cols, cols + dc))
    r_ref = slice(max(0, -dr), min(rows, rows - dr))
    c_ref = slice(max(0, -dc), min(cols, cols - dc))
    a, b = reference[r_ref, c_ref].ravel(), moved[r_mov, c_mov].ravel()
    if a.size < 16 or a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _template_shift_px(reference: np.ndarray, moved: np.ndarray) -> tuple[float, float]:
    """The whole-pixel shift at which the middle of the moved picture matches
    the reference best, by normalised cross-correlation. Slower than phase
    correlation and blind to sub-pixel shifts, but it does not need the two
    pictures to share their whole extent."""
    from skimage.feature import match_template

    rows, cols = moved.shape
    template = moved[rows // 4: 3 * rows // 4, cols // 4: 3 * cols // 4]
    score = match_template(reference, template)
    r, c = np.unravel_index(int(np.argmax(score)), score.shape)
    # The template's top-left sat at (rows/4, cols/4) in the moved picture and
    # was found at (r, c) in the reference: the features moved by the difference.
    return float(cols // 4 - c), float(rows // 4 - r)


def feature_shift_px(reference: np.ndarray, moved: np.ndarray, *, upsample: int = 20) -> dict:
    """How far the features moved, in pixels, from the first picture to the second.

    Phase correlation finds the whole-image shift that lays one picture over
    the other, to a fraction of a pixel. It is reported as where the features
    went (second minus first), in columns and rows, which is the convention
    the sign discussion above depends on.

    Phase correlation can lock onto the wrong answer when the two pictures
    share a fixed pattern or little texture. So the shift it names is checked
    by laying the pictures over one another and asking how well they agree;
    when they do not, a plain template match decides instead, and `method`
    says which one answered.
    """
    shift, error, _ = phase_cross_correlation(reference, moved, upsample_factor=upsample)
    dcol, drow = float(-shift[1]), float(-shift[0])
    agreement = overlap_agreement(reference, moved, dcol, drow)
    method = "phase"
    if agreement < 0.5:
        dcol, drow = _template_shift_px(reference, moved)
        agreement = overlap_agreement(reference, moved, dcol, drow)
        method = "template"
    return {
        "dcol_px": dcol,
        "drow_px": drow,
        "agreement": agreement,
        "method": method,
        "error": float(error),
    }


def run(pipeline_data: dict, state: dict, **params) -> dict:
    given = pipeline_data["input"]
    channel = int(params.get("channel", 0))
    residual_max = float(params.get("residual_max", RESIDUAL_MAX))
    upsample = int(params.get("upsample", 20))
    stage_move_um = float(given["stage_move_um"])
    if stage_move_um <= 0:
        raise ValueError(f"stage_move_um must be > 0, got {stage_move_um}")

    home = _plane(given["home"], channel)
    plus_x = _plane(given["plus_x"], channel)
    plus_y = _plane(given["plus_y"], channel)
    for name, image in (("plus_x", plus_x), ("plus_y", plus_y)):
        if image.shape != home.shape:
            raise ValueError(f"{name} is {image.shape}, home is {home.shape}; they must match")

    shift_x = feature_shift_px(home, plus_x, upsample=upsample)
    shift_y = feature_shift_px(home, plus_y, upsample=upsample)

    # Features per micrometre of stage travel, one column per stage axis.
    moved = np.array(
        [
            [shift_x["dcol_px"], shift_y["dcol_px"]],
            [shift_x["drow_px"], shift_y["drow_px"]],
        ]
    ) / stage_move_um
    lengths = np.linalg.norm(moved, axis=0)  # px per um, one per axis
    if not np.all(np.isfinite(lengths)) or np.any(lengths <= 0):
        raise ValueError("the features did not move; the stage move was too small or the field is flat")
    pixel_um_by_axis = {"x": float(1.0 / lengths[0]), "y": float(1.0 / lengths[1])}
    pixel_um = float(np.mean([pixel_um_by_axis["x"], pixel_um_by_axis["y"]]))

    # Scale out the pixel size so what is left is direction alone, then take
    # the correction as the sign convention above says.
    unit = moved * pixel_um
    try:
        fitted = -np.linalg.inv(unit)
    except np.linalg.LinAlgError as exc:
        raise ValueError(f"the two moves did not span the picture ({exc}); the shifts are collinear") from exc

    (rotation_deg, reflection), residual = nearest_orientation(fitted)
    accepted = residual <= residual_max
    axes_disagree = abs(pixel_um_by_axis["x"] - pixel_um_by_axis["y"]) / pixel_um
    why = None
    if not accepted:
        why = (
            f"the measured mapping sat {residual:.3f} from the nearest whole quarter-turn "
            f"(more than {residual_max}); the rig may be turned by a part of a turn, the "
            f"field may have too little structure, or the stage move may be too small"
        )
    elif axes_disagree > 0.05:
        why = (
            f"the pixel size measured along X ({pixel_um_by_axis['x']:.4f} um) and Y "
            f"({pixel_um_by_axis['y']:.4f} um) disagree by {axes_disagree:.0%}; the "
            "orientation is trusted but the pixel size should be checked"
        )

    return {
        "measure_orientation": {
            "orientation": orientation_document(rotation_deg, reflection, measured=True),
            "accepted": bool(accepted),
            "why": why,
            "residual": float(residual),
            "residual_max": residual_max,
            "image_to_stage": [list(r) for r in STAGE_FROM_ORIENTATION[(rotation_deg, reflection)]],
            "pixel_um": {**pixel_um_by_axis, "mean": pixel_um},
            "stage_move_um": stage_move_um,
            "registrations": {"stage_plus_x": shift_x, "stage_plus_y": shift_y},
            "settings": {"channel": channel, "upsample": upsample},
        }
    }


# ---------------------------------------------------------------------------
# The picture of the result, as the notebook shows it
# ---------------------------------------------------------------------------


def _for_display(image: np.ndarray) -> np.ndarray:
    values = np.asarray(image, dtype=np.float64)
    lo, hi = np.percentile(values, (1.0, 99.0))
    return np.zeros_like(values) if hi <= lo else np.clip((values - lo) / (hi - lo), 0.0, 1.0)


def candidate_overlay(home, plus_x, plus_y, *, stage_move_um, pixel_um, rotation_deg, reflection):
    """Home in magenta; both moved pictures, shifted back by the move this
    candidate predicts, in green. The right candidate overlaps white."""
    from scipy.ndimage import shift as nd_shift

    image_to_stage = np.asarray(STAGE_FROM_ORIENTATION[(rotation_deg, reflection)], dtype=float)
    stage_to_image = -np.linalg.inv(image_to_stage)
    expected_x = stage_to_image[:, 0] * stage_move_um
    expected_y = stage_to_image[:, 1] * stage_move_um

    def align(image, expected_um):
        return nd_shift(np.asarray(image, dtype=np.float64),
                        shift=(-expected_um[1] / pixel_um, -expected_um[0] / pixel_um),
                        order=1, mode="constant", cval=float(np.median(image)), prefilter=False)

    moved = (align(plus_x, expected_x) + align(plus_y, expected_y)) / 2.0
    ref, tgt = _for_display(home), _for_display(moved)
    rgb = np.zeros((*ref.shape, 3))
    rgb[..., 0] = ref; rgb[..., 2] = ref; rgb[..., 1] = tgt
    return reorient(np.clip(rgb, 0.0, 1.0), rotation_deg, reflection)


def write_diagnostic(home, plus_x, plus_y, answer: dict, path, *, channel: int = 0):
    """The set_orientation notebook's figure: the detected correction, and the
    eight-candidate gallery it was chosen from.

    Each candidate lays the moved pictures back over the home picture the way
    that candidate predicts; the one that is right overlaps white. Written to
    ``path`` as a PNG and the path returned; ``None`` without matplotlib.
    """
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from matplotlib.patches import FancyBboxPatch, Patch
    except ImportError:
        return None
    o = answer["orientation"]
    accepted = bool(answer.get("accepted"))
    colour = "#087F5B" if accepted else "#C56A00"
    home_p, x_p, y_p = (_plane(a, channel) for a in (home, plus_x, plus_y))
    stride = max(1, int(np.ceil(max(home_p.shape) / 256)))
    home_g, x_g, y_g = (a[::stride, ::stride] for a in (home_p, x_p, y_p))
    pixel_um = float(answer["pixel_um"]["mean"]) * stride
    move_um = float(answer["stage_move_um"])

    fig = Figure(figsize=(14, 9.4), facecolor="#F4F6F7")
    FigureCanvasAgg(fig)
    grid = fig.add_gridspec(3, 1, height_ratios=(0.58, 0.14, 2.0), left=0.035, right=0.985,
                            bottom=0.07, top=0.97, hspace=0.12)
    gallery = grid[2].subgridspec(2, 5, width_ratios=(0.18, 1, 1, 1, 1), hspace=0.16, wspace=0.10)

    card = fig.add_subplot(grid[0]); card.set_axis_off()
    card.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.012,rounding_size=0.025",
                                  transform=card.transAxes, facecolor="white", edgecolor="#DDE2E5",
                                  linewidth=1.2, clip_on=False))
    t = lambda x, y, text, **kw: card.text(x, y, text, transform=card.transAxes, ha="left", va="center", **kw)
    t(0.025, 0.84, "DETECTED IMAGE CORRECTION" if accepted else "ORIENTATION NOT ACCEPTED",
      fontsize=11.5, fontweight="bold", color=colour)
    t(0.025, 0.57, "ROTATION", fontsize=9.5, fontweight="bold", color="#7A858C")
    t(0.025, 0.28, f"{o['rotation_deg']}° clockwise", fontsize=20, fontweight="bold", color="#172126")
    t(0.30, 0.57, "REFLECTION", fontsize=9.5, fontweight="bold", color="#7A858C")
    t(0.30, 0.28, "Yes" if o["reflection"] else "No", fontsize=20, fontweight="bold", color="#172126")
    t(0.52, 0.57, "SIGN CONVENTION", fontsize=9.5, fontweight="bold", color="#7A858C")
    t(0.52, 0.28, f"Stage X  ←  image {o['sign_convention']['stage_x_from_image']}     "
                  f"Stage Y  ←  image {o['sign_convention']['stage_y_from_image']}",
      fontsize=16, fontweight="bold", color="#172126")

    legend = fig.add_subplot(grid[1]); legend.set_axis_off()
    legend.legend(handles=(Patch(facecolor="#FF00FF", edgecolor="none", label="Home image"),
                           Patch(facecolor="#00C853", edgecolor="none", label="Moved images corrected by each candidate"),
                           Patch(facecolor="white", edgecolor="#9AA3A8", label="Agreement / overlap")),
                  loc="center left", bbox_to_anchor=(0.005, 0.5), ncol=3, frameon=False, fontsize=10,
                  handlelength=1.2, columnspacing=1.8)
    legend.text(0.995, 0.5, "The selected candidate has the strongest white overlap.",
                transform=legend.transAxes, ha="right", va="center", fontsize=9.5, color="#667179")

    for row, label in enumerate(("NO\nREFLECTION", "REFLECTION")):
        ax = fig.add_subplot(gallery[row, 0]); ax.set_axis_off()
        ax.text(0.52, 0.5, label, transform=ax.transAxes, ha="center", va="center", fontsize=9.5,
                linespacing=1.25, fontweight="bold", color="#667179")
    for row, reflection in enumerate((False, True)):
        for column, rotation_deg in enumerate((0, 90, 180, 270)):
            ax = fig.add_subplot(gallery[row, column + 1])
            if row == 0:
                ax.set_title(f"{rotation_deg}°", fontsize=11, fontweight="bold", color="#354047", pad=7)
            ax.imshow(candidate_overlay(home_g, x_g, y_g, stage_move_um=move_um, pixel_um=pixel_um,
                                        rotation_deg=rotation_deg, reflection=reflection), interpolation="nearest")
            ax.set_xticks([]); ax.set_yticks([])
            selected = (rotation_deg, reflection) == (o["rotation_deg"], o["reflection"])
            for spine in ax.spines.values():
                spine.set_color(colour if selected else "#A8ADB3"); spine.set_linewidth(4.0 if selected else 0.9)
            if selected:
                ax.text(0.5, 0.965, "SELECTED" if accepted else "NEAREST - REJECTED", transform=ax.transAxes,
                        ha="center", va="top", color="white", fontsize=8.5, fontweight="bold",
                        bbox={"facecolor": colour, "edgecolor": "none", "pad": 3.5})
    fig.text(0.5, 0.025, "Eight lossless possibilities: four rotations × reflection absent or present.",
             ha="center", va="center", fontsize=9.5, color="#667179")
    fig.savefig(str(path), dpi=105)
    return str(path)
