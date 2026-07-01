"""
Objective resolution.
======================
ZEN switches objectives by turret **position index** (an int). This maps a
human-friendly selector (index, name, or magnification) to that index using the
fitted-objectives list (``get_objectives``, cached on the client).

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations


def resolve_objective_index(client, *, index=None, name=None, magnification=None) -> int:
    """Resolve an objective selector to a turret position index.

    Exactly one of ``index`` / ``name`` / ``magnification`` should be given.
    ``index`` is returned directly; ``name``/``magnification`` are looked up in
    the fitted-objectives list.

    Raises:
        ValueError: nothing was provided, or no objective matched.
    """
    if index is not None:
        return int(index)

    from ..readers import get_objectives

    objectives = get_objectives(client)
    if name is not None:
        for obj in objectives:
            if obj["name"] == name:
                return obj["index"]
        raise ValueError(
            f"No objective named {name!r}. Available: {[o['name'] for o in objectives]}"
        )
    if magnification is not None:
        for obj in objectives:
            if obj["magnification"] == magnification:
                return obj["index"]
        raise ValueError(
            f"No objective with magnification {magnification!r}. "
            f"Available: {[o['magnification'] for o in objectives]}"
        )
    raise ValueError("set_objective requires one of: index, name, magnification")
