"""Helpers for workflow-specific interpretation of driver save manifests."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace


def require_single_plane(saved, *, context: str):
    """Return the only saved plane, or fail with an explicit policy error."""
    if len(saved.image_paths) != 1:
        raise RuntimeError(
            f"{context} produced {len(saved.image_paths)} saved planes; "
            "choose an explicit channel/z/time policy before analysis"
        )
    idx, path = next(iter(saved.image_paths.items()))
    return SimpleNamespace(
        image_path=path,
        naming=replace(saved.naming, t=idx.t, z=idx.z, c=idx.c),
    )
