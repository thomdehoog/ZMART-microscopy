"""
Step METADATA extraction via AST parsing.

Reads a step file's METADATA dict without executing any code. Used by the
engine at register() time to determine execution requirements for each step.

The engine never imports or executes step files. All step execution happens
in worker subprocesses running in the correct conda environment.
"""

import ast
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def get_step_settings(step_path: Path) -> dict:
    """
    Extract execution settings from a step file without running it.

    Parses the file's AST to read the METADATA dict literal.
    No module code is executed.

    Returns
    -------
    dict
        - environment : str or None
            Conda environment name. None means orchestrator's environment.
        - max_workers : int
            Maximum parallel workers for this step. Default 1.
    """
    metadata = _extract_metadata(step_path) or {}
    settings = {
        "environment": metadata.get("environment", None),
        "max_workers": metadata.get("max_workers", 1),
    }
    logger.debug("Step settings for %s: environment=%s, max_workers=%d",
                 step_path.name, settings["environment"],
                 settings["max_workers"])
    return settings


def _extract_metadata(step_path: Path) -> dict:
    """Extract the METADATA dict literal from a step file via AST."""
    with open(step_path) as f:
        tree = ast.parse(f.read())

    for node in ast.iter_child_nodes(tree):
        if (isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "METADATA"):
            result = ast.literal_eval(node.value)
            logger.debug("Extracted METADATA from %s (line %d): %s",
                         step_path.name, node.lineno, result)
            return result

    logger.debug("No METADATA found in %s, using defaults", step_path.name)
    return {}
