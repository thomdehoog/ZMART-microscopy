"""One map of every discovered cell: UMAP over the measured features.

The features the analysis measures are made for gating one pair at a time;
this folds all of them into two axes (``umap_1``, ``umap_2``) so the operator
can also gate on the population's own structure -- cells that are alike stand
together, whatever combination of columns makes them alike.

An embedding is a statement about the WHOLE population, so it cannot live in
the per-field pipeline the way the features do: two fields embedded apart
would land in two unrelated spaces. It runs once, here, over every discovered
cell, after discovery has answered.

What goes in is chosen, not everything numeric:

- identity and position stay out (``label``, ``bbox_*``, ``centroid_*``,
  ``stage_x_um``/``stage_y_um``) -- a map that clusters by where a cell sits
  on the slide is a picture of the scan pattern, not of the cells;
- ``bg_global_mean*`` stays out -- one scalar per field, so keeping it would
  embed the field a cell came from rather than the cell.

And what goes in is conditioned before the embedding sees it: per-column
median imputation for the odd non-finite value (a column mostly missing is
dropped instead), then robust scaling by median and IQR so a handful of
bright outliers cannot own an axis, then PCA down to at most 50 components
to shed noise, then UMAP with a pinned seed so the same population always
gets the same map.

Author: Thom de Hoog (ZMB, University of Zurich).
License: MIT
"""

from __future__ import annotations

import numpy as np

#: Columns that never enter the embedding: identity, position, and per-field
#: scalars. Matched by exact name or by prefix.
LEFT_OUT = ("label",)
LEFT_OUT_PREFIXES = ("bbox_", "centroid_", "stage_x_um", "stage_y_um", "bg_global_mean")

#: A column must have a finite value for at least this share of the cells;
#: below it, the median would be speaking for the imputation, not the data.
ENOUGH_MEASURED = 0.5

#: The fewest cells a map is worth drawing for. UMAP needs neighbours to
#: reason about, and a "map" of a handful of points is noise wearing axes.
ENOUGH_CELLS = 10


def wanted(name: str) -> bool:
    """Whether a feature column belongs in the embedding."""
    if name in LEFT_OUT:
        return False
    return not any(name.startswith(prefix) for prefix in LEFT_OUT_PREFIXES)


def feature_matrix(cells: list[dict]) -> tuple[np.ndarray, list[str], list[str]]:
    """The conditioned matrix the embedding runs on.

    Takes the cells as discovery reports them (each with a ``features`` dict
    and an ``id``), returns ``(matrix, ids, columns)``: one robustly scaled
    row per cell, in the cells' order. Selection, imputation, and scaling all
    happen here so they can be pinned by tests without umap installed.
    """
    ids = [str(cell["id"]) for cell in cells]
    names = sorted({
        name
        for cell in cells
        for name, value in (cell.get("features") or {}).items()
        if wanted(name) and isinstance(value, (int, float))
    })
    raw = np.full((len(cells), len(names)), np.nan, dtype=np.float64)
    for row, cell in enumerate(cells):
        features = cell.get("features") or {}
        for col, name in enumerate(names):
            value = features.get(name)
            if isinstance(value, (int, float)):
                raw[row, col] = float(value)

    kept: list[int] = []
    for col in range(len(names)):
        column = raw[:, col]
        finite = np.isfinite(column)
        if finite.mean() < ENOUGH_MEASURED:
            continue
        # The odd unmeasured value takes the column's median; a degenerate
        # object's NaN should cost it nothing, not banish the whole column.
        column[~finite] = float(np.median(column[finite]))
        middle = float(np.median(column))
        quarter, three_quarters = np.percentile(column, [25, 75])
        spread = float(three_quarters - quarter)
        if spread == 0.0:
            spread = float(column.std())
        if spread == 0.0:
            continue  # the same number for every cell says nothing
        raw[:, col] = (column - middle) / spread
        kept.append(col)

    return raw[:, kept], ids, [names[col] for col in kept]


def umap_embedding(cells: list[dict], *, random_state: int = 0) -> dict[str, list[float]]:
    """The map: each cell's id to its ``[umap_1, umap_2]``.

    Deterministic for a given population (the seed is pinned), and honest
    about a population too small or too featureless to map -- that raises
    with a sentence rather than answering with noise.
    """
    if len(cells) < ENOUGH_CELLS:
        raise RuntimeError(
            f"only {len(cells)} cells were discovered; a map needs at least "
            f"{ENOUGH_CELLS} to say anything about the population"
        )
    matrix, ids, columns = feature_matrix(cells)
    if not columns:
        raise RuntimeError(
            "no feature column was measured widely enough to map the cells on"
        )

    # Imported here, not at the top: umap (and the numba it compiles through)
    # is a heavy import, and the bridge must load on machines that only scan.
    from sklearn.decomposition import PCA
    from umap import UMAP

    reduced = matrix
    room = min(50, matrix.shape[0], matrix.shape[1])
    if matrix.shape[1] > room:
        reduced = PCA(n_components=room, random_state=random_state).fit_transform(matrix)

    laid_out = UMAP(
        n_components=2,
        n_neighbors=min(15, len(cells) - 1),
        min_dist=0.1,
        random_state=random_state,
    ).fit_transform(reduced)

    return {
        an_id: [float(point[0]), float(point[1])]
        for an_id, point in zip(ids, laid_out)
    }


def in_another_process(cells: list[dict]) -> dict[str, list[float]]:
    """The map, drawn where it cannot slow the bridge down.

    The bridge is one process with the picture server inside it, and the map
    is the one long computation the bridge itself would run: on the
    operator's PC it took 25 s on first use and 12 s warm for 4010 cells, and
    while it ran the picture server's answers went from 3 ms to 365 ms, past
    their one-second budget under the load of a real run. So the map is drawn
    in a process of its own and only the points come back. Each map pays
    umap's import and compile again; that is what "lands quietly" costs.
    """
    return apart(umap_embedding, cells)


def apart(work, *arguments):
    """Run *work* in a fresh process and hand back what it returned.

    A failure comes back as the same exception, so a caller reads the same
    sentence whether the work ran here or apart. The process is started
    afresh, never forked, because the bridge runs on Windows.
    """
    import multiprocessing

    with multiprocessing.get_context("spawn").Pool(1) as workers:
        return workers.apply(work, arguments)
