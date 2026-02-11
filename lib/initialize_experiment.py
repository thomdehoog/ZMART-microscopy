#!/usr/bin/env python3
"""
initialize_experiment.py — Manufacturer-agnostic experiment initialization.

Provides a generic interface for parsing, enriching, summarising, and
visualising microscope experiment templates.  Manufacturer-specific backends
(Leica LAS X, Zeiss ZEN, Nikon NIS, etc.) live in separate files and
register themselves via the backend registry — exactly the same pattern
used by ``microscope_connector.py``.

Why this file exists
--------------------
Different microscope vendors store experiment templates in completely
different file formats (Leica: XML+LRP+RGN, Zeiss: CZI experiment files,
Nikon: NIS protocol files).  This module defines the *pipeline stages* that
every experiment initialization must go through, and a factory function
that orchestrates them without knowing any vendor-specific details.

Architecture
------------
    ExperimentBackend            Abstract base class — defines pipeline stages.
    initialize_experiment()      Factory / orchestrator — runs the full pipeline.
    register_backend()           Registers a manufacturer-specific backend class.

Pipeline stages (each delegated to the backend)
-----------------------------------------------
    1. resolve input   — locate or retrieve template files
    2. parse           — extract jobs, positions, geometries, focus points
    3. enrich          — add pixel / tile sizes (from API or image files)
    4. summarise       — print a human-readable inspection report
    5. visualise       — render the template as a matplotlib figure

Usage
-----
    from initialize_experiment import initialize_experiment

    # Initialize a Leica LAS X experiment
    data = initialize_experiment("lasx", input="auto", verbose=1)

    # Explicit folder, offline enrichment, detailed report
    data = initialize_experiment("lasx", input="path/to/folder",
                                 enrich="files", verbose=2)

    # Data only, no figure or print
    data = initialize_experiment("lasx", input="path/to/folder", verbose=0)

Extending
---------
    To add a new manufacturer, create a file (e.g. ``zen_experiment.py``) that:
      1. Subclasses ``ExperimentBackend``
      2. Implements all abstract methods
      3. Calls ``register_backend("zen", ZenExperimentBackend)``

    See ``vendors/lasx/inspect.py`` for a reference implementation.

Metadata
--------
    Author:  Adaptive Feedback Microscopy project
    Version: 1.0.0
    License: MIT
    Python:  >= 3.9
"""

from __future__ import annotations

import json
import sys
import traceback
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type, Union


__all__ = [
    "ExperimentBackend",
    "initialize_experiment",
    "register_backend",
    "list_backends",
]

__version__ = "1.0.0"


# ━━━ Backend Registry ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_BACKEND_REGISTRY: Dict[str, Type[ExperimentBackend]] = {}


def register_backend(name: str, cls: Type[ExperimentBackend]) -> None:
    """
    Register a manufacturer-specific experiment backend.

    Parameters
    ----------
    name : str
        Short identifier (e.g. ``"lasx"``, ``"zen"``).
        Stored lowercase for case-insensitive lookup.
    cls : type
        A subclass of :class:`ExperimentBackend`.

    Raises
    ------
    TypeError
        If *cls* is not a subclass of :class:`ExperimentBackend`.
    """
    if not (isinstance(cls, type) and issubclass(cls, ExperimentBackend)):
        raise TypeError(
            f"Backend class must be a subclass of ExperimentBackend, "
            f"got {cls!r}"
        )
    _BACKEND_REGISTRY[name.lower()] = cls


def list_backends() -> List[str]:
    """Return the names of all registered experiment backends."""
    return sorted(_BACKEND_REGISTRY.keys())


# ━━━ Abstract Base Class ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ExperimentBackend(ABC):
    """
    Abstract base class for microscopy experiment backends.

    Defines the pipeline stages that every manufacturer-specific backend
    must implement.  The generic :func:`initialize_experiment` orchestrator
    calls these methods in order.

    Subclasses must implement all ``@abstractmethod`` methods.  The
    ``print_summary_*`` and ``supports_*`` methods have sensible defaults
    that can be overridden.
    """

    # ── Identity ──────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Short identifier for this backend (e.g. ``"lasx"``)."""
        ...

    # ── Stage 1: Resolve input ────────────────────────────────────────────

    @abstractmethod
    def resolve_input_auto(self, client: Any) -> Tuple[Optional[Path], Any]:
        """
        Handle ``input="auto"`` — retrieve the template from live software.

        Returns ``(folder_path, client)`` on success, or ``(None, client)``
        on failure.  The returned *client* may be newly created.
        """
        ...

    @abstractmethod
    def find_template_files(self, folder: Path) -> Dict[str, Optional[Path]]:
        """
        Locate vendor-specific template files in *folder*.

        Returns a dict mapping logical roles to paths, e.g.
        ``{"xml": Path, "lrp": Path, "rgn": Path | None}``.

        Raises :class:`FileNotFoundError` for missing required files.
        """
        ...

    # ── Stage 2: Parse ────────────────────────────────────────────────────

    @abstractmethod
    def parse(self, files: Dict[str, Optional[Path]]) -> Dict[str, Any]:
        """
        Parse template files into the standardised data dict.

        The returned dict must contain at minimum:
        ``acquisition_jobs``, ``acquisition_positions``,
        ``visualization_data``.
        """
        ...

    # ── Stage 3: Enrich ───────────────────────────────────────────────────

    @abstractmethod
    def enrich_from_api(
        self,
        data: Dict[str, Any],
        client: Any,
        verbose: int,
    ) -> Dict[str, Any]:
        """Enrich parsed data using a live API connection."""
        ...

    @abstractmethod
    def enrich_from_files(
        self,
        data: Dict[str, Any],
        template_dir: Path,
        experiment_root: Optional[Path],
        verbose: int,
    ) -> Dict[str, Any]:
        """Enrich parsed data from acquired image files on disk."""
        ...

    # ── Stage 4: Summarise ────────────────────────────────────────────────

    def print_summary_compact(self, data: Dict[str, Any]) -> None:
        """
        Print a one-line summary (verbose=1).

        Override in subclasses for backend-specific formatting.
        """
        groups = data.get("acquisition_positions", {})
        n_tiles = sum(len(g["positions"]) for g in groups.values())
        print(f"Groups: {len(groups)}  Positions: {n_tiles}")

    def print_summary_detailed(
        self,
        data: Dict[str, Any],
        enrich: str,
    ) -> None:
        """
        Print a comprehensive structured report (verbose=2).

        The default implementation produces a full inspection report
        working entirely from the standardised data dict.  Override in
        subclasses to add vendor-specific sections.
        """
        _default_detailed_report(data, enrich=enrich)

    # ── Stage 5: Visualise ────────────────────────────────────────────────

    @abstractmethod
    def visualize(
        self,
        data: Dict[str, Any],
        *,
        output_path: Optional[str] = None,
        figsize: Tuple[float, float] = (14, 10),
        dpi: int = 300,
        show: bool = True,
    ) -> Any:
        """
        Render the template as a matplotlib figure.

        Each backend provides its own visualiser because tile layout
        conventions and display preferences differ between manufacturers.
        """
        ...

    # ── Capability flags ──────────────────────────────────────────────────

    def supports_auto_input(self) -> bool:
        """Whether this backend can retrieve templates from live software."""
        return False

    def supports_file_enrichment(self) -> bool:
        """Whether this backend can enrich from acquired image files."""
        return True

    def can_probe_api(self) -> bool:
        """
        Try to reach the vendor API without an existing client.

        Used by ``enrich="auto"`` to decide if live enrichment is possible.
        Returns ``True`` if the API is reachable.
        """
        return False


# ━━━ Factory / Orchestrator ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def initialize_experiment(
    backend: str,
    input: Union[str, Path, None] = None,
    *,
    enrich: str = "auto",
    client: Any = None,
    experiment_root: Union[str, Path, None] = None,
    output_path: Union[str, Path, None] = None,
    show_focus_points: bool = True,
    show_geometries: bool = True,
    figsize: Tuple[float, float] = (14, 10),
    dpi: int = 300,
    verbose: int = 1,
) -> Optional[Dict[str, Any]]:
    """
    Initialize a microscopy experiment — single entry point.

    Orchestrates the full pipeline (resolve -> parse -> enrich -> summarise
    -> visualise) by delegating each stage to the registered backend.
    Contains **zero** vendor-specific code.

    Parameters
    ----------
    backend : str
        Name of the experiment backend (e.g. ``"lasx"``).
    input : str, Path, or None
        Template location.

        * ``"auto"`` — retrieve from live software (backend must support it).
        * ``None`` — open an interactive folder picker.
        * ``str`` / ``Path`` — explicit path to a folder with template files.

    enrich : {"auto", "api", "files", "none"}
        How to determine pixel / tile sizes.

        * ``"auto"`` — try ``"api"`` -> ``"files"`` -> ``"none"`` in order.
        * ``"api"`` — query a running microscope instance.
        * ``"files"`` — read from acquired image headers on disk.
        * ``"none"`` — skip enrichment (tile sizes may be ``None``).

    client : connector or vendor client, optional
        Existing API connection to reuse.  Type depends on the backend.
    experiment_root : path-like, optional
        Root of the experiment folder tree (for ``enrich="files"``).
        ``None`` auto-detects one level above the template folder.
    output_path : path-like, optional
        Save the figure as PNG and a JSON sidecar alongside it.
    show_focus_points : bool
        Draw focus-point crosshairs on the figure.
    show_geometries : bool
        Draw region geometry outlines on the figure.
    figsize : tuple of float
        Matplotlib figure size ``(width, height)`` in inches.
    dpi : int
        Resolution for the saved PNG.
    verbose : int
        Output detail level.

        * ``0`` — silent; returns data only (no print, no figure).
        * ``1`` — one-line summary + figure.
        * ``2`` — full structured report + figure.

    Returns
    -------
    dict or None
        The enriched data dict on success, ``None`` on error.

    Examples
    --------
    >>> data = initialize_experiment("lasx", input="auto")
    >>> data = initialize_experiment("lasx", input="path/to/folder",
    ...                              enrich="files", verbose=2)
    >>> data = initialize_experiment("lasx", input="path/to/folder", verbose=0)
    """
    # ── Look up backend ───────────────────────────────────────────────────
    key = backend.lower()
    if key not in _BACKEND_REGISTRY:
        _try_auto_import(key)
    if key not in _BACKEND_REGISTRY:
        available = ", ".join(list_backends()) or "(none)"
        raise ValueError(
            f"Unknown experiment backend: {backend!r}. "
            f"Registered: {available}. "
            f"Make sure the backend module is importable "
            f"(e.g. add it to your PYTHONPATH)."
        )

    be = _BACKEND_REGISTRY[key]()

    try:
        # ── Stage 1: Resolve input ────────────────────────────────────────
        folder: Optional[Path] = None

        if isinstance(input, str) and input.lower() == "auto":
            if not be.supports_auto_input():
                raise ValueError(
                    f"Backend {backend!r} does not support input='auto'."
                )
            folder, client = be.resolve_input_auto(client)
            if folder is None:
                return None
        elif input is None:
            folder = _choose_folder_interactive()
        else:
            folder = Path(input)
            if not folder.is_dir():
                raise NotADirectoryError(f"Not a directory: {folder}")

        files = be.find_template_files(folder)

        if verbose >= 1:
            print(f"Template folder: {folder}")
            for role, path in files.items():
                label = path.name if path else "(none)"
                print(f"  {role.upper()}: {label}")
            print()

        # ── Stage 2: Parse ────────────────────────────────────────────────
        data = be.parse(files)

        # ── Stage 3: Enrich ───────────────────────────────────────────────
        resolved_enrich = _resolve_enrich_mode(
            enrich, folder, client, experiment_root, be,
        )

        if resolved_enrich == "api":
            data = be.enrich_from_api(data, client, verbose)
        elif resolved_enrich == "files":
            exp_root = Path(experiment_root) if experiment_root else None
            data = be.enrich_from_files(data, folder, exp_root, verbose)

        # ── Stage 4: Summarise ────────────────────────────────────────────
        if verbose == 1:
            be.print_summary_compact(data)
        elif verbose >= 2:
            be.print_summary_detailed(data, enrich=resolved_enrich)

        # ── Stage 5: Visualise ────────────────────────────────────────────
        if verbose >= 1:
            viz_data = _prepare_viz_data(
                data,
                show_focus_points=show_focus_points,
                show_geometries=show_geometries,
            )

            save_png = str(output_path) if output_path else None
            be.visualize(
                viz_data,
                output_path=save_png,
                figsize=figsize,
                dpi=dpi,
                show=True,
            )

        # ── Save JSON sidecar ─────────────────────────────────────────────
        if output_path:
            json_path = Path(output_path).with_suffix(".json")
            with open(json_path, "w") as f:
                json.dump(data, f, indent=2)
            if verbose >= 1:
                print(f"\nJSON saved to {json_path}")

        return data

    # ── Error handling ────────────────────────────────────────────────────
    except FileNotFoundError as exc:
        _error("FileNotFoundError", exc,
               "Check that the folder contains the required template files.")
    except NotADirectoryError as exc:
        _error("NotADirectoryError", exc,
               "Verify 'input' points to an existing folder.")
    except ConnectionError as exc:
        _error("ConnectionError", exc,
               "Ensure the microscope software is running with the API "
               "server enabled, or switch to enrich='files'.")
    except RuntimeError as exc:
        _error("RuntimeError", exc,
               "If this is about qtpy, install it (`pip install qtpy`) "
               "or set 'input' to an explicit path instead of None.")
    except ValueError as exc:
        _error("ValueError", exc,
               "Accepted enrich modes: 'auto', 'files', 'api', 'none'.")
    except Exception as exc:
        _error(type(exc).__name__, exc, "Full traceback below:")
        traceback.print_exc()

    return None


# ━━━ Internal Helpers ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _try_auto_import(backend_key: str) -> None:
    """
    Attempt to import a vendor backend package by convention.

    Mapping: ``"lasx"`` -> ``vendors.lasx``, ``"zen"`` -> ``vendors.zen``.

    The vendor package's ``__init__.py`` is responsible for importing
    and registering all backends (connector, inspection, analysis, ...).
    """
    module_name = f"vendors.{backend_key}"
    try:
        __import__(module_name)
    except ImportError:
        pass


def _choose_folder_interactive() -> Path:
    """Open a Qt folder-picker dialog and return the selected path."""
    try:
        from qtpy.QtWidgets import QApplication, QFileDialog
    except ImportError:
        raise RuntimeError(
            "Interactive folder selection requires qtpy.\n"
            "Install it (`pip install qtpy`) or pass a path string instead."
        )

    app = QApplication.instance() or QApplication(sys.argv)
    folder = QFileDialog.getExistingDirectory(
        None, "Select template folder"
    )
    if not folder:
        raise SystemExit("No folder selected -- aborting.")
    return Path(folder)


def _resolve_enrich_mode(
    enrich: str,
    folder: Optional[Path],
    client: Any,
    experiment_root: Union[str, Path, None],
    be: ExperimentBackend,
) -> str:
    """
    Resolve ``enrich="auto"`` to a concrete mode.

    Fallback order:
      1. ``"api"``   — if a client is provided, or the backend can probe.
      2. ``"files"`` — if the experiment folder tree contains image files.
      3. ``"none"``  — last resort.

    Non-auto values are validated and returned as-is.
    """
    valid = {"auto", "api", "files", "none"}
    if enrich not in valid:
        raise ValueError(
            f"Unknown enrich mode {enrich!r}. Expected one of {valid}."
        )

    if enrich != "auto":
        return enrich

    # Auto: try API first
    if client is not None:
        return "api"

    if be.can_probe_api():
        return "api"

    # Auto: try files
    if folder is not None and be.supports_file_enrichment():
        root = Path(experiment_root) if experiment_root else folder.parent
        try:
            ome_files = list(root.rglob("*.ome.tif"))
            if ome_files:
                return "files"
        except Exception:
            pass

    # Auto: fallback to none
    print("  Note: No API connection and no acquired images found.")
    print("  Tile sizes will be unavailable. To resolve, either:")
    print("    - Run with the microscope software open (API enrichment)")
    print("    - Point to a folder with acquired images (file enrichment)")
    return "none"


def _prepare_viz_data(
    data: Dict[str, Any],
    *,
    show_focus_points: bool = True,
    show_geometries: bool = True,
) -> Dict[str, Any]:
    """
    Return a shallow copy of *data* with sections removed according to
    the visibility flags.  The original dict is never mutated.
    """
    viz = dict(data)

    if not show_focus_points:
        viz["focus_points"] = []
        viz["autofocus_points"] = []

    if not show_geometries:
        viz["geometries"] = {}

    return viz


# ━━━ Default Summary Report ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_LINE = "-" * 72


def _default_detailed_report(data: Dict[str, Any], *, enrich: str) -> None:
    """
    Print a comprehensive, structured inspection report.

    Works entirely from the standardised data dict — no vendor-specific
    knowledge.  Used as the default ``print_summary_detailed()``
    implementation; backends can override for vendor-specific sections.
    """
    jobs = data.get("acquisition_jobs", {})
    groups = data.get("acquisition_positions", {})
    fps = data.get("focus_points", [])
    afps = data.get("autofocus_points", [])
    geoms = data.get("geometries", {})
    matrix = data.get("matrix_settings", {})
    n_tiles = sum(len(g["positions"]) for g in groups.values())

    # ── Header ────────────────────────────────────────────────────────────
    print()
    print(_LINE)
    print("  MICROSCOPY TEMPLATE INSPECTION REPORT")
    print(_LINE)

    carrier = matrix.get("carrier", "n/a")
    print(f"  Carrier:      {carrier}")
    print(f"  Enrichment:   {enrich}")
    print(f"  Jobs:         {len(jobs)}")
    print(f"  Groups:       {len(groups)}")
    print(f"  Positions:    {n_tiles}")

    if fps or afps:
        print(f"  Focus pts:    {len(fps)} manual, {len(afps)} autofocus")

    if geoms:
        type_counts: Dict[str, int] = {}
        for g in geoms.values():
            t = g.get("type", "Unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
        parts = ", ".join(f"{n}x {t}" for t, n in type_counts.items())
        print(f"  Geometries:   {len(geoms)} ({parts})")

    # ── Jobs ──────────────────────────────────────────────────────────────
    print()
    print(_LINE)
    print("  ACQUISITION JOBS")
    print(_LINE)

    for jn, j in jobs.items():
        jid = j.get("id", "?")
        fmt = j.get("format", "n/a")
        obj = j.get("objective", {})
        obj_name = obj.get("name", "n/a")
        obj_mag = obj.get("magnification", "")
        obj_na = obj.get("na", "")
        obj_imm = obj.get("immersion", "")
        zoom = j.get("zoom", {})
        zoom_val = zoom.get("current", "n/a")
        speed = j.get("scanSpeed", {})
        speed_val = speed.get("value", "n/a")
        speed_unit = speed.get("unit", "")
        resonant = speed.get("isResonant", False)
        seq_mode = j.get("sequentialMode", "n/a")
        af = j.get("autoFocus", {}).get("isActive", False)
        n_steps = len(j.get("activeSettings", []))

        px = j.get("pixelSize_um")
        ts = j.get("tileSize_um")
        im = j.get("imageSize_um")

        px_str = f"{px['x']:.4f} x {px['y']:.4f} um" if px else "n/a"
        ts_str = f"{ts:.2f} um" if ts else "n/a"
        im_str = f"{im['x']:.1f} x {im['y']:.1f} um" if im else "n/a"
        obj_str = obj_name
        if obj_mag:
            obj_str += f" {obj_mag}x"
        if obj_na:
            obj_str += f" NA {obj_na}"
        if obj_imm:
            obj_str += f" ({obj_imm})"
        speed_str = f"{speed_val} {speed_unit}".strip()
        if resonant:
            speed_str += " [resonant]"

        print()
        if isinstance(jid, int):
            print(f"  {jn}  (J{jid:02d})")
        else:
            print(f"  {jn}  (id={jid})")
        print(f"    Format:       {fmt}")
        print(f"    Pixel size:   {px_str}")
        print(f"    Tile size:    {ts_str}")
        print(f"    Image size:   {im_str}")
        print(f"    Objective:    {obj_str}")
        print(f"    Zoom:         {zoom_val}")
        print(f"    Scan speed:   {speed_str}")
        print(f"    Seq. mode:    {seq_mode}  ({n_steps} step(s))")
        print(f"    AutoFocus:    {'on' if af else 'off'}")

    # ── Position groups ───────────────────────────────────────────────────
    print()
    print(_LINE)
    print("  POSITION GROUPS")
    print(_LINE)

    job_id_lookup = {jn: j.get("id", "?") for jn, j in jobs.items()}

    for gid, g in groups.items():
        jn = g.get("job_name", "?")
        jid = job_id_lookup.get(jn, "?")
        nr = g.get("num_rows", 0)
        nc = g.get("num_cols", 0)
        nt = g.get("num_tiles", 0)
        ts = g.get("tile_size_um")
        ts_str = f"{ts:.2f} um" if ts else "n/a"

        print()
        print(f"  Group {gid}  |  {jn} (id={jid})  "
              f"|  {nr}x{nc} = {nt} tiles  |  tile: {ts_str}")

        bb = g.get("group_bounding_box")
        if bb:
            w = bb["x_max_um"] - bb["x_min_um"]
            h = bb["y_max_um"] - bb["y_min_um"]
            print(f"    Bounding box: {w:.1f} x {h:.1f} um  "
                  f"x=[{bb['x_min_um']:.1f} .. {bb['x_max_um']:.1f}]  "
                  f"y=[{bb['y_min_um']:.1f} .. {bb['y_max_um']:.1f}]")

        geom_id = g.get("geometry_id")
        if geom_id:
            geom = geoms.get(geom_id, {})
            print(f"    Geometry:     {geom.get('type', '?')} (id={geom_id})")

        g_fps = g.get("focus_points", [])
        g_afps = g.get("autofocus_points", [])
        if g_fps or g_afps:
            print(f"    Focus pts:    {len(g_fps)} manual, "
                  f"{len(g_afps)} autofocus")

    # ── Footer ────────────────────────────────────────────────────────────
    viz = data.get("visualization_data", {})
    job_ts = viz.get("job_tile_sizes", {})
    missing = [jn for jn in jobs if jn not in job_ts or job_ts[jn] is None]
    if missing:
        print()
        print(f"  NOTE: Tile size unknown for: {', '.join(missing)}")
        print("  Run with enrich='api' or enrich='files' to resolve.")

    print()
    print(_LINE)
    print()


def _error(label: str, exc: Exception, hint: str) -> None:
    """Print a formatted, actionable error message."""
    print(f"[{label}] {exc}")
    print(f"  -> {hint}")


# ━━━ CLI ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


if __name__ == "__main__":
    print("Experiment Initialization Framework")
    print("=" * 50)
    print(f"Version: {__version__}")
    backends = list_backends() or "(none -- import a backend first)"
    print(f"Registered backends: {backends}")
    print()
    print("Usage:")
    print("  from initialize_experiment import initialize_experiment")
    print('  data = initialize_experiment("lasx", input="auto")')
    print()
    print("Available vendor packages (import to register):")
    print("  vendors.lasx   — Leica LAS X       (lib/vendors/lasx/)")
    print("  (more to come) — Zeiss ZEN, Nikon NIS-Elements, ...")
