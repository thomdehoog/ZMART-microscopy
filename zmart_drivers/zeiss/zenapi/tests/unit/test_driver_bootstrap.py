"""The package imports cleanly with only its own roots on sys.path.

Guards against accidental dependence on being launched from a particular
directory, and confirms `import zenapi` works without the zen_api wheel
(everything vendor-specific is lazily imported).
"""

import subprocess
import sys
from pathlib import Path


def test_imports_with_minimal_syspath():
    here = Path(__file__).resolve()
    # parents: [0]=unit [1]=tests [2]=zenapi [3]=zeiss [4]=zmart_drivers [5]=repo root
    zeiss_dir = here.parents[3]  # .../zmart_drivers/zeiss  (so `import zenapi` resolves)
    repo_root = here.parents[5]  # .../smart-microscopy  (so `import shared` resolves)
    code = (
        "import sys;"
        f"sys.path.insert(0, r'{zeiss_dir}');"
        f"sys.path.insert(0, r'{repo_root}');"
        "import zenapi;"
        "assert hasattr(zenapi, 'connect');"
        "assert hasattr(zenapi, 'move_xy');"
        "assert hasattr(zenapi, 'acquire');"
        "print('import-ok')"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "import-ok" in result.stdout
