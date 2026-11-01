"""reduce_dimensions -- two axes for a detected population, made from all its features.

The features are made for gating one pair at a time. This folds all of them
into two axes, so objects that are alike stand together, whatever mix of
features makes them alike:

- ``pca``: the first two principal components (``pca_1``, ``pca_2``). A
  fraction of a second over half a million objects.
- ``umap``: a UMAP layout (``umap_1``, ``umap_2``) of the first 50
  components. Minutes over half a million objects, so it runs on request.

Takes ``input["table"]`` (the population table of a detected overview, one row
per object), ``input["ids"]`` (the objects to use, or None for all) and
``input["kind"]``. Writes the columns beside the table as ``<stem>_pca.csv``
and ``<stem>_umap.csv``.

Only measurements go in: identity and place (``label``, ``bbox_*``,
``centroid_*``, the stage position) stay out, and so does ``bg_global_mean*``,
one value per field. A column measured for fewer than ``enough_measured`` of
the objects stays out. Missing values take their column's median
(scikit-learn ``SimpleImputer``), and each column is centred on its median and
scaled by its interquartile range (``RobustScaler``), so a few bright outliers
cannot own an axis. The seed is fixed: the same population gives the same plot.

Publishes under ``pipeline_data["reduce_dimensions"]``::

    written                   {kind: path} for every file written
    objects                   how many objects were used
    features                  the columns the axes are made from
    explained_variance_ratio  the share of the spread each component carries
    loadings                  the five features weighing most on each of the
                              first two components
    umap                      the settings of the UMAP, or None
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

METADATA = {
    "description": "Principal components or a UMAP of a discovered population",
    "version": "1.0",
    "max_workers": 1,
    "environment": "ZMART--object_analysis--umap",
}

#: The two kinds of plot, and the columns each writes.
KINDS = {"pca": ("pca_1", "pca_2"), "umap": ("umap_1", "umap_2")}

#: Columns that say which object it is or where it sits, not what it is like.
NOT_MEASURED = {
    "field",
    "position_label",
    "id",
    "x_um",
    "y_um",
    "intensity",
    "r",
    "label",
    "object_id",
    "tile_name",
}
NOT_MEASURED_PREFIXES = ("bbox_", "centroid_", "weighted_centroid", "stage_", "bg_global_mean")


def run(pipeline_data: dict, state: dict, **params) -> dict:

    verbose = pipeline_data.get("metadata", {}).get("verbose", 0)

    given = pipeline_data["input"]

    kind = given.get("kind")

    seed = int(params.get("seed", 0))

    if kind not in KINDS:
        raise ValueError(f"kind must be one of {tuple(KINDS)}, got {kind!r}.")

    table = Path(given["table"])

    frame = _read_population(table, given.get("ids"))

    ids = [str(one) for one in frame["id"]]

    features = _measured_columns(frame, float(params.get("enough_measured", 0.5)))

    _check(ids, features, int(params.get("enough_objects", 10)))

    components, explained, loadings = _principal_components(
        _scaled(frame, features), features, seed, int(params.get("components", 50))
    )

    # The principal components are always written; a UMAP is laid out from them
    stem = table.name.removesuffix("_objects.csv")

    written = {
        "pca": _write(table.with_name(f"{stem}_pca.csv"), ids, KINDS["pca"], components[:, :2])
    }

    umap_settings = None

    if kind == "umap":
        umap_settings, laid_out = _umap(components, len(ids), seed, params)

        written["umap"] = _write(table.with_name(f"{stem}_umap.csv"), ids, KINDS["umap"], laid_out)

    if verbose:
        print(f"  [reduce_dimensions] {kind} over {len(ids)} objects, {len(features)} features")

    pipeline_data["reduce_dimensions"] = {
        "written": {key: str(path) for key, path in written.items()},
        "objects": len(ids),
        "features": features,
        "explained_variance_ratio": explained,
        "loadings": loadings,
        "umap": umap_settings,
    }

    return pipeline_data


def _read_population(table: Path, ids):
    """The population table, narrowed to ``ids`` when given, in its own order."""

    import pandas as pd

    frame = pd.read_csv(table, dtype={"id": str, "position_label": str})

    if ids is not None:
        frame = frame[frame["id"].isin(set(map(str, ids)))]

    return frame.reset_index(drop=True)


def _check(ids: list[str], features: list[str], enough_objects: int) -> None:
    """Refuse a population too small, or without a feature, to say anything."""

    if len(ids) < enough_objects:
        raise ValueError(
            f"only {len(ids)} objects; a plot needs at least {enough_objects} "
            "to say anything about the population"
        )

    if not features:
        raise ValueError("no feature was measured widely enough to plot the objects on")


def _measured_columns(frame, enough_measured: float) -> list[str]:
    """The numeric measurement columns worth keeping, in name order.

    A column measured for fewer than ``enough_measured`` of the objects stays
    out, and so does one with the same value for every object.
    """

    from pandas.api.types import is_numeric_dtype

    kept = []

    for name in sorted(frame.columns):
        if name in NOT_MEASURED or name.startswith(NOT_MEASURED_PREFIXES):
            continue

        if not is_numeric_dtype(frame[name]):
            continue

        column = np.asarray(frame[name], dtype=np.float64)

        finite = np.isfinite(column)

        if not finite.size or finite.mean() < enough_measured:
            continue

        if np.ptp(column[finite]) == 0.0:
            continue

        kept.append(name)

    return kept


def _scaled(frame, features: list[str]) -> np.ndarray:
    """The feature columns, missing values filled with the median, robustly scaled.

    A column whose interquartile range is zero is scaled by its standard
    deviation instead, because ``RobustScaler`` would leave it unscaled.
    """

    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import RobustScaler

    if not features:
        return np.empty((len(frame), 0))

    # A copy: pandas hands out read-only views of its columns
    raw = np.array(frame[features], dtype=np.float64)

    raw[~np.isfinite(raw)] = np.nan

    filled = SimpleImputer(strategy="median").fit_transform(raw)

    scaled = RobustScaler(quantile_range=(25.0, 75.0)).fit_transform(filled)

    q1, q3 = np.percentile(filled, [25, 75], axis=0)

    flat = (q3 - q1) == 0.0

    if flat.any():
        std = filled[:, flat].std(axis=0)

        std[std == 0] = 1.0

        scaled[:, flat] = (filled[:, flat] - np.median(filled[:, flat], axis=0)) / std

    return scaled


def _principal_components(matrix: np.ndarray, features: list[str], seed: int, n_components: int):
    """PCA of the scaled matrix: the components, the spread each explains, and the loadings.

    The loadings are the five features weighing most on each of the first
    two components, so the two axes drawn can be read.
    """

    from sklearn.decomposition import PCA

    room = min(n_components, matrix.shape[0], matrix.shape[1])

    pca = PCA(n_components=room, random_state=seed)

    components = pca.fit_transform(matrix)

    explained = [float(v) for v in pca.explained_variance_ratio_]

    loadings = {
        f"pca_{axis + 1}": {
            feature: float(weight)
            for feature, weight in sorted(
                zip(features, pca.components_[axis], strict=True), key=lambda fw: -abs(fw[1])
            )[:5]
        }
        for axis in range(min(2, components.shape[1]))
    }

    # A single component still draws as two axes, the second flat
    if components.shape[1] < 2:
        components = np.hstack([components, np.zeros((components.shape[0], 1))])

    return components, explained, loadings


def _umap(components: np.ndarray, n_objects: int, seed: int, params: dict):
    """A two-axis UMAP layout of the principal components, and the settings it used."""

    from umap import UMAP

    settings = {
        "n_neighbors": min(int(params.get("neighbours", 15)), n_objects - 1),
        "min_dist": float(params.get("min_dist", 0.1)),
        "components_in": int(components.shape[1]),
        "random_state": seed,
    }

    laid_out = UMAP(
        n_components=2,
        n_neighbors=settings["n_neighbors"],
        min_dist=settings["min_dist"],
        random_state=seed,
    ).fit_transform(components)

    return settings, laid_out


def _write(path: Path, ids: list[str], columns: tuple[str, str], values: np.ndarray) -> Path:
    """Two columns per object, by id, as a CSV file."""

    with path.open("w", encoding="utf-8", newline="") as out:
        rows = csv.writer(out)

        rows.writerow(["id", *columns])

        for an_id, (a, b) in zip(ids, values, strict=True):
            rows.writerow([an_id, float(a), float(b)])

    return path
