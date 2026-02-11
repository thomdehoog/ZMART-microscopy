#!/usr/bin/env python3
"""
vendors/lasx/inspect.py — Leica LAS X experiment backend.

Implements the :class:`ExperimentBackend` interface defined in
``initialize_experiment.py`` for Leica LAS X microscopes.  All LAS X-specific
knowledge (file formats, API quirks, folder conventions) lives in this
package (``vendors/lasx/``).

Why this file exists
--------------------
LAS X stores experiment templates as a set of three files:

    * ``_ScanningTemplate.xml`` — tile positions, scan field data
    * ``_ScanningTemplate.lrp`` — hardware settings, job definitions
    * ``_ScanningTemplate.rgn`` — region geometries (optional)

This module knows how to find, parse, and enrich those files.  The generic
``initialize_experiment.py`` orchestrator calls into this backend without
knowing any of these details.

Dependencies (within this package)
-----------------------------------
    .parser               — XML/LRP/RGN parser
    .api_enrichment       — live API enrichment via microscope_connector
    .offline_enrichment   — OME-TIFF file-based enrichment
    .visualizer           — matplotlib tile layout visualiser

Dependencies (generic layer)
----------------------------
    initialize_experiment — ABC + registry
    microscope_connector  — API connector (used by resolve_input_auto)

Usage
-----
    # Preferred: via the generic entry point (auto-imports this package)
    from initialize_experiment import initialize_experiment
    data = initialize_experiment("lasx", input="auto")

    # Direct import also works
    from vendors.lasx.inspect import LasXExperimentBackend

Metadata
--------
    Author:  Adaptive Feedback Microscopy project
    Version: 1.0.0
    License: MIT
    Python:  >= 3.9
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from initialize_experiment import (
    ExperimentBackend,
    register_backend,
)


__all__ = ["LasXExperimentBackend"]

__version__ = "1.0.0"


# ━━━ LAS X Template file patterns ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Recognised globs for each file type, preferred patterns first.
_TEMPLATE_GLOBS = {
    "xml": ["*ScanningTemplate*.xml", "*.xml"],
    "lrp": ["*ScanningTemplate*.lrp", "*.lrp"],
    "rgn": ["*ScanningTemplate*.rgn", "*.rgn"],
}

# Auto-save placeholder name used by input="auto".
_AUTO_TEMPLATE_NAME = "{ScanningTemplate}_PythonInspect.xml"
_AUTO_TEMPLATE_BASE = "{ScanningTemplate}_PythonInspect"


# ━━━ Backend Implementation ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class LasXExperimentBackend(ExperimentBackend):
    """
    Leica LAS X inspection backend.

    Implements the full inspection pipeline for LAS X:
      1. resolve_input_auto — saves the current template via the LAS X API
      2. find_template_files — locates .xml, .lrp, .rgn files
      3. parse — delegates to ``.parser.parse_template``
      4. enrich_from_api — delegates to ``.api_enrichment``
      5. enrich_from_files — delegates to ``.offline_enrichment``
      6. visualize — delegates to ``.visualizer``
    """

    # Persistent temp folder -- reused across calls, files overwritten.
    _auto_temp_dir: Optional[Path] = None

    # ── Identity ──────────────────────────────────────────────────────────

    @property
    def backend_name(self) -> str:
        return "lasx"

    # ── Stage 1: Resolve input ────────────────────────────────────────────

    def resolve_input_auto(self, client: Any) -> Tuple[Optional[Path], Any]:
        """
        Save the currently loaded LAS X template via the API, copy the
        files to an isolated temp folder, and return the path.

        Uses a fixed placeholder template name that is overwritten on
        each call.  If the first save produces empty scan fields (LAS X
        has not computed positions yet), retries with a load-save cycle
        up to 4 times.

        Returns ``(folder, client)`` on success, ``(None, client)`` on
        failure.
        """
        # Get or create API connection
        if client is None:
            try:
                from microscope_connector import initialize_api
                with contextlib.redirect_stdout(io.StringIO()):
                    connector = initialize_api(
                        "lasx", timeout=10.0, auto_connect=True,
                    )
                client = connector.client
            except Exception as exc:
                print(f"  input=auto failed: {exc}")
                return None, None

        # Find the LAS X ScanningTemplates directory
        templates_dir = self._find_scanning_templates_dir()
        if templates_dir is None:
            print("  input=auto failed: Could not locate "
                  "ScanningTemplates folder.")
            print("  Expected: %APPDATA%\\Leica Microsystems\\LAS X"
                  "\\MatrixScreener6\\User_*\\ScanningTemplates")
            return None, client

        # Save and check (with load + retry if empty)
        try:
            if self._save_and_check(client, templates_dir):
                return self._auto_temp_dir, client

            for attempt in range(4):
                client.PyApiLoadExperiment.Model.ExperimentName = (
                    _AUTO_TEMPLATE_NAME
                )
                client.PyApiLoadExperiment.UpdateAsync()
                time.sleep(4.0 + attempt * 3.0)

                if self._save_and_check(client, templates_dir):
                    return self._auto_temp_dir, client

        except Exception as exc:
            print(f"  input=auto failed: {exc}")
            return None, client

        # Verify at least xml + lrp arrived
        if (self._auto_temp_dir
                and not (self._auto_temp_dir
                         / "_ScanningTemplate.lrp").is_file()):
            print("  input=auto failed: LRP file not found.")
            return None, client

        print("  Warning: API save produced empty <ScanFields /> "
              "after retries.")
        print("  LAS X has not computed tile positions yet.")
        print("  Try clicking on the Navigator view in LAS X, "
              "then re-run.")
        return None, client

    def find_template_files(
        self, folder: Path,
    ) -> Dict[str, Optional[Path]]:
        """
        Locate .xml, .lrp, and (optionally) .rgn template files in
        *folder*.

        Returns ``{"xml": Path, "lrp": Path, "rgn": Path | None}``.

        Raises :class:`FileNotFoundError` if .xml or .lrp are missing.
        """
        found: Dict[str, Optional[Path]] = {}
        for ext, patterns in _TEMPLATE_GLOBS.items():
            matches = []
            for pat in patterns:
                matches = sorted(folder.glob(pat))
                if matches:
                    break
            if ext in ("xml", "lrp") and not matches:
                raise FileNotFoundError(
                    f"No .{ext} template file found in {folder}\n"
                    f"  (tried: {', '.join(patterns)})"
                )
            found[ext] = matches[0] if matches else None

        return found

    # ── Stage 2: Parse ────────────────────────────────────────────────────

    def parse(self, files: Dict[str, Optional[Path]]) -> Dict[str, Any]:
        """
        Parse LAS X template files into the standardised data dict.

        Delegates to ``vendors.lasx.parser.parse_template()``.
        """
        from .parser import parse_template

        return parse_template(
            str(files["xml"]),
            str(files["lrp"]),
            str(files["rgn"]) if files.get("rgn") else None,
        )

    # ── Stage 3: Enrich ───────────────────────────────────────────────────

    def enrich_from_api(
        self,
        data: Dict[str, Any],
        client: Any,
        verbose: int,
    ) -> Dict[str, Any]:
        """
        Enrich parsed data from a live LAS X API connection.

        Supports both :class:`MicroscopeConnector` instances and raw
        Leica SDK client objects.
        """
        from .api_enrichment import enrich_with_api_data

        try:
            from microscope_connector import MicroscopeConnector
            is_connector = isinstance(client, MicroscopeConnector)
        except ImportError:
            is_connector = False

        if is_connector:
            return enrich_with_api_data(
                data, connector=client, verbose=(verbose >= 2),
            )
        else:
            return enrich_with_api_data(
                data, existing_client=client, verbose=(verbose >= 2),
            )

    def enrich_from_files(
        self,
        data: Dict[str, Any],
        template_dir: Path,
        experiment_root: Optional[Path],
        verbose: int,
    ) -> Dict[str, Any]:
        """
        Enrich parsed data from OME-TIFF image headers on disk.

        Delegates to ``vendors.lasx.offline_enrichment.enrich_offline()``.
        """
        from .offline_enrichment import enrich_offline

        return enrich_offline(
            data,
            template_dir=template_dir,
            experiment_root=experiment_root,
            verbose=(verbose >= 2),
        )

    # ── Stage 5: Visualise ────────────────────────────────────────────────

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
        Render the LAS X template as a matplotlib figure.

        Delegates to ``vendors.lasx.visualizer.visualize()``.
        """
        from .visualizer import visualize

        return visualize(
            data,
            output_path=output_path,
            figsize=figsize,
            dpi=dpi,
            show=show,
        )

    # ── Capability flags ──────────────────────────────────────────────────

    def supports_auto_input(self) -> bool:
        return True

    def supports_file_enrichment(self) -> bool:
        return True

    def can_probe_api(self) -> bool:
        """Try to reach the LAS X API without an existing client."""
        try:
            from microscope_connector import initialize_api
            with contextlib.redirect_stdout(io.StringIO()):
                connector = initialize_api(
                    "lasx", timeout=5.0, auto_connect=True,
                )
            connector.disconnect()
            return True
        except Exception:
            return False

    # ── Private helpers ───────────────────────────────────────────────────

    @staticmethod
    def _find_scanning_templates_dir() -> Optional[Path]:
        """
        Locate the LAS X ScanningTemplates folder via %APPDATA%.

        Returns the path, or ``None`` if not found.
        """
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        base = (Path(appdata) / "Leica Microsystems"
                / "LAS X" / "MatrixScreener6")
        if not base.is_dir():
            return None
        user_dirs = sorted(base.glob("User_*"))
        if not user_dirs:
            return None
        templates = user_dirs[0] / "ScanningTemplates"
        return templates if templates.is_dir() else None

    def _save_and_check(
        self, client: Any, templates_dir: Path,
    ) -> bool:
        """
        Save template via the API, copy to temp dir, return True if
        scan positions are present.
        """
        client.PyApiSaveExperiment.Model.ExperimentName = (
            _AUTO_TEMPLATE_NAME
        )
        client.PyApiSaveExperiment.UpdateAsync()
        time.sleep(0.5)

        expected_xml = templates_dir / _AUTO_TEMPLATE_NAME
        if not expected_xml.is_file():
            time.sleep(1.0)
        if not expected_xml.is_file():
            return False

        if self._auto_temp_dir is None:
            self.__class__._auto_temp_dir = Path(
                tempfile.mkdtemp(prefix="lasx_inspect_")
            )

        for ext in ("xml", "lrp", "rgn"):
            src = templates_dir / f"{_AUTO_TEMPLATE_BASE}.{ext}"
            dst = self._auto_temp_dir / f"_ScanningTemplate.{ext}"
            if src.is_file():
                shutil.copy2(src, dst)

        xml_file = self._auto_temp_dir / "_ScanningTemplate.xml"
        if not xml_file.is_file():
            return False

        xml_text = xml_file.read_text(errors="ignore")
        return "ScanFieldData" in xml_text


# ━━━ Self-register ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

register_backend("lasx", LasXExperimentBackend)
