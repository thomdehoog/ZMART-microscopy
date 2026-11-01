"""segment_watershed -- find the nuclei in one image tile with a watershed, no model.

A port of QuPath's cell detection (``WatershedCellDetection``, Bankhead et
al. 2017): a second or two per field on an ordinary processor, for when the
microscope is waiting and Cellpose would take too long. It needs only scipy
and scikit-image, so it runs in the classical environment and never starts a
torch worker.

Everything around the detector is the same as in ``segment_cellpose``: the
binning, the border and size filters, and the record filed beside the data.
Settings: ``diameter`` (pixels, default 30) and ``threshold`` (a nucleus's mean
above background, in counts, default 100).

Publishes under ``pipeline_data["segment_watershed"]`` what
``segment_cellpose`` publishes, with ``detector_params["method"] == "fast"``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from segment_cellpose import filter_by_area, segment  # noqa: E402

METADATA = {
    "description": "Find nuclei with a watershed, without a deep-learning model",
    "version": "1.0",
    "max_workers": 1,
    "environment": "ZMART--object_analysis--classical",
}


def run(pipeline_data: dict, state: dict, **params) -> dict:

    pipeline_data["segment_watershed"] = segment(pipeline_data, params, "fast", _find_nuclei)

    return pipeline_data


def _find_nuclei(image, scale: float, settings: dict):
    """The watershed on the first channel, with its sizes following the binning.

    ``diameter`` is 30 pixels and ``threshold`` 100 counts unless set.
    """

    plane = image if image.ndim == 2 else image[..., 0]

    diameter = float(settings["diameter"]) if settings["diameter"] is not None else 30.0

    threshold = settings["threshold"] if settings["threshold"] is not None else 100.0

    masks, used = _watershed(plane, diameter * scale, threshold)

    return masks, {"method": "fast", "device": "cpu", **used}


def _watershed(plane, diameter_px: float, threshold: float):
    """Nuclei in one plane, the way QuPath's cell detection finds them.

    In order: the background is estimated by opening by reconstruction and
    taken off; a Gaussian blur and a Laplacian make the blob response; its
    positive part is the foreground, whose maxima seed a watershed; regions
    dimmer than ``threshold`` go; what is left is filled and split again on
    its distance transform, so touching nuclei part; objects outside the
    area range go. QuPath's micrometre defaults become ratios of the one
    diameter D given: background radius D, sigma D / 8, areas A / 8 to 5 A,
    with A the disc of diameter D.

    Returns the label image, numbered 1..n, and the parameters used, in pixels.
    """

    from scipy import ndimage
    from skimage import filters, measure, morphology, segmentation

    f = np.asarray(plane, dtype=np.float32)

    d = max(float(diameter_px), 2.0)

    radius = max(int(round(d)), 1)

    sigma = max(d / 8.0, 0.5)

    disc = np.pi * (d / 2.0) ** 2

    min_area = max(int(round(disc / 8.0)), 1)

    max_area = max(int(round(disc * 5.0)), min_area + 1)

    used = {
        "threshold": float(threshold),
        "sigma_px": float(sigma),
        "background_radius_px": int(radius),
        "min_area_px": int(min_area),
        "max_area_px": int(max_area),
        "split_by_shape": True,
    }

    # The background, by opening by reconstruction, taken off
    eroded = morphology.erosion(f, morphology.disk(radius, decomposition="sequence"))

    subtracted = f - morphology.reconstruction(eroded, f, method="dilation")

    # The blob response, and a watershed seeded at its maxima
    blurred = filters.gaussian(subtracted, sigma=sigma, preserve_range=True)

    response = ndimage.convolve(
        blurred, np.array([[0, -1, 0], [-1, 4, -1], [0, -1, 0]], dtype=np.float32)
    )

    above = response > 0

    seeds = measure.label(morphology.local_maxima(response) & above, connectivity=1)

    regions = segmentation.watershed(-response, seeds, mask=above, connectivity=1)

    labels = np.arange(1, int(regions.max()) + 1)

    if labels.size == 0:
        return np.zeros(f.shape, dtype=np.int32), used

    # Regions bright enough to be a nucleus, filled
    means = np.asarray(ndimage.mean(subtracted, regions, labels))

    kept = np.isin(regions, labels[means > threshold])

    kept = ndimage.binary_dilation(kept, structure=np.ones((3, 3), dtype=bool)) & above

    kept = ndimage.binary_fill_holes(kept)

    # Touching nuclei split on the distance to the background
    distance = ndimage.distance_transform_edt(kept)

    peaks = measure.label(morphology.h_maxima(distance, 0.5) & kept, connectivity=1)

    split = segmentation.watershed(-distance, peaks, mask=kept, watershed_line=True)

    objects = np.arange(1, int(split.max()) + 1)

    if objects.size:
        means = np.asarray(ndimage.mean(subtracted, split, objects))
        split = np.where(np.isin(split, objects[means >= threshold]), split, 0)

    masks, _ = filter_by_area(np.asarray(split, dtype=np.int32), min_area, max_area)

    # The detector numbers its objects once; the filters after it keep these numbers
    masks, _, _ = segmentation.relabel_sequential(np.asarray(masks, dtype=np.int32))

    return np.asarray(masks, dtype=np.int32), used
