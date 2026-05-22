"""Import bootstrap only. Must never choose runtime write paths."""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _candidate in [_HERE, *_HERE.parents]:
    if (
        _candidate.name == "navigator_expert"
        and (_candidate / "__init__.py").is_file()
    ):
        _pkg_parent = _candidate.parent
        break
    if (_candidate / "navigator_expert" / "__init__.py").is_file():
        _pkg_parent = _candidate
        break
else:
    raise RuntimeError(
        "Could not locate the navigator_expert package by walking up "
        f"from {_HERE}. Ensure the notebook lives where _bootstrap.py "
        "can find the navigator_expert package, or use an editable "
        "install (pip install -e)."
    )

if str(_pkg_parent) not in sys.path:
    sys.path.insert(0, str(_pkg_parent))
