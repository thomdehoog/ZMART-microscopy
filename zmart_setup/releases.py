"""Which versions of the five blocks to install, read from ``releases.toml``.

``releases.toml``, in the top folder of ZMART Microscopy, names the GitHub
account the blocks come from and, for each block, the release to install.
To try other versions before a release, ``--github`` and ``--ref`` change
them for one setup only; the file itself is changed at a release.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: The five blocks, by the name pip knows them, and their repository on GitHub.
BLOCKS = {
    "zmart-controller": "ZMART-controller",
    "zmart-viewer": "ZMART-viewer",
    "zmart-drivers": "ZMART-drivers",
    "zmart-analysis": "ZMART-analysis",
    "zmart-interface": "ZMART-interface",
}


@dataclass
class Releases:
    """The account the blocks come from, and the release (a tag or a branch) of each."""

    github: str
    refs: dict[str, str] = field(default_factory=dict)

    def address(self, block: str, extras: str = "") -> str:
        """The block as pip is asked for it: ``name[extras] @ git+https://github.com/<account>/<repo>@<ref>``."""
        name = f"{block}[{extras}]" if extras else block
        return f"{name} @ git+https://github.com/{self.github}/{BLOCKS[block]}@{self.refs[block]}"

    def version(self, block: str) -> str | None:
        """The version a release tag stands for (``v0.2.0rc1`` is ``0.2.0rc1``), or None for a branch."""
        ref = self.refs[block]
        return ref[1:] if re.fullmatch(r"v\d+(\.\d+)*([a-z]+\d+)?", ref) else None


def read(path: Path, github: str | None = None, refs: list[str] = ()) -> Releases:
    """The releases in ``path``, with ``github`` and ``refs`` (``block=ref``) laid over them.

    Raises ValueError, with a sentence saying what is wrong, for a block the
    file does not name or a ``--ref`` for something that is not a block.
    """
    written = _parse(path.read_text(encoding="utf-8"))
    releases = Releases(github or written.get("github", "ZMB-UZH"), dict(written.get("blocks", {})))
    missing = [block for block in BLOCKS if block not in releases.refs]
    if missing:
        raise ValueError(f"{path.name} names no release for {', '.join(missing)}")
    for one in refs:
        block, _, ref = one.partition("=")
        if block not in BLOCKS or not ref:
            raise ValueError(f"--ref {one}: give it as BLOCK=REF, with BLOCK one of {', '.join(BLOCKS)}")
        releases.refs[block] = ref
    return releases


def _parse(text: str) -> dict:
    """The small part of TOML that ``releases.toml`` uses: ``key = "value"`` lines, in sections.

    Python 3.11 reads TOML itself; the conda base environment that runs the
    setup may be older, so this reads the file in the same way either way.
    """
    out: dict = {}
    section = out
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        heading = re.fullmatch(r"\[([A-Za-z0-9_.-]+)\]", line)
        if heading:
            section = out.setdefault(heading[1], {})
            continue
        pair = re.fullmatch(r'([A-Za-z0-9_.-]+)\s*=\s*"([^"]*)"', line)
        if not pair:
            raise ValueError(f"releases.toml: cannot read the line {line!r}")
        section[pair[1]] = pair[2]
    return out
