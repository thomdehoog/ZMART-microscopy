"""Checks that installing the project actually installs the live machinery."""

from __future__ import annotations

import re
from pathlib import Path


def test_the_built_project_includes_zmart_live():
    """Source-tree imports can hide an omitted package in the wheel configuration."""
    repository = Path(__file__).resolve().parents[2]
    settings = (repository / "pyproject.toml").read_text(encoding="utf-8")
    named = re.search(r"^packages\s*=\s*\[(?P<names>[^]]*)]", settings, re.MULTILINE)
    assert named is not None
    assert '"zmart_live"' in named.group("names")
