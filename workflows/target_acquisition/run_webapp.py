"""Launch the target-acquisition website from this directory."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for path in (REPO_ROOT, HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def main() -> None:
    """Import the website only after its package roots are available."""
    from workflow.webapp.__main__ import main as webapp_main

    webapp_main()


if __name__ == "__main__":
    main()
