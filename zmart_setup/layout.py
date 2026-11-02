"""Where everything the setup makes and uses is: the workflows, the two clones, the two environments.

ZMART Microscopy holds the target acquisition workflow in two halves,
``workflows/target_acquisition/for-non-coders`` (the operator window) and
``for-coders/template`` (a notebook to build from). The operator window's
steps live in the ZMART Interface's ``examples`` folder, and the analysis
pipelines it runs in ZMART Analysis's ``examples`` folder; both are cloned,
at the releases in ``releases.toml``, next to ZMART Microscopy.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
#: Where the clones go: next to ZMART Microscopy.
BESIDE = REPO.parent
WORKFLOW = REPO / "workflows" / "target_acquisition"
NON_CODERS = WORKFLOW / "for-non-coders"
CODERS = WORKFLOW / "for-coders" / "template"


@dataclass(frozen=True)
class Clone:
    """A repository cloned next to ZMART Microscopy, for the folder of workflows it holds."""

    block: str
    folder: Path
    workflows: Path


def clones(beside: Path | None = None) -> dict[str, Clone]:
    """The two clones: the interface's steps, and the analysis pipelines."""
    beside = beside or BESIDE
    return {
        "interface": Clone("zmart-interface", beside / "ZMART-interface", beside / "ZMART-interface" / "examples"),
        "analysis": Clone("zmart-analysis", beside / "ZMART-analysis", beside / "ZMART-analysis" / "examples"),
    }


@dataclass(frozen=True)
class Environment:
    """One of the two environments ZMART runs in: its name, its file, and the blocks it gets."""

    name: str
    file: Path
    blocks: tuple[str, ...]


#: The operator window's environment, for everyone.
OPERATOR = Environment("zmart-for-non-coders", NON_CODERS / "environment.yml",
                       ("zmart-controller", "zmart-viewer", "zmart-analysis", "zmart-interface"))

#: The notebook's environment, for people who write code.
CODER = Environment("zmart-for-coders", CODERS / "environment.yml",
                    ("zmart-controller", "zmart-analysis"))
