"""Remove conda environments for the focus workflow."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "parts"))
from _env_setup import clean_workflow_envs  # noqa: E402


if __name__ == "__main__":
    clean_workflow_envs(workflow="focus")
