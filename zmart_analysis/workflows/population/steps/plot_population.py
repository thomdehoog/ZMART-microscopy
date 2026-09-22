"""plot_population -- a multidimensional plot of a discovered population.

The features object analysis measures are made for gating one pair at a
time; this folds all of them into two axes so the population's own
structure can be gated on too -- objects that are alike stand together,
whatever combination of columns makes them alike:

- ``pca``, the first two principal components (``pc_1``, ``pc_2``): linear,
  and a fraction of a second over half a million objects;
- ``umap``, a UMAP layout (``umap_1``, ``umap_2``) of the first 50 of those
  components: minutes over half a million, which is why the operator asks
  for it and detection never runs it.

Takes ``input["table"]``, the population table written when a whole overview
has been detected (one row an object, one column a feature), narrowed to
``input["ids"]`` when given, and ``input["kind"]``. Writes the two columns
beside the table (``<stem>_pca.csv``, ``<stem>_umap.csv``); a UMAP writes the
components too, since it stands on them.

What goes in is chosen, not everything numeric: identity and place stay out
(``label``, ``bbox_*``, ``centroid_*``, the stage position), and so does
``bg_global_mean*`` -- one number per field, which would lay out the field an
object came from rather than the object. A column measured for fewer than
half the objects stays out; the odd missing value takes its column's
median. Each column is centred on its median and scaled by its spread
between the quartiles, so a few bright outliers cannot own an axis. The
seed is pinned: the same population always gets the same plot.

Publishes under ``pipeline_data["plot_population"]``::

    written   {kind: path} for every file written
    objects   how many objects were plotted
    features  the columns the plot stands on
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

METADATA = {
    "description": "Principal components or a UMAP of a discovered population",
    "version": "1.0",
    "max_workers": 1,
    "environment": "ZMART--population--main",
}

#: The two plots there are, and the columns each lands as.
KINDS = {"pca": ("pc_1", "pc_2"), "umap": ("umap_1", "umap_2")}

#: Columns of the population table that are not measurements of the object.
NOT_MEASURED = {"field", "position_label", "id", "x_um", "y_um", "intensity", "r", "label"}
NOT_MEASURED_PREFIXES = ("bbox_", "centroid_", "weighted_centroid", "stage_", "bg_global_mean")


def run(pipeline_data: dict, state: dict, **params) -> dict:
    verbose = pipeline_data.get("metadata", {}).get("verbose", 0)
    inp = pipeline_data["input"]
    kind = inp.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {tuple(KINDS)}, got {kind!r}.")
    table = Path(inp["table"])
    enough_objects = int(params.get("enough_objects", 10))
    matrix, ids, features = _conditioned(
        _read_population(table, inp.get("ids")), float(params.get("enough_measured", 0.5)),
    )
    if len(ids) < enough_objects:
        raise ValueError(
            f"only {len(ids)} objects; a plot needs at least {enough_objects} "
            "to say anything about the population"
        )
    if not features:
        raise ValueError("no feature was measured widely enough to plot the objects on")
    seed = int(params.get("seed", 0))

    from sklearn.decomposition import PCA

    room = min(int(params.get("components", 50)), matrix.shape[0], matrix.shape[1])
    components = PCA(n_components=room, random_state=seed).fit_transform(matrix)
    if components.shape[1] < 2:
        components = np.hstack([components, np.zeros((components.shape[0], 1))])
    stem = table.name.removesuffix("_objects.csv")
    written = {"pca": _write(table.with_name(f"{stem}_pca.csv"), ids, KINDS["pca"], components[:, :2])}
    if kind == "umap":
        from umap import UMAP

        laid_out = UMAP(
            n_components=2, n_neighbors=min(int(params.get("neighbours", 15)), len(ids) - 1),
            min_dist=float(params.get("min_dist", 0.1)), random_state=seed,
        ).fit_transform(components)
        written["umap"] = _write(table.with_name(f"{stem}_umap.csv"), ids, KINDS["umap"], laid_out)
    if verbose:
        print(f"  [plot_population] {kind} over {len(ids)} objects, {len(features)} features")
    pipeline_data["plot_population"] = {
        "written": {key: str(path) for key, path in written.items()},
        "objects": len(ids),
        "features": features,
    }
    return pipeline_data


def _read_population(table: Path, ids):
    """The population table, narrowed to *ids* when given, in its own order."""
    import pandas as pd

    frame = pd.read_csv(table, dtype={"id": str, "position_label": str})
    if ids is not None:
        frame = frame[frame["id"].isin(set(map(str, ids)))]
    return frame.reset_index(drop=True)


def _measured(name: str) -> bool:
    return name not in NOT_MEASURED and not name.startswith(NOT_MEASURED_PREFIXES)


def _conditioned(frame, enough_measured: float) -> tuple[np.ndarray, list[str], list[str]]:
    """``(matrix, ids, features)``: one row an object in the table's order,
    one column a measurement worth keeping, each centred on its median and
    scaled by its interquartile spread."""
    ids = [str(one) for one in frame["id"]]
    columns, kept = [], []
    for name in sorted(name for name in frame.columns if _measured(name)):
        column = np.asarray(frame[name], dtype=np.float64)
        finite = np.isfinite(column)
        if not finite.size or finite.mean() < enough_measured:
            continue
        column = np.where(finite, column, np.median(column[finite]))
        middle = float(np.median(column))
        quarter, three_quarters = np.percentile(column, [25, 75])
        spread = float(three_quarters - quarter) or float(column.std())
        if spread == 0.0:
            continue  # the same number for every object says nothing
        columns.append((column - middle) / spread)
        kept.append(name)
    matrix = np.stack(columns, axis=1) if columns else np.empty((len(ids), 0))
    return matrix, ids, kept


def _write(path: Path, ids: list[str], columns: tuple[str, str], values: np.ndarray) -> Path:
    with path.open("w", encoding="utf-8", newline="") as out:
        rows = csv.writer(out)
        rows.writerow(["id", *columns])
        for an_id, (a, b) in zip(ids, values, strict=True):
            rows.writerow([an_id, float(a), float(b)])
    return path
