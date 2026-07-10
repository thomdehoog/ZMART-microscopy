"""Acquire a chosen number of gated targets and review them as image pairs.

The last interactive step: the operator types how many targets to acquire
and presses **Acquire**. That many cells are drawn *at random* from the
gate (random, so the acquired set is a fair sample of the gated population
rather than, say, the first tile's cells), the microscope re-images each
one at the target job, and the results appear underneath as a gallery —
one row per cell, showing:

- **left**: the cell as the overview saw it (low magnification), cropped
  to exactly the target job's field of view;
- **right**: the freshly acquired target image (high magnification).

Both panels are drawn in micrometres over the *same physical window*, so a
cell appears at the same size on both sides — what changes between the
panels is the detail, which is precisely what the pair is for: checking
that the high-magnification shot really captured the cell that was picked.

Interaction needs an interactive matplotlib backend (``%matplotlib
widget`` in JupyterLab). Everything is also scriptable —
:meth:`AcquisitionGallery.acquire` takes the count directly, which is how
the offline tests (and a static backend) drive it.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

from ._records import record_channel_paths
from .steps import acquire_targets


class AcquisitionGallery:
    """Pick N gated targets at random, acquire them, and show the pairs.

    ``source`` is a :class:`~._discovery_widget.TargetExplorer` (its current
    gate is sampled at the moment Acquire is pressed) or a plain list of
    targets. ``overviews`` is the discovery input list (for the left-hand
    overview crops). ``state`` / ``focus`` / ``options`` are passed to the
    acquisition exactly as in :func:`~.steps.acquire_targets`.

    ``after_acquire`` (optional) is called with the fresh records before the
    gallery is drawn — the notebook uses it for the simulation-mode image
    hijack, so simulated runs review the mock images they actually produced.

    ``seed`` fixes the random pick for a reproducible session (and for the
    tests); by default every press draws a fresh sample.
    """

    def __init__(
        self,
        session: Any,
        source: Any,
        overviews: list[dict] | None = None,
        *,
        state: dict | None = None,
        focus: Any = None,
        options: dict | None = None,
        after_acquire: Callable[[list[dict]], Any] | None = None,
        default_count: int = 5,
        seed: int | None = None,
    ) -> None:
        import matplotlib.pyplot as plt
        from matplotlib.widgets import Button, TextBox

        self.session = session
        self.source = source
        self.overviews = {i: o for i, o in enumerate(overviews or [])}
        self.state = state
        self.focus = focus
        self.options = options
        self.after_acquire = after_acquire
        self._rng = random.Random(seed)
        self._busy = False

        #: Set by :meth:`acquire`: the sampled targets and the driver records.
        self.picked: list[dict] = []
        self.records: list[dict] = []

        self.fig = plt.figure(figsize=(9, 7))
        self._count_ax = self.fig.add_axes([0.18, 0.92, 0.14, 0.05])
        self._count_box = TextBox(
            self._count_ax, "how many ", initial=str(int(default_count))
        )
        self._button_ax = self.fig.add_axes([0.36, 0.92, 0.22, 0.05])
        self._button = Button(self._button_ax, "Acquire")
        self._button.on_clicked(self._on_acquire_clicked)
        self._status = self.fig.text(
            0.62, 0.945, f"{len(self._gated())} target(s) in the gate", fontsize=9
        )
        self._gallery_axes: list[Any] = []

    # --- acquiring ------------------------------------------------------------

    def _gated(self) -> list[dict]:
        gated = getattr(self.source, "gated", self.source)
        return list(gated)

    def acquire(self, count: int) -> list[dict]:
        """Randomly pick ``count`` gated targets, acquire them, draw the gallery.

        Returns the driver records (also kept as ``self.records``, with the
        sampled targets in ``self.picked``, in the same order). Asking for
        more targets than the gate holds acquires the whole gate.
        """
        gated = self._gated()
        if not gated:
            raise RuntimeError(
                "the gate is empty — widen the sliders (or clear the lasso) in "
                "the target explorer before acquiring."
            )
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError("target count must be a positive whole number")
        if self._busy:
            raise RuntimeError("an acquisition is already running")
        picked = (
            self._rng.sample(gated, count) if count < len(gated) else list(gated)
        )
        self._busy = True
        self._status.set_text(f"acquiring {len(picked)} target(s)...")
        self.fig.canvas.draw_idle()
        try:
            records = acquire_targets(
                self.session,
                picked,
                state=self.state,
                focus=self.focus,
                options=self.options,
            )
            if self.after_acquire is not None:
                self.after_acquire(records)
        except Exception:
            self._status.set_text("acquisition failed; no result set was committed")
            self.fig.canvas.draw_idle()
            raise
        finally:
            self._busy = False
        self.picked = picked
        self.records = records
        self._draw_gallery()
        return records

    def _on_acquire_clicked(self, _event: Any) -> None:
        # A widget callback swallows tracebacks in most notebook frontends,
        # so problems are shown on the figure where the operator is looking.
        try:
            text = self._count_box.text.strip()
            if not text.isdecimal():
                raise ValueError("target count must be a positive whole number")
            count = int(text)
            self.acquire(count)
        except Exception as exc:  # noqa: BLE001 -- shown to the operator, not lost
            self._status.set_text(f"acquire failed: {exc}")
            self.fig.canvas.draw_idle()

    # --- the gallery ------------------------------------------------------------

    def _draw_gallery(self) -> None:
        for ax in self._gallery_axes:
            ax.remove()
        self._gallery_axes = []

        rows = len(self.picked)
        self.fig.set_size_inches(9, max(7.0, 1.9 * rows + 1.5), forward=True)
        top, bottom = 0.88, 0.04
        row_height = (top - bottom) / rows
        height = row_height * 0.88
        for row, (target, record) in enumerate(
            zip(self.picked, self.records, strict=True)
        ):
            y0 = top - (row + 1) * row_height + row_height * 0.06
            ax_low = self.fig.add_axes([0.07, y0, 0.40, height])
            ax_high = self.fig.add_axes([0.53, y0, 0.40, height])
            self._gallery_axes += [ax_low, ax_high]
            self._draw_pair(ax_low, ax_high, target, record)

        self._status.set_text(
            f"acquired {len(self.records)} of {len(self._gated())} gated target(s)"
        )
        self.fig.canvas.draw_idle()

    def _draw_pair(self, ax_low: Any, ax_high: Any, target: dict, record: dict) -> None:
        """One gallery row: overview crop (left) and target image (right).

        Both panels span the same physical window (the target job's field of
        view, in micrometres, centred on the cell), so the two images sit at
        the same scale and differ only in detail.
        """
        for ax in (ax_low, ax_high):
            ax.set_axis_off()

        pair = self._pair_images(target, record)
        if pair is None:
            ax_low.text(0.5, 0.5, "no image in this record", ha="center", fontsize=8)
            return
        low, high, width_um, height_um = pair
        half_w, half_h = width_um / 2.0, height_um / 2.0
        extent = (-half_w, half_w, half_h, -half_h)
        ax_low.imshow(low, cmap="gray", extent=extent, interpolation="nearest")
        ax_high.imshow(high, cmap="gray", extent=extent, interpolation="nearest")
        source = target.get("source") or {}
        ax_low.set_title(
            f"overview crop — tile {source.get('naming_p', '?')} "
            f"({width_um:.0f} × {height_um:.0f} um)",
            fontsize=8,
        )
        ax_high.set_title(
            f"target {record.get('position_label', '?')} — same window", fontsize=8
        )

    def _pair_images(self, target: dict, record: dict):
        """The (overview crop, target image, width_um, height_um) for one row.

        Returns ``None`` when the record carries no image (the controller's
        mock driver, for instance) — the row then says so instead of failing
        the whole gallery.
        """
        from ._geom import crop_overview_at_target_fov
        from ._overview_widget import _load_channels
        from .discovery import read_overview_geometry

        images = record_channel_paths(record, context="target record", allow_empty=True)
        if not images:
            return None
        high = _load_channels(images[0])[0]
        geometry = read_overview_geometry(images[0])
        target_pixel_size = float(geometry["pixel_size_um"])
        target_shape = geometry["image_size_px"]
        width_um = target_shape[1] * target_pixel_size
        height_um = target_shape[0] * target_pixel_size

        source = target.get("source") or {}
        overview = self.overviews.get(source.get("naming_p"))
        centroid = source.get("centroid_col_row_px")
        if overview is None or centroid is None:
            # No overview to crop from; show the target beside a blank panel
            # rather than refusing the row.
            import numpy as np

            low = np.zeros((2, 2), dtype=high.dtype)
        else:
            low = crop_overview_at_target_fov(
                _load_channels(overview["image_path"])[0],
                centroid_col_row_px=tuple(centroid),
                source_pixel_size_um=float(overview["pixel_size_um"]),
                target_shape_px=target_shape,
                target_pixel_size_um=target_pixel_size,
            )
        return low, high, width_um, height_um


def acquire_gallery(
    session: Any,
    source: Any,
    overviews: list[dict] | None = None,
    *,
    state: dict | None = None,
    focus: Any = None,
    options: dict | None = None,
    after_acquire: Callable[[list[dict]], Any] | None = None,
    default_count: int = 5,
    seed: int | None = None,
) -> AcquisitionGallery:
    """Open the acquire-and-review widget; returns the :class:`AcquisitionGallery`.

    Type a count, press **Acquire**: that many targets are randomly drawn
    from ``source`` (a :class:`~._discovery_widget.TargetExplorer`'s gate,
    or a plain target list), acquired at the target job, and shown as
    same-scale overview/target image pairs. ``after_acquire`` runs on the
    fresh records before the gallery draws (the simulation hijack goes
    here). The records live on ``gallery.records`` for the run summary.
    """
    return AcquisitionGallery(
        session,
        source,
        overviews,
        state=state,
        focus=focus,
        options=options,
        after_acquire=after_acquire,
        default_count=default_count,
        seed=seed,
    )
